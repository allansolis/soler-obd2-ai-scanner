"""
deep_analyzer.py — Motor de análisis profundo del Scaner Soler Pro.

Completamente autónomo (sin backend). Combina correlación de DTCs,
análisis de sensores, inferencia de causa raíz y plan de reparación.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .dtc_database import DTCDatabase


# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses públicas
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SensorAlert:
    sensor_name: str
    value: float
    unit: str
    expected_range: tuple[float, float]
    deviation_pct: float
    severity: str  # 'critical' | 'warning' | 'info'

    def __str__(self) -> str:
        lo, hi = self.expected_range
        return (
            f"{self.sensor_name}: {self.value} {self.unit} "
            f"(esperado {lo}–{hi} {self.unit}, desviación {self.deviation_pct:+.1f}%)"
        )


@dataclass
class DTCGroup:
    name: str
    codes: list[str]
    probable_cause: str
    affected_system: str


@dataclass
class RootCauseReport:
    probable_causes: list[str]
    confidence: float          # 0.0 – 1.0
    evidence: list[str]


@dataclass
class DiagnosisReport:
    timestamp: datetime = field(default_factory=datetime.now)
    vin: str = ""
    dtcs: list[str] = field(default_factory=list)
    sensor_alerts: list[SensorAlert] = field(default_factory=list)
    root_causes: RootCauseReport = field(
        default_factory=lambda: RootCauseReport([], 0.0, [])
    )
    health_score: int = 100
    repair_plan: str = ""
    severity: str = "info"   # 'critical' | 'warning' | 'info'


# ─────────────────────────────────────────────────────────────────────────────
# Tablas de conocimiento estático
# ─────────────────────────────────────────────────────────────────────────────

# 20+ grupos de correlación de DTCs
# Cada entrada: (nombre_grupo, prefijo/códigos, causa_probable, sistema)
_DTC_CORRELATION_RULES: list[tuple] = [
    # 1 — Misfires múltiples → bujías/bobinas/compresión general
    (
        "Misfire múltiple (varios cilindros)",
        re.compile(r"^P030[0-9]$"),
        "Bujías desgastadas, bobinas de encendido defectuosas o pérdida de compresión generalizada",
        "Sistema de encendido",
    ),
    # 2 — Misfire + código de bobina individual
    (
        "Misfire cilindro específico",
        re.compile(r"^P030[1-9]$"),
        "Bobina de encendido o bujía del cilindro afectado",
        "Sistema de encendido",
    ),
    # 3 — Mezcla pobre banco 1 + sensor O2
    (
        "Mezcla pobre Banco 1",
        {"P0171", "P0131", "P0133"},
        "MAF sucio, vacíos de aire, inyector obstruido o bomba de combustible débil",
        "Sistema de combustible",
    ),
    # 4 — Mezcla rica banco 1
    (
        "Mezcla rica Banco 1",
        {"P0172", "P0132"},
        "Inyector con fuga interna, sensor O2 B1S1 contaminado o presión de combustible excesiva",
        "Sistema de combustible",
    ),
    # 5 — Mezcla pobre banco 2
    (
        "Mezcla pobre Banco 2",
        {"P0174", "P0137", "P0139"},
        "Vacío de aire en banco 2, MAF o sensor O2 B2S1 defectuoso",
        "Sistema de combustible",
    ),
    # 6 — Mezcla rica banco 2
    (
        "Mezcla rica Banco 2",
        {"P0175", "P0138"},
        "Inyector con fuga interna banco 2 o sensor O2 B2S1 contaminado",
        "Sistema de combustible",
    ),
    # 7 — Sistema evaporativo EVAP
    (
        "Sistema evaporativo EVAP",
        re.compile(r"^P04[4-6][0-9]$"),
        "Tapón de gasolina suelto, purga EVAP defectuosa o fuga en mangueras de vacío",
        "Sistema de emisiones EVAP",
    ),
    # 8 — Catalizador por debajo del umbral
    (
        "Catalizador deteriorado",
        {"P0420", "P0430"},
        "Catalizador dañado o contaminado; también verificar O2 upstream/downstream",
        "Sistema de emisiones",
    ),
    # 9 — Sensor MAF / caudal de aire
    (
        "Falla sensor MAF",
        re.compile(r"^P010[0-3]$"),
        "MAF sucio o defectuoso; verificar filtro de aire y conducto de admisión",
        "Sistema de admisión",
    ),
    # 10 — Temperatura de refrigerante
    (
        "Falla sensor ECT / sobrecalentamiento",
        re.compile(r"^P011[6-9]$"),
        "Sensor de temperatura de refrigerante defectuoso o nivel de refrigerante bajo",
        "Sistema de refrigeración",
    ),
    # 11 — Sensor de posición del acelerador TPS
    (
        "Falla TPS",
        re.compile(r"^P012[0-9]$"),
        "Sensor TPS fuera de calibración, sucio o defectuoso",
        "Control de acelerador",
    ),
    # 12 — Sensor de posición del árbol de levas CMP
    (
        "Falla sensor CMP",
        re.compile(r"^P034[0-9]$"),
        "Sensor CMP defectuoso, reluctor sucio o cadena de distribución desgastada",
        "Tren de válvulas",
    ),
    # 13 — Sensor cigüeñal CKP
    (
        "Falla sensor CKP",
        re.compile(r"^P033[5-9]$"),
        "Sensor CKP defectuoso, reluctor dañado o holgura incorrecta",
        "Sistema de encendido",
    ),
    # 14 — Sistema EGR
    (
        "Falla EGR",
        re.compile(r"^P040[0-9]$"),
        "Válvula EGR atascada, solenoide defectuoso o conducto obstruido",
        "Control de emisiones EGR",
    ),
    # 15 — Control de ralentí
    (
        "Inestabilidad de ralentí",
        {"P0505", "P0506", "P0507"},
        "Válvula IAC sucia, vacíos de aire o acelerador con carbón",
        "Control de ralentí",
    ),
    # 16 — Tensión del sistema eléctrico
    (
        "Falla eléctrica / voltaje",
        re.compile(r"^P056[0-9]$"),
        "Alternador defectuoso, batería sulfatada o conexiones de masa corroídas",
        "Sistema eléctrico",
    ),
    # 17 — Inyectores
    (
        "Falla circuito inyector",
        re.compile(r"^P020[1-8]$"),
        "Inyector abierto/en cortocircuito, cableado dañado o driver ECU defectuoso",
        "Sistema de combustible",
    ),
    # 18 — Transmisión automática
    (
        "Falla transmisión automática",
        re.compile(r"^P07[0-3][0-9]$"),
        "Nivel o condición de ATF, solenoide de cambio defectuoso o sensor de velocidad",
        "Transmisión",
    ),
    # 19 — VVT / control de fases
    (
        "Falla VVT / variador de fase",
        re.compile(r"^P034[6-9]|P035[0-9]$"),
        "Aceite degradado, actuador OCV obstruido o árbol de levas con desgaste",
        "Tren de válvulas VVT",
    ),
    # 20 — Sensor knock / detonación
    (
        "Sensor de detonación (Knock)",
        re.compile(r"^P032[5-9]$"),
        "Sensor knock defectuoso, cableado dañado o detonación real por combustible de baja octanaje",
        "Sistema de encendido",
    ),
    # 21 — Comunicación / CAN bus
    (
        "Falla comunicación CAN/Bus",
        re.compile(r"^[UBC]0[0-9]{3}$"),
        "Bus CAN dañado, módulo en falla o resistencia de terminación incorrecta",
        "Red de comunicación",
    ),
    # 22 — Bomba de combustible / circuito
    (
        "Falla circuito bomba de combustible",
        {"P0230", "P0231", "P0232"},
        "Bomba de combustible desgastada, relé de bomba defectuoso o cableado con falla",
        "Sistema de combustible",
    ),
    # 23 — Sensor O2 aguas abajo post-catalizador
    (
        "Sensor O2 downstream inactivo",
        {"P0136", "P0137", "P0138", "P0141", "P0156", "P0157"},
        "Sensor O2 aguas abajo contaminado o circuito calentador defectuoso",
        "Sistema de emisiones",
    ),
    # 24 — Módulo de control (fallos internos ECU)
    (
        "Falla interna ECU/PCM",
        re.compile(r"^P060[0-9]$"),
        "EEPROM o memoria RAM de la ECU corrupta; requiere reparación o reemplazo de módulo",
        "Control del motor (ECU)",
    ),
]

# Rangos normales por sensor PID
# Formato: sensor_key -> (min, max, unidad, severidad_si_fuera)
_SENSOR_RANGES: dict[str, tuple] = {
    # Motor
    "rpm":              (600,   7000,  "rpm",   "critical"),
    "coolant_temp":     (70,    110,   "°C",    "critical"),
    "intake_temp":      (-20,   60,    "°C",    "warning"),
    "throttle_pos":     (0,     100,   "%",     "warning"),
    "engine_load":      (0,     100,   "%",     "info"),
    # Combustible
    "fuel_trim_st_b1":  (-10.0, 10.0,  "%",    "warning"),
    "fuel_trim_lt_b1":  (-10.0, 10.0,  "%",    "warning"),
    "fuel_trim_st_b2":  (-10.0, 10.0,  "%",    "warning"),
    "fuel_trim_lt_b2":  (-10.0, 10.0,  "%",    "warning"),
    "fuel_pressure":    (250,   450,   "kPa",   "critical"),
    "fuel_level":       (5,     100,   "%",     "info"),
    # O2 Sensores
    "o2_b1s1":          (0.1,   0.9,   "V",    "warning"),
    "o2_b1s2":          (0.1,   0.9,   "V",    "warning"),
    "o2_b2s1":          (0.1,   0.9,   "V",    "warning"),
    "o2_b2s2":          (0.1,   0.9,   "V",    "warning"),
    # MAF
    "maf":              (2.0,   400.0, "g/s",  "warning"),
    # MAP / presión colector
    "map":              (10,    107,   "kPa",  "warning"),
    # Eléctrico
    "battery_voltage":  (11.5,  15.0,  "V",   "critical"),
    "control_voltage":  (11.5,  15.0,  "V",   "critical"),
    # Velocidad
    "vehicle_speed":    (0,     260,   "km/h", "warning"),
    # Temperatura aceite
    "oil_temp":         (60,    140,   "°C",  "warning"),
    # Avance de encendido
    "timing_advance":   (-10,   45,    "°",   "warning"),
    # EGR
    "egr_commanded":    (0,     100,   "%",   "info"),
    "egr_error":        (-20,   20,    "%",   "warning"),
    # Catalizador
    "catalyst_temp_b1": (200,   900,   "°C",  "critical"),
    "catalyst_temp_b2": (200,   900,   "°C",  "critical"),
    # EVAP
    "evap_pressure":    (-200,  200,   "Pa",  "warning"),
    # Alternador
    "generator_load":   (0,     100,   "%",   "warning"),
    # Inyección directa (GDI)
    "fuel_rail_pressure": (3000, 25000, "kPa", "critical"),
}

# Reglas de causa raíz:
# Lista de (descripcion_causa, condicion_fn(dtcs, alerts), confianza, evidencias_fn)
# condicion_fn recibe (set_of_dtcs, list_of_SensorAlert) -> bool
# evidencias_fn recibe (set_of_dtcs, list_of_SensorAlert) -> list[str]

def _has_dtc(dtcs: set, *codes) -> bool:
    return bool(dtcs.intersection(codes))

def _has_alert(alerts: list[SensorAlert], sensor: str) -> Optional[SensorAlert]:
    return next((a for a in alerts if a.sensor_name == sensor), None)

def _alert_positive(alerts: list[SensorAlert], sensor: str) -> bool:
    a = _has_alert(alerts, sensor)
    return a is not None and a.value > a.expected_range[1]

def _alert_negative(alerts: list[SensorAlert], sensor: str) -> bool:
    a = _has_alert(alerts, sensor)
    return a is not None and a.value < a.expected_range[0]

_ROOT_CAUSE_RULES: list[tuple] = [
    # ── Mezcla pobre + MAF bajo + fuel trim alto → MAF o vacío
    (
        "MAF sensor sucio/defectuoso o fuga de vacío (admisión)",
        lambda dtcs, alerts: (
            _has_dtc(dtcs, "P0171", "P0174") and
            (_alert_negative(alerts, "maf") or _alert_positive(alerts, "fuel_trim_lt_b1"))
        ),
        0.82,
        lambda dtcs, alerts: [
            "DTC P0171/P0174 detectado (mezcla pobre)",
            "MAF bajo o fuel trim a largo plazo > +10%" if _alert_negative(alerts, "maf") else "Fuel trim positivo elevado",
            "Síntoma clásico: MAF contaminado o grieta en manguera de admisión post-MAF",
        ],
    ),
    # ── Mezcla rica + fuel trim negativo → inyector con fuga
    (
        "Inyector con fuga interna (mezcla rica persistente)",
        lambda dtcs, alerts: (
            _has_dtc(dtcs, "P0172", "P0175") and
            (_alert_negative(alerts, "fuel_trim_st_b1") or _alert_negative(alerts, "fuel_trim_lt_b1"))
        ),
        0.75,
        lambda dtcs, alerts: [
            "DTC P0172/P0175 detectado (mezcla rica)",
            "Fuel trim negativo: la ECU recorta combustible en exceso",
            "Posible causa: inyector que gotea en reposo, sensor MAP alto o presión de riel excesiva",
        ],
    ),
    # ── Misfires múltiples + RPM inestable
    (
        "Bujías o bobinas de encendido deterioradas (misfire generalizado)",
        lambda dtcs, alerts: (
            sum(1 for d in dtcs if re.match(r"^P030[1-9]$", d)) >= 2 or "P0300" in dtcs
        ),
        0.85,
        lambda dtcs, alerts: [
            f"DTCs de misfire presentes: {', '.join(d for d in sorted(dtcs) if re.match(r'^P030', d))}",
            "Misfires en múltiples cilindros apuntan a falla sistémica (bujías, bobinas o compresión)",
        ],
    ),
    # ── Misfire en un solo cilindro + bobina
    (
        "Bobina de encendido o bujía defectuosa en cilindro específico",
        lambda dtcs, alerts: (
            sum(1 for d in dtcs if re.match(r"^P030[1-9]$", d)) == 1 and "P0300" not in dtcs
        ),
        0.80,
        lambda dtcs, alerts: [
            f"Misfire único detectado: {next((d for d in dtcs if re.match(r'^P030[1-9]$', d)), '')}",
            "Cambiar bujía y bobina del cilindro afectado; luego verificar compresión",
        ],
    ),
    # ── Catalizador + sensor O2 downstream activo → catalizador agotado
    (
        "Catalizador de tres vías agotado (eficiencia por debajo del umbral)",
        lambda dtcs, alerts: _has_dtc(dtcs, "P0420", "P0430"),
        0.70,
        lambda dtcs, alerts: [
            "DTC P0420/P0430: sensor O2 downstream imita la señal upstream",
            "Descartar primero: coolant leak, aceite quemado o fuel trim fuera de rango",
            "Si parámetros normales → catalizador requiere reemplazo",
        ],
    ),
    # ── EVAP grande + pequeña fuga
    (
        "Fuga en sistema EVAP (tapón de combustible o manguera purga)",
        lambda dtcs, alerts: any(d in dtcs for d in {"P0440", "P0441", "P0442", "P0455", "P0456"}),
        0.72,
        lambda dtcs, alerts: [
            f"EVAP DTCs: {', '.join(d for d in sorted(dtcs) if d.startswith('P04'))}",
            "Verificar tapón de gasolina, válvula de purga y cánister de carbón",
        ],
    ),
    # ── Sobrecalentamiento + ECT alto + coolant bajo
    (
        "Sobrecalentamiento del motor (refrigeración insuficiente)",
        lambda dtcs, alerts: (
            _has_dtc(dtcs, "P0117", "P0118", "P0116") or _alert_positive(alerts, "coolant_temp")
        ),
        0.88,
        lambda dtcs, alerts: [
            "DTC o sensor ECT por encima de 110°C detectado",
            "Posibles causas: nivel bajo de refrigerante, termostato atascado cerrado, bomba de agua defectuosa o radiador obstruido",
        ],
    ),
    # ── Tensión baja + alternador
    (
        "Alternador o batería defectuosa (voltaje del sistema bajo)",
        lambda dtcs, alerts: (
            _has_dtc(dtcs, "P0560", "P0562") or _alert_negative(alerts, "battery_voltage")
        ),
        0.84,
        lambda dtcs, alerts: [
            "Voltaje de sistema < 11.5 V o DTC P056x presente",
            "Revisar alternador (salida), batería (carga/CCA) y conexiones de masa",
        ],
    ),
    # ── CKP/CMP simultáneos → distribución o sensor
    (
        "Falla en sincronización motor (CKP/CMP simultáneos)",
        lambda dtcs, alerts: (
            any(re.match(r"^P033[5-9]$", d) for d in dtcs) and
            any(re.match(r"^P034[0-9]$", d) for d in dtcs)
        ),
        0.78,
        lambda dtcs, alerts: [
            "CKP y CMP en falla simultáneamente",
            "Verificar cadena/correa de distribución, reluctores y cableado de sensores",
        ],
    ),
    # ── Inyector individual + misfire mismo cilindro
    (
        "Inyector de combustible defectuoso (abierto/obstruido)",
        lambda dtcs, alerts: any(
            f"P020{i}" in dtcs and f"P030{i}" in dtcs for i in range(1, 9)
        ),
        0.83,
        lambda dtcs, alerts: [
            "Inyector y misfire del mismo cilindro presentes simultáneamente",
            "Revisar resistencia del inyector, cableado y driver de la ECU",
        ],
    ),
    # ── Fuel pressure bajo + misfires/mezcla pobre
    (
        "Bomba de combustible o regulador de presión defectuoso",
        lambda dtcs, alerts: (
            (_has_dtc(dtcs, "P0171", "P0174") or any(re.match(r"^P030", d) for d in dtcs)) and
            _alert_negative(alerts, "fuel_pressure")
        ),
        0.79,
        lambda dtcs, alerts: [
            "Mezcla pobre/misfires + presión de combustible baja detectada",
            "Prueba de drop-test de presión; posible bomba desgastada o filtro obstruido",
        ],
    ),
]

# Patrones conocidos → diagnóstico directo
_DTC_PATTERNS: list[tuple[set | re.Pattern, str]] = [
    ({"P0300", "P0301", "P0302", "P0303", "P0304"}, "Fallo generalizado bobinas/bujías — Misfire en 4 cilindros"),
    ({"P0171", "P0174"}, "Mezcla pobre en ambos bancos — verificar MAF, vacíos de aire o bomba de combustible"),
    ({"P0172", "P0175"}, "Mezcla rica en ambos bancos — verificar presión de riel y sensor MAP"),
    ({"P0420", "P0430"}, "Catalizadores de ambos bancos por debajo de umbral — posible daño generalizado"),
    ({"P0171", "P0300"}, "Mezcla pobre + misfire — bujías carbonizadas o inyectores obstruidos"),
    ({"P0335", "P0340"}, "CKP + CMP simultáneo — distribución desfasada o cadena de timing estirada"),
    ({"P0560", "P0601"}, "Voltaje bajo + error ECU — riesgo de corrupción de datos en módulo"),
    (re.compile(r"^P030[1-4]$"), "Misfires en 1-4 cilindros — inspeccionar bujías y bobinas individualmente"),
    ({"P0441", "P0442"}, "EVAP purga incorrecta + fuga pequeña — válvula de purga o tapón de gasolina"),
    ({"P0505", "P0171"}, "Ralentí inestable + mezcla pobre — cuerpo de acelerador sucio o IAC defectuosa"),
]


# ─────────────────────────────────────────────────────────────────────────────
# DeepAnalyzer
# ─────────────────────────────────────────────────────────────────────────────

class DeepAnalyzer:
    """
    Motor de análisis profundo de diagnóstico OBD-II.
    Opera completamente offline usando DTCDatabase local y tablas internas.
    """

    def __init__(self, dtc_db: Optional[DTCDatabase] = None):
        self.dtc_db = dtc_db or DTCDatabase()

    # ── API pública ──────────────────────────────────────────────────────────

    def run_full_diagnosis(
        self,
        dtcs: list[str],
        live_data: dict,
        vehicle_info: dict,
    ) -> DiagnosisReport:
        """
        Ejecuta el diagnóstico completo y devuelve un DiagnosisReport.

        Parameters
        ----------
        dtcs : list[str]
            Códigos DTC en formato estándar (p.ej. ["P0171", "P0300"]).
        live_data : dict
            Datos en vivo del vehículo. Cada valor puede ser:
            - un número directo: {"rpm": 850}
            - un dict con 'value' (y opcionalmente 'unit'): {"rpm": {"value": 850, "unit": "rpm"}}
        vehicle_info : dict
            Información del vehículo: {"vin": "...", "make": "...", ...}
        """
        dtcs_clean = [
            (d.code if hasattr(d, 'code') else str(d)).strip().upper()
            for d in dtcs
            if (d.code if hasattr(d, 'code') else str(d)).strip()
        ]
        live_flat  = self._flatten_live_data(live_data)

        sensor_alerts = self.analyze_sensor_deviations(live_data)
        root_causes   = self.find_root_cause(dtcs_clean, live_data)
        health        = self.calculate_health_score(dtcs_clean, live_data)
        severity      = self._overall_severity(dtcs_clean, sensor_alerts)

        report = DiagnosisReport(
            vin           = vehicle_info.get("vin", ""),
            dtcs          = dtcs_clean,
            sensor_alerts = sensor_alerts,
            root_causes   = root_causes,
            health_score  = health,
            severity      = severity,
        )
        report.repair_plan = self.generate_repair_plan(report)
        return report

    def correlate_dtcs(self, dtcs: list[str]) -> list[DTCGroup]:
        """
        Agrupa DTCs relacionados en grupos con causa probable y sistema afectado.
        Un mismo DTC puede aparecer en más de un grupo.
        """
        dtcs_set = {d.strip().upper() for d in dtcs}
        groups: list[DTCGroup] = []
        seen_combos: set[frozenset] = set()

        for entry in _DTC_CORRELATION_RULES:
            name, matcher, cause, system = entry
            matched = self._match_codes(dtcs_set, matcher)
            if len(matched) == 0:
                continue
            combo_key = frozenset(matched)
            if combo_key in seen_combos:
                continue
            seen_combos.add(combo_key)
            # Enriquecer descripción de cada código desde la BD
            groups.append(DTCGroup(
                name            = name,
                codes           = sorted(matched),
                probable_cause  = cause,
                affected_system = system,
            ))

        return groups

    def analyze_sensor_deviations(self, live_data: dict) -> list[SensorAlert]:
        """
        Compara cada PID del live_data contra los rangos normales.
        Devuelve alertas para sensores fuera de rango.
        """
        flat = self._flatten_live_data(live_data)
        alerts: list[SensorAlert] = []

        for key, (lo, hi, unit, sev_level) in _SENSOR_RANGES.items():
            if key not in flat:
                continue
            val = flat[key]
            if val is None:
                continue
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue

            if lo <= val <= hi:
                continue  # dentro del rango

            # Calcular desviación porcentual respecto al límite más cercano
            rango = hi - lo
            if rango == 0:
                dev_pct = 0.0
            elif val < lo:
                dev_pct = ((val - lo) / abs(lo if lo != 0 else 0.001)) * 100
            else:
                dev_pct = ((val - hi) / abs(hi if hi != 0 else 0.001)) * 100

            alerts.append(SensorAlert(
                sensor_name    = key,
                value          = val,
                unit           = unit,
                expected_range = (lo, hi),
                deviation_pct  = round(dev_pct, 1),
                severity       = sev_level,
            ))

        return alerts

    def find_root_cause(
        self,
        dtcs: list[str],
        live_data: dict,
    ) -> RootCauseReport:
        """
        Combina patrones de DTCs y desviaciones de sensores para inferir
        la(s) causa(s) raíz más probables.
        """
        dtcs_set = {d.strip().upper() for d in dtcs}
        alerts   = self.analyze_sensor_deviations(live_data)

        causes:   list[str]  = []
        evidence: list[str]  = []
        max_conf             = 0.0

        for cause_desc, condition_fn, confidence, evidence_fn in _ROOT_CAUSE_RULES:
            try:
                if condition_fn(dtcs_set, alerts):
                    causes.append(cause_desc)
                    evidence.extend(evidence_fn(dtcs_set, alerts))
                    if confidence > max_conf:
                        max_conf = confidence
            except Exception:
                continue

        # Si no se disparó ninguna regla, reportar genérico
        if not causes and dtcs_set:
            causes   = [f"Diagnóstico pendiente para: {', '.join(sorted(dtcs_set))}"]
            evidence = ["No se encontraron patrones conocidos. Revisar manualmente cada código."]
            max_conf = 0.3
        elif not causes:
            causes   = ["Sin fallas detectadas en motor o sensores"]
            evidence = ["Todos los DTCs y sensores dentro de parámetros normales"]
            max_conf = 1.0

        # Desduplicar evidencia
        seen: set[str] = set()
        evidence_dedup = []
        for e in evidence:
            if e not in seen:
                seen.add(e)
                evidence_dedup.append(e)

        return RootCauseReport(
            probable_causes = causes,
            confidence      = round(max_conf, 2),
            evidence        = evidence_dedup,
        )

    def generate_repair_plan(self, report: DiagnosisReport) -> str:
        """
        Genera un plan de reparación en formato Markdown a partir de un DiagnosisReport.
        """
        lines: list[str] = []
        lines.append("# Plan de Reparación — Scaner Soler Pro")
        lines.append(f"**Fecha:** {report.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        if report.vin:
            lines.append(f"**VIN:** {report.vin}")
        lines.append(f"**Score de Salud:** {report.health_score}/100  "
                      f"**Severidad:** {report.severity.upper()}")
        lines.append("")

        # Sección 1 — Causa raíz
        lines.append("## 1. Diagnóstico de Causa Raíz")
        if report.root_causes.probable_causes:
            lines.append(f"**Confianza:** {report.root_causes.confidence * 100:.0f}%")
            lines.append("")
            for i, cause in enumerate(report.root_causes.probable_causes, 1):
                lines.append(f"{i}. {cause}")
            if report.root_causes.evidence:
                lines.append("")
                lines.append("**Evidencia:**")
                for ev in report.root_causes.evidence:
                    lines.append(f"- {ev}")
        else:
            lines.append("No se encontraron causas raíz identificadas.")
        lines.append("")

        # Sección 2 — DTCs con descripción enriquecida
        if report.dtcs:
            lines.append("## 2. Códigos de Falla (DTCs)")
            for code in sorted(report.dtcs):
                info = self.dtc_db.lookup(code)
                desc = info.get("description", "Descripción no disponible")
                sev  = info.get("severity", "info")
                sug  = info.get("suggested_action", "")
                icon = "🔴" if sev == "critical" else ("🟡" if sev == "warning" else "🔵")
                lines.append(f"- {icon} **{code}** — {desc}")
                if sug:
                    lines.append(f"  - *Acción sugerida:* {sug}")
            lines.append("")

        # Sección 3 — Alertas de sensores
        if report.sensor_alerts:
            lines.append("## 3. Alertas de Sensores")
            critical_alerts = [a for a in report.sensor_alerts if a.severity == "critical"]
            warning_alerts  = [a for a in report.sensor_alerts if a.severity == "warning"]
            info_alerts     = [a for a in report.sensor_alerts if a.severity == "info"]

            for group, label in [(critical_alerts, "Crítico"), (warning_alerts, "Aviso"), (info_alerts, "Info")]:
                if group:
                    lines.append(f"### {label}")
                    for a in group:
                        lo, hi = a.expected_range
                        lines.append(
                            f"- **{a.sensor_name}**: {a.value} {a.unit} "
                            f"(rango esperado: {lo}–{hi} {a.unit}, desviación: {a.deviation_pct:+.1f}%)"
                        )
            lines.append("")

        # Sección 4 — Pasos de reparación ordenados por prioridad
        lines.append("## 4. Pasos de Reparación (por Prioridad)")
        step = 1

        if report.severity == "critical":
            lines.append(f"{step}. ⚠️ **CRÍTICO:** No operar el vehículo hasta resolver los códigos críticos.")
            step += 1

        # Agregar pasos específicos según grupos de DTCs
        groups = self.correlate_dtcs(report.dtcs)
        systems_seen: set[str] = set()
        for grp in groups:
            if grp.affected_system in systems_seen:
                continue
            systems_seen.add(grp.affected_system)
            lines.append(f"{step}. **{grp.affected_system}** — {grp.probable_cause}")
            step += 1

        # Pasos de sensores críticos
        for alert in [a for a in report.sensor_alerts if a.severity == "critical"]:
            lines.append(
                f"{step}. Verificar sensor **{alert.sensor_name}** "
                f"(actual: {alert.value} {alert.unit}, rango: {alert.expected_range[0]}–{alert.expected_range[1]})"
            )
            step += 1

        # Paso final
        lines.append(f"{step}. Borrar DTCs y realizar prueba de manejo de 15 minutos para confirmar reparación.")
        lines.append(f"{step + 1}. Re-escanear para verificar que no reaparecen códigos.")
        lines.append("")

        # Sección 5 — Grupos de correlación
        if groups:
            lines.append("## 5. Grupos de Correlación de Fallas")
            for grp in groups:
                codes_str = ", ".join(grp.codes)
                lines.append(f"- **{grp.name}** ({codes_str}): {grp.probable_cause}")
            lines.append("")

        lines.append("---")
        lines.append("*Generado por Scaner Soler Pro — Motor de Análisis Profundo*")

        return "\n".join(lines)

    def calculate_health_score(
        self,
        dtcs: list[str],
        live_data: dict,
    ) -> int:
        """
        Calcula un score de salud del vehículo de 0 a 100.

        Descuentos:
        - DTC crítico: -30 pts
        - DTC warning: -15 pts
        - DTC info:    -5 pts
        - Sensor fuera de rango (cualquier severidad): -2 pts
        """
        score = 100
        dtcs_clean = [d.strip().upper() for d in dtcs]

        for code in dtcs_clean:
            info = self.dtc_db.lookup(code)
            sev  = info.get("severity", "info")
            if sev == "critical":
                score -= 30
            elif sev == "warning":
                score -= 15
            else:
                score -= 5

        alerts = self.analyze_sensor_deviations(live_data)
        score -= len(alerts) * 2

        return max(0, min(100, score))

    def check_dtc_patterns(self, dtcs: list[str]) -> list[str]:
        """
        Compara los DTCs contra patrones conocidos y devuelve diagnósticos textuales.
        """
        dtcs_set = {d.strip().upper() for d in dtcs}
        found: list[str] = []

        for pattern, diagnosis in _DTC_PATTERNS:
            if isinstance(pattern, set):
                if pattern.issubset(dtcs_set):
                    found.append(diagnosis)
            elif isinstance(pattern, re.Pattern):
                if any(pattern.match(d) for d in dtcs_set):
                    found.append(diagnosis)

        return found

    # ── Helpers privados ─────────────────────────────────────────────────────

    @staticmethod
    def _flatten_live_data(live_data: dict) -> dict[str, float]:
        """
        Normaliza live_data: acepta tanto {"rpm": 850} como
        {"rpm": {"value": 850, "unit": "rpm"}} y devuelve {"rpm": 850.0}.
        """
        flat: dict[str, float] = {}
        for key, val in live_data.items():
            key_norm = key.lower().strip().replace(" ", "_")
            if isinstance(val, dict):
                raw = val.get("value")
            else:
                raw = val
            try:
                flat[key_norm] = float(raw)
            except (TypeError, ValueError):
                pass
        return flat

    @staticmethod
    def _match_codes(dtcs_set: set[str], matcher) -> set[str]:
        """Devuelve los DTCs del conjunto que coinciden con el matcher (set o Pattern)."""
        if isinstance(matcher, set):
            return dtcs_set.intersection(matcher)
        if isinstance(matcher, re.Pattern):
            return {d for d in dtcs_set if matcher.match(d)}
        return set()

    @staticmethod
    def _overall_severity(dtcs: list[str], alerts: list[SensorAlert]) -> str:
        """Determina la severidad global del reporte."""
        # DTCs críticos llevan precedencia; usamos GENERIC_DTCS como fallback rápido
        from .dtc_database import GENERIC_DTCS
        for code in dtcs:
            sev = GENERIC_DTCS.get(code, (None, None, "info"))[2]
            if sev == "critical":
                return "critical"

        for alert in alerts:
            if alert.severity == "critical":
                return "critical"

        if dtcs or alerts:
            return "warning"

        return "info"
