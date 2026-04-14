"""
SOLER OBD2 AI Scanner - Motor de Reglas Expertas de Diagnostico
================================================================
Motor de reglas con 200+ reglas de diagnostico que cubren todos los
sistemas principales del vehiculo. Cada regla incluye condiciones,
severidad, diagnostico en espanol, causas probables, acciones
correctivas y predicciones de fallas futuras.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums y tipos
# ---------------------------------------------------------------------------

class Severity(IntEnum):
    """Nivel de severidad del diagnostico."""
    INFO = 1
    LEVE = 2
    MODERADO = 3
    GRAVE = 4
    CRITICO = 5


class VehicleSystem(str, Enum):
    """Sistema del vehiculo al que pertenece la regla."""
    MOTOR = "motor"
    REFRIGERACION = "refrigeracion"
    COMBUSTIBLE = "combustible"
    ENCENDIDO = "encendido"
    EMISION = "emision"
    TRANSMISION = "transmision"
    ELECTRICO = "electrico"
    TURBO = "turbo"
    ESCAPE = "escape"
    EVAP = "evap"
    EGR = "egr"
    CATALIZADOR = "catalizador"
    SENSOR_O2 = "sensor_o2"
    ACELERADOR = "acelerador"
    VVT = "vvt"
    ABS = "abs"
    AIRBAG = "airbag"
    DIRECCION = "direccion"
    SUSPENSION = "suspension"
    AIRE_ACONDICIONADO = "aire_acondicionado"
    CARROCERIA = "carroceria"
    COMUNICACION = "comunicacion"


# ---------------------------------------------------------------------------
# Modelos de datos
# ---------------------------------------------------------------------------

@dataclass
class DiagnosticRule:
    """Regla de diagnostico individual."""
    rule_id: str
    name: str
    system: VehicleSystem
    severity: Severity
    description: str  # Descripcion en espanol
    condition: Callable[[dict[str, Any]], bool]
    diagnosis: str  # Diagnostico en espanol
    probable_causes: list[str]
    corrective_actions: list[str]
    prediction: str  # Prediccion de falla futura
    related_dtcs: list[str] = field(default_factory=list)
    chain_rules: list[str] = field(default_factory=list)  # IDs de reglas encadenadas
    confidence_base: float = 0.85
    min_sensors_required: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class RuleResult:
    """Resultado de la evaluacion de una regla."""
    rule_id: str
    rule_name: str
    system: VehicleSystem
    severity: Severity
    triggered: bool
    confidence: float
    diagnosis: str
    probable_causes: list[str]
    corrective_actions: list[str]
    prediction: str
    related_dtcs: list[str]
    chain_rules: list[str]
    sensor_evidence: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Funciones auxiliares para condiciones
# ---------------------------------------------------------------------------

def _sensor(data: dict[str, Any], key: str, default: Any = None) -> Any:
    """Obtiene un valor del sensor de forma segura."""
    sensors = data.get("sensors", {})
    return sensors.get(key, default)


def _dtc_present(data: dict[str, Any], dtc: str) -> bool:
    """Verifica si un DTC esta presente."""
    dtcs = data.get("dtcs", [])
    if isinstance(dtcs, list):
        if dtcs and isinstance(dtcs[0], dict):
            return any(d.get("code", "") == dtc for d in dtcs)
        return dtc in dtcs
    return False


def _dtc_prefix(data: dict[str, Any], prefix: str) -> bool:
    """Verifica si algun DTC comienza con un prefijo."""
    dtcs = data.get("dtcs", [])
    if isinstance(dtcs, list):
        if dtcs and isinstance(dtcs[0], dict):
            return any(d.get("code", "").startswith(prefix) for d in dtcs)
        return any(str(d).startswith(prefix) for d in dtcs)
    return False


def _dtc_any(data: dict[str, Any], dtc_list: list[str]) -> bool:
    """Verifica si alguno de los DTCs esta presente."""
    return any(_dtc_present(data, dtc) for dtc in dtc_list)


def _has_sensor(data: dict[str, Any], key: str) -> bool:
    """Verifica si un sensor esta disponible."""
    sensors = data.get("sensors", {})
    return key in sensors and sensors[key] is not None


# ---------------------------------------------------------------------------
# Motor de reglas
# ---------------------------------------------------------------------------

class RulesEngine:
    """Motor de reglas expertas de diagnostico vehicular."""

    def __init__(self) -> None:
        self._rules: dict[str, DiagnosticRule] = {}
        self._load_all_rules()

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    def get_rule(self, rule_id: str) -> Optional[DiagnosticRule]:
        return self._rules.get(rule_id)

    def get_rules_by_system(self, system: VehicleSystem) -> list[DiagnosticRule]:
        return [r for r in self._rules.values() if r.system == system]

    def get_rules_by_severity(self, min_severity: Severity) -> list[DiagnosticRule]:
        return [r for r in self._rules.values() if r.severity >= min_severity]

    # ------------------------------------------------------------------
    # Evaluacion
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        data: dict[str, Any],
        *,
        max_chain_depth: int = 3,
    ) -> list[RuleResult]:
        """Evalua todas las reglas contra los datos proporcionados.

        Args:
            data: Diccionario con 'sensors' y 'dtcs'.
            max_chain_depth: Profundidad maxima de encadenamiento.

        Returns:
            Lista de resultados de reglas que se activaron.
        """
        results: list[RuleResult] = []
        evaluated: set[str] = set()

        for rule_id, rule in self._rules.items():
            if rule_id not in evaluated:
                self._evaluate_rule(rule, data, results, evaluated, 0, max_chain_depth)

        # Ordenar por severidad descendente, luego por confianza
        results.sort(key=lambda r: (r.severity, r.confidence), reverse=True)
        return results

    def _evaluate_rule(
        self,
        rule: DiagnosticRule,
        data: dict[str, Any],
        results: list[RuleResult],
        evaluated: set[str],
        depth: int,
        max_depth: int,
    ) -> Optional[RuleResult]:
        """Evalua una regla individual con soporte de encadenamiento."""
        if rule.rule_id in evaluated:
            # Ya fue evaluada; devolver resultado si existe
            for r in results:
                if r.rule_id == rule.rule_id:
                    return r
            return None

        evaluated.add(rule.rule_id)

        try:
            triggered = rule.condition(data)
        except Exception as exc:
            logger.debug("Error evaluando regla %s: %s", rule.rule_id, exc)
            triggered = False

        if not triggered:
            return None

        # Calcular confianza
        confidence = self._calculate_confidence(rule, data)

        # Recopilar evidencia de sensores
        evidence: dict[str, Any] = {}
        sensors = data.get("sensors", {})
        for s in rule.min_sensors_required:
            if s in sensors:
                evidence[s] = sensors[s]

        result = RuleResult(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            system=rule.system,
            severity=rule.severity,
            triggered=True,
            confidence=confidence,
            diagnosis=rule.diagnosis,
            probable_causes=rule.probable_causes,
            corrective_actions=rule.corrective_actions,
            prediction=rule.prediction,
            related_dtcs=rule.related_dtcs,
            chain_rules=rule.chain_rules,
            sensor_evidence=evidence,
        )
        results.append(result)

        # Encadenamiento
        if depth < max_depth and rule.chain_rules:
            for chain_id in rule.chain_rules:
                chained = self._rules.get(chain_id)
                if chained and chain_id not in evaluated:
                    self._evaluate_rule(
                        chained, data, results, evaluated, depth + 1, max_depth
                    )

        return result

    def _calculate_confidence(
        self, rule: DiagnosticRule, data: dict[str, Any]
    ) -> float:
        """Calcula la confianza del diagnostico."""
        confidence = rule.confidence_base

        # Bonus por DTCs relacionados presentes
        dtc_match = sum(
            1 for dtc in rule.related_dtcs if _dtc_present(data, dtc)
        )
        if rule.related_dtcs:
            confidence += 0.05 * min(dtc_match, 3)

        # Bonus por sensores disponibles
        sensors = data.get("sensors", {})
        sensor_available = sum(
            1 for s in rule.min_sensors_required if s in sensors and sensors[s] is not None
        )
        if rule.min_sensors_required:
            ratio = sensor_available / len(rule.min_sensors_required)
            confidence *= (0.7 + 0.3 * ratio)

        return min(confidence, 0.99)

    # ------------------------------------------------------------------
    # Carga de reglas
    # ------------------------------------------------------------------

    def _load_all_rules(self) -> None:
        """Carga todas las reglas de diagnostico."""
        self._load_cooling_rules()
        self._load_fuel_mixture_rules()
        self._load_misfire_rules()
        self._load_catalyst_rules()
        self._load_o2_sensor_rules()
        self._load_evap_rules()
        self._load_egr_rules()
        self._load_ignition_rules()
        self._load_fuel_system_rules()
        self._load_transmission_rules()
        self._load_electrical_rules()
        self._load_turbo_rules()
        self._load_throttle_rules()
        self._load_vvt_rules()
        self._load_abs_rules()
        self._load_airbag_rules()
        self._load_emission_rules()
        self._load_engine_mechanical_rules()
        self._load_communication_rules()
        self._load_ac_rules()
        self._load_steering_rules()
        self._load_generic_sensor_rules()
        self._load_additional_fuel_rules()
        self._load_additional_ignition_rules()
        self._load_additional_transmission_rules()
        self._load_additional_emission_rules()
        self._load_additional_engine_rules()
        self._load_additional_electrical_rules()
        self._load_additional_body_rules()
        self._load_additional_cooling_rules()
        self._load_supplementary_rules()
        logger.info(
            "Motor de reglas cargado: %d reglas en total", len(self._rules)
        )

    def _add(self, rule: DiagnosticRule) -> None:
        self._rules[rule.rule_id] = rule

    # ==================================================================
    # REGLAS: SISTEMA DE REFRIGERACION (COOL-xxx)
    # ==================================================================

    def _load_cooling_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="COOL-001",
            name="Sobrecalentamiento critico",
            system=VehicleSystem.REFRIGERACION,
            severity=Severity.CRITICO,
            description="Temperatura del refrigerante extremadamente alta",
            condition=lambda d: (_sensor(d, "coolant_temp", 0) > 115),
            diagnosis="ALERTA CRITICA: El motor se encuentra en sobrecalentamiento severo. "
                       "La temperatura del refrigerante supera los 115 C. Detener el vehiculo inmediatamente.",
            probable_causes=[
                "Falla total de la bomba de agua",
                "Termostato atascado en posicion cerrada",
                "Rotura de manguera de refrigerante",
                "Ventilador de refrigeracion inoperante",
                "Junta de culata danada",
            ],
            corrective_actions=[
                "DETENER EL VEHICULO INMEDIATAMENTE",
                "Apagar el motor y dejar enfriar",
                "No abrir el tapon del radiador en caliente",
                "Verificar nivel de refrigerante",
                "Remolcar al taller mas cercano",
            ],
            prediction="Riesgo inminente de danio severo al motor: deformacion de culata, "
                       "danio a pistones y camisas. Reparacion costosa si no se detiene.",
            related_dtcs=["P0217", "P0118", "P0116"],
            chain_rules=["COOL-002", "COOL-005"],
            confidence_base=0.95,
            min_sensors_required=["coolant_temp"],
        ))

        self._add(DiagnosticRule(
            rule_id="COOL-002",
            name="Temperatura elevada de refrigerante",
            system=VehicleSystem.REFRIGERACION,
            severity=Severity.GRAVE,
            description="Temperatura de refrigerante por encima del rango normal",
            condition=lambda d: (100 < _sensor(d, "coolant_temp", 0) <= 115),
            diagnosis="El motor muestra temperatura de refrigerante elevada (100-115 C). "
                       "Se requiere atencion pronto para evitar sobrecalentamiento.",
            probable_causes=[
                "Termostato parcialmente atascado",
                "Nivel bajo de refrigerante",
                "Ventilador de refrigeracion con funcionamiento intermitente",
                "Radiador parcialmente obstruido",
                "Tapa del radiador con presion insuficiente",
            ],
            corrective_actions=[
                "Reducir la velocidad y evitar esfuerzos al motor",
                "Encender la calefaccion para disipar calor",
                "Verificar nivel de refrigerante al enfriarse",
                "Inspeccionar el termostato",
                "Revisar funcionamiento del ventilador",
            ],
            prediction="Sin correccion, el sobrecalentamiento total puede ocurrir en "
                       "30-60 minutos de conduccion. Posible danio a la junta de culata.",
            related_dtcs=["P0217", "P0116", "P0128"],
            chain_rules=["COOL-003"],
            confidence_base=0.90,
            min_sensors_required=["coolant_temp"],
        ))

        self._add(DiagnosticRule(
            rule_id="COOL-003",
            name="Motor no alcanza temperatura operativa",
            system=VehicleSystem.REFRIGERACION,
            severity=Severity.MODERADO,
            description="Motor frio despues de tiempo suficiente de operacion",
            condition=lambda d: (
                _sensor(d, "coolant_temp", 90) < 70
                and _sensor(d, "run_time", 0) > 600
            ),
            diagnosis="El motor no alcanza la temperatura operativa normal despues de 10 minutos. "
                       "El termostato podria estar atascado en posicion abierta.",
            probable_causes=[
                "Termostato atascado en posicion abierta",
                "Sensor de temperatura defectuoso (lectura baja)",
                "Termostato faltante o con especificacion incorrecta",
            ],
            corrective_actions=[
                "Reemplazar el termostato",
                "Verificar sensor de temperatura ECT",
                "Comprobar que el termostato sea el correcto para el vehiculo",
            ],
            prediction="Mayor consumo de combustible (10-15%), mayor desgaste del motor "
                       "por operacion en frio, aumento de emisiones.",
            related_dtcs=["P0128", "P0125"],
            confidence_base=0.85,
            min_sensors_required=["coolant_temp", "run_time"],
        ))

        self._add(DiagnosticRule(
            rule_id="COOL-004",
            name="Sensor de temperatura de refrigerante erratico",
            system=VehicleSystem.REFRIGERACION,
            severity=Severity.MODERADO,
            description="Lecturas erraticas del sensor ECT",
            condition=lambda d: _dtc_any(d, ["P0115", "P0116", "P0117", "P0118", "P0119"]),
            diagnosis="El sensor de temperatura del refrigerante (ECT) presenta lecturas "
                       "erraticas o fuera de rango. La ECU no puede gestionar correctamente la mezcla.",
            probable_causes=[
                "Sensor ECT defectuoso",
                "Conector del sensor corroido o suelto",
                "Cableado danado entre sensor y ECU",
                "Cortocircuito en el circuito del sensor",
            ],
            corrective_actions=[
                "Inspeccionar conector del sensor ECT",
                "Medir resistencia del sensor con multimetro",
                "Verificar cableado entre sensor y ECU",
                "Reemplazar sensor si esta fuera de especificacion",
            ],
            prediction="La ECU usara valores por defecto, causando arranque en frio dificil, "
                       "mayor consumo y ralenti inestable.",
            related_dtcs=["P0115", "P0116", "P0117", "P0118", "P0119"],
            confidence_base=0.88,
            min_sensors_required=["coolant_temp"],
        ))

        self._add(DiagnosticRule(
            rule_id="COOL-005",
            name="Ventilador de refrigeracion inactivo",
            system=VehicleSystem.REFRIGERACION,
            severity=Severity.GRAVE,
            description="Ventilador no se activa con temperatura alta",
            condition=lambda d: (
                _sensor(d, "coolant_temp", 0) > 105
                and _sensor(d, "vehicle_speed", 999) < 10
            ),
            diagnosis="El ventilador de refrigeracion no se esta activando a pesar de que "
                       "la temperatura supera los 105 C en baja velocidad.",
            probable_causes=[
                "Rele del ventilador defectuoso",
                "Motor del ventilador quemado",
                "Fusible del ventilador fundido",
                "Sensor de activacion del ventilador danado",
                "Falla en el modulo de control del ventilador",
            ],
            corrective_actions=[
                "Verificar fusible del ventilador",
                "Probar rele del ventilador",
                "Verificar alimentacion al motor del ventilador",
                "Reemplazar motor del ventilador si no funciona",
            ],
            prediction="Sobrecalentamiento garantizado en trafico lento. Riesgo de danio "
                       "al motor en los proximos 15-30 minutos de ralenti.",
            related_dtcs=["P0480", "P0481"],
            chain_rules=["COOL-001"],
            confidence_base=0.87,
            min_sensors_required=["coolant_temp", "vehicle_speed"],
        ))

        self._add(DiagnosticRule(
            rule_id="COOL-006",
            name="Posible fuga de refrigerante",
            system=VehicleSystem.REFRIGERACION,
            severity=Severity.GRAVE,
            description="Patron de sobrecalentamiento intermitente sugiere fuga",
            condition=lambda d: (
                _sensor(d, "coolant_temp", 0) > 105
                and _dtc_any(d, ["P0217", "P0116"])
            ),
            diagnosis="Patron de temperatura sugiere posible fuga en el sistema de refrigeracion. "
                       "El nivel de refrigerante podria estar bajo.",
            probable_causes=[
                "Fuga en mangueras de refrigerante",
                "Radiador con fisura o corrosion",
                "Bomba de agua con sello danado",
                "Junta de culata con fuga menor",
                "Deposito de expansion fisurado",
            ],
            corrective_actions=[
                "Inspeccionar visualmente todas las mangueras",
                "Verificar nivel de refrigerante (motor frio)",
                "Realizar prueba de presion al sistema",
                "Inspeccionar bomba de agua por fugas",
                "Revisar radiador por fisuras",
            ],
            prediction="La fuga empeorara progresivamente. Riesgo de sobrecalentamiento "
                       "total en 1-4 semanas sin reparacion.",
            related_dtcs=["P0217", "P0116"],
            confidence_base=0.80,
            min_sensors_required=["coolant_temp"],
        ))

    # ==================================================================
    # REGLAS: MEZCLA AIRE-COMBUSTIBLE (FUEL-xxx)
    # ==================================================================

    def _load_fuel_mixture_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="FUEL-001",
            name="Mezcla pobre - Banco 1",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.GRAVE,
            description="Sistema demasiado pobre en banco 1",
            condition=lambda d: (
                _dtc_present(d, "P0171")
                or (_sensor(d, "long_fuel_trim_1", 0) > 20)
            ),
            diagnosis="El sistema de combustible esta operando con mezcla demasiado pobre "
                       "en el banco 1. Exceso de aire o falta de combustible.",
            probable_causes=[
                "Fuga de vacio en el multiple de admision",
                "Inyectores de combustible obstruidos",
                "Filtro de combustible tapado",
                "Bomba de combustible debil",
                "Sensor MAF sucio o defectuoso",
                "Junta del multiple de admision danada",
            ],
            corrective_actions=[
                "Inspeccionar mangueras de vacio por fugas",
                "Limpiar o reemplazar sensor MAF",
                "Verificar presion de combustible",
                "Limpiar inyectores de combustible",
                "Revisar juntas del multiple de admision",
            ],
            prediction="Posible falla de catalizador en 3-6 meses por temperatura excesiva. "
                       "Riesgo de detonacion y danio a pistones.",
            related_dtcs=["P0171", "P0174"],
            chain_rules=["CAT-001", "O2-001"],
            confidence_base=0.88,
            min_sensors_required=["long_fuel_trim_1"],
        ))

        self._add(DiagnosticRule(
            rule_id="FUEL-002",
            name="Mezcla pobre - Banco 2",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.GRAVE,
            description="Sistema demasiado pobre en banco 2",
            condition=lambda d: (
                _dtc_present(d, "P0174")
                or (_sensor(d, "long_fuel_trim_2", 0) > 20)
            ),
            diagnosis="El sistema de combustible esta operando con mezcla demasiado pobre "
                       "en el banco 2. Exceso de aire o falta de combustible.",
            probable_causes=[
                "Fuga de vacio en el multiple de admision (lado banco 2)",
                "Inyectores de combustible obstruidos en banco 2",
                "Sensor MAF sucio o defectuoso",
                "Bomba de combustible con presion insuficiente",
            ],
            corrective_actions=[
                "Inspeccionar mangueras de vacio del banco 2",
                "Limpiar o reemplazar sensor MAF",
                "Verificar presion de combustible",
                "Limpiar inyectores del banco 2",
            ],
            prediction="Catalizador del banco 2 en riesgo de sobrecalentamiento. "
                       "Mayor desgaste en cilindros del banco 2.",
            related_dtcs=["P0174"],
            chain_rules=["CAT-002"],
            confidence_base=0.88,
            min_sensors_required=["long_fuel_trim_2"],
        ))

        self._add(DiagnosticRule(
            rule_id="FUEL-003",
            name="Mezcla rica - Banco 1",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.GRAVE,
            description="Sistema demasiado rico en banco 1",
            condition=lambda d: (
                _dtc_present(d, "P0172")
                or (_sensor(d, "long_fuel_trim_1", 0) < -20)
            ),
            diagnosis="El sistema de combustible esta operando con mezcla demasiado rica "
                       "en el banco 1. Exceso de combustible.",
            probable_causes=[
                "Inyectores de combustible con fuga interna",
                "Regulador de presion de combustible defectuoso",
                "Sensor MAF contaminado (lectura alta)",
                "Sensor de temperatura ECT dando lectura de frio constante",
                "Valvula de purga EVAP atascada abierta",
                "Sensor de oxigeno perezoso o defectuoso",
            ],
            corrective_actions=[
                "Verificar inyectores por fugas",
                "Comprobar presion de combustible y regulador",
                "Limpiar o reemplazar sensor MAF",
                "Verificar sensor ECT",
                "Inspeccionar sistema EVAP",
            ],
            prediction="Contaminacion del catalizador con combustible no quemado. "
                       "Degradacion acelerada del aceite del motor. Posible lavado de cilindros.",
            related_dtcs=["P0172"],
            chain_rules=["CAT-001", "O2-001"],
            confidence_base=0.88,
            min_sensors_required=["long_fuel_trim_1"],
        ))

        self._add(DiagnosticRule(
            rule_id="FUEL-004",
            name="Mezcla rica - Banco 2",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.GRAVE,
            description="Sistema demasiado rico en banco 2",
            condition=lambda d: (
                _dtc_present(d, "P0175")
                or (_sensor(d, "long_fuel_trim_2", 0) < -20)
            ),
            diagnosis="El sistema de combustible esta operando con mezcla demasiado rica "
                       "en el banco 2. Exceso de combustible.",
            probable_causes=[
                "Inyectores del banco 2 con fuga interna",
                "Regulador de presion de combustible defectuoso",
                "Sensor MAF contaminado",
                "Sensor O2 del banco 2 defectuoso",
            ],
            corrective_actions=[
                "Verificar inyectores del banco 2",
                "Comprobar presion de combustible",
                "Limpiar o reemplazar sensor MAF",
                "Verificar sensor O2 del banco 2",
            ],
            prediction="Contaminacion del catalizador del banco 2. "
                       "Posible falla de catalizador en 2-4 meses.",
            related_dtcs=["P0175"],
            chain_rules=["CAT-002"],
            confidence_base=0.88,
            min_sensors_required=["long_fuel_trim_2"],
        ))

        self._add(DiagnosticRule(
            rule_id="FUEL-005",
            name="Ajuste de combustible ambos bancos pobre",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.GRAVE,
            description="Ambos bancos muestran mezcla pobre",
            condition=lambda d: (
                _sensor(d, "long_fuel_trim_1", 0) > 15
                and _sensor(d, "long_fuel_trim_2", 0) > 15
            ),
            diagnosis="Ambos bancos muestran ajuste de combustible positivo alto. "
                       "Problema comun a todo el motor: fuga de vacio o presion de combustible baja.",
            probable_causes=[
                "Presion de combustible baja (bomba, filtro, regulador)",
                "Fuga de vacio grande en el multiple de admision",
                "Sensor MAF contaminado o defectuoso",
                "Linea de retorno de combustible obstruida",
            ],
            corrective_actions=[
                "Medir presion de combustible con manometro",
                "Inspeccionar multiple de admision por fugas",
                "Limpiar o reemplazar sensor MAF",
                "Verificar filtro de combustible",
            ],
            prediction="Sin correccion, posible falla multiple de catalizadores "
                       "y detonacion del motor.",
            related_dtcs=["P0171", "P0174"],
            chain_rules=["FUEL-001", "FUEL-002"],
            confidence_base=0.90,
            min_sensors_required=["long_fuel_trim_1", "long_fuel_trim_2"],
        ))

        self._add(DiagnosticRule(
            rule_id="FUEL-006",
            name="Presion de combustible baja",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.GRAVE,
            description="Presion de combustible por debajo del minimo",
            condition=lambda d: (
                _has_sensor(d, "fuel_pressure")
                and _sensor(d, "fuel_pressure", 999) < 30
            ),
            diagnosis="La presion de riel de combustible esta por debajo del valor minimo. "
                       "El motor no recibe suficiente combustible.",
            probable_causes=[
                "Bomba de combustible debilitada",
                "Filtro de combustible obstruido",
                "Regulador de presion defectuoso",
                "Fuga en linea de combustible",
            ],
            corrective_actions=[
                "Medir presion de combustible en riel",
                "Reemplazar filtro de combustible",
                "Verificar bomba de combustible (amperaje y presion)",
                "Inspeccionar lineas de combustible por fugas",
            ],
            prediction="El motor puede calarse en aceleracion o subidas. "
                       "Riesgo de danio a inyectores por cavitacion.",
            related_dtcs=["P0087", "P0190", "P0191"],
            confidence_base=0.90,
            min_sensors_required=["fuel_pressure"],
        ))

        self._add(DiagnosticRule(
            rule_id="FUEL-007",
            name="Presion de combustible alta",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.MODERADO,
            description="Presion de combustible por encima del maximo",
            condition=lambda d: (
                _has_sensor(d, "fuel_pressure")
                and _sensor(d, "fuel_pressure", 0) > 70
            ),
            diagnosis="La presion de combustible en el riel esta por encima del rango normal. "
                       "Posible regulador de presion defectuoso.",
            probable_causes=[
                "Regulador de presion atascado cerrado",
                "Linea de retorno de combustible obstruida",
                "Valvula de control de presion defectuosa",
            ],
            corrective_actions=[
                "Verificar regulador de presion de combustible",
                "Inspeccionar linea de retorno de combustible",
                "Comprobar valvula de alivio",
            ],
            prediction="Inyeccion excesiva de combustible, consumo elevado, "
                       "posible inundacion del motor en arranque.",
            related_dtcs=["P0193"],
            confidence_base=0.85,
            min_sensors_required=["fuel_pressure"],
        ))

    # ==================================================================
    # REGLAS: FALLAS DE ENCENDIDO / MISFIRE (MIS-xxx)
    # ==================================================================

    def _load_misfire_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="MIS-001",
            name="Falla de encendido aleatoria",
            system=VehicleSystem.ENCENDIDO,
            severity=Severity.GRAVE,
            description="Falla de encendido aleatoria en multiples cilindros",
            condition=lambda d: _dtc_present(d, "P0300"),
            diagnosis="Se detectan fallas de encendido aleatorias en multiples cilindros. "
                       "Esto indica un problema comun a todos los cilindros.",
            probable_causes=[
                "Presion de combustible baja",
                "Fuga de vacio grande",
                "Bobina de encendido principal defectuosa",
                "Distribuidor desgastado (si aplica)",
                "Sensor de posicion del ciguenal defectuoso",
                "Correa de distribucion desplazada",
            ],
            corrective_actions=[
                "Verificar presion de combustible",
                "Inspeccionar mangueras de vacio",
                "Verificar sistema de encendido principal",
                "Comprobar sincronizacion de la distribucion",
                "Verificar sensor CKP",
            ],
            prediction="Danio al catalizador por combustible no quemado. "
                       "Vibracion excesiva que puede danar soportes de motor.",
            related_dtcs=["P0300"],
            chain_rules=["CAT-001", "FUEL-006"],
            confidence_base=0.85,
            min_sensors_required=["rpm"],
        ))

        # Fallas individuales por cilindro (P0301-P0312)
        for cyl in range(1, 13):
            dtc_code = f"P030{cyl}" if cyl < 10 else f"P03{cyl:02d}"
            # Capture cyl and dtc_code in lambda closure
            self._add(DiagnosticRule(
                rule_id=f"MIS-{100 + cyl:03d}",
                name=f"Falla de encendido cilindro {cyl}",
                system=VehicleSystem.ENCENDIDO,
                severity=Severity.GRAVE,
                description=f"Falla de encendido detectada en cilindro {cyl}",
                condition=(lambda d, _dtc=dtc_code: _dtc_present(d, _dtc)),
                diagnosis=f"Falla de encendido en el cilindro {cyl}. El cilindro no esta "
                           f"produciendo combustion completa o no hay combustion.",
                probable_causes=[
                    f"Bujia del cilindro {cyl} desgastada o con gap incorrecto",
                    f"Bobina de encendido del cilindro {cyl} defectuosa",
                    f"Cable de bujia del cilindro {cyl} danado (si aplica)",
                    f"Inyector del cilindro {cyl} obstruido o con fuga",
                    f"Baja compresion en cilindro {cyl} (valvula o anillos)",
                ],
                corrective_actions=[
                    f"Reemplazar bujia del cilindro {cyl}",
                    f"Verificar bobina de encendido del cilindro {cyl}",
                    f"Probar inyector del cilindro {cyl}",
                    f"Realizar prueba de compresion al cilindro {cyl}",
                    "Intercambiar bobina con otro cilindro para confirmar",
                ],
                prediction=f"Sin reparacion, danio al catalizador por combustible no quemado "
                            f"del cilindro {cyl}. Vibracion que dania soportes de motor.",
                related_dtcs=[dtc_code],
                chain_rules=["CAT-001"],
                confidence_base=0.87,
                min_sensors_required=["rpm"],
            ))

        self._add(DiagnosticRule(
            rule_id="MIS-200",
            name="Fallas de encendido en multiples cilindros simultaneas",
            system=VehicleSystem.ENCENDIDO,
            severity=Severity.CRITICO,
            description="Multiples cilindros con falla de encendido",
            condition=lambda d: (
                _dtc_present(d, "P0300")
                and sum(1 for c in range(1, 9) if _dtc_present(d, f"P030{c}")) >= 2
            ),
            diagnosis="Se detectan fallas de encendido simultaneas en multiples cilindros. "
                       "Esto sugiere un problema grave en el sistema de combustible o encendido.",
            probable_causes=[
                "Presion de combustible criticamente baja",
                "Fuga de vacio masiva",
                "Falla del modulo de encendido",
                "Correa/cadena de distribucion saltada",
                "Agua en el combustible",
            ],
            corrective_actions=[
                "Verificar presion de combustible INMEDIATAMENTE",
                "Inspeccionar distribucion del motor",
                "Verificar que no haya agua en el tanque",
                "Comprobar modulo de encendido",
            ],
            prediction="Motor puede detenerse en cualquier momento. Danio severo al "
                       "catalizador y posible danio mecanico interno.",
            related_dtcs=["P0300", "P0301", "P0302", "P0303", "P0304"],
            confidence_base=0.92,
            min_sensors_required=["rpm"],
        ))

    # ==================================================================
    # REGLAS: CATALIZADOR (CAT-xxx)
    # ==================================================================

    def _load_catalyst_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="CAT-001",
            name="Eficiencia del catalizador baja - Banco 1",
            system=VehicleSystem.CATALIZADOR,
            severity=Severity.GRAVE,
            description="Catalizador del banco 1 con eficiencia reducida",
            condition=lambda d: _dtc_present(d, "P0420"),
            diagnosis="El catalizador del banco 1 no esta convirtiendo los gases de escape "
                       "con la eficiencia requerida. Las emisiones exceden los limites.",
            probable_causes=[
                "Catalizador degradado por edad o kilometraje",
                "Contaminacion del catalizador por mezcla rica prolongada",
                "Fuga en el escape antes del catalizador",
                "Sensor O2 trasero defectuoso (falso P0420)",
                "Uso de combustible con plomo o aditivos daninos",
            ],
            corrective_actions=[
                "Verificar sensor O2 trasero banco 1 antes de reemplazar catalizador",
                "Inspeccionar escape por fugas",
                "Si mezcla rica/pobre corregir primero la causa",
                "Reemplazar catalizador si esta confirmado defectuoso",
            ],
            prediction="El vehiculo no pasara la inspeccion de emisiones. "
                       "Posible obstruccion del catalizador que reduce potencia.",
            related_dtcs=["P0420", "P0421"],
            confidence_base=0.82,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="CAT-002",
            name="Eficiencia del catalizador baja - Banco 2",
            system=VehicleSystem.CATALIZADOR,
            severity=Severity.GRAVE,
            description="Catalizador del banco 2 con eficiencia reducida",
            condition=lambda d: _dtc_present(d, "P0430"),
            diagnosis="El catalizador del banco 2 no convierte gases con eficiencia adecuada.",
            probable_causes=[
                "Catalizador degradado por edad",
                "Contaminacion por mezcla rica en banco 2",
                "Fuga de escape antes del catalizador banco 2",
                "Sensor O2 trasero banco 2 defectuoso",
            ],
            corrective_actions=[
                "Verificar sensor O2 trasero banco 2",
                "Inspeccionar escape banco 2 por fugas",
                "Corregir primero cualquier problema de mezcla",
                "Reemplazar catalizador banco 2 si confirmado",
            ],
            prediction="Fallo en inspeccion de emisiones. Posible obstruccion progresiva.",
            related_dtcs=["P0430", "P0431"],
            confidence_base=0.82,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="CAT-003",
            name="Temperatura del catalizador excesiva",
            system=VehicleSystem.CATALIZADOR,
            severity=Severity.CRITICO,
            description="Catalizador a temperatura peligrosamente alta",
            condition=lambda d: (
                _has_sensor(d, "catalyst_temp")
                and _sensor(d, "catalyst_temp", 0) > 900
            ),
            diagnosis="La temperatura del catalizador supera los 900 C. Riesgo de incendio "
                       "y destruccion del catalizador.",
            probable_causes=[
                "Falla de encendido enviando combustible crudo al escape",
                "Mezcla extremadamente rica",
                "Catalizador parcialmente obstruido",
                "Inyector con fuga interna severa",
            ],
            corrective_actions=[
                "DETENER EL VEHICULO - Riesgo de incendio",
                "Corregir fallas de encendido inmediatamente",
                "Verificar inyectores por fugas",
                "Inspeccionar catalizador por obstruccion",
            ],
            prediction="Destruccion total del catalizador inminente. "
                       "Riesgo real de incendio del vehiculo.",
            related_dtcs=["P0420", "P0430", "P0300"],
            confidence_base=0.93,
            min_sensors_required=["catalyst_temp"],
        ))

        self._add(DiagnosticRule(
            rule_id="CAT-004",
            name="Catalizador obstruido",
            system=VehicleSystem.CATALIZADOR,
            severity=Severity.GRAVE,
            description="Posible obstruccion del catalizador",
            condition=lambda d: (
                _has_sensor(d, "intake_manifold_pressure")
                and _sensor(d, "intake_manifold_pressure", 0) > 95
                and _sensor(d, "rpm", 0) > 2000
            ),
            diagnosis="Alta presion en el multiple de admision en RPM elevadas sugiere "
                       "una restriccion en el escape, posiblemente catalizador obstruido.",
            probable_causes=[
                "Catalizador colapsado internamente",
                "Catalizador derretido parcialmente",
                "Silenciador colapsado",
            ],
            corrective_actions=[
                "Medir contrapresion de escape",
                "Inspeccionar catalizador visualmente (con endoscopio si es posible)",
                "Reemplazar catalizador si esta obstruido",
            ],
            prediction="Perdida progresiva de potencia. El motor podria detenerse "
                       "por incapacidad de expulsar gases.",
            related_dtcs=["P0420"],
            confidence_base=0.78,
            min_sensors_required=["intake_manifold_pressure", "rpm"],
        ))

    # ==================================================================
    # REGLAS: SENSORES DE OXIGENO (O2-xxx)
    # ==================================================================

    def _load_o2_sensor_rules(self) -> None:

        o2_rules = [
            ("O2-001", "Sensor O2 banco 1 sensor 1 - circuito", "P0130",
             "banco 1, sensor 1 (delantero)", ["P0130", "P0131", "P0132", "P0133"]),
            ("O2-002", "Sensor O2 banco 1 sensor 2 - circuito", "P0136",
             "banco 1, sensor 2 (trasero)", ["P0136", "P0137", "P0138", "P0139"]),
            ("O2-003", "Sensor O2 banco 2 sensor 1 - circuito", "P0150",
             "banco 2, sensor 1 (delantero)", ["P0150", "P0151", "P0152", "P0153"]),
            ("O2-004", "Sensor O2 banco 2 sensor 2 - circuito", "P0156",
             "banco 2, sensor 2 (trasero)", ["P0156", "P0157", "P0158", "P0159"]),
        ]

        for rule_id, name, primary_dtc, location, dtcs in o2_rules:
            self._add(DiagnosticRule(
                rule_id=rule_id,
                name=name,
                system=VehicleSystem.SENSOR_O2,
                severity=Severity.MODERADO,
                description=f"Problema en circuito del sensor de oxigeno {location}",
                condition=(lambda d, _dtcs=dtcs: _dtc_any(d, _dtcs)),
                diagnosis=f"El sensor de oxigeno {location} presenta un problema en su "
                           f"circuito electrico. La ECU no puede monitorear correctamente "
                           f"la mezcla aire-combustible.",
                probable_causes=[
                    f"Sensor O2 {location} defectuoso",
                    "Cableado del sensor danado o corroido",
                    "Conector desconectado o con corrosion",
                    "Calentador del sensor O2 quemado",
                    "Cortocircuito en el circuito del sensor",
                ],
                corrective_actions=[
                    f"Inspeccionar cableado del sensor O2 {location}",
                    "Verificar resistencia del calentador del sensor",
                    "Comprobar voltaje de senal del sensor",
                    f"Reemplazar sensor O2 {location} si esta fuera de especificacion",
                ],
                prediction="Mayor consumo de combustible (5-15%). La ECU opera en lazo "
                           "abierto, sin correccion de mezcla. Posible danio al catalizador.",
                related_dtcs=dtcs,
                confidence_base=0.86,
                min_sensors_required=[],
            ))

        self._add(DiagnosticRule(
            rule_id="O2-005",
            name="Sensor O2 respuesta lenta - Banco 1 Sensor 1",
            system=VehicleSystem.SENSOR_O2,
            severity=Severity.MODERADO,
            description="Sensor O2 con respuesta lenta",
            condition=lambda d: _dtc_present(d, "P0133"),
            diagnosis="El sensor O2 delantero del banco 1 tiene respuesta lenta. "
                       "La ECU no puede ajustar la mezcla con precision.",
            probable_causes=[
                "Sensor O2 envejecido (degradacion normal)",
                "Sensor O2 contaminado por silicona o fosforo",
                "Fuga de escape cerca del sensor",
            ],
            corrective_actions=[
                "Reemplazar sensor O2 banco 1 sensor 1",
                "Inspeccionar escape por fugas cerca del sensor",
            ],
            prediction="Consumo de combustible elevado y emisiones fuera de norma. "
                       "Posible danio gradual al catalizador.",
            related_dtcs=["P0133"],
            confidence_base=0.85,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="O2-006",
            name="Calentador sensor O2 - Banco 1 Sensor 1",
            system=VehicleSystem.SENSOR_O2,
            severity=Severity.MODERADO,
            description="Falla en calentador del sensor O2",
            condition=lambda d: _dtc_any(d, ["P0135", "P0141", "P0155", "P0161"]),
            diagnosis="El calentador del sensor de oxigeno ha fallado. El sensor tarda "
                       "mas en alcanzar la temperatura de operacion.",
            probable_causes=[
                "Elemento calentador del sensor O2 quemado",
                "Fusible del calentador fundido",
                "Rele de calentador defectuoso",
                "Cableado de alimentacion del calentador danado",
            ],
            corrective_actions=[
                "Verificar fusible del calentador del sensor O2",
                "Medir resistencia del calentador (debe ser 2-15 ohms)",
                "Verificar alimentacion de 12V al calentador",
                "Reemplazar sensor O2 si calentador esta abierto",
            ],
            prediction="En frio, el motor operara con mezcla rica hasta que el sensor "
                       "se caliente. Mayor contaminacion en arranques.",
            related_dtcs=["P0135", "P0141", "P0155", "P0161"],
            confidence_base=0.88,
            min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS: SISTEMA EVAPORATIVO (EVAP-xxx)
    # ==================================================================

    def _load_evap_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="EVAP-001",
            name="Fuga grande en sistema EVAP",
            system=VehicleSystem.EVAP,
            severity=Severity.MODERADO,
            description="Fuga grande detectada en sistema de control de emisiones evaporativas",
            condition=lambda d: _dtc_present(d, "P0455"),
            diagnosis="Se detecto una fuga grande en el sistema EVAP. Vapores de combustible "
                       "se estan escapando a la atmosfera.",
            probable_causes=[
                "Tapa del tanque de combustible suelta, danada o faltante",
                "Manguera EVAP desconectada o rota",
                "Canister de carbon activado danado",
                "Valvula de purga EVAP atascada abierta",
                "Sello del tanque de combustible danado",
            ],
            corrective_actions=[
                "Verificar que la tapa del tanque este bien cerrada",
                "Inspeccionar mangueras del sistema EVAP",
                "Realizar prueba de humo al sistema EVAP",
                "Verificar canister de carbon",
            ],
            prediction="El vehiculo no pasara la inspeccion de emisiones. "
                       "Olor a combustible posible.",
            related_dtcs=["P0455", "P0456"],
            confidence_base=0.85,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="EVAP-002",
            name="Fuga pequena en sistema EVAP",
            system=VehicleSystem.EVAP,
            severity=Severity.LEVE,
            description="Fuga pequena detectada en sistema EVAP",
            condition=lambda d: _dtc_present(d, "P0456"),
            diagnosis="Se detecto una fuga pequena en el sistema EVAP. Generalmente causada "
                       "por la tapa del tanque.",
            probable_causes=[
                "Tapa del tanque de combustible no sellando correctamente",
                "Junta de la tapa del tanque desgastada",
                "Fuga menor en manguera o conexion EVAP",
            ],
            corrective_actions=[
                "Apretar correctamente la tapa del tanque (3 clicks)",
                "Reemplazar la tapa del tanque si el sello esta danado",
                "Borrar codigo y monitorear",
            ],
            prediction="Sin impacto en rendimiento del motor. Posible fallo en inspeccion de emisiones.",
            related_dtcs=["P0456"],
            confidence_base=0.88,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="EVAP-003",
            name="Valvula de purga EVAP",
            system=VehicleSystem.EVAP,
            severity=Severity.MODERADO,
            description="Problema con la valvula de purga del sistema EVAP",
            condition=lambda d: _dtc_any(d, ["P0441", "P0443", "P0444", "P0445"]),
            diagnosis="La valvula de purga del sistema EVAP no funciona correctamente. "
                       "No se estan purgando adecuadamente los vapores de combustible.",
            probable_causes=[
                "Valvula de purga atascada (abierta o cerrada)",
                "Cableado de la valvula de purga danado",
                "Conector de la valvula desconectado",
                "ECU no activando la valvula",
            ],
            corrective_actions=[
                "Verificar funcionamiento de la valvula de purga con multimetro",
                "Inspeccionar cableado y conector",
                "Aplicar vacio a la valvula y verificar que selle",
                "Reemplazar valvula de purga si defectuosa",
            ],
            prediction="Puede causar problemas de arranque en caliente y ralenti inestable.",
            related_dtcs=["P0441", "P0443", "P0444", "P0445"],
            confidence_base=0.85,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="EVAP-004",
            name="Valvula de venteo EVAP",
            system=VehicleSystem.EVAP,
            severity=Severity.MODERADO,
            description="Problema con valvula de venteo del sistema EVAP",
            condition=lambda d: _dtc_any(d, ["P0446", "P0447", "P0448", "P0449"]),
            diagnosis="La valvula de venteo del sistema EVAP no funciona correctamente.",
            probable_causes=[
                "Valvula de venteo defectuosa",
                "Obstruccion en la linea de venteo",
                "Filtro de carbon del canister obstruido",
                "Cableado de la valvula danado",
            ],
            corrective_actions=[
                "Verificar funcionamiento de la valvula de venteo",
                "Inspeccionar linea de venteo por obstrucciones",
                "Verificar cableado y conector",
                "Reemplazar valvula si defectuosa",
            ],
            prediction="Posible presion excesiva en tanque de combustible. "
                       "Dificultad para llenar el tanque.",
            related_dtcs=["P0446", "P0447", "P0448", "P0449"],
            confidence_base=0.84,
            min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS: EGR (EGR-xxx)
    # ==================================================================

    def _load_egr_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="EGR-001",
            name="Flujo EGR insuficiente",
            system=VehicleSystem.EGR,
            severity=Severity.MODERADO,
            description="Flujo de recirculacion de gases insuficiente",
            condition=lambda d: _dtc_present(d, "P0401"),
            diagnosis="El sistema de recirculacion de gases de escape (EGR) no esta "
                       "recirculando suficiente gas. Emisiones de NOx elevadas.",
            probable_causes=[
                "Valvula EGR obstruida con carbon",
                "Pasajes de EGR bloqueados",
                "Sensor de posicion de la valvula EGR defectuoso",
                "Solenoide de vacio de EGR defectuoso",
                "Manguera de vacio de EGR rota o desconectada",
            ],
            corrective_actions=[
                "Limpiar la valvula EGR y sus pasajes",
                "Verificar vacio en la valvula EGR",
                "Inspeccionar mangueras de vacio del sistema",
                "Verificar sensor de posicion EGR",
                "Reemplazar valvula EGR si no funciona despues de limpieza",
            ],
            prediction="Emisiones de NOx elevadas. Posible golpeteo (detonacion) del motor "
                       "bajo carga. Fallo en inspeccion de emisiones.",
            related_dtcs=["P0401"],
            confidence_base=0.85,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="EGR-002",
            name="Flujo EGR excesivo",
            system=VehicleSystem.EGR,
            severity=Severity.MODERADO,
            description="Flujo de recirculacion de gases excesivo",
            condition=lambda d: _dtc_present(d, "P0402"),
            diagnosis="El sistema EGR esta recirculando demasiado gas de escape al motor. "
                       "Esto causa ralenti inestable y posible calado.",
            probable_causes=[
                "Valvula EGR atascada en posicion abierta",
                "Solenoide de control EGR defectuoso",
                "Diafragma de la valvula EGR roto",
            ],
            corrective_actions=[
                "Inspeccionar valvula EGR por atascamiento",
                "Verificar solenoide de control",
                "Reemplazar valvula EGR si esta atascada abierta",
            ],
            prediction="Ralenti muy inestable, posible calado del motor. "
                       "Perdida de potencia en aceleracion.",
            related_dtcs=["P0402"],
            confidence_base=0.86,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="EGR-003",
            name="Sensor de temperatura de gases EGR",
            system=VehicleSystem.EGR,
            severity=Severity.LEVE,
            description="Problema con sensor de temperatura del sistema EGR",
            condition=lambda d: _dtc_any(d, ["P0404", "P0405", "P0406", "P0407", "P0408"]),
            diagnosis="El sensor de posicion o temperatura del sistema EGR reporta valores "
                       "fuera de rango.",
            probable_causes=[
                "Sensor de posicion EGR defectuoso",
                "Depositos de carbon en el sensor",
                "Cableado del sensor danado",
            ],
            corrective_actions=[
                "Limpiar sensor de posicion EGR",
                "Verificar cableado del sensor",
                "Reemplazar sensor si esta defectuoso",
            ],
            prediction="La ECU no puede controlar el EGR con precision. "
                       "Posible aumento de emisiones.",
            related_dtcs=["P0404", "P0405", "P0406", "P0407", "P0408"],
            confidence_base=0.83,
            min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS: SISTEMA DE ENCENDIDO (IGN-xxx)
    # ==================================================================

    def _load_ignition_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="IGN-001",
            name="Sensor de posicion del ciguenal (CKP)",
            system=VehicleSystem.ENCENDIDO,
            severity=Severity.CRITICO,
            description="Problema con sensor de posicion del ciguenal",
            condition=lambda d: _dtc_any(d, ["P0335", "P0336", "P0337", "P0338", "P0339"]),
            diagnosis="El sensor de posicion del ciguenal (CKP) presenta una falla. "
                       "El motor puede no arrancar o detenerse inesperadamente.",
            probable_causes=[
                "Sensor CKP defectuoso",
                "Rueda reluctora danada o con dientes faltantes",
                "Gap del sensor CKP incorrecto",
                "Cableado del sensor danado",
                "Interferencia electromagnetica",
            ],
            corrective_actions=[
                "Verificar gap del sensor CKP",
                "Inspeccionar rueda reluctora por danos",
                "Verificar cableado y conector del sensor",
                "Reemplazar sensor CKP si defectuoso",
            ],
            prediction="El motor puede detenerse sin aviso en cualquier momento. "
                       "Riesgo de quedar varado.",
            related_dtcs=["P0335", "P0336", "P0337", "P0338", "P0339"],
            confidence_base=0.90,
            min_sensors_required=["rpm"],
        ))

        self._add(DiagnosticRule(
            rule_id="IGN-002",
            name="Sensor de posicion del arbol de levas (CMP)",
            system=VehicleSystem.ENCENDIDO,
            severity=Severity.GRAVE,
            description="Problema con sensor de posicion del arbol de levas",
            condition=lambda d: _dtc_any(d, ["P0340", "P0341", "P0342", "P0343", "P0344",
                                              "P0345", "P0346", "P0347", "P0348", "P0349"]),
            diagnosis="El sensor de posicion del arbol de levas (CMP) reporta senal "
                       "anormal. Puede afectar el arranque y la sincronizacion de inyeccion.",
            probable_causes=[
                "Sensor CMP defectuoso",
                "Cadena/correa de distribucion estirada",
                "Cableado del sensor danado",
                "Gap del sensor incorrecto",
            ],
            corrective_actions=[
                "Verificar senal del sensor CMP con osciloscopio",
                "Inspeccionar cadena/correa de distribucion",
                "Verificar cableado y conector",
                "Reemplazar sensor CMP si defectuoso",
            ],
            prediction="Arranque dificil y posible falla de encendido. "
                       "En casos severos, el motor no arrancara.",
            related_dtcs=["P0340", "P0341", "P0342", "P0343", "P0344"],
            confidence_base=0.87,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="IGN-003",
            name="Avance de encendido fuera de rango",
            system=VehicleSystem.ENCENDIDO,
            severity=Severity.MODERADO,
            description="Angulo de avance de encendido anormal",
            condition=lambda d: (
                _has_sensor(d, "timing_advance")
                and (
                    _sensor(d, "timing_advance", 0) > 45
                    or _sensor(d, "timing_advance", 0) < -10
                )
            ),
            diagnosis="El avance de encendido esta fuera del rango normal. Esto puede "
                       "causar detonacion o perdida de potencia.",
            probable_causes=[
                "Sensor de detonacion (knock) defectuoso",
                "Sensor CKP con senal erratica",
                "ECU con error de calculo",
                "Combustible de bajo octanaje",
            ],
            corrective_actions=[
                "Verificar sensor de detonacion",
                "Usar combustible de octanaje recomendado",
                "Verificar sensor CKP",
                "Revisar la ECU por actualizaciones",
            ],
            prediction="Detonacion que puede danar pistones y cojinetes. "
                       "Perdida de potencia y aumento de consumo.",
            related_dtcs=["P0325", "P0326", "P0327"],
            confidence_base=0.80,
            min_sensors_required=["timing_advance"],
        ))

        self._add(DiagnosticRule(
            rule_id="IGN-004",
            name="Sensor de detonacion (Knock)",
            system=VehicleSystem.ENCENDIDO,
            severity=Severity.MODERADO,
            description="Problema con sensor de detonacion",
            condition=lambda d: _dtc_any(d, ["P0325", "P0326", "P0327", "P0328",
                                              "P0330", "P0331", "P0332", "P0333"]),
            diagnosis="El sensor de detonacion no funciona correctamente. "
                       "La ECU no puede proteger el motor contra la detonacion.",
            probable_causes=[
                "Sensor de detonacion defectuoso",
                "Cableado del sensor danado",
                "Sensor mal torqueado",
                "Interferencia de otro componente",
            ],
            corrective_actions=[
                "Verificar torque de instalacion del sensor",
                "Inspeccionar cableado y conector",
                "Reemplazar sensor de detonacion",
                "Verificar que no haya interferencia electrica",
            ],
            prediction="La ECU retrasara el encendido como proteccion, causando perdida "
                       "de potencia de 5-15%. Riesgo de detonacion sin deteccion.",
            related_dtcs=["P0325", "P0326", "P0327", "P0328"],
            confidence_base=0.86,
            min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS: SISTEMA DE COMBUSTIBLE AVANZADO (FSYS-xxx)
    # ==================================================================

    def _load_fuel_system_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="FSYS-001",
            name="Sistema de combustible en lazo abierto",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.MODERADO,
            description="Sistema de combustible no entra en lazo cerrado",
            condition=lambda d: (
                _sensor(d, "fuel_system_status", "") == "open_loop"
                and _sensor(d, "coolant_temp", 0) > 80
                and _sensor(d, "run_time", 0) > 300
            ),
            diagnosis="El sistema de combustible permanece en lazo abierto a pesar de que "
                       "el motor esta caliente. La ECU no puede ajustar la mezcla.",
            probable_causes=[
                "Sensor O2 delantero defectuoso",
                "Calentador de sensor O2 no funcional",
                "Fuga de vacio que impide estabilizar mezcla",
                "ECU con falla interna",
            ],
            corrective_actions=[
                "Verificar sensores O2 delanteros",
                "Inspeccionar calentadores de sensores O2",
                "Buscar fugas de vacio",
                "Verificar codigos relacionados con sensores O2",
            ],
            prediction="Consumo de combustible excesivo (15-25% mas). "
                       "Emisiones muy por encima de la norma.",
            related_dtcs=["P0130", "P0150", "P0135", "P0155"],
            chain_rules=["O2-001", "O2-003"],
            confidence_base=0.85,
            min_sensors_required=["fuel_system_status", "coolant_temp", "run_time"],
        ))

        self._add(DiagnosticRule(
            rule_id="FSYS-002",
            name="Inyector de combustible con circuito abierto",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.GRAVE,
            description="Circuito de inyector con falla",
            condition=lambda d: _dtc_any(d, [
                "P0200", "P0201", "P0202", "P0203", "P0204",
                "P0205", "P0206", "P0207", "P0208",
            ]),
            diagnosis="Se detecto un problema en el circuito de uno o mas inyectores. "
                       "El cilindro afectado no recibe combustible adecuadamente.",
            probable_causes=[
                "Inyector defectuoso (bobina abierta)",
                "Conector del inyector desconectado",
                "Cableado del inyector cortado o cortocircuitado",
                "Driver del inyector en la ECU danado",
            ],
            corrective_actions=[
                "Medir resistencia del inyector afectado (10-16 ohms tipico)",
                "Verificar conector y cableado",
                "Intercambiar inyectores para aislar la falla",
                "Reemplazar inyector defectuoso",
            ],
            prediction="Falla de encendido en el cilindro afectado. Danio al catalizador. "
                       "Vibracion excesiva del motor.",
            related_dtcs=["P0200", "P0201", "P0202", "P0203", "P0204",
                          "P0205", "P0206", "P0207", "P0208"],
            chain_rules=["MIS-001"],
            confidence_base=0.88,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="FSYS-003",
            name="Sensor MAF fuera de rango",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.MODERADO,
            description="Sensor de flujo de masa de aire con problema",
            condition=lambda d: _dtc_any(d, ["P0100", "P0101", "P0102", "P0103", "P0104"]),
            diagnosis="El sensor de flujo de masa de aire (MAF) reporta valores fuera de rango. "
                       "La ECU no puede calcular correctamente la cantidad de combustible.",
            probable_causes=[
                "Sensor MAF sucio o contaminado",
                "Sensor MAF defectuoso",
                "Fuga de aire despues del sensor MAF",
                "Filtro de aire muy sucio",
                "Cableado del sensor danado",
            ],
            corrective_actions=[
                "Limpiar sensor MAF con limpiador especifico",
                "Verificar que no haya fugas de aire post-MAF",
                "Reemplazar filtro de aire",
                "Reemplazar sensor MAF si la limpieza no funciona",
            ],
            prediction="Mezcla incorrecta, perdida de potencia y mayor consumo. "
                       "Posible danio al catalizador.",
            related_dtcs=["P0100", "P0101", "P0102", "P0103", "P0104"],
            chain_rules=["FUEL-001"],
            confidence_base=0.86,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="FSYS-004",
            name="Sensor MAP fuera de rango",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.MODERADO,
            description="Sensor de presion del multiple de admision con problema",
            condition=lambda d: _dtc_any(d, ["P0105", "P0106", "P0107", "P0108", "P0109"]),
            diagnosis="El sensor de presion absoluta del multiple (MAP) reporta valores anormales.",
            probable_causes=[
                "Sensor MAP defectuoso",
                "Manguera de vacio al sensor MAP desconectada o rota",
                "Fuga de vacio en el multiple de admision",
                "Cableado del sensor danado",
            ],
            corrective_actions=[
                "Verificar manguera de vacio al sensor MAP",
                "Comprobar valores del sensor MAP con multimetro",
                "Reemplazar sensor MAP si defectuoso",
            ],
            prediction="Mezcla aire-combustible incorrecta, ralenti inestable, "
                       "perdida de potencia.",
            related_dtcs=["P0105", "P0106", "P0107", "P0108", "P0109"],
            confidence_base=0.85,
            min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS: TRANSMISION (TRANS-xxx)
    # ==================================================================

    def _load_transmission_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="TRANS-001",
            name="Temperatura de transmision alta",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.GRAVE,
            description="Temperatura del fluido de transmision excesiva",
            condition=lambda d: (
                _has_sensor(d, "trans_temp")
                and _sensor(d, "trans_temp", 0) > 120
            ),
            diagnosis="La temperatura del fluido de transmision supera los 120 C. "
                       "El fluido se degrada rapidamente a estas temperaturas.",
            probable_causes=[
                "Nivel bajo de fluido de transmision",
                "Fluido de transmision degradado",
                "Enfriador de transmision obstruido",
                "Convertidor de torque con deslizamiento excesivo",
                "Conduccion severa (remolque, pendientes)",
            ],
            corrective_actions=[
                "Verificar nivel de fluido de transmision",
                "Inspeccionar color y olor del fluido",
                "Verificar enfriador de transmision",
                "Reducir carga del vehiculo",
                "Realizar cambio de fluido si esta degradado",
            ],
            prediction="El fluido de transmision pierde propiedades rapidamente por encima de 120 C. "
                       "Danio a embragues internos si no se corrige en 30-60 minutos.",
            related_dtcs=["P0710", "P0711", "P0712", "P0713"],
            confidence_base=0.87,
            min_sensors_required=["trans_temp"],
        ))

        self._add(DiagnosticRule(
            rule_id="TRANS-002",
            name="Deslizamiento de transmision",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.GRAVE,
            description="Relacion de transmision anormal detectada",
            condition=lambda d: _dtc_any(d, [
                "P0730", "P0731", "P0732", "P0733", "P0734", "P0735", "P0736"
            ]),
            diagnosis="Se detecta una relacion de engranaje incorrecta. La transmision "
                       "esta deslizando o no engancha correctamente la marcha.",
            probable_causes=[
                "Nivel bajo de fluido de transmision",
                "Embragues internos desgastados",
                "Solenoide de cambio defectuoso",
                "Cuerpo de valvulas con problema",
                "Banda de transmision desgastada",
            ],
            corrective_actions=[
                "Verificar nivel y condicion del fluido",
                "Diagnosticar solenoides de cambio",
                "Verificar presion de linea de transmision",
                "Puede requerir reconstruccion de transmision",
            ],
            prediction="Desgaste acelerado de la transmision. Sin reparacion, "
                       "falla total de la transmision en 1-6 meses.",
            related_dtcs=["P0730", "P0731", "P0732", "P0733", "P0734", "P0735"],
            confidence_base=0.85,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="TRANS-003",
            name="Solenoide de cambio A",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.MODERADO,
            description="Problema con solenoide de cambio A",
            condition=lambda d: _dtc_any(d, ["P0750", "P0751", "P0752", "P0753", "P0754"]),
            diagnosis="El solenoide de cambio A de la transmision automatica presenta una falla. "
                       "Puede afectar los cambios entre 1ra y 2da marcha.",
            probable_causes=[
                "Solenoide de cambio A defectuoso",
                "Cableado del solenoide danado",
                "Conector del solenoide corroido",
                "Falla del modulo TCM",
            ],
            corrective_actions=[
                "Verificar resistencia del solenoide (tipico 15-25 ohms)",
                "Inspeccionar conector y cableado",
                "Verificar alimentacion y tierra del solenoide",
                "Reemplazar solenoide si defectuoso",
            ],
            prediction="Cambios bruscos o ausencia de cambio entre 1ra y 2da. "
                       "Desgaste acelerado de embragues si no se repara.",
            related_dtcs=["P0750", "P0751", "P0752", "P0753", "P0754"],
            confidence_base=0.85,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="TRANS-004",
            name="Solenoide de cambio B",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.MODERADO,
            description="Problema con solenoide de cambio B",
            condition=lambda d: _dtc_any(d, ["P0755", "P0756", "P0757", "P0758", "P0759"]),
            diagnosis="El solenoide de cambio B presenta una falla. "
                       "Puede afectar cambios entre 2da y 3ra marcha.",
            probable_causes=[
                "Solenoide de cambio B defectuoso",
                "Cableado danado",
                "Fluido de transmision contaminado",
            ],
            corrective_actions=[
                "Verificar resistencia del solenoide B",
                "Inspeccionar conector y cableado",
                "Cambiar fluido de transmision si contaminado",
                "Reemplazar solenoide si defectuoso",
            ],
            prediction="Cambios erraticos entre 2da y 3ra. Posible modo de emergencia.",
            related_dtcs=["P0755", "P0756", "P0757", "P0758", "P0759"],
            confidence_base=0.85,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="TRANS-005",
            name="Convertidor de torque - embrague",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.MODERADO,
            description="Problema con el embrague del convertidor de torque",
            condition=lambda d: _dtc_any(d, ["P0740", "P0741", "P0742", "P0743", "P0744"]),
            diagnosis="El embrague del convertidor de torque (TCC) no funciona correctamente. "
                       "Puede causar perdida de eficiencia o vibracion.",
            probable_causes=[
                "Solenoide TCC defectuoso",
                "Embrague del convertidor desgastado",
                "Cableado del solenoide TCC danado",
                "Fluido de transmision contaminado",
            ],
            corrective_actions=[
                "Verificar solenoide TCC",
                "Verificar presion del TCC",
                "Cambiar fluido de transmision",
                "Puede requerir reemplazo del convertidor de torque",
            ],
            prediction="Mayor consumo de combustible (5-10%). Posible sobrecalentamiento "
                       "de transmision si el convertidor desliza.",
            related_dtcs=["P0740", "P0741", "P0742", "P0743", "P0744"],
            confidence_base=0.84,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="TRANS-006",
            name="Sensor de velocidad de entrada de transmision",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.MODERADO,
            description="Problema con sensor de velocidad de entrada",
            condition=lambda d: _dtc_any(d, ["P0715", "P0716", "P0717"]),
            diagnosis="El sensor de velocidad de entrada de transmision reporta senal anormal.",
            probable_causes=[
                "Sensor de velocidad defectuoso",
                "Cableado del sensor danado",
                "Gap del sensor incorrecto",
            ],
            corrective_actions=[
                "Verificar senal del sensor con osciloscopio",
                "Inspeccionar cableado y conector",
                "Reemplazar sensor si defectuoso",
            ],
            prediction="Cambios erraticos o bruscos. La transmision no puede calcular "
                       "relaciones de engranaje correctamente.",
            related_dtcs=["P0715", "P0716", "P0717"],
            confidence_base=0.85,
            min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS: SISTEMA ELECTRICO / ALTERNADOR (ELEC-xxx)
    # ==================================================================

    def _load_electrical_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="ELEC-001",
            name="Voltaje del sistema bajo",
            system=VehicleSystem.ELECTRICO,
            severity=Severity.GRAVE,
            description="Voltaje del sistema electrico por debajo del normal",
            condition=lambda d: (
                _has_sensor(d, "control_module_voltage")
                and _sensor(d, "control_module_voltage", 14) < 12.5
                and _sensor(d, "rpm", 0) > 800
            ),
            diagnosis="El voltaje del sistema electrico esta por debajo de 12.5V con el motor "
                       "en marcha. El alternador no esta cargando suficientemente.",
            probable_causes=[
                "Alternador defectuoso (diodos, regulador, rotor)",
                "Correa del alternador floja o rota",
                "Bateria en mal estado que absorbe exceso de corriente",
                "Conexiones de bateria corroidas",
                "Cable de carga del alternador danado",
            ],
            corrective_actions=[
                "Verificar tension de la correa del alternador",
                "Medir voltaje de salida del alternador (debe ser 13.5-14.7V)",
                "Inspeccionar conexiones de bateria",
                "Probar la bateria (prueba de carga)",
                "Reemplazar alternador si no carga",
            ],
            prediction="La bateria se descargara progresivamente. El vehiculo puede "
                       "quedar varado en 1-3 horas de conduccion.",
            related_dtcs=["P0562", "P0563"],
            confidence_base=0.88,
            min_sensors_required=["control_module_voltage", "rpm"],
        ))

        self._add(DiagnosticRule(
            rule_id="ELEC-002",
            name="Voltaje del sistema alto",
            system=VehicleSystem.ELECTRICO,
            severity=Severity.MODERADO,
            description="Voltaje del sistema electrico por encima del normal",
            condition=lambda d: (
                _has_sensor(d, "control_module_voltage")
                and _sensor(d, "control_module_voltage", 14) > 15.5
            ),
            diagnosis="El voltaje del sistema supera 15.5V. Sobrecarga del alternador "
                       "que puede danar componentes electronicos.",
            probable_causes=[
                "Regulador de voltaje del alternador defectuoso",
                "Conexion de tierra del alternador deficiente",
                "Bateria con celda en cortocircuito",
            ],
            corrective_actions=[
                "Verificar voltaje de regulacion del alternador",
                "Inspeccionar tierra del alternador",
                "Probar bateria",
                "Reemplazar alternador si regulador esta defectuoso",
            ],
            prediction="Danio a modulos electronicos, focos fundidos prematuramente, "
                       "bateria hervidenda (perdida de electrolito).",
            related_dtcs=["P0563"],
            confidence_base=0.88,
            min_sensors_required=["control_module_voltage"],
        ))

        self._add(DiagnosticRule(
            rule_id="ELEC-003",
            name="Circuito de alimentacion de la ECU",
            system=VehicleSystem.ELECTRICO,
            severity=Severity.GRAVE,
            description="Problema de alimentacion electrica a la ECU",
            condition=lambda d: _dtc_any(d, ["P0560", "P0561", "P0562", "P0563"]),
            diagnosis="La unidad de control del motor (ECU) detecta anomalias en su "
                       "alimentacion electrica. Esto puede causar comportamiento erratico.",
            probable_causes=[
                "Bateria debil o defectuosa",
                "Alternador con carga insuficiente",
                "Fusible o rele de alimentacion de ECU defectuoso",
                "Cableado de alimentacion danado",
                "Tierra de la ECU deficiente",
            ],
            corrective_actions=[
                "Verificar voltaje de bateria y alternador",
                "Inspeccionar fusibles y reles de la ECU",
                "Verificar tierras de la ECU",
                "Inspeccionar arnes de alimentacion",
            ],
            prediction="Comportamiento erratico del motor. Posible perdida de memoria "
                       "de la ECU y necesidad de reprogramacion.",
            related_dtcs=["P0560", "P0561", "P0562", "P0563"],
            confidence_base=0.86,
            min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS: TURBOCOMPRESOR (TURBO-xxx)
    # ==================================================================

    def _load_turbo_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="TURBO-001",
            name="Presion de sobrealimentacion baja",
            system=VehicleSystem.TURBO,
            severity=Severity.MODERADO,
            description="Presion de turbo por debajo de lo esperado",
            condition=lambda d: (
                _has_sensor(d, "boost_pressure")
                and _sensor(d, "boost_pressure", 100) < 80
                and _sensor(d, "rpm", 0) > 2500
                and _sensor(d, "throttle_pos", 0) > 70
            ),
            diagnosis="La presion de sobrealimentacion del turbo esta baja a RPM y acelerador altos. "
                       "El turbo no esta generando presion suficiente.",
            probable_causes=[
                "Fuga en el intercooler o mangueras de presion",
                "Valvula wastegate atascada abierta",
                "Turbocompresor con juego excesivo en eje",
                "Actuador de wastegate defectuoso",
                "Fuga en el multiple de admision post-turbo",
            ],
            corrective_actions=[
                "Inspeccionar mangueras de presion por fugas",
                "Verificar intercooler por fugas",
                "Comprobar actuador de wastegate",
                "Verificar juego del turbo (axial y radial)",
                "Inspeccionar abrazaderas y conexiones",
            ],
            prediction="Perdida de potencia notable. Si es por desgaste del turbo, "
                       "falla total en 2-6 meses.",
            related_dtcs=["P0234", "P0299"],
            confidence_base=0.82,
            min_sensors_required=["boost_pressure", "rpm", "throttle_pos"],
        ))

        self._add(DiagnosticRule(
            rule_id="TURBO-002",
            name="Sobrealimentacion excesiva",
            system=VehicleSystem.TURBO,
            severity=Severity.CRITICO,
            description="Presion de turbo peligrosamente alta",
            condition=lambda d: (
                _has_sensor(d, "boost_pressure")
                and _sensor(d, "boost_pressure", 0) > 180
            ),
            diagnosis="ALERTA: Presion de sobrealimentacion excesiva. Riesgo de danio "
                       "mecanico severo al motor.",
            probable_causes=[
                "Valvula wastegate atascada cerrada",
                "Actuador de wastegate defectuoso",
                "Solenoide de control de boost defectuoso",
                "Manguera de senal de wastegate desconectada",
            ],
            corrective_actions=[
                "REDUCIR ACELERADOR INMEDIATAMENTE",
                "Verificar actuador de wastegate",
                "Inspeccionar solenoide de control de boost",
                "Verificar manguera de senal del wastegate",
            ],
            prediction="Riesgo inminente de danio al motor: bielas dobladas, pistones "
                       "danados, junta de culata reventada.",
            related_dtcs=["P0234", "P0235", "P0236"],
            confidence_base=0.92,
            min_sensors_required=["boost_pressure"],
        ))

        self._add(DiagnosticRule(
            rule_id="TURBO-003",
            name="Sensor de presion de turbo",
            system=VehicleSystem.TURBO,
            severity=Severity.MODERADO,
            description="Problema con sensor de presion de sobrealimentacion",
            condition=lambda d: _dtc_any(d, ["P0235", "P0236", "P0237", "P0238", "P0239"]),
            diagnosis="El sensor de presion del turbo reporta valores fuera de rango.",
            probable_causes=[
                "Sensor de presion de boost defectuoso",
                "Manguera de senal al sensor obstruida",
                "Cableado del sensor danado",
            ],
            corrective_actions=[
                "Verificar manguera de senal al sensor",
                "Comprobar valores del sensor con manometro",
                "Inspeccionar cableado y conector",
                "Reemplazar sensor si defectuoso",
            ],
            prediction="Control inadecuado de la presion de boost. Posible "
                       "sobrealimentacion o subalimentacion.",
            related_dtcs=["P0235", "P0236", "P0237", "P0238", "P0239"],
            confidence_base=0.84,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="TURBO-004",
            name="Aceite en el turbo - consumo excesivo",
            system=VehicleSystem.TURBO,
            severity=Severity.GRAVE,
            description="Posible fuga de aceite del turbo",
            condition=lambda d: (
                _has_sensor(d, "boost_pressure")
                and _dtc_prefix(d, "P02")
                and _sensor(d, "short_fuel_trim_1", 0) < -10
            ),
            diagnosis="Patron de mezcla rica combinado con turbo sugiere posible fuga de "
                       "aceite por los sellos del turbocompresor.",
            probable_causes=[
                "Sellos del turbo desgastados",
                "Retorno de aceite del turbo obstruido",
                "Presion excesiva en el carter",
                "Sistema PCV defectuoso",
            ],
            corrective_actions=[
                "Inspeccionar tuberia de admision despues del turbo por aceite",
                "Verificar retorno de aceite del turbo",
                "Comprobar sistema PCV",
                "Si hay aceite excesivo, reconstruir o reemplazar turbo",
            ],
            prediction="Contaminacion de bujias e intercooler con aceite. "
                       "Falla del turbo en 3-12 meses.",
            related_dtcs=[],
            confidence_base=0.72,
            min_sensors_required=["boost_pressure", "short_fuel_trim_1"],
        ))

    # ==================================================================
    # REGLAS: ACELERADOR ELECTRONICO (THROT-xxx)
    # ==================================================================

    def _load_throttle_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="THROT-001",
            name="Sensor de posicion del acelerador (TPS) A",
            system=VehicleSystem.ACELERADOR,
            severity=Severity.GRAVE,
            description="Problema con sensor de posicion del acelerador A",
            condition=lambda d: _dtc_any(d, ["P0120", "P0121", "P0122", "P0123", "P0124"]),
            diagnosis="El sensor de posicion del acelerador A reporta valores anormales. "
                       "El motor puede entrar en modo de proteccion (limp mode).",
            probable_causes=[
                "Sensor TPS defectuoso",
                "Cableado del sensor danado",
                "Cuerpo de aceleracion sucio",
                "Conector del sensor corroido",
            ],
            corrective_actions=[
                "Verificar voltaje del sensor TPS (0.5V cerrado, 4.5V abierto)",
                "Inspeccionar cableado y conector",
                "Limpiar cuerpo de aceleracion",
                "Reemplazar sensor TPS si defectuoso",
                "Realizar reaprendizaje del acelerador despues de reparacion",
            ],
            prediction="Motor en modo limp (potencia reducida). Aceleracion errática. "
                       "Posible calado del motor.",
            related_dtcs=["P0120", "P0121", "P0122", "P0123", "P0124"],
            confidence_base=0.88,
            min_sensors_required=["throttle_pos"],
        ))

        self._add(DiagnosticRule(
            rule_id="THROT-002",
            name="Correlacion pedal-acelerador",
            system=VehicleSystem.ACELERADOR,
            severity=Severity.GRAVE,
            description="Discrepancia entre posicion del pedal y acelerador",
            condition=lambda d: _dtc_any(d, ["P2135", "P2138", "P2139", "P2140"]),
            diagnosis="Se detecta discrepancia entre la posicion del pedal del acelerador "
                       "y la posicion del cuerpo de aceleracion. Sistema en modo seguro.",
            probable_causes=[
                "Sensor de pedal de acelerador defectuoso",
                "Motor del cuerpo de aceleracion defectuoso",
                "Cuerpo de aceleracion sucio o trabado",
                "Cableado entre ECU y cuerpo de aceleracion danado",
            ],
            corrective_actions=[
                "Limpiar cuerpo de aceleracion",
                "Verificar sensor de pedal de acelerador",
                "Verificar motor del cuerpo de aceleracion",
                "Inspeccionar arnes de cableado",
                "Realizar reaprendizaje del acelerador",
            ],
            prediction="Motor permanecera en modo limp hasta correccion. "
                       "Velocidad maxima limitada a ~50 km/h.",
            related_dtcs=["P2135", "P2138", "P2139", "P2140"],
            confidence_base=0.90,
            min_sensors_required=["throttle_pos"],
        ))

        self._add(DiagnosticRule(
            rule_id="THROT-003",
            name="Control de ralenti inestable",
            system=VehicleSystem.ACELERADOR,
            severity=Severity.MODERADO,
            description="RPM de ralenti inestable o fuera de rango",
            condition=lambda d: (
                _sensor(d, "throttle_pos", 0) < 5
                and _has_sensor(d, "rpm")
                and (
                    _sensor(d, "rpm", 800) < 500
                    or _sensor(d, "rpm", 800) > 1200
                )
            ),
            diagnosis="El ralenti del motor es inestable o esta fuera del rango normal "
                       "(600-900 RPM). Multiples causas posibles.",
            probable_causes=[
                "Valvula de control de ralenti (IAC) sucia o defectuosa",
                "Fuga de vacio",
                "Cuerpo de aceleracion sucio",
                "Inyectores sucios",
                "Sensor de temperatura ECT con lectura erronea",
            ],
            corrective_actions=[
                "Limpiar cuerpo de aceleracion y valvula IAC",
                "Inspeccionar mangueras de vacio",
                "Verificar sensor ECT",
                "Limpiar inyectores",
                "Realizar reaprendizaje de ralenti",
            ],
            prediction="Posible calado en semaforos. Vibracion excesiva. "
                       "Mayor desgaste de soportes de motor.",
            related_dtcs=["P0505", "P0506", "P0507"],
            confidence_base=0.82,
            min_sensors_required=["rpm", "throttle_pos"],
        ))

    # ==================================================================
    # REGLAS: VVT - DISTRIBUCION VARIABLE (VVT-xxx)
    # ==================================================================

    def _load_vvt_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="VVT-001",
            name="VVT banco 1 - rendimiento",
            system=VehicleSystem.VVT,
            severity=Severity.MODERADO,
            description="Sistema de distribucion variable banco 1 con rendimiento bajo",
            condition=lambda d: _dtc_any(d, ["P0010", "P0011", "P0012", "P0013", "P0014"]),
            diagnosis="El sistema de distribucion variable (VVT/VCT) del banco 1 no esta "
                       "ajustando la sincronizacion correctamente.",
            probable_causes=[
                "Solenoide VVT/VCT del banco 1 defectuoso",
                "Aceite de motor sucio o viscosidad incorrecta",
                "Pasajes de aceite al VVT obstruidos",
                "Engranaje VVT/VCT desgastado",
                "Cadena de distribucion estirada",
            ],
            corrective_actions=[
                "Verificar nivel y condicion del aceite del motor",
                "Cambiar aceite si esta sucio o tiene kilometraje excesivo",
                "Verificar solenoide VVT/VCT banco 1",
                "Inspeccionar tension de cadena de distribucion",
                "Reemplazar solenoide si defectuoso",
            ],
            prediction="Perdida de potencia y eficiencia. Ralenti irregular. "
                       "Si es cadena estirada, riesgo de salto de tiempo.",
            related_dtcs=["P0010", "P0011", "P0012", "P0013", "P0014"],
            confidence_base=0.84,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="VVT-002",
            name="VVT banco 2 - rendimiento",
            system=VehicleSystem.VVT,
            severity=Severity.MODERADO,
            description="Sistema de distribucion variable banco 2 con rendimiento bajo",
            condition=lambda d: _dtc_any(d, ["P0020", "P0021", "P0022", "P0023", "P0024"]),
            diagnosis="El sistema de distribucion variable (VVT/VCT) del banco 2 no funciona correctamente.",
            probable_causes=[
                "Solenoide VVT/VCT del banco 2 defectuoso",
                "Aceite de motor degradado",
                "Pasajes de aceite obstruidos",
                "Cadena de distribucion estirada",
            ],
            corrective_actions=[
                "Cambiar aceite del motor con la especificacion correcta",
                "Verificar solenoide VVT/VCT banco 2",
                "Inspeccionar cadena de distribucion",
                "Reemplazar solenoide si defectuoso",
            ],
            prediction="Perdida de potencia en banco 2. Posible falla de "
                       "catalizador banco 2 por sincronizacion incorrecta.",
            related_dtcs=["P0020", "P0021", "P0022", "P0023", "P0024"],
            chain_rules=["CAT-002"],
            confidence_base=0.84,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="VVT-003",
            name="Tensor de cadena de distribucion",
            system=VehicleSystem.VVT,
            severity=Severity.GRAVE,
            description="Posible problema con tensor de cadena de distribucion",
            condition=lambda d: (
                _dtc_any(d, ["P0011", "P0021"])
                and _dtc_any(d, ["P0341", "P0016", "P0017"])
            ),
            diagnosis="La combinacion de codigos VVT y posicion de arbol de levas sugiere "
                       "un problema con el tensor o la cadena de distribucion.",
            probable_causes=[
                "Tensor de cadena defectuoso",
                "Cadena de distribucion estirada",
                "Guias de cadena desgastadas",
            ],
            corrective_actions=[
                "Inspeccionar tensor de cadena de distribucion",
                "Verificar estiramiento de cadena con osciloscopio (CKP vs CMP)",
                "Reemplazar cadena, tensores y guias como conjunto",
            ],
            prediction="Riesgo ALTO de salto de tiempo de distribucion. "
                       "Puede causar contacto valvula-piston (danio catastrofico en motores de interferencia).",
            related_dtcs=["P0011", "P0021", "P0016", "P0017", "P0341"],
            confidence_base=0.82,
            min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS: ABS (ABS-xxx)
    # ==================================================================

    def _load_abs_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="ABS-001",
            name="Sensor de velocidad de rueda - Delantero izquierdo",
            system=VehicleSystem.ABS,
            severity=Severity.GRAVE,
            description="Problema con sensor de velocidad de rueda delantero izquierdo",
            condition=lambda d: _dtc_any(d, ["C0035", "C0040", "C0041"]),
            diagnosis="El sensor de velocidad de rueda delantero izquierdo no funciona. "
                       "El sistema ABS esta desactivado.",
            probable_causes=[
                "Sensor de velocidad de rueda defectuoso",
                "Anillo reluctor danado o sucio",
                "Cableado del sensor danado",
                "Rodamiento de rueda con juego excesivo",
            ],
            corrective_actions=[
                "Inspeccionar sensor y anillo reluctor",
                "Verificar gap del sensor",
                "Inspeccionar cableado y conector",
                "Verificar rodamiento de rueda",
            ],
            prediction="ABS inoperante. En frenado de emergencia, las ruedas pueden bloquearse. "
                       "Control de estabilidad (ESP) tambien puede desactivarse.",
            related_dtcs=["C0035", "C0040", "C0041"],
            confidence_base=0.86,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ABS-002",
            name="Sensor de velocidad de rueda - Delantero derecho",
            system=VehicleSystem.ABS,
            severity=Severity.GRAVE,
            description="Problema con sensor de velocidad de rueda delantero derecho",
            condition=lambda d: _dtc_any(d, ["C0045", "C0050", "C0051"]),
            diagnosis="El sensor de velocidad de rueda delantero derecho no funciona. ABS desactivado.",
            probable_causes=[
                "Sensor de velocidad de rueda defectuoso",
                "Anillo reluctor danado",
                "Cableado danado",
                "Rodamiento de rueda con juego",
            ],
            corrective_actions=[
                "Inspeccionar sensor y anillo reluctor",
                "Verificar cableado y conector",
                "Verificar rodamiento de rueda",
            ],
            prediction="ABS no funcional. Frenado inseguro en superficies resbaladizas.",
            related_dtcs=["C0045", "C0050", "C0051"],
            confidence_base=0.86,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ABS-003",
            name="Sensor de velocidad de rueda - Trasero izquierdo",
            system=VehicleSystem.ABS,
            severity=Severity.GRAVE,
            description="Problema con sensor de velocidad de rueda trasero izquierdo",
            condition=lambda d: _dtc_any(d, ["C0055", "C0060", "C0061"]),
            diagnosis="El sensor de velocidad de rueda trasero izquierdo tiene falla.",
            probable_causes=[
                "Sensor de velocidad de rueda defectuoso",
                "Anillo reluctor danado",
                "Cableado danado por exposicion al ambiente",
            ],
            corrective_actions=[
                "Inspeccionar sensor y anillo reluctor",
                "Verificar cableado (revisar por danos de corrosion)",
                "Reemplazar sensor si defectuoso",
            ],
            prediction="ABS parcialmente inoperante. Control de traccion afectado.",
            related_dtcs=["C0055", "C0060", "C0061"],
            confidence_base=0.86,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ABS-004",
            name="Sensor de velocidad de rueda - Trasero derecho",
            system=VehicleSystem.ABS,
            severity=Severity.GRAVE,
            description="Problema con sensor de velocidad de rueda trasero derecho",
            condition=lambda d: _dtc_any(d, ["C0065", "C0070", "C0071"]),
            diagnosis="El sensor de velocidad de rueda trasero derecho tiene falla.",
            probable_causes=[
                "Sensor de velocidad defectuoso",
                "Anillo reluctor danado",
                "Cableado corroido",
            ],
            corrective_actions=[
                "Inspeccionar sensor y anillo reluctor",
                "Verificar cableado",
                "Reemplazar sensor si defectuoso",
            ],
            prediction="ABS parcialmente inoperante. Frenado trasero sin control ABS.",
            related_dtcs=["C0065", "C0070", "C0071"],
            confidence_base=0.86,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ABS-005",
            name="Modulo de control ABS",
            system=VehicleSystem.ABS,
            severity=Severity.CRITICO,
            description="Falla del modulo de control ABS",
            condition=lambda d: _dtc_any(d, ["C0110", "C0121", "C0161", "U0121"]),
            diagnosis="El modulo de control del ABS reporta una falla interna. "
                       "El sistema ABS esta completamente desactivado.",
            probable_causes=[
                "Modulo ABS con falla electronica interna",
                "Bomba ABS defectuosa",
                "Falla de alimentacion electrica al modulo",
                "Corrosion en el conector del modulo",
            ],
            corrective_actions=[
                "Verificar alimentacion y tierras del modulo ABS",
                "Inspeccionar conector del modulo por corrosion",
                "Verificar fusibles del sistema ABS",
                "Puede requerir reemplazo del modulo ABS",
            ],
            prediction="ABS y ESC completamente inoperantes. Frenado solo mecanico. "
                       "RIESGO ELEVADO en superficies mojadas.",
            related_dtcs=["C0110", "C0121", "C0161", "U0121"],
            confidence_base=0.88,
            min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS: AIRBAG (AIR-xxx)
    # ==================================================================

    def _load_airbag_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="AIR-001",
            name="Falla del sistema de airbag",
            system=VehicleSystem.AIRBAG,
            severity=Severity.CRITICO,
            description="Falla general del sistema de bolsas de aire",
            condition=lambda d: _dtc_any(d, ["B0001", "B0002", "B0003", "B0010"]),
            diagnosis="El sistema de bolsas de aire (SRS) reporta una falla. "
                       "Las bolsas de aire pueden NO desplegarse en un accidente.",
            probable_causes=[
                "Sensor de impacto defectuoso",
                "Modulo de control SRS defectuoso",
                "Cableado del sistema SRS danado",
                "Conector del relo de reloj (clock spring) danado",
            ],
            corrective_actions=[
                "Diagnosticar con escaner avanzado de airbag",
                "No intentar reparacion casera - RIESGO DE DESPLIEGUE",
                "Llevar a taller especializado en SRS",
                "Verificar si hay recalls del fabricante",
            ],
            prediction="SISTEMA DE SEGURIDAD CRITICO comprometido. Las bolsas de aire "
                       "NO se desplegaran en caso de accidente.",
            related_dtcs=["B0001", "B0002", "B0003", "B0010"],
            confidence_base=0.90,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AIR-002",
            name="Clock spring / contacto rotativo",
            system=VehicleSystem.AIRBAG,
            severity=Severity.GRAVE,
            description="Problema con el contacto rotativo del volante",
            condition=lambda d: _dtc_any(d, ["B0050", "B0051", "B0053"]),
            diagnosis="El contacto rotativo (clock spring) del volante tiene una falla. "
                       "Afecta airbag del conductor, claxon y controles del volante.",
            probable_causes=[
                "Clock spring desgastado o roto",
                "Conector del clock spring desconectado",
                "Danio al clock spring por reparacion anterior del volante",
            ],
            corrective_actions=[
                "Reemplazar el clock spring",
                "Verificar que la instalacion del volante sea correcta",
                "Comprobar claxon y controles del volante despues de reparacion",
            ],
            prediction="Airbag del conductor no se desplegara. Claxon inoperante. "
                       "Controles del volante pueden no funcionar.",
            related_dtcs=["B0050", "B0051", "B0053"],
            confidence_base=0.87,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AIR-003",
            name="Sensor de ocupante del asiento",
            system=VehicleSystem.AIRBAG,
            severity=Severity.MODERADO,
            description="Problema con sensor de ocupante del asiento del pasajero",
            condition=lambda d: _dtc_any(d, ["B0071", "B0072", "B0081"]),
            diagnosis="El sensor de presencia de ocupante del asiento del pasajero tiene una falla. "
                       "El airbag del pasajero puede no funcionar correctamente.",
            probable_causes=[
                "Sensor de peso/presencia del asiento defectuoso",
                "Conector bajo el asiento desconectado",
                "Tapizado del asiento interferiendo con el sensor",
            ],
            corrective_actions=[
                "Verificar conector bajo el asiento del pasajero",
                "Inspeccionar sensor de peso del asiento",
                "Verificar que no haya objetos bajo el asiento",
            ],
            prediction="Airbag del pasajero puede no desplegarse o desplegarse incorrectamente.",
            related_dtcs=["B0071", "B0072", "B0081"],
            confidence_base=0.85,
            min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS: EMISIONES GENERALES (EMIS-xxx)
    # ==================================================================

    def _load_emission_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="EMIS-001",
            name="Readiness monitors incompletos",
            system=VehicleSystem.EMISION,
            severity=Severity.LEVE,
            description="Monitores de emision no completados",
            condition=lambda d: (
                _sensor(d, "monitors_incomplete", 0) > 2
            ),
            diagnosis="Hay mas de 2 monitores de emision sin completar. "
                       "El vehiculo no pasara la inspeccion de emisiones.",
            probable_causes=[
                "Bateria desconectada recientemente",
                "Codigos borrados recientemente",
                "No se ha conducido suficiente para completar los ciclos",
            ],
            corrective_actions=[
                "Conducir el vehiculo en ciclo de conduccion mixto (ciudad/carretera)",
                "Completar al menos 2 ciclos de calentamiento completo",
                "Verificar que no haya DTCs pendientes que impidan los monitores",
            ],
            prediction="No aprobara la inspeccion de emisiones hasta que los monitores "
                       "se completen.",
            related_dtcs=[],
            confidence_base=0.90,
            min_sensors_required=["monitors_incomplete"],
        ))

        self._add(DiagnosticRule(
            rule_id="EMIS-002",
            name="MIL (Check Engine) encendido",
            system=VehicleSystem.EMISION,
            severity=Severity.MODERADO,
            description="Luz indicadora de falla del motor encendida",
            condition=lambda d: _sensor(d, "mil_status", False) is True,
            diagnosis="La luz de Check Engine (MIL) esta encendida. Hay al menos un "
                       "codigo de diagnostico activo que requiere atencion.",
            probable_causes=[
                "Cualquier falla que genere un DTC confirmado",
                "Tapa de combustible suelta (causa comun)",
                "Sensor de oxigeno defectuoso (causa frecuente)",
            ],
            corrective_actions=[
                "Leer y diagnosticar los codigos DTC almacenados",
                "Verificar tapa de combustible como primera medida",
                "No ignorar - diagnosticar causa raiz",
            ],
            prediction="El vehiculo no pasara la inspeccion de emisiones. "
                       "La falla subyacente puede empeorar.",
            related_dtcs=[],
            confidence_base=0.95,
            min_sensors_required=["mil_status"],
        ))

    # ==================================================================
    # REGLAS: MOTOR MECANICO (MECH-xxx)
    # ==================================================================

    def _load_engine_mechanical_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="MECH-001",
            name="RPM erraticas en ralenti",
            system=VehicleSystem.MOTOR,
            severity=Severity.MODERADO,
            description="Fluctuacion anormal de RPM en ralenti",
            condition=lambda d: (
                _has_sensor(d, "rpm")
                and _sensor(d, "throttle_pos", 0) < 3
                and _sensor(d, "rpm", 800) < 400
            ),
            diagnosis="Las RPM en ralenti estan muy bajas, indicando que el motor "
                       "tiene dificultad para mantenerse encendido.",
            probable_causes=[
                "Valvula de control de ralenti defectuosa",
                "Fuga de vacio",
                "Inyectores sucios",
                "Bujias desgastadas",
                "Sensor IAT defectuoso",
            ],
            corrective_actions=[
                "Limpiar cuerpo de aceleracion",
                "Inspeccionar mangueras de vacio",
                "Limpiar inyectores",
                "Verificar bujias",
            ],
            prediction="El motor puede calarse frecuentemente. Mayor desgaste de componentes.",
            related_dtcs=["P0505", "P0506"],
            confidence_base=0.82,
            min_sensors_required=["rpm", "throttle_pos"],
        ))

        self._add(DiagnosticRule(
            rule_id="MECH-002",
            name="Presion de aceite baja",
            system=VehicleSystem.MOTOR,
            severity=Severity.CRITICO,
            description="Presion de aceite por debajo del minimo",
            condition=lambda d: (
                _has_sensor(d, "oil_pressure")
                and _sensor(d, "oil_pressure", 999) < 15
                and _sensor(d, "rpm", 0) > 800
            ),
            diagnosis="ALERTA CRITICA: La presion de aceite esta peligrosamente baja. "
                       "El motor puede sufrir danio severo por falta de lubricacion.",
            probable_causes=[
                "Nivel de aceite criticamente bajo",
                "Bomba de aceite defectuosa",
                "Filtro de aceite obstruido",
                "Cojinetes de biela o bancada desgastados",
                "Sensor de presion defectuoso (verificar primero)",
            ],
            corrective_actions=[
                "DETENER EL MOTOR INMEDIATAMENTE",
                "Verificar nivel de aceite",
                "No arrancar hasta confirmar nivel correcto",
                "Si el nivel es correcto, remolcar al taller",
            ],
            prediction="Danio catastrofico al motor en minutos: fundicion de cojinetes, "
                       "rayado de ciguenal, gripe de motor.",
            related_dtcs=[],
            confidence_base=0.93,
            min_sensors_required=["oil_pressure", "rpm"],
        ))

        self._add(DiagnosticRule(
            rule_id="MECH-003",
            name="Temperatura de aceite alta",
            system=VehicleSystem.MOTOR,
            severity=Severity.GRAVE,
            description="Temperatura del aceite del motor excesiva",
            condition=lambda d: (
                _has_sensor(d, "oil_temp")
                and _sensor(d, "oil_temp", 0) > 130
            ),
            diagnosis="La temperatura del aceite supera los 130 C. El aceite pierde "
                       "sus propiedades lubricantes a esta temperatura.",
            probable_causes=[
                "Enfriador de aceite obstruido o defectuoso",
                "Nivel de aceite bajo",
                "Aceite degradado o viscosidad incorrecta",
                "Conduccion severa (remolque, carreras)",
                "Sistema de refrigeracion con problema asociado",
            ],
            corrective_actions=[
                "Reducir la exigencia al motor",
                "Verificar nivel de aceite",
                "Inspeccionar enfriador de aceite",
                "Cambiar aceite si esta degradado",
            ],
            prediction="Degradacion acelerada del aceite. Desgaste prematuro de "
                       "cojinetes y partes moviles.",
            related_dtcs=[],
            chain_rules=["COOL-002"],
            confidence_base=0.85,
            min_sensors_required=["oil_temp"],
        ))

        self._add(DiagnosticRule(
            rule_id="MECH-004",
            name="Carga excesiva del motor",
            system=VehicleSystem.MOTOR,
            severity=Severity.MODERADO,
            description="Motor operando con carga excesiva prolongada",
            condition=lambda d: (
                _sensor(d, "engine_load", 0) > 90
                and _sensor(d, "rpm", 0) > 4000
                and _sensor(d, "coolant_temp", 0) > 100
            ),
            diagnosis="El motor esta operando con carga muy alta, RPM elevadas y temperatura "
                       "elevada. Condiciones de estres extremo.",
            probable_causes=[
                "Conduccion agresiva o deportiva prolongada",
                "Remolque de carga excesiva",
                "Subida prolongada en pendiente",
                "Problema mecanico que aumenta resistencia (freno aplicado)",
            ],
            corrective_actions=[
                "Reducir velocidad y carga del motor",
                "Verificar que ningun freno este aplicado",
                "Dejar enfriar el motor en ralenti",
                "Verificar temperatura de transmision tambien",
            ],
            prediction="En estas condiciones: aceite degradandose, posible detonacion, "
                       "estres en junta de culata.",
            related_dtcs=[],
            chain_rules=["COOL-002", "TRANS-001"],
            confidence_base=0.80,
            min_sensors_required=["engine_load", "rpm", "coolant_temp"],
        ))

        self._add(DiagnosticRule(
            rule_id="MECH-005",
            name="Vibracion del motor - soporte danado",
            system=VehicleSystem.MOTOR,
            severity=Severity.MODERADO,
            description="Patron de vibracion sugiere soporte de motor danado",
            condition=lambda d: (
                _sensor(d, "rpm", 800) < 700
                and _sensor(d, "throttle_pos", 0) < 3
                and _dtc_any(d, ["P0300", "P0301", "P0302", "P0303", "P0304"])
            ),
            diagnosis="RPM bajo en ralenti combinado con fallas de encendido puede indicar "
                       "soportes de motor desgastados que permiten vibracion excesiva.",
            probable_causes=[
                "Soportes de motor (montajes) desgastados",
                "Soporte de transmision danado",
                "Falla de encendido contribuyendo a vibracion",
            ],
            corrective_actions=[
                "Inspeccionar visualmente soportes de motor",
                "Verificar soportes con palanca (no debe haber movimiento excesivo)",
                "Corregir falla de encendido primero",
                "Reemplazar soportes desgastados",
            ],
            prediction="Vibracion excesiva puede danar mangueras, cables y componentes cercanos.",
            related_dtcs=["P0300"],
            confidence_base=0.72,
            min_sensors_required=["rpm", "throttle_pos"],
        ))

    # ==================================================================
    # REGLAS: COMUNICACION (COMM-xxx)
    # ==================================================================

    def _load_communication_rules(self) -> None:

        comm_modules = [
            ("COMM-001", "ECU/PCM", "U0100", "modulo de control del motor (PCM/ECM)"),
            ("COMM-002", "TCM", "U0101", "modulo de control de transmision (TCM)"),
            ("COMM-003", "ABS/ESC", "U0121", "modulo ABS/control de estabilidad"),
            ("COMM-004", "SRS/Airbag", "U0151", "modulo de bolsas de aire (SRS)"),
            ("COMM-005", "Instrumentos", "U0155", "cluster de instrumentos"),
            ("COMM-006", "HVAC", "U0164", "modulo de climatizacion (HVAC)"),
            ("COMM-007", "BCM", "U0140", "modulo de control de carroceria (BCM)"),
        ]

        for rule_id, mod_name, dtc, description in comm_modules:
            self._add(DiagnosticRule(
                rule_id=rule_id,
                name=f"Perdida de comunicacion con {mod_name}",
                system=VehicleSystem.COMUNICACION,
                severity=Severity.GRAVE,
                description=f"Sin comunicacion CAN-Bus con {description}",
                condition=(lambda d, _dtc=dtc: _dtc_present(d, _dtc)),
                diagnosis=f"Se perdio la comunicacion CAN-Bus con el {description}. "
                           f"El modulo no responde en la red del vehiculo.",
                probable_causes=[
                    f"Modulo {mod_name} con falla interna",
                    f"Cableado CAN-Bus al {mod_name} danado",
                    f"Conector del {mod_name} desconectado",
                    "Problema general en la red CAN-Bus",
                    f"Fusible de alimentacion del {mod_name} fundido",
                ],
                corrective_actions=[
                    f"Verificar fusible del {mod_name}",
                    f"Inspeccionar conector del {mod_name}",
                    "Verificar resistencias de terminacion CAN-Bus",
                    f"Verificar alimentacion y tierra del {mod_name}",
                    "Diagnosticar red CAN-Bus con osciloscopio",
                ],
                prediction=f"Funciones controladas por {mod_name} inoperantes. "
                            f"Otros modulos pueden mostrar errores secundarios.",
                related_dtcs=[dtc],
                confidence_base=0.88,
                min_sensors_required=[],
            ))

        self._add(DiagnosticRule(
            rule_id="COMM-010",
            name="Multiples perdidas de comunicacion CAN",
            system=VehicleSystem.COMUNICACION,
            severity=Severity.CRITICO,
            description="Multiples modulos sin comunicacion en red CAN",
            condition=lambda d: (
                sum(1 for dtc in ["U0100", "U0101", "U0121", "U0140", "U0151", "U0155"]
                    if _dtc_present(d, dtc)) >= 2
            ),
            diagnosis="Multiples modulos han perdido comunicacion CAN. "
                       "Esto indica un problema en el bus CAN comun, no en modulos individuales.",
            probable_causes=[
                "Cable CAN-H o CAN-L cortado o en cortocircuito",
                "Resistencia de terminacion CAN faltante o danada",
                "Conector principal del bus CAN danado",
                "Modulo con falla que esta cortocircuitando el bus",
                "Interferencia electromagnetica severa",
            ],
            corrective_actions=[
                "Medir resistencia del bus CAN (debe ser ~60 ohms entre H y L)",
                "Verificar forma de onda CAN con osciloscopio",
                "Desconectar modulos uno por uno para aislar falla",
                "Inspeccionar arnes principal del bus CAN",
            ],
            prediction="Vehiculo puede quedar inmovil. Sistemas criticos de seguridad "
                       "(ABS, airbag) inoperantes.",
            related_dtcs=["U0100", "U0101", "U0121", "U0140"],
            confidence_base=0.90,
            min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS: AIRE ACONDICIONADO (AC-xxx)
    # ==================================================================

    def _load_ac_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="AC-001",
            name="Presion de refrigerante AC baja",
            system=VehicleSystem.AIRE_ACONDICIONADO,
            severity=Severity.LEVE,
            description="Presion baja en el sistema de aire acondicionado",
            condition=lambda d: (
                _has_sensor(d, "ac_pressure_low")
                and _sensor(d, "ac_pressure_low", 30) < 15
            ),
            diagnosis="La presion en el lado de baja del sistema de AC es insuficiente. "
                       "Posible fuga de refrigerante.",
            probable_causes=[
                "Fuga de refrigerante en el sistema AC",
                "Compresor de AC debil",
                "Valvula de expansion obstruida",
                "Nivel bajo de refrigerante AC",
            ],
            corrective_actions=[
                "Verificar nivel de refrigerante AC con manometros",
                "Realizar prueba de fugas con detector de UV",
                "Recargar refrigerante si esta bajo",
                "Reparar fugas antes de recargar",
            ],
            prediction="El AC dejara de enfriar progresivamente. Sin refrigerante, "
                       "el compresor puede danarse.",
            related_dtcs=[],
            confidence_base=0.80,
            min_sensors_required=["ac_pressure_low"],
        ))

        self._add(DiagnosticRule(
            rule_id="AC-002",
            name="Presion de AC alta excesiva",
            system=VehicleSystem.AIRE_ACONDICIONADO,
            severity=Severity.MODERADO,
            description="Presion excesiva en el lado de alta del AC",
            condition=lambda d: (
                _has_sensor(d, "ac_pressure_high")
                and _sensor(d, "ac_pressure_high", 150) > 350
            ),
            diagnosis="La presion en el lado de alta del sistema AC es excesiva. "
                       "El sistema esta sobrecargado o hay obstruccion.",
            probable_causes=[
                "Sobrecarga de refrigerante",
                "Condensador obstruido o ventilador inoperante",
                "Obstruccion en el sistema AC",
                "Valvula de expansion defectuosa",
            ],
            corrective_actions=[
                "Verificar funcionamiento del ventilador del condensador",
                "Limpiar el condensador",
                "Verificar carga de refrigerante",
                "Inspeccionar valvula de expansion",
            ],
            prediction="Riesgo de danio al compresor por presion excesiva. "
                       "Posible rotura de manguera.",
            related_dtcs=[],
            confidence_base=0.80,
            min_sensors_required=["ac_pressure_high"],
        ))

    # ==================================================================
    # REGLAS: DIRECCION (STEER-xxx)
    # ==================================================================

    def _load_steering_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="STEER-001",
            name="Falla en direccion asistida electrica (EPS)",
            system=VehicleSystem.DIRECCION,
            severity=Severity.CRITICO,
            description="Falla en el sistema de direccion asistida electrica",
            condition=lambda d: _dtc_any(d, ["C0545", "C0550", "C0460", "C0470"]),
            diagnosis="El sistema de direccion asistida electrica (EPS) ha fallado. "
                       "La direccion puede sentirse extremadamente dura.",
            probable_causes=[
                "Motor de la EPS defectuoso",
                "Sensor de torque del volante defectuoso",
                "Modulo de control de EPS con falla",
                "Cableado del sistema EPS danado",
                "Fusible de la EPS fundido",
            ],
            corrective_actions=[
                "Verificar fusible del sistema EPS",
                "Inspeccionar conector del modulo EPS",
                "Diagnosticar sensor de torque",
                "Llevar a taller con equipo de diagnostico EPS",
            ],
            prediction="Conduccion peligrosa sin asistencia de direccion, especialmente "
                       "a baja velocidad y en estacionamiento.",
            related_dtcs=["C0545", "C0550", "C0460", "C0470"],
            confidence_base=0.88,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="STEER-002",
            name="Sensor de angulo de direccion",
            system=VehicleSystem.DIRECCION,
            severity=Severity.MODERADO,
            description="Problema con sensor de angulo de direccion",
            condition=lambda d: _dtc_any(d, ["C0455", "C0456", "U0126"]),
            diagnosis="El sensor de angulo de direccion no reporta correctamente. "
                       "Afecta el control de estabilidad y la asistencia de direccion.",
            probable_causes=[
                "Sensor de angulo de direccion defectuoso",
                "Sensor no calibrado despues de alineacion",
                "Cableado del sensor danado",
            ],
            corrective_actions=[
                "Recalibrar sensor de angulo de direccion",
                "Verificar alineacion del vehiculo",
                "Inspeccionar cableado del sensor",
                "Reemplazar sensor si defectuoso",
            ],
            prediction="ESC/ESP no funcional. Asistencia variable de direccion incorrecta.",
            related_dtcs=["C0455", "C0456", "U0126"],
            confidence_base=0.84,
            min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS: SENSORES GENERICOS (SENS-xxx)
    # ==================================================================

    def _load_generic_sensor_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="SENS-001",
            name="Sensor IAT fuera de rango",
            system=VehicleSystem.MOTOR,
            severity=Severity.LEVE,
            description="Sensor de temperatura de aire de admision con lectura anormal",
            condition=lambda d: _dtc_any(d, ["P0110", "P0111", "P0112", "P0113"]),
            diagnosis="El sensor de temperatura del aire de admision (IAT) reporta valores fuera de rango.",
            probable_causes=[
                "Sensor IAT defectuoso",
                "Conector del sensor IAT corroido",
                "Cableado del sensor danado",
            ],
            corrective_actions=[
                "Verificar conector del sensor IAT",
                "Medir resistencia del sensor (debe variar con temperatura)",
                "Reemplazar sensor IAT si defectuoso",
            ],
            prediction="La ECU calcula incorrectamente la densidad del aire. "
                       "Menor eficiencia de combustible.",
            related_dtcs=["P0110", "P0111", "P0112", "P0113"],
            confidence_base=0.85,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="SENS-002",
            name="Sensor de velocidad del vehiculo (VSS)",
            system=VehicleSystem.MOTOR,
            severity=Severity.MODERADO,
            description="Problema con sensor de velocidad del vehiculo",
            condition=lambda d: _dtc_any(d, ["P0500", "P0501", "P0502", "P0503"]),
            diagnosis="El sensor de velocidad del vehiculo (VSS) reporta valores incorrectos. "
                       "Afecta el velocimetro y los cambios de transmision.",
            probable_causes=[
                "Sensor VSS defectuoso",
                "Engranaje impulsor del sensor danado",
                "Cableado del sensor danado",
                "Modulo de instrumentos defectuoso",
            ],
            corrective_actions=[
                "Verificar senal del sensor VSS",
                "Inspeccionar engranaje impulsor",
                "Verificar cableado y conector",
                "Reemplazar sensor VSS si defectuoso",
            ],
            prediction="Velocimetro incorrecto, cambios de transmision erraticos, "
                       "control de crucero inoperante.",
            related_dtcs=["P0500", "P0501", "P0502", "P0503"],
            confidence_base=0.85,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="SENS-003",
            name="Sensor de presion barometrica (BARO)",
            system=VehicleSystem.MOTOR,
            severity=Severity.LEVE,
            description="Sensor de presion barometrica con lectura anormal",
            condition=lambda d: _dtc_any(d, ["P0069", "P0070"]),
            diagnosis="El sensor de presion barometrica reporta valores fuera de rango. "
                       "La ECU no puede compensar correctamente por altitud.",
            probable_causes=[
                "Sensor barometrico defectuoso",
                "El sensor MAP esta siendo usado como BARO y tiene falla",
            ],
            corrective_actions=[
                "Verificar sensor barometrico",
                "Comparar lectura con presion barometrica real",
                "Reemplazar si esta fuera de especificacion",
            ],
            prediction="Mezcla aire-combustible ligeramente incorrecta. "
                       "Mayor impacto en zonas de alta altitud.",
            related_dtcs=["P0069", "P0070"],
            confidence_base=0.80,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="SENS-004",
            name="Circuito del sensor de temperatura de escape",
            system=VehicleSystem.ESCAPE,
            severity=Severity.MODERADO,
            description="Problema con sensor de temperatura de gases de escape",
            condition=lambda d: _dtc_any(d, ["P0544", "P0545", "P0546"]),
            diagnosis="El sensor de temperatura de gases de escape tiene un problema de circuito.",
            probable_causes=[
                "Sensor de temperatura de escape defectuoso",
                "Cableado del sensor danado por calor",
                "Conector fundido o derretido",
            ],
            corrective_actions=[
                "Inspeccionar sensor y cableado (zona de alta temperatura)",
                "Verificar conector por danos por calor",
                "Reemplazar sensor si defectuoso",
            ],
            prediction="Sin proteccion contra sobrecalentamiento del catalizador/turbo.",
            related_dtcs=["P0544", "P0545", "P0546"],
            confidence_base=0.83,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="SENS-005",
            name="Sensor de temperatura del aire de admision alto",
            system=VehicleSystem.MOTOR,
            severity=Severity.MODERADO,
            description="Temperatura de aire de admision excesiva",
            condition=lambda d: (
                _has_sensor(d, "intake_air_temp")
                and _sensor(d, "intake_air_temp", 25) > 70
            ),
            diagnosis="La temperatura del aire de admision es excesivamente alta (>70 C). "
                       "Reduce la potencia y aumenta riesgo de detonacion.",
            probable_causes=[
                "Intercooler obstruido o ineficiente (motores turbo)",
                "Conducto de aire caliente (toma cerca del motor)",
                "Filtro de aire muy restringido",
                "Heat soak despues de conduccion y parada",
            ],
            corrective_actions=[
                "Verificar intercooler y sus mangueras (motores turbo)",
                "Inspeccionar sistema de admision de aire",
                "Verificar filtro de aire",
                "Considerar mejora en la toma de aire",
            ],
            prediction="Perdida de potencia por aire caliente menos denso. "
                       "Riesgo de detonacion bajo carga.",
            related_dtcs=[],
            confidence_base=0.78,
            min_sensors_required=["intake_air_temp"],
        ))

        self._add(DiagnosticRule(
            rule_id="SENS-006",
            name="Sensor APP (Pedal de acelerador)",
            system=VehicleSystem.ACELERADOR,
            severity=Severity.GRAVE,
            description="Problema con sensor de posicion del pedal de acelerador",
            condition=lambda d: _dtc_any(d, ["P2122", "P2123", "P2127", "P2128", "P2138"]),
            diagnosis="El sensor de posicion del pedal de acelerador (APP) tiene una falla. "
                       "El vehiculo entrara en modo limp.",
            probable_causes=[
                "Sensor APP defectuoso",
                "Cableado del pedal de acelerador danado",
                "Conector del sensor APP corroido",
                "Pedal de acelerador danado mecanicamente",
            ],
            corrective_actions=[
                "Verificar voltaje del sensor APP",
                "Inspeccionar conector y cableado",
                "Verificar mecanismo del pedal",
                "Reemplazar modulo del pedal si defectuoso",
            ],
            prediction="Vehiculo en modo limp con aceleracion limitada. "
                       "No podra superar 50-60 km/h.",
            related_dtcs=["P2122", "P2123", "P2127", "P2128", "P2138"],
            confidence_base=0.88,
            min_sensors_required=[],
        ))

        # Sensor de oxigeno de banda ancha (wideband)
        self._add(DiagnosticRule(
            rule_id="SENS-007",
            name="Sensor de relacion aire-combustible (A/F)",
            system=VehicleSystem.SENSOR_O2,
            severity=Severity.MODERADO,
            description="Problema con sensor de relacion aire-combustible",
            condition=lambda d: _dtc_any(d, ["P2195", "P2196", "P2197", "P2198"]),
            diagnosis="El sensor de relacion aire-combustible (sensor O2 de banda ancha) "
                       "indica mezcla consistentemente rica o pobre.",
            probable_causes=[
                "Sensor A/F desgastado",
                "Fuga de escape antes del sensor",
                "Problema real de mezcla (fuga de vacio, inyector)",
            ],
            corrective_actions=[
                "Verificar si hay fuga de escape antes del sensor",
                "Descartar problemas reales de mezcla primero",
                "Reemplazar sensor A/F si la mezcla es correcta",
            ],
            prediction="Sin correccion precisa de mezcla. Mayor consumo y emisiones.",
            related_dtcs=["P2195", "P2196", "P2197", "P2198"],
            confidence_base=0.82,
            min_sensors_required=[],
        ))

        # Mas reglas para completar 200+
        self._add(DiagnosticRule(
            rule_id="SENS-008",
            name="Sensor de nivel de combustible",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.LEVE,
            description="Problema con sensor de nivel de combustible",
            condition=lambda d: _dtc_any(d, ["P0460", "P0461", "P0462", "P0463"]),
            diagnosis="El sensor de nivel de combustible reporta valores erraticos. "
                       "El indicador de combustible no es confiable.",
            probable_causes=[
                "Flotador del sensor de nivel atascado",
                "Resistencia del sensor desgastada",
                "Cableado del sensor danado",
            ],
            corrective_actions=[
                "Verificar resistencia del sensor de nivel",
                "Inspeccionar flotador del sensor",
                "Reemplazar unidad emisora de nivel",
            ],
            prediction="Indicador de combustible erratico. Riesgo de quedarse sin combustible.",
            related_dtcs=["P0460", "P0461", "P0462", "P0463"],
            confidence_base=0.83,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="SENS-009",
            name="Sensor de temperatura de transmision",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.LEVE,
            description="Problema con sensor de temperatura de transmision",
            condition=lambda d: _dtc_any(d, ["P0710", "P0711", "P0712", "P0713"]),
            diagnosis="El sensor de temperatura del fluido de transmision reporta valores anormales.",
            probable_causes=[
                "Sensor de temperatura de transmision defectuoso",
                "Cableado del sensor danado",
                "Fluido de transmision contaminado afectando sensor",
            ],
            corrective_actions=[
                "Verificar resistencia del sensor de temperatura",
                "Inspeccionar conector y cableado",
                "Reemplazar sensor si defectuoso",
            ],
            prediction="La transmision no puede protegerse contra sobrecalentamiento.",
            related_dtcs=["P0710", "P0711", "P0712", "P0713"],
            confidence_base=0.83,
            min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="SENS-010",
            name="Rango alto de sensor de temperatura de admision",
            system=VehicleSystem.MOTOR,
            severity=Severity.MODERADO,
            description="Temperatura de admision anormalmente alta",
            condition=lambda d: (
                _has_sensor(d, "intake_air_temp")
                and _sensor(d, "intake_air_temp", 25) > 90
            ),
            diagnosis="Temperatura del aire de admision extremadamente alta (>90 C). "
                       "Condiciones criticas para la combustion.",
            probable_causes=[
                "Intercooler con falla total",
                "Admision de aire caliente directa del motor",
                "Sensor IAT defectuoso (lectura alta falsa)",
            ],
            corrective_actions=[
                "Verificar sensor IAT con termometro de referencia",
                "Inspeccionar sistema de admision de aire",
                "Verificar intercooler (motores turbo)",
            ],
            prediction="Detonacion severa posible. Perdida significativa de potencia.",
            related_dtcs=["P0113"],
            confidence_base=0.80,
            min_sensors_required=["intake_air_temp"],
        ))

        # Reglas adicionales para sensor de posicion del ciguenal intermitente
        self._add(DiagnosticRule(
            rule_id="SENS-011",
            name="Senal intermitente del sensor CKP",
            system=VehicleSystem.ENCENDIDO,
            severity=Severity.GRAVE,
            description="Senal intermitente del sensor de posicion del ciguenal",
            condition=lambda d: (
                _dtc_present(d, "P0336")
                and _has_sensor(d, "rpm")
                and _sensor(d, "rpm", 800) > 0
            ),
            diagnosis="El sensor CKP tiene senal intermitente mientras el motor funciona. "
                       "Puede causar paradas repentinas del motor.",
            probable_causes=[
                "Gap del sensor CKP incorrecto",
                "Conector del sensor con contacto intermitente",
                "Rueda reluctora con acumulacion de virutas metalicas",
                "Cableado del sensor rozando y haciendo contacto intermitente",
            ],
            corrective_actions=[
                "Verificar y ajustar gap del sensor CKP",
                "Limpiar rueda reluctora de virutas metalicas",
                "Inspeccionar cableado por friccion o danos",
                "Verificar conector por terminales flojos",
            ],
            prediction="Paradas imprevistas del motor. Riesgo de quedar varado "
                       "en situaciones peligrosas.",
            related_dtcs=["P0336"],
            confidence_base=0.84,
            min_sensors_required=["rpm"],
        ))

        self._add(DiagnosticRule(
            rule_id="SENS-012",
            name="Correlacion MAP/MAF",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.MODERADO,
            description="Discrepancia entre sensores MAP y MAF",
            condition=lambda d: _dtc_present(d, "P0068"),
            diagnosis="Los sensores MAP y MAF no coinciden en sus lecturas. "
                       "Uno de los dos esta dando informacion incorrecta.",
            probable_causes=[
                "Sensor MAF sucio o defectuoso",
                "Sensor MAP defectuoso",
                "Fuga de aire entre MAF y cuerpo de aceleracion",
                "Manguera de vacio del MAP desconectada",
            ],
            corrective_actions=[
                "Limpiar sensor MAF",
                "Verificar manguera de vacio del MAP",
                "Buscar fugas de aire en el conducto de admision",
                "Comparar lecturas de ambos sensores con valores esperados",
            ],
            prediction="Mezcla incorrecta de combustible. Mayor consumo y posibles fallas.",
            related_dtcs=["P0068"],
            confidence_base=0.82,
            min_sensors_required=[],
        ))

        # Regla para sensor de posicion del pedal del freno
        self._add(DiagnosticRule(
            rule_id="SENS-013",
            name="Switch de luz de freno",
            system=VehicleSystem.MOTOR,
            severity=Severity.MODERADO,
            description="Problema con el interruptor de luz de freno",
            condition=lambda d: _dtc_any(d, ["P0571", "P0572", "P0573"]),
            diagnosis="El interruptor de la luz de freno reporta estado incorrecto. "
                       "Afecta desactivacion del control de crucero y luces de freno.",
            probable_causes=[
                "Interruptor de luz de freno desajustado",
                "Interruptor defectuoso",
                "Cableado del interruptor danado",
            ],
            corrective_actions=[
                "Ajustar posicion del interruptor de luz de freno",
                "Verificar funcionamiento de luces de freno",
                "Reemplazar interruptor si defectuoso",
            ],
            prediction="Luces de freno pueden no encender (peligro para vehiculos detras). "
                       "Control de crucero no se desactiva con freno.",
            related_dtcs=["P0571", "P0572", "P0573"],
            confidence_base=0.86,
            min_sensors_required=[],
        ))

        # Regla para sensor PCV
        self._add(DiagnosticRule(
            rule_id="SENS-014",
            name="Sistema PCV (ventilacion positiva del carter)",
            system=VehicleSystem.MOTOR,
            severity=Severity.LEVE,
            description="Problema con el sistema de ventilacion del carter",
            condition=lambda d: _dtc_any(d, ["P051A", "P051B", "P0171"]) and (
                _has_sensor(d, "short_fuel_trim_1")
                and _sensor(d, "short_fuel_trim_1", 0) > 10
            ),
            diagnosis="Posible falla en el sistema PCV. La valvula PCV puede estar "
                       "atascada abierta causando fuga de vacio.",
            probable_causes=[
                "Valvula PCV atascada abierta",
                "Manguera PCV rota o desconectada",
                "Sello del tapon de aceite danado",
            ],
            corrective_actions=[
                "Inspeccionar valvula PCV y mangueras",
                "Reemplazar valvula PCV",
                "Verificar sello del tapon de aceite",
            ],
            prediction="Fuga de vacio constante. Consumo elevado de aceite. "
                       "Contaminacion del filtro de aire.",
            related_dtcs=["P051A", "P051B"],
            confidence_base=0.75,
            min_sensors_required=["short_fuel_trim_1"],
        ))

        self._add(DiagnosticRule(
            rule_id="SENS-015",
            name="Sensor de presion de aceite",
            system=VehicleSystem.MOTOR,
            severity=Severity.LEVE,
            description="Circuito del sensor de presion de aceite",
            condition=lambda d: _dtc_any(d, ["P0520", "P0521", "P0522", "P0523"]),
            diagnosis="El sensor de presion de aceite tiene un problema de circuito.",
            probable_causes=[
                "Sensor de presion de aceite defectuoso",
                "Cableado del sensor danado",
                "Conector corroido",
            ],
            corrective_actions=[
                "Verificar presion de aceite con manometro mecanico",
                "Inspeccionar sensor y cableado",
                "Reemplazar sensor si defectuoso",
            ],
            prediction="Sin monitoreo de presion de aceite. No se detectara presion baja.",
            related_dtcs=["P0520", "P0521", "P0522", "P0523"],
            confidence_base=0.83,
            min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS ADICIONALES: COMBUSTIBLE (AFUEL-xxx)
    # ==================================================================

    def _load_additional_fuel_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="AFUEL-001",
            name="Inyector cilindro 1 - circuito",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.GRAVE,
            description="Circuito del inyector del cilindro 1",
            condition=lambda d: _dtc_present(d, "P0201"),
            diagnosis="El inyector del cilindro 1 tiene un problema de circuito. "
                       "El cilindro no recibe combustible correctamente.",
            probable_causes=["Inyector 1 defectuoso", "Cableado cortado", "Conector suelto"],
            corrective_actions=["Medir resistencia del inyector 1", "Verificar cableado", "Reemplazar inyector"],
            prediction="Falla de encendido cilindro 1. Danio al catalizador.",
            related_dtcs=["P0201"], chain_rules=["MIS-101"],
            confidence_base=0.87, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AFUEL-002",
            name="Inyector cilindro 2 - circuito",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.GRAVE,
            description="Circuito del inyector del cilindro 2",
            condition=lambda d: _dtc_present(d, "P0202"),
            diagnosis="El inyector del cilindro 2 tiene un problema de circuito.",
            probable_causes=["Inyector 2 defectuoso", "Cableado cortado", "Conector suelto"],
            corrective_actions=["Medir resistencia del inyector 2", "Verificar cableado", "Reemplazar inyector"],
            prediction="Falla de encendido cilindro 2. Danio al catalizador.",
            related_dtcs=["P0202"], chain_rules=["MIS-102"],
            confidence_base=0.87, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AFUEL-003",
            name="Inyector cilindro 3 - circuito",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.GRAVE,
            description="Circuito del inyector del cilindro 3",
            condition=lambda d: _dtc_present(d, "P0203"),
            diagnosis="El inyector del cilindro 3 tiene un problema de circuito.",
            probable_causes=["Inyector 3 defectuoso", "Cableado cortado", "Conector suelto"],
            corrective_actions=["Medir resistencia del inyector 3", "Verificar cableado", "Reemplazar inyector"],
            prediction="Falla de encendido cilindro 3. Danio al catalizador.",
            related_dtcs=["P0203"], chain_rules=["MIS-103"],
            confidence_base=0.87, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AFUEL-004",
            name="Inyector cilindro 4 - circuito",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.GRAVE,
            description="Circuito del inyector del cilindro 4",
            condition=lambda d: _dtc_present(d, "P0204"),
            diagnosis="El inyector del cilindro 4 tiene un problema de circuito.",
            probable_causes=["Inyector 4 defectuoso", "Cableado cortado", "Conector suelto"],
            corrective_actions=["Medir resistencia del inyector 4", "Verificar cableado", "Reemplazar inyector"],
            prediction="Falla de encendido cilindro 4. Danio al catalizador.",
            related_dtcs=["P0204"], chain_rules=["MIS-104"],
            confidence_base=0.87, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AFUEL-005",
            name="Inyector cilindro 5 - circuito",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.GRAVE,
            description="Circuito del inyector del cilindro 5",
            condition=lambda d: _dtc_present(d, "P0205"),
            diagnosis="El inyector del cilindro 5 tiene un problema de circuito.",
            probable_causes=["Inyector 5 defectuoso", "Cableado cortado"],
            corrective_actions=["Medir resistencia del inyector 5", "Reemplazar inyector"],
            prediction="Falla de encendido cilindro 5.",
            related_dtcs=["P0205"], chain_rules=["MIS-105"],
            confidence_base=0.87, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AFUEL-006",
            name="Inyector cilindro 6 - circuito",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.GRAVE,
            description="Circuito del inyector del cilindro 6",
            condition=lambda d: _dtc_present(d, "P0206"),
            diagnosis="El inyector del cilindro 6 tiene un problema de circuito.",
            probable_causes=["Inyector 6 defectuoso", "Cableado cortado"],
            corrective_actions=["Medir resistencia del inyector 6", "Reemplazar inyector"],
            prediction="Falla de encendido cilindro 6.",
            related_dtcs=["P0206"], chain_rules=["MIS-106"],
            confidence_base=0.87, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AFUEL-007",
            name="Sensor de presion de riel alta presion (GDI)",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.GRAVE,
            description="Presion de riel de alta presion fuera de rango (inyeccion directa)",
            condition=lambda d: _dtc_any(d, ["P0088", "P0089", "P0090", "P0091", "P0092", "P0093"]),
            diagnosis="El sistema de inyeccion directa de combustible tiene un problema "
                       "con la presion del riel de alta presion.",
            probable_causes=[
                "Bomba de alta presion defectuosa",
                "Regulador de presion de riel defectuoso",
                "Sensor de presion de riel danado",
                "Levas de accionamiento de bomba desgastadas",
            ],
            corrective_actions=[
                "Verificar presion de riel con escaner (valor tipico 50-200 bar)",
                "Inspeccionar bomba de alta presion",
                "Verificar sensor de presion de riel",
                "Inspeccionar levas de accionamiento",
            ],
            prediction="Arranque dificil, perdida de potencia, posible calado.",
            related_dtcs=["P0088", "P0089", "P0090", "P0091"],
            confidence_base=0.86, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AFUEL-008",
            name="Control de combustible en limite maximo",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.MODERADO,
            description="Ajuste de combustible en limite de compensacion",
            condition=lambda d: (
                abs(_sensor(d, "short_fuel_trim_1", 0)) > 25
                or abs(_sensor(d, "short_fuel_trim_2", 0)) > 25
            ),
            diagnosis="El ajuste de combustible a corto plazo ha alcanzado el limite "
                       "de compensacion. La ECU no puede corregir la mezcla.",
            probable_causes=[
                "Fuga de vacio severa",
                "Inyector con fuga o bloqueado",
                "Presion de combustible muy fuera de rango",
                "Sensor O2 defectuoso dando senal incorrecta",
            ],
            corrective_actions=[
                "Verificar presion de combustible inmediatamente",
                "Buscar fugas de vacio con maquina de humo",
                "Verificar inyectores",
                "Comprobar sensores O2",
            ],
            prediction="Conduccion deficiente, alto consumo, posible danio a catalizador.",
            related_dtcs=["P0170", "P0173"],
            confidence_base=0.84, min_sensors_required=["short_fuel_trim_1"],
        ))

        self._add(DiagnosticRule(
            rule_id="AFUEL-009",
            name="Filtro de particulas diesel (DPF) obstruido",
            system=VehicleSystem.ESCAPE,
            severity=Severity.GRAVE,
            description="Filtro de particulas diesel necesita regeneracion o reemplazo",
            condition=lambda d: _dtc_any(d, ["P2002", "P2003", "P244A", "P244B"]),
            diagnosis="El filtro de particulas diesel (DPF) esta obstruido. "
                       "El motor puede entrar en modo de emergencia.",
            probable_causes=[
                "Conduccion urbana excesiva sin regeneracion",
                "Sensor de presion diferencial del DPF defectuoso",
                "Inyector de regeneracion del DPF obstruido",
                "DPF al final de su vida util",
            ],
            corrective_actions=[
                "Intentar regeneracion forzada con escaner",
                "Conducir a velocidad de carretera por 30 minutos",
                "Verificar sensor de presion diferencial",
                "Si no regenera, reemplazar DPF",
            ],
            prediction="Modo limp activado. Perdida severa de potencia. "
                       "El vehiculo puede detenerse.",
            related_dtcs=["P2002", "P2003", "P244A", "P244B"],
            confidence_base=0.88, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AFUEL-010",
            name="Sensor de calidad de combustible",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.MODERADO,
            description="Calidad de combustible detectada como deficiente",
            condition=lambda d: _dtc_any(d, ["P0180", "P0181", "P0182", "P0183"]),
            diagnosis="El sensor de composicion de combustible detecta calidad anormal. "
                       "Posible combustible contaminado o mezcla incorrecta.",
            probable_causes=[
                "Combustible contaminado con agua",
                "Mezcla incorrecta de gasolina/diesel",
                "Sensor de composicion defectuoso",
            ],
            corrective_actions=[
                "Drenar y reemplazar combustible si contaminado",
                "Verificar sensor de composicion de combustible",
                "Usar combustible de estacion confiable",
            ],
            prediction="Rendimiento reducido, posible danio a inyectores y bomba.",
            related_dtcs=["P0180", "P0181", "P0182", "P0183"],
            confidence_base=0.80, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AFUEL-011",
            name="Regulador de presion de combustible - vacio",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.MODERADO,
            description="Regulador de presion no responde a cambios de vacio",
            condition=lambda d: (
                _has_sensor(d, "fuel_pressure")
                and _has_sensor(d, "intake_manifold_pressure")
                and abs(_sensor(d, "fuel_pressure", 45) - 45) < 2
                and _sensor(d, "intake_manifold_pressure", 90) < 50
            ),
            diagnosis="La presion de combustible no varia con el vacio del multiple. "
                       "El regulador de presion puede estar atascado.",
            probable_causes=[
                "Regulador de presion defectuoso",
                "Manguera de vacio del regulador desconectada",
                "Diafragma del regulador roto",
            ],
            corrective_actions=[
                "Verificar manguera de vacio del regulador",
                "Medir presion con y sin vacio aplicado",
                "Reemplazar regulador si no varia con vacio",
            ],
            prediction="Mezcla ligeramente incorrecta en diferentes cargas del motor.",
            related_dtcs=[],
            confidence_base=0.75, min_sensors_required=["fuel_pressure", "intake_manifold_pressure"],
        ))

    # ==================================================================
    # REGLAS ADICIONALES: ENCENDIDO (AIGN-xxx)
    # ==================================================================

    def _load_additional_ignition_rules(self) -> None:

        # Bobinas individuales P0351-P0358
        for coil in range(1, 9):
            dtc = f"P035{coil}"
            self._add(DiagnosticRule(
                rule_id=f"AIGN-{coil:03d}",
                name=f"Bobina de encendido {coil}",
                system=VehicleSystem.ENCENDIDO,
                severity=Severity.GRAVE,
                description=f"Circuito de la bobina de encendido {coil}",
                condition=(lambda d, _dtc=dtc: _dtc_present(d, _dtc)),
                diagnosis=f"La bobina de encendido del cilindro {coil} tiene un problema "
                           f"de circuito. El cilindro tendra falla de encendido.",
                probable_causes=[
                    f"Bobina de encendido {coil} defectuosa",
                    f"Conector de la bobina {coil} danado",
                    "Driver de bobina en la ECU danado",
                ],
                corrective_actions=[
                    f"Medir resistencia primaria y secundaria de bobina {coil}",
                    f"Intercambiar bobina {coil} con otra para confirmar",
                    "Verificar conector y cableado",
                    f"Reemplazar bobina {coil} si defectuosa",
                ],
                prediction=f"Falla permanente en cilindro {coil}. Danio al catalizador.",
                related_dtcs=[dtc],
                chain_rules=[f"MIS-{100 + coil:03d}"],
                confidence_base=0.88, min_sensors_required=[],
            ))

        self._add(DiagnosticRule(
            rule_id="AIGN-010",
            name="Sincronizacion CKP/CMP desalineada",
            system=VehicleSystem.ENCENDIDO,
            severity=Severity.GRAVE,
            description="Correlacion incorrecta entre sensores CKP y CMP",
            condition=lambda d: _dtc_any(d, ["P0016", "P0017", "P0018", "P0019"]),
            diagnosis="La sincronizacion entre el ciguenal y el arbol de levas esta "
                       "desalineada. Posible problema de distribucion.",
            probable_causes=[
                "Cadena/correa de distribucion saltada un diente",
                "Tensor de cadena/correa defectuoso",
                "Engranaje de distribucion desgastado",
                "Sensor CKP o CMP defectuoso",
            ],
            corrective_actions=[
                "Verificar marcas de distribucion",
                "Inspeccionar tensor de cadena/correa",
                "Comparar senales CKP y CMP con osciloscopio",
                "Reemplazar cadena/correa y tensores si necesario",
            ],
            prediction="Riesgo ALTO de salto de distribucion completo. "
                       "Motor de interferencia: danio catastrofico posible.",
            related_dtcs=["P0016", "P0017", "P0018", "P0019"],
            chain_rules=["VVT-003"],
            confidence_base=0.88, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AIGN-011",
            name="Sistema de encendido secundario",
            system=VehicleSystem.ENCENDIDO,
            severity=Severity.MODERADO,
            description="Falla en el sistema de encendido secundario",
            condition=lambda d: (
                _dtc_present(d, "P0300")
                and _sensor(d, "rpm", 800) > 600
                and not _dtc_any(d, ["P0351", "P0352", "P0353", "P0354",
                                      "P0355", "P0356", "P0357", "P0358"])
            ),
            diagnosis="Falla de encendido aleatoria sin codigos de bobina. "
                       "Posible problema en bujias o cables de alta tension.",
            probable_causes=[
                "Bujias desgastadas o con gap incorrecto",
                "Cables de bujia con alta resistencia (si aplica)",
                "Humedad en el sistema de encendido",
                "Tapa de distribuidor desgastada (si aplica)",
            ],
            corrective_actions=[
                "Inspeccionar y reemplazar bujias",
                "Verificar cables de alta tension (resistencia)",
                "Inspeccionar tapa de distribuidor (si aplica)",
                "Verificar gap de bujias con galga",
            ],
            prediction="Fallas intermitentes que empeoaran. Mayor consumo.",
            related_dtcs=["P0300"],
            confidence_base=0.78, min_sensors_required=["rpm"],
        ))

    # ==================================================================
    # REGLAS ADICIONALES: TRANSMISION (ATRANS-xxx)
    # ==================================================================

    def _load_additional_transmission_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="ATRANS-001",
            name="Solenoide de cambio C",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.MODERADO,
            description="Problema con solenoide de cambio C",
            condition=lambda d: _dtc_any(d, ["P0760", "P0761", "P0762", "P0763", "P0764"]),
            diagnosis="El solenoide de cambio C de la transmision tiene una falla.",
            probable_causes=["Solenoide C defectuoso", "Cableado danado", "Fluido contaminado"],
            corrective_actions=["Verificar solenoide C", "Cambiar fluido", "Reemplazar solenoide"],
            prediction="Cambios erraticos entre 3ra y 4ta marcha.",
            related_dtcs=["P0760", "P0761", "P0762", "P0763"],
            confidence_base=0.85, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ATRANS-002",
            name="Solenoide de cambio D",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.MODERADO,
            description="Problema con solenoide de cambio D",
            condition=lambda d: _dtc_any(d, ["P0765", "P0766", "P0767", "P0768", "P0769"]),
            diagnosis="El solenoide de cambio D de la transmision tiene una falla.",
            probable_causes=["Solenoide D defectuoso", "Cableado danado", "Fluido contaminado"],
            corrective_actions=["Verificar solenoide D", "Cambiar fluido", "Reemplazar solenoide"],
            prediction="Cambios erraticos en 4ta/5ta marcha. Posible modo de emergencia.",
            related_dtcs=["P0765", "P0766", "P0767", "P0768"],
            confidence_base=0.85, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ATRANS-003",
            name="Solenoide de cambio E",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.MODERADO,
            description="Problema con solenoide de cambio E",
            condition=lambda d: _dtc_any(d, ["P0770", "P0771", "P0772", "P0773", "P0774"]),
            diagnosis="El solenoide de cambio E de la transmision tiene una falla.",
            probable_causes=["Solenoide E defectuoso", "Cableado danado"],
            corrective_actions=["Verificar solenoide E", "Reemplazar solenoide"],
            prediction="Perdida de overdrive o 6ta marcha.",
            related_dtcs=["P0770", "P0771", "P0772", "P0773"],
            confidence_base=0.85, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ATRANS-004",
            name="Solenoide de control de presion",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.GRAVE,
            description="Problema con solenoide de control de presion de linea",
            condition=lambda d: _dtc_any(d, ["P0745", "P0746", "P0747", "P0748", "P0749"]),
            diagnosis="El solenoide de control de presion de linea no funciona correctamente. "
                       "La transmision puede patinar o hacer cambios bruscos.",
            probable_causes=[
                "Solenoide de presion defectuoso",
                "Cuerpo de valvulas danado",
                "Fluido de transmision degradado",
            ],
            corrective_actions=[
                "Verificar solenoide de presion de linea",
                "Medir presion de linea de transmision",
                "Cambiar fluido de transmision",
            ],
            prediction="Cambios muy bruscos. Desgaste acelerado de embragues.",
            related_dtcs=["P0745", "P0746", "P0747", "P0748"],
            confidence_base=0.86, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ATRANS-005",
            name="Sensor de velocidad de salida de transmision",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.MODERADO,
            description="Problema con sensor de velocidad de salida",
            condition=lambda d: _dtc_any(d, ["P0720", "P0721", "P0722", "P0723"]),
            diagnosis="El sensor de velocidad de salida de la transmision tiene una falla.",
            probable_causes=["Sensor defectuoso", "Cableado danado", "Gap incorrecto"],
            corrective_actions=["Verificar senal del sensor", "Inspeccionar cableado", "Reemplazar sensor"],
            prediction="Velocimetro erratico, cambios incorrectos.",
            related_dtcs=["P0720", "P0721", "P0722", "P0723"],
            confidence_base=0.85, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ATRANS-006",
            name="Codigo general de transmision",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.MODERADO,
            description="Codigo de transmision generico detectado",
            condition=lambda d: _dtc_present(d, "P0700"),
            diagnosis="La ECU del motor ha recibido un codigo de falla del modulo de "
                       "transmision (TCM). Se requiere leer codigos de transmision.",
            probable_causes=[
                "Falla interna de transmision",
                "Problema de comunicacion ECU-TCM",
                "Sensor de transmision defectuoso",
            ],
            corrective_actions=[
                "Leer codigos DTC del modulo TCM directamente",
                "Verificar comunicacion con TCM",
                "Diagnosticar codigos especificos de transmision",
            ],
            prediction="La transmision puede tener un problema que requiere diagnostico profundo.",
            related_dtcs=["P0700"],
            confidence_base=0.80, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ATRANS-007",
            name="Relacion de engranaje 1ra marcha",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.GRAVE,
            description="Relacion incorrecta en 1ra marcha",
            condition=lambda d: _dtc_present(d, "P0731"),
            diagnosis="La relacion de engranaje de primera marcha es incorrecta. "
                       "La transmision desliza en primera.",
            probable_causes=["Embrague de 1ra desgastado", "Banda de 1ra desgastada", "Presion de linea baja"],
            corrective_actions=["Verificar presion de linea", "Puede requerir reconstruccion"],
            prediction="Deslizamiento cada vez peor. Falla total de 1ra marcha inminente.",
            related_dtcs=["P0731"],
            confidence_base=0.86, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ATRANS-008",
            name="Relacion de engranaje 2da marcha",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.GRAVE,
            description="Relacion incorrecta en 2da marcha",
            condition=lambda d: _dtc_present(d, "P0732"),
            diagnosis="La relacion de engranaje de segunda marcha es incorrecta.",
            probable_causes=["Embrague de 2da desgastado", "Solenoide de cambio defectuoso"],
            corrective_actions=["Verificar solenoide de cambio A", "Verificar presion de linea"],
            prediction="Deslizamiento en 2da. Puede perder la marcha completamente.",
            related_dtcs=["P0732"],
            confidence_base=0.86, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ATRANS-009",
            name="Relacion de engranaje 3ra marcha",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.GRAVE,
            description="Relacion incorrecta en 3ra marcha",
            condition=lambda d: _dtc_present(d, "P0733"),
            diagnosis="La relacion de engranaje de tercera marcha es incorrecta.",
            probable_causes=["Embrague de 3ra desgastado", "Solenoide de cambio defectuoso"],
            corrective_actions=["Verificar solenoides de cambio", "Verificar presion"],
            prediction="Deslizamiento en 3ra marcha.",
            related_dtcs=["P0733"],
            confidence_base=0.86, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ATRANS-010",
            name="Relacion de engranaje 4ta marcha",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.GRAVE,
            description="Relacion incorrecta en 4ta marcha",
            condition=lambda d: _dtc_present(d, "P0734"),
            diagnosis="La relacion de engranaje de cuarta marcha es incorrecta.",
            probable_causes=["Embrague de 4ta desgastado", "Solenoide defectuoso"],
            corrective_actions=["Diagnosticar presion y solenoides"],
            prediction="Deslizamiento en 4ta. Mayor consumo en carretera.",
            related_dtcs=["P0734"],
            confidence_base=0.86, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ATRANS-011",
            name="Relacion de engranaje 5ta marcha",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.GRAVE,
            description="Relacion incorrecta en 5ta marcha",
            condition=lambda d: _dtc_present(d, "P0735"),
            diagnosis="La relacion de engranaje de quinta marcha es incorrecta.",
            probable_causes=["Embrague de 5ta desgastado", "Solenoide defectuoso"],
            corrective_actions=["Diagnosticar presion y solenoides"],
            prediction="Perdida de overdrive. RPM elevadas en carretera.",
            related_dtcs=["P0735"],
            confidence_base=0.86, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ATRANS-012",
            name="Relacion de engranaje reversa",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.GRAVE,
            description="Relacion incorrecta en reversa",
            condition=lambda d: _dtc_present(d, "P0736"),
            diagnosis="La relacion de reversa es incorrecta. La transmision puede no "
                       "engranar reversa o deslizar.",
            probable_causes=["Embrague/banda de reversa desgastado", "Presion insuficiente"],
            corrective_actions=["Verificar presion de linea en reversa", "Puede requerir reconstruccion"],
            prediction="Perdida total de reversa inminente.",
            related_dtcs=["P0736"],
            confidence_base=0.86, min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS ADICIONALES: EMISION (AEMIS-xxx)
    # ==================================================================

    def _load_additional_emission_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="AEMIS-001",
            name="Sistema de inyeccion de aire secundario",
            system=VehicleSystem.EMISION,
            severity=Severity.MODERADO,
            description="Problema con sistema de inyeccion de aire secundario",
            condition=lambda d: _dtc_any(d, ["P0410", "P0411", "P0412", "P0413", "P0414", "P0418", "P0419"]),
            diagnosis="El sistema de inyeccion de aire secundario (AIR) no funciona. "
                       "Este sistema reduce emisiones durante el arranque en frio.",
            probable_causes=[
                "Bomba de aire secundario defectuosa",
                "Valvula de control de aire secundario atascada",
                "Valvula check de aire secundario defectuosa",
                "Rele de la bomba de aire defectuoso",
            ],
            corrective_actions=[
                "Verificar funcionamiento de la bomba de aire",
                "Inspeccionar valvula de control",
                "Verificar rele y fusible",
                "Reemplazar componentes defectuosos",
            ],
            prediction="Emisiones elevadas en arranque en frio. Fallo en inspeccion.",
            related_dtcs=["P0410", "P0411", "P0412", "P0413"],
            confidence_base=0.84, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AEMIS-002",
            name="Sensor NOx",
            system=VehicleSystem.EMISION,
            severity=Severity.MODERADO,
            description="Problema con sensor de oxidos de nitrogeno",
            condition=lambda d: _dtc_any(d, ["P229F", "P2200", "P2201"]),
            diagnosis="El sensor de NOx reporta valores fuera de rango. "
                       "No se pueden monitorear las emisiones de NOx.",
            probable_causes=[
                "Sensor NOx defectuoso",
                "Cableado del sensor danado",
                "Modulo de control del sensor defectuoso",
            ],
            corrective_actions=[
                "Verificar sensor NOx",
                "Inspeccionar cableado",
                "Reemplazar sensor si defectuoso",
            ],
            prediction="Emisiones de NOx no monitoreadas. Posible aumento de contaminacion.",
            related_dtcs=["P229F", "P2200", "P2201"],
            confidence_base=0.82, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AEMIS-003",
            name="Sistema SCR - AdBlue/DEF",
            system=VehicleSystem.EMISION,
            severity=Severity.GRAVE,
            description="Problema con sistema de reduccion catalitica selectiva",
            condition=lambda d: _dtc_any(d, ["P20EE", "P20E8", "P207F", "P2BAD"]),
            diagnosis="El sistema SCR (AdBlue/DEF) tiene una falla. El vehiculo puede "
                       "entrar en modo de potencia reducida.",
            probable_causes=[
                "Nivel bajo de AdBlue/DEF",
                "Calidad del AdBlue/DEF deficiente",
                "Inyector de AdBlue obstruido",
                "Bomba de AdBlue defectuosa",
                "Sensor de nivel de AdBlue defectuoso",
            ],
            corrective_actions=[
                "Verificar nivel de AdBlue/DEF",
                "Reemplazar AdBlue si calidad es dudosa",
                "Verificar inyector de AdBlue",
                "Inspeccionar bomba del sistema SCR",
            ],
            prediction="Motor en modo limp si no se corrige. "
                       "Puede impedir el arranque tras cierto kilometraje.",
            related_dtcs=["P20EE", "P20E8", "P207F"],
            confidence_base=0.86, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AEMIS-004",
            name="Catalizador por debajo de temperatura",
            system=VehicleSystem.CATALIZADOR,
            severity=Severity.LEVE,
            description="El catalizador no alcanza temperatura de operacion",
            condition=lambda d: _dtc_present(d, "P0420") and (
                _has_sensor(d, "catalyst_temp")
                and _sensor(d, "catalyst_temp", 400) < 250
                and _sensor(d, "run_time", 0) > 300
            ),
            diagnosis="El catalizador no alcanza su temperatura minima de operacion "
                       "despues de 5 minutos. No puede convertir gases eficientemente.",
            probable_causes=[
                "Termostato atascado abierto (motor frio)",
                "Fuga de escape antes del catalizador",
                "Catalizador con sustrato danado",
            ],
            corrective_actions=[
                "Verificar temperatura del motor",
                "Inspeccionar escape por fugas",
                "Verificar termostato",
            ],
            prediction="Emisiones elevadas constantes. Fallo en inspeccion.",
            related_dtcs=["P0420"],
            chain_rules=["COOL-003"],
            confidence_base=0.76, min_sensors_required=["catalyst_temp", "run_time"],
        ))

        self._add(DiagnosticRule(
            rule_id="AEMIS-005",
            name="Valvula de control de flujo EVAP",
            system=VehicleSystem.EVAP,
            severity=Severity.LEVE,
            description="Problema con valvula de control de flujo EVAP",
            condition=lambda d: _dtc_present(d, "P0440"),
            diagnosis="La valvula de control de flujo del sistema EVAP tiene una falla general.",
            probable_causes=["Valvula EVAP defectuosa", "Fuga en el sistema EVAP", "Tapa de tanque suelta"],
            corrective_actions=["Verificar tapa del tanque", "Inspeccionar sistema EVAP completo"],
            prediction="Posible fallo en inspeccion de emisiones.",
            related_dtcs=["P0440"],
            confidence_base=0.82, min_sensors_required=[],
        ))

        # Sensores O2 adicionales
        self._add(DiagnosticRule(
            rule_id="AEMIS-006",
            name="Sensor O2 B1S1 - voltaje alto permanente",
            system=VehicleSystem.SENSOR_O2,
            severity=Severity.MODERADO,
            description="Sensor O2 banco 1 sensor 1 con voltaje alto permanente",
            condition=lambda d: _dtc_present(d, "P0132"),
            diagnosis="El sensor O2 B1S1 muestra voltaje alto permanente (>0.9V). "
                       "La ECU interpreta mezcla rica constante.",
            probable_causes=["Sensor O2 en cortocircuito", "Mezcla realmente rica", "Cableado en corto a voltaje"],
            corrective_actions=["Descartar mezcla rica real", "Verificar cableado", "Reemplazar sensor O2"],
            prediction="Compensacion pobre excesiva. Ralenti irregular.",
            related_dtcs=["P0132"],
            confidence_base=0.85, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AEMIS-007",
            name="Sensor O2 B1S1 - voltaje bajo permanente",
            system=VehicleSystem.SENSOR_O2,
            severity=Severity.MODERADO,
            description="Sensor O2 banco 1 sensor 1 con voltaje bajo permanente",
            condition=lambda d: _dtc_present(d, "P0131"),
            diagnosis="El sensor O2 B1S1 muestra voltaje bajo permanente (<0.1V). "
                       "La ECU interpreta mezcla pobre constante.",
            probable_causes=["Sensor O2 defectuoso", "Fuga de escape", "Cableado en corto a tierra"],
            corrective_actions=["Verificar fuga de escape", "Verificar cableado", "Reemplazar sensor"],
            prediction="Compensacion rica excesiva. Mayor consumo.",
            related_dtcs=["P0131"],
            confidence_base=0.85, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AEMIS-008",
            name="Sensor O2 B2S1 - voltaje alto permanente",
            system=VehicleSystem.SENSOR_O2,
            severity=Severity.MODERADO,
            description="Sensor O2 banco 2 sensor 1 con voltaje alto permanente",
            condition=lambda d: _dtc_present(d, "P0152"),
            diagnosis="El sensor O2 B2S1 muestra voltaje alto permanente.",
            probable_causes=["Sensor O2 en cortocircuito", "Mezcla realmente rica banco 2"],
            corrective_actions=["Descartar mezcla rica real", "Reemplazar sensor O2 B2S1"],
            prediction="Compensacion pobre en banco 2.",
            related_dtcs=["P0152"],
            confidence_base=0.85, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AEMIS-009",
            name="Sensor O2 B2S1 - voltaje bajo permanente",
            system=VehicleSystem.SENSOR_O2,
            severity=Severity.MODERADO,
            description="Sensor O2 banco 2 sensor 1 con voltaje bajo permanente",
            condition=lambda d: _dtc_present(d, "P0151"),
            diagnosis="El sensor O2 B2S1 muestra voltaje bajo permanente.",
            probable_causes=["Sensor O2 defectuoso", "Fuga de escape banco 2"],
            corrective_actions=["Verificar fuga de escape", "Reemplazar sensor O2 B2S1"],
            prediction="Compensacion rica en banco 2. Mayor consumo.",
            related_dtcs=["P0151"],
            confidence_base=0.85, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AEMIS-010",
            name="Sensor O2 B1S2 - respuesta lenta",
            system=VehicleSystem.SENSOR_O2,
            severity=Severity.LEVE,
            description="Sensor O2 trasero banco 1 con respuesta lenta",
            condition=lambda d: _dtc_present(d, "P0139"),
            diagnosis="El sensor O2 trasero B1S2 tiene respuesta lenta. Afecta monitoreo del catalizador.",
            probable_causes=["Sensor O2 envejecido", "Contaminacion del sensor"],
            corrective_actions=["Reemplazar sensor O2 B1S2"],
            prediction="Falso codigo P0420 posible. Monitoreo de catalizador impreciso.",
            related_dtcs=["P0139"],
            confidence_base=0.83, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AEMIS-011",
            name="Sensor O2 B2S2 - respuesta lenta",
            system=VehicleSystem.SENSOR_O2,
            severity=Severity.LEVE,
            description="Sensor O2 trasero banco 2 con respuesta lenta",
            condition=lambda d: _dtc_present(d, "P0159"),
            diagnosis="El sensor O2 trasero B2S2 tiene respuesta lenta.",
            probable_causes=["Sensor O2 envejecido", "Contaminacion del sensor"],
            corrective_actions=["Reemplazar sensor O2 B2S2"],
            prediction="Falso codigo P0430 posible.",
            related_dtcs=["P0159"],
            confidence_base=0.83, min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS ADICIONALES: MOTOR (AMECH-xxx)
    # ==================================================================

    def _load_additional_engine_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="AMECH-001",
            name="RPM excesivas en ralenti",
            system=VehicleSystem.MOTOR,
            severity=Severity.MODERADO,
            description="RPM de ralenti anormalmente altas",
            condition=lambda d: (
                _sensor(d, "throttle_pos", 0) < 3
                and _sensor(d, "rpm", 800) > 1500
                and _sensor(d, "coolant_temp", 0) > 70
            ),
            diagnosis="Las RPM de ralenti superan las 1500 con el motor caliente. "
                       "Posible fuga de vacio o problema con el control de ralenti.",
            probable_causes=[
                "Fuga de vacio grande",
                "Valvula IAC atascada abierta",
                "Cuerpo de aceleracion sucio con mariposa no cerrando",
                "Sensor TPS desajustado",
            ],
            corrective_actions=[
                "Buscar fugas de vacio",
                "Limpiar cuerpo de aceleracion",
                "Verificar valvula IAC",
                "Verificar sensor TPS",
            ],
            prediction="Desgaste prematuro de embrague (manual) o frenos. Mayor consumo.",
            related_dtcs=["P0507"],
            confidence_base=0.82, min_sensors_required=["rpm", "throttle_pos", "coolant_temp"],
        ))

        self._add(DiagnosticRule(
            rule_id="AMECH-002",
            name="Carga del motor excesiva en ralenti",
            system=VehicleSystem.MOTOR,
            severity=Severity.MODERADO,
            description="Carga del motor alta en ralenti",
            condition=lambda d: (
                _sensor(d, "engine_load", 0) > 40
                and _sensor(d, "throttle_pos", 0) < 3
                and _sensor(d, "rpm", 800) < 1000
            ),
            diagnosis="La carga del motor en ralenti es anormalmente alta. "
                       "Algo esta frenando el motor o hay un accesorio con alta demanda.",
            probable_causes=[
                "Compresor de AC trabado",
                "Alternador con carga excesiva",
                "Freno de estacionamiento parcialmente aplicado",
                "Problema mecanico interno (alta friccion)",
            ],
            corrective_actions=[
                "Verificar si el AC esta encendido",
                "Verificar amperaje del alternador",
                "Verificar freno de estacionamiento",
                "Inspeccionar accesorios movidos por correa",
            ],
            prediction="Mayor consumo de combustible en ralenti. Posible estres en motor.",
            related_dtcs=[],
            confidence_base=0.75, min_sensors_required=["engine_load", "throttle_pos", "rpm"],
        ))

        self._add(DiagnosticRule(
            rule_id="AMECH-003",
            name="Vacio del motor bajo",
            system=VehicleSystem.MOTOR,
            severity=Severity.MODERADO,
            description="Presion de vacio del motor baja en ralenti",
            condition=lambda d: (
                _has_sensor(d, "intake_manifold_pressure")
                and _sensor(d, "intake_manifold_pressure", 30) > 65
                and _sensor(d, "throttle_pos", 0) < 3
                and _sensor(d, "rpm", 800) < 1000
            ),
            diagnosis="La presion del multiple de admision en ralenti es alta (vacio bajo). "
                       "Indica fuga de vacio o problema mecanico interno.",
            probable_causes=[
                "Fuga de vacio en manguera o junta",
                "Valvula EGR atascada abierta",
                "Desgaste de anillos de piston (baja compresion)",
                "Valvulas con sellado deficiente",
            ],
            corrective_actions=[
                "Inspeccionar mangueras de vacio",
                "Verificar valvula EGR",
                "Realizar prueba de compresion si otros items estan bien",
            ],
            prediction="Si es mecanico: desgaste progresivo del motor.",
            related_dtcs=[],
            confidence_base=0.78, min_sensors_required=["intake_manifold_pressure", "throttle_pos", "rpm"],
        ))

        self._add(DiagnosticRule(
            rule_id="AMECH-004",
            name="Consumo excesivo de combustible",
            system=VehicleSystem.MOTOR,
            severity=Severity.MODERADO,
            description="Indicadores de consumo excesivo de combustible",
            condition=lambda d: (
                _sensor(d, "long_fuel_trim_1", 0) < -12
                and _sensor(d, "engine_load", 0) < 30
                and _sensor(d, "vehicle_speed", 0) > 40
            ),
            diagnosis="Los ajustes de combustible negativos altos en conduccion normal "
                       "indican que el motor consume mas combustible del necesario.",
            probable_causes=[
                "Inyectores con fuga",
                "Regulador de presion defectuoso (presion alta)",
                "Sensor MAF contaminado (lectura alta)",
                "Sensor ECT dando senal de frio constante",
            ],
            corrective_actions=[
                "Verificar presion de combustible",
                "Limpiar sensor MAF",
                "Verificar sensor ECT",
                "Inspeccionar inyectores por fugas",
            ],
            prediction="Contaminacion del aceite con combustible. Catalizador en riesgo.",
            related_dtcs=["P0172", "P0175"],
            confidence_base=0.78, min_sensors_required=["long_fuel_trim_1", "engine_load", "vehicle_speed"],
        ))

        self._add(DiagnosticRule(
            rule_id="AMECH-005",
            name="Sensor de posicion de valvula de admision variable",
            system=VehicleSystem.VVT,
            severity=Severity.MODERADO,
            description="Problema con actuador de admision variable",
            condition=lambda d: _dtc_any(d, ["P0076", "P0077", "P0078", "P0079"]),
            diagnosis="El actuador de la valvula de admision variable tiene un problema de circuito.",
            probable_causes=["Solenoide de control defectuoso", "Cableado danado", "Motor de vacio defectuoso"],
            corrective_actions=["Verificar solenoide de control", "Inspeccionar cableado"],
            prediction="Perdida de potencia a ciertas RPM. Consumo elevado.",
            related_dtcs=["P0076", "P0077", "P0078", "P0079"],
            confidence_base=0.82, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AMECH-006",
            name="Sistema de admision de aire con restriccion",
            system=VehicleSystem.MOTOR,
            severity=Severity.LEVE,
            description="Posible restriccion en la admision de aire",
            condition=lambda d: (
                _has_sensor(d, "intake_manifold_pressure")
                and _sensor(d, "intake_manifold_pressure", 90) < 20
                and _sensor(d, "rpm", 0) > 2000
                and _sensor(d, "throttle_pos", 0) > 50
            ),
            diagnosis="Vacio excesivo a RPM altas con acelerador abierto sugiere "
                       "restriccion en el sistema de admision de aire.",
            probable_causes=[
                "Filtro de aire completamente obstruido",
                "Conducto de aire colapsado",
                "Cuerpo de aceleracion parcialmente bloqueado",
            ],
            corrective_actions=[
                "Reemplazar filtro de aire",
                "Inspeccionar conducto de aire",
                "Limpiar cuerpo de aceleracion",
            ],
            prediction="Perdida de potencia. Mayor consumo. Posible danio al turbo (si aplica).",
            related_dtcs=[],
            confidence_base=0.75, min_sensors_required=["intake_manifold_pressure", "rpm", "throttle_pos"],
        ))

    # ==================================================================
    # REGLAS ADICIONALES: ELECTRICO (AELEC-xxx)
    # ==================================================================

    def _load_additional_electrical_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="AELEC-001",
            name="Circuito de rele principal del motor",
            system=VehicleSystem.ELECTRICO,
            severity=Severity.GRAVE,
            description="Problema con el rele principal de alimentacion del motor",
            condition=lambda d: _dtc_any(d, ["P0685", "P0686", "P0687", "P0688"]),
            diagnosis="El circuito del rele principal de alimentacion del motor tiene una falla. "
                       "Puede causar apagado repentino del motor.",
            probable_causes=["Rele principal defectuoso", "Cableado del rele danado", "Fusible principal danado"],
            corrective_actions=["Verificar rele principal", "Inspeccionar fusibles", "Verificar cableado"],
            prediction="Motor puede apagarse sin aviso. Riesgo de quedar varado.",
            related_dtcs=["P0685", "P0686", "P0687", "P0688"],
            confidence_base=0.87, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AELEC-002",
            name="Motor de arranque - circuito",
            system=VehicleSystem.ELECTRICO,
            severity=Severity.MODERADO,
            description="Problema con circuito del motor de arranque",
            condition=lambda d: _dtc_any(d, ["P0615", "P0616", "P0617"]),
            diagnosis="El circuito de control del motor de arranque tiene una falla.",
            probable_causes=["Rele de arranque defectuoso", "Solenoide de arranque danado", "Cableado defectuoso"],
            corrective_actions=["Verificar rele de arranque", "Inspeccionar solenoide", "Verificar cableado"],
            prediction="Dificultad para arrancar o no arranca.",
            related_dtcs=["P0615", "P0616", "P0617"],
            confidence_base=0.85, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AELEC-003",
            name="Generador/alternador - campo",
            system=VehicleSystem.ELECTRICO,
            severity=Severity.MODERADO,
            description="Problema con el circuito de campo del alternador",
            condition=lambda d: _dtc_any(d, ["P0620", "P0621", "P0622"]),
            diagnosis="El circuito de excitacion del alternador tiene una falla. "
                       "La carga de la bateria puede ser insuficiente.",
            probable_causes=["Regulador del alternador defectuoso", "Escobillas desgastadas", "Cableado de campo danado"],
            corrective_actions=["Verificar voltaje de salida del alternador", "Inspeccionar regulador", "Reemplazar alternador"],
            prediction="Bateria no se carga completamente. Descarga progresiva.",
            related_dtcs=["P0620", "P0621", "P0622"],
            confidence_base=0.85, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AELEC-004",
            name="Circuito de bomba de combustible",
            system=VehicleSystem.ELECTRICO,
            severity=Severity.GRAVE,
            description="Problema con circuito de la bomba de combustible",
            condition=lambda d: _dtc_any(d, ["P0230", "P0231", "P0232", "P0233"]),
            diagnosis="El circuito de la bomba de combustible tiene una falla electrica.",
            probable_causes=[
                "Rele de bomba de combustible defectuoso",
                "Fusible de bomba fundido",
                "Cableado a la bomba danado",
                "Bomba de combustible en cortocircuito",
            ],
            corrective_actions=[
                "Verificar fusible de bomba de combustible",
                "Verificar rele de bomba",
                "Medir amperaje de la bomba",
                "Inspeccionar cableado",
            ],
            prediction="Motor puede no arrancar o detenerse repentinamente.",
            related_dtcs=["P0230", "P0231", "P0232", "P0233"],
            confidence_base=0.88, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AELEC-005",
            name="Ventilador de refrigeracion 2",
            system=VehicleSystem.ELECTRICO,
            severity=Severity.MODERADO,
            description="Problema con segundo ventilador de refrigeracion",
            condition=lambda d: _dtc_any(d, ["P0481", "P0482", "P0483"]),
            diagnosis="El segundo ventilador de refrigeracion (alta velocidad o auxiliar) tiene una falla.",
            probable_causes=["Motor del ventilador 2 defectuoso", "Rele defectuoso", "Fusible fundido"],
            corrective_actions=["Verificar fusible y rele", "Probar motor del ventilador", "Reemplazar si defectuoso"],
            prediction="Refrigeracion insuficiente a alta carga o con AC encendido.",
            related_dtcs=["P0481", "P0482", "P0483"],
            confidence_base=0.84, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AELEC-006",
            name="Circuito de control de bujias incandescentes (diesel)",
            system=VehicleSystem.ELECTRICO,
            severity=Severity.MODERADO,
            description="Problema con sistema de bujias incandescentes",
            condition=lambda d: _dtc_any(d, ["P0380", "P0381", "P0382", "P0383",
                                              "P0670", "P0671", "P0672", "P0673", "P0674"]),
            diagnosis="El sistema de bujias incandescentes (precalentamiento diesel) tiene una falla.",
            probable_causes=[
                "Bujia incandescente quemada",
                "Rele de precalentamiento defectuoso",
                "Temporizador de precalentamiento danado",
                "Cableado del circuito danado",
            ],
            corrective_actions=[
                "Medir resistencia de cada bujia incandescente",
                "Verificar rele de precalentamiento",
                "Inspeccionar cableado",
                "Reemplazar bujias defectuosas",
            ],
            prediction="Arranque dificil en frio. Humo blanco en arranque. "
                       "Mayor desgaste del motor por arranque frio deficiente.",
            related_dtcs=["P0380", "P0670", "P0671", "P0672", "P0673", "P0674"],
            confidence_base=0.86, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="AELEC-007",
            name="Modulo de control del tren motriz (PCM) interno",
            system=VehicleSystem.ELECTRICO,
            severity=Severity.CRITICO,
            description="Falla interna del modulo de control del motor",
            condition=lambda d: _dtc_any(d, ["P0606", "P0607", "P0608", "P060A", "P060B", "P060C"]),
            diagnosis="El modulo de control del motor (PCM/ECU) reporta una falla interna. "
                       "Los calculos del motor pueden ser incorrectos.",
            probable_causes=[
                "PCM/ECU con falla electronica interna",
                "Software corrupto",
                "Alimentacion electrica inestable danando la memoria",
                "Dano por sobrevoltaje",
            ],
            corrective_actions=[
                "Intentar reprogramacion/actualizacion del software",
                "Verificar alimentacion y tierras del PCM",
                "Reemplazar PCM si la falla persiste",
                "Verificar que no haya sobrevoltaje del alternador",
            ],
            prediction="Comportamiento completamente erratico del motor. "
                       "Puede afectar todos los sistemas controlados.",
            related_dtcs=["P0606", "P0607", "P0608", "P060A", "P060B"],
            confidence_base=0.90, min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS ADICIONALES: CARROCERIA Y CONFORT (ABODY-xxx)
    # ==================================================================

    def _load_additional_body_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="ABODY-001",
            name="Circuito de claxon",
            system=VehicleSystem.CARROCERIA,
            severity=Severity.LEVE,
            description="Problema con circuito del claxon",
            condition=lambda d: _dtc_any(d, ["B1322", "B1323"]),
            diagnosis="El circuito del claxon (bocina) tiene una falla.",
            probable_causes=["Claxon defectuoso", "Rele del claxon danado", "Clock spring danado"],
            corrective_actions=["Verificar fusible y rele", "Probar claxon directamente", "Verificar clock spring"],
            prediction="Claxon inoperante. Problema de seguridad.",
            related_dtcs=["B1322", "B1323"],
            confidence_base=0.82, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ABODY-002",
            name="Sistema de inmovilizador",
            system=VehicleSystem.ELECTRICO,
            severity=Severity.GRAVE,
            description="Problema con sistema antirrobo/inmovilizador",
            condition=lambda d: _dtc_any(d, ["P1260", "P1693", "B2799"]),
            diagnosis="El sistema inmovilizador no reconoce la llave. "
                       "El motor puede no arrancar.",
            probable_causes=[
                "Llave sin chip transponder correcto",
                "Antena del inmovilizador defectuosa",
                "Modulo inmovilizador con falla",
                "Chip de llave danado",
            ],
            corrective_actions=[
                "Verificar con llave de repuesto",
                "Reprogramar llaves al inmovilizador",
                "Verificar antena de lectura de llave",
            ],
            prediction="El vehiculo puede quedar inmovilizado sin aviso.",
            related_dtcs=["P1260", "P1693", "B2799"],
            confidence_base=0.86, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ABODY-003",
            name="Sensor de lluvia/luz",
            system=VehicleSystem.CARROCERIA,
            severity=Severity.LEVE,
            description="Problema con sensor de lluvia o luz",
            condition=lambda d: _dtc_any(d, ["B1A43", "B1A44"]),
            diagnosis="El sensor de lluvia/luz automatico tiene una falla.",
            probable_causes=["Sensor defectuoso", "Parabrisas reemplazado sin recalibrar", "Cableado danado"],
            corrective_actions=["Recalibrar sensor", "Verificar cableado", "Reemplazar sensor"],
            prediction="Limpiaparabrisas/luces automaticas no funcionan.",
            related_dtcs=["B1A43", "B1A44"],
            confidence_base=0.78, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ABODY-004",
            name="Sistema de camaras/sensores de estacionamiento",
            system=VehicleSystem.CARROCERIA,
            severity=Severity.LEVE,
            description="Problema con sensores de estacionamiento o camara trasera",
            condition=lambda d: _dtc_any(d, ["B1612", "B1613", "C1A00"]),
            diagnosis="Los sensores de estacionamiento o la camara trasera tienen una falla.",
            probable_causes=["Sensor de estacionamiento danado", "Camara trasera defectuosa", "Cableado danado"],
            corrective_actions=["Verificar sensores individualmente", "Inspeccionar camara", "Verificar cableado"],
            prediction="Asistencia de estacionamiento no funcional.",
            related_dtcs=["B1612", "B1613"],
            confidence_base=0.78, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ABODY-005",
            name="Cinturon de seguridad - tensor",
            system=VehicleSystem.AIRBAG,
            severity=Severity.GRAVE,
            description="Problema con pretensor de cinturon de seguridad",
            condition=lambda d: _dtc_any(d, ["B0095", "B0096", "B0097", "B0098"]),
            diagnosis="El pretensor del cinturon de seguridad tiene una falla. "
                       "No se tensara en caso de accidente.",
            probable_causes=["Pretensor defectuoso", "Conector desconectado", "Cableado danado"],
            corrective_actions=["Inspeccionar conector bajo el asiento", "Verificar cableado", "Reemplazar pretensor"],
            prediction="Proteccion reducida en caso de accidente.",
            related_dtcs=["B0095", "B0096", "B0097", "B0098"],
            confidence_base=0.87, min_sensors_required=[],
        ))

    # ==================================================================
    # REGLAS ADICIONALES: REFRIGERACION (ACOOL-xxx)
    # ==================================================================

    def _load_additional_cooling_rules(self) -> None:

        self._add(DiagnosticRule(
            rule_id="ACOOL-001",
            name="Bomba de agua electrica",
            system=VehicleSystem.REFRIGERACION,
            severity=Severity.GRAVE,
            description="Problema con bomba de agua electrica",
            condition=lambda d: _dtc_any(d, ["P2181", "P2182", "P2183"]),
            diagnosis="La bomba de agua electrica no funciona correctamente. "
                       "El flujo de refrigerante puede ser insuficiente.",
            probable_causes=[
                "Bomba de agua electrica defectuosa",
                "Circuito de control de bomba danado",
                "Rele o fusible defectuoso",
            ],
            corrective_actions=[
                "Verificar fusible y rele de la bomba",
                "Medir amperaje de la bomba",
                "Verificar control de la ECU a la bomba",
                "Reemplazar bomba si defectuosa",
            ],
            prediction="Sobrecalentamiento posible sin aviso. Especialmente en "
                       "vehiculos BMW, Mercedes y otros con bomba electrica.",
            related_dtcs=["P2181", "P2182", "P2183"],
            chain_rules=["COOL-001"],
            confidence_base=0.87, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ACOOL-002",
            name="Sensor de nivel de refrigerante",
            system=VehicleSystem.REFRIGERACION,
            severity=Severity.MODERADO,
            description="Problema con sensor de nivel de refrigerante",
            condition=lambda d: _dtc_any(d, ["P2560", "P2561", "P2562", "P2563"]),
            diagnosis="El sensor de nivel del refrigerante reporta nivel bajo o falla de circuito.",
            probable_causes=[
                "Nivel de refrigerante realmente bajo",
                "Sensor de nivel defectuoso",
                "Conector del sensor corroido",
            ],
            corrective_actions=[
                "Verificar nivel de refrigerante fisicamente",
                "Inspeccionar sensor de nivel",
                "Si nivel esta bien, reemplazar sensor",
            ],
            prediction="Si el nivel es realmente bajo, fuga de refrigerante presente.",
            related_dtcs=["P2560", "P2561"],
            chain_rules=["COOL-006"],
            confidence_base=0.83, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ACOOL-003",
            name="Control del termostato electronico",
            system=VehicleSystem.REFRIGERACION,
            severity=Severity.MODERADO,
            description="Problema con termostato electronico controlado",
            condition=lambda d: _dtc_any(d, ["P0597", "P0598", "P0599"]),
            diagnosis="El termostato electronico tiene un problema de control. "
                       "No puede regular la temperatura del motor correctamente.",
            probable_causes=[
                "Termostato electronico defectuoso",
                "Calentador del termostato quemado",
                "Cableado de control danado",
            ],
            corrective_actions=[
                "Verificar resistencia del calentador del termostato",
                "Inspeccionar conector y cableado",
                "Reemplazar termostato electronico",
            ],
            prediction="Temperatura de motor inestable. Consumo elevado.",
            related_dtcs=["P0597", "P0598", "P0599"],
            confidence_base=0.84, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="ACOOL-004",
            name="Flujo de refrigerante insuficiente",
            system=VehicleSystem.REFRIGERACION,
            severity=Severity.GRAVE,
            description="Flujo de refrigerante por debajo del minimo requerido",
            condition=lambda d: (
                _has_sensor(d, "coolant_temp")
                and _sensor(d, "coolant_temp", 0) > 108
                and _sensor(d, "vehicle_speed", 0) > 60
            ),
            diagnosis="El motor se sobrecalienta incluso a velocidad de carretera, "
                       "lo que indica flujo de refrigerante insuficiente.",
            probable_causes=[
                "Bomba de agua con impulsor danado",
                "Radiador severamente obstruido internamente",
                "Burbuja de aire en el sistema de refrigeracion",
                "Manguera de refrigerante colapsada",
            ],
            corrective_actions=[
                "Verificar flujo de bomba de agua",
                "Purgar aire del sistema de refrigeracion",
                "Inspeccionar mangueras por colapso",
                "Realizar flush del radiador",
            ],
            prediction="Sobrecalentamiento incluso en carretera. Junta de culata en riesgo.",
            related_dtcs=["P0217"],
            chain_rules=["COOL-001"],
            confidence_base=0.85, min_sensors_required=["coolant_temp", "vehicle_speed"],
        ))

    # ==================================================================
    # REGLAS SUPLEMENTARIAS PARA ALCANZAR 200+ (SUPP-xxx)
    # ==================================================================

    def _load_supplementary_rules(self) -> None:

        # --- Inyectores adicionales (cilindros 7-8) ---
        self._add(DiagnosticRule(
            rule_id="SUPP-001",
            name="Inyector cilindro 7 - circuito",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.GRAVE,
            description="Circuito del inyector del cilindro 7",
            condition=lambda d: _dtc_present(d, "P0207"),
            diagnosis="El inyector del cilindro 7 tiene un problema de circuito.",
            probable_causes=["Inyector 7 defectuoso", "Cableado cortado"],
            corrective_actions=["Medir resistencia del inyector 7", "Reemplazar inyector"],
            prediction="Falla de encendido cilindro 7.",
            related_dtcs=["P0207"], chain_rules=["MIS-107"],
            confidence_base=0.87, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="SUPP-002",
            name="Inyector cilindro 8 - circuito",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.GRAVE,
            description="Circuito del inyector del cilindro 8",
            condition=lambda d: _dtc_present(d, "P0208"),
            diagnosis="El inyector del cilindro 8 tiene un problema de circuito.",
            probable_causes=["Inyector 8 defectuoso", "Cableado cortado"],
            corrective_actions=["Medir resistencia del inyector 8", "Reemplazar inyector"],
            prediction="Falla de encendido cilindro 8.",
            related_dtcs=["P0208"], chain_rules=["MIS-108"],
            confidence_base=0.87, min_sensors_required=[],
        ))

        # --- Sensor de oxigeno - calentadores adicionales ---
        self._add(DiagnosticRule(
            rule_id="SUPP-003",
            name="Calentador sensor O2 - B1S2",
            system=VehicleSystem.SENSOR_O2,
            severity=Severity.MODERADO,
            description="Falla en calentador del sensor O2 banco 1 sensor 2",
            condition=lambda d: _dtc_present(d, "P0141"),
            diagnosis="El calentador del sensor O2 trasero del banco 1 ha fallado.",
            probable_causes=["Calentador quemado", "Fusible fundido", "Cableado danado"],
            corrective_actions=["Medir resistencia del calentador", "Verificar alimentacion", "Reemplazar sensor"],
            prediction="Monitoreo de catalizador ineficiente. Posible falso P0420.",
            related_dtcs=["P0141"],
            confidence_base=0.85, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="SUPP-004",
            name="Calentador sensor O2 - B2S1",
            system=VehicleSystem.SENSOR_O2,
            severity=Severity.MODERADO,
            description="Falla en calentador del sensor O2 banco 2 sensor 1",
            condition=lambda d: _dtc_present(d, "P0155"),
            diagnosis="El calentador del sensor O2 delantero del banco 2 ha fallado.",
            probable_causes=["Calentador quemado", "Fusible fundido", "Cableado danado"],
            corrective_actions=["Medir resistencia del calentador", "Verificar alimentacion", "Reemplazar sensor"],
            prediction="Control de mezcla banco 2 retrasado en frio. Mayor contaminacion.",
            related_dtcs=["P0155"],
            confidence_base=0.85, min_sensors_required=[],
        ))

        self._add(DiagnosticRule(
            rule_id="SUPP-005",
            name="Calentador sensor O2 - B2S2",
            system=VehicleSystem.SENSOR_O2,
            severity=Severity.MODERADO,
            description="Falla en calentador del sensor O2 banco 2 sensor 2",
            condition=lambda d: _dtc_present(d, "P0161"),
            diagnosis="El calentador del sensor O2 trasero del banco 2 ha fallado.",
            probable_causes=["Calentador quemado", "Fusible fundido", "Cableado danado"],
            corrective_actions=["Medir resistencia del calentador", "Verificar alimentacion", "Reemplazar sensor"],
            prediction="Monitoreo de catalizador banco 2 ineficiente.",
            related_dtcs=["P0161"],
            confidence_base=0.85, min_sensors_required=[],
        ))

        # --- Sensor de temperatura de escape adicional ---
        self._add(DiagnosticRule(
            rule_id="SUPP-006",
            name="Temperatura de escape excesiva",
            system=VehicleSystem.ESCAPE,
            severity=Severity.GRAVE,
            description="Temperatura de gases de escape peligrosamente alta",
            condition=lambda d: (
                _has_sensor(d, "exhaust_gas_temp")
                and _sensor(d, "exhaust_gas_temp", 0) > 850
            ),
            diagnosis="La temperatura de los gases de escape supera los 850 C. "
                       "Riesgo de danio al turbo y catalizador.",
            probable_causes=["Mezcla pobre bajo carga", "Avance de encendido retrasado",
                            "Falla de inyector", "Turbo con problema de wastegate"],
            corrective_actions=["Reducir carga del motor", "Verificar mezcla aire-combustible",
                               "Inspeccionar turbo y wastegate"],
            prediction="Danio al turbo y/o catalizador inminente.",
            related_dtcs=["P0544", "P0546"],
            confidence_base=0.88, min_sensors_required=["exhaust_gas_temp"],
        ))

        # --- Valvula de mariposa motorizada ---
        self._add(DiagnosticRule(
            rule_id="SUPP-007",
            name="Motor del cuerpo de aceleracion",
            system=VehicleSystem.ACELERADOR,
            severity=Severity.GRAVE,
            description="Problema con motor del cuerpo de aceleracion electronico",
            condition=lambda d: _dtc_any(d, ["P2100", "P2101", "P2102", "P2103", "P2104", "P2105"]),
            diagnosis="El motor del cuerpo de aceleracion electronico (ETC) tiene una falla. "
                       "El motor puede entrar en modo limp.",
            probable_causes=["Motor ETC defectuoso", "Cableado del motor danado",
                            "Cuerpo de aceleracion obstruido", "Driver en ECU danado"],
            corrective_actions=["Limpiar cuerpo de aceleracion", "Verificar cableado",
                               "Verificar alimentacion al motor", "Reemplazar cuerpo de aceleracion si defectuoso"],
            prediction="Modo limp permanente. Velocidad maxima 50-60 km/h.",
            related_dtcs=["P2100", "P2101", "P2102", "P2103"],
            confidence_base=0.88, min_sensors_required=[],
        ))

        # --- Control de crucero ---
        self._add(DiagnosticRule(
            rule_id="SUPP-008",
            name="Sistema de control de crucero",
            system=VehicleSystem.MOTOR,
            severity=Severity.LEVE,
            description="Problema con sistema de control de crucero",
            condition=lambda d: _dtc_any(d, ["P0564", "P0565", "P0566", "P0567", "P0568"]),
            diagnosis="El sistema de control de crucero tiene una falla en su circuito.",
            probable_causes=["Interruptor de control de crucero defectuoso",
                            "Clock spring danado", "Modulo de control defectuoso"],
            corrective_actions=["Verificar interruptores del volante",
                               "Inspeccionar clock spring", "Verificar modulo de control"],
            prediction="Control de crucero inoperante. No afecta conduccion normal.",
            related_dtcs=["P0564", "P0565", "P0566"],
            confidence_base=0.82, min_sensors_required=[],
        ))

        # --- Sensor de presion de neumaticos ---
        self._add(DiagnosticRule(
            rule_id="SUPP-009",
            name="Sistema TPMS (presion de neumaticos)",
            system=VehicleSystem.CARROCERIA,
            severity=Severity.LEVE,
            description="Problema con sistema de monitoreo de presion de neumaticos",
            condition=lambda d: _dtc_any(d, ["C0750", "C0755", "C0760", "C0765"]),
            diagnosis="El sistema TPMS no puede monitorear la presion de uno o mas neumaticos.",
            probable_causes=["Sensor TPMS con bateria agotada", "Sensor danado",
                            "Neumatico reemplazado sin sensor", "Sensores no programados"],
            corrective_actions=["Verificar sensores TPMS", "Reprogramar sensores",
                               "Reemplazar sensores con bateria agotada"],
            prediction="Sin monitoreo de presion. Riesgo de conducir con presion baja.",
            related_dtcs=["C0750", "C0755", "C0760", "C0765"],
            confidence_base=0.80, min_sensors_required=[],
        ))

        # --- Sistema Stop/Start ---
        self._add(DiagnosticRule(
            rule_id="SUPP-010",
            name="Sistema Start/Stop automatico",
            system=VehicleSystem.MOTOR,
            severity=Severity.LEVE,
            description="Problema con sistema de parada/arranque automatico",
            condition=lambda d: _dtc_any(d, ["P1B00", "P1B01", "P1B15"]),
            diagnosis="El sistema Start/Stop no funciona. El motor no se apagara en semaforos.",
            probable_causes=["Bateria debil (no compatible con Start/Stop)",
                            "Sensor de bateria defectuoso", "Temperatura de motor inadecuada"],
            corrective_actions=["Verificar estado de la bateria (debe ser AGM o EFB)",
                               "Verificar sensor de bateria", "Registrar bateria nueva si fue reemplazada"],
            prediction="Mayor consumo en ciudad. Sin otras consecuencias graves.",
            related_dtcs=["P1B00", "P1B01"],
            confidence_base=0.78, min_sensors_required=[],
        ))

        # --- Suspension electronica ---
        self._add(DiagnosticRule(
            rule_id="SUPP-011",
            name="Suspension electronica/neumatica",
            system=VehicleSystem.SUSPENSION,
            severity=Severity.GRAVE,
            description="Problema con sistema de suspension electronica",
            condition=lambda d: _dtc_any(d, ["C1700", "C1701", "C1710", "C1711", "C1720", "C1721"]),
            diagnosis="El sistema de suspension electronica o neumatica tiene una falla. "
                       "La altura del vehiculo puede ser incorrecta.",
            probable_causes=["Compresor de aire defectuoso", "Fuga en bolsa de aire",
                            "Sensor de altura defectuoso", "Valvula de control defectuosa"],
            corrective_actions=["Verificar compresor de aire", "Inspeccionar bolsas por fugas",
                               "Verificar sensores de altura", "Inspeccionar valvulas de control"],
            prediction="Vehiculo puede descender a un lado. Manejo inestable.",
            related_dtcs=["C1700", "C1701", "C1710", "C1711"],
            confidence_base=0.85, min_sensors_required=[],
        ))

        # --- Control de estabilidad ---
        self._add(DiagnosticRule(
            rule_id="SUPP-012",
            name="Sensor de aceleracion lateral (ESC)",
            system=VehicleSystem.ABS,
            severity=Severity.MODERADO,
            description="Problema con sensor de aceleracion lateral",
            condition=lambda d: _dtc_any(d, ["C0186", "C0196", "C0197"]),
            diagnosis="El sensor de aceleracion lateral/yaw rate tiene una falla. "
                       "El control de estabilidad no funciona.",
            probable_causes=["Sensor de yaw rate defectuoso", "Sensor no calibrado",
                            "Cableado del sensor danado"],
            corrective_actions=["Recalibrar sensor de yaw rate", "Verificar cableado",
                               "Reemplazar sensor si defectuoso"],
            prediction="Control de estabilidad (ESC/ESP) inoperante.",
            related_dtcs=["C0186", "C0196", "C0197"],
            confidence_base=0.85, min_sensors_required=[],
        ))

        # --- Valvula de recirculacion de turbo (blow-off/diverter) ---
        self._add(DiagnosticRule(
            rule_id="SUPP-013",
            name="Valvula de recirculacion/blow-off turbo",
            system=VehicleSystem.TURBO,
            severity=Severity.MODERADO,
            description="Problema con valvula de recirculacion del turbo",
            condition=lambda d: _dtc_any(d, ["P2261", "P2262", "P2263"]),
            diagnosis="La valvula de recirculacion de aire del turbo (diverter/blow-off) "
                       "no funciona correctamente.",
            probable_causes=["Valvula diverter desgastada", "Diafragma roto",
                            "Solenoide de control defectuoso", "Manguera de vacio desconectada"],
            corrective_actions=["Inspeccionar valvula diverter", "Verificar diafragma",
                               "Comprobar solenoide de control", "Verificar manguera de vacio"],
            prediction="Perdida de presion de boost en cambios de marcha. Ruido de siseo.",
            related_dtcs=["P2261", "P2262", "P2263"],
            confidence_base=0.82, min_sensors_required=[],
        ))

        # --- Sensor de contrapresion de escape ---
        self._add(DiagnosticRule(
            rule_id="SUPP-014",
            name="Sensor de contrapresion de escape",
            system=VehicleSystem.ESCAPE,
            severity=Severity.MODERADO,
            description="Problema con sensor de contrapresion de escape",
            condition=lambda d: _dtc_any(d, ["P1471", "P1472", "P1473"]),
            diagnosis="El sensor de contrapresion de escape reporta valores anormales.",
            probable_causes=["Sensor defectuoso", "Tubo al sensor obstruido",
                            "Escape obstruido realmente", "Cableado danado"],
            corrective_actions=["Verificar sensor", "Limpiar tubo de muestreo",
                               "Verificar escape por obstruccion"],
            prediction="Si la contrapresion es real, perdida de potencia progresiva.",
            related_dtcs=["P1471", "P1472", "P1473"],
            confidence_base=0.80, min_sensors_required=[],
        ))

        # --- Sensor de posicion de valvula EGR electronica ---
        self._add(DiagnosticRule(
            rule_id="SUPP-015",
            name="Valvula EGR electronica - posicion",
            system=VehicleSystem.EGR,
            severity=Severity.MODERADO,
            description="Problema con posicion de la valvula EGR electronica",
            condition=lambda d: _dtc_any(d, ["P0403", "P0404"]),
            diagnosis="La posicion real de la valvula EGR no coincide con la comandada por la ECU.",
            probable_causes=["Valvula EGR con carbon acumulado", "Motor de la valvula desgastado",
                            "Sensor de posicion defectuoso"],
            corrective_actions=["Limpiar valvula EGR", "Verificar motor de la valvula",
                               "Verificar sensor de posicion"],
            prediction="Emisiones de NOx elevadas o ralenti inestable segun posicion.",
            related_dtcs=["P0403", "P0404"],
            confidence_base=0.84, min_sensors_required=[],
        ))

        # --- Turbo VGT (geometria variable) ---
        self._add(DiagnosticRule(
            rule_id="SUPP-016",
            name="Turbo de geometria variable (VGT)",
            system=VehicleSystem.TURBO,
            severity=Severity.GRAVE,
            description="Problema con turbo de geometria variable",
            condition=lambda d: _dtc_any(d, ["P2562", "P2563", "P0046", "P0047", "P0048", "P0049"]),
            diagnosis="El mecanismo de geometria variable del turbo no funciona. "
                       "La presion de boost no se regula correctamente.",
            probable_causes=["Mecanismo VGT atascado por hollin", "Actuador VGT defectuoso",
                            "Solenoide de control defectuoso", "Varillaje desajustado"],
            corrective_actions=["Intentar desatascar VGT (limpieza)", "Verificar actuador",
                               "Verificar solenoide de control", "Puede requerir reemplazo del turbo"],
            prediction="Perdida de potencia y humo negro. Motor en modo limp posible.",
            related_dtcs=["P0046", "P0047", "P0048", "P0049"],
            confidence_base=0.85, min_sensors_required=[],
        ))

        # --- Sensor de posicion del pedal de freno (para ESP/ABS) ---
        self._add(DiagnosticRule(
            rule_id="SUPP-017",
            name="Sensor de posicion del pedal de freno",
            system=VehicleSystem.ABS,
            severity=Severity.MODERADO,
            description="Problema con sensor de posicion del pedal de freno",
            condition=lambda d: _dtc_any(d, ["C0242", "C0245"]),
            diagnosis="El sensor de posicion del pedal de freno reporta estado incorrecto al ABS.",
            probable_causes=["Interruptor desajustado", "Sensor defectuoso", "Cableado danado"],
            corrective_actions=["Ajustar interruptor", "Verificar sensor", "Inspeccionar cableado"],
            prediction="Control de estabilidad puede funcionar incorrectamente.",
            related_dtcs=["C0242", "C0245"],
            confidence_base=0.82, min_sensors_required=[],
        ))

        # --- Sensor de acelerometro para airbag ---
        self._add(DiagnosticRule(
            rule_id="SUPP-018",
            name="Sensor de impacto frontal",
            system=VehicleSystem.AIRBAG,
            severity=Severity.CRITICO,
            description="Problema con sensor de impacto frontal",
            condition=lambda d: _dtc_any(d, ["B0015", "B0016", "B0017", "B0018"]),
            diagnosis="El sensor de impacto frontal del sistema SRS tiene una falla. "
                       "El airbag frontal puede no desplegarse.",
            probable_causes=["Sensor de impacto defectuoso", "Conector danado",
                            "Sensor desplazado por reparacion previa"],
            corrective_actions=["Inspeccionar sensor de impacto frontal",
                               "Verificar que este correctamente montado",
                               "Reemplazar sensor - NO reparar"],
            prediction="Airbags frontales pueden NO desplegarse en colision.",
            related_dtcs=["B0015", "B0016", "B0017", "B0018"],
            confidence_base=0.90, min_sensors_required=[],
        ))

        # --- Sensor de impacto lateral ---
        self._add(DiagnosticRule(
            rule_id="SUPP-019",
            name="Sensor de impacto lateral",
            system=VehicleSystem.AIRBAG,
            severity=Severity.CRITICO,
            description="Problema con sensor de impacto lateral",
            condition=lambda d: _dtc_any(d, ["B0020", "B0021", "B0022", "B0023"]),
            diagnosis="El sensor de impacto lateral del sistema SRS tiene una falla.",
            probable_causes=["Sensor de impacto lateral defectuoso", "Conector danado",
                            "Dano previo en carroceria"],
            corrective_actions=["Inspeccionar sensor de impacto lateral",
                               "Verificar montaje", "Reemplazar sensor"],
            prediction="Airbags laterales y cortinas pueden NO desplegarse.",
            related_dtcs=["B0020", "B0021", "B0022", "B0023"],
            confidence_base=0.90, min_sensors_required=[],
        ))

        # --- Control de traccion ---
        self._add(DiagnosticRule(
            rule_id="SUPP-020",
            name="Control de traccion (TCS)",
            system=VehicleSystem.ABS,
            severity=Severity.MODERADO,
            description="Problema con sistema de control de traccion",
            condition=lambda d: _dtc_any(d, ["C0131", "C0132", "C0136", "C0137"]),
            diagnosis="El sistema de control de traccion (TCS) tiene una falla.",
            probable_causes=["Sensor de velocidad de rueda defectuoso",
                            "Modulo ABS/TCS con problema", "Cableado danado"],
            corrective_actions=["Verificar sensores de velocidad de rueda",
                               "Diagnosticar modulo ABS", "Inspeccionar cableado"],
            prediction="Ruedas pueden patinar sin control en aceleracion.",
            related_dtcs=["C0131", "C0132", "C0136", "C0137"],
            confidence_base=0.84, min_sensors_required=[],
        ))

        # --- Sistema hibrido ---
        self._add(DiagnosticRule(
            rule_id="SUPP-021",
            name="Sistema hibrido - bateria de alto voltaje",
            system=VehicleSystem.ELECTRICO,
            severity=Severity.CRITICO,
            description="Problema con bateria de alto voltaje (vehiculo hibrido)",
            condition=lambda d: _dtc_any(d, ["P0A80", "P0A7F", "P0A7E", "P0AA6"]),
            diagnosis="La bateria de alto voltaje del sistema hibrido tiene un problema. "
                       "PRECAUCION: Alto voltaje presente.",
            probable_causes=["Celda de bateria degradada", "Sensor de temperatura de bateria defectuoso",
                            "Sistema de enfriamiento de bateria con falla", "Bateria al final de vida util"],
            corrective_actions=["NO intentar reparacion sin capacitacion HV",
                               "Llevar a concesionario o taller especializado en hibridos",
                               "Verificar sistema de enfriamiento de bateria"],
            prediction="Perdida de capacidad hibrida. Mayor consumo. Posible inmovilizacion.",
            related_dtcs=["P0A80", "P0A7F", "P0A7E"],
            confidence_base=0.88, min_sensors_required=[],
        ))

        # --- Control adaptativo de cambios ---
        self._add(DiagnosticRule(
            rule_id="SUPP-022",
            name="Control adaptativo de transmision",
            system=VehicleSystem.TRANSMISION,
            severity=Severity.LEVE,
            description="Problema con aprendizaje adaptativo de cambios",
            condition=lambda d: _dtc_any(d, ["P0700", "P0701", "P0702", "P0703"]),
            diagnosis="El sistema de control adaptativo de cambios de la transmision reporta una anomalia.",
            probable_causes=["Bateria desconectada (perdida de datos adaptativos)",
                            "TCM con falla menor", "Sensor de rango de transmision defectuoso"],
            corrective_actions=["Realizar procedimiento de reaprendizaje",
                               "Verificar sensor de rango", "Conducir normalmente por 50 km"],
            prediction="Cambios ligeramente bruscos hasta que reaprenada.",
            related_dtcs=["P0700", "P0701", "P0702"],
            confidence_base=0.78, min_sensors_required=[],
        ))

        # --- Recirculacion de vapores de aceite (PCV avanzado) ---
        self._add(DiagnosticRule(
            rule_id="SUPP-023",
            name="Sistema de ventilacion del carter (PCV)",
            system=VehicleSystem.MOTOR,
            severity=Severity.MODERADO,
            description="Problema con el sistema de ventilacion positiva del carter",
            condition=lambda d: _dtc_any(d, ["P051A", "P051B", "P051C", "P051D"]),
            diagnosis="El sistema PCV no funciona correctamente. Presion incorrecta en el carter.",
            probable_causes=["Valvula PCV atascada", "Separador de aceite obstruido",
                            "Manguera PCV rota", "Diafragma de PCV roto"],
            corrective_actions=["Inspeccionar y reemplazar valvula PCV",
                               "Verificar mangueras del sistema", "Limpiar separador de aceite"],
            prediction="Consumo de aceite elevado. Fugas de aceite por sellos.",
            related_dtcs=["P051A", "P051B", "P051C"],
            confidence_base=0.83, min_sensors_required=[],
        ))

        # --- Sensor de presion diferencial DPF ---
        self._add(DiagnosticRule(
            rule_id="SUPP-024",
            name="Sensor de presion diferencial DPF",
            system=VehicleSystem.ESCAPE,
            severity=Severity.MODERADO,
            description="Problema con sensor de presion diferencial del filtro de particulas",
            condition=lambda d: _dtc_any(d, ["P2452", "P2453", "P2454", "P2455"]),
            diagnosis="El sensor de presion diferencial del DPF no funciona. "
                       "No se puede determinar el nivel de obstruccion del filtro.",
            probable_causes=["Sensor de presion diferencial defectuoso",
                            "Tubos de muestreo obstruidos o desconectados",
                            "Cableado del sensor danado"],
            corrective_actions=["Verificar tubos de muestreo al sensor",
                               "Limpiar tubos de muestreo",
                               "Reemplazar sensor si defectuoso"],
            prediction="No se activara la regeneracion automatica del DPF.",
            related_dtcs=["P2452", "P2453", "P2454", "P2455"],
            confidence_base=0.84, min_sensors_required=[],
        ))

        # --- Sensor de temperatura de combustible ---
        self._add(DiagnosticRule(
            rule_id="SUPP-025",
            name="Sensor de temperatura de combustible",
            system=VehicleSystem.COMBUSTIBLE,
            severity=Severity.LEVE,
            description="Problema con sensor de temperatura de combustible",
            condition=lambda d: _dtc_any(d, ["P0180", "P0181", "P0182", "P0183"]),
            diagnosis="El sensor de temperatura de combustible reporta valores fuera de rango.",
            probable_causes=["Sensor defectuoso", "Cableado danado", "Conector corroido"],
            corrective_actions=["Verificar resistencia del sensor", "Inspeccionar conector", "Reemplazar sensor"],
            prediction="Calculo de densidad de combustible incorrecto. Menor eficiencia.",
            related_dtcs=["P0180", "P0181", "P0182", "P0183"],
            confidence_base=0.80, min_sensors_required=[],
        ))

        # --- Circuito de valvula de control de aire en ralenti ---
        self._add(DiagnosticRule(
            rule_id="SUPP-026",
            name="Valvula de control de aire de ralenti (IAC)",
            system=VehicleSystem.MOTOR,
            severity=Severity.MODERADO,
            description="Problema con valvula IAC",
            condition=lambda d: _dtc_any(d, ["P0505", "P0506", "P0507", "P0508", "P0509"]),
            diagnosis="La valvula de control de aire de ralenti (IAC) no funciona correctamente.",
            probable_causes=["Valvula IAC sucia o atascada", "Cableado defectuoso",
                            "Cuerpo de aceleracion sucio", "Fuga de vacio"],
            corrective_actions=["Limpiar valvula IAC y cuerpo de aceleracion",
                               "Verificar cableado", "Reemplazar valvula si defectuosa"],
            prediction="Ralenti inestable, calado frecuente.",
            related_dtcs=["P0505", "P0506", "P0507", "P0508"],
            confidence_base=0.84, min_sensors_required=[],
        ))

        # --- Circuito del sensor de oxigeno de banda ancha ---
        self._add(DiagnosticRule(
            rule_id="SUPP-027",
            name="Sensor de oxigeno de banda ancha (wideband) B1S1",
            system=VehicleSystem.SENSOR_O2,
            severity=Severity.MODERADO,
            description="Problema con sensor O2 de banda ancha banco 1",
            condition=lambda d: _dtc_any(d, ["P0134", "P2270", "P2271"]),
            diagnosis="El sensor de oxigeno de banda ancha B1S1 no genera actividad correcta.",
            probable_causes=["Sensor wideband defectuoso", "Calentador del sensor danado",
                            "Fuga de escape", "Cableado danado"],
            corrective_actions=["Verificar calentador del sensor", "Buscar fugas de escape",
                               "Reemplazar sensor wideband"],
            prediction="Control de mezcla impreciso. Mayor consumo y emisiones.",
            related_dtcs=["P0134", "P2270", "P2271"],
            confidence_base=0.84, min_sensors_required=[],
        ))

        # --- Falla general de sensor MAP con correlacion ---
        self._add(DiagnosticRule(
            rule_id="SUPP-028",
            name="Correlacion TPS/MAP",
            system=VehicleSystem.MOTOR,
            severity=Severity.MODERADO,
            description="Discrepancia entre sensores TPS y MAP",
            condition=lambda d: _dtc_present(d, "P0069"),
            diagnosis="Los sensores de posicion del acelerador y presion del multiple "
                       "no correlacionan correctamente.",
            probable_causes=["Sensor MAP defectuoso", "Sensor TPS defectuoso",
                            "Fuga de vacio grande", "Manguera de MAP desconectada"],
            corrective_actions=["Verificar manguera del MAP", "Comprobar sensor TPS",
                               "Buscar fugas de vacio"],
            prediction="Rendimiento erratico del motor. Aceleracion impredecible.",
            related_dtcs=["P0069"],
            confidence_base=0.82, min_sensors_required=[],
        ))

        # --- Circuito del sensor de velocidad del vehiculo B ---
        self._add(DiagnosticRule(
            rule_id="SUPP-029",
            name="Sensor de velocidad del vehiculo B",
            system=VehicleSystem.MOTOR,
            severity=Severity.MODERADO,
            description="Problema con sensor de velocidad B del vehiculo",
            condition=lambda d: _dtc_any(d, ["P0501", "P0502", "P0503"]),
            diagnosis="El sensor de velocidad B del vehiculo da lecturas erraticas o no genera senal.",
            probable_causes=["Sensor defectuoso", "Engranaje impulsor danado", "Cableado cortado"],
            corrective_actions=["Verificar senal del sensor", "Inspeccionar engranaje", "Reemplazar sensor"],
            prediction="Velocimetro incorrecto, ABS puede desactivarse.",
            related_dtcs=["P0501", "P0502", "P0503"],
            confidence_base=0.84, min_sensors_required=[],
        ))

        # --- Control de embrague de aire acondicionado ---
        self._add(DiagnosticRule(
            rule_id="SUPP-030",
            name="Embrague del compresor de AC",
            system=VehicleSystem.AIRE_ACONDICIONADO,
            severity=Severity.LEVE,
            description="Problema con embrague del compresor de aire acondicionado",
            condition=lambda d: _dtc_any(d, ["P0645", "P0646", "P0647"]),
            diagnosis="El circuito del embrague del compresor de AC tiene una falla.",
            probable_causes=["Rele del embrague defectuoso", "Bobina del embrague quemada",
                            "Cableado danado", "Fusible fundido"],
            corrective_actions=["Verificar fusible y rele", "Medir resistencia de la bobina",
                               "Verificar cableado", "Reemplazar embrague si defectuoso"],
            prediction="Aire acondicionado inoperante.",
            related_dtcs=["P0645", "P0646", "P0647"],
            confidence_base=0.83, min_sensors_required=[],
        ))

        # --- Control de velocidad del ventilador de refrigeracion ---
        self._add(DiagnosticRule(
            rule_id="SUPP-031",
            name="Modulo de control del ventilador de refrigeracion",
            system=VehicleSystem.REFRIGERACION,
            severity=Severity.MODERADO,
            description="Problema con modulo de control del ventilador",
            condition=lambda d: _dtc_any(d, ["P0691", "P0692", "P0693"]),
            diagnosis="El modulo de control del ventilador de refrigeracion tiene una falla.",
            probable_causes=["Modulo defectuoso", "Resistencia de velocidad quemada",
                            "Cableado danado"],
            corrective_actions=["Verificar modulo de control", "Comprobar resistencia",
                               "Inspeccionar cableado"],
            prediction="Ventilador a velocidad fija o inoperante.",
            related_dtcs=["P0691", "P0692", "P0693"],
            confidence_base=0.83, min_sensors_required=[],
        ))

        # --- Sensor de presion de aceite bajo en ralenti ---
        self._add(DiagnosticRule(
            rule_id="SUPP-032",
            name="Presion de aceite marginal en ralenti caliente",
            system=VehicleSystem.MOTOR,
            severity=Severity.GRAVE,
            description="Presion de aceite baja en ralenti con motor caliente",
            condition=lambda d: (
                _has_sensor(d, "oil_pressure")
                and _sensor(d, "oil_pressure", 999) < 25
                and _sensor(d, "oil_pressure", 999) >= 15
                and _sensor(d, "rpm", 0) < 900
                and _sensor(d, "coolant_temp", 0) > 90
            ),
            diagnosis="La presion de aceite en ralenti con motor caliente esta en el "
                       "limite bajo. Puede indicar desgaste de cojinetes o aceite degradado.",
            probable_causes=[
                "Aceite de motor degradado o viscosidad incorrecta",
                "Desgaste normal de cojinetes por kilometraje",
                "Bomba de aceite con desgaste inicial",
                "Filtro de aceite obstruido",
            ],
            corrective_actions=[
                "Cambiar aceite con la viscosidad recomendada",
                "Verificar que el filtro de aceite sea correcto",
                "Monitorear presion de aceite en los proximos servicios",
                "Si persiste, inspeccionar bomba de aceite",
            ],
            prediction="Desgaste gradual de cojinetes si no se atiende. "
                       "Puede evolucionar a presion critica.",
            related_dtcs=[],
            chain_rules=["MECH-002"],
            confidence_base=0.80, min_sensors_required=["oil_pressure", "rpm", "coolant_temp"],
        ))
