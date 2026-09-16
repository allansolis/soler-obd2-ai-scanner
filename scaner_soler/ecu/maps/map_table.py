import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.interpolate import RegularGridInterpolator


class SafetyError(Exception):
    pass


@dataclass
class MapTable:
    name: str
    rpm_axis: np.ndarray
    load_axis: np.ndarray
    values: np.ndarray
    unit: str = ""
    min_safe: float = -999.0
    max_safe: float = 999.0
    description: str = ""

    def __post_init__(self):
        self._backup: np.ndarray = self.values.copy()
        self._dirty: bool = False
        self._change_log: list[dict] = []

    # ── Safety ────────────────────────────────────────────────────────────

    def _validate_value(self, value: float):
        if not (self.min_safe <= value <= self.max_safe):
            raise SafetyError(
                f"[{self.name}] Valor {value:.3f} {self.unit} fuera del rango "
                f"seguro [{self.min_safe}, {self.max_safe}]"
            )

    # ── Cell access ────────────────────────────────────────────────────────

    def get_cell(self, rpm_idx: int, load_idx: int) -> float:
        return float(self.values[rpm_idx, load_idx])

    def set_cell(self, rpm_idx: int, load_idx: int, value: float):
        self._validate_value(value)
        old = self.values[rpm_idx, load_idx]
        self.values[rpm_idx, load_idx] = value
        self._dirty = True
        self._change_log.append({
            "rpm_idx": rpm_idx, "load_idx": load_idx,
            "rpm": float(self.rpm_axis[rpm_idx]),
            "load": float(self.load_axis[load_idx]),
            "old": float(old), "new": float(value),
        })

    def set_region(self, rpm_slice: slice, load_slice: slice, delta: float):
        """Add `delta` to a region. Validates each cell individually."""
        region = self.values[rpm_slice, load_slice] + delta
        for i, ri in enumerate(range(*rpm_slice.indices(len(self.rpm_axis)))):
            for j, li in enumerate(range(*load_slice.indices(len(self.load_axis)))):
                self._validate_value(float(region[i, j]))
        self.values[rpm_slice, load_slice] = region
        self._dirty = True

    # ── Interpolation ──────────────────────────────────────────────────────

    def interpolate_at(self, rpm: float, load: float) -> float:
        interp = RegularGridInterpolator(
            (self.rpm_axis, self.load_axis), self.values,
            method="linear", bounds_error=False, fill_value=None
        )
        return float(interp([[rpm, load]])[0])

    # ── Backup / restore ───────────────────────────────────────────────────

    def restore_backup(self):
        self.values = self._backup.copy()
        self._dirty = False
        self._change_log.clear()

    @property
    def has_changes(self) -> bool:
        return self._dirty

    @property
    def diff(self) -> np.ndarray:
        return self.values - self._backup

    @property
    def changed_cells(self) -> list[dict]:
        return [c for c in self._change_log]

    # ── Serialization ──────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "unit": self.unit,
            "min_safe": self.min_safe,
            "max_safe": self.max_safe,
            "description": self.description,
            "rows": len(self.rpm_axis),
            "cols": len(self.load_axis),
            "rpm_axis": self.rpm_axis.tolist(),
            "load_axis": self.load_axis.tolist(),
            "values": self.values.tolist(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MapTable":
        return cls(
            name=d["name"],
            rpm_axis=np.array(d["rpm_axis"]),
            load_axis=np.array(d["load_axis"]),
            values=np.array(d["values"]),
            unit=d.get("unit", ""),
            min_safe=d.get("min_safe", -999.0),
            max_safe=d.get("max_safe", 999.0),
            description=d.get("description", ""),
        )

    def checksum(self) -> str:
        return hashlib.sha256(self.values.tobytes()).hexdigest()[:16]

    def __repr__(self) -> str:
        return (f"MapTable(name={self.name!r}, shape={self.values.shape}, "
                f"unit={self.unit!r}, range=[{self.min_safe},{self.max_safe}])")
