"""Hourly outdoor temperature and solar radiation from Open-Meteo (free, no key).

Only the home coordinates rounded to 0.1° (~10 km) are sent. History comes
from the archive API (a few days behind), the recent past and the next 16 days
from the forecast API. Everything is cached in HA storage, so the archive is
downloaded once and then only topped up.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"
VARS = "temperature_2m,shortwave_radiation"
ARCHIVE_LAG = timedelta(days=6)
REFRESH = timedelta(hours=6)


class Weather:
    """Hourly series keyed by UTC hour (epoch seconds)."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.lat = round(hass.config.latitude, 1)
        self.lon = round(hass.config.longitude, 1)
        self._store = Store(hass, 1, f"{DOMAIN}.weather.{entry_id}")
        self.archive: dict[int, tuple[float, float]] = {}  # final values
        self.recent: dict[int, tuple[float, float]] = {}  # forecast API: past 31 days + 16 ahead
        self.fetched: datetime | None = None
        self._loaded = False

    async def _get(self, url: str, params: dict) -> dict:
        session = async_get_clientsession(self.hass)
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=60)) as r:
            r.raise_for_status()
            return await r.json()

    @staticmethod
    def _parse(data: dict) -> dict[int, tuple[float, float]]:
        h = data["hourly"]
        out = {}
        for t, temp, sun in zip(h["time"], h["temperature_2m"], h["shortwave_radiation"]):
            if temp is not None:
                ts = int(datetime.fromisoformat(t).replace(tzinfo=UTC).timestamp())
                out[ts] = (float(temp), float(sun or 0.0))
        return out

    async def async_update(self, since: datetime) -> None:
        """Make sure hours from `since` until +16 days are available."""
        if not self._loaded:
            if stored := await self._store.async_load():
                if (stored.get("lat"), stored.get("lon")) == (self.lat, self.lon):
                    self.archive = {int(k): tuple(v) for k, v in stored["archive"].items()}
            self._loaded = True
        now = datetime.now(UTC)
        if self.fetched and now - self.fetched < REFRESH:
            return
        loc = {"latitude": self.lat, "longitude": self.lon, "hourly": VARS, "timezone": "UTC"}
        end = (now - ARCHIVE_LAG).date()
        start = since.astimezone(UTC).date()
        if self.archive:
            start = max(start, datetime.fromtimestamp(max(self.archive), UTC).date())
        if start < end:
            data = await self._get(ARCHIVE, {**loc, "start_date": start.isoformat(), "end_date": end.isoformat()})
            self.archive.update(self._parse(data))
            await self._store.async_save(
                {"lat": self.lat, "lon": self.lon, "archive": {str(k): list(v) for k, v in self.archive.items()}}
            )
        self.recent = self._parse(await self._get(FORECAST, {**loc, "past_days": 31, "forecast_days": 16}))
        self.fetched = now

    def get(self, ts: int) -> tuple[float, float] | None:
        return self.archive.get(ts) or self.recent.get(ts)
