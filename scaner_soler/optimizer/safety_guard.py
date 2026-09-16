from dataclasses import dataclass
import numpy as np


class SafetyError(Exception):
    pass


@dataclass
class SafetyLimits:
    max_ignition_advance: float = 45.0      # degrees BTDC absolute
    min_lambda_wot: float = 0.78            # richest allowed at WOT
    max_lambda_idle: float = 1.05           # leanest allowed at idle
    max_boost_bar: float = 2.5             # absolute pressure bar
    max_egt_celsius: float = 980.0
    max_coolant_celsius: float = 105.0
    max_rpm_margin: int = 200              # above OEM redline


STREET   = SafetyLimits()
TRACK    = SafetyLimits(max_ignition_advance=45, min_lambda_wot=0.85, max_boost_bar=2.2)
RACE     = SafetyLimits(max_ignition_advance=45, min_lambda_wot=0.78, max_boost_bar=2.5)

PROFILES = {"street": STREET, "track": TRACK, "race": RACE}


class SafetyGuard:

    def __init__(self, limits: SafetyLimits | None = None, profile: str = "track"):
        self.limits = limits or PROFILES.get(profile, TRACK)

    def validate_ignition_map(self, values: np.ndarray) -> list[str]:
        violations = []
        if values.max() > self.limits.max_ignition_advance:
            idx = np.unravel_index(values.argmax(), values.shape)
            violations.append(
                f"Avance maximo {values.max():.1f}° excede limite "
                f"{self.limits.max_ignition_advance}° en celda {idx}"
            )
        return violations

    def validate_fuel_map(self, lambda_values: np.ndarray) -> list[str]:
        violations = []
        if lambda_values.min() < self.limits.min_lambda_wot:
            idx = np.unravel_index(lambda_values.argmin(), lambda_values.shape)
            violations.append(
                f"Lambda minimo {lambda_values.min():.3f} por debajo del limite "
                f"{self.limits.min_lambda_wot} en celda {idx}"
            )
        return violations

    def validate_boost_map(self, boost_bar: np.ndarray) -> list[str]:
        violations = []
        if boost_bar.max() > self.limits.max_boost_bar:
            idx = np.unravel_index(boost_bar.argmax(), boost_bar.shape)
            violations.append(
                f"Boost maximo {boost_bar.max():.2f} bar excede limite "
                f"{self.limits.max_boost_bar} bar en celda {idx}"
            )
        return violations

    def validate_all(self, ignition: np.ndarray | None = None,
                     fuel_lambda: np.ndarray | None = None,
                     boost: np.ndarray | None = None) -> list[str]:
        all_violations = []
        if ignition is not None:
            all_violations += self.validate_ignition_map(ignition)
        if fuel_lambda is not None:
            all_violations += self.validate_fuel_map(fuel_lambda)
        if boost is not None:
            all_violations += self.validate_boost_map(boost)
        return all_violations

    def assert_safe(self, ignition=None, fuel_lambda=None, boost=None):
        violations = self.validate_all(ignition, fuel_lambda, boost)
        if violations:
            raise SafetyError("Mapa rechazado por SafetyGuard:\n" + "\n".join(f"  • {v}" for v in violations))
