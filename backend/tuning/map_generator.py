"""
SOLER OBD2 AI Scanner - ECU Map Generator
==========================================
Generates stock and base ECU calibration maps as numpy 2D arrays
with properly labelled axes for fuel, ignition, boost, VVT,
throttle-response, rev-limiter, and launch-control.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Standard axis definitions
# ---------------------------------------------------------------------------

# RPM breakpoints (500 - 8000 in 500 rpm steps)
DEFAULT_RPM_AXIS: np.ndarray = np.arange(500, 8500, 500, dtype=np.float64)

# Load breakpoints (0 - 100 % in 5 % steps)
DEFAULT_LOAD_AXIS: np.ndarray = np.arange(0, 105, 5, dtype=np.float64)

# Throttle position breakpoints (0 - 100 % in 5 % steps)
DEFAULT_THROTTLE_AXIS: np.ndarray = np.arange(0, 105, 5, dtype=np.float64)

# Pedal position breakpoints (0 - 100 % in 10 % steps)
DEFAULT_PEDAL_AXIS: np.ndarray = np.arange(0, 110, 10, dtype=np.float64)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MapAxis:
    """Describes a single map axis."""

    name: str
    unit: str
    values: np.ndarray

    def __len__(self) -> int:
        return len(self.values)


@dataclass
class ECUMap:
    """A single 2D calibration map with metadata."""

    name: str
    description: str
    unit: str
    x_axis: MapAxis
    y_axis: MapAxis
    data: np.ndarray  # shape (len(y_axis), len(x_axis))

    def __post_init__(self) -> None:
        expected = (len(self.y_axis), len(self.x_axis))
        if self.data.shape != expected:
            raise ValueError(
                f"Map '{self.name}' data shape {self.data.shape} "
                f"does not match axes {expected}"
            )

    def copy(self) -> "ECUMap":
        """Return a deep copy of this map."""
        return ECUMap(
            name=self.name,
            description=self.description,
            unit=self.unit,
            x_axis=MapAxis(self.x_axis.name, self.x_axis.unit, self.x_axis.values.copy()),
            y_axis=MapAxis(self.y_axis.name, self.y_axis.unit, self.y_axis.values.copy()),
            data=self.data.copy(),
        )


@dataclass
class RevLimiterSettings:
    """Rev limiter configuration."""

    soft_limit_rpm: float = 6800.0
    hard_limit_rpm: float = 7000.0
    fuel_cut_percent: float = 100.0  # % fuel cut at hard limit
    ignition_retard_deg: float = 15.0  # degrees retard at soft limit


@dataclass
class LaunchControlSettings:
    """Launch control configuration."""

    enabled: bool = True
    launch_rpm: float = 3500.0
    max_rpm: float = 4000.0
    ignition_retard_deg: float = 20.0
    boost_limit_bar: float = 0.8
    time_limit_sec: float = 10.0


@dataclass
class ECUMapSet:
    """Complete set of ECU calibration maps for a vehicle."""

    fuel_map: ECUMap
    ignition_map: ECUMap
    boost_map: ECUMap
    vvt_map: ECUMap
    throttle_map: ECUMap
    rev_limiter: RevLimiterSettings
    launch_control: LaunchControlSettings
    vehicle_info: dict[str, str] = field(default_factory=dict)

    def copy(self) -> "ECUMapSet":
        """Deep-copy every map in the set."""
        return ECUMapSet(
            fuel_map=self.fuel_map.copy(),
            ignition_map=self.ignition_map.copy(),
            boost_map=self.boost_map.copy(),
            vvt_map=self.vvt_map.copy(),
            throttle_map=self.throttle_map.copy(),
            rev_limiter=RevLimiterSettings(
                soft_limit_rpm=self.rev_limiter.soft_limit_rpm,
                hard_limit_rpm=self.rev_limiter.hard_limit_rpm,
                fuel_cut_percent=self.rev_limiter.fuel_cut_percent,
                ignition_retard_deg=self.rev_limiter.ignition_retard_deg,
            ),
            launch_control=LaunchControlSettings(
                enabled=self.launch_control.enabled,
                launch_rpm=self.launch_control.launch_rpm,
                max_rpm=self.launch_control.max_rpm,
                ignition_retard_deg=self.launch_control.ignition_retard_deg,
                boost_limit_bar=self.launch_control.boost_limit_bar,
                time_limit_sec=self.launch_control.time_limit_sec,
            ),
            vehicle_info=dict(self.vehicle_info),
        )


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class ECUMapGenerator:
    """Generates realistic stock ECU calibration maps.

    The generator produces physically plausible base maps that model
    typical naturally-aspirated and turbocharged gasoline engines.
    All values include proper safety margins for a stock calibration.
    """

    def __init__(
        self,
        rpm_axis: Optional[np.ndarray] = None,
        load_axis: Optional[np.ndarray] = None,
        throttle_axis: Optional[np.ndarray] = None,
        pedal_axis: Optional[np.ndarray] = None,
        displacement_cc: float = 2000.0,
        turbo: bool = True,
        max_boost_bar: float = 1.2,
        design_rev_limit: float = 7000.0,
    ) -> None:
        self.rpm_axis = rpm_axis if rpm_axis is not None else DEFAULT_RPM_AXIS.copy()
        self.load_axis = load_axis if load_axis is not None else DEFAULT_LOAD_AXIS.copy()
        self.throttle_axis = throttle_axis if throttle_axis is not None else DEFAULT_THROTTLE_AXIS.copy()
        self.pedal_axis = pedal_axis if pedal_axis is not None else DEFAULT_PEDAL_AXIS.copy()

        self.displacement_cc = displacement_cc
        self.turbo = turbo
        self.max_boost_bar = max_boost_bar if turbo else 0.0
        self.design_rev_limit = design_rev_limit

    # ------------------------------------------------------------------
    # Fuel injection map  (RPM x Load -> pulse-width in ms)
    # ------------------------------------------------------------------

    def generate_fuel_map(self) -> ECUMap:
        """Create a stock fuel injection pulse-width map.

        Values range from ~1.5 ms at idle / low load up to ~12 ms at
        high RPM / full load.  The map includes slight enrichment at
        very high RPM for component protection.
        """
        rpm = self.rpm_axis
        load = self.load_axis
        rpm_norm = (rpm - rpm.min()) / (rpm.max() - rpm.min())  # 0..1
        load_norm = load / 100.0  # 0..1

        rpm_g, load_g = np.meshgrid(rpm_norm, load_norm)

        # Base pulse width: idle ~1.5 ms, peak ~10 ms
        base_pw = 1.5 + 8.5 * load_g

        # RPM correction: higher RPM needs slightly longer PW due to
        # volumetric efficiency curve (peaks ~0.7 normalised RPM)
        ve_curve = 1.0 + 0.12 * np.sin(np.pi * rpm_g)
        pw = base_pw * ve_curve

        # High-RPM enrichment for safety (above 85 % of rev range)
        high_rpm_mask = rpm_g > 0.85
        pw = np.where(high_rpm_mask, pw * (1.0 + 0.05 * (rpm_g - 0.85) / 0.15), pw)

        # Overrun fuel cut (very low load at medium+ RPM)
        overrun = (load_g < 0.05) & (rpm_g > 0.25)
        pw = np.where(overrun, 0.0, pw)

        pw = np.clip(pw, 0.0, 15.0).round(3)

        return ECUMap(
            name="fuel_injection",
            description="Fuel injector pulse width (ms) vs RPM and engine load",
            unit="ms",
            x_axis=MapAxis("RPM", "rpm", rpm.copy()),
            y_axis=MapAxis("Load", "%", load.copy()),
            data=pw,
        )

    # ------------------------------------------------------------------
    # Ignition timing map  (RPM x Load -> degrees BTDC)
    # ------------------------------------------------------------------

    def generate_ignition_map(self) -> ECUMap:
        """Create a stock ignition timing map.

        Values from ~8 deg BTDC at high load / low RPM up to ~35 deg
        at light load / mid RPM.  Timing is conservatively pulled at
        high load to prevent knock.
        """
        rpm = self.rpm_axis
        load = self.load_axis
        rpm_norm = (rpm - rpm.min()) / (rpm.max() - rpm.min())
        load_norm = load / 100.0

        rpm_g, load_g = np.meshgrid(rpm_norm, load_norm)

        # Base timing: light-load cruise ~30 deg, full-load ~12 deg
        base_timing = 30.0 - 18.0 * load_g

        # RPM correction: advance rises with RPM to a plateau
        rpm_advance = 5.0 * (1.0 - np.exp(-3.0 * rpm_g))
        timing = base_timing + rpm_advance

        # Knock-prone region: pull timing above 70 % load and mid RPM
        knock_pull = np.where(
            (load_g > 0.7) & (rpm_g > 0.3),
            -3.0 * load_g * rpm_g,
            0.0,
        )
        timing = timing + knock_pull

        # Turbo engines run less timing under boost
        if self.turbo:
            boost_retard = -2.0 * load_g * (1.0 + rpm_g)
            timing = timing + boost_retard

        timing = np.clip(timing, 0.0, 36.0).round(2)

        return ECUMap(
            name="ignition_timing",
            description="Ignition timing (degrees BTDC) vs RPM and engine load",
            unit="deg BTDC",
            x_axis=MapAxis("RPM", "rpm", rpm.copy()),
            y_axis=MapAxis("Load", "%", load.copy()),
            data=timing,
        )

    # ------------------------------------------------------------------
    # Boost pressure map  (RPM x Throttle -> bar)
    # ------------------------------------------------------------------

    def generate_boost_map(self) -> ECUMap:
        """Create a target boost pressure map (turbocharged engines).

        Returns zero map for naturally-aspirated engines.  Boost ramps
        from 0 at idle up to max_boost_bar at high RPM / high throttle,
        with a safe margin below the wastegate limit.
        """
        rpm = self.rpm_axis
        throttle = self.throttle_axis
        rpm_norm = (rpm - rpm.min()) / (rpm.max() - rpm.min())
        thr_norm = throttle / 100.0

        rpm_g, thr_g = np.meshgrid(rpm_norm, thr_norm)

        if not self.turbo:
            data = np.zeros_like(rpm_g)
        else:
            # Spool-up model: boost builds with RPM (turbo lag below ~2000 rpm)
            spool = 1.0 - np.exp(-4.0 * rpm_g)

            # Throttle demand
            demand = thr_g ** 1.3

            target = self.max_boost_bar * spool * demand

            # Stock safety margin: cap at 90 % of physical max
            target = np.clip(target, 0.0, self.max_boost_bar * 0.90)
            data = target.round(3)

        return ECUMap(
            name="boost_pressure",
            description="Target boost pressure (bar) vs RPM and throttle position",
            unit="bar",
            x_axis=MapAxis("RPM", "rpm", rpm.copy()),
            y_axis=MapAxis("Throttle", "%", throttle.copy()),
            data=data,
        )

    # ------------------------------------------------------------------
    # Variable Valve Timing map  (RPM x Load -> cam degrees)
    # ------------------------------------------------------------------

    def generate_vvt_map(self) -> ECUMap:
        """Create a VVT intake-cam advance map.

        Typical range 0 - 50 cam degrees.  Advance peaks at mid RPM /
        mid load for best overlap-driven torque and drops at idle and
        very high RPM.
        """
        rpm = self.rpm_axis
        load = self.load_axis
        rpm_norm = (rpm - rpm.min()) / (rpm.max() - rpm.min())
        load_norm = load / 100.0

        rpm_g, load_g = np.meshgrid(rpm_norm, load_norm)

        # Bell-shaped advance centred at ~0.5 normalised RPM
        rpm_bell = np.exp(-((rpm_g - 0.50) ** 2) / 0.08)

        # Load factor: partial load benefits most from cam advance
        load_factor = np.sin(np.pi * load_g)

        cam_advance = 45.0 * rpm_bell * load_factor

        # Idle stability: retard cam near idle
        idle_mask = (rpm_g < 0.10) | (load_g < 0.05)
        cam_advance = np.where(idle_mask, 0.0, cam_advance)

        cam_advance = np.clip(cam_advance, 0.0, 50.0).round(2)

        return ECUMap(
            name="vvt_intake",
            description="VVT intake cam advance (degrees) vs RPM and engine load",
            unit="cam deg",
            x_axis=MapAxis("RPM", "rpm", rpm.copy()),
            y_axis=MapAxis("Load", "%", load.copy()),
            data=cam_advance,
        )

    # ------------------------------------------------------------------
    # Throttle response map  (Pedal x RPM -> throttle %)
    # ------------------------------------------------------------------

    def generate_throttle_map(self) -> ECUMap:
        """Create an electronic throttle response map.

        Maps driver pedal-position to actual throttle-body opening,
        including non-linear low-pedal shaping for driveability.
        """
        rpm = self.rpm_axis
        pedal = self.pedal_axis
        rpm_norm = (rpm - rpm.min()) / (rpm.max() - rpm.min())
        pedal_norm = pedal / 100.0

        rpm_g, pedal_g = np.meshgrid(rpm_norm, pedal_norm)

        # Slightly aggressive stock curve (1.15 exponent)
        throttle_opening = 100.0 * pedal_g ** 1.15

        # At very low RPM, limit throttle to prevent stall/jerk
        low_rpm_limit = np.where(rpm_g < 0.10, 0.6 + 0.4 * (rpm_g / 0.10), 1.0)
        throttle_opening = throttle_opening * low_rpm_limit

        throttle_opening = np.clip(throttle_opening, 0.0, 100.0).round(2)

        return ECUMap(
            name="throttle_response",
            description="Throttle body opening (%) vs pedal position and RPM",
            unit="%",
            x_axis=MapAxis("RPM", "rpm", rpm.copy()),
            y_axis=MapAxis("Pedal", "%", pedal.copy()),
            data=throttle_opening,
        )

    # ------------------------------------------------------------------
    # Rev limiter & launch control
    # ------------------------------------------------------------------

    def generate_rev_limiter(self) -> RevLimiterSettings:
        """Return stock rev-limiter settings."""
        return RevLimiterSettings(
            soft_limit_rpm=self.design_rev_limit - 200.0,
            hard_limit_rpm=self.design_rev_limit,
            fuel_cut_percent=100.0,
            ignition_retard_deg=15.0,
        )

    def generate_launch_control(self) -> LaunchControlSettings:
        """Return stock launch-control settings."""
        return LaunchControlSettings(
            enabled=True,
            launch_rpm=min(3500.0, self.design_rev_limit * 0.50),
            max_rpm=min(4000.0, self.design_rev_limit * 0.57),
            ignition_retard_deg=20.0,
            boost_limit_bar=self.max_boost_bar * 0.65 if self.turbo else 0.0,
            time_limit_sec=10.0,
        )

    # ------------------------------------------------------------------
    # Full map-set generation
    # ------------------------------------------------------------------

    def generate_stock_maps(
        self,
        vehicle_info: Optional[dict[str, str]] = None,
    ) -> ECUMapSet:
        """Generate a complete set of stock ECU calibration maps.

        Parameters
        ----------
        vehicle_info:
            Optional dict with keys like ``make``, ``model``, ``year``,
            ``engine`` to tag the map set.

        Returns
        -------
        ECUMapSet
            Contains all maps, rev-limiter, and launch-control settings.
        """
        return ECUMapSet(
            fuel_map=self.generate_fuel_map(),
            ignition_map=self.generate_ignition_map(),
            boost_map=self.generate_boost_map(),
            vvt_map=self.generate_vvt_map(),
            throttle_map=self.generate_throttle_map(),
            rev_limiter=self.generate_rev_limiter(),
            launch_control=self.generate_launch_control(),
            vehicle_info=vehicle_info or {},
        )
