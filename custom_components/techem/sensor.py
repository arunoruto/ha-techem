"""Sensors: latest month per service, comparison, kWh per unit, year to date."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TechemConfigEntry
from .analysis import Analysis
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


@dataclass(frozen=True)
class ModelKind:
    key: str
    name: str
    unit: str | None
    value: Callable[[Analysis], float | None]
    attrs: Callable[[Analysis], dict]
    diagnostic: bool = False


def _fit_attrs(a: Analysis) -> dict:
    f = a.fit
    if not f:
        return {}
    return {
        "balance_temperature": f.base,
        "kwh_per_degree_day": round(f.a_hdd, 3),
        "kwh_per_kwh_m2_sun": round(f.a_sun, 3),
        "r2": round(f.r2, 3),
        "rmse_loo_kwh": round(f.rmse_loo, 1),
        "months_fitted": f.months,
    }


MODEL_KINDS = [
    ModelKind(
        "forecast_this_month", "Heating forecast this month", "KWH", lambda a: a.forecast,
        lambda a: {
            "month": a.month, "so_far": a.so_far, "behaviour_factor": a.factor.value,
            "hours_from_weather_forecast": a.forecast_from_forecast_h,
            "hours_from_past_years": a.forecast_from_climate_h,
        },
    ),
    ModelKind("this_month_so_far", "Heating this month so far", "KWH", lambda a: a.so_far, lambda a: {"month": a.month}),
    ModelKind(
        "behaviour_factor", "Heating behaviour factor", None, lambda a: a.factor.value,
        lambda a: {"months": a.factor.months, "actual_kwh": a.factor.actual, "weather_model_kwh": a.factor.model, **_fit_attrs(a)},
        diagnostic=True,
    ),
    ModelKind(
        "last_month_vs_weather", "Heating last month vs weather", "%",
        lambda a: a.last_month_ratio and round(a.last_month_ratio * 100, 1), lambda a: {"period": a.last_month},
    ),
]  # fmt: skip


async def async_setup_entry(hass: HomeAssistant, entry: TechemConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        TechemSensor(coordinator, unit, service, kind)
        for unit, services in coordinator.data.items()
        for service, svc in services.items()
        for kind in kinds(service, svc)
    ]
    entities += [TechemModelSensor(coordinator, unit, kind) for unit in coordinator.analyses for kind in MODEL_KINDS]
    add(entities)


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


class TechemModelSensor(CoordinatorEntity[TechemCoordinator], SensorEntity):
    """Outputs of the empirical heating model (see README)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TechemCoordinator, unit: str, kind: ModelKind) -> None:
        super().__init__(coordinator)
        self._unit, self._kind = unit, kind
        self._attr_unique_id = f"{unit}_HEATING_model_{kind.key}"
        self._attr_name = kind.name
        if kind.unit == "KWH":
            self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_suggested_display_precision = 0
        elif kind.unit:
            self._attr_native_unit_of_measurement = kind.unit
        else:
            self._attr_suggested_display_precision = 2
        if kind.diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, unit)})

    @property
    def _analysis(self) -> Analysis | None:
        return self.coordinator.analyses.get(self._unit)

    @property
    def available(self) -> bool:
        return super().available and self._analysis is not None and self._analysis.fit is not None

    @property
    def native_value(self) -> float | None:
        return self._kind.value(self._analysis) if self._analysis else None

    @property
    def extra_state_attributes(self) -> dict:
        return self._kind.attrs(self._analysis) if self._analysis else {}
