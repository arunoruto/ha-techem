"""Sensors: latest month per service, comparison, kWh per unit, year to date."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TechemConfigEntry
from .api import ServiceData
from .const import BASE_URL, DOMAIN
from .coordinator import TechemCoordinator, short_id

UNITS = {
    "KWH": (UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY),
    "M3": (UnitOfVolume.CUBIC_METERS, SensorDeviceClass.WATER),
    "HCU": ("units", None),
}


def latest(svc: ServiceData, unit: str) -> dict | None:
    rows = [r for r in svc.rows if r["unitOfMeasure"] == unit]
    return rows[-1] if rows else None


def row_attrs(row: dict | None) -> dict:
    if not row:
        return {}
    return {k: row.get(k) for k in ("period", "status", "quality", "revision", "createdAt")}


@dataclass(frozen=True)
class Kind:
    key: str
    name: str
    unit: str
    value: Callable[[ServiceData], float | None]
    attrs: Callable[[ServiceData], dict]


def kinds(service: str, svc: ServiceData) -> list[Kind]:
    units = {r["unitOfMeasure"] for r in svc.rows}
    label = service.replace("_", " ").capitalize()
    out = []
    for u in units:
        out.append(Kind(
            f"last_month_{u.lower()}", f"{label} last month" + ("" if u == "KWH" else f" ({UNITS.get(u, (u,))[0]})"), u,
            lambda s, u=u: (r := latest(s, u)) and r["amount"],
            lambda s, u=u: row_attrs(latest(s, u)),
        ))  # fmt: skip
    if "KWH" in units:
        def same_month_last_year(s: ServiceData) -> dict | None:
            if not (r := latest(s, "KWH")):
                return None
            y, m = r["period"].split("-")
            prev = f"{int(y) - 1}-{m}"
            return next((x for x in s.rows if x["period"] == prev and x["unitOfMeasure"] == "KWH"), None)

        def year_to_date(s: ServiceData) -> float | None:
            if not (r := latest(s, "KWH")):
                return None
            year = r["period"][:4]
            return round(sum(x["amount"] for x in s.rows if x["unitOfMeasure"] == "KWH" and x["period"].startswith(year)), 1)

        out += [
            Kind("same_month_last_year", f"{label} same month last year", "KWH",
                 lambda s: (r := same_month_last_year(s)) and r["amount"], lambda s: row_attrs(same_month_last_year(s))),
            Kind("year_to_date", f"{label} year to date", "KWH", year_to_date,
                 lambda s: {"year": (r := latest(s, "KWH")) and r["period"][:4]}),
        ]  # fmt: skip
    if svc.average:
        out.append(Kind(
            "comparable_households", f"{label} comparable households", svc.average.get("unitOfMeasure", "KWH"),
            lambda s: s.average and s.average.get("amount"), lambda s: {"createdAt": s.average and s.average.get("createdAt")},
        ))  # fmt: skip
    if {"KWH", "HCU"} <= units:
        def factor(s: ServiceData) -> float | None:
            kwh, hcu = latest(s, "KWH"), latest(s, "HCU")
            if kwh and hcu and kwh["period"] == hcu["period"] and hcu["amount"]:
                return round(kwh["amount"] / hcu["amount"], 3)
            return None

        out.append(Kind("kwh_per_unit", f"{label} kWh per unit", "KWH/HCU", factor,
                        lambda s: {"period": (r := latest(s, "HCU")) and r["period"]}))  # fmt: skip
    return out


async def async_setup_entry(hass: HomeAssistant, entry: TechemConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    add(
        TechemSensor(coordinator, unit, service, kind)
        for unit, services in coordinator.data.items()
        for service, svc in services.items()
        for kind in kinds(service, svc)
    )


class TechemSensor(CoordinatorEntity[TechemCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: TechemCoordinator, unit: str, service: str, kind: Kind) -> None:
        super().__init__(coordinator)
        self._unit, self._service, self._kind = unit, service, kind
        sid = short_id(unit)
        self._attr_unique_id = f"{unit}_{service}_{kind.key}"
        self._attr_name = kind.name
        if kind.unit == "KWH/HCU":
            self._attr_native_unit_of_measurement = "kWh/unit"
            self._attr_suggested_display_precision = 2
        else:
            self._attr_native_unit_of_measurement, self._attr_device_class = UNITS.get(kind.unit, (kind.unit, None))
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unit)},
            name=f"Techem {sid}",
            manufacturer="Techem",
            model="Tenant portal",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=BASE_URL,
        )

    @property
    def _svc(self) -> ServiceData | None:
        return (self.coordinator.data or {}).get(self._unit, {}).get(self._service)

    @property
    def available(self) -> bool:
        return super().available and self._svc is not None

    @property
    def native_value(self) -> float | None:
        return self._kind.value(self._svc) if self._svc else None

    @property
    def extra_state_attributes(self) -> dict:
        return self._kind.attrs(self._svc) if self._svc else {}
