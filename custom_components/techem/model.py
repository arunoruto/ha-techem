"""Empirical heating model: monthly Techem totals vs weather, plus hourly distribution.

Pure numpy, no Home Assistant imports, so it can be tested on its own.
See README "How the model works" for the equations.

Conventions: hourly arrays are aligned to UTC hours; `month[i]` is the local
calendar month ("YYYY-MM") that hour i belongs to.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

BASES = np.arange(14.0, 24.01, 0.5)  # candidate balance temperatures, °C
SUMMER_KWH = 50.0  # months the model expects to need less than this: spread evenly
FACTOR_MONTHS = 3  # recent heating months used for the behaviour factor
FACTOR_WINDOW = 4  # ... within this many months of the newest one (no bleed across summer)
FACTOR_PRIOR_KWH = 100.0  # shrinks the factor towards 1 when there is little data
FACTOR_MIN_KWH = 100.0  # only months with real heating (actual and expected) count
# Radiator physics for the valve weighting
FLOW_SLOPE = 1.17  # heating curve: T_flow = 20 + slope * (20 - T_out) ...
FLOW_MIN, FLOW_MAX = 25.0, 70.0  # ... clipped to this range
RADIATOR_EXPONENT = 1.3  # EN 442 radiator exponent
VALVE_COVERAGE = 0.8  # share of a month's hours with valve data needed to use it


@dataclass
class Fit:
    base: float  # balance temperature T_b, °C
    a_hdd: float  # kWh per degree day
    a_sun: float  # kWh per kWh/m² of sun during heating hours (negative: solar gain)
    r2: float
    rmse_loo: float  # leave-one-out RMSE, kWh/month
    months: int


@dataclass
class Factor:
    value: float
    months: list[str] = field(default_factory=list)
    actual: float = 0.0
    model: float = 0.0


def monthly_features(month: np.ndarray, T: np.ndarray, S: np.ndarray, months: list[str], base: float) -> np.ndarray:
    """[degree days, kWh/m² sun while heating] per month."""
    out = np.zeros((len(months), 2))
    for i, m in enumerate(months):
        k = month == m
        d = np.clip(base - T[k], 0, None)
        out[i] = d.sum() / 24, S[k][d > 0].sum() / 1000
    return out


def fit(month: np.ndarray, T: np.ndarray, S: np.ndarray, kwh: dict[str, float]) -> Fit | None:
    """Least squares kWh = a_hdd*HDD + a_sun*SUN through the origin; base by best LOO error."""
    have = set(month[~np.isnan(T)])
    months = sorted(m for m in kwh if m in have)  # summer zeros anchor the fit too
    if len(months) < 4:
        return None
    y = np.array([kwh[m] for m in months])
    best = None
    for base in BASES:
        X = monthly_features(month, T, S, months, base)
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        pred = X @ coef
        r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
        loo = []
        for i in range(len(y)):
            keep = np.arange(len(y)) != i
            c, *_ = np.linalg.lstsq(X[keep], y[keep], rcond=None)
            loo.append(y[i] - X[i] @ c)
        rmse = float(np.sqrt(np.mean(np.square(loo))))
        if best is None or rmse < best.rmse_loo:
            best = Fit(float(base), float(coef[0]), float(coef[1]), float(r2), rmse, len(months))
    return best


def hourly_model(T: np.ndarray, S: np.ndarray, f: Fit) -> np.ndarray:
    """Expected kWh per hour from weather alone (before the behaviour factor)."""
    d = np.clip(f.base - T, 0, None)
    return np.clip(f.a_hdd * d / 24 + f.a_sun * (S / 1000) * (d > 0), 0, None)


def factor(month: np.ndarray, expected: np.ndarray, kwh: dict[str, float]) -> Factor:
    """Behaviour factor = actual / weather model over the last heating months, shrunk towards 1."""
    rows = []
    newest = max(kwh) if kwh else "0000-00"
    ny, nm = map(int, newest.split("-"))
    for m in sorted(kwh, reverse=True):
        y, mo = map(int, m.split("-"))
        if (ny - y) * 12 + nm - mo >= FACTOR_WINDOW:
            break
        exp = float(expected[month == m].sum())
        if exp >= FACTOR_MIN_KWH and kwh[m] >= FACTOR_MIN_KWH / 2:
            rows.append((m, kwh[m], exp))
        if len(rows) == FACTOR_MONTHS:
            break
    if not rows:
        return Factor(1.0)
    act, mod = sum(r[1] for r in rows), sum(r[2] for r in rows)
    value = (act + FACTOR_PRIOR_KWH) / (mod + FACTOR_PRIOR_KWH)
    return Factor(round(value, 3), [r[0] for r in rows], round(act, 1), round(mod, 1))


def valve_weights(T_out: np.ndarray, valves: list[np.ndarray], rooms: list[np.ndarray]) -> np.ndarray:
    """Σ valve% × (T_flow − T_room)^1.3; NaN where any valve has no data."""
    t_flow = np.clip(20 + FLOW_SLOPE * (20 - T_out), FLOW_MIN, FLOW_MAX)
    w = np.zeros_like(T_out)
    for v, tr in zip(valves, rooms):
        dt = np.clip(t_flow - np.where(np.isnan(tr), 20.0, tr), 0, None)
        w = w + v / 100 * dt**RADIATOR_EXPONENT
    return w


def distribute(total: float, idx: np.ndarray, weather_w: np.ndarray, valve_w: np.ndarray | None) -> tuple[np.ndarray, str]:
    """Split a month total over its hours `idx`; returns (kWh per hour, method)."""
    n = len(idx)
    if valve_w is not None:
        vw = valve_w[idx]
        if np.mean(~np.isnan(vw)) >= VALVE_COVERAGE and np.nansum(vw) > 0:
            vw = np.where(np.isnan(vw), np.nanmean(vw), vw)
            return total * vw / vw.sum(), "valves"
    ww = weather_w[idx]
    if np.nansum(ww) >= SUMMER_KWH and not np.isnan(ww).any():
        return total * ww / ww.sum(), "weather"
    return np.full(n, total / n), "even"
