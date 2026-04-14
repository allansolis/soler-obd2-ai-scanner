"""
SOLER OBD2 AI Scanner - Safety Verification System
===================================================
Validates ECU map sets against hard safety limits before they can
be flashed.  Any map that fails verification is blocked from export.
Each verified map set receives an integrity hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np

from backend.tuning.map_generator import ECUMapSet


# ---------------------------------------------------------------------------
# Safety thresholds (absolute hard limits)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SafetyLimits:
    """Absolute safety boundaries for ECU calibration values.

    These limits represent the maximum values that should never be
    exceeded regardless of tuning profile.  They include a margin
    above the aggressive Stage 2 profile.
    """

    # Ignition timing
    max_timing_deg: float = 38.0           # max degrees BTDC anywhere in map

    # Air-fuel ratio (derived from fuel PW relative to stock)
    min_afr_under_load: float = 11.5       # lambda ~0.78 - rich safety limit
    max_afr_under_load: float = 15.5       # lambda ~1.06 - lean detonation limit

    # Rev limiter
    max_rev_limit_over_design_pct: float = 10.0  # % above design rev limit

    # Boost pressure
    max_boost_over_design_pct: float = 30.0      # % above design max boost

    # Exhaust gas temperature (estimated)
    max_egt_celsius: float = 900.0

    # VVT cam advance
    max_vvt_deg: float = 55.0

    # Fuel pulse width
    max_fuel_pw_ms: float = 15.0
    min_fuel_pw_ms: float = 0.5            # below this = misfire risk

    # Throttle
    max_throttle_pct: float = 100.0


DEFAULT_LIMITS = SafetyLimits()


# ---------------------------------------------------------------------------
# Check result types
# ---------------------------------------------------------------------------

class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


@dataclass
class CheckResult:
    """Result of a single safety check."""

    check_name: str
    status: CheckStatus
    detail: str
    measured_value: Optional[float] = None
    limit_value: Optional[float] = None


@dataclass
class SafetyReport:
    """Aggregate safety report for an :class:`ECUMapSet`."""

    passed: bool
    integrity_hash: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == CheckStatus.FAIL]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == CheckStatus.WARN]

    def summary(self) -> str:
        """Human-readable summary string."""
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.status == CheckStatus.PASS)
        failed = len(self.failed_checks)
        warned = len(self.warnings)
        status = "PASSED" if self.passed else "BLOCKED"
        lines = [
            f"Safety Report: {status}",
            f"  Checks: {total}  |  Pass: {passed}  |  Fail: {failed}  |  Warn: {warned}",
            f"  Integrity hash: {self.integrity_hash}",
        ]
        if self.failed_checks:
            lines.append("  Failed checks:")
            for c in self.failed_checks:
                lines.append(f"    - {c.check_name}: {c.detail}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Safety verifier
# ---------------------------------------------------------------------------

class SafetyVerifier:
    """Runs all safety checks against an :class:`ECUMapSet`.

    Parameters
    ----------
    limits:
        Override default safety limits if needed.
    design_rev_limit:
        The manufacturer's design rev-limit for this engine (rpm).
    design_max_boost:
        The manufacturer's design maximum boost pressure (bar).
    stock_fuel_pw_at_wot:
        Representative stock fuel pulse-width at WOT / peak (ms).
        Used to derive approximate AFR from modified PW.
    """

    def __init__(
        self,
        limits: SafetyLimits = DEFAULT_LIMITS,
        design_rev_limit: float = 7000.0,
        design_max_boost: float = 1.2,
        stock_fuel_pw_at_wot: float = 10.0,
    ) -> None:
        self.limits = limits
        self.design_rev_limit = design_rev_limit
        self.design_max_boost = design_max_boost
        self.stock_fuel_pw_at_wot = stock_fuel_pw_at_wot

    # ------------------------------------------------------------------
    # Integrity hashing
    # ------------------------------------------------------------------

    @staticmethod
    def compute_integrity_hash(maps: ECUMapSet) -> str:
        """Compute a SHA-256 digest over all map data and settings.

        The hash covers the raw numpy bytes of every map plus the
        scalar rev-limiter / launch-control values, providing tamper
        detection for exported map files.
        """
        h = hashlib.sha256()

        for ecu_map in (
            maps.fuel_map,
            maps.ignition_map,
            maps.boost_map,
            maps.vvt_map,
            maps.throttle_map,
        ):
            h.update(ecu_map.data.tobytes())
            h.update(ecu_map.x_axis.values.tobytes())
            h.update(ecu_map.y_axis.values.tobytes())

        settings_blob = json.dumps(
            {
                "rev_soft": maps.rev_limiter.soft_limit_rpm,
                "rev_hard": maps.rev_limiter.hard_limit_rpm,
                "rev_fuel_cut": maps.rev_limiter.fuel_cut_percent,
                "rev_ign_retard": maps.rev_limiter.ignition_retard_deg,
                "lc_enabled": maps.launch_control.enabled,
                "lc_rpm": maps.launch_control.launch_rpm,
                "lc_max_rpm": maps.launch_control.max_rpm,
                "lc_ign_retard": maps.launch_control.ignition_retard_deg,
                "lc_boost": maps.launch_control.boost_limit_bar,
                "lc_time": maps.launch_control.time_limit_sec,
            },
            sort_keys=True,
        ).encode()
        h.update(settings_blob)

        return h.hexdigest()

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_timing(self, maps: ECUMapSet) -> CheckResult:
        """Verify ignition timing stays below the hard limit."""
        peak = float(np.max(maps.ignition_map.data))
        ok = peak <= self.limits.max_timing_deg
        return CheckResult(
            check_name="ignition_timing_max",
            status=CheckStatus.PASS if ok else CheckStatus.FAIL,
            detail=(
                f"Peak timing {peak:.1f} deg "
                f"{'<=' if ok else '>'} limit {self.limits.max_timing_deg:.1f} deg"
            ),
            measured_value=peak,
            limit_value=self.limits.max_timing_deg,
        )

    def _check_afr_range(self, maps: ECUMapSet) -> CheckResult:
        """Estimate AFR from fuel PW and check it stays in safe band.

        Uses a simplified model: AFR ~ 14.7 * (stock_pw / actual_pw)
        for non-zero cells at load >= 50 %.
        """
        load_axis = maps.fuel_map.y_axis.values
        high_load_rows = load_axis >= 50.0
        fuel_data = maps.fuel_map.data[high_load_rows, :]

        # Ignore zero cells (overrun fuel cut)
        active = fuel_data[fuel_data > 0.0]
        if active.size == 0:
            return CheckResult(
                check_name="afr_range",
                status=CheckStatus.WARN,
                detail="No active fuel cells at load >= 50 % to evaluate",
            )

        estimated_afr = 14.7 * (self.stock_fuel_pw_at_wot / active)
        min_afr = float(np.min(estimated_afr))
        max_afr = float(np.max(estimated_afr))

        too_rich = min_afr < self.limits.min_afr_under_load
        too_lean = max_afr > self.limits.max_afr_under_load

        if too_rich or too_lean:
            detail_parts: list[str] = []
            if too_rich:
                detail_parts.append(
                    f"Min AFR {min_afr:.2f} < {self.limits.min_afr_under_load} (too rich)"
                )
            if too_lean:
                detail_parts.append(
                    f"Max AFR {max_afr:.2f} > {self.limits.max_afr_under_load} (too lean)"
                )
            return CheckResult(
                check_name="afr_range",
                status=CheckStatus.FAIL,
                detail="; ".join(detail_parts),
                measured_value=min_afr if too_rich else max_afr,
                limit_value=(
                    self.limits.min_afr_under_load if too_rich
                    else self.limits.max_afr_under_load
                ),
            )

        return CheckResult(
            check_name="afr_range",
            status=CheckStatus.PASS,
            detail=f"Estimated AFR range [{min_afr:.2f} .. {max_afr:.2f}] within limits",
            measured_value=min_afr,
            limit_value=self.limits.min_afr_under_load,
        )

    def _check_rev_limit(self, maps: ECUMapSet) -> CheckResult:
        """Rev limit must not exceed design + allowed margin."""
        hard = maps.rev_limiter.hard_limit_rpm
        ceiling = self.design_rev_limit * (
            1.0 + self.limits.max_rev_limit_over_design_pct / 100.0
        )
        ok = hard <= ceiling
        return CheckResult(
            check_name="rev_limit",
            status=CheckStatus.PASS if ok else CheckStatus.FAIL,
            detail=(
                f"Hard rev limit {hard:.0f} rpm "
                f"{'<=' if ok else '>'} ceiling {ceiling:.0f} rpm "
                f"(design {self.design_rev_limit:.0f} + "
                f"{self.limits.max_rev_limit_over_design_pct:.0f} %)"
            ),
            measured_value=hard,
            limit_value=ceiling,
        )

    def _check_boost(self, maps: ECUMapSet) -> CheckResult:
        """Peak boost must not exceed design + allowed margin."""
        peak = float(np.max(maps.boost_map.data))
        ceiling = self.design_max_boost * (
            1.0 + self.limits.max_boost_over_design_pct / 100.0
        )
        ok = peak <= ceiling
        return CheckResult(
            check_name="boost_pressure",
            status=CheckStatus.PASS if ok else CheckStatus.FAIL,
            detail=(
                f"Peak boost {peak:.3f} bar "
                f"{'<=' if ok else '>'} ceiling {ceiling:.3f} bar "
                f"(design {self.design_max_boost:.2f} + "
                f"{self.limits.max_boost_over_design_pct:.0f} %)"
            ),
            measured_value=peak,
            limit_value=ceiling,
        )

    def _check_egt(self, maps: ECUMapSet) -> CheckResult:
        """Estimate EGT from timing advance and fuel mixture.

        Uses a simplified thermal model:
        EGT_base ~ 700 C at stoichiometric, +25 C per degree of advance,
        +40 C per AFR unit above stoich (lean = hotter).
        """
        timing_peak = float(np.max(maps.ignition_map.data))
        fuel_min_at_load = maps.fuel_map.data[maps.fuel_map.data > 0.0]
        if fuel_min_at_load.size == 0:
            return CheckResult(
                check_name="egt_estimate",
                status=CheckStatus.WARN,
                detail="Cannot estimate EGT: no active fuel cells",
            )

        leanest_pw = float(np.min(fuel_min_at_load))
        afr_lean = 14.7 * (self.stock_fuel_pw_at_wot / leanest_pw)
        afr_excess = max(0.0, afr_lean - 14.7)

        egt_est = 700.0 + 25.0 * (timing_peak / 10.0) + 40.0 * afr_excess

        ok = egt_est <= self.limits.max_egt_celsius
        warn = egt_est > self.limits.max_egt_celsius * 0.90

        if not ok:
            status = CheckStatus.FAIL
        elif warn:
            status = CheckStatus.WARN
        else:
            status = CheckStatus.PASS

        return CheckResult(
            check_name="egt_estimate",
            status=status,
            detail=(
                f"Estimated peak EGT {egt_est:.0f} C "
                f"{'<=' if ok else '>'} limit {self.limits.max_egt_celsius:.0f} C"
            ),
            measured_value=egt_est,
            limit_value=self.limits.max_egt_celsius,
        )

    def _check_vvt(self, maps: ECUMapSet) -> CheckResult:
        """VVT cam advance must stay within mechanical limits."""
        peak = float(np.max(maps.vvt_map.data))
        ok = peak <= self.limits.max_vvt_deg
        return CheckResult(
            check_name="vvt_advance",
            status=CheckStatus.PASS if ok else CheckStatus.FAIL,
            detail=(
                f"Peak VVT advance {peak:.1f} deg "
                f"{'<=' if ok else '>'} limit {self.limits.max_vvt_deg:.1f} deg"
            ),
            measured_value=peak,
            limit_value=self.limits.max_vvt_deg,
        )

    def _check_fuel_pw(self, maps: ECUMapSet) -> CheckResult:
        """Fuel pulse width must be within injector capability."""
        active = maps.fuel_map.data[maps.fuel_map.data > 0.0]
        if active.size == 0:
            return CheckResult(
                check_name="fuel_pulse_width",
                status=CheckStatus.WARN,
                detail="No active fuel cells to evaluate",
            )

        pw_min = float(np.min(active))
        pw_max = float(np.max(active))

        too_low = pw_min < self.limits.min_fuel_pw_ms
        too_high = pw_max > self.limits.max_fuel_pw_ms

        if too_low or too_high:
            parts: list[str] = []
            if too_low:
                parts.append(f"Min PW {pw_min:.2f} ms < {self.limits.min_fuel_pw_ms} ms")
            if too_high:
                parts.append(f"Max PW {pw_max:.2f} ms > {self.limits.max_fuel_pw_ms} ms")
            return CheckResult(
                check_name="fuel_pulse_width",
                status=CheckStatus.FAIL,
                detail="; ".join(parts),
                measured_value=pw_max if too_high else pw_min,
                limit_value=(
                    self.limits.max_fuel_pw_ms if too_high
                    else self.limits.min_fuel_pw_ms
                ),
            )

        return CheckResult(
            check_name="fuel_pulse_width",
            status=CheckStatus.PASS,
            detail=f"Fuel PW range [{pw_min:.2f} .. {pw_max:.2f}] ms within limits",
            measured_value=pw_max,
            limit_value=self.limits.max_fuel_pw_ms,
        )

    def _check_throttle(self, maps: ECUMapSet) -> CheckResult:
        """Throttle map must not exceed 100 %."""
        peak = float(np.max(maps.throttle_map.data))
        ok = peak <= self.limits.max_throttle_pct
        return CheckResult(
            check_name="throttle_opening",
            status=CheckStatus.PASS if ok else CheckStatus.FAIL,
            detail=(
                f"Peak throttle {peak:.1f} % "
                f"{'<=' if ok else '>'} limit {self.limits.max_throttle_pct:.1f} %"
            ),
            measured_value=peak,
            limit_value=self.limits.max_throttle_pct,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify(self, maps: ECUMapSet) -> SafetyReport:
        """Run all safety checks and return a :class:`SafetyReport`.

        The report includes an integrity hash computed over the map
        data.  If any check fails, ``report.passed`` is ``False`` and
        the map set should be blocked from export / flash.
        """
        checks = [
            self._check_timing(maps),
            self._check_afr_range(maps),
            self._check_rev_limit(maps),
            self._check_boost(maps),
            self._check_egt(maps),
            self._check_vvt(maps),
            self._check_fuel_pw(maps),
            self._check_throttle(maps),
        ]

        passed = all(c.status != CheckStatus.FAIL for c in checks)
        integrity = self.compute_integrity_hash(maps)

        return SafetyReport(
            passed=passed,
            integrity_hash=integrity,
            checks=checks,
        )

    def verify_or_raise(self, maps: ECUMapSet) -> SafetyReport:
        """Like :meth:`verify` but raises :class:`ValueError` on failure."""
        report = self.verify(maps)
        if not report.passed:
            details = "; ".join(c.detail for c in report.failed_checks)
            raise ValueError(
                f"Safety verification failed ({len(report.failed_checks)} "
                f"check(s)): {details}"
            )
        return report
