"""
SOLER OBD2 AI Scanner - Analizador de Correlacion Multi-Sensor
===============================================================
Analizador inteligente que correlaciona datos de sensores, DTCs y
resultados del motor de reglas para generar diagnosticos completos
en espanol, con puntuacion de salud del vehiculo y predicciones.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from .rules_engine import RuleResult, RulesEngine, Severity, VehicleSystem

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Modelos de datos del analisis
# ---------------------------------------------------------------------------

@dataclass
class SystemHealth:
    """Salud de un sistema individual del vehiculo."""
    system: VehicleSystem
    score: float  # 0-100
    issues: list[str] = field(default_factory=list)
    severity: Severity = Severity.INFO
    recommendations: list[str] = field(default_factory=list)


@dataclass
class RootCauseAnalysis:
    """Analisis de causa raiz para un grupo de DTCs correlacionados."""
    root_cause: str
    confidence: float
    related_dtcs: list[str]
    related_rules: list[str]
    explanation: str
    fix_priority: int  # 1 = mas urgente


@dataclass
class DiagnosticReport:
    """Reporte completo de diagnostico del vehiculo."""
    timestamp: datetime
    vehicle_health_score: float  # 0-100
    overall_status: str  # "excelente", "bueno", "aceptable", "precaucion", "critico"
    system_scores: dict[str, SystemHealth]
    triggered_rules: list[RuleResult]
    root_causes: list[RootCauseAnalysis]
    diagnosis_text: str  # Diagnostico en lenguaje natural (espanol)
    predictions: list[str]
    immediate_actions: list[str]
    maintenance_recommendations: list[str]
    raw_data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Grupos de correlacion de DTCs
# ---------------------------------------------------------------------------

# DTCs que frecuentemente tienen la misma causa raiz
DTC_CORRELATION_GROUPS: list[dict[str, Any]] = [
    {
        "name": "Mezcla pobre generalizada",
        "dtcs": ["P0171", "P0174", "P0300", "P0420", "P0430"],
        "root_cause": "Fuga de vacio o presion de combustible baja",
        "explanation": "Cuando ambos bancos muestran mezcla pobre junto con fallas de "
                       "encendido y eficiencia baja de catalizador, la causa raiz mas "
                       "probable es una fuga de vacio grande o falla de la bomba de combustible.",
    },
    {
        "name": "Mezcla rica generalizada",
        "dtcs": ["P0172", "P0175", "P0420", "P0430"],
        "root_cause": "Inyeccion excesiva de combustible",
        "explanation": "Mezcla rica en ambos bancos con eficiencia baja de catalizador "
                       "indica un problema comun: regulador de presion, sensor MAF contaminado "
                       "o sensor ECT enviando senal de motor frio.",
    },
    {
        "name": "Distribucion desplazada",
        "dtcs": ["P0011", "P0021", "P0300", "P0016", "P0017", "P0341"],
        "root_cause": "Cadena/correa de distribucion estirada o saltada",
        "explanation": "Codigos de VVT en ambos bancos con discrepancia CKP/CMP y "
                       "fallas de encendido sugieren que la cadena o correa de distribucion "
                       "se ha estirado o desplazado.",
    },
    {
        "name": "Falla electrica generalizada",
        "dtcs": ["P0562", "P0563", "U0100", "U0101"],
        "root_cause": "Problema de alimentacion electrica principal",
        "explanation": "Voltaje anormal combinado con perdida de comunicacion en multiples "
                       "modulos indica un problema en el circuito de alimentacion principal: "
                       "bateria, alternador o cableado principal.",
    },
    {
        "name": "Sensor MAF contaminado",
        "dtcs": ["P0101", "P0171", "P0174", "P0068"],
        "root_cause": "Sensor MAF sucio o defectuoso",
        "explanation": "Correlacion entre lectura anormal del MAF, mezcla pobre en ambos "
                       "bancos y discrepancia MAF/MAP apunta a un sensor MAF contaminado.",
    },
    {
        "name": "Catalizador danado por misfire",
        "dtcs": ["P0300", "P0301", "P0302", "P0420"],
        "root_cause": "Falla de encendido causando danio al catalizador",
        "explanation": "Las fallas de encendido envian combustible no quemado al catalizador, "
                       "elevando su temperatura y degradandolo. Reparar primero las fallas "
                       "de encendido antes de reemplazar el catalizador.",
    },
    {
        "name": "Transmision en modo de emergencia",
        "dtcs": ["P0700", "P0730", "P0750", "P0755"],
        "root_cause": "Falla interna de transmision automatica",
        "explanation": "Multiples codigos de transmision con relacion de engranaje incorrecta "
                       "y fallas de solenoides sugieren un problema grave interno que puede "
                       "requerir reconstruccion.",
    },
    {
        "name": "Sistema EVAP - tapa de combustible",
        "dtcs": ["P0440", "P0441", "P0455", "P0456"],
        "root_cause": "Tapa del tanque de combustible defectuosa",
        "explanation": "Multiples codigos EVAP sin otros sintomas generalmente indican "
                       "que la tapa del tanque no sella correctamente. Verificar antes de "
                       "diagnosticar mas a fondo.",
    },
    {
        "name": "Sensor O2 delantero degradado",
        "dtcs": ["P0133", "P0171", "P0172"],
        "root_cause": "Sensor O2 delantero con respuesta lenta",
        "explanation": "Un sensor O2 con respuesta lenta causa oscilaciones entre mezcla "
                       "rica y pobre. La ECU alterna entre compensar mucho y poco, generando "
                       "estos codigos alternadamente.",
    },
    {
        "name": "Red CAN-Bus danada",
        "dtcs": ["U0100", "U0101", "U0121", "U0140", "U0151"],
        "root_cause": "Cable CAN-Bus principal danado",
        "explanation": "Perdida de comunicacion con multiples modulos simultaneamente indica "
                       "un problema en el bus CAN comun, no en modulos individuales. Verificar "
                       "cableado CAN-H y CAN-L.",
    },
]


# ---------------------------------------------------------------------------
# Rangos normales de operacion por defecto
# ---------------------------------------------------------------------------

DEFAULT_NORMAL_RANGES: dict[str, dict[str, float]] = {
    "coolant_temp": {"min": 80, "max": 105, "ideal_min": 85, "ideal_max": 100},
    "rpm": {"min": 600, "max": 6500, "ideal_min": 650, "ideal_max": 900},
    "vehicle_speed": {"min": 0, "max": 200, "ideal_min": 0, "ideal_max": 120},
    "engine_load": {"min": 0, "max": 100, "ideal_min": 15, "ideal_max": 70},
    "throttle_pos": {"min": 0, "max": 100, "ideal_min": 0, "ideal_max": 80},
    "long_fuel_trim_1": {"min": -15, "max": 15, "ideal_min": -5, "ideal_max": 5},
    "long_fuel_trim_2": {"min": -15, "max": 15, "ideal_min": -5, "ideal_max": 5},
    "short_fuel_trim_1": {"min": -15, "max": 15, "ideal_min": -5, "ideal_max": 5},
    "short_fuel_trim_2": {"min": -15, "max": 15, "ideal_min": -5, "ideal_max": 5},
    "timing_advance": {"min": -5, "max": 40, "ideal_min": 5, "ideal_max": 35},
    "intake_air_temp": {"min": -20, "max": 60, "ideal_min": 10, "ideal_max": 45},
    "intake_manifold_pressure": {"min": 20, "max": 101, "ideal_min": 25, "ideal_max": 95},
    "control_module_voltage": {"min": 13.2, "max": 14.8, "ideal_min": 13.5, "ideal_max": 14.5},
    "fuel_pressure": {"min": 35, "max": 65, "ideal_min": 38, "ideal_max": 60},
    "oil_temp": {"min": 60, "max": 120, "ideal_min": 80, "ideal_max": 110},
    "catalyst_temp": {"min": 200, "max": 850, "ideal_min": 300, "ideal_max": 700},
    "trans_temp": {"min": 40, "max": 110, "ideal_min": 60, "ideal_max": 100},
    "boost_pressure": {"min": 95, "max": 170, "ideal_min": 100, "ideal_max": 155},
}


# ---------------------------------------------------------------------------
# Analizador principal
# ---------------------------------------------------------------------------

class VehicleAnalyzer:
    """Analizador de diagnostico vehicular multi-sensor."""

    def __init__(
        self,
        rules_engine: Optional[RulesEngine] = None,
        normal_ranges: Optional[dict[str, dict[str, float]]] = None,
    ) -> None:
        self._engine = rules_engine or RulesEngine()
        self._normal_ranges = normal_ranges or DEFAULT_NORMAL_RANGES.copy()

    @property
    def rules_engine(self) -> RulesEngine:
        return self._engine

    def update_normal_ranges(self, ranges: dict[str, dict[str, float]]) -> None:
        """Actualiza los rangos normales de operacion (por ejemplo, de la knowledge base)."""
        self._normal_ranges.update(ranges)

    # ------------------------------------------------------------------
    # Analisis principal
    # ------------------------------------------------------------------

    async def analyze(
        self,
        data: dict[str, Any],
        *,
        vehicle_info: Optional[dict[str, str]] = None,
    ) -> DiagnosticReport:
        """Realiza un analisis completo del vehiculo.

        Args:
            data: Diccionario con 'sensors' (dict) y 'dtcs' (list).
            vehicle_info: Info opcional del vehiculo (make, model, year, engine).

        Returns:
            DiagnosticReport con diagnostico completo.
        """
        # 1. Evaluar reglas
        triggered = await self._engine.evaluate(data)

        # 2. Analisis de causa raiz
        root_causes = self._find_root_causes(data, triggered)

        # 3. Calcular salud por sistema
        system_scores = self._calculate_system_health(data, triggered)

        # 4. Calcular puntuacion global
        health_score = self._calculate_global_health(system_scores, triggered)

        # 5. Determinar estado general
        overall_status = self._get_overall_status(health_score)

        # 6. Generar predicciones
        predictions = self._generate_predictions(triggered, data)

        # 7. Acciones inmediatas
        immediate_actions = self._get_immediate_actions(triggered)

        # 8. Recomendaciones de mantenimiento
        maintenance = self._get_maintenance_recommendations(
            data, triggered, system_scores
        )

        # 9. Generar texto de diagnostico en espanol
        diagnosis_text = self._generate_diagnosis_text(
            health_score, overall_status, triggered, root_causes,
            system_scores, vehicle_info
        )

        return DiagnosticReport(
            timestamp=datetime.now(),
            vehicle_health_score=round(health_score, 1),
            overall_status=overall_status,
            system_scores=system_scores,
            triggered_rules=triggered,
            root_causes=root_causes,
            diagnosis_text=diagnosis_text,
            predictions=predictions,
            immediate_actions=immediate_actions,
            maintenance_recommendations=maintenance,
            raw_data=data,
        )

    # ------------------------------------------------------------------
    # Analisis de causa raiz
    # ------------------------------------------------------------------

    def _find_root_causes(
        self,
        data: dict[str, Any],
        triggered: list[RuleResult],
    ) -> list[RootCauseAnalysis]:
        """Encuentra causas raiz correlacionando DTCs."""
        root_causes: list[RootCauseAnalysis] = []
        dtcs = self._extract_dtc_codes(data)

        if not dtcs:
            return root_causes

        dtc_set = set(dtcs)

        for group in DTC_CORRELATION_GROUPS:
            group_dtcs = set(group["dtcs"])
            overlap = dtc_set & group_dtcs

            if len(overlap) >= 2:
                # Encontramos correlacion
                match_ratio = len(overlap) / len(group_dtcs)
                confidence = min(0.6 + match_ratio * 0.35, 0.98)

                # Buscar reglas relacionadas
                related_rule_ids = []
                for rule in triggered:
                    if any(dtc in overlap for dtc in rule.related_dtcs):
                        related_rule_ids.append(rule.rule_id)

                root_causes.append(RootCauseAnalysis(
                    root_cause=group["root_cause"],
                    confidence=round(confidence, 2),
                    related_dtcs=sorted(overlap),
                    related_rules=related_rule_ids,
                    explanation=group["explanation"],
                    fix_priority=self._calculate_fix_priority(triggered, overlap),
                ))

        # Ordenar por prioridad
        root_causes.sort(key=lambda rc: rc.fix_priority)
        return root_causes

    def _calculate_fix_priority(
        self,
        triggered: list[RuleResult],
        dtcs: set[str],
    ) -> int:
        """Calcula la prioridad de reparacion basada en severidad."""
        max_severity = Severity.INFO
        for rule in triggered:
            if any(dtc in dtcs for dtc in rule.related_dtcs):
                if rule.severity > max_severity:
                    max_severity = rule.severity

        # Prioridad inversa a severidad (1 = mas urgente)
        return max(1, 6 - int(max_severity))

    # ------------------------------------------------------------------
    # Salud por sistema
    # ------------------------------------------------------------------

    def _calculate_system_health(
        self,
        data: dict[str, Any],
        triggered: list[RuleResult],
    ) -> dict[str, SystemHealth]:
        """Calcula la salud de cada sistema del vehiculo."""
        scores: dict[str, SystemHealth] = {}

        # Inicializar todos los sistemas en 100
        for system in VehicleSystem:
            scores[system.value] = SystemHealth(
                system=system,
                score=100.0,
                severity=Severity.INFO,
            )

        # Reducir puntuacion basada en reglas activadas
        for rule in triggered:
            sys_key = rule.system.value
            health = scores[sys_key]

            # Penalizacion basada en severidad
            penalty = {
                Severity.INFO: 3,
                Severity.LEVE: 8,
                Severity.MODERADO: 15,
                Severity.GRAVE: 25,
                Severity.CRITICO: 40,
            }.get(rule.severity, 10)

            # Ajustar por confianza
            penalty *= rule.confidence

            health.score = max(0, health.score - penalty)
            health.issues.append(rule.diagnosis)

            if rule.severity > health.severity:
                health.severity = rule.severity

            health.recommendations.extend(rule.corrective_actions[:2])

        # Reducir por sensores fuera de rango
        sensors = data.get("sensors", {})
        for sensor_name, value in sensors.items():
            if value is None:
                continue
            ranges = self._normal_ranges.get(sensor_name)
            if not ranges:
                continue

            system_map = self._sensor_to_system(sensor_name)
            if not system_map:
                continue

            sys_key = system_map.value
            health = scores.get(sys_key)
            if not health:
                continue

            # Fuera de rango ideal pero dentro de rango aceptable
            if value < ranges.get("ideal_min", ranges["min"]) or value > ranges.get("ideal_max", ranges["max"]):
                if ranges["min"] <= value <= ranges["max"]:
                    health.score = max(0, health.score - 3)
                else:
                    # Fuera de rango aceptable
                    health.score = max(0, health.score - 10)

        return scores

    def _sensor_to_system(self, sensor_name: str) -> Optional[VehicleSystem]:
        """Mapea un sensor a su sistema correspondiente."""
        mapping: dict[str, VehicleSystem] = {
            "coolant_temp": VehicleSystem.REFRIGERACION,
            "oil_temp": VehicleSystem.MOTOR,
            "oil_pressure": VehicleSystem.MOTOR,
            "rpm": VehicleSystem.MOTOR,
            "engine_load": VehicleSystem.MOTOR,
            "timing_advance": VehicleSystem.ENCENDIDO,
            "intake_air_temp": VehicleSystem.MOTOR,
            "intake_manifold_pressure": VehicleSystem.MOTOR,
            "throttle_pos": VehicleSystem.ACELERADOR,
            "vehicle_speed": VehicleSystem.MOTOR,
            "long_fuel_trim_1": VehicleSystem.COMBUSTIBLE,
            "long_fuel_trim_2": VehicleSystem.COMBUSTIBLE,
            "short_fuel_trim_1": VehicleSystem.COMBUSTIBLE,
            "short_fuel_trim_2": VehicleSystem.COMBUSTIBLE,
            "fuel_pressure": VehicleSystem.COMBUSTIBLE,
            "catalyst_temp": VehicleSystem.CATALIZADOR,
            "control_module_voltage": VehicleSystem.ELECTRICO,
            "trans_temp": VehicleSystem.TRANSMISION,
            "boost_pressure": VehicleSystem.TURBO,
        }
        return mapping.get(sensor_name)

    # ------------------------------------------------------------------
    # Puntuacion global de salud
    # ------------------------------------------------------------------

    def _calculate_global_health(
        self,
        system_scores: dict[str, SystemHealth],
        triggered: list[RuleResult],
    ) -> float:
        """Calcula la puntuacion global de salud (0-100)."""
        if not system_scores:
            return 100.0

        # Pesos por sistema (los sistemas criticos pesan mas)
        weights: dict[str, float] = {
            VehicleSystem.MOTOR.value: 2.0,
            VehicleSystem.REFRIGERACION.value: 1.5,
            VehicleSystem.COMBUSTIBLE.value: 1.5,
            VehicleSystem.ENCENDIDO.value: 1.5,
            VehicleSystem.TRANSMISION.value: 1.3,
            VehicleSystem.ELECTRICO.value: 1.2,
            VehicleSystem.ABS.value: 1.2,
            VehicleSystem.AIRBAG.value: 1.2,
            VehicleSystem.DIRECCION.value: 1.3,
            VehicleSystem.CATALIZADOR.value: 1.0,
            VehicleSystem.SENSOR_O2.value: 0.8,
            VehicleSystem.EVAP.value: 0.5,
            VehicleSystem.EGR.value: 0.7,
            VehicleSystem.TURBO.value: 1.0,
            VehicleSystem.ACELERADOR.value: 1.2,
            VehicleSystem.VVT.value: 0.8,
            VehicleSystem.EMISION.value: 0.6,
            VehicleSystem.ESCAPE.value: 0.7,
            VehicleSystem.COMUNICACION.value: 1.0,
            VehicleSystem.AIRE_ACONDICIONADO.value: 0.3,
            VehicleSystem.SUSPENSION.value: 0.8,
            VehicleSystem.CARROCERIA.value: 0.3,
        }

        total_weight = 0.0
        weighted_sum = 0.0

        for sys_key, health in system_scores.items():
            # Solo considerar sistemas que tienen problemas o datos
            if health.score < 100 or health.issues:
                weight = weights.get(sys_key, 0.5)
                weighted_sum += health.score * weight
                total_weight += weight

        if total_weight == 0:
            # Sin problemas detectados
            # Penalizar ligeramente si hay DTCs sin regla
            dtc_penalty = min(len(triggered) * 2, 15)
            return max(85.0, 100.0 - dtc_penalty)

        base = weighted_sum / total_weight

        # Penalizacion adicional por codigos criticos
        critical_count = sum(1 for r in triggered if r.severity == Severity.CRITICO)
        grave_count = sum(1 for r in triggered if r.severity == Severity.GRAVE)

        base -= critical_count * 10
        base -= grave_count * 3

        return max(0.0, min(100.0, base))

    def _get_overall_status(self, score: float) -> str:
        """Determina el estado general basado en la puntuacion."""
        if score >= 90:
            return "excelente"
        elif score >= 75:
            return "bueno"
        elif score >= 55:
            return "aceptable"
        elif score >= 35:
            return "precaucion"
        else:
            return "critico"

    # ------------------------------------------------------------------
    # Predicciones
    # ------------------------------------------------------------------

    def _generate_predictions(
        self,
        triggered: list[RuleResult],
        data: dict[str, Any],
    ) -> list[str]:
        """Genera predicciones de fallas futuras."""
        predictions: list[str] = []
        seen: set[str] = set()

        for rule in triggered:
            if rule.prediction and rule.prediction not in seen:
                seen.add(rule.prediction)
                predictions.append(rule.prediction)

        # Predicciones adicionales basadas en sensores
        sensors = data.get("sensors", {})

        coolant = sensors.get("coolant_temp")
        if coolant is not None and 95 < coolant <= 100:
            predictions.append(
                "La temperatura del refrigerante esta en el limite alto del rango normal. "
                "Monitorear de cerca, especialmente en trafico pesado."
            )

        voltage = sensors.get("control_module_voltage")
        if voltage is not None and 12.8 < voltage <= 13.2:
            predictions.append(
                "El voltaje de carga esta marginalmente bajo. La bateria podria no "
                "estar recibienda carga optima. Verificar alternador pronto."
            )

        oil_temp = sensors.get("oil_temp")
        if oil_temp is not None and 110 < oil_temp <= 130:
            predictions.append(
                "La temperatura del aceite esta elevada. El aceite se degrada mas "
                "rapidamente. Considerar acortar el intervalo de cambio de aceite."
            )

        return predictions

    # ------------------------------------------------------------------
    # Acciones inmediatas
    # ------------------------------------------------------------------

    def _get_immediate_actions(self, triggered: list[RuleResult]) -> list[str]:
        """Obtiene acciones que requieren atencion inmediata."""
        actions: list[str] = []
        seen: set[str] = set()

        for rule in triggered:
            if rule.severity >= Severity.CRITICO:
                for action in rule.corrective_actions:
                    if action not in seen:
                        seen.add(action)
                        actions.append(f"[CRITICO] {action}")

        for rule in triggered:
            if rule.severity == Severity.GRAVE:
                for action in rule.corrective_actions[:2]:
                    if action not in seen:
                        seen.add(action)
                        actions.append(f"[URGENTE] {action}")

        return actions

    # ------------------------------------------------------------------
    # Recomendaciones de mantenimiento
    # ------------------------------------------------------------------

    def _get_maintenance_recommendations(
        self,
        data: dict[str, Any],
        triggered: list[RuleResult],
        system_scores: dict[str, SystemHealth],
    ) -> list[str]:
        """Genera recomendaciones de mantenimiento."""
        recommendations: list[str] = []

        # Recomendaciones de reglas activadas (no criticas)
        for rule in triggered:
            if rule.severity <= Severity.MODERADO:
                for action in rule.corrective_actions[:1]:
                    recommendations.append(action)

        # Recomendaciones generales basadas en datos
        sensors = data.get("sensors", {})

        run_time = sensors.get("run_time", 0)
        if run_time > 36000:  # Mas de 10 horas
            recommendations.append(
                "Largo tiempo de operacion continua. Permitir que el motor descanse."
            )

        fuel_level = sensors.get("fuel_level")
        if fuel_level is not None and fuel_level < 15:
            recommendations.append(
                "Nivel de combustible bajo. Repostar pronto para evitar "
                "que la bomba de combustible trabaje en seco."
            )

        # Si todo esta bien, dar recomendacion positiva
        if not triggered:
            recommendations.append(
                "Todos los sistemas operan dentro de parametros normales. "
                "Mantener el programa de mantenimiento del fabricante."
            )

        return recommendations

    # ------------------------------------------------------------------
    # Generacion de texto de diagnostico
    # ------------------------------------------------------------------

    def _generate_diagnosis_text(
        self,
        health_score: float,
        overall_status: str,
        triggered: list[RuleResult],
        root_causes: list[RootCauseAnalysis],
        system_scores: dict[str, SystemHealth],
        vehicle_info: Optional[dict[str, str]] = None,
    ) -> str:
        """Genera un diagnostico en lenguaje natural en espanol."""
        parts: list[str] = []

        # Encabezado
        status_emoji = {
            "excelente": "EXCELENTE",
            "bueno": "BUENO",
            "aceptable": "ACEPTABLE",
            "precaucion": "PRECAUCION",
            "critico": "CRITICO",
        }

        vehicle_str = ""
        if vehicle_info:
            make = vehicle_info.get("make", "")
            model = vehicle_info.get("model", "")
            year = vehicle_info.get("year", "")
            if make or model:
                vehicle_str = f" para {make} {model} {year}".strip()

        parts.append(
            f"=== REPORTE DE DIAGNOSTICO{vehicle_str} ===\n"
            f"Estado general: {status_emoji.get(overall_status, overall_status)} "
            f"({health_score:.0f}/100)\n"
        )

        # Resumen de problemas
        critical = [r for r in triggered if r.severity == Severity.CRITICO]
        grave = [r for r in triggered if r.severity == Severity.GRAVE]
        moderate = [r for r in triggered if r.severity == Severity.MODERADO]
        light = [r for r in triggered if r.severity <= Severity.LEVE]

        if not triggered:
            parts.append(
                "No se detectaron problemas significativos. "
                "El vehiculo se encuentra en buen estado de funcionamiento.\n"
            )
        else:
            parts.append(
                f"Se detectaron {len(triggered)} condiciones: "
                f"{len(critical)} criticas, {len(grave)} graves, "
                f"{len(moderate)} moderadas, {len(light)} leves.\n"
            )

        # Problemas criticos
        if critical:
            parts.append("--- PROBLEMAS CRITICOS (Atencion inmediata) ---")
            for rule in critical:
                parts.append(f"  * {rule.rule_name}: {rule.diagnosis}")
            parts.append("")

        # Problemas graves
        if grave:
            parts.append("--- PROBLEMAS GRAVES (Reparar pronto) ---")
            for rule in grave:
                parts.append(f"  * {rule.rule_name}: {rule.diagnosis}")
            parts.append("")

        # Causa raiz
        if root_causes:
            parts.append("--- ANALISIS DE CAUSA RAIZ ---")
            for i, rc in enumerate(root_causes, 1):
                parts.append(
                    f"  {i}. {rc.root_cause} (confianza: {rc.confidence:.0%})\n"
                    f"     {rc.explanation}\n"
                    f"     DTCs relacionados: {', '.join(rc.related_dtcs)}"
                )
            parts.append("")

        # Sistemas afectados
        affected = [
            (k, v) for k, v in system_scores.items()
            if v.score < 100
        ]
        if affected:
            affected.sort(key=lambda x: x[1].score)
            parts.append("--- SALUD POR SISTEMA ---")
            for sys_key, health in affected:
                parts.append(
                    f"  {sys_key.upper()}: {health.score:.0f}/100 "
                    f"[{health.severity.name}]"
                )
            parts.append("")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    def _extract_dtc_codes(self, data: dict[str, Any]) -> list[str]:
        """Extrae codigos DTC del diccionario de datos."""
        dtcs = data.get("dtcs", [])
        if not dtcs:
            return []
        if isinstance(dtcs[0], dict):
            return [d.get("code", "") for d in dtcs if d.get("code")]
        return [str(d) for d in dtcs]
