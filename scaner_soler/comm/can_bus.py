"""
can_bus.py — Módulo CAN bus / DBC para Scaner Soler.

Migrado y limpiado desde extracted_group5.py (Grupo 5 de revisión de repos).

Repos de referencia:
  - kostaszaf/can-gateway-sniffer  (91★, C)   — CAN sniffer VW/Audi
  - eerimoq/cantools               (2.3k★)     — DBC parsing + CAN decode/encode
  - python-can                     (1.6k★)     — interfaz CAN bus
  - PowerBroker2/ArduHUD           (52★)       — HUD ELM327
  - KoffeinFlummi/rustbucket       (60★, Rust) — OBD2/CAN/KWP K-line

Clases exportadas:
  CANFrame, CANFrameDecoder
  DBCSignal, DBCMessage, DBCParser
  AnomalyEvent, OBDSensorAnomalyDetector
  HUDData, HUDDataCalculator

Funciones exportadas:
  parse_can_log(filepath) -> list[CANFrame]
"""

from __future__ import annotations

import re
import struct
import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTES CAN / OBD
# ═══════════════════════════════════════════════════════════════════════════════

# Tabla de PIDs propietarios VW/Audi conocidos del can-gateway-sniffer
VW_AUDI_CAN_PIDS: dict[int, str] = {
    0x5BF:      "steering_wheel_buttons",
    0x17333310: "virtual_cockpit_display",
    0x0C6:      "engine_rpm_raw",
    0x280:      "engine_data_1",
    0x288:      "transmission_data",
    0x320:      "abs_wheel_speeds",
    0x3D0:      "vehicle_speed_ext",
    0x470:      "instrument_cluster",
    0x540:      "comfort_can_body",
    0x569:      "ac_climate_control",
    0x621:      "gateway_diag",
}

# IDs estándar OBD-II sobre CAN (SAE J1939 / ISO 15765)
OBD_CAN_REQUEST_ID   = 0x7DF   # broadcast funcional
OBD_CAN_RESPONSE_BASE = 0x7E8  # ECU 1 responde en 0x7E8..0x7EF


# ═══════════════════════════════════════════════════════════════════════════════
# 1. CAN FRAME
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CANFrame:
    """Trama CAN decodificada.

    Campos:
        arbitration_id: identificador de mensaje (11-bit o 29-bit)
        is_extended_id: True si es ID de 29 bits (CAN extendido)
        dlc:            Data Length Code (0–8 bytes)
        data:           payload de hasta 8 bytes
        timestamp:      tiempo de captura en segundos (opcional)
        channel:        nombre del bus CAN de origen (opcional)
    """
    arbitration_id: int
    is_extended_id: bool
    dlc: int
    data: bytes
    timestamp: float = 0.0
    channel: str = ""

    @property
    def id_hex(self) -> str:
        """ID en hexadecimal: 3 dígitos para 11-bit, 8 para 29-bit."""
        if self.is_extended_id:
            return f"{self.arbitration_id:08X}"
        return f"{self.arbitration_id:03X}"

    @property
    def data_hex(self) -> str:
        """Payload en hexadecimal separado por espacios: 'DE AD BE EF'."""
        return " ".join(f"{b:02X}" for b in self.data)

    @property
    def is_obd_request(self) -> bool:
        return self.arbitration_id == OBD_CAN_REQUEST_ID

    @property
    def is_obd_response(self) -> bool:
        return OBD_CAN_RESPONSE_BASE <= self.arbitration_id <= OBD_CAN_RESPONSE_BASE + 7

    def get_byte(self, index: int, default: int = 0) -> int:
        """Retorna el byte en posición *index* o *default* si no existe."""
        return self.data[index] if index < len(self.data) else default

    def __repr__(self) -> str:
        ext = "X" if self.is_extended_id else " "
        return (
            f"CAN[{ext}] ID={self.id_hex} DLC={self.dlc} "
            f"Data=[{self.data_hex}] t={self.timestamp:.3f}s"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. CAN FRAME DECODER
# ═══════════════════════════════════════════════════════════════════════════════

class CANFrameDecoder:
    """Decodifica tramas CAN desde múltiples formatos de texto/bytes.

    Formatos soportados:
      - candump log:   '  vcan0  7E8   [8]  03 41 0C 1A 00 00 00 00'
      - SavvyCAN CSV:  '7E8,8,03 41 0C 1A 00 00 00 00,0.000'
      - SocketCAN hex: '7E8#03410C1A00000000'
      - raw bytes:     bytes de 13 octetos (ID 4B + DLC 1B + Data 8B)
    """

    @staticmethod
    def from_candump_line(line: str, channel: str = "") -> Optional[CANFrame]:
        """Parsea una línea de candump:
           '  vcan0  7E8   [8]  03 41 0C 1A 00 00 00 00'
        """
        line = line.strip()
        if not line or line.startswith("("):
            return None
        m = re.match(
            r"(?:\([\d.]+\)\s+)?(\w+)\s+([0-9A-Fa-f]+)\s+\[(\d+)\]\s+([\dA-Fa-f ]*)",
            line
        )
        if not m:
            return None
        ch = channel or m.group(1)
        arb_id = int(m.group(2), 16)
        dlc = int(m.group(3))
        hex_bytes = m.group(4).strip().split()
        data = bytes(int(b, 16) for b in hex_bytes if b)
        is_ext = arb_id > 0x7FF
        return CANFrame(
            arbitration_id=arb_id,
            is_extended_id=is_ext,
            dlc=dlc,
            data=data[:dlc],
            channel=ch,
        )

    @staticmethod
    def from_socketcan_string(s: str, channel: str = "") -> Optional[CANFrame]:
        """Parsea formato SocketCAN: '7E8#0341' o '18FEF100#0000000000000000'."""
        s = s.strip()
        if "#" not in s:
            return None
        id_part, data_part = s.split("#", 1)
        id_part = id_part.rstrip("RBE").strip()
        arb_id = int(id_part, 16)
        is_ext = len(id_part) > 3 or arb_id > 0x7FF
        data = bytes.fromhex(data_part)
        return CANFrame(
            arbitration_id=arb_id,
            is_extended_id=is_ext,
            dlc=len(data),
            data=data,
            channel=channel,
        )

    @staticmethod
    def from_raw_bytes(raw: bytes, channel: str = "") -> Optional[CANFrame]:
        """Parsea trama binaria compacta: 4B ID | 1B DLC | hasta 8B datos."""
        if len(raw) < 5:
            return None
        arb_id = struct.unpack(">I", raw[:4])[0]
        is_ext  = bool(arb_id & 0x80000000)
        arb_id &= 0x1FFFFFFF
        dlc = raw[4] & 0x0F
        data = raw[5:5 + dlc]
        return CANFrame(
            arbitration_id=arb_id,
            is_extended_id=is_ext,
            dlc=dlc,
            data=data,
            channel=channel,
        )

    @staticmethod
    def decode_obd_response(frame: CANFrame) -> Optional[dict]:
        """Extrae modo + PID + valor crudo de una respuesta OBD-II.

        Retorna {mode, pid, raw_bytes, service_name, ecu_id} o None.
        """
        if not frame.is_obd_response:
            return None
        if len(frame.data) < 3:
            return None
        mode = frame.data[1]
        pid  = frame.data[2]
        payload = list(frame.data[3:frame.dlc])
        service_map = {
            0x41: "Mode01_CurrentData",
            0x42: "Mode02_FreezeFrame",
            0x43: "Mode03_StoredDTCs",
            0x44: "Mode04_ClearDTCs",
            0x47: "Mode07_PendingDTCs",
            0x49: "Mode09_VehicleInfo",
            0x4A: "Mode0A_PermanentDTCs",
        }
        return {
            "mode": mode,
            "pid": pid,
            "raw_bytes": payload,
            "service_name": service_map.get(mode, f"Mode_{mode:02X}"),
            "ecu_id": frame.arbitration_id - OBD_CAN_RESPONSE_BASE,
        }

    @staticmethod
    def identify_vw_audi_signal(frame: CANFrame) -> str:
        """Identifica señales VW/Audi/Skoda conocidas del can-gateway-sniffer."""
        return VW_AUDI_CAN_PIDS.get(frame.arbitration_id, "unknown_signal")

    @staticmethod
    def extract_signal_bits(
        data: bytes,
        start_bit: int,
        bit_length: int,
        byte_order: str = "little_endian",
        is_signed: bool = False,
    ) -> int:
        """Extrae una señal de *bit_length* bits de *data* con posición *start_bit*.

        byte_order: 'little_endian' (Intel) o 'big_endian' (Motorola).
        Basado en el formato de señales del estándar DBC/cantools.
        """
        if byte_order == "little_endian":
            raw = 0
            for i in range(bit_length):
                bit_pos = start_bit + i
                byte_idx = bit_pos // 8
                bit_idx  = bit_pos %  8
                if byte_idx < len(data) and (data[byte_idx] >> bit_idx) & 1:
                    raw |= (1 << i)
        else:
            raw = 0
            start_byte = start_bit // 8
            start_bit_in_byte = start_bit % 8
            bit_pos = start_byte * 8 + (7 - start_bit_in_byte)
            for i in range(bit_length):
                cur_byte = bit_pos // 8
                cur_bit  = bit_pos %  8
                if cur_byte < len(data) and (data[cur_byte] >> cur_bit) & 1:
                    raw |= (1 << (bit_length - 1 - i))
                bit_pos += 1
                if (bit_pos % 8) == 0:
                    bit_pos += 8

        if is_signed and (raw >> (bit_length - 1)) & 1:
            raw -= (1 << bit_length)
        return raw


# ═══════════════════════════════════════════════════════════════════════════════
# 3. DBC SIGNAL / MESSAGE / PARSER
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DBCSignal:
    """Definición de señal CAN leída de un archivo .dbc."""
    name: str
    start_bit: int
    length: int
    byte_order: str = "little_endian"
    is_signed: bool = False
    scale: float = 1.0
    offset: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    unit: str = ""
    receivers: list[str] = field(default_factory=list)

    def decode(self, data: bytes) -> float:
        """Convierte bytes de trama CAN al valor físico de esta señal."""
        raw = CANFrameDecoder.extract_signal_bits(
            data, self.start_bit, self.length, self.byte_order, self.is_signed
        )
        return raw * self.scale + self.offset

    def encode(self, physical_value: float) -> int:
        """Convierte un valor físico al valor crudo (raw) entero."""
        raw = (physical_value - self.offset) / self.scale
        raw_int = int(round(raw))
        if self.is_signed:
            lo = -(1 << (self.length - 1))
            hi = (1 << (self.length - 1)) - 1
        else:
            lo, hi = 0, (1 << self.length) - 1
        return max(lo, min(hi, raw_int))


@dataclass
class DBCMessage:
    """Mensaje CAN definido en un archivo .dbc."""
    message_id: int
    name: str
    dlc: int
    transmitter: str = ""
    signals: dict[str, DBCSignal] = field(default_factory=dict)

    def decode_frame(self, frame: CANFrame) -> dict[str, float]:
        """Decodifica todos los signals del mensaje dado un CANFrame."""
        if frame.arbitration_id != (self.message_id & 0x1FFFFFFF):
            raise ValueError(
                f"ID mismatch: frame {frame.id_hex} != "
                f"message {self.message_id:08X}"
            )
        return {name: sig.decode(frame.data) for name, sig in self.signals.items()}


class DBCParser:
    """Parser básico de archivos .dbc (formato Vector/PEAK).

    Soporta: declaraciones BO_ (mensajes), SG_ (señales), comentarios //.
    Encoding Intel (1) y Motorola (0).
    """

    _MSG_RE = re.compile(r"^BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)\s+(\w+)")
    _SIG_RE = re.compile(
        r"^\s+SG_\s+(\w+)\s*:\s*"
        r"(\d+)\|(\d+)@([01])([+-])\s*"
        r"\(([-\d.eE+]+),([-\d.eE+]+)\)\s*"
        r"\[([-\d.eE+]*)\|([-\d.eE+]*)\]\s*"
        r'"([^"]*)"\s*(.*)'
    )

    @classmethod
    def parse_file(cls, filepath: str) -> dict[int, DBCMessage]:
        """Lee un archivo .dbc y retorna dict {message_id: DBCMessage}."""
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
        return cls.parse_string(content)

    @classmethod
    def parse_string(cls, content: str) -> dict[int, DBCMessage]:
        """Parsea el contenido de un .dbc como string."""
        messages: dict[int, DBCMessage] = {}
        current_msg: Optional[DBCMessage] = None

        for raw_line in content.splitlines():
            line = raw_line.split("//")[0]

            m = cls._MSG_RE.match(line)
            if m:
                msg_id = int(m.group(1))
                current_msg = DBCMessage(
                    message_id=msg_id,
                    name=m.group(2),
                    dlc=int(m.group(3)),
                    transmitter=m.group(4),
                )
                messages[msg_id & 0x1FFFFFFF] = current_msg
                continue

            if current_msg is not None:
                s = cls._SIG_RE.match(line)
                if s:
                    byte_order = "little_endian" if s.group(4) == "1" else "big_endian"
                    is_signed  = s.group(5) == "-"
                    min_str, max_str = s.group(8), s.group(9)
                    receivers = [r.strip() for r in s.group(11).split(",") if r.strip()]
                    sig = DBCSignal(
                        name=s.group(1),
                        start_bit=int(s.group(2)),
                        length=int(s.group(3)),
                        byte_order=byte_order,
                        is_signed=is_signed,
                        scale=float(s.group(6)),
                        offset=float(s.group(7)),
                        min_val=float(min_str) if min_str else 0.0,
                        max_val=float(max_str) if max_str else 0.0,
                        unit=s.group(10),
                        receivers=receivers,
                    )
                    current_msg.signals[sig.name] = sig

        return messages

    @staticmethod
    def decode_frame_with_db(
        frame: CANFrame,
        db: dict[int, DBCMessage],
    ) -> Optional[dict[str, float]]:
        """Decodifica un CANFrame usando la base de datos DBC cargada.

        Retorna {signal_name: physical_value} o None si el ID no está en la DB.
        """
        msg = db.get(frame.arbitration_id)
        if msg is None:
            return None
        return msg.decode_frame(frame)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. OBD SENSOR ANOMALY DETECTOR
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AnomalyEvent:
    sensor_name: str
    value: float
    unit: str
    anomaly_type: str   # 'zscore' | 'iqr' | 'spike' | 'freeze' | 'range'
    severity: str       # 'critical' | 'warning' | 'info'
    detail: str

    def __str__(self) -> str:
        return (
            f"[{self.severity.upper()}] {self.sensor_name}={self.value} {self.unit} "
            f"— {self.anomaly_type}: {self.detail}"
        )


# Rangos normales de operación por sensor (nombre → (lo, hi))
_SENSOR_NORMAL_RANGES: dict[str, tuple[float, float]] = {
    "rpm":              (600,   7500),
    "speed":            (0,     250),
    "coolant_temp":     (70,    115),
    "iat":              (-20,   70),
    "ambient_temp":     (-30,   60),
    "maf":              (2,     300),
    "map_kpa":          (20,    250),
    "throttle":         (0,     100),
    "fuel_trim_st_b1":  (-25,   25),
    "fuel_trim_lt_b1":  (-25,   25),
    "fuel_trim_st_b2":  (-25,   25),
    "fuel_trim_lt_b2":  (-25,   25),
    "o2_b1s1_v":        (0.05,  0.95),
    "o2_b1s2_v":        (0.1,   0.9),
    "o2_b2s1_v":        (0.05,  0.95),
    "o2_b2s2_v":        (0.1,   0.9),
    "fuel_pressure":    (200,   700),
    "ignition_advance": (-5,    45),
    "ctrl_voltage":     (11.5,  15.0),
    "engine_load":      (5,     95),
    "abs_load":         (0,     100),
    "fuel_level":       (0,     100),
    "egr_cmd":          (0,     80),
    "oil_temp":         (50,    130),
    "catalyst_temp_b1s1": (200, 900),
    "fuel_rate":        (0,     50),
    "baro_kpa":         (85,    107),
}

# Umbrales de tasa de cambio máxima por segundo (spike detection)
_SENSOR_MAX_ROC: dict[str, float] = {
    "rpm":           1500.0,
    "speed":           40.0,
    "coolant_temp":     5.0,
    "maf":            200.0,
    "throttle":       100.0,
    "fuel_pressure":  300.0,
    "ctrl_voltage":     3.0,
    "oil_temp":         5.0,
}


class OBDSensorAnomalyDetector:
    """Detector de anomalías en tiempo real para sensores OBD-II.

    Uso típico:
        detector = OBDSensorAnomalyDetector(window_size=30)
        events = detector.update({"rpm": 850.0, "coolant_temp": 95.0})
        for ev in events:
            print(ev)
    """

    def __init__(
        self,
        window_size: int = 30,
        zscore_threshold: float = 3.0,
        iqr_factor: float = 2.5,
        freeze_tolerance: float = 0.001,
        freeze_min_samples: int = 10,
    ):
        self.window_size = window_size
        self.zscore_threshold = zscore_threshold
        self.iqr_factor = iqr_factor
        self.freeze_tolerance = freeze_tolerance
        self.freeze_min_samples = freeze_min_samples

        self._windows: dict[str, deque[float]] = {}
        self._last_values: dict[str, float] = {}
        self._sample_count: dict[str, int] = {}

    def _get_window(self, sensor: str) -> deque[float]:
        if sensor not in self._windows:
            self._windows[sensor] = deque(maxlen=self.window_size)
            self._sample_count[sensor] = 0
        return self._windows[sensor]

    def update(
        self,
        sensor_data: dict[str, float | None],
        timestamp: float = 0.0,
        dt: float = 1.0,
    ) -> list[AnomalyEvent]:
        """Procesa una lectura completa de sensores y retorna eventos de anomalía."""
        events: list[AnomalyEvent] = []

        for sensor, value in sensor_data.items():
            if value is None:
                continue
            unit = self._get_unit(sensor)
            window = self._get_window(sensor)
            self._sample_count[sensor] = self._sample_count.get(sensor, 0) + 1
            n = self._sample_count[sensor]

            # 1. Rango estático
            rng = _SENSOR_NORMAL_RANGES.get(sensor)
            if rng and not (rng[0] <= value <= rng[1]):
                sev = "critical" if (value < rng[0] * 0.8 or value > rng[1] * 1.2) else "warning"
                events.append(AnomalyEvent(
                    sensor_name=sensor, value=value, unit=unit,
                    anomaly_type="range", severity=sev,
                    detail=f"fuera del rango normal [{rng[0]}, {rng[1]}] {unit}",
                ))

            # 2. Rate-of-Change (spike)
            if sensor in self._last_values and dt > 0:
                roc = abs(value - self._last_values[sensor]) / dt
                max_roc = _SENSOR_MAX_ROC.get(sensor)
                if max_roc and roc > max_roc:
                    sev = "critical" if roc > max_roc * 2 else "warning"
                    events.append(AnomalyEvent(
                        sensor_name=sensor, value=value, unit=unit,
                        anomaly_type="spike", severity=sev,
                        detail=f"ROC={roc:.1f} {unit}/s (máx. esperado {max_roc} {unit}/s)",
                    ))

            # 3. Z-score (ventana deslizante, mín. 8 muestras)
            if len(window) >= 8:
                try:
                    mu  = statistics.mean(window)
                    sig = statistics.stdev(window)
                    if sig > 1e-9:
                        z = abs(value - mu) / sig
                        if z > self.zscore_threshold:
                            sev = "critical" if z > self.zscore_threshold * 1.5 else "warning"
                            events.append(AnomalyEvent(
                                sensor_name=sensor, value=value, unit=unit,
                                anomaly_type="zscore", severity=sev,
                                detail=f"Z={z:.2f} (umbral={self.zscore_threshold}), μ={mu:.2f} σ={sig:.2f}",
                            ))
                except statistics.StatisticsError:
                    pass

            # 4. IQR outlier
            if len(window) >= 12:
                sorted_w = sorted(window)
                q1 = sorted_w[len(sorted_w) // 4]
                q3 = sorted_w[3 * len(sorted_w) // 4]
                iqr = q3 - q1
                if iqr > 1e-9:
                    lo_fence = q1 - self.iqr_factor * iqr
                    hi_fence = q3 + self.iqr_factor * iqr
                    if not (lo_fence <= value <= hi_fence):
                        events.append(AnomalyEvent(
                            sensor_name=sensor, value=value, unit=unit,
                            anomaly_type="iqr", severity="warning",
                            detail=f"fuera de vallas IQR [{lo_fence:.2f}, {hi_fence:.2f}]",
                        ))

            # 5. Sensor congelado (freeze)
            if n >= self.freeze_min_samples and len(window) >= self.freeze_min_samples:
                variation = max(window) - min(window)
                if variation < self.freeze_tolerance and rng and (rng[1] - rng[0]) > 1:
                    events.append(AnomalyEvent(
                        sensor_name=sensor, value=value, unit=unit,
                        anomaly_type="freeze", severity="warning",
                        detail=f"variación={variation:.4f} en {len(window)} muestras — posible sensor muerto",
                    ))

            window.append(value)
            self._last_values[sensor] = value

        return events

    def reset_sensor(self, sensor: str) -> None:
        self._windows.pop(sensor, None)
        self._last_values.pop(sensor, None)
        self._sample_count.pop(sensor, None)

    def reset_all(self) -> None:
        self._windows.clear()
        self._last_values.clear()
        self._sample_count.clear()

    def get_sensor_stats(self, sensor: str) -> dict:
        window = self._windows.get(sensor)
        if not window or len(window) < 2:
            return {"n": 0}
        vals = list(window)
        return {
            "n": len(vals),
            "mean": round(statistics.mean(vals), 4),
            "stdev": round(statistics.stdev(vals), 4),
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
            "last": round(vals[-1], 4),
        }

    @staticmethod
    def _get_unit(sensor: str) -> str:
        _UNITS = {
            "rpm": "rpm", "speed": "km/h", "coolant_temp": "°C",
            "iat": "°C", "maf": "g/s", "throttle": "%",
            "fuel_trim_st_b1": "%", "fuel_trim_lt_b1": "%",
            "fuel_trim_st_b2": "%", "fuel_trim_lt_b2": "%",
            "o2_b1s1_v": "V", "o2_b1s2_v": "V",
            "o2_b2s1_v": "V", "o2_b2s2_v": "V",
            "fuel_pressure": "kPa", "ctrl_voltage": "V",
            "engine_load": "%", "map_kpa": "kPa",
            "ignition_advance": "°", "oil_temp": "°C",
            "fuel_level": "%", "fuel_rate": "L/h",
            "catalyst_temp_b1s1": "°C", "baro_kpa": "kPa",
            "egr_cmd": "%",
        }
        return _UNITS.get(sensor, "")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. HUD DATA CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════════

_GEAR_RATIOS_6SPD = [3.82, 2.20, 1.52, 1.15, 0.89, 0.73]   # 1ra..6ta
_FINAL_DRIVE_RATIO = 3.74
_TIRE_CIRCUMFERENCE_M = 1.95   # ~205/55R16 aprox.


@dataclass
class HUDData:
    """Datos listos para mostrar en un display HUD."""
    speed_kmh:                Optional[float] = None
    rpm:                      Optional[float] = None
    fuel_consumption_l100km:  Optional[float] = None
    fuel_economy_mpg:         Optional[float] = None
    coolant_temp_c:           Optional[float] = None
    throttle_pct:             Optional[float] = None
    engine_load_pct:          Optional[float] = None
    fuel_level_pct:           Optional[float] = None
    estimated_gear:           Optional[int]   = None
    rpm_bar_pct:              Optional[float] = None
    intake_temp_c:            Optional[float] = None
    maf_gs:                   Optional[float] = None
    fuel_rate_lh:             Optional[float] = None
    oil_temp_c:               Optional[float] = None
    ctrl_voltage_v:           Optional[float] = None
    warning_flags:            list[str]       = field(default_factory=list)


class HUDDataCalculator:
    """Calcula datos HUD a partir de lecturas OBD-II crudas.

    Métodos para consumo instantáneo:
      A) PID fuel_rate (0x5E): L/100km = fuel_rate_lh / speed * 100
      B) MAF (SAE): fuel_rate = MAF / (14.7 * 730 * 0.001)
    """

    REDLINE_RPM: float      = 7000.0
    IDLE_RPM_MIN: float     = 600.0
    OVERHEAT_TEMP_C: float  = 110.0
    LOW_VOLTAGE_V: float    = 11.8
    LOW_FUEL_PCT: float     = 15.0

    def __init__(self, redline_rpm: float = 7000.0):
        self.REDLINE_RPM = redline_rpm

    def calculate(self, pid_values: dict[str, float | None]) -> HUDData:
        """Recibe un dict {nombre_pid: valor} y retorna HUDData."""
        hud = HUDData()
        get = lambda k: pid_values.get(k)

        hud.speed_kmh = get("speed")
        hud.rpm = get("rpm")

        if hud.rpm is not None:
            hud.rpm_bar_pct = min(100.0, hud.rpm / self.REDLINE_RPM * 100.0)

        fuel_rate = get("fuel_rate")
        maf       = get("maf")
        speed     = hud.speed_kmh

        if fuel_rate is not None and speed is not None and speed > 1.0:
            l_per_100 = (fuel_rate / speed) * 100.0
            hud.fuel_consumption_l100km = round(max(0.0, l_per_100), 2)
            hud.fuel_rate_lh = round(fuel_rate, 2)
        elif maf is not None and speed is not None and speed > 1.0:
            estimated_lh = (maf * 3600.0) / (14.7 * 730.0)
            l_per_100 = (estimated_lh / speed) * 100.0
            hud.fuel_consumption_l100km = round(max(0.0, l_per_100), 2)
            hud.fuel_rate_lh = round(estimated_lh, 2)
        elif fuel_rate is not None:
            hud.fuel_rate_lh = round(fuel_rate, 2)

        if hud.fuel_consumption_l100km and hud.fuel_consumption_l100km > 0:
            hud.fuel_economy_mpg = round(282.48 / hud.fuel_consumption_l100km, 1)

        hud.coolant_temp_c  = get("coolant_temp")
        hud.intake_temp_c   = get("iat")
        hud.oil_temp_c      = get("oil_temp")
        hud.maf_gs          = maf
        hud.throttle_pct    = get("throttle")
        hud.engine_load_pct = get("engine_load") or get("abs_load")
        hud.fuel_level_pct  = get("fuel_level")
        hud.ctrl_voltage_v  = get("ctrl_voltage")

        if hud.rpm and hud.speed_kmh and hud.speed_kmh > 5.0 and hud.rpm > 200.0:
            hud.estimated_gear = self._estimate_gear(hud.rpm, hud.speed_kmh)

        hud.warning_flags = self._compute_warnings(hud)
        return hud

    def _estimate_gear(self, rpm: float, speed_kmh: float) -> int:
        wheel_rpm = (speed_kmh * 1000.0) / (60.0 * _TIRE_CIRCUMFERENCE_M)
        if wheel_rpm < 1.0:
            return 1
        theoretical_ratio = rpm / (wheel_rpm * _FINAL_DRIVE_RATIO)
        best_gear = 1
        best_diff = float("inf")
        for i, ratio in enumerate(_GEAR_RATIOS_6SPD):
            diff = abs(theoretical_ratio - ratio)
            if diff < best_diff:
                best_diff = diff
                best_gear = i + 1
        return best_gear

    def _compute_warnings(self, hud: HUDData) -> list[str]:
        flags = []
        if hud.coolant_temp_c is not None and hud.coolant_temp_c > self.OVERHEAT_TEMP_C:
            flags.append(f"SOBRECALENTAMIENTO {hud.coolant_temp_c:.0f}°C")
        if hud.ctrl_voltage_v is not None and hud.ctrl_voltage_v < self.LOW_VOLTAGE_V:
            flags.append(f"VOLTAJE BAJO {hud.ctrl_voltage_v:.1f}V")
        if hud.fuel_level_pct is not None and hud.fuel_level_pct < self.LOW_FUEL_PCT:
            flags.append(f"COMBUSTIBLE BAJO {hud.fuel_level_pct:.0f}%")
        if hud.rpm is not None and hud.rpm > self.REDLINE_RPM * 0.95:
            flags.append(f"SOBRERGIMEN {hud.rpm:.0f} RPM")
        if hud.oil_temp_c is not None and hud.oil_temp_c > 130.0:
            flags.append(f"ACEITE CALIENTE {hud.oil_temp_c:.0f}°C")
        return flags

    @staticmethod
    def format_display(hud: HUDData) -> str:
        """Formatea HUDData como string multilinea para terminal o log."""
        lines = [
            "┌─── HUD ─────────────────────────────────────┐",
            f"│  Speed:   {(hud.speed_kmh or 0):>6.1f} km/h   "
            f"RPM: {(hud.rpm or 0):>6.0f}",
            f"│  Gear:    {'--' if hud.estimated_gear is None else hud.estimated_gear:>6}         "
            f"Load: {(hud.engine_load_pct or 0):>5.1f}%",
            f"│  Coolant: {(hud.coolant_temp_c or 0):>6.1f} °C    "
            f"Oil: {(hud.oil_temp_c or 0):>6.1f} °C",
            f"│  Fuel:    {(hud.fuel_level_pct or 0):>6.1f} %    "
            f"Volt: {(hud.ctrl_voltage_v or 0):>5.2f} V",
        ]
        if hud.fuel_consumption_l100km is not None:
            lines.append(
                f"│  Consumo: {hud.fuel_consumption_l100km:>6.2f} L/100km  "
                f"({hud.fuel_economy_mpg or 0:.1f} MPG)"
            )
        if hud.warning_flags:
            lines.append("│  ⚠ " + " | ".join(hud.warning_flags))
        lines.append("└──────────────────────────────────────────────┘")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. PARSE CAN LOG
# ═══════════════════════════════════════════════════════════════════════════════

def parse_can_log(filepath: str) -> list[CANFrame]:
    """Lee un archivo de log CAN estándar y retorna una lista de CANFrame.

    Formatos soportados (auto-detectados por línea):
      - candump:    '  vcan0  7E8   [8]  03 41 0C 1A 00 00 00 00'
      - timestamp:  '(1234.567) vcan0 7E8   [8]  DE AD BE EF'
      - socketcan:  '7E8#03410C1A'
      - columnas:   'timestamp channel id dlc data...'

    Líneas en blanco o que no coinciden con ningún formato se ignoran.

    Args:
        filepath: ruta absoluta o relativa al archivo de log.

    Returns:
        Lista de CANFrame parseados (vacía si el archivo no contiene tramas válidas).
    """
    frames: list[CANFrame] = []

    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        for lineno, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            # Intento 1: formato candump (con o sin timestamp)
            frame = CANFrameDecoder.from_candump_line(line)
            if frame is not None:
                # Extraer timestamp si está presente: "(1234.567) ..."
                ts_match = re.match(r"\(([\d.]+)\)", line)
                if ts_match:
                    frame.timestamp = float(ts_match.group(1))
                frames.append(frame)
                continue

            # Intento 2: formato SocketCAN "ID#DATA"
            if "#" in line.split()[0] if line.split() else False:
                token = line.split()[0]
                frame = CANFrameDecoder.from_socketcan_string(token)
                if frame is not None:
                    frames.append(frame)
                    continue

            # Intento 3: columnas "timestamp channel id dlc data..."
            # Ejemplo: "0.000 can0 7E8 8 03 41 0C 1A 00 00 00 00"
            parts = line.split()
            if len(parts) >= 4:
                try:
                    ts  = float(parts[0])
                    ch  = parts[1]
                    aid = int(parts[2], 16)
                    dlc = int(parts[3])
                    data_bytes = bytes(int(x, 16) for x in parts[4:4 + dlc])
                    frames.append(CANFrame(
                        arbitration_id=aid,
                        is_extended_id=aid > 0x7FF,
                        dlc=dlc,
                        data=data_bytes,
                        timestamp=ts,
                        channel=ch,
                    ))
                    continue
                except (ValueError, IndexError):
                    pass  # no coincide con este formato

    return frames


# ═══════════════════════════════════════════════════════════════════════════════
# API PÚBLICA
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # CAN frame
    "CANFrame",
    "CANFrameDecoder",
    # DBC
    "DBCSignal",
    "DBCMessage",
    "DBCParser",
    # Anomaly detection
    "AnomalyEvent",
    "OBDSensorAnomalyDetector",
    # HUD
    "HUDData",
    "HUDDataCalculator",
    # Log parser
    "parse_can_log",
    # Constantes
    "VW_AUDI_CAN_PIDS",
    "OBD_CAN_REQUEST_ID",
    "OBD_CAN_RESPONSE_BASE",
    "_SENSOR_NORMAL_RANGES",
]
