import numpy as np
from scipy.optimize import minimize

from ..ecu.maps.map_table import MapTable
from .safety_guard import SafetyGuard, SafetyLimits, PROFILES


# Simplified torque estimator — replace with dyno-validated model per engine
def _estimate_torque(advance_flat: np.ndarray, shape: tuple,
                     base_torque: float = 100.0) -> float:
    advance = advance_flat.reshape(shape)
    # MBT advance is roughly linear up to peak, then falls off
    peak_advance = 35.0
    torque_map = base_torque * (1.0 - ((advance - peak_advance) / peak_advance) ** 2)
    return float(torque_map.mean())


def _estimate_egt(advance_flat: np.ndarray, shape: tuple,
                  base_egt: float = 700.0) -> float:
    advance = advance_flat.reshape(shape)
    # More advance = higher EGT (approximation)
    return base_egt + (advance.mean() - 25.0) * 5.0


class MapOptimizer:

    # ── Profile presets ────────────────────────────────────────────────────

    PROFILE_PARAMS = {
        "street": {
            "lambda_target": 1.0,
            "advance_margin": -2.0,     # degrees below MBT
            "boost_factor": 0.85,
            "description": "Economia + confort. Lambda estequiometrico, avance conservador.",
        },
        "track": {
            "lambda_target": 0.88,
            "advance_margin": 0.0,      # at MBT with knock safety margin
            "boost_factor": 1.0,
            "description": "Potencia maxima. Lambda rico, boost max seguro, EGT<950C.",
        },
        "race": {
            "lambda_target": 0.83,
            "advance_margin": 0.5,      # slightly past MBT for race fuel
            "boost_factor": 1.0,
            "description": "Carrera en circuito cerrado. Lambda muy rico, boost fisico.",
        },
    }

    def __init__(self, profile: str = "track", fuel_grade: int = 95):
        if profile not in self.PROFILE_PARAMS:
            raise ValueError(f"Perfil desconocido: {profile}. Opciones: {list(self.PROFILE_PARAMS)}")
        self.profile = profile
        self.params = self.PROFILE_PARAMS[profile]
        self.fuel_grade = fuel_grade
        self.guard = SafetyGuard(profile=profile)

    # ── Knock limit by octane ──────────────────────────────────────────────

    def _knock_limit(self) -> float:
        # Rough MBT knock limit by octane: 87oct≈28°, 91oct≈32°, 95oct≈36°, 98oct≈40°, E85≈45°
        grade_map = {87: 28.0, 91: 32.0, 95: 36.0, 98: 40.0, 100: 42.0, 104: 45.0}
        grades = sorted(grade_map.keys())
        if self.fuel_grade <= grades[0]:
            return grade_map[grades[0]]
        if self.fuel_grade >= grades[-1]:
            return grade_map[grades[-1]]
        for i in range(len(grades) - 1):
            if grades[i] <= self.fuel_grade <= grades[i + 1]:
                t = (self.fuel_grade - grades[i]) / (grades[i + 1] - grades[i])
                return grade_map[grades[i]] + t * (grade_map[grades[i + 1]] - grade_map[grades[i]])
        return 35.0

    # ── SLSQP optimizer ────────────────────────────────────────────────────

    def optimize_ignition(self, base_table: MapTable,
                          max_egt: float = 950.0,
                          max_iter: int = 500) -> MapTable:
        shape = base_table.values.shape
        knock_lim = self._knock_limit() + self.params["advance_margin"]
        safe_max = min(base_table.max_safe, knock_lim)

        def objective(x):
            return -_estimate_torque(x, shape)

        def egt_constraint(x):
            egt = _estimate_egt(x, shape)
            return max_egt - egt

        constraints = [{"type": "ineq", "fun": egt_constraint}]
        bounds = [(base_table.min_safe, safe_max)] * base_table.values.size
        x0 = np.clip(base_table.values.flatten(), base_table.min_safe, safe_max)

        result = minimize(
            objective, x0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": max_iter, "ftol": 1e-8},
        )

        optimized_values = np.clip(
            result.x.reshape(shape),
            base_table.min_safe, safe_max
        )
        # Safety gate
        self.guard.validate_ignition_map(optimized_values)

        new_table = MapTable(
            name=f"{base_table.name}_opt_{self.profile}",
            rpm_axis=base_table.rpm_axis.copy(),
            load_axis=base_table.load_axis.copy(),
            values=optimized_values,
            unit=base_table.unit,
            min_safe=base_table.min_safe,
            max_safe=base_table.max_safe,
            description=f"Optimizado — perfil {self.profile}, {self.fuel_grade}oct. "
                        f"Success={result.success}",
        )
        return new_table

    def apply_lambda_profile(self, fuel_table: MapTable) -> MapTable:
        """Scale fuel table toward the profile's lambda target."""
        target = self.params["lambda_target"]
        # Current lambda assumed ~1.0 for street map base
        scale = 1.0 / target     # <1.0 means richer (more fuel)
        new_values = np.clip(fuel_table.values * scale, fuel_table.min_safe, fuel_table.max_safe)
        self.guard.validate_fuel_map(new_values)
        return MapTable(
            name=f"{fuel_table.name}_lambda_{target:.2f}",
            rpm_axis=fuel_table.rpm_axis.copy(),
            load_axis=fuel_table.load_axis.copy(),
            values=new_values,
            unit=fuel_table.unit,
            min_safe=fuel_table.min_safe,
            max_safe=fuel_table.max_safe,
            description=f"Lambda {target:.2f} — perfil {self.profile}",
        )

    def summary(self, base: MapTable, optimized: MapTable) -> str:
        base_mean = base.values.mean()
        opt_mean = optimized.values.mean()
        gain_pct = (opt_mean - base_mean) / base_mean * 100 if base_mean else 0
        return (
            f"Perfil:     {self.profile.upper()}\n"
            f"Combustible:{self.fuel_grade} octanos\n"
            f"Lambda obj: {self.params['lambda_target']}\n"
            f"Knock lim:  {self._knock_limit():.1f}°\n"
            f"Avance med. base:  {base_mean:.2f}°\n"
            f"Avance med. opt:   {opt_mean:.2f}°\n"
            f"Variacion media:   {gain_pct:+.1f}%\n"
            f"Descripcion: {self.params['description']}"
        )
