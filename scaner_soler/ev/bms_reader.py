"""
BMS Reader — agrega y valida datos del Battery Management System.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CellStats:
    count:    int   = 0
    max_v:    float = 0.0
    min_v:    float = 0.0
    delta_v:  float = 0.0


_BMS_LIMITS: dict[str, tuple[float, float]] = {
    "soc_pct":       (0.0,  100.0),
    "soh_pct":       (0.0,  100.0),
    "temp_max":      (-40,   60.0),
    "temp_delta":    (0.0,    8.0),
    "cells.delta_v": (0.0,   0.05),
    "motor_temp":    (-40,  180.0),
    "inverter_temp": (-40,  100.0),
}

_CAPACITY_KWH: dict[str, float] = {
    "Nissan_Leaf":    40.0,
    "Chevrolet_Bolt": 65.0,
    "BMW_i3":         42.2,
    "VW_MEB":         77.0,
    "Renault_Zoe":    52.0,
    "Hyundai_EGMP":   77.4,
    "Tesla_OBD":      82.0,
}


@dataclass
class BMSData:
    brand:          str
    timestamp:      datetime = field(default_factory=datetime.now)

    soc_pct:        Optional[float] = None
    soh_pct:        Optional[float] = None
    usable_soc:     Optional[float] = None

    pack_voltage:   Optional[float] = None
    pack_current:   Optional[float] = None
    pack_power_kw:  Optional[float] = None

    temp_max:       Optional[float] = None
    temp_min:       Optional[float] = None
    temp_delta:     Optional[float] = None

    cells:          CellStats = field(default_factory=CellStats)

    motor_temp:     Optional[float] = None
    inverter_temp:  Optional[float] = None

    charge_power_kw:    Optional[float] = None
    charge_session_kwh: Optional[float] = None
    dc_inlet_voltage:   Optional[float] = None
    dc_inlet_current:   Optional[float] = None
    charge_time_min:    Optional[float] = None

    alerts:         list[str] = field(default_factory=list)

    @property
    def estimated_range_km(self) -> Optional[float]:
        if self.soc_pct is None:
            return None
        cap = _CAPACITY_KWH.get(self.brand, 50.0)
        return round(cap * (self.soc_pct / 100.0) * 6.0, 1)

    @property
    def is_charging(self) -> bool:
        if self.pack_current is not None:
            return self.pack_current > 1.0
        return (self.charge_power_kw or 0) > 0.5

    def validate(self) -> list[str]:
        self.alerts = []

        if self.pack_power_kw is None and (
            self.pack_voltage is not None and self.pack_current is not None
        ):
            self.pack_power_kw = round(self.pack_voltage * self.pack_current / 1000, 2)

        if self.temp_max is not None and self.temp_min is not None:
            self.temp_delta = round(self.temp_max - self.temp_min, 1)

        if self.cells.max_v and self.cells.min_v:
            self.cells.delta_v = round(self.cells.max_v - self.cells.min_v, 4)

        def _check(attr: str, value: Optional[float]) -> None:
            if value is None:
                return
            lo, hi = _BMS_LIMITS[attr]
            if value < lo:
                self.alerts.append(f"BAJO {attr}: {value} (min {lo})")
            elif value > hi:
                self.alerts.append(f"ALTO {attr}: {value} (max {hi})")

        _check("soc_pct",       self.soc_pct)
        _check("soh_pct",       self.soh_pct)
        _check("temp_max",      self.temp_max)
        _check("temp_delta",    self.temp_delta)
        _check("cells.delta_v", self.cells.delta_v if self.cells.delta_v else None)
        _check("motor_temp",    self.motor_temp)
        _check("inverter_temp", self.inverter_temp)

        if self.soh_pct is not None and self.soh_pct < 70:
            self.alerts.append(f"SOH critico: {self.soh_pct}% — considerar reemplazo")

        return self.alerts

    def summary(self) -> str:
        lines = [
            f"BMS {self.brand}  [{self.timestamp.strftime('%H:%M:%S')}]",
            f"  SOC: {self.soc_pct}%   SOH: {self.soh_pct}%   Rango: {self.estimated_range_km} km",
            f"  Pack: {self.pack_voltage} V / {self.pack_current} A / {self.pack_power_kw} kW",
            f"  Temp: max={self.temp_max}C  min={self.temp_min}C  delta={self.temp_delta}C",
            f"  Celdas: max={self.cells.max_v}V  min={self.cells.min_v}V  delta={self.cells.delta_v}V",
            f"  Motor: {self.motor_temp}C  Inversor: {self.inverter_temp}C",
        ]
        if self.is_charging:
            lines.append(
                f"  CARGANDO: {self.charge_power_kw} kW  "
                f"sesion {self.charge_session_kwh} kWh  "
                f"tiempo ~{self.charge_time_min} min"
            )
        if self.alerts:
            lines.append("  ALERTAS:")
            for a in self.alerts:
                lines.append(f"    * {a}")
        return "\n".join(lines)


_FIELD_MAP: dict[str, str] = {
    "bms_soc":              "soc_pct",
    "bms_usable_soc":       "usable_soc",
    "bms_soh":              "soh_pct",
    "bms_pack_voltage":     "pack_voltage",
    "bms_current":          "pack_current",
    "bms_temp_max":         "temp_max",
    "bms_temp_min":         "temp_min",
    "bms_batt_temp_max":    "temp_max",
    "bms_batt_temp_min":    "temp_min",
    "bms_temp":             "temp_max",
    "bms_max_cell_v":       "cells.max_v",
    "bms_min_cell_v":       "cells.min_v",
    "motor_temp":           "motor_temp",
    "inverter_temp":        "inverter_temp",
    "charge_power_kw":      "charge_power_kw",
    "charger_power_kw":     "charge_power_kw",
    "charge_session_kwh":   "charge_session_kwh",
    "dc_inlet_voltage":     "dc_inlet_voltage",
    "dc_inlet_current":     "dc_inlet_current",
    "charge_time_min":      "charge_time_min",
}


class BMSReader:
    def __init__(self, brand: str):
        self.brand = brand

    def build(self, readings: dict[str, object]) -> BMSData:
        bms = BMSData(brand=self.brand)
        for src_name, value in readings.items():
            dst = _FIELD_MAP.get(src_name)
            if dst is None or value is None:
                continue
            if dst.startswith("cells."):
                attr = dst.split(".")[1]
                setattr(bms.cells, attr, float(value))
            else:
                setattr(bms, dst, float(value))
        bms.validate()
        return bms
