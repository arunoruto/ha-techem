"""Polls the portal, keeps the rolling cookie, imports monthly history into statistics."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.components.recorder.models import StatisticData, StatisticMeanType, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ServiceData, TechemAuthError, TechemClient, TechemError
from .const import CONF_COOKIES, DOMAIN

_LOGGER = logging.getLogger(__name__)

# portal unit -> (HA unit, unit class) for units that can be summed into statistics
STAT_UNITS = {"KWH": (UnitOfEnergy.KILO_WATT_HOUR, "energy"), "M3": (UnitOfVolume.CUBIC_METERS, "volume")}

type TechemData = dict[str, dict[str, ServiceData]]  # unit id -> service -> data


def short_id(unit: str) -> str:
    return unit.rsplit(":", 1)[-1][-8:].lower()


class TechemCoordinator(DataUpdateCoordinator[TechemData]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: TechemClient) -> None:
        # daily data, but poll every 6 h so the 30-day session cookie keeps rolling
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=timedelta(hours=6))
        self.client = client

    async def _async_update_data(self) -> TechemData:
        try:
            await self.client.session_user()
            data = {unit: await self.client.consumption(unit) for unit in await self.client.units()}
        except TechemAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (TechemError, OSError, TimeoutError) as err:
            raise UpdateFailed(str(err)) from err
        finally:
            if self.client.cookies != self.config_entry.data[CONF_COOKIES]:
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data={**self.config_entry.data, CONF_COOKIES: self.client.cookies}
                )
        self._import_statistics(data)
        return data

    def _import_statistics(self, data: TechemData) -> None:
        tz = dt_util.get_default_time_zone()
        for unit, services in data.items():
            for service, svc in services.items():
                for portal_unit, (ha_unit, unit_class) in STAT_UNITS.items():
                    rows = [r for r in svc.rows if r["unitOfMeasure"] == portal_unit]
                    if not rows:
                        continue
                    stat_id = f"{DOMAIN}:{service.lower()}_{portal_unit.lower()}_{short_id(unit)}"
                    total, stats = 0.0, []
                    for r in rows:  # sorted by period; a month's whole amount lands on its first hour
                        total += r["amount"]
                        year, month = map(int, r["period"].split("-"))
                        start = datetime(year, month, 1, tzinfo=tz)
                        stats.append(StatisticData(start=start, state=r["amount"], sum=round(total, 3)))
                    meta = StatisticMetaData(
                        mean_type=StatisticMeanType.NONE,
                        has_sum=True,
                        name=f"Techem {service.replace('_', ' ').title()} ({ha_unit}, monthly)",
                        source=DOMAIN,
                        statistic_id=stat_id,
                        unit_class=unit_class,
                        unit_of_measurement=ha_unit,
                    )
                    async_add_external_statistics(self.hass, meta, stats)
