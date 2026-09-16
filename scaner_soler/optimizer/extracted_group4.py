"""
extracted_group4.py — Modelos extraídos y sintetizados de 4 repos GitHub
=========================================================================

Repos revisados:
  REPO 1: github.com/lbenthins/ecu-simulator  (Python, UDS/OBD, MIT)
  REPO 2: github.com/shchers/ecu-simulator     (Python, OBD CAN, Apache-2.0)
  REPO 3: github.com/langroodi/OBD-II-Emulator (C++, OBD emulator, MIT)
  REPO 4: github.com/pschichtel/VirtualECU     (Scala, multi-ECU, GPL-3.0)

Contribuciones por repo:
  REPO 1  → constantes UDS NRC, codificación DTC OBD/UDS, servicios 0x10/0x11/0x19
  REPO 2  → rangos físicos de PIDs, valores de sensores correlacionados
  REPO 3  → arquitectura de servicio/callback, bitmap de PIDs soportados
  REPO 4  → modelo multi-estado, expresiones de cómputo por estado ECU

Qué agrega esto al sandbox MiroFish existente
─────────────────────────────────────────────
El ECUSandbox ya tiene LHS + safety guard + scoring de deltas%.
Este módulo agrega la capa de "estado físico coherente":

  ECUStateMachine   → cold_start → warm_up → idle → cruise → wot
  SensorModel       → RPM/MAP/IAT/coolant correlacionados físicamente
  UDSResponder      → respuestas UDS ISO-14229 parseable por escáner real
  OBDPIDResponder   → respuestas OBD Servicio 01 con codificación correcta
  DTCManager        → DTCs se activan cuando parámetros salen de rango
  FreezeFrameStore  → snapshot de sensores en el momento de activación DTC
  SecurityAccess    → seed-key algorithm (simple XOR+rotate, compatible UDS)

Uso desde el sandbox:
    from .extracted_group4 import ECUStateMachine, UDSResponder, DTCManager

    ecu = ECUStateMachine(initial_state='cold_start')
    ecu.tick(dt=1.0)           # avanza 1 segundo
    sensors = ecu.sensors      # dict con todos los PIDs físicamente coherentes
    dtcmgr = DTCManager(ecu)
    dtcmgr.evaluate()          # activa DTCs si hay anomalías
"""

from __future__ import annotations

import random
import math
import struct
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# SECCIÓN 1: Constantes UDS / OBD
# Fuente: REPO 1 (lbenthins) + estándar ISO 14229 / SAE J1979
# =============================================================================

# ── Negative Response Codes (NRC) ISO 14229-1 ────────────────────────────────
class NRC:
    """Códigos de Respuesta Negativa UDS (ISO 14229-1 §10.3)."""
    GENERAL_REJECT                              = 0x10
    SERVICE_NOT_SUPPORTED                       = 0x11
    SUBFUNCTION_NOT_SUPPORTED                   = 0x12  # de lbenthins
    INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT  = 0x13  # de lbenthins
    RESPONSE_TOO_LONG                           = 0x14
    CONDITIONS_NOT_CORRECT                      = 0x22
    REQUEST_SEQUENCE_ERROR                      = 0x24
    REQUEST_OUT_OF_RANGE                        = 0x31
    SECURITY_ACCESS_DENIED                      = 0x33
    INVALID_KEY                                 = 0x35
    EXCEEDED_NUMBER_OF_ATTEMPTS                 = 0x36
    REQUIRED_TIME_DELAY_NOT_EXPIRED             = 0x37
    UPLOAD_DOWNLOAD_NOT_ACCEPTED                = 0x70
    TRANSFER_DATA_SUSPENDED                     = 0x71
    GENERAL_PROGRAMMING_FAILURE                 = 0x72
    WRONG_BLOCK_SEQUENCE_COUNTER                = 0x73
    REQUEST_CORRECTLY_RECEIVED_RESPONSE_PENDING = 0x78
    SUBFUNCTION_NOT_SUPPORTED_IN_ACTIVE_SESSION = 0x7E
    SERVICE_NOT_SUPPORTED_IN_ACTIVE_SESSION     = 0x7F


# ── SIDs UDS ──────────────────────────────────────────────────────────────────
class UDS_SID:
    DIAGNOSTIC_SESSION_CONTROL  = 0x10  # de lbenthins
    ECU_RESET                   = 0x11  # de lbenthins
    SECURITY_ACCESS             = 0x27
    COMMUNICATION_CONTROL       = 0x28
    READ_DATA_BY_IDENTIFIER     = 0x22
    WRITE_DATA_BY_IDENTIFIER    = 0x2E
    CLEAR_DTC                   = 0x14
    READ_DTC_INFORMATION        = 0x19  # de lbenthins
    ROUTINE_CONTROL             = 0x31
    REQUEST_DOWNLOAD            = 0x34
    REQUEST_UPLOAD              = 0x35
    TRANSFER_DATA               = 0x36
    REQUEST_TRANSFER_EXIT       = 0x37
    NEGATIVE_RESPONSE           = 0x7F
    POSITIVE_OFFSET             = 0x40  # de shchers (response = request + 0x40)


# ── Grupos DTC (de lbenthins dtc_utils.py) ───────────────────────────────────
DTC_GROUPS = {"P": 0b00, "C": 0b01, "B": 0b10, "U": 0b11}
DTC_TYPES  = {"0": 0b00, "1": 0b01, "2": 0b10, "3": 0b11}

# ── Bitmap PIDs soportados Servicio 01 (de shchers pids.py) ──────────────────
# Bits indican PIDs 01-20 soportados: 0x05, 0x0B, 0x0C, 0x0D, 0x0F, 0x10, 0x11
# + 0x04(engine load), 0x33(baro)
OBD_SUPPORTED_PIDS_BITMAP = bytes([0xBF, 0xDF, 0xB9, 0x91])  # de shchers


# =============================================================================
# SECCIÓN 2: Modelos físicos de sensores correlacionados
# Fuente: REPO 2 (shchers) — rangos reales; física de motor
# =============================================================================

class ECUState(str, Enum):
    """Estados del ciclo de vida del motor. Inspirado en VirtualECU (REPO 4)."""
    COLD_START = "cold_start"   # arranque en frío: <40°C coolant
    WARM_UP    = "warm_up"      # calentando: 40-80°C coolant
    IDLE       = "idle"         # ralentí estable: ~750 RPM
    CRUISE     = "cruise"       # crucero: 1500-3000 RPM carga media
    WOT        = "wot"          # plena carga (Wide Open Throttle): >4000 RPM


@dataclass
class SensorSnapshot:
    """
    Snapshot de todos los sensores en un instante dado.
    Cada campo corresponde a un PID OBD-II estándar.
    """
    # Temperatura refrigerante [°C] — PID 0x05 (rango shchers: 128-135 raw → aprox. 88-95°C)
    coolant_temp_c: float = 20.0
    # Temperatura aire admisión [°C] — PID 0x0F (shchers: 60-64 raw → aprox. 20-24°C)
    intake_air_temp_c: float = 20.0
    # RPM motor — PID 0x0C (shchers: 18-70 * 256/4)
    rpm: float = 0.0
    # Velocidad vehículo [km/h] — PID 0x0D
    vehicle_speed_kmh: float = 0.0
    # Presión absoluta colector [kPa] — PID 0x0B (shchers: 10-40)
    map_kpa: float = 30.0
    # Flujo de aire MAF [g/s] — PID 0x10
    maf_gs: float = 2.0
    # Posición acelerador [%] — PID 0x11 (shchers: 20-60%)
    throttle_pct: float = 0.0
    # Carga calculada motor [%] — PID 0x04
    engine_load_pct: float = 0.0
    # Presión barométrica [kPa] — PID 0x33 (shchers: 20-60)
    baro_kpa: float = 101.3
    # Lambda (O2 estimado): 1.0 = estequiométrico, <1.0 = rico, >1.0 = pobre
    lambda_ratio: float = 1.0
    # Tiempo motor encendido [s]
    engine_run_time_s: float = 0.0
    # Voltaje batería [V]
    battery_voltage: float = 12.6
    # Timestamp
    timestamp: float = field(default_factory=time.time)

    def to_obd_dict(self) -> Dict[str, Any]:
        """Convierte a dict con claves = PID hex string."""
        return {
            "0x04": self.engine_load_pct,
            "0x05": self.coolant_temp_c,
            "0x0B": self.map_kpa,
            "0x0C": self.rpm,
            "0x0D": self.vehicle_speed_kmh,
            "0x0F": self.intake_air_temp_c,
            "0x11": self.throttle_pct,
            "0x33": self.baro_kpa,
            "lambda": self.lambda_ratio,
        }


class SensorModel:
    """
    Modelo físico de sensores correlacionados.

    Física implementada:
    ─────────────────────
    • RPM ↑ → MAF ↑ (más aire por ciclo)
    • RPM ↑ → IAT sube gradualmente (calor del motor al air box)
    • Throttle ↑ → MAP sube (menos vacío = más presión colector)
    • Idle: throttle ~2%, MAP ~30-35 kPa (vacío alto), RPM ~750
    • WOT:  throttle 100%, MAP ~95-100 kPa (casi atmosférico), RPM alto
    • Coolant temp sube durante warm_up, estabiliza en ~90°C
    • Lambda: idle=1.0, WOT=0.87 (rico), cruise lean=1.05
    • Engine load = MAF_actual / MAF_máximo_a_esa_RPM * 100

    Fuente de rangos: shchers/ecu-simulator pids.py
    """

    # Parámetros del motor (ajustables por perfil de vehículo)
    IDLE_RPM          = 750.0
    MAX_RPM           = 6500.0
    IDLE_MAP_KPA      = 32.0    # kPa en ralentí (alto vacío)
    WOT_MAP_KPA       = 98.0    # kPa a plena carga (casi baro)
    COOLANT_MAX_C     = 92.0    # temperatura estable de trabajo [°C]
    COOLANT_COLD_C    = 20.0    # temperatura de arranque en frío [°C]
    IAT_AMBIENT_C     = 25.0    # temperatura ambiente base [°C]
    MAF_MAX_GS        = 25.0    # g/s a RPM máxima (motor 1.6L típico)
    WARMUP_TIME_S     = 180.0   # segundos hasta temperatura estable

    def compute(self, state: ECUState, run_time_s: float,
                throttle_override: Optional[float] = None) -> SensorSnapshot:
        """
        Calcula todos los sensores dados el estado y el tiempo de marcha.

        Parámetros
        ──────────
        state          : estado actual de la ECU
        run_time_s     : tiempo en segundos desde arranque
        throttle_override : fuerza un % de acelerador (para simulaciones)

        Retorna SensorSnapshot con todos los valores coherentes.
        """
        snap = SensorSnapshot(engine_run_time_s=run_time_s)

        # ── Temperatura refrigerante ──────────────────────────────────────────
        # Modelo: sube con tiempo, se estabiliza en COOLANT_MAX_C
        warm_factor = min(1.0, run_time_s / self.WARMUP_TIME_S)
        snap.coolant_temp_c = (
            self.COOLANT_COLD_C
            + (self.COOLANT_MAX_C - self.COOLANT_COLD_C) * warm_factor
        )
        # Pequeña variación aleatoria ±0.5°C (shchers usa random.randrange)
        snap.coolant_temp_c += random.uniform(-0.5, 0.5)

        # ── Throttle y RPM según estado ───────────────────────────────────────
        if state == ECUState.COLD_START:
            throttle = throttle_override if throttle_override is not None else 3.0
            rpm = self.IDLE_RPM * 1.25   # RPM alta en arranque frío
        elif state == ECUState.WARM_UP:
            throttle = throttle_override if throttle_override is not None else 2.0
            rpm = self.IDLE_RPM * 1.10
        elif state == ECUState.IDLE:
            throttle = throttle_override if throttle_override is not None else 2.0
            rpm = self.IDLE_RPM + random.uniform(-30, 30)
        elif state == ECUState.CRUISE:
            throttle = throttle_override if throttle_override is not None else random.uniform(15, 35)
            rpm = random.uniform(1800, 2800)
        elif state == ECUState.WOT:
            throttle = throttle_override if throttle_override is not None else random.uniform(90, 100)
            rpm = random.uniform(4000, 6200)
        else:
            throttle = 2.0
            rpm = self.IDLE_RPM

        snap.throttle_pct = float(throttle)
        snap.rpm = float(max(0.0, rpm))

        # ── MAP: correlacionado con throttle (no-lineal) ──────────────────────
        # A mayor throttle, MAP sube hacia la presión barométrica
        # Modelo: MAP = baro - (baro - idle_MAP) * (1 - throttle/100)^1.5
        t_norm = snap.throttle_pct / 100.0
        snap.map_kpa = self.IDLE_MAP_KPA + (self.WOT_MAP_KPA - self.IDLE_MAP_KPA) * (t_norm ** 0.8)
        snap.map_kpa += random.uniform(-1.0, 1.0)
        snap.map_kpa = max(20.0, min(102.0, snap.map_kpa))

        # ── MAF: proporcional a RPM * MAP / temperatura admisión ─────────────
        # Modelo simplificado de la ecuación de flujo de aire en motor NA
        snap.maf_gs = (snap.rpm / self.MAX_RPM) * (snap.map_kpa / self.WOT_MAP_KPA) * self.MAF_MAX_GS
        snap.maf_gs += random.uniform(-0.1, 0.1)
        snap.maf_gs = max(0.1, snap.maf_gs)

        # ── IAT: sube con RPM y tiempo (calor del compartimiento motor) ───────
        rpm_factor = snap.rpm / self.MAX_RPM
        time_factor = min(1.0, run_time_s / 600.0)   # satura en 10 min
        snap.intake_air_temp_c = (
            self.IAT_AMBIENT_C
            + 15.0 * rpm_factor   # hasta +15°C por RPM alta
            + 10.0 * time_factor  # hasta +10°C por soak térmico
            + random.uniform(-1.0, 1.0)
        )

        # ── Engine load: % de capacidad de flujo de aire máxima ──────────────
        max_maf_at_rpm = (snap.rpm / self.MAX_RPM) * self.MAF_MAX_GS
        snap.engine_load_pct = min(100.0, (snap.maf_gs / max(0.1, max_maf_at_rpm)) * 100.0)

        # ── Lambda según estado ───────────────────────────────────────────────
        if state == ECUState.COLD_START:
            snap.lambda_ratio = 0.85     # muy rico en arranque frío
        elif state == ECUState.WARM_UP:
            snap.lambda_ratio = 0.90 + random.uniform(-0.02, 0.02)
        elif state == ECUState.IDLE:
            snap.lambda_ratio = 1.00 + random.uniform(-0.02, 0.02)  # lazo cerrado
        elif state == ECUState.CRUISE:
            snap.lambda_ratio = 1.02 + random.uniform(-0.03, 0.03)  # ligeramente lean
        elif state == ECUState.WOT:
            snap.lambda_ratio = 0.88 + random.uniform(-0.02, 0.02)  # rico para potencia

        # ── Velocidad vehículo ────────────────────────────────────────────────
        if state in (ECUState.IDLE, ECUState.COLD_START, ECUState.WARM_UP):
            snap.vehicle_speed_kmh = 0.0
        elif state == ECUState.CRUISE:
            snap.vehicle_speed_kmh = random.uniform(60, 120)
        elif state == ECUState.WOT:
            snap.vehicle_speed_kmh = random.uniform(80, 200)

        # ── Voltaje batería ───────────────────────────────────────────────────
        if rpm > 500:
            snap.battery_voltage = 14.2 + random.uniform(-0.2, 0.2)  # alternador activo
        else:
            snap.battery_voltage = 12.4 + random.uniform(-0.1, 0.1)

        snap.timestamp = time.time()
        return snap


# =============================================================================
# SECCIÓN 3: Máquina de estados ECU
# Fuente: VirtualECU (REPO 4) — concepto multi-estado; física propia
# =============================================================================

class ECUStateMachine:
    """
    Máquina de estados del motor. Transiciona entre:
    cold_start → warm_up → idle → cruise ↔ wot

    Permite simular un ciclo de conducción completo o quedarse en un estado
    fijo para pruebas de diagnóstico.
    """

    WARMUP_THRESHOLD_C = 70.0   # coolant para salir de warm_up
    IDLE_RPM_THRESHOLD = 900.0  # RPM límite idle/cruise

    def __init__(self, initial_state: str = "cold_start",
                 coolant_start_c: float = 20.0):
        self.state = ECUState(initial_state)
        self._run_time_s: float = 0.0
        self._model = SensorModel()
        self._model.COOLANT_COLD_C = coolant_start_c
        self.sensors: SensorSnapshot = SensorSnapshot()
        self._history: List[SensorSnapshot] = []
        self._forced_state: Optional[ECUState] = None

    def force_state(self, state: str) -> None:
        """Fuerza un estado específico (útil para pruebas UDS)."""
        self._forced_state = ECUState(state)
        self.state = self._forced_state

    def release_forced_state(self) -> None:
        self._forced_state = None

    def tick(self, dt: float = 1.0,
             throttle_override: Optional[float] = None) -> SensorSnapshot:
        """
        Avanza la simulación dt segundos.

        Transiciones automáticas:
        • cold_start → warm_up cuando coolant > 40°C
        • warm_up → idle cuando coolant > WARMUP_THRESHOLD_C
        • idle → cruise si throttle_override > 20%
        • cruise → wot si throttle_override > 85%
        """
        self._run_time_s += dt

        if self._forced_state is None:
            self._auto_transition(throttle_override)

        self.sensors = self._model.compute(
            state=self.state,
            run_time_s=self._run_time_s,
            throttle_override=throttle_override,
        )
        self._history.append(self.sensors)
        # Mantener solo los últimos 300 snapshots (5 min a 1 Hz)
        if len(self._history) > 300:
            self._history.pop(0)
        return self.sensors

    def _auto_transition(self, throttle: Optional[float]) -> None:
        warm_factor = min(1.0, self._run_time_s / SensorModel.WARMUP_TIME_S)
        approx_coolant = (
            SensorModel.COOLANT_COLD_C
            + (SensorModel.COOLANT_MAX_C - SensorModel.COOLANT_COLD_C) * warm_factor
        )

        if self.state == ECUState.COLD_START and approx_coolant > 40.0:
            self.state = ECUState.WARM_UP
        elif self.state == ECUState.WARM_UP and approx_coolant > self.WARMUP_THRESHOLD_C:
            self.state = ECUState.IDLE
        elif self.state == ECUState.IDLE and throttle is not None and throttle > 20.0:
            self.state = ECUState.CRUISE
        elif self.state == ECUState.CRUISE:
            if throttle is not None:
                if throttle > 85.0:
                    self.state = ECUState.WOT
                elif throttle < 5.0:
                    self.state = ECUState.IDLE
        elif self.state == ECUState.WOT and throttle is not None and throttle < 60.0:
            self.state = ECUState.CRUISE

    @property
    def run_time_s(self) -> float:
        return self._run_time_s

    def get_state_summary(self) -> Dict[str, Any]:
        s = self.sensors
        return {
            "state": self.state.value,
            "run_time_s": round(self._run_time_s, 1),
            "rpm": round(s.rpm, 0),
            "coolant_c": round(s.coolant_temp_c, 1),
            "throttle_pct": round(s.throttle_pct, 1),
            "map_kpa": round(s.map_kpa, 1),
            "lambda": round(s.lambda_ratio, 3),
            "iat_c": round(s.intake_air_temp_c, 1),
            "battery_v": round(s.battery_voltage, 2),
        }


# =============================================================================
# SECCIÓN 4: Gestión de DTCs con activación por condiciones físicas
# Fuente: REPO 1 (lbenthins dtc_utils.py) + extensión propia
# =============================================================================

@dataclass
class DTCEntry:
    """Entrada de código DTC con estado y freeze frame."""
    code: str                        # Ej: "P0118"
    description: str
    status: int = 0x2F               # Byte de estado UDS (de lbenthins encode_uds_dtcs)
    # 0x2F = 0010 1111: confirmado + activo + testFailed + warningIndicatorRequested
    active: bool = False
    confirmed: bool = False
    freeze_frame: Optional[SensorSnapshot] = None
    first_seen_ts: float = 0.0
    last_seen_ts: float = 0.0
    occurrence_count: int = 0

    def activate(self, sensors: SensorSnapshot) -> None:
        """Activa el DTC y guarda freeze frame."""
        now = time.time()
        if not self.active:
            self.active = True
            self.first_seen_ts = now
            self.freeze_frame = sensors   # freeze frame: estado en el momento de fallo
            self.status |= 0x01          # testFailed
        self.last_seen_ts = now
        self.occurrence_count += 1
        if self.occurrence_count >= 2:
            self.confirmed = True
            self.status |= 0x20          # confirmedDTC

    def deactivate(self) -> None:
        """Desactiva el DTC (condición de fallo desaparecida)."""
        self.active = False
        self.status &= ~0x01             # clear testFailed bit

    def encode_obd(self) -> bytes:
        """
        Codifica DTC a 2 bytes para respuesta OBD Servicio 03.
        Algoritmo de lbenthins/dtc_utils.py encode_obd_dtcs().
        """
        if len(self.code) != 5:
            return b'\x00\x00'
        group_char = self.code[0].upper()
        type_char  = self.code[1]
        group_bits = DTC_GROUPS.get(group_char, 0b00)
        type_bits  = DTC_TYPES.get(type_char, 0b00)
        # Primer byte: [group(2) | type(2) | hex_digit_2(4)]
        byte1 = (group_bits << 6) | (type_bits << 4) | int(self.code[2], 16)
        # Segundo byte: [hex_digit_3(4) | hex_digit_4(4)]
        byte2 = (int(self.code[3], 16) << 4) | int(self.code[4], 16)
        return bytes([byte1, byte2])

    def encode_uds(self) -> bytes:
        """
        Codifica DTC a 4 bytes para respuesta UDS Servicio 0x19.
        Algoritmo de lbenthins/dtc_utils.py encode_uds_dtcs():
        2 bytes OBD + 0x01 + status_byte
        """
        obd = self.encode_obd()
        return obd + bytes([0x01, self.status])


class DTCManager:
    """
    Gestor de DTCs con activación automática por condiciones físicas.

    Condiciones de activación basadas en rangos de sensores conocidos
    del estándar OBD-II SAE J2012.
    """

    # Tabla de DTCs con sus condiciones de activación
    # Formato: (code, descripción, función_condición(SensorSnapshot) → bool)
    DTC_DEFINITIONS: List[Tuple[str, str]] = [
        ("P0118", "Coolant Temperature Circuit High"),
        ("P0117", "Coolant Temperature Circuit Low"),
        ("P0113", "Intake Air Temperature Circuit High"),
        ("P0112", "Intake Air Temperature Circuit Low"),
        ("P0106", "MAP/BARO Pressure Circuit Range/Performance"),
        ("P0171", "System Too Lean (Bank 1)"),
        ("P0172", "System Too Rich (Bank 1)"),
        ("P0300", "Random/Multiple Cylinder Misfire Detected"),
        ("P0562", "System Voltage Low"),
        ("P0563", "System Voltage High"),
        ("P0507", "Idle Control System RPM High"),
        ("P0506", "Idle Control System RPM Low"),
    ]

    def __init__(self, ecu: ECUStateMachine,
                 initial_dtcs: Optional[List[str]] = None):
        self.ecu = ecu
        self._dtcs: Dict[str, DTCEntry] = {}
        # Inicializa todas las definiciones
        for code, desc in self.DTC_DEFINITIONS:
            self._dtcs[code] = DTCEntry(code=code, description=desc)
        # Activa DTCs iniciales (cargados desde vehículo real)
        for code in (initial_dtcs or []):
            if code in self._dtcs:
                # Activa sin freeze frame (ya existía antes de conectar)
                self._dtcs[code].active = True
                self._dtcs[code].confirmed = True

    def evaluate(self) -> List[str]:
        """
        Evalúa los sensores actuales y activa/desactiva DTCs según condiciones.
        Retorna lista de códigos DTC activos.
        """
        s = self.ecu.sensors
        newly_triggered = []

        # ── P0118 Coolant alto (>120°C) ───────────────────────────────────────
        if s.coolant_temp_c > 120.0:
            self._dtcs["P0118"].activate(s)
            newly_triggered.append("P0118")
        else:
            self._dtcs["P0118"].deactivate()

        # ── P0117 Coolant bajo (<-30°C, sensor abierto) ───────────────────────
        if s.coolant_temp_c < -30.0:
            self._dtcs["P0117"].activate(s)
        else:
            self._dtcs["P0117"].deactivate()

        # ── P0113 IAT alto (>80°C) ────────────────────────────────────────────
        if s.intake_air_temp_c > 80.0:
            self._dtcs["P0113"].activate(s)
            newly_triggered.append("P0113")
        else:
            self._dtcs["P0113"].deactivate()

        # ── P0112 IAT bajo (<-30°C) ───────────────────────────────────────────
        if s.intake_air_temp_c < -30.0:
            self._dtcs["P0112"].activate(s)
        else:
            self._dtcs["P0112"].deactivate()

        # ── P0106 MAP fuera de rango ──────────────────────────────────────────
        # En idle MAP debe ser < 50 kPa; en WOT debe ser > 60 kPa
        if self.ecu.state == ECUState.IDLE and s.map_kpa > 65.0:
            self._dtcs["P0106"].activate(s)
            newly_triggered.append("P0106")
        elif self.ecu.state == ECUState.WOT and s.map_kpa < 40.0:
            self._dtcs["P0106"].activate(s)
            newly_triggered.append("P0106")
        else:
            self._dtcs["P0106"].deactivate()

        # ── P0171 Mezcla pobre (lambda > 1.15 sostenido) ─────────────────────
        if s.lambda_ratio > 1.15 and self.ecu.state not in (ECUState.COLD_START,):
            self._dtcs["P0171"].activate(s)
            newly_triggered.append("P0171")
        else:
            self._dtcs["P0171"].deactivate()

        # ── P0172 Mezcla rica (lambda < 0.80 sostenido) ───────────────────────
        if s.lambda_ratio < 0.80 and self.ecu.state not in (ECUState.COLD_START,):
            self._dtcs["P0172"].activate(s)
            newly_triggered.append("P0172")
        else:
            self._dtcs["P0172"].deactivate()

        # ── P0300 Misfire (RPM muy inestable en idle, indicado por RPM baja) ──
        if self.ecu.state == ECUState.IDLE and s.rpm < 400.0:
            self._dtcs["P0300"].activate(s)
            newly_triggered.append("P0300")
        else:
            self._dtcs["P0300"].deactivate()

        # ── P0562 Voltaje bajo (<11.5V) ───────────────────────────────────────
        if s.battery_voltage < 11.5:
            self._dtcs["P0562"].activate(s)
        else:
            self._dtcs["P0562"].deactivate()

        # ── P0563 Voltaje alto (>15.5V) ───────────────────────────────────────
        if s.battery_voltage > 15.5:
            self._dtcs["P0563"].activate(s)
        else:
            self._dtcs["P0563"].deactivate()

        # ── P0507 RPM idle alto (> 1100 RPM sostenido en idle) ───────────────
        if self.ecu.state == ECUState.IDLE and s.rpm > 1100.0:
            self._dtcs["P0507"].activate(s)
        else:
            self._dtcs["P0507"].deactivate()

        # ── P0506 RPM idle bajo (< 500 RPM en idle) ───────────────────────────
        if self.ecu.state == ECUState.IDLE and s.rpm < 500.0:
            self._dtcs["P0506"].activate(s)
        else:
            self._dtcs["P0506"].deactivate()

        return newly_triggered

    def get_active_dtcs(self) -> List[DTCEntry]:
        return [d for d in self._dtcs.values() if d.active]

    def get_confirmed_dtcs(self) -> List[DTCEntry]:
        return [d for d in self._dtcs.values() if d.confirmed]

    def clear_all_dtcs(self) -> None:
        """Simula el borrado de DTCs (Servicio OBD 0x04 / UDS 0x14)."""
        for d in self._dtcs.values():
            d.active = False
            d.confirmed = False
            d.freeze_frame = None
            d.occurrence_count = 0
            d.status = 0x00

    def inject_dtc(self, code: str) -> None:
        """Inyecta un DTC manualmente (para pruebas del sandbox)."""
        if code in self._dtcs:
            self._dtcs[code].activate(self.ecu.sensors)
        else:
            # DTC externo no en la tabla: agrega dinámicamente
            self._dtcs[code] = DTCEntry(
                code=code,
                description=f"Custom injected DTC",
                active=True, confirmed=True,
                freeze_frame=self.ecu.sensors
            )

    def encode_obd_response(self) -> bytes:
        """
        Construye respuesta completa para Servicio OBD 03 (Show DTCs).
        Formato: [num_dtcs] + [2 bytes por DTC] ...
        De lbenthins obd/responses.py pattern.
        """
        active = self.get_active_dtcs()
        response = bytes([len(active)])
        for dtc in active:
            response += dtc.encode_obd()
        return response

    def encode_uds_dtc_response(self, status_mask: int = 0xFF) -> bytes:
        """
        Construye respuesta para UDS Servicio 0x19 subfunción 0x02.
        Formato: [status_availability_mask(1)] + [4 bytes por DTC] ...
        De lbenthins uds/services.py patrón ReadDTCInformation.
        """
        active = [d for d in self._dtcs.values()
                  if d.active and (d.status & status_mask)]
        response = bytes([status_mask])  # statusAvailabilityMask
        for dtc in active:
            response += dtc.encode_uds()
        return response


# =============================================================================
# SECCIÓN 5: SecurityAccess UDS (seed-key)
# Fuente: patrón UDS estándar; REPO 1 mencionaba el servicio pero no lo
# implementaba — aquí implementación propia compatible ISO 14229-1
# =============================================================================

class SecurityAccessLevel(Enum):
    LOCKED          = 0
    PROGRAMMING     = 1   # nivel 0x01/0x02 UDS
    EXTENDED_DIAG   = 3   # nivel 0x03/0x04 UDS


class SecurityAccessManager:
    """
    Implementa el protocolo SecurityAccess UDS (Servicio 0x27).

    Algoritmo seed-key (nivel 0x01):
    ────────────────────────────────
    key = ((seed XOR 0x9D3F) + 0x4321) & 0xFFFF
    Este es un algoritmo simple pero efectivo para pruebas.
    Los OEMs usan variantes más complejas (por ej. PKCS, AES).

    Flujo:
    1. Tester envía 27 01 (requestSeed)
    2. ECU responde 67 01 SEED_HI SEED_LO
    3. Tester calcula key = f(seed)
    4. Tester envía 27 02 KEY_HI KEY_LO
    5. ECU verifica, responde 67 02 (OK) o 7F 27 35 (InvalidKey)
    """

    MAX_ATTEMPTS = 3       # intentos antes de bloqueo temporal
    LOCKOUT_TIME_S = 10.0  # segundos bloqueado tras MAX_ATTEMPTS fallidos

    def __init__(self):
        self._current_seed: Optional[int] = None
        self._level = SecurityAccessLevel.LOCKED
        self._attempt_count = 0
        self._lockout_until: float = 0.0
        self._session_type: int = 0x01  # defaultSession

    @staticmethod
    def _compute_key(seed: int, level: int = 0x01) -> int:
        """
        Calcula la key esperada a partir del seed.
        Algoritmo: XOR con constante mágica + desplazamiento circular.

        level 0x01 (programming): key = ((seed XOR 0x9D3F) + 0x4321) & 0xFFFF
        level 0x03 (extended):    key = ((seed ROTL 3) XOR 0xA5A5) & 0xFFFF
        """
        if level in (0x01, 0x02):
            return ((seed ^ 0x9D3F) + 0x4321) & 0xFFFF
        elif level in (0x03, 0x04):
            # Rotate left 3 bits en 16 bits
            rotated = ((seed << 3) | (seed >> 13)) & 0xFFFF
            return rotated ^ 0xA5A5
        else:
            return seed ^ 0xFFFF

    def request_seed(self, sub_function: int) -> bytes:
        """
        Procesa requestSeed (27 [subfunction]).
        Retorna respuesta positiva [67 subfunction seed_hi seed_lo]
        o negativa [7F 27 NRC].
        """
        now = time.time()
        # Verificar lockout
        if now < self._lockout_until:
            remaining = self._lockout_until - now
            # NRC 0x37: requiredTimeDelayNotExpired
            return bytes([UDS_SID.NEGATIVE_RESPONSE, 0x27,
                          NRC.REQUIRED_TIME_DELAY_NOT_EXPIRED])

        # Ya autenticado en este nivel
        if self._level != SecurityAccessLevel.LOCKED:
            # Seed = 0x0000 si ya está desbloqueado (de spec UDS)
            return bytes([0x67, sub_function, 0x00, 0x00])

        # Genera seed aleatorio de 16 bits
        self._current_seed = random.randint(0x0001, 0xFFFE)
        seed_hi = (self._current_seed >> 8) & 0xFF
        seed_lo = self._current_seed & 0xFF
        return bytes([0x67, sub_function, seed_hi, seed_lo])

    def send_key(self, sub_function: int, key: int) -> bytes:
        """
        Procesa sendKey (27 [subfunction+1] key_hi key_lo).
        Retorna respuesta positiva [67 subfunction+1] o negativa.
        """
        now = time.time()
        if now < self._lockout_until:
            return bytes([UDS_SID.NEGATIVE_RESPONSE, 0x27,
                          NRC.REQUIRED_TIME_DELAY_NOT_EXPIRED])

        if self._current_seed is None:
            return bytes([UDS_SID.NEGATIVE_RESPONSE, 0x27,
                          NRC.REQUEST_SEQUENCE_ERROR])

        expected_key = self._compute_key(self._current_seed, sub_function - 1)

        if key != expected_key:
            self._attempt_count += 1
            self._current_seed = None
            if self._attempt_count >= self.MAX_ATTEMPTS:
                self._lockout_until = now + self.LOCKOUT_TIME_S
                self._attempt_count = 0
                return bytes([UDS_SID.NEGATIVE_RESPONSE, 0x27,
                              NRC.EXCEEDED_NUMBER_OF_ATTEMPTS])
            return bytes([UDS_SID.NEGATIVE_RESPONSE, 0x27,
                          NRC.INVALID_KEY])

        # Key correcta
        self._attempt_count = 0
        self._current_seed = None
        if sub_function in (0x01, 0x02):
            self._level = SecurityAccessLevel.PROGRAMMING
        else:
            self._level = SecurityAccessLevel.EXTENDED_DIAG
        return bytes([0x67, sub_function])

    def is_unlocked(self, required_level: SecurityAccessLevel = SecurityAccessLevel.PROGRAMMING) -> bool:
        return self._level.value >= required_level.value

    def lock(self) -> None:
        """Vuelve a bloquear (tras ECUReset o fin de sesión)."""
        self._level = SecurityAccessLevel.LOCKED
        self._current_seed = None


# =============================================================================
# SECCIÓN 6: UDSResponder — respuestas ISO 14229-1
# Fuente: REPO 1 (lbenthins uds/services.py) + extensión propia
# =============================================================================

class UDSResponder:
    """
    Procesa y genera respuestas UDS (ISO 14229-1) para los servicios
    implementados en lbenthins + SecurityAccess + ReadDataByIdentifier.

    Construido sobre ECUStateMachine + DTCManager + SecurityAccessManager.
    """

    # Tipos de sesión (0x10 DiagnosticSessionControl, de lbenthins)
    SESSION_DEFAULT     = 0x01
    SESSION_PROGRAMMING = 0x02
    SESSION_EXTENDED    = 0x03

    # Parámetros de sesión (P2_server, P2*_server en ms)
    SESSION_PARAMS = {0x01: (50, 5000), 0x02: (25, 5000), 0x03: (50, 5000)}

    # Tipos de reset (0x11 ECUReset, de lbenthins)
    RESET_HARD        = 0x01
    RESET_KEY_OFF_ON  = 0x02
    RESET_SOFT        = 0x03
    RESET_ENABLE_RAPID_SHUTDOWN  = 0x04
    RESET_DISABLE_RAPID_SHUTDOWN = 0x05

    def __init__(self, ecu: ECUStateMachine,
                 dtc_manager: DTCManager,
                 vin: str = "TESTVIN0123456789",
                 ecu_name: str = "SCANER_SOLER_ECU"):
        self.ecu = ecu
        self.dtc = dtc_manager
        self.security = SecurityAccessManager()
        self._session = self.SESSION_DEFAULT
        self._vin = vin[:17].ljust(17)
        self._ecu_name = ecu_name[:20]

    def process(self, request: bytes) -> bytes:
        """
        Punto de entrada principal. Procesa un frame UDS completo.

        Parámetros
        ──────────
        request : bytes — payload UDS sin cabecera ISO-TP

        Retorna
        ───────
        bytes — respuesta UDS (positiva o negativa)
        """
        if not request:
            return self._nrc(0x00, NRC.INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT)

        sid = request[0]
        data = request[1:]

        dispatch = {
            UDS_SID.DIAGNOSTIC_SESSION_CONTROL: self._handle_session_control,
            UDS_SID.ECU_RESET:                  self._handle_ecu_reset,
            UDS_SID.SECURITY_ACCESS:            self._handle_security_access,
            UDS_SID.READ_DTC_INFORMATION:       self._handle_read_dtc,
            UDS_SID.READ_DATA_BY_IDENTIFIER:    self._handle_read_data_by_id,
            UDS_SID.CLEAR_DTC:                  self._handle_clear_dtc,
        }

        handler = dispatch.get(sid)
        if handler is None:
            return self._nrc(sid, NRC.SERVICE_NOT_SUPPORTED)
        return handler(sid, data)

    # ── Servicios individuales (de lbenthins + extensiones) ──────────────────

    def _handle_session_control(self, sid: int, data: bytes) -> bytes:
        """0x10 DiagnosticSessionControl — de lbenthins uds/services.py."""
        if len(data) < 1:
            return self._nrc(sid, NRC.INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT)
        session_type = data[0]
        if session_type not in (0x01, 0x02, 0x03, 0x04):
            return self._nrc(sid, NRC.SUBFUNCTION_NOT_SUPPORTED)
        self._session = session_type
        p2, p2star = self.SESSION_PARAMS.get(session_type, (50, 5000))
        # Respuesta: [0x50] + [session_type] + [P2 hi/lo] + [P2* hi/lo]
        return bytes([0x50, session_type,
                      (p2 >> 8) & 0xFF, p2 & 0xFF,
                      (p2star >> 8) & 0xFF, p2star & 0xFF])

    def _handle_ecu_reset(self, sid: int, data: bytes) -> bytes:
        """0x11 ECUReset — de lbenthins uds/services.py."""
        if len(data) < 1:
            return self._nrc(sid, NRC.INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT)
        reset_type = data[0]
        if reset_type not in range(0x01, 0x06):
            return self._nrc(sid, NRC.SUBFUNCTION_NOT_SUPPORTED)
        # Simular reset: vuelve a cold_start
        self.ecu.force_state("cold_start")
        self.security.lock()
        if reset_type == self.RESET_ENABLE_RAPID_SHUTDOWN:
            return bytes([0x51, reset_type, 0x01])  # powerDownTime = 1s
        return bytes([0x51, reset_type])

    def _handle_security_access(self, sid: int, data: bytes) -> bytes:
        """0x27 SecurityAccess — implementación propia basada en ISO 14229."""
        if len(data) < 1:
            return self._nrc(sid, NRC.INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT)
        sub_fn = data[0]
        if sub_fn % 2 == 1:  # requestSeed (subfunciones impares)
            return self.security.request_seed(sub_fn)
        else:                 # sendKey (subfunciones pares)
            if len(data) < 3:
                return self._nrc(sid, NRC.INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT)
            key = (data[1] << 8) | data[2]
            return self.security.send_key(sub_fn, key)

    def _handle_read_dtc(self, sid: int, data: bytes) -> bytes:
        """0x19 ReadDTCInformation — de lbenthins uds/services.py."""
        if len(data) < 1:
            return self._nrc(sid, NRC.INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT)
        sub_fn = data[0]
        if sub_fn == 0x02:  # reportDTCByStatusMask
            status_mask = data[1] if len(data) > 1 else 0xFF
            payload = self.dtc.encode_uds_dtc_response(status_mask)
            return bytes([0x59, sub_fn]) + payload
        elif sub_fn == 0x0F:  # reportSupportedDTCs
            payload = self.dtc.encode_uds_dtc_response(0xFF)
            return bytes([0x59, sub_fn]) + payload
        else:
            return self._nrc(sid, NRC.SUBFUNCTION_NOT_SUPPORTED)

    def _handle_read_data_by_id(self, sid: int, data: bytes) -> bytes:
        """0x22 ReadDataByIdentifier — PIDs en tiempo real como DID UDS."""
        if len(data) < 2:
            return self._nrc(sid, NRC.INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT)
        did = (data[0] << 8) | data[1]
        s = self.ecu.sensors

        did_map = {
            0xF190: self._vin.encode("ascii"),            # VIN
            0xF18C: self._ecu_name.encode("ascii"),       # ECU serial/name
            0xF401: struct.pack(">H", int(s.rpm * 4)),    # RPM (UDS escala OBD)
            0xF402: bytes([int(s.coolant_temp_c + 40)]),  # Coolant (+40 offset)
            0xF403: bytes([int(s.throttle_pct * 255/100)]),
            0xF404: bytes([int(s.map_kpa)]),
            0xF405: struct.pack(">H", int(s.maf_gs * 100)),
        }

        if did not in did_map:
            return self._nrc(sid, NRC.REQUEST_OUT_OF_RANGE)
        payload = did_map[did]
        return bytes([0x62, data[0], data[1]]) + payload

    def _handle_clear_dtc(self, sid: int, data: bytes) -> bytes:
        """0x14 ClearDiagnosticInformation."""
        # Requiere sesión extendida o autenticación
        # (en esta implementación permitimos en cualquier sesión para simplificar)
        self.dtc.clear_all_dtcs()
        return bytes([0x54])

    @staticmethod
    def _nrc(sid: int, nrc_code: int) -> bytes:
        """Construye respuesta negativa UDS."""
        return bytes([UDS_SID.NEGATIVE_RESPONSE, sid, nrc_code])


# =============================================================================
# SECCIÓN 7: OBDPIDResponder — respuestas OBD Servicio 01
# Fuente: REPO 2 (shchers ecu-simulator.py + pids.py) — rangos y codificación
#         REPO 3 (langroodi) — arquitectura de servicio con bitmap de soporte
# =============================================================================

class OBDPIDResponder:
    """
    Genera respuestas OBD-II Servicio 01 (PIDs en tiempo real).

    Codificación basada en shchers/ecu-simulator:
    • RPM:     (A*256+B)/4  → raw = RPM * 4
    • Coolant: A - 40       → raw = temp + 40
    • MAP:     A kPa        → raw = kPa (1 byte)
    • Speed:   A km/h       → raw = km/h (1 byte)
    • Throttle: A*100/255   → raw = throttle * 255/100
    • IAT:     A - 40       → raw = temp + 40
    • MAF:     (A*256+B)/100→ raw = MAF * 100 (2 bytes)
    • Baro:    A kPa        → raw = kPa (1 byte)

    Respuesta OBD: longitud(1) + 0x41(1) + PID(1) + datos(1-4)
    """

    def __init__(self, ecu: ECUStateMachine, dtc_manager: Optional[DTCManager] = None):
        self.ecu = ecu
        self.dtc = dtc_manager

    def process(self, request: bytes) -> Optional[bytes]:
        """
        Procesa una solicitud OBD-II.

        request : bytes — payload CAN datos (sin ID CAN)
                  Ej: [02 01 0C 00 00 00 00 00] → len=2, svc=0x01, pid=0x0C

        Retorna bytes de respuesta o None si no se soporta.
        """
        if len(request) < 3:
            return None
        # length = request[0]  (bytes adicionales)
        service = request[1]
        pid = request[2]

        if service == 0x01:
            return self._service01(pid)
        elif service == 0x03:
            return self._service03_dtcs()
        elif service == 0x04:
            return self._service04_clear()
        elif service == 0x09:
            return self._service09(pid)
        return None

    def _service01(self, pid: int) -> Optional[bytes]:
        """Servicio 01: Current Data."""
        s = self.ecu.sensors

        # PIDs de capacidades (múltiplos de 0x20)
        if pid == 0x00:
            # Bitmap: indica PIDs 01-20 soportados
            return self._response(0x41, pid, OBD_SUPPORTED_PIDS_BITMAP)
        if pid == 0x20:
            return self._response(0x41, pid, bytes([0x80, 0x00, 0x00, 0x00]))
        if pid == 0x40:
            return self._response(0x41, pid, bytes([0x40, 0x00, 0x00, 0x00]))

        # ── Estado monitors (PID 0x01) ────────────────────────────────────────
        if pid == 0x01:
            dtc_count = len(self.dtc.get_active_dtcs()) if self.dtc else 0
            mil_on = 0x80 if dtc_count > 0 else 0x00
            byte1 = mil_on | (dtc_count & 0x7F)
            return self._response(0x41, pid, bytes([byte1, 0x07, 0xFF, 0x00]))

        # ── Carga calculada motor (PID 0x04) ──────────────────────────────────
        if pid == 0x04:
            raw = int(s.engine_load_pct * 255.0 / 100.0)
            return self._response(0x41, pid, bytes([raw & 0xFF]))

        # ── Temperatura refrigerante (PID 0x05) ──────────────────────────────
        if pid == 0x05:
            raw = int(s.coolant_temp_c + 40.0)
            raw = max(0, min(255, raw))
            return self._response(0x41, pid, bytes([raw]))

        # ── Presión colector MAP (PID 0x0B) ──────────────────────────────────
        if pid == 0x0B:
            raw = int(s.map_kpa)
            raw = max(0, min(255, raw))
            return self._response(0x41, pid, bytes([raw]))

        # ── RPM motor (PID 0x0C) ──────────────────────────────────────────────
        if pid == 0x0C:
            raw = int(s.rpm * 4.0)
            raw = max(0, min(65535, raw))
            hi = (raw >> 8) & 0xFF
            lo = raw & 0xFF
            return self._response(0x41, pid, bytes([hi, lo]))

        # ── Velocidad vehículo (PID 0x0D) ────────────────────────────────────
        if pid == 0x0D:
            raw = int(s.vehicle_speed_kmh)
            raw = max(0, min(255, raw))
            return self._response(0x41, pid, bytes([raw]))

        # ── Temperatura aire admisión IAT (PID 0x0F) ─────────────────────────
        if pid == 0x0F:
            raw = int(s.intake_air_temp_c + 40.0)
            raw = max(0, min(255, raw))
            return self._response(0x41, pid, bytes([raw]))

        # ── Flujo MAF (PID 0x10) ─────────────────────────────────────────────
        if pid == 0x10:
            raw = int(s.maf_gs * 100.0)
            raw = max(0, min(65535, raw))
            hi = (raw >> 8) & 0xFF
            lo = raw & 0xFF
            return self._response(0x41, pid, bytes([hi, lo]))

        # ── Posición acelerador (PID 0x11) ───────────────────────────────────
        if pid == 0x11:
            raw = int(s.throttle_pct * 255.0 / 100.0)
            raw = max(0, min(255, raw))
            return self._response(0x41, pid, bytes([raw]))

        # ── Presión barométrica (PID 0x33) ───────────────────────────────────
        if pid == 0x33:
            raw = int(s.baro_kpa)
            raw = max(0, min(255, raw))
            return self._response(0x41, pid, bytes([raw]))

        # ── Tiempo motor encendido (PID 0x1F) ────────────────────────────────
        if pid == 0x1F:
            raw = int(s.engine_run_time_s)
            raw = max(0, min(65535, raw))
            hi = (raw >> 8) & 0xFF
            lo = raw & 0xFF
            return self._response(0x41, pid, bytes([hi, lo]))

        return None

    def _service03_dtcs(self) -> bytes:
        """Servicio 03: Mostrar DTCs almacenados."""
        if self.dtc:
            return bytes([0x03]) + self.dtc.encode_obd_response()
        return bytes([0x43, 0x00])  # sin DTCs

    def _service04_clear(self) -> bytes:
        """Servicio 04: Borrar DTCs."""
        if self.dtc:
            self.dtc.clear_all_dtcs()
        return bytes([0x44])

    def _service09(self, pid: int) -> Optional[bytes]:
        """Servicio 09: Información del vehículo."""
        if pid == 0x02:  # VIN
            vin_bytes = "TESTVIN0123456789".encode("ascii")
            return self._response(0x49, pid, vin_bytes)
        if pid == 0x0A:  # ECU Name
            name_bytes = "SCANER_SOLER_ECU    ".encode("ascii")
            return self._response(0x49, pid, name_bytes)
        return None

    @staticmethod
    def _response(service_response: int, pid: int, data: bytes) -> bytes:
        """
        Construye respuesta OBD completa.
        Formato: [len] [service+0x40] [pid] [datos...]
        De shchers: responde en 0x7E8 con offset +0x40 al servicio.
        """
        payload = bytes([service_response, pid]) + data
        return bytes([len(payload)]) + payload


# =============================================================================
# SECCIÓN 8: FreezeFrameStore — almacenamiento de freeze frames
# Lógica propia basada en el concepto de freeze frame OBD-II (SAE J1979 §5.4)
# Activado cuando un DTC se confirma (de la arquitectura de DTCManager arriba)
# =============================================================================

class FreezeFrameStore:
    """
    Almacena y recupera freeze frames asociados a DTCs.

    Un freeze frame = snapshot completo de todos los sensores en el instante
    exacto en que se activó un DTC. Permite diagnóstico post-fallo sin que
    el mecánico tenga que reproducir la condición.

    En OBD Servicio 02: "Show Freeze Frame Data"
    """

    def __init__(self, max_frames: int = 10):
        self._frames: Dict[str, SensorSnapshot] = {}
        self._max = max_frames

    def store(self, dtc_code: str, snapshot: SensorSnapshot) -> None:
        """Almacena freeze frame para un DTC."""
        if len(self._frames) >= self._max:
            # Elimina el más antiguo
            oldest = min(self._frames.items(), key=lambda x: x[1].timestamp)
            del self._frames[oldest[0]]
        self._frames[dtc_code] = snapshot

    def get(self, dtc_code: str) -> Optional[SensorSnapshot]:
        """Recupera freeze frame de un DTC."""
        return self._frames.get(dtc_code)

    def get_all(self) -> Dict[str, SensorSnapshot]:
        return dict(self._frames)

    def encode_obd_freeze_frame(self, dtc_code: str, pid: int) -> Optional[bytes]:
        """
        Codifica un PID del freeze frame para respuesta OBD Servicio 02.
        Formato: [0x42] [pid] [dtc_hi] [dtc_lo] [valor...]
        """
        frame = self.get(dtc_code)
        if frame is None:
            return None

        # Reutiliza el mismo encoding que OBDPIDResponder._service01
        # pero desde el snapshot congelado
        ecu_mock = _SnapshotECU(frame)
        responder = OBDPIDResponder(ecu_mock)
        response = responder._service01(pid)
        if response is None:
            return None

        # Prepara DTC como 2 bytes
        temp_dtc = DTCEntry(code=dtc_code, description="")
        dtc_bytes = temp_dtc.encode_obd()
        # Servicio 02 response: [len] [0x42] [pid] [dtc_hi] [dtc_lo] [valores]
        return bytes([0x42, pid]) + dtc_bytes + response[3:]

    def clear(self, dtc_code: Optional[str] = None) -> None:
        if dtc_code:
            self._frames.pop(dtc_code, None)
        else:
            self._frames.clear()


class _SnapshotECU:
    """Adaptador mínimo para usar OBDPIDResponder con un snapshot congelado."""
    def __init__(self, snapshot: SensorSnapshot):
        self.sensors = snapshot
    def tick(self, *args, **kwargs) -> SensorSnapshot:
        return self.sensors


# =============================================================================
# SECCIÓN 9: ECUSimulatorCore — integración de todos los módulos
# Punto de entrada único para el sandbox MiroFish
# =============================================================================

class ECUSimulatorCore:
    """
    Integra todos los módulos del grupo 4 en una sola interfaz.

    Uso desde el sandbox:
        core = ECUSimulatorCore(initial_state='idle', vin='VF1ABC123')
        core.tick(dt=1.0)
        response = core.uds.process(bytes([0x22, 0xF4, 0x01]))
        response = core.obd.process(bytes([0x02, 0x01, 0x0C, 0x00]))
        core.dtc_mgr.inject_dtc('P0118')
        active = core.dtc_mgr.get_active_dtcs()
    """

    def __init__(
        self,
        initial_state: str = "cold_start",
        vin: str = "TESTVIN0123456789",
        ecu_name: str = "SCANER_SOLER_ECU",
        initial_dtcs: Optional[List[str]] = None,
        coolant_start_c: float = 20.0,
    ):
        self.ecu = ECUStateMachine(
            initial_state=initial_state,
            coolant_start_c=coolant_start_c,
        )
        self.dtc_mgr = DTCManager(self.ecu, initial_dtcs=initial_dtcs)
        self.freeze_store = FreezeFrameStore()
        self.uds = UDSResponder(self.ecu, self.dtc_mgr, vin=vin, ecu_name=ecu_name)
        self.obd = OBDPIDResponder(self.ecu, self.dtc_mgr)
        self._vin = vin

    def tick(self, dt: float = 1.0, throttle: Optional[float] = None) -> SensorSnapshot:
        """
        Avanza la simulación dt segundos.
        Evalúa DTCs y guarda freeze frames si se activan nuevos.
        """
        snap = self.ecu.tick(dt=dt, throttle_override=throttle)
        newly_triggered = self.dtc_mgr.evaluate()
        # Guarda freeze frames para DTCs recién activados
        for code in newly_triggered:
            entry = self.dtc_mgr._dtcs.get(code)
            if entry and entry.freeze_frame:
                self.freeze_store.store(code, entry.freeze_frame)
        return snap

    def run_scenario(
        self,
        duration_s: float = 60.0,
        dt: float = 1.0,
        throttle_profile: Optional[List[Tuple[float, float]]] = None,
    ) -> List[SensorSnapshot]:
        """
        Ejecuta un escenario completo y retorna historial de snapshots.

        throttle_profile : lista de (tiempo_s, throttle_pct) — interpolado.
        Ejemplo: [(0, 0), (10, 5), (20, 30), (40, 80), (60, 5)]
        """
        history = []
        t = 0.0
        while t <= duration_s:
            thr = None
            if throttle_profile:
                thr = self._interpolate_throttle(t, throttle_profile)
            snap = self.tick(dt=dt, throttle=thr)
            history.append(snap)
            t += dt
        return history

    @staticmethod
    def _interpolate_throttle(t: float,
                               profile: List[Tuple[float, float]]) -> float:
        """Interpola linealmente el perfil de acelerador en el instante t."""
        if not profile:
            return 0.0
        if t <= profile[0][0]:
            return profile[0][1]
        if t >= profile[-1][0]:
            return profile[-1][1]
        for i in range(len(profile) - 1):
            t0, v0 = profile[i]
            t1, v1 = profile[i + 1]
            if t0 <= t <= t1:
                alpha = (t - t0) / (t1 - t0)
                return v0 + alpha * (v1 - v0)
        return 0.0

    def get_full_status(self) -> Dict[str, Any]:
        """Retorna estado completo del simulador como dict (para GUI/API)."""
        active_dtcs = self.dtc_mgr.get_active_dtcs()
        return {
            "ecu_state": self.ecu.state.value,
            "run_time_s": round(self.ecu.run_time_s, 1),
            "sensors": self.ecu.sensors.to_obd_dict(),
            "active_dtcs": [d.code for d in active_dtcs],
            "confirmed_dtcs": [d.code for d in self.dtc_mgr.get_confirmed_dtcs()],
            "security_unlocked": self.uds.security.is_unlocked(),
            "freeze_frames": list(self.freeze_store.get_all().keys()),
        }
