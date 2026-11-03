"""Glue between portal data, weather, recorder history and the empirical model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import logging

import numpy as np

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from . import model
from .api import ServiceData
from .weather import Weather

_LOGGER = logging.getLogger(__name__)


@dataclass
class MonthResult:
    month: str
    kwh: float  # actual (Techem) or estimate
    actual: bool
    method: str  # valves / weather / even / estimate
    hourly: np.ndarray  # kWh per hour (elapsed hours only for estimates)
    start: int  # first hour, epoch seconds UTC


@dataclass
class Analysis:
    fit: model.Fit | None = None
    factor: model.Factor = field(default_factory=lambda: model.Factor(1.0))
    month: str = ""
    so_far: float | None = None  # current month, estimate until now
    forecast: float | None = None  # current month, whole-month estimate
    forecast_from_forecast_h: int = 0  # hours of the month covered by the weather forecast
    forecast_from_climate_h: int = 0  # hours beyond the forecast, filled from past years
    last_month: str | None = None
    last_month_ratio: float | None = None  # actual / weather model
    months: list[MonthResult] = field(default_factory=list)
    signature: dict[str, str] = field(default_factory=dict)


def _month_key(ts: int, tz) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%Y-%m")


def temperature_partner(hass: HomeAssistant, valve: str) -> str | None:
    """The temperature sensor on the same device as a valve (e.g. the Eve Thermo's own)."""
    reg = er.async_get(hass)
    ent = reg.async_get(valve)
    if not ent or not ent.device_id:
        return None
    for other in er.async_entries_for_device(reg, ent.device_id):
        if other.domain == "sensor" and (other.device_class or other.original_device_class) == "temperature":
            return other.entity_id
    return None


async def _hourly_means(hass: HomeAssistant, ids: list[str], start: datetime, end: datetime) -> dict[str, dict[int, float]]:
    if not ids:
        return {}
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, start, end, set(ids), "hour", None, {"mean"}
    )
    return {
        sid: {int(r["start"]): r["mean"] for r in rows if r.get("mean") is not None}
        for sid, rows in stats.items()
    }


async def analyse(hass: HomeAssistant, svc: ServiceData, weather: Weather | None, valves: list[str]) -> Analysis:
    tz = dt_util.get_default_time_zone()
    kwh = {r["period"]: float(r["amount"]) for r in svc.rows if r["unitOfMeasure"] == "KWH"}
    if not kwh:
        return Analysis()
    now = dt_util.now()
    first = datetime.strptime(min(kwh), "%Y-%m").replace(tzinfo=tz)
    nxt = (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) + timedelta(days=32)).replace(day=1)
    t0, t1 = int(first.astimezone(UTC).timestamp()), int(nxt.astimezone(UTC).timestamp())
    hours = np.arange(t0, t1, 3600)
    month = np.array([_month_key(int(h), tz) for h in hours])
    now_ts = now.timestamp()
    elapsed = hours < now_ts

    T = np.full(len(hours), np.nan)
    S = np.full(len(hours), np.nan)
    if weather:
        await weather.async_update(first)
        for i, h in enumerate(hours):
            if v := weather.get(int(h)):
                T[i], S[i] = v

    res = Analysis(month=now.strftime("%Y-%m"))
    res.fit = model.fit(month, T, S, kwh) if weather else None
    weather_w = model.hourly_model(np.nan_to_num(T, nan=99), np.nan_to_num(S), res.fit) if res.fit else np.full(len(hours), np.nan)
    weather_w[np.isnan(T)] = np.nan
    if res.fit:
        res.factor = model.factor(month, np.nan_to_num(weather_w), kwh)
        last = max(kwh)
        exp = float(np.nansum(weather_w[month == last]))
        res.last_month, res.last_month_ratio = last, (round(kwh[last] / exp, 3) if exp >= 50 else None)

    # Valve weighting from long-term statistics (hourly means)
    valve_w = None
    if valves:
        partners = {v: temperature_partner(hass, v) for v in valves}
        means = await _hourly_means(hass, valves + [p for p in partners.values() if p], first, nxt)
        if any(means.get(v) for v in valves):
            def series(sid):
                m = means.get(sid or "", {})
                return np.array([m.get(int(h), np.nan) for h in hours])
            t_out = np.where(np.isnan(T), 10.0, T)
            valve_w = model.valve_weights(t_out, [series(v) for v in valves], [series(partners[v]) for v in valves])
            missing = np.zeros(len(hours), bool)
            for v in valves:
                missing |= np.isnan(series(v))
            valve_w[missing] = np.nan

    # Per month: distribute actuals; estimate months Techem hasn't delivered yet
    for m in sorted(set(month)):
        idx = np.where(month == m)[0]
        if m in kwh:
            hourly, method = model.distribute(kwh[m], idx, weather_w, valve_w)
            res.months.append(MonthResult(m, kwh[m], True, method, hourly, int(hours[idx[0]])))
            continue
        if not res.fit:
            continue
        done = idx[elapsed[idx]]
        est = res.factor.value * np.nan_to_num(weather_w[done])
        if valve_w is not None and len(done) and np.mean(~np.isnan(valve_w[done])) >= model.VALVE_COVERAGE:
            hourly, _ = model.distribute(float(est.sum()), done, weather_w, valve_w)
        else:
            hourly = est
        if len(done):
            res.months.append(MonthResult(m, float(hourly.sum()), False, "estimate", hourly, int(hours[done[0]])))
        if m == res.month:
            res.so_far = round(float(est.sum()), 1)
            ahead = idx[~elapsed[idx]]
            have = ahead[~np.isnan(weather_w[ahead])]
            gap = ahead[np.isnan(weather_w[ahead])]
            future = float(weather_w[have].sum())
            if len(gap):  # beyond the 16-day forecast: same calendar month in past years, per hour
                same = np.array([mm[5:] == m[5:] and mm < m for mm in month])
                past = weather_w[same & ~np.isnan(weather_w)]
                future += float(past.mean()) * len(gap) if len(past) else 0.0
            res.forecast = round(res.so_far + res.factor.value * future, 1)
            res.forecast_from_forecast_h, res.forecast_from_climate_h = len(have), len(gap)

    for mr in res.months:
        res.signature[mr.month] = hashlib.md5(np.round(mr.hourly, 4).tobytes()).hexdigest()
    return res
