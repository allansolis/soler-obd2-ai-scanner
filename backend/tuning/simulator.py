"""
SOLER OBD2 AI Scanner - Performance Simulator
==============================================
Estimates horsepower / torque gains, fuel-consumption changes, and
generates before-vs-after comparison data suitable for frontend
charting from stock and modified :class:`ECUMapSet` instances.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from backend.tuning.map_generator import ECUMapSet


# ---------------------------------------------------------------------------
# Simulation result types
# ---------------------------------------------------------------------------

@dataclass
class CurvePoint:
    """Single point on a dyno-style curve."""

    rpm: float
    value: float  # HP or Nm or L/100km depending on context


@dataclass
class ComparisonCurve:
    """Paired stock / modified curves for a single metric."""

    metric: str
    unit: str
    stock: list[CurvePoint]
    modified: list[CurvePoint]

    def stock_peak(self) -> float:
        return max(p.value for p in self.stock) if self.stock else 0.0

    def modified_peak(self) -> float:
        return max(p.value for p in self.modified) if self.modified else 0.0

    def peak_gain(self) -> float:
        return self.modified_peak() - self.stock_peak()

    def peak_gain_pct(self) -> float:
        sp = self.stock_peak()
        return (self.peak_gain() / sp * 100.0) if sp else 0.0


@dataclass
class SimulationResult:
    """Complete simulation output comparing stock vs modified maps."""

    hp_curve: ComparisonCurve
    torque_curve: ComparisonCurve
    fuel_curve: ComparisonCurve

    hp_gain_pct: float
    torque_gain_pct: float
    fuel_change_pct: float  # positive = higher consumption

    summary: dict[str, float] = field(default_factory=dict)

    def as_chart_data(self) -> dict:
        """Return a JSON-serialisable dict for the frontend."""
        def _curve_to_dict(curve: ComparisonCurve) -> dict:
            return {
                "metric": curve.metric,
                "unit": curve.unit,
                "stock": [{"rpm": p.rpm, "value": round(p.value, 2)} for p in curve.stock],
                "modified": [{"rpm": p.rpm, "value": round(p.value, 2)} for p in curve.modified],
                "stock_peak": round(curve.stock_peak(), 2),
                "modified_peak": round(curve.modified_peak(), 2),
                "peak_gain": round(curve.peak_gain(), 2),
                "peak_gain_pct": round(curve.peak_gain_pct(), 2),
            }

        return {
            "hp": _curve_to_dict(self.hp_curve),
            "torque": _curve_to_dict(self.torque_curve),
            "fuel": _curve_to_dict(self.fuel_curve),
            "summary": {
                "hp_gain_pct": round(self.hp_gain_pct, 2),
                "torque_gain_pct": round(self.torque_gain_pct, 2),
                "fuel_change_pct": round(self.fuel_change_pct, 2),
            },
        }


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class PerformanceSimulator:
    """Estimates performance differences between two ECU map sets.

    The simulator uses a simplified thermodynamic model that accounts
    for:
    - Fuel energy input (proportional to pulse-width)
    - Ignition efficiency (timing vs MBT)
    - Boost contribution to volumetric efficiency
    - VVT contribution to breathing

    Parameters
    ----------
    base_hp:
        Stock peak horsepower of the engine.
    base_torque_nm:
        Stock peak torque in Nm.
    displacement_cc:
        Engine displacement in cc.
    base_fuel_consumption_lp100km:
        Stock fuel consumption in L/100 km at cruise.
    """

    # MBT (Maximum Brake Torque) timing angle estimate
    MBT_TIMING_DEG: float = 32.0

    def __init__(
        self,
        base_hp: float = 200.0,
        base_torque_nm: float = 350.0,
        displacement_cc: float = 2000.0,
        base_fuel_consumption_lp100km: float = 8.5,
    ) -> None:
        self.base_hp = base_hp
        self.base_torque_nm = base_torque_nm
        self.displacement_cc = displacement_cc
        self.base_fuel_lp100km = base_fuel_consumption_lp100km

    # ------------------------------------------------------------------
    # Internal estimation helpers
    # ------------------------------------------------------------------

    def _fuel_energy_ratio(
        self,
        stock_fuel: np.ndarray,
        mod_fuel: np.ndarray,
    ) -> np.ndarray:
        """Ratio of fuel energy input: modified / stock.

        Higher PW = more fuel = more energy available (up to a point).
        """
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(stock_fuel > 0.0, mod_fuel / stock_fuel, 1.0)
        return ratio

    def _timing_efficiency(self, timing_data: np.ndarray) -> np.ndarray:
        """Estimate combustion efficiency as function of timing.

        Peak efficiency occurs at MBT; both retard and excess advance
        reduce efficiency.  Model: eta = 1 - k * (timing - MBT)^2
        """
        deviation = timing_data - self.MBT_TIMING_DEG
        eta = 1.0 - 0.0008 * deviation ** 2
        return np.clip(eta, 0.3, 1.0)

    def _boost_ve_factor(self, boost_data: np.ndarray) -> np.ndarray:
        """Volumetric efficiency multiplier from boost pressure.

        Each bar of boost roughly doubles the air charge compared to
        naturally-aspirated (1.0 bar absolute).
        """
        return 1.0 + boost_data  # bar gauge -> absolute multiplier

    def _vvt_breathing_factor(self, vvt_data: np.ndarray) -> np.ndarray:
        """Small breathing improvement from cam advance.

        Optimal overlap improves mid-range torque.  Model: bell-shaped
        benefit centred at ~25 deg of cam advance.
        """
        benefit = 1.0 + 0.02 * np.exp(-((vvt_data - 25.0) ** 2) / 200.0)
        return benefit

    def _estimate_power_curve(
        self,
        maps: ECUMapSet,
        stock_maps: ECUMapSet,
        base_power: float,
    ) -> list[CurvePoint]:
        """Estimate power at each RPM breakpoint for full-load row.

        Uses the highest load row of each map as the WOT condition.
        """
        rpm_axis = maps.fuel_map.x_axis.values
        n_rpm = len(rpm_axis)

        # Use last row (max load) for WOT
        fuel_stock = stock_maps.fuel_map.data[-1, :]
        fuel_mod = maps.fuel_map.data[-1, :]

        timing_stock = stock_maps.ignition_map.data[-1, :]
        timing_mod = maps.ignition_map.data[-1, :]

        boost_stock = stock_maps.boost_map.data[-1, :]
        boost_mod = maps.boost_map.data[-1, :]

        vvt_stock = stock_maps.vvt_map.data[-1, :]
        vvt_mod = maps.vvt_map.data[-1, :]

        # Efficiency factors
        fuel_ratio = self._fuel_energy_ratio(fuel_stock, fuel_mod)
        eta_stock = self._timing_efficiency(timing_stock)
        eta_mod = self._timing_efficiency(timing_mod)
        boost_ve_stock = self._boost_ve_factor(boost_stock)
        boost_ve_mod = self._boost_ve_factor(boost_mod)
        vvt_stock_f = self._vvt_breathing_factor(vvt_stock)
        vvt_mod_f = self._vvt_breathing_factor(vvt_mod)

        # Combined power multiplier
        with np.errstate(divide="ignore", invalid="ignore"):
            combined = np.where(
                (eta_stock > 0) & (boost_ve_stock > 0) & (vvt_stock_f > 0),
                (fuel_ratio * eta_mod * boost_ve_mod * vvt_mod_f)
                / (eta_stock * boost_ve_stock * vvt_stock_f),
                1.0,
            )

        # Stock power shape: peaks at ~75 % of rev range, tapers at extremes
        rpm_norm = (rpm_axis - rpm_axis.min()) / (rpm_axis.max() - rpm_axis.min())
        power_shape = np.sin(np.pi * rpm_norm * 0.85 + 0.15)
        power_shape = np.clip(power_shape, 0.1, 1.0)

        mod_power = base_power * power_shape * combined

        return [
            CurvePoint(rpm=float(rpm_axis[i]), value=float(mod_power[i]))
            for i in range(n_rpm)
        ]

    def _estimate_torque_from_hp(
        self,
        hp_curve: list[CurvePoint],
    ) -> list[CurvePoint]:
        """Derive torque from HP: Torque(Nm) = HP * 745.7 / (RPM * 2pi/60)."""
        torque_points: list[CurvePoint] = []
        for p in hp_curve:
            if p.rpm > 0:
                torque = p.value * 7120.0 / p.rpm  # HP * 5252 (ft-lb) then * 1.3558 -> Nm
            else:
                torque = 0.0
            torque_points.append(CurvePoint(rpm=p.rpm, value=torque))
        return torque_points

    def _estimate_fuel_consumption_curve(
        self,
        stock_maps: ECUMapSet,
        mod_maps: ECUMapSet,
    ) -> list[CurvePoint]:
        """Estimate fuel consumption change at partial load (cruise row).

        Uses ~30 % load row as a representative cruise condition.
        """
        rpm_axis = stock_maps.fuel_map.x_axis.values
        load_axis = stock_maps.fuel_map.y_axis.values

        # Find row closest to 30 % load
        cruise_idx = int(np.argmin(np.abs(load_axis - 30.0)))

        fuel_stock = stock_maps.fuel_map.data[cruise_idx, :]
        fuel_mod = mod_maps.fuel_map.data[cruise_idx, :]

        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(fuel_stock > 0.0, fuel_mod / fuel_stock, 1.0)

        consumption = self.base_fuel_lp100km * ratio

        return [
            CurvePoint(rpm=float(rpm_axis[i]), value=float(consumption[i]))
            for i in range(len(rpm_axis))
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def simulate(
        self,
        stock_maps: ECUMapSet,
        modified_maps: ECUMapSet,
    ) -> SimulationResult:
        """Run a full comparison simulation.

        Parameters
        ----------
        stock_maps:
            The baseline (unmodified) map set.
        modified_maps:
            The tuned map set to evaluate.

        Returns
        -------
        SimulationResult
            Contains HP, torque, and fuel curves with gain percentages.
        """
        # HP curves
        stock_hp_points = self._estimate_power_curve(
            stock_maps, stock_maps, self.base_hp,
        )
        mod_hp_points = self._estimate_power_curve(
            modified_maps, stock_maps, self.base_hp,
        )

        hp_curve = ComparisonCurve(
            metric="Horsepower",
            unit="HP",
            stock=stock_hp_points,
            modified=mod_hp_points,
        )

        # Torque curves
        stock_tq = self._estimate_torque_from_hp(stock_hp_points)
        mod_tq = self._estimate_torque_from_hp(mod_hp_points)

        torque_curve = ComparisonCurve(
            metric="Torque",
            unit="Nm",
            stock=stock_tq,
            modified=mod_tq,
        )

        # Fuel consumption curves
        stock_fuel_pts = self._estimate_fuel_consumption_curve(stock_maps, stock_maps)
        mod_fuel_pts = self._estimate_fuel_consumption_curve(stock_maps, modified_maps)

        fuel_curve = ComparisonCurve(
            metric="Fuel Consumption",
            unit="L/100km",
            stock=stock_fuel_pts,
            modified=mod_fuel_pts,
        )

        # Summary percentages
        hp_gain_pct = hp_curve.peak_gain_pct()
        tq_gain_pct = torque_curve.peak_gain_pct()

        # Average fuel change across cruise RPM points
        stock_fuel_avg = np.mean([p.value for p in stock_fuel_pts if p.value > 0])
        mod_fuel_avg = np.mean([p.value for p in mod_fuel_pts if p.value > 0])
        fuel_change_pct = (
            ((mod_fuel_avg - stock_fuel_avg) / stock_fuel_avg * 100.0)
            if stock_fuel_avg > 0 else 0.0
        )

        return SimulationResult(
            hp_curve=hp_curve,
            torque_curve=torque_curve,
            fuel_curve=fuel_curve,
            hp_gain_pct=hp_gain_pct,
            torque_gain_pct=tq_gain_pct,
            fuel_change_pct=fuel_change_pct,
            summary={
                "stock_peak_hp": hp_curve.stock_peak(),
                "modified_peak_hp": hp_curve.modified_peak(),
                "stock_peak_torque_nm": torque_curve.stock_peak(),
                "modified_peak_torque_nm": torque_curve.modified_peak(),
                "stock_avg_fuel_lp100km": stock_fuel_avg,
                "modified_avg_fuel_lp100km": mod_fuel_avg,
            },
        )
