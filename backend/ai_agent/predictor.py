"""
SOLER OBD2 AI Scanner - Predictor de Fallas
=============================================
Analiza tendencias de sensores en el tiempo para detectar patrones
de degradacion, predecir fallas de componentes y generar
recomendaciones de mantenimiento preventivo.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums y tipos
# ---------------------------------------------------------------------------

class DegradationLevel(str, Enum):
    """Nivel de degradacion de un componente."""
    NORMAL = "normal"
    LEVE = "leve"
    MODERADO = "moderado"
    AVANZADO = "avanzado"
    CRITICO = "critico"


class TrendDirection(str, Enum):
    """Direccion de la tendencia."""
    ESTABLE = "estable"
    SUBIENDO = "subiendo"
    BAJANDO = "bajando"
    ERRATICO = "erratico"


class MaintenanceUrgency(str, Enum):
    """Urgencia de la recomendacion de mantenimiento."""
    RUTINA = "rutina"
    PRONTO = "pronto"
    URGENTE = "urgente"
    INMEDIATO = "inmediato"


# ---------------------------------------------------------------------------
# Modelos de datos
# ---------------------------------------------------------------------------

@dataclass
class SensorTrend:
    """Tendencia analizada de un sensor."""
    sensor_name: str
    direction: TrendDirection
    change_rate: float  # Cambio por hora
    change_percent: float  # Cambio porcentual total
    current_value: float
    predicted_value_24h: float
    predicted_value_7d: float
    confidence: float
    sample_count: int
    time_span_hours: float
    description: str


@dataclass
class ComponentPrediction:
    """Prediccion de falla de un componente."""
    component: str
    system: str
    degradation_level: DegradationLevel
    estimated_remaining_life_km: Optional[int]
    estimated_remaining_life_days: Optional[int]
    failure_probability_30d: float  # Probabilidad de falla en 30 dias
    failure_probability_90d: float  # Probabilidad de falla en 90 dias
    symptoms: list[str]
    evidence: list[str]
    confidence: float
    description: str


@dataclass
class MaintenanceRecommendation:
    """Recomendacion de mantenimiento."""
    component: str
    action: str
    urgency: MaintenanceUrgency
    estimated_cost_range: tuple[int, int]  # (min, max) en USD aproximado
    reason: str
    consequences_if_ignored: str
    recommended_by_km: Optional[int] = None
    recommended_by_date: Optional[str] = None


@dataclass
class PredictionReport:
    """Reporte completo de predicciones."""
    timestamp: datetime
    vehicle_vin: str
    sensor_trends: list[SensorTrend]
    component_predictions: list[ComponentPrediction]
    maintenance_schedule: list[MaintenanceRecommendation]
    overall_risk_score: float  # 0-100 (0 = sin riesgo)
    summary: str  # Resumen en espanol


# ---------------------------------------------------------------------------
# Patrones de degradacion conocidos
# ---------------------------------------------------------------------------

DEGRADATION_PATTERNS: list[dict[str, Any]] = [
    {
        "name": "Degradacion del catalizador",
        "sensors": {
            "catalyst_temp": {"trend": "subiendo", "threshold_high": 800},
        },
        "dtc_indicators": ["P0420", "P0430"],
        "component": "Catalizador",
        "system": "catalizador",
        "typical_life_km": 150000,
        "symptoms": [
            "Olor a huevo podrido en el escape",
            "Perdida gradual de potencia",
            "Mayor consumo de combustible",
        ],
        "failure_consequences": "Aumento severo de emisiones. Posible obstruccion total del escape.",
        "estimated_cost": (300, 1500),
    },
    {
        "name": "Desgaste de bujias",
        "sensors": {
            "rpm": {"trend": "erratico", "variance_threshold": 100},
        },
        "dtc_indicators": ["P0300", "P0301", "P0302", "P0303", "P0304"],
        "component": "Bujias de encendido",
        "system": "encendido",
        "typical_life_km": 60000,
        "symptoms": [
            "Ralenti irregular",
            "Dificultad para arrancar en frio",
            "Perdida de potencia en aceleracion",
        ],
        "failure_consequences": "Fallas de encendido frecuentes. Danio al catalizador.",
        "estimated_cost": (40, 200),
    },
    {
        "name": "Degradacion de la bomba de combustible",
        "sensors": {
            "fuel_pressure": {"trend": "bajando", "threshold_low": 35},
            "long_fuel_trim_1": {"trend": "subiendo", "threshold_high": 15},
        },
        "dtc_indicators": ["P0087", "P0171", "P0174"],
        "component": "Bomba de combustible",
        "system": "combustible",
        "typical_life_km": 200000,
        "symptoms": [
            "Perdida de potencia en aceleracion fuerte",
            "Motor se cala en subidas",
            "Ruido zumbido del tanque de combustible",
        ],
        "failure_consequences": "Motor se detiene sin aviso. Vehiculo inmovil.",
        "estimated_cost": (200, 800),
    },
    {
        "name": "Degradacion del termostato",
        "sensors": {
            "coolant_temp": {"trend": "bajando", "threshold_low": 75},
        },
        "dtc_indicators": ["P0128", "P0125"],
        "component": "Termostato",
        "system": "refrigeracion",
        "typical_life_km": 120000,
        "symptoms": [
            "Motor tarda mucho en calentar",
            "Calefaccion debil",
            "Mayor consumo de combustible",
        ],
        "failure_consequences": "Mayor desgaste del motor por operacion en frio. 10-15% mas de consumo.",
        "estimated_cost": (30, 150),
    },
    {
        "name": "Degradacion del alternador",
        "sensors": {
            "control_module_voltage": {"trend": "bajando", "threshold_low": 13.0},
        },
        "dtc_indicators": ["P0562"],
        "component": "Alternador",
        "system": "electrico",
        "typical_life_km": 180000,
        "symptoms": [
            "Luces que parpadean o se atenuan",
            "Bateria se descarga frecuentemente",
            "Ruido de rodamiento o chillido",
        ],
        "failure_consequences": "Bateria muerta. Vehiculo inmovil. Posible danio a electronicos.",
        "estimated_cost": (200, 600),
    },
    {
        "name": "Degradacion de sensor O2",
        "sensors": {
            "long_fuel_trim_1": {"trend": "erratico", "variance_threshold": 5},
        },
        "dtc_indicators": ["P0133", "P0130", "P0135"],
        "component": "Sensor de oxigeno delantero",
        "system": "sensor_o2",
        "typical_life_km": 120000,
        "symptoms": [
            "Mayor consumo de combustible",
            "Ralenti ligeramente inestable",
            "Olor a combustible en el escape",
        ],
        "failure_consequences": "Mezcla constantemente incorrecta. Danio acelerado al catalizador.",
        "estimated_cost": (80, 300),
    },
    {
        "name": "Degradacion de bobinas de encendido",
        "sensors": {
            "rpm": {"trend": "erratico", "variance_threshold": 80},
        },
        "dtc_indicators": ["P0351", "P0352", "P0353", "P0354"],
        "component": "Bobinas de encendido",
        "system": "encendido",
        "typical_life_km": 100000,
        "symptoms": [
            "Tiron al acelerar",
            "Falla intermitente en un cilindro",
            "Dificultad para arrancar",
        ],
        "failure_consequences": "Falla de encendido permanente en cilindro. Danio al catalizador.",
        "estimated_cost": (50, 250),
    },
    {
        "name": "Desgaste de embragues de transmision",
        "sensors": {
            "trans_temp": {"trend": "subiendo", "threshold_high": 110},
        },
        "dtc_indicators": ["P0730", "P0731", "P0732", "P0733"],
        "component": "Embragues de transmision automatica",
        "system": "transmision",
        "typical_life_km": 200000,
        "symptoms": [
            "Cambios bruscos o tardios",
            "Deslizamiento al acelerar",
            "Vibracion al cambiar marchas",
        ],
        "failure_consequences": "Falla total de transmision. Reparacion muy costosa.",
        "estimated_cost": (1500, 4000),
    },
    {
        "name": "Degradacion del sensor MAF",
        "sensors": {
            "long_fuel_trim_1": {"trend": "subiendo", "threshold_high": 12},
            "long_fuel_trim_2": {"trend": "subiendo", "threshold_high": 12},
        },
        "dtc_indicators": ["P0101", "P0171", "P0174"],
        "component": "Sensor MAF",
        "system": "combustible",
        "typical_life_km": 150000,
        "symptoms": [
            "Mayor consumo de combustible gradual",
            "Perdida leve de potencia",
            "Ralenti ligeramente irregular",
        ],
        "failure_consequences": "Mezcla pobre que dania el catalizador. Perdida de potencia.",
        "estimated_cost": (60, 350),
    },
    {
        "name": "Degradacion de rodamiento de turbo",
        "sensors": {
            "boost_pressure": {"trend": "bajando", "threshold_low": 90},
            "oil_temp": {"trend": "subiendo", "threshold_high": 120},
        },
        "dtc_indicators": ["P0299"],
        "component": "Turbocompresor",
        "system": "turbo",
        "typical_life_km": 180000,
        "symptoms": [
            "Silbido anormal del turbo",
            "Perdida progresiva de potencia",
            "Humo azul en el escape",
            "Consumo de aceite elevado",
        ],
        "failure_consequences": "Falla catastrofica del turbo. Fragmentos pueden danar el motor.",
        "estimated_cost": (800, 3000),
    },
    {
        "name": "Desgaste de cadena de distribucion",
        "sensors": {},
        "dtc_indicators": ["P0011", "P0016", "P0017", "P0021", "P0341"],
        "component": "Cadena de distribucion",
        "system": "motor",
        "typical_life_km": 250000,
        "symptoms": [
            "Ruido de cascabeleo al arrancar en frio",
            "Ralenti irregular al arrancar",
            "Luz de check engine por VVT",
        ],
        "failure_consequences": "Salto de cadena = contacto valvulas/pistones = danio catastrofico del motor.",
        "estimated_cost": (500, 2000),
    },
    {
        "name": "Degradacion del sistema de frenos ABS",
        "sensors": {},
        "dtc_indicators": ["C0035", "C0045", "C0055", "C0065"],
        "component": "Sistema ABS",
        "system": "abs",
        "typical_life_km": 200000,
        "symptoms": [
            "Luz de ABS encendida",
            "Frenado sin asistencia ABS",
            "Vibracion anormal al frenar",
        ],
        "failure_consequences": "Bloqueo de ruedas en frenado de emergencia. Mayor distancia de frenado.",
        "estimated_cost": (100, 500),
    },
]

# ---------------------------------------------------------------------------
# Programa de mantenimiento base
# ---------------------------------------------------------------------------

BASE_MAINTENANCE_SCHEDULE: list[dict[str, Any]] = [
    {
        "component": "Aceite de motor y filtro",
        "interval_km": 10000,
        "interval_months": 6,
        "urgency_overdue_factor": 1.3,
        "estimated_cost": (40, 100),
        "consequences": "Desgaste acelerado del motor. Posible danio a cojinetes.",
    },
    {
        "component": "Filtro de aire del motor",
        "interval_km": 30000,
        "interval_months": 24,
        "urgency_overdue_factor": 1.5,
        "estimated_cost": (15, 50),
        "consequences": "Restriccion de aire, mayor consumo. Posible contaminacion del MAF.",
    },
    {
        "component": "Bujias de encendido",
        "interval_km": 60000,
        "interval_months": 48,
        "urgency_overdue_factor": 1.2,
        "estimated_cost": (40, 200),
        "consequences": "Fallas de encendido, mayor consumo, danio al catalizador.",
    },
    {
        "component": "Fluido de transmision",
        "interval_km": 60000,
        "interval_months": 48,
        "urgency_overdue_factor": 1.3,
        "estimated_cost": (80, 250),
        "consequences": "Degradacion del fluido, cambios bruscos, desgaste acelerado.",
    },
    {
        "component": "Refrigerante del motor",
        "interval_km": 60000,
        "interval_months": 36,
        "urgency_overdue_factor": 1.4,
        "estimated_cost": (50, 150),
        "consequences": "Corrosion interna, obstruccion del radiador, sobrecalentamiento.",
    },
    {
        "component": "Liquido de frenos",
        "interval_km": 40000,
        "interval_months": 24,
        "urgency_overdue_factor": 1.5,
        "estimated_cost": (30, 80),
        "consequences": "Punto de ebullicion bajo, frenado esponjoso, riesgo de falla.",
    },
    {
        "component": "Correa de accesorios",
        "interval_km": 80000,
        "interval_months": 60,
        "urgency_overdue_factor": 1.2,
        "estimated_cost": (30, 120),
        "consequences": "Rotura de correa, perdida de alternador/AC/direccion.",
    },
    {
        "component": "Filtro de combustible",
        "interval_km": 40000,
        "interval_months": 36,
        "urgency_overdue_factor": 1.3,
        "estimated_cost": (20, 80),
        "consequences": "Restriccion de flujo, presion baja, danio a bomba e inyectores.",
    },
    {
        "component": "Pastillas de freno",
        "interval_km": 50000,
        "interval_months": 36,
        "urgency_overdue_factor": 1.5,
        "estimated_cost": (80, 300),
        "consequences": "Frenado insuficiente. Danio a discos de freno.",
    },
    {
        "component": "Bateria",
        "interval_km": 0,
        "interval_months": 48,
        "urgency_overdue_factor": 1.3,
        "estimated_cost": (80, 250),
        "consequences": "No arranca. Danio a alternador por sobrecarga.",
    },
]


# ---------------------------------------------------------------------------
# Predictor de fallas
# ---------------------------------------------------------------------------

class FailurePredictor:
    """Predictor de fallas vehiculares basado en tendencias de sensores."""

    def __init__(self) -> None:
        self._degradation_patterns = DEGRADATION_PATTERNS
        self._maintenance_schedule = BASE_MAINTENANCE_SCHEDULE

    # ------------------------------------------------------------------
    # Analisis principal
    # ------------------------------------------------------------------

    async def predict(
        self,
        sensor_history: list[dict[str, Any]],
        current_data: dict[str, Any],
        vehicle_info: Optional[dict[str, Any]] = None,
        mileage: Optional[int] = None,
        last_service_km: Optional[int] = None,
    ) -> PredictionReport:
        """Genera un reporte completo de predicciones.

        Args:
            sensor_history: Lista de lecturas historicas
                [{timestamp, sensors: {name: value}, ...}].
            current_data: Datos actuales {sensors: {...}, dtcs: [...]}.
            vehicle_info: Info del vehiculo {make, model, year, engine}.
            mileage: Kilometraje actual.
            last_service_km: Kilometraje del ultimo servicio.

        Returns:
            PredictionReport completo.
        """
        vin = ""
        if vehicle_info:
            vin = vehicle_info.get("vin", "")

        # 1. Analizar tendencias de sensores
        sensor_trends = self._analyze_sensor_trends(sensor_history, current_data)

        # 2. Predecir fallas de componentes
        component_predictions = self._predict_component_failures(
            sensor_trends, current_data, mileage
        )

        # 3. Generar programa de mantenimiento
        maintenance = self._generate_maintenance_schedule(
            component_predictions, mileage, last_service_km
        )

        # 4. Calcular riesgo general
        risk_score = self._calculate_risk_score(
            component_predictions, sensor_trends
        )

        # 5. Generar resumen
        summary = self._generate_summary(
            risk_score, component_predictions, maintenance
        )

        return PredictionReport(
            timestamp=datetime.now(),
            vehicle_vin=vin,
            sensor_trends=sensor_trends,
            component_predictions=component_predictions,
            maintenance_schedule=maintenance,
            overall_risk_score=round(risk_score, 1),
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Analisis de tendencias
    # ------------------------------------------------------------------

    def _analyze_sensor_trends(
        self,
        history: list[dict[str, Any]],
        current_data: dict[str, Any],
    ) -> list[SensorTrend]:
        """Analiza tendencias de sensores basado en historial."""
        trends: list[SensorTrend] = []

        if not history:
            return trends

        # Agrupar datos por sensor
        sensor_data: dict[str, list[tuple[float, float]]] = {}

        for record in history:
            ts = record.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts) if isinstance(ts, str) else datetime.fromtimestamp(ts)
                epoch = dt.timestamp()
            except (ValueError, TypeError, OSError):
                continue

            sensors = record.get("sensors", {})
            for name, value in sensors.items():
                if value is not None and isinstance(value, (int, float)):
                    if name not in sensor_data:
                        sensor_data[name] = []
                    sensor_data[name].append((epoch, float(value)))

        # Agregar datos actuales
        current_sensors = current_data.get("sensors", {})
        now_epoch = time.time()
        for name, value in current_sensors.items():
            if value is not None and isinstance(value, (int, float)):
                if name not in sensor_data:
                    sensor_data[name] = []
                sensor_data[name].append((now_epoch, float(value)))

        # Analizar cada sensor
        for sensor_name, data_points in sensor_data.items():
            if len(data_points) < 3:
                continue

            # Ordenar por tiempo
            data_points.sort(key=lambda x: x[0])

            trend = self._calculate_trend(sensor_name, data_points)
            if trend:
                trends.append(trend)

        return trends

    def _calculate_trend(
        self,
        sensor_name: str,
        data_points: list[tuple[float, float]],
    ) -> Optional[SensorTrend]:
        """Calcula la tendencia de un sensor individual."""
        n = len(data_points)
        if n < 3:
            return None

        times = [p[0] for p in data_points]
        values = [p[1] for p in data_points]

        # Regresion lineal simple
        mean_t = sum(times) / n
        mean_v = sum(values) / n

        numerator = sum((t - mean_t) * (v - mean_v) for t, v in zip(times, values))
        denominator = sum((t - mean_t) ** 2 for t in times)

        if denominator == 0:
            return None

        slope = numerator / denominator  # Cambio por segundo
        slope_per_hour = slope * 3600

        # R-squared para confianza
        ss_res = sum((v - (mean_v + slope * (t - mean_t))) ** 2 for t, v in zip(times, values))
        ss_tot = sum((v - mean_v) ** 2 for v in values)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        # Varianza para detectar erraticidad
        variance = sum((v - mean_v) ** 2 for v in values) / n
        std_dev = math.sqrt(variance) if variance > 0 else 0

        # Coeficiente de variacion
        cv = (std_dev / abs(mean_v)) * 100 if mean_v != 0 else 0

        # Determinar direccion
        time_span_hours = (times[-1] - times[0]) / 3600

        if cv > 20 and r_squared < 0.3:
            direction = TrendDirection.ERRATICO
        elif abs(slope_per_hour) < 0.01:
            direction = TrendDirection.ESTABLE
        elif slope_per_hour > 0:
            direction = TrendDirection.SUBIENDO
        else:
            direction = TrendDirection.BAJANDO

        # Cambio porcentual
        first_value = values[0]
        last_value = values[-1]
        change_pct = ((last_value - first_value) / abs(first_value) * 100) if first_value != 0 else 0

        # Predicciones
        predicted_24h = last_value + slope_per_hour * 24
        predicted_7d = last_value + slope_per_hour * 168

        # Confianza basada en R-squared y cantidad de muestras
        confidence = max(0.2, min(0.95, r_squared * 0.7 + min(n / 20, 0.3)))

        # Descripcion
        direction_text = {
            TrendDirection.ESTABLE: "estable",
            TrendDirection.SUBIENDO: "subiendo",
            TrendDirection.BAJANDO: "bajando",
            TrendDirection.ERRATICO: "erratico",
        }[direction]

        description = (
            f"Sensor '{sensor_name}' muestra tendencia {direction_text} "
            f"({change_pct:+.1f}%) en {time_span_hours:.1f} horas. "
            f"Valor actual: {last_value:.2f}."
        )

        return SensorTrend(
            sensor_name=sensor_name,
            direction=direction,
            change_rate=round(slope_per_hour, 4),
            change_percent=round(change_pct, 2),
            current_value=last_value,
            predicted_value_24h=round(predicted_24h, 2),
            predicted_value_7d=round(predicted_7d, 2),
            confidence=round(confidence, 2),
            sample_count=n,
            time_span_hours=round(time_span_hours, 2),
            description=description,
        )

    # ------------------------------------------------------------------
    # Prediccion de fallas de componentes
    # ------------------------------------------------------------------

    def _predict_component_failures(
        self,
        trends: list[SensorTrend],
        current_data: dict[str, Any],
        mileage: Optional[int],
    ) -> list[ComponentPrediction]:
        """Predice fallas de componentes basado en tendencias y DTCs."""
        predictions: list[ComponentPrediction] = []
        dtcs = set(self._extract_dtcs(current_data))

        trend_map = {t.sensor_name: t for t in trends}

        for pattern in self._degradation_patterns:
            evidence: list[str] = []
            score = 0.0

            # Verificar DTCs indicadores
            matching_dtcs = dtcs & set(pattern["dtc_indicators"])
            if matching_dtcs:
                score += 0.4 * (len(matching_dtcs) / len(pattern["dtc_indicators"]))
                evidence.append(
                    f"DTCs presentes: {', '.join(matching_dtcs)}"
                )

            # Verificar tendencias de sensores
            sensor_patterns = pattern.get("sensors", {})
            for sensor_name, expected in sensor_patterns.items():
                trend = trend_map.get(sensor_name)
                if not trend:
                    continue

                expected_trend = expected.get("trend")
                if expected_trend and trend.direction.value == expected_trend:
                    score += 0.2
                    evidence.append(
                        f"Sensor '{sensor_name}' con tendencia {trend.direction.value} "
                        f"({trend.change_percent:+.1f}%)"
                    )

                # Verificar umbrales
                threshold_high = expected.get("threshold_high")
                if threshold_high and trend.current_value > threshold_high:
                    score += 0.2
                    evidence.append(
                        f"Sensor '{sensor_name}' supera umbral: "
                        f"{trend.current_value:.1f} > {threshold_high}"
                    )

                threshold_low = expected.get("threshold_low")
                if threshold_low and trend.current_value < threshold_low:
                    score += 0.2
                    evidence.append(
                        f"Sensor '{sensor_name}' bajo umbral: "
                        f"{trend.current_value:.1f} < {threshold_low}"
                    )

            if score < 0.15:
                continue

            # Determinar nivel de degradacion
            degradation = self._score_to_degradation(score)

            # Estimar vida restante
            typical_life = pattern.get("typical_life_km", 0)
            remaining_km = None
            remaining_days = None

            if mileage and typical_life:
                used_ratio = min(1.0, mileage / typical_life)
                degradation_factor = max(0.1, 1.0 - score)
                remaining_km = int(typical_life * degradation_factor * (1.0 - used_ratio))
                # Asumiendo ~15000 km/anio
                remaining_days = int(remaining_km / 41.0) if remaining_km > 0 else 0

            # Probabilidades de falla
            prob_30d = min(0.95, score * 0.6)
            prob_90d = min(0.98, score * 0.85)

            # Descripcion
            description = (
                f"El componente '{pattern['component']}' muestra signos de "
                f"degradacion {degradation.value}. "
                f"{'Atencion inmediata requerida.' if degradation in (DegradationLevel.AVANZADO, DegradationLevel.CRITICO) else 'Monitorear y planificar mantenimiento.'}"
            )

            predictions.append(ComponentPrediction(
                component=pattern["component"],
                system=pattern["system"],
                degradation_level=degradation,
                estimated_remaining_life_km=remaining_km,
                estimated_remaining_life_days=remaining_days,
                failure_probability_30d=round(prob_30d, 2),
                failure_probability_90d=round(prob_90d, 2),
                symptoms=pattern["symptoms"],
                evidence=evidence,
                confidence=round(min(0.95, score + 0.1), 2),
                description=description,
            ))

        # Ordenar por probabilidad de falla
        predictions.sort(key=lambda p: p.failure_probability_30d, reverse=True)
        return predictions

    def _score_to_degradation(self, score: float) -> DegradationLevel:
        """Convierte un puntaje a nivel de degradacion."""
        if score >= 0.8:
            return DegradationLevel.CRITICO
        elif score >= 0.6:
            return DegradationLevel.AVANZADO
        elif score >= 0.4:
            return DegradationLevel.MODERADO
        elif score >= 0.2:
            return DegradationLevel.LEVE
        else:
            return DegradationLevel.NORMAL

    # ------------------------------------------------------------------
    # Programa de mantenimiento
    # ------------------------------------------------------------------

    def _generate_maintenance_schedule(
        self,
        predictions: list[ComponentPrediction],
        mileage: Optional[int],
        last_service_km: Optional[int],
    ) -> list[MaintenanceRecommendation]:
        """Genera recomendaciones de mantenimiento."""
        recommendations: list[MaintenanceRecommendation] = []

        # Recomendaciones basadas en predicciones de fallas
        for pred in predictions:
            if pred.degradation_level in (DegradationLevel.MODERADO,
                                           DegradationLevel.AVANZADO,
                                           DegradationLevel.CRITICO):
                urgency = {
                    DegradationLevel.MODERADO: MaintenanceUrgency.PRONTO,
                    DegradationLevel.AVANZADO: MaintenanceUrgency.URGENTE,
                    DegradationLevel.CRITICO: MaintenanceUrgency.INMEDIATO,
                }[pred.degradation_level]

                # Buscar costo estimado del patron
                cost_range = (50, 500)
                for pattern in self._degradation_patterns:
                    if pattern["component"] == pred.component:
                        cost_range = pattern.get("estimated_cost", cost_range)
                        break

                recommendations.append(MaintenanceRecommendation(
                    component=pred.component,
                    action=f"Inspeccionar y reparar/reemplazar {pred.component}",
                    urgency=urgency,
                    estimated_cost_range=cost_range,
                    reason=pred.description,
                    consequences_if_ignored=(
                        f"Riesgo de falla: {pred.failure_probability_30d:.0%} en 30 dias. "
                        + "; ".join(pred.symptoms[:2])
                    ),
                    recommended_by_km=(
                        mileage + (pred.estimated_remaining_life_km or 5000)
                        if mileage else None
                    ),
                ))

        # Recomendaciones de mantenimiento programado
        if mileage and last_service_km is not None:
            km_since_service = mileage - last_service_km

            for item in self._maintenance_schedule:
                interval = item["interval_km"]
                if interval <= 0:
                    continue

                if km_since_service >= interval:
                    overdue_factor = km_since_service / interval
                    if overdue_factor >= item.get("urgency_overdue_factor", 1.3):
                        urgency = MaintenanceUrgency.URGENTE
                    else:
                        urgency = MaintenanceUrgency.PRONTO

                    recommendations.append(MaintenanceRecommendation(
                        component=item["component"],
                        action=f"Reemplazar {item['component']}",
                        urgency=urgency,
                        estimated_cost_range=item["estimated_cost"],
                        reason=(
                            f"Intervalo de {interval:,} km excedido. "
                            f"Kilometros desde ultimo servicio: {km_since_service:,}"
                        ),
                        consequences_if_ignored=item["consequences"],
                        recommended_by_km=mileage + 500,
                    ))
                elif km_since_service >= interval * 0.85:
                    recommendations.append(MaintenanceRecommendation(
                        component=item["component"],
                        action=f"Programar reemplazo de {item['component']}",
                        urgency=MaintenanceUrgency.RUTINA,
                        estimated_cost_range=item["estimated_cost"],
                        reason=(
                            f"Proximo al intervalo de {interval:,} km. "
                            f"Actual: {km_since_service:,} km desde servicio"
                        ),
                        consequences_if_ignored=item["consequences"],
                        recommended_by_km=last_service_km + interval,
                    ))

        # Ordenar por urgencia
        urgency_order = {
            MaintenanceUrgency.INMEDIATO: 0,
            MaintenanceUrgency.URGENTE: 1,
            MaintenanceUrgency.PRONTO: 2,
            MaintenanceUrgency.RUTINA: 3,
        }
        recommendations.sort(key=lambda r: urgency_order.get(r.urgency, 99))

        return recommendations

    # ------------------------------------------------------------------
    # Riesgo general
    # ------------------------------------------------------------------

    def _calculate_risk_score(
        self,
        predictions: list[ComponentPrediction],
        trends: list[SensorTrend],
    ) -> float:
        """Calcula un puntaje de riesgo general (0-100)."""
        if not predictions and not trends:
            return 0.0

        risk = 0.0

        # Riesgo de predicciones de componentes
        for pred in predictions:
            level_risk = {
                DegradationLevel.NORMAL: 0,
                DegradationLevel.LEVE: 5,
                DegradationLevel.MODERADO: 15,
                DegradationLevel.AVANZADO: 30,
                DegradationLevel.CRITICO: 50,
            }.get(pred.degradation_level, 0)

            risk += level_risk * pred.confidence

        # Riesgo de tendencias erraticas o extremas
        for trend in trends:
            if trend.direction == TrendDirection.ERRATICO and trend.confidence > 0.5:
                risk += 5
            elif abs(trend.change_percent) > 20 and trend.confidence > 0.5:
                risk += 8

        return min(100.0, risk)

    # ------------------------------------------------------------------
    # Generacion de resumen
    # ------------------------------------------------------------------

    def _generate_summary(
        self,
        risk_score: float,
        predictions: list[ComponentPrediction],
        maintenance: list[MaintenanceRecommendation],
    ) -> str:
        """Genera un resumen en espanol del reporte de predicciones."""
        parts: list[str] = []

        # Riesgo general
        if risk_score < 10:
            parts.append(
                "Riesgo de fallas: BAJO. No se detectan tendencias preocupantes."
            )
        elif risk_score < 30:
            parts.append(
                "Riesgo de fallas: MODERADO. Algunos componentes muestran signos "
                "de desgaste normal. Monitorear en los proximos servicios."
            )
        elif risk_score < 60:
            parts.append(
                "Riesgo de fallas: ELEVADO. Se detectan tendencias de degradacion "
                "que requieren atencion. Programar inspeccion pronto."
            )
        else:
            parts.append(
                "Riesgo de fallas: ALTO. Multiples componentes muestran degradacion "
                "significativa. Se recomienda atencion inmediata."
            )

        # Componentes criticos
        critical = [
            p for p in predictions
            if p.degradation_level in (DegradationLevel.AVANZADO, DegradationLevel.CRITICO)
        ]
        if critical:
            parts.append("\nComponentes que requieren atencion urgente:")
            for pred in critical:
                parts.append(f"  - {pred.component}: {pred.description}")

        # Mantenimiento inmediato
        urgent_maint = [
            m for m in maintenance
            if m.urgency in (MaintenanceUrgency.INMEDIATO, MaintenanceUrgency.URGENTE)
        ]
        if urgent_maint:
            parts.append("\nMantenimiento urgente recomendado:")
            for m in urgent_maint:
                cost_str = f"${m.estimated_cost_range[0]}-${m.estimated_cost_range[1]}"
                parts.append(f"  - {m.action} ({cost_str} USD aprox.)")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    def _extract_dtcs(self, data: dict[str, Any]) -> list[str]:
        """Extrae codigos DTC del diccionario de datos."""
        dtcs = data.get("dtcs", [])
        if not dtcs:
            return []
        if isinstance(dtcs[0], dict):
            return [d.get("code", "") for d in dtcs if d.get("code")]
        return [str(d) for d in dtcs]
