"""
Charging Session Monitor — modela el ciclo de vida de una sesión de carga.

Estándares cubiertos:
  - ISO 15118-2/-20 (CCS Combo — vehículo-cargador, Plug&Charge)
  - DIN 70121 (DC legacy, aún presente en BMW/VW pre-2019)
  - OCPP 1.6 / 2.0.1 (charger-to-CSMS — para logging externo)
  - CHAdeMO 1.x / 2.0 (protocolo japonés, Nissan/Mitsubishi)
  - AC Mode 2 / Mode 3 (IEC 61851-1)

Refs:
  - juherr/awesome-ev-charging (protocolo map)
  - uhi22/pyPLC (ISO 15118 Python impl.)
  - mobilityhouse/ocpp (OCPP Python lib.)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ChargingState(Enum):
    # Vehículo desconectado
    DISCONNECTED        = "DISCONNECTED"
    # Cable conectado, carga no iniciada
    CONNECTED           = "CONNECTED"
    # Negociación de protocolo (ISO 15118 SDP / DIN 70121)
    PROTOCOL_HANDSHAKE  = "PROTOCOL_HANDSHAKE"
    # Autenticación / Plug&Charge (ISO 15118-20)
    AUTHENTICATING      = "AUTHENTICATING"
    # Pre-carga DC (contactor cerrado, potencia subiendo)
    PRECHARGING         = "PRECHARGING"
    # Carga activa
    CHARGING            = "CHARGING"
    # Suspendida por EV (BMS lleno o pausa)
    SUSPENDED_EV        = "SUSPENDED_EV"
    # Suspendida por EVSE (fallo de red, tarifa)
    SUSPENDED_EVSE      = "SUSPENDED_EVSE"
    # Terminando: contactor abriendo
    FINISHING           = "FINISHING"
    # Carga completada (SOC objetivo alcanzado)
    FINISHED            = "FINISHED"
    # Error durante la sesión
    FAULTED             = "FAULTED"


class ChargingConnectorType(Enum):
    AC_TYPE1        = "AC_J1772"        # SAE J1772 (EEUU/Japón)
    AC_TYPE2        = "AC_IEC62196"     # IEC 62196-2 (Europa)
    DC_CCS1         = "DC_CCS_SAE"      # CCS Combo 1 (EEUU/Corea)
    DC_CCS2         = "DC_CCS_IEC"      # CCS Combo 2 (Europa)
    DC_CHADEMO      = "DC_CHADEMO"      # CHAdeMO (Japón)
    DC_TESLA_NACS   = "DC_NACS"         # NACS / SAE J3400 (Tesla + adoptado 2023)
    AC_DC_MCS       = "DC_MCS"          # Megawatt Charging (ISO 15118-20, >1 MW)
    INDUCTIVE       = "INDUCTIVE"       # WPT / qi estándar vehicular


class ChargingProtocol(Enum):
    IEC61851        = "IEC_61851"       # AC Mode 2/3 — CP signal
    ISO15118_2      = "ISO_15118_2"     # DC/AC con PLC (SLAC/V2G)
    ISO15118_20     = "ISO_15118_20"    # Siguiente generación (Plug&Charge, BPT)
    DIN70121        = "DIN_70121"       # Legacy DC (BMW/VW pre-2019)
    CHADEMO_1       = "CHADEMO_1X"      # CHAdeMO 1.x
    CHADEMO_2       = "CHADEMO_2X"      # CHAdeMO 2.0 (V2G)
    NACS            = "NACS_J3400"      # Tesla NACS adoptado por SAE


@dataclass
class ChargingSession:
    """
    Representa una sesión de carga completa del vehículo.

    Se crea al detectar un evento de conexión y se cierra al desconectar
    o al completarse la carga.  Puede ser consultada en tiempo real
    para mostrar progreso y estadísticas.
    """
    session_id:      str
    brand:           str
    connector:       ChargingConnectorType  = ChargingConnectorType.DC_CCS2
    protocol:        ChargingProtocol       = ChargingProtocol.ISO15118_2
    state:           ChargingState          = ChargingState.DISCONNECTED

    # Tiempos
    start_time:      Optional[datetime]     = None
    end_time:        Optional[datetime]     = None
    last_update:     datetime               = field(default_factory=datetime.now)

    # Parámetros de energía en tiempo real
    soc_start_pct:   Optional[float]        = None
    soc_current_pct: Optional[float]        = None
    soc_target_pct:  float                  = 80.0   # objetivo por defecto

    energy_kwh:      float                  = 0.0    # energía entregada esta sesión
    power_kw:        float                  = 0.0    # potencia instantánea
    power_kw_max:    float                  = 0.0    # pico de la sesión

    voltage_v:       Optional[float]        = None
    current_a:       Optional[float]        = None

    # Límites negociados (ISO 15118 / DIN 70121)
    max_voltage_v:   Optional[float]        = None   # límite del vehículo (BMS)
    max_current_a:   Optional[float]        = None
    max_power_kw:    Optional[float]        = None   # límite del cargador

    # Historial de potencia (para curva de carga)
    power_history:   list[tuple[float, float]] = field(default_factory=list)
    # [(segundos_desde_inicio, kW), ...]

    # Plug&Charge (ISO 15118-20)
    pnc_enabled:     bool                   = False
    pnc_contract_id: Optional[str]          = None

    # Errores y eventos
    fault_codes:     list[str]              = field(default_factory=list)
    events:          list[str]              = field(default_factory=list)

    # ── API pública ──────────────────────────────────────────────────────────

    def connect(self, connector: ChargingConnectorType,
                soc_pct: Optional[float] = None) -> None:
        self.connector = connector
        self.soc_start_pct = soc_pct
        self.soc_current_pct = soc_pct
        self.state = ChargingState.CONNECTED
        self._log(f"Conectado: {connector.value}")

    def start_handshake(self, protocol: ChargingProtocol) -> None:
        self.protocol = protocol
        self.state = ChargingState.PROTOCOL_HANDSHAKE
        self._log(f"Handshake: {protocol.value}")

    def start_auth(self, contract_id: Optional[str] = None) -> None:
        self.state = ChargingState.AUTHENTICATING
        if contract_id:
            self.pnc_enabled = True
            self.pnc_contract_id = contract_id
            self._log(f"Plug&Charge: {contract_id}")
        else:
            self._log("Autenticación: RFID/App")

    def start_charging(self, max_v: float, max_a: float) -> None:
        self.max_voltage_v = max_v
        self.max_current_a = max_a
        self.max_power_kw = round(max_v * max_a / 1000, 2)
        self.start_time = datetime.now()
        self.state = ChargingState.CHARGING
        self._log(f"Carga iniciada: máx {max_v}V / {max_a}A / {self.max_power_kw} kW")

    def update(self, voltage_v: float, current_a: float,
               soc_pct: float, energy_kwh: Optional[float] = None) -> None:
        """Actualiza telemetría en tiempo real (llamar cada ~1s)."""
        dt = (datetime.now() - self.last_update).total_seconds()
        self.voltage_v = voltage_v
        self.current_a = current_a
        self.soc_current_pct = soc_pct

        self.power_kw = round(voltage_v * current_a / 1000, 2)
        if self.power_kw > self.power_kw_max:
            self.power_kw_max = self.power_kw

        if energy_kwh is not None:
            self.energy_kwh = energy_kwh
        else:
            # Integración trapezoidal simple
            self.energy_kwh = round(self.energy_kwh + self.power_kw * dt / 3600, 4)

        if self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            self.power_history.append((round(elapsed, 1), self.power_kw))

        self.last_update = datetime.now()

        # Transición automática: SOC objetivo alcanzado
        if soc_pct >= self.soc_target_pct and self.state == ChargingState.CHARGING:
            self.state = ChargingState.FINISHING
            self._log(f"Objetivo SOC {self.soc_target_pct}% alcanzado → terminando")

    def stop(self, reason: str = "normal") -> None:
        self.end_time = datetime.now()
        self.state = ChargingState.FINISHED
        self._log(f"Sesión terminada: {reason}")

    def fault(self, code: str, description: str) -> None:
        self.fault_codes.append(code)
        self.state = ChargingState.FAULTED
        self._log(f"FALLO {code}: {description}")

    def suspend_ev(self) -> None:
        self.state = ChargingState.SUSPENDED_EV
        self._log("Suspendida por EV (BMS)")

    def suspend_evse(self) -> None:
        self.state = ChargingState.SUSPENDED_EVSE
        self._log("Suspendida por EVSE (cargador)")

    # ── Consultas ────────────────────────────────────────────────────────────

    @property
    def duration_min(self) -> Optional[float]:
        if self.start_time is None:
            return None
        end = self.end_time or datetime.now()
        return round((end - self.start_time).total_seconds() / 60, 1)

    @property
    def soc_added_pct(self) -> Optional[float]:
        if self.soc_start_pct is None or self.soc_current_pct is None:
            return None
        return round(self.soc_current_pct - self.soc_start_pct, 1)

    @property
    def avg_power_kw(self) -> Optional[float]:
        if not self.power_history:
            return None
        total = sum(p for _, p in self.power_history)
        return round(total / len(self.power_history), 2)

    @property
    def is_dc(self) -> bool:
        return self.connector in (
            ChargingConnectorType.DC_CCS1,
            ChargingConnectorType.DC_CCS2,
            ChargingConnectorType.DC_CHADEMO,
            ChargingConnectorType.DC_TESLA_NACS,
            ChargingConnectorType.AC_DC_MCS,
        )

    @property
    def is_active(self) -> bool:
        return self.state in (
            ChargingState.PRECHARGING,
            ChargingState.CHARGING,
            ChargingState.SUSPENDED_EV,
            ChargingState.SUSPENDED_EVSE,
        )

    @property
    def protocol_version(self) -> str:
        return self.protocol.value

    def summary(self) -> str:
        lines = [
            f"Sesión {self.session_id} — {self.brand}",
            f"  Estado : {self.state.value}",
            f"  Conector: {self.connector.value}  Protocolo: {self.protocol.value}",
            f"  SOC    : {self.soc_start_pct}% → {self.soc_current_pct}%"
            f"  (+{self.soc_added_pct}%)",
            f"  Energía: {self.energy_kwh} kWh   Duración: {self.duration_min} min",
            f"  Potencia: {self.power_kw} kW (pico {self.power_kw_max} kW, "
            f"media {self.avg_power_kw} kW)",
            f"  Voltaje: {self.voltage_v} V   Corriente: {self.current_a} A",
        ]
        if self.pnc_enabled:
            lines.append(f"  Plug&Charge: {self.pnc_contract_id}")
        if self.fault_codes:
            lines.append(f"  Fallos: {', '.join(self.fault_codes)}")
        return "\n".join(lines)

    def _log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.events.append(f"[{ts}] {msg}")
