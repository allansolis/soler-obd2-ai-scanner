"""
SOLER OBD2 AI Scanner - Tuning Profiles
========================================
Predefined tuning profiles that modify stock ECU maps with
validated percentage-based adjustments.  Each profile targets a
specific trade-off between economy, power, and component safety.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np

from backend.tuning.map_generator import ECUMapSet, LaunchControlSettings, RevLimiterSettings


# ---------------------------------------------------------------------------
# Profile enumeration
# ---------------------------------------------------------------------------

class ProfileName(str, Enum):
    """Available tuning profile identifiers."""

    ECONOMY = "economy"
    STAGE_1 = "stage_1"
    SPORT = "sport"
    STAGE_2 = "stage_2"


# ---------------------------------------------------------------------------
# Profile specification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProfileSpec:
    """Numerical specification for a tuning profile.

    All *_pct fields are expressed as **signed percentages** relative
    to the stock map value (e.g. +4 means 4 % richer fuel, -8 means
    8 % leaner).
    """

    name: ProfileName
    label: str
    description: str

    # Map modifiers (signed %)
    fuel_enrichment_pct: float
    timing_offset_deg: float      # absolute degrees added / removed
    boost_change_pct: float
    vvt_offset_deg: float         # absolute cam-degrees offset
    throttle_gain_pct: float      # throttle map multiplier delta

    # Rev-limiter adjustments
    rev_limit_offset_rpm: float

    # Launch-control adjustments
    launch_rpm_offset: float
    launch_boost_pct: float       # signed % change on boost limit

    # Expected outcome ranges
    hp_gain_min_pct: float
    hp_gain_max_pct: float
    mpg_change_min_pct: float     # positive = better economy
    mpg_change_max_pct: float


# ---------------------------------------------------------------------------
# Built-in profile definitions
# ---------------------------------------------------------------------------

_ECONOMY = ProfileSpec(
    name=ProfileName.ECONOMY,
    label="Economy",
    description=(
        "Optimised for fuel efficiency.  Leans fuel delivery, retards "
        "timing slightly, and reduces boost demand to minimise consumption."
    ),
    fuel_enrichment_pct=-8.0,
    timing_offset_deg=-1.0,
    boost_change_pct=-15.0,
    vvt_offset_deg=3.0,           # slightly more overlap for pumping loss
    throttle_gain_pct=-5.0,
    rev_limit_offset_rpm=-200.0,
    launch_rpm_offset=-300.0,
    launch_boost_pct=-20.0,
    hp_gain_min_pct=-5.0,
    hp_gain_max_pct=-2.0,
    mpg_change_min_pct=8.0,
    mpg_change_max_pct=15.0,
)

_STAGE_1 = ProfileSpec(
    name=ProfileName.STAGE_1,
    label="Stage 1",
    description=(
        "Mild street tune.  Modest enrichment and timing advance for "
        "a noticeable but safe power increase on a stock engine."
    ),
    fuel_enrichment_pct=4.0,
    timing_offset_deg=2.0,
    boost_change_pct=10.0,
    vvt_offset_deg=2.0,
    throttle_gain_pct=5.0,
    rev_limit_offset_rpm=0.0,
    launch_rpm_offset=200.0,
    launch_boost_pct=5.0,
    hp_gain_min_pct=5.0,
    hp_gain_max_pct=12.0,
    mpg_change_min_pct=-3.0,
    mpg_change_max_pct=-1.0,
)

_SPORT = ProfileSpec(
    name=ProfileName.SPORT,
    label="Sport",
    description=(
        "Aggressive street / light track tune.  Significant enrichment, "
        "timing advance, and boost increase for spirited driving."
    ),
    fuel_enrichment_pct=8.0,
    timing_offset_deg=4.0,
    boost_change_pct=18.0,
    vvt_offset_deg=4.0,
    throttle_gain_pct=12.0,
    rev_limit_offset_rpm=200.0,
    launch_rpm_offset=400.0,
    launch_boost_pct=12.0,
    hp_gain_min_pct=10.0,
    hp_gain_max_pct=20.0,
    mpg_change_min_pct=-10.0,
    mpg_change_max_pct=-5.0,
)

_STAGE_2 = ProfileSpec(
    name=ProfileName.STAGE_2,
    label="Stage 2",
    description=(
        "High-performance tune requiring supporting hardware mods "
        "(intake, exhaust, intercooler).  Maximum safe power output "
        "for a stock internal engine."
    ),
    fuel_enrichment_pct=12.0,
    timing_offset_deg=6.0,
    boost_change_pct=30.0,
    vvt_offset_deg=6.0,
    throttle_gain_pct=18.0,
    rev_limit_offset_rpm=400.0,
    launch_rpm_offset=600.0,
    launch_boost_pct=20.0,
    hp_gain_min_pct=18.0,
    hp_gain_max_pct=35.0,
    mpg_change_min_pct=-18.0,
    mpg_change_max_pct=-10.0,
)


# ---------------------------------------------------------------------------
# Profile application logic
# ---------------------------------------------------------------------------

class TuningProfile:
    """Applies a :class:`ProfileSpec` to a stock :class:`ECUMapSet`."""

    def __init__(self, spec: ProfileSpec) -> None:
        self.spec = spec

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _scale_map(data: np.ndarray, pct: float) -> np.ndarray:
        """Scale non-zero values by *pct* percent."""
        factor = 1.0 + pct / 100.0
        out = data.copy()
        mask = data != 0.0
        out[mask] = data[mask] * factor
        return out

    @staticmethod
    def _offset_map(data: np.ndarray, offset: float) -> np.ndarray:
        """Add a fixed offset to all non-zero values."""
        out = data.copy()
        mask = data != 0.0
        out[mask] = data[mask] + offset
        return out

    # -- public ------------------------------------------------------------

    def apply(self, stock: ECUMapSet) -> ECUMapSet:
        """Return a **new** :class:`ECUMapSet` with the profile applied.

        The original *stock* maps are never mutated.
        """
        modified = stock.copy()

        # Fuel map: percentage enrichment / leaning
        modified.fuel_map.data = self._scale_map(
            stock.fuel_map.data, self.spec.fuel_enrichment_pct,
        )

        # Ignition map: absolute degree offset
        modified.ignition_map.data = self._offset_map(
            stock.ignition_map.data, self.spec.timing_offset_deg,
        )
        modified.ignition_map.data = np.clip(modified.ignition_map.data, 0.0, 50.0)

        # Boost map: percentage change
        modified.boost_map.data = self._scale_map(
            stock.boost_map.data, self.spec.boost_change_pct,
        )
        modified.boost_map.data = np.clip(modified.boost_map.data, 0.0, 3.0)

        # VVT map: absolute degree offset
        modified.vvt_map.data = self._offset_map(
            stock.vvt_map.data, self.spec.vvt_offset_deg,
        )
        modified.vvt_map.data = np.clip(modified.vvt_map.data, 0.0, 55.0)

        # Throttle map: percentage gain change
        modified.throttle_map.data = self._scale_map(
            stock.throttle_map.data, self.spec.throttle_gain_pct,
        )
        modified.throttle_map.data = np.clip(modified.throttle_map.data, 0.0, 100.0)

        # Rev limiter
        modified.rev_limiter = RevLimiterSettings(
            soft_limit_rpm=stock.rev_limiter.soft_limit_rpm + self.spec.rev_limit_offset_rpm,
            hard_limit_rpm=stock.rev_limiter.hard_limit_rpm + self.spec.rev_limit_offset_rpm,
            fuel_cut_percent=stock.rev_limiter.fuel_cut_percent,
            ignition_retard_deg=stock.rev_limiter.ignition_retard_deg,
        )

        # Launch control
        modified.launch_control = LaunchControlSettings(
            enabled=stock.launch_control.enabled,
            launch_rpm=stock.launch_control.launch_rpm + self.spec.launch_rpm_offset,
            max_rpm=stock.launch_control.max_rpm + self.spec.launch_rpm_offset,
            ignition_retard_deg=stock.launch_control.ignition_retard_deg,
            boost_limit_bar=stock.launch_control.boost_limit_bar * (
                1.0 + self.spec.launch_boost_pct / 100.0
            ),
            time_limit_sec=stock.launch_control.time_limit_sec,
        )

        # Tag the profile in vehicle info
        modified.vehicle_info = dict(stock.vehicle_info)
        modified.vehicle_info["tuning_profile"] = self.spec.name.value

        return modified


# ---------------------------------------------------------------------------
# Profile library (singleton registry)
# ---------------------------------------------------------------------------

class ProfileLibrary:
    """Registry of all available tuning profiles."""

    _specs: dict[ProfileName, ProfileSpec] = {
        ProfileName.ECONOMY: _ECONOMY,
        ProfileName.STAGE_1: _STAGE_1,
        ProfileName.SPORT: _SPORT,
        ProfileName.STAGE_2: _STAGE_2,
    }

    @classmethod
    def get_spec(cls, name: ProfileName) -> ProfileSpec:
        """Return the :class:`ProfileSpec` for *name*."""
        return cls._specs[name]

    @classmethod
    def get_profile(cls, name: ProfileName) -> TuningProfile:
        """Return a ready-to-use :class:`TuningProfile` for *name*."""
        return TuningProfile(cls._specs[name])

    @classmethod
    def list_profiles(cls) -> list[ProfileSpec]:
        """Return all registered profile specs."""
        return list(cls._specs.values())

    @classmethod
    def apply_to_stock(
        cls,
        name: ProfileName,
        stock: ECUMapSet,
    ) -> ECUMapSet:
        """Convenience: apply profile *name* to *stock* and return result."""
        return cls.get_profile(name).apply(stock)

    @classmethod
    def register(cls, spec: ProfileSpec) -> None:
        """Register a custom profile spec."""
        cls._specs[spec.name] = spec
