"""
Base de códigos DTC específicos para vehículos eléctricos e híbridos.

Rangos cubiertos:
  P0A00–P0AFF  Hybrid/EV Battery Pack, Control Module, Motor Electronics
  P0B00–P0BFF  High Voltage Battery, Charger, DC/DC Converter
  P0C00–P0CFF  Motor Electronics Cooling
  P1xxx        Fabricante (muestra de los más comunes)
  B3xxx        Cuerpo — puerto de carga / On-Board Charger
  U0xxx        Red — comunicación con BMS / Inversor

Fuentes:
  - SAE J2012-DA  (DTC definitions standard)
  - ALLDATA EV supplement
  - Mitchell1 EV codes
  - openVehicles community DTC lists (Nissan Leaf, Chevy Bolt, BMW i3, VW MEB)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EVDTCEntry:
    code:          str
    description:   str
    system:        str       # "battery" | "motor" | "charger" | "cooling" | "comm" | "body"
    severity:      str       # "critical" | "warning" | "info"
    action:        str       # acción sugerida


# ── P0A00 – P0AFF: Hybrid/EV — módulo de batería y motor ──────────────────
_P0A = {
    "P0A00": EVDTCEntry("P0A00", "Battery Energy Control Module Performance",
                        "battery", "critical",
                        "Revisar BECM, verificar conexiones de alta tensión"),
    "P0A01": EVDTCEntry("P0A01", "Battery Energy Control Module Performance Circuit Range",
                        "battery", "critical",
                        "Verificar cableado del módulo de control de energía de batería"),
    "P0A07": EVDTCEntry("P0A07", "Battery Coolant Temperature Sensor Circuit",
                        "cooling",  "warning",
                        "Revisar sensor de temperatura del refrigerante de batería"),
    "P0A08": EVDTCEntry("P0A08", "Battery Coolant Temperature Sensor Performance",
                        "cooling",  "warning",
                        "Verificar bomba de refrigerante y flujo de líquido refrigerante"),
    "P0A0A": EVDTCEntry("P0A0A", "Battery Energy Control Module Maximum Input Voltage",
                        "battery", "critical",
                        "ALTA TENSIÓN — no tocar; diagnóstico con escáner certificado EV"),
    "P0A0F": EVDTCEntry("P0A0F", "Battery Current Sensor Circuit",
                        "battery", "warning",
                        "Revisar sensor de corriente del pack; calibrar si necesario"),
    "P0A1F": EVDTCEntry("P0A1F", "Battery State of Health",
                        "battery", "warning",
                        "Capacidad de batería degradada (<70% SOH); evaluar reemplazo"),
    "P0A3F": EVDTCEntry("P0A3F", "Drive Motor 'A' Performance",
                        "motor",   "critical",
                        "Motor de tracción fuera de rango; revisar inversor y bobinados"),
    "P0A7A": EVDTCEntry("P0A7A", "Drive Motor 'A' Inverter Performance",
                        "motor",   "critical",
                        "Inversor averiado; inspeccionar IGBT y capacitores de bus DC"),
    "P0A78": EVDTCEntry("P0A78", "Drive Motor 'A' Inverter Temperature Too High",
                        "motor",   "critical",
                        "Sobrecalentamiento inversor; revisar refrigeración y filtros"),
    "P0A79": EVDTCEntry("P0A79", "Drive Motor 'A' Inverter Temperature Sensor Circuit",
                        "motor",   "warning",
                        "Revisar sensor NTC del inversor"),
    "P0A80": EVDTCEntry("P0A80", "Replace Battery Pack",
                        "battery", "critical",
                        "EOL de batería; reemplazo completo del pack requerido"),
    "P0A81": EVDTCEntry("P0A81", "Battery Pack Over Temperature",
                        "battery", "critical",
                        "Temperatura de pack >60°C; detener vehículo inmediatamente"),
    "P0A82": EVDTCEntry("P0A82", "Battery Pack Under Temperature",
                        "battery", "warning",
                        "Pack demasiado frío; precalentar antes de carga rápida DC"),
    "P0A90": EVDTCEntry("P0A90", "Drive Motor 'A' Current",
                        "motor",   "warning",
                        "Corriente de motor fuera de rango; revisar sensor de fase"),
    "P0A93": EVDTCEntry("P0A93", "Drive Motor 'A' Resolver Circuit",
                        "motor",   "warning",
                        "Resolver del motor averiado; verificar señal de posición"),
    "P0A94": EVDTCEntry("P0A94", "Drive Motor 'A' Resolver Performance",
                        "motor",   "warning",
                        "Señal del resolver inestable; revisar blindaje del cableado"),
}

# ── P0B00 – P0BFF: HV Battery / Charger / DC-DC ───────────────────────────
_P0B = {
    "P0B00": EVDTCEntry("P0B00", "Low Voltage Battery Voltage Low",
                        "battery", "warning",
                        "Batería 12V baja; revisar DC-DC converter y estado de 12V"),
    "P0B01": EVDTCEntry("P0B01", "HV Battery Pack Contactor Failure (Main+)",
                        "battery", "critical",
                        "Contactor HV principal abierto; no operar hasta inspección"),
    "P0B02": EVDTCEntry("P0B02", "HV Battery Pack Contactor Failure (Main-)",
                        "battery", "critical",
                        "Contactor HV negativo averiado; riesgo eléctrico — taller"),
    "P0B03": EVDTCEntry("P0B03", "HV Battery Pack Precharge Circuit",
                        "battery", "critical",
                        "Circuito de precarga fallado; condensadores de bus no cargan"),
    "P0B05": EVDTCEntry("P0B05", "HV Battery Pack Voltage Imbalance",
                        "battery", "warning",
                        "Desbalanceo entre módulos; verificar celda de mayor delta-V"),
    "P0B0A": EVDTCEntry("P0B0A", "High Voltage Battery Pack SOC Low",
                        "battery", "info",
                        "Pack por debajo del 10% SOC; cargar inmediatamente"),
    "P0B30": EVDTCEntry("P0B30", "On-Board Charger Circuit",
                        "charger", "critical",
                        "OBC averiado; verificar puente rectificador y MOSFET de carga"),
    "P0B31": EVDTCEntry("P0B31", "On-Board Charger Performance",
                        "charger", "warning",
                        "Carga AC reducida; temperatura o derating del OBC"),
    "P0B50": EVDTCEntry("P0B50", "DC/DC Converter Performance",
                        "battery", "warning",
                        "Convertidor DC/DC fuera de rango; revisar tensión de salida 12V"),
    "P0B51": EVDTCEntry("P0B51", "DC/DC Converter Temperature Too High",
                        "battery", "warning",
                        "Sobrecalentamiento DC/DC; comprobar refrigeración del módulo"),
}

# ── P0C00 – P0CFF: Motor Electronics Cooling ─────────────────────────────
_P0C = {
    "P0C00": EVDTCEntry("P0C00", "Motor Electronics Coolant Pump Control Circuit",
                        "cooling", "warning",
                        "Bomba de refrigerante del inversor sin señal; revisar relé"),
    "P0C10": EVDTCEntry("P0C10", "Motor Electronics Coolant Temperature Too High",
                        "cooling", "critical",
                        "Refrigerante del inversor >90°C; revisar radiador y bomba"),
    "P0C15": EVDTCEntry("P0C15", "Battery Cooling Fan Control Circuit",
                        "cooling", "warning",
                        "Ventilador de refrigeración de batería sin respuesta"),
}

# ── P1xxx fabricante — muestra de los más comunes ────────────────────────
_P1 = {
    # Nissan Leaf
    "P1A00": EVDTCEntry("P1A00", "[Nissan] LBC Battery Degradation",
                        "battery", "warning",
                        "Degradación LBC Nissan; usar Leaf Spy Pro para SOH exacto"),
    "P1A0A": EVDTCEntry("P1A0A", "[Nissan] Abnormal Cell Temperature",
                        "battery", "critical",
                        "Temperatura de celda anómala en Leaf; revisar loop de refrigeración"),
    # BMW i3
    "P1B00": EVDTCEntry("P1B00", "[BMW] SME Internal Fault",
                        "battery", "critical",
                        "Fallo interno SME (Speicher-Managementsystem); diagnóstico ISTA"),
    "P1B12": EVDTCEntry("P1B12", "[BMW] SME Cell Voltage Too High",
                        "battery", "critical",
                        "Celda de batería con sobretensión; inspección urgente"),
    # VW MEB
    "P1C00": EVDTCEntry("P1C00", "[VW MEB] HV Battery Management Fault",
                        "battery", "critical",
                        "Fallo BMS MEB; diagnóstico VCDS o ODIS"),
    "P1D30": EVDTCEntry("P1D30", "[VW MEB] Charging Inlet Lock Fault",
                        "charger", "warning",
                        "Seguro del conector de carga sin respuesta; limpiar y lubricar"),
    # Chevy Bolt
    "P1E00": EVDTCEntry("P1E00", "[Chevy] HV Battery Energy Exceeded",
                        "battery", "critical",
                        "Energía del pack excede límite — recall Bolt 2020-2022; verificar"),
    # Hyundai E-GMP
    "P1F00": EVDTCEntry("P1F00", "[Hyundai EGMP] BMS Communication Error",
                        "comm",    "critical",
                        "Pérdida de comunicación BMS E-GMP; revisar CAN HS 500 kbps"),
}

# ── B3xxx — Body / Carga OBD ───────────────────────────────────────────────
_B3 = {
    "B3010": EVDTCEntry("B3010", "Charging Port Lock Actuator Circuit",
                        "body",    "warning",
                        "Actuador de seguro del conector de carga; revisar motor del pestillo"),
    "B3012": EVDTCEntry("B3012", "Charging Port Lock Stuck Open",
                        "body",    "warning",
                        "Conector no puede bloquearse; limpiar guía del pestillo"),
    "B3013": EVDTCEntry("B3013", "Charging Port Lock Stuck Closed",
                        "body",    "critical",
                        "Conector bloqueado permanentemente; revisar solenoide de desbloqueo"),
    "B3020": EVDTCEntry("B3020", "Inductive Charging Pad Alignment",
                        "charger", "info",
                        "Alineación de pad de carga inductiva fuera de tolerancia; reposicionar"),
}

# ── U0xxx — Red / Comunicación ────────────────────────────────────────────
_U0 = {
    "U0100": EVDTCEntry("U0100", "Lost Communication with ECM/PCM",
                        "comm",    "critical",
                        "Pérdida de comunicación con módulo principal; revisar CAN bus HV"),
    "U0110": EVDTCEntry("U0110", "Lost Communication with Drive Motor Control Module",
                        "comm",    "critical",
                        "Sin respuesta del módulo de control de motor; verificar terminación CAN"),
    "U0121": EVDTCEntry("U0121", "Lost Communication with ABS Control Module",
                        "comm",    "warning",
                        "ABS sin comunicación; impacta frenado regenerativo — revisión urgente"),
    "U0140": EVDTCEntry("U0140", "Lost Communication with Body Control Module",
                        "comm",    "warning",
                        "BCM sin respuesta; puede afectar bloqueo del conector de carga"),
    "U3000": EVDTCEntry("U3000", "Control Module Internal Failure (EV ECU)",
                        "comm",    "critical",
                        "Fallo interno del módulo EV; verificar alimentación y tierra"),
    "U3003": EVDTCEntry("U3003", "Control Module Battery Voltage",
                        "comm",    "warning",
                        "Tensión de alimentación del módulo fuera de rango (12V)"),
}

# ── Base de datos unificada ───────────────────────────────────────────────
EV_DTC_DB: dict[str, EVDTCEntry] = {
    **_P0A, **_P0B, **_P0C, **_P1, **_B3, **_U0,
}


def classify_ev_dtc(code: str) -> Optional[EVDTCEntry]:
    """
    Busca un código DTC en la base de datos EV.

    Retorna EVDTCEntry si se encuentra, None si es un código ICE estándar.
    """
    return EV_DTC_DB.get(code.upper())


def is_ev_dtc(code: str) -> bool:
    """True si el código pertenece a rangos EV/híbrido."""
    code = code.upper()
    if code in EV_DTC_DB:
        return True
    # Rangos numéricos EV aunque no estén en la BD
    prefixes = ("P0A", "P0B", "P0C", "B30", "B31", "U0110", "U0121")
    return any(code.startswith(p) for p in prefixes)


from typing import Optional  # noqa: F401  (usado por type hints externos)
