"""
ELM327 Protocol driver — Scaner Soler Pro.

Integra lo mejor de:
  - Ircama/ELM327-emulator : IsoTpMultiframe, KWP2000 frame builder, ECU address map
  - provrb/obdium          : SupportedPIDScanner, FreezeFrameReader, DemoReplayProtocol
  - rzetterberg/elmobd     : MonitorStatus, validate_obd_response, bitmask parser
  - pyobd / kotlin-obd-api : baudrate auto-detect, parse_dtcs_robust
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import serial

from .base import AbstractProtocol, DTC

# ── PID Table ──────────────────────────────────────────────────────────────────
# pid -> (name, unit, min, max, formula)
PID_TABLE: dict[int, tuple] = {
    0x04: ("engine_load",        "%",      0,     100,    lambda v: v[0] * 100 / 255),
    0x05: ("coolant_temp",       "C",      -40,   215,    lambda v: v[0] - 40),
    0x06: ("fuel_trim_st_b1",    "%",      -100,  99.2,   lambda v: (v[0] - 128) * 100 / 128),
    0x07: ("fuel_trim_lt_b1",    "%",      -100,  99.2,   lambda v: (v[0] - 128) * 100 / 128),
    0x08: ("fuel_trim_st_b2",    "%",      -100,  99.2,   lambda v: (v[0] - 128) * 100 / 128),
    0x09: ("fuel_trim_lt_b2",    "%",      -100,  99.2,   lambda v: (v[0] - 128) * 100 / 128),
    0x0A: ("fuel_pressure",      "kPa",    0,     765,    lambda v: v[0] * 3),
    0x0B: ("map_kpa",            "kPa",    0,     255,    lambda v: v[0]),
    0x0C: ("rpm",                "rpm",    0,     16383,  lambda v: ((v[0] * 256) + v[1]) / 4),
    0x0D: ("speed",              "km/h",   0,     255,    lambda v: v[0]),
    0x0E: ("ignition_advance",   "deg",    -64,   63.5,   lambda v: v[0] / 2 - 64),
    0x0F: ("iat",                "C",      -40,   215,    lambda v: v[0] - 40),
    0x10: ("maf",                "g/s",    0,     655,    lambda v: ((v[0] * 256) + v[1]) / 100),
    0x11: ("throttle",           "%",      0,     100,    lambda v: v[0] * 100 / 255),
    0x12: ("sec_air_status",     "",       0,     255,    lambda v: v[0]),
    0x13: ("o2_sensors_present", "",       0,     255,    lambda v: v[0]),
    0x14: ("o2_b1s1_v",          "V",      0,     1.275,  lambda v: v[0] / 200),
    0x15: ("o2_b1s2_v",          "V",      0,     1.275,  lambda v: v[0] / 200),
    0x16: ("o2_b2s1_v",          "V",      0,     1.275,  lambda v: v[0] / 200),
    0x17: ("o2_b2s2_v",          "V",      0,     1.275,  lambda v: v[0] / 200),
    0x1C: ("obd_standard",       "",       0,     255,    lambda v: v[0]),
    0x1F: ("runtime",            "s",      0,     65535,  lambda v: (v[0] * 256) + v[1]),
    0x20: ("pids_supported_21",  "",       0,     0,      lambda v: v),  # bitmask
    0x21: ("mil_distance",       "km",     0,     65535,  lambda v: (v[0] * 256) + v[1]),
    0x22: ("fuel_rail_p_vac",    "kPa",    0,     5177,   lambda v: (v[0] * 256 + v[1]) * 0.079),
    0x23: ("fuel_rail_p_dir",    "kPa",    0,     655350, lambda v: (v[0] * 256 + v[1]) * 10),
    # O2 sensores wideband (lambda+voltage)
    0x24: ("o2_wb_b1s1_eq",      "",       0,     2,      lambda v: (v[0] * 256 + v[1]) / 32768),
    0x25: ("o2_wb_b1s2_eq",      "",       0,     2,      lambda v: (v[0] * 256 + v[1]) / 32768),
    0x26: ("o2_wb_b2s1_eq",      "",       0,     2,      lambda v: (v[0] * 256 + v[1]) / 32768),
    0x27: ("o2_wb_b2s2_eq",      "",       0,     2,      lambda v: (v[0] * 256 + v[1]) / 32768),
    0x2C: ("egr_cmd",            "%",      0,     100,    lambda v: v[0] * 100 / 255),
    0x2D: ("egr_error",          "%",      -100,  99.2,   lambda v: (v[0] - 128) * 100 / 128),
    0x2E: ("evap_purge",         "%",      0,     100,    lambda v: v[0] * 100 / 255),
    0x2F: ("fuel_level",         "%",      0,     100,    lambda v: v[0] * 100 / 255),
    0x30: ("warmups_since_clr",  "cnt",    0,     255,    lambda v: v[0]),
    0x31: ("dist_dtc_clear",     "km",     0,     65535,  lambda v: (v[0] * 256) + v[1]),
    0x32: ("evap_sys_vp",        "Pa",     -8192, 8192,   lambda v: (v[0] * 256 + v[1]) / 4 - 8192),
    0x33: ("baro_kpa",           "kPa",    0,     255,    lambda v: v[0]),
    # O2 wideband con corriente
    0x34: ("o2_wb_b1s1_cur",     "mA",     -128,  128,    lambda v: (v[2] * 256 + v[3]) / 256 - 128),
    0x35: ("o2_wb_b1s2_cur",     "mA",     -128,  128,    lambda v: (v[2] * 256 + v[3]) / 256 - 128),
    0x36: ("o2_wb_b2s1_cur",     "mA",     -128,  128,    lambda v: (v[2] * 256 + v[3]) / 256 - 128),
    0x37: ("o2_wb_b2s2_cur",     "mA",     -128,  128,    lambda v: (v[2] * 256 + v[3]) / 256 - 128),
    # Catalyst temps
    0x3C: ("catalyst_temp_b1s1", "C",      -40,   6513,   lambda v: ((v[0] * 256) + v[1]) / 10 - 40),
    0x3D: ("catalyst_temp_b2s1", "C",      -40,   6513,   lambda v: ((v[0] * 256) + v[1]) / 10 - 40),
    0x3E: ("catalyst_temp_b1s2", "C",      -40,   6513,   lambda v: ((v[0] * 256) + v[1]) / 10 - 40),
    0x3F: ("catalyst_temp_b2s2", "C",      -40,   6513,   lambda v: ((v[0] * 256) + v[1]) / 10 - 40),
    0x41: ("monitor_status_drv", "",       0,     0,      lambda v: v),  # bitmask, decodificar con parse_monitor_status
    0x42: ("ctrl_voltage",       "V",      0,     65.535, lambda v: ((v[0] * 256) + v[1]) / 1000),
    0x43: ("abs_load",           "%",      0,     25700,  lambda v: (v[0] * 256 + v[1]) * 100 / 255),
    0x44: ("lambda_eq_ratio",    "",       0,     2,      lambda v: (v[0] * 256 + v[1]) / 32768),
    0x45: ("rel_throttle",       "%",      0,     100,    lambda v: v[0] * 100 / 255),
    0x46: ("ambient_temp",       "C",      -40,   215,    lambda v: v[0] - 40),
    0x47: ("throttle_pos_b",     "%",      0,     100,    lambda v: v[0] * 100 / 255),
    0x48: ("throttle_pos_c",     "%",      0,     100,    lambda v: v[0] * 100 / 255),
    0x49: ("accel_pos_d",        "%",      0,     100,    lambda v: v[0] * 100 / 255),
    0x4A: ("accel_pos_e",        "%",      0,     100,    lambda v: v[0] * 100 / 255),
    0x4B: ("throttle_act",       "%",      0,     100,    lambda v: v[0] * 100 / 255),
    0x4C: ("throttle_act2",      "%",      0,     100,    lambda v: v[0] * 100 / 255),
    0x4D: ("time_mil_on",        "min",    0,     65535,  lambda v: (v[0] * 256) + v[1]),
    0x4E: ("time_dtc_clear",     "min",    0,     65535,  lambda v: (v[0] * 256) + v[1]),
    0x4F: ("max_eq_o2_map",      "",       0,     255,    lambda v: v[0]),  # 4 valores
    0x50: ("max_maf",            "g/s",    0,     2550,   lambda v: v[0] * 10),
    0x51: ("fuel_type",          "",       0,     255,    lambda v: v[0]),
    0x52: ("ethanol_pct",        "%",      0,     100,    lambda v: v[0] * 100 / 255),
    0x53: ("evap_vapor_pres",    "Pa",     0,     65535,  lambda v: (v[0] * 256 + v[1]) / 200),
    0x54: ("evap_vapor_pres2",   "Pa",     -32767, 32768, lambda v: (v[0] * 256 + v[1]) - 32767),
    0x55: ("o2_trim_b1",         "%",      -100,  99.2,   lambda v: (v[0] - 128) * 100 / 128),
    0x56: ("o2_trim_b2",         "%",      -100,  99.2,   lambda v: (v[0] - 128) * 100 / 128),
    0x57: ("o2_trim_b3",         "%",      -100,  99.2,   lambda v: (v[0] - 128) * 100 / 128),
    0x58: ("o2_trim_b4",         "%",      -100,  99.2,   lambda v: (v[0] - 128) * 100 / 128),
    0x59: ("fuel_rail_abs_pres", "kPa",    0,     655350, lambda v: (v[0] * 256 + v[1]) * 10),
    0x5A: ("accel_pos_f",        "%",      0,     100,    lambda v: v[0] * 100 / 255),
    0x5B: ("hybrid_bat_remain",  "%",      0,     100,    lambda v: v[0] * 100 / 255),
    0x5C: ("oil_temp",           "C",      -40,   210,    lambda v: v[0] - 40),
    0x5D: ("fuel_inj_timing",    "deg",    -210,  301,    lambda v: (v[0] * 256 + v[1]) / 128 - 210),
    0x5E: ("fuel_rate",          "L/h",    0,     3276,   lambda v: (v[0] * 256 + v[1]) * 0.05),
    0x5F: ("emission_req",       "",       0,     255,    lambda v: v[0]),
    0x61: ("torque_demand",      "%",      -125,  130,    lambda v: v[0] - 125),
    0x62: ("torque_actual",      "%",      -125,  130,    lambda v: v[0] - 125),
    0x63: ("torque_ref",         "Nm",     0,     65535,  lambda v: (v[0] * 256) + v[1]),
    0x67: ("coolant_temp2",      "C",      -40,   215,    lambda v: v[1] - 40),
    0x6D: ("oil_pressure",       "kPa",    0,     765,    lambda v: v[2] if len(v) > 2 else 0),
    0xA6: ("odometer",           "km",     0,     429496, lambda v: ((v[0]<<24)|(v[1]<<16)|(v[2]<<8)|v[3]) / 10),
}

FUEL_TYPE_MAP = {
    0x01: "Gasoline",       0x02: "Methanol",     0x03: "Ethanol",
    0x04: "Diesel",         0x05: "GPL/LPG",      0x06: "Natural Gas",
    0x07: "Propane",        0x08: "Electric",     0x09: "Bifuel Gasoline",
    0x0A: "Bifuel Methanol",0x0B: "Bifuel Ethanol",0x0C: "Bifuel LPG",
    0x0D: "Bifuel NG",      0x0E: "Bifuel Propane",0x0F: "Bifuel Electric",
    0x10: "Bifuel Gas/Elec",0x11: "Hybrid Gasoline",0x12: "Hybrid Ethanol",
    0x13: "Hybrid Diesel",  0x14: "Hybrid Electric",0x15: "Hybrid Mixed",
    0x16: "Hybrid Regen",
}

_TRY_BAUDS = [38400, 115200, 9600, 57600, 19200, 230400, 500000]
INIT_CMDS  = ["ATZ", "ATE0", "ATH1", "ATL0", "ATSP0", "ATAT1"]
DTC_LETTERS = ['P', 'C', 'B', 'U']

# Rangos de soporte de PIDs por servicio
_SUPPORTED_PID_RANGES: dict[str, list[str]] = {
    "01": ["00", "20", "40", "60", "80", "A0", "C0"],
    "02": ["00"],
    "09": ["00"],
}

# ECU address map (Ircama/ELM327-emulator)
ECU_ADDRESSES = {
    "ECU_ADDR_E":   0x7E0,  # Engine Control Module
    "ECU_ADDR_T":   0x7E1,  # Transmission
    "ECU_ADDR_H":   0x7E2,  # Hybrid / Auxiliary
    "ECU_ADDR_B":   0x7E3,  # Battery Management
    "ECU_ADDR_M":   0x7E5,  # Continental Powertrain
    "ECU_ADDR_S":   0x7B0,  # ABS / Stability
    "ECU_ADDR_P":   0x7C4,  # Climate / HVAC
    "ECU_R_ADDR_E": 0x7E8,  # Engine response
    "ECU_R_ADDR_T": 0x7E9,  # Transmission response
    "ECU_R_ADDR_H": 0x7EA,  # Hybrid response
    "ECU_R_ADDR_B": 0x7EB,  # BMS response
}
ECU_ADDR_NAMES: dict[int, str] = {v: k for k, v in ECU_ADDRESSES.items()}

# ELM327 error strings (rzetterberg/elmobd + ELM327-emulator)
_ELM_ERRORS = [
    "NO DATA", "UNABLE TO CONNECT", "BUS INIT: ERROR",
    "CAN ERROR", "BUS BUSY", "FB ERROR", "DATA ERROR",
    "ERR", "STOPPED", "?",
]


# =============================================================================
# ISO-TP Multiframe assembler (Ircama/ELM327-emulator)
# =============================================================================

class IsoTpMultiframe:
    """
    Ensambla tramas ISO 15765-2 (SF/FF/CF).
    Crítico para VIN, respuestas DTC largas, lecturas UDS.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._payload_hex = ""
        self._expected_len = 0
        self._next_sn = 1
        self._complete = False

    @property
    def is_complete(self) -> bool:
        return self._complete

    def feed_hex(self, hex_str: str) -> Optional[bytes]:
        """Alimenta una trama hex. Devuelve bytes cuando el mensaje está completo."""
        hex_str = hex_str.replace(" ", "").upper()
        if len(hex_str) < 2:
            return None
        frame_type = int(hex_str[0], 16)

        if frame_type == 0:      # Single Frame
            data_len = int(hex_str[1], 16)
            payload = hex_str[2:2 + data_len * 2]
            self._complete = True
            return bytes.fromhex(payload)

        elif frame_type == 1:    # First Frame
            self._expected_len = int(hex_str[1:4], 16)
            self._payload_hex = hex_str[4:]
            self._next_sn = 1
            self._complete = False
            return None

        elif frame_type == 2:    # Consecutive Frame
            sn = int(hex_str[1], 16)
            if sn != (self._next_sn & 0xF):
                self.reset()
                return None
            self._payload_hex += hex_str[2:]
            self._next_sn = (self._next_sn + 1) & 0xF
            if len(self._payload_hex) // 2 >= self._expected_len:
                complete_hex = self._payload_hex[:self._expected_len * 2]
                self._complete = True
                return bytes.fromhex(complete_hex)
            return None
        return None

    @staticmethod
    def build_flow_control(block_size: int = 0, st_min_ms: int = 0) -> str:
        """Genera trama FC (30 00 00) para responder a un First Frame."""
        return f"30 {block_size & 0xFF:02X} {st_min_ms & 0x7F:02X}"

    @staticmethod
    def assemble_multiline(lines: list[str]) -> Optional[bytes]:
        """
        Ensambla una respuesta multi-línea ELM327 en bytes.
        Acepta formato candump '0: 10 14 49 02 ...' o líneas hex simples.
        """
        mf = IsoTpMultiframe()
        for line in lines:
            # Eliminar prefijo de índice "0:" "1:" etc.
            clean = re.sub(r'^\d+:\s*', '', line.strip())
            clean = clean.replace(" ", "").upper()
            if not clean or clean == ">":
                continue
            result = mf.feed_hex(clean)
            if result is not None:
                return result
        return None


# =============================================================================
# KWP2000 frame builder (Ircama/ELM327-emulator)
# =============================================================================

def kwp2000_checksum(data: bytes | list[int]) -> int:
    """Checksum KWP2000/ISO-14230: suma módulo 256."""
    return sum(data) & 0xFF


def kwp2000_build_request(
    service_id: int,
    data: bytes = b"",
    tester_addr: int = 0xF1,
    ecu_addr: int = 0x01,
) -> bytes:
    """Construye frame KWP2000 con cabecera 3-byte y checksum."""
    payload = bytes([service_id]) + data
    length = len(payload)
    len_flag = 0x80 | (length & 0x3F)
    header = bytes([len_flag, ecu_addr, tester_addr])
    frame_no_cs = header + payload
    return frame_no_cs + bytes([kwp2000_checksum(frame_no_cs)])


# =============================================================================
# Response validator (rzetterberg/elmobd)
# =============================================================================

class OBDResponseError(Exception):
    pass


def validate_obd_response(raw_line: str, expected_mode: int, expected_pid: int) -> list[int]:
    """
    Valida y decodifica respuesta OBD-II del ELM327.
    Detecta errores ELM327, verifica echo de modo (modo+0x40) y echo de PID.
    Devuelve bytes de datos útiles. Lanza OBDResponseError si falla.
    """
    upper = raw_line.strip().upper()
    for err in _ELM_ERRORS:
        if err in upper:
            raise OBDResponseError(f"ELM327 error: '{upper}'")

    clean = upper.replace(" ", "")
    if len(clean) < 4 or len(clean) % 2 != 0:
        raise OBDResponseError(f"Respuesta malformada: '{raw_line}'")

    try:
        resp_bytes = [int(clean[i:i+2], 16) for i in range(0, len(clean), 2)]
    except ValueError as exc:
        raise OBDResponseError(f"Hex inválido: '{raw_line}'") from exc

    if len(resp_bytes) < 2:
        raise OBDResponseError("Respuesta demasiado corta")

    mode_echo = expected_mode + 0x40
    if resp_bytes[0] != mode_echo:
        raise OBDResponseError(
            f"Echo modo incorrecto: esperado {mode_echo:#04x}, recibido {resp_bytes[0]:#04x}")
    if resp_bytes[1] != expected_pid:
        raise OBDResponseError(
            f"Echo PID incorrecto: esperado {expected_pid:#04x}, recibido {resp_bytes[1]:#04x}")

    return resp_bytes[2:]


# =============================================================================
# Monitor Status (rzetterberg/elmobd — PID 0x01)
# =============================================================================

@dataclass
class MonitorStatus:
    """Estado del PID 0x01 — MIL + conteo DTC + flags de monitores."""
    mil_active: bool = False
    dtc_count: int = 0
    misfire_supported: bool = False
    misfire_incomplete: bool = False
    fuel_system_supported: bool = False
    fuel_system_incomplete: bool = False
    components_supported: bool = False
    components_incomplete: bool = False

    def summary(self) -> str:
        mil = "🔴 MIL ON" if self.mil_active else "🟢 MIL OFF"
        return f"{mil} | DTCs: {self.dtc_count}"


def parse_monitor_status(raw_bytes: list[int]) -> MonitorStatus:
    """
    Decodifica los 4 bytes del PID 0x01.
    Byte A: bit7=MIL, bits0-6=DTC count.
    Byte B: flags de monitores continuos.
    """
    ms = MonitorStatus()
    if not raw_bytes:
        return ms
    a = raw_bytes[0]
    ms.mil_active = bool(a & 0x80)
    ms.dtc_count  = a & 0x7F
    if len(raw_bytes) >= 2:
        b = raw_bytes[1]
        ms.misfire_incomplete       = bool(b & 0x10)
        ms.fuel_system_incomplete   = bool(b & 0x20)
        ms.components_incomplete    = bool(b & 0x40)
        ms.misfire_supported        = bool(b & 0x01)
        ms.fuel_system_supported    = bool(b & 0x02)
        ms.components_supported     = bool(b & 0x04)
    return ms


# =============================================================================
# Supported PIDs Scanner (provrb/obdium)
# =============================================================================

def parse_supported_pids_bitmask(range_pid_hex: str, bitmask_bytes: list[int]) -> list[int]:
    """
    Decodifica el bitmask de 32 bits de un PID de soporte (0x00, 0x20, ...).
    Algoritmo de rzetterberg/elmobd: bit MSB del byte A = PID base+1.
    Devuelve lista de PIDs soportados en el rango.
    """
    base = int(range_pid_hex, 16) + 1
    if len(bitmask_bytes) < 4:
        return []
    combined = (
        (bitmask_bytes[0] << 24) |
        (bitmask_bytes[1] << 16) |
        (bitmask_bytes[2] << 8)  |
         bitmask_bytes[3]
    )
    return [base + i for i in range(32) if (combined >> (31 - i)) & 1]


class SupportedPIDScanner:
    """
    Detecta todos los PIDs soportados consultando rangos 0x00, 0x20, 0x40...
    de forma jerárquica (provrb/obdium).
    """

    def __init__(self, protocol: "ELM327Protocol") -> None:
        self._proto = protocol

    def scan(self, service: int = 1) -> list[int]:
        """Devuelve lista ordenada de todos los PIDs soportados para el servicio."""
        service_hex = f"{service:02X}"
        ranges = _SUPPORTED_PID_RANGES.get(service_hex, ["00"])
        all_pids: list[int] = []

        for range_pid in ranges:
            pid_int = int(range_pid, 16)
            try:
                result = self._proto.read_pid(pid_int, mode=service)
                raw = result.get("raw", [])
                if len(raw) >= 4:
                    pids = parse_supported_pids_bitmask(range_pid, raw[:4])
                    all_pids.extend(pids)
                    if (pid_int + 0x20) not in pids:
                        break
            except Exception:
                break

        return sorted(set(all_pids))


# =============================================================================
# ECU header parser (Ircama/ELM327-emulator)
# =============================================================================

def parse_ecu_header(header_hex: str) -> dict:
    """Identifica la ECU a partir de su dirección CAN 11-bit."""
    try:
        addr = int(header_hex.strip(), 16)
    except ValueError:
        return {"ecu_addr": None, "ecu_name": "UNKNOWN", "is_response": False}
    name = ECU_ADDR_NAMES.get(addr, f"0x{addr:03X}")
    return {
        "ecu_addr": addr,
        "ecu_name": name,
        "is_response": (addr & 0x008) != 0,
    }


# =============================================================================
# Freeze Frame support (provrb/obdium)
# =============================================================================

class FreezeFrameReader:
    """
    Lee datos de Freeze Frame (service 02) reutilizando decodificadores de service 01.
    provrb/obdium: "switch service 01 → 02 before sending".
    """

    def __init__(self, protocol: "ELM327Protocol", frame_index: int = 0) -> None:
        self._proto = protocol
        self._frame_index = frame_index

    def read_pid(self, pid: int) -> dict:
        """Lee un PID del Freeze Frame (service 02)."""
        cmd = f"02{pid:02X}{self._frame_index:02X}"
        raw = self._proto._send_command(cmd, delay=0.15)
        return self._proto._decode_pid(pid, 0x02, raw)

    def read_all_available(self, pid_list: list[int]) -> dict[int, dict]:
        """Lee todos los PIDs disponibles del Freeze Frame."""
        return {pid: self.read_pid(pid) for pid in pid_list if self.read_pid(pid).get("value") is not None}


# =============================================================================
# Demo Replay Protocol (provrb/obdium)
# =============================================================================

class DemoReplayProtocol:
    """
    Modo offline: reproduce pares request/response desde un JSON.
    Permite probar el scanner sin hardware.

    Formato JSON:
        {"01 0C": "41 0C 1A F8", "03": "43 01 33 00 00 00 00", ...}
    """

    def __init__(self, replay_file: str | Path) -> None:
        self._file = Path(replay_file)
        self._db: dict[str, str] = {}
        if self._file.exists():
            with open(self._file, encoding="utf-8") as f:
                self._db = json.load(f)

    @property
    def is_connected(self) -> bool:
        return bool(self._db)

    def connect(self, *args, **kwargs) -> bool:
        return bool(self._db)

    def disconnect(self) -> None:
        pass

    def _send_command(self, cmd: str, delay: float = 0.0) -> str:
        key = cmd.strip().upper().replace(" ", "")
        for k, v in self._db.items():
            if k.replace(" ", "").upper() == key:
                return v
        return "NO DATA"

    def read_pid(self, pid: int, mode: int = 0x01) -> dict:
        cmd = f"{mode:02X}{pid:02X}"
        raw = self._send_command(cmd)
        lines = [raw]
        expected_prefix = f"{(mode + 0x40):02X}{pid:02X}".upper()
        data_bytes = []
        for line in lines:
            clean = line.replace(" ", "").upper()
            if clean.startswith(expected_prefix):
                hex_data = clean[len(expected_prefix):]
                try:
                    data_bytes = [int(hex_data[i:i+2], 16) for i in range(0, len(hex_data), 2)]
                except ValueError:
                    pass
                break
        if pid in PID_TABLE and data_bytes:
            name, unit, vmin, vmax, formula = PID_TABLE[pid]
            try:
                value = formula(data_bytes)
                return {"name": name, "value": round(value, 3), "unit": unit, "raw": data_bytes}
            except (IndexError, ZeroDivisionError):
                pass
        return {"raw": raw, "raw_bytes": data_bytes}

    @staticmethod
    def save_session(protocol, pid_list: list[int], output_file: str | Path, mode: int = 0x01) -> None:
        """Graba una sesión real en JSON para usar luego en replay."""
        db: dict[str, str] = {}
        for pid in pid_list:
            cmd = f"{mode:02X}{pid:02X}"
            raw = protocol._send_command(cmd, delay=0.15)
            db[cmd] = raw.strip()
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2)


# =============================================================================
# Orquestador: escaneo completo de vehículo
# =============================================================================

def full_vehicle_scan(protocol: "ELM327Protocol") -> dict:
    """
    Realiza un escaneo completo:
      1. PIDs soportados
      2. Monitor status (MIL + DTC count)
      3. Disponibilidad de Freeze Frame
    """
    report: dict = {
        "supported_pids": [],
        "monitor_status": None,
        "freeze_frame_available": False,
    }
    try:
        report["supported_pids"] = SupportedPIDScanner(protocol).scan()
    except Exception as exc:
        report["supported_pids_error"] = str(exc)

    try:
        ms_raw = protocol.read_pid(0x01, mode=0x01)
        report["monitor_status"] = parse_monitor_status(ms_raw.get("raw", []))
    except Exception as exc:
        report["monitor_status_error"] = str(exc)

    try:
        ffr = FreezeFrameReader(protocol)
        ff = ffr.read_pid(0x0C)
        report["freeze_frame_available"] = ff.get("value") is not None
        if ff.get("value"):
            report["freeze_frame_rpm"] = ff["value"]
    except Exception:
        pass

    return report


# =============================================================================
# ELM327 Protocol — driver principal
# =============================================================================

class ELM327Protocol(AbstractProtocol):

    def __init__(self):
        self._serial: serial.Serial | None = None
        self._connected = False
        self._isotp = IsoTpMultiframe()

    @property
    def is_connected(self) -> bool:
        return self._connected and self._serial is not None and self._serial.is_open

    def connect(self, port: str = "COM3", baudrate: int = 0) -> bool:
        """Conecta al ELM327. baudrate=0 activa auto-detección."""
        try:
            bauds = _TRY_BAUDS if baudrate == 0 else [baudrate]
            self._serial = serial.Serial(port, bauds[0], timeout=1.0)
            time.sleep(0.3)
            found = False
            for baud in bauds:
                self._serial.baudrate = baud
                self._serial.reset_input_buffer()
                self._serial.reset_output_buffer()
                self._serial.write(b"ATZ\r")
                time.sleep(0.5)
                resp = self._serial.read(256).decode("ascii", errors="ignore").lower()
                if "elm" in resp or ">" in resp:
                    found = True
                    break
            if not found and baudrate == 0:
                raise ConnectionError(f"No ELM327 found on {port}")
            self._serial.timeout = 5.0
            for cmd in INIT_CMDS[1:]:
                self._send_command(cmd, delay=0.4)
            self._connected = True
            return True
        except serial.SerialException as e:
            raise ConnectionError(f"ELM327 connect failed on {port}: {e}") from e

    def disconnect(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._connected = False

    def send_raw(self, data: bytes, timeout: float = 5.0) -> bytes:
        self._serial.timeout = timeout
        self._serial.write(data + b"\r")
        return self._read_response()

    def _send_command(self, cmd: str, delay: float = 0.1) -> str:
        self._serial.reset_input_buffer()
        self._serial.write((cmd + "\r").encode())
        time.sleep(delay)
        raw = b""
        while self._serial.in_waiting:
            raw += self._serial.read(self._serial.in_waiting)
            time.sleep(0.02)
        return raw.decode("ascii", errors="ignore").strip()

    def _read_response(self) -> bytes:
        buf = b""
        deadline = time.time() + 5.0
        while time.time() < deadline:
            chunk = self._serial.read(256)
            buf += chunk
            if b">" in buf:
                break
        return buf

    def read_pid(self, pid: int, mode: int = 0x01) -> dict:
        """Lee un PID OBD-II. Usa validate_obd_response (rzetterberg/elmobd)."""
        cmd = f"{mode:02X}{pid:02X}"
        raw = self._send_command(cmd, delay=0.15)

        # Intentar validación robusta primero
        lines = [l.strip() for l in raw.splitlines()
                 if l.strip() and ">" not in l and l.strip()]
        for line in lines:
            try:
                data_bytes = validate_obd_response(line, mode, pid)
                return self._build_result(pid, mode, data_bytes, raw)
            except OBDResponseError:
                continue

        # Fallback: decodificación directa
        return self._decode_pid(pid, mode, raw)

    def _decode_pid(self, pid: int, mode: int, raw: str) -> dict:
        lines = [l.strip() for l in raw.splitlines() if l.strip() and ">" not in l]

        # Detectar ISO-TP multiframe (líneas con ":")
        if any(":" in l for l in lines):
            assembled = IsoTpMultiframe.assemble_multiline(lines)
            if assembled and len(assembled) >= 2:
                data_bytes = list(assembled[2:])  # Saltar modo+PID echo
                return self._build_result(pid, mode, data_bytes, raw)

        data_bytes = []
        expected_prefix = f"{(mode + 0x40):02X}{pid:02X}".upper()
        for line in lines:
            clean = line.replace(" ", "").upper()
            if clean.startswith(expected_prefix):
                hex_data = clean[len(expected_prefix):]
                try:
                    data_bytes = [int(hex_data[i:i+2], 16) for i in range(0, len(hex_data), 2)]
                except ValueError:
                    pass
                break
        return self._build_result(pid, mode, data_bytes, raw)

    def _build_result(self, pid: int, mode: int, data_bytes: list[int], raw: str) -> dict:
        if pid in PID_TABLE and data_bytes:
            name, unit, vmin, vmax, formula = PID_TABLE[pid]
            try:
                value = formula(data_bytes)
                if pid == 0x51:
                    value = FUEL_TYPE_MAP.get(data_bytes[0], f"type_{data_bytes[0]}")
                elif isinstance(value, float):
                    if vmax > vmin and not (vmin <= value <= vmax * 1.05):
                        value = None
                    else:
                        value = round(value, 3)
                return {"pid": pid, "name": name, "value": value, "unit": unit, "raw": data_bytes}
            except (IndexError, ZeroDivisionError):
                pass
        return {"pid": pid, "name": f"PID_{pid:02X}", "value": None, "unit": "", "raw": data_bytes}

    # ── DTCs ──────────────────────────────────────────────────────────────────

    def read_dtc(self) -> list[DTC]:
        raw = self._send_command("03", delay=0.5)
        return self._parse_dtc_response(raw, status="confirmed")

    def read_pending_dtc(self) -> list[DTC]:
        """Mode 07 — DTCs pendientes."""
        raw = self._send_command("07", delay=0.5)
        return self._parse_dtc_response(raw, status="pending")

    def read_permanent_dtc(self) -> list[DTC]:
        """Mode 0A — DTCs permanentes (no se borran con Mode 04)."""
        raw = self._send_command("0A", delay=0.5)
        return self._parse_dtc_response(raw, status="permanent")

    def _parse_dtc_response(self, raw: str, status: str) -> list[DTC]:
        """
        Parser tri-protocolo (kotlin-obd-api + ELM327-emulator):
          - CAN one-frame  : "43XX[codigos]"
          - CAN multi-frame: líneas con ":" → IsoTpMultiframe
          - ISO9141/KWP    : una línea por respuesta
        """
        lines = [l.strip() for l in raw.splitlines() if l.strip() and ">" not in l]

        # Intentar ensamblar con ISO-TP si hay tramas multi
        if any(":" in l for l in lines):
            assembled = IsoTpMultiframe.assemble_multiline(lines)
            if assembled:
                # Saltar byte de modo (0x43/0x47/0x4A) y número de DTCs
                payload = assembled[2:] if len(assembled) > 2 else assembled
                return self._dtc_from_bytes(list(payload), status)

        clean_all = raw.replace('\r', '').replace('\n', '').replace(' ', '').upper()

        # CAN one-frame
        for prefix in ("43", "47", "4A"):
            if clean_all.startswith(prefix):
                working = clean_all[4:]  # Saltar modo + count
                return self._dtc_from_hex(working, status)

        # ISO9141/KWP línea por línea
        working = re.sub(r'^43|[\r\n]43|^47|[\r\n]47|^4A|[\r\n]4A', '', clean_all)
        working = re.sub(r'[\r\n]', '', working)
        return self._dtc_from_hex(working, status)

    def _dtc_from_hex(self, hex_str: str, status: str) -> list[DTC]:
        """Convierte string hex en lista de DTC."""
        dtcs = []
        for i in range(0, len(hex_str) - 3, 4):
            chunk = hex_str[i:i+4]
            if len(chunk) < 4 or chunk == "0000":
                continue
            try:
                b1 = int(chunk[0], 16)
                letter = DTC_LETTERS[(b1 >> 2) & 0x3]
                code = f"{letter}{b1 & 0x3:01X}{chunk[1:]}"
                if len(code) == 5 and code != "P0000":
                    dtc = DTC.from_raw_code(code)
                    dtc.status = status
                    dtcs.append(dtc)
            except (ValueError, IndexError):
                continue
        return dtcs

    def _dtc_from_bytes(self, data: list[int], status: str) -> list[DTC]:
        """Convierte lista de bytes en DTCs."""
        dtcs = []
        for i in range(0, len(data) - 1, 2):
            b1, b2 = data[i], data[i+1]
            if b1 == 0 and b2 == 0:
                continue
            try:
                letter = DTC_LETTERS[(b1 >> 6) & 0x3]
                code = f"{letter}{(b1 >> 4) & 0x3:01X}{b1 & 0xF:01X}{b2:02X}"
                if len(code) == 5 and code != "P0000":
                    dtc = DTC.from_raw_code(code)
                    dtc.status = status
                    dtcs.append(dtc)
            except (ValueError, IndexError):
                continue
        return dtcs

    def clear_dtc(self) -> bool:
        """Mode 04 — Borrar todos los DTCs y datos de Freeze Frame."""
        raw = self._send_command("04", delay=0.5)
        return "44" in raw.upper() or "OK" in raw.upper()

    # ── Monitor Status ────────────────────────────────────────────────────────

    def read_monitor_status(self) -> MonitorStatus:
        """Lee PID 0x01 y devuelve MonitorStatus con MIL + conteo DTC."""
        result = self.read_pid(0x01, mode=0x01)
        return parse_monitor_status(result.get("raw", []))

    # ── PIDs soportados ───────────────────────────────────────────────────────

    def scan_supported_pids(self, service: int = 1) -> list[int]:
        """Detecta todos los PIDs que soporta la ECU para el servicio dado."""
        return SupportedPIDScanner(self).scan(service=service)

    # ── Freeze Frame ──────────────────────────────────────────────────────────

    def read_freeze_frame(self, pid: int = 0x0C, frame_index: int = 0) -> dict:
        """Lee un PID específico del Freeze Frame (service 02)."""
        return FreezeFrameReader(self, frame_index).read_pid(pid)

    def get_freeze_frame_reader(self, frame_index: int = 0) -> FreezeFrameReader:
        """Devuelve un FreezeFrameReader para leer múltiples PIDs."""
        return FreezeFrameReader(self, frame_index)

    # ── Vehicle Info ──────────────────────────────────────────────────────────

    def read_vehicle_info(self) -> dict:
        """
        Lee VIN, calibration ID y ECU name via Mode 09.
        Usa IsoTpMultiframe para ensamblar respuestas largas (VIN = 17 chars).
        """
        results = {}

        for pid_hex, key in [("0902", "vin"), ("0904", "calibration_id"), ("090A", "ecu_name")]:
            raw = self._send_command(pid_hex, delay=0.5)
            lines = [l.strip() for l in raw.splitlines() if l.strip() and ">" not in l]

            # Intentar ISO-TP assembly para VIN (multi-frame)
            assembled = IsoTpMultiframe.assemble_multiline(lines)
            if assembled:
                text = assembled.decode("ascii", errors="ignore").strip("\x00").strip()
                results[key] = "".join(c for c in text if c.isprintable())
            else:
                results[key] = self._extract_string(raw, pid_hex[:2] + " " + pid_hex[2:])

        return results

    def _extract_string(self, raw: str, prefix: str) -> str:
        try:
            clean = raw.replace(" ", "").upper()
            pclean = prefix.replace(" ", "").upper()
            # Buscar eco de respuesta (prefix + 0x40 en primer nibble)
            resp_prefix = f"{(int(pclean[:2], 16) + 0x40):02X}{pclean[2:]}"
            idx = clean.index(resp_prefix)
            hex_str = clean[idx + len(resp_prefix):idx + len(resp_prefix) + 50]
            chars = [chr(int(hex_str[i:i+2], 16)) for i in range(0, len(hex_str), 2)]
            return "".join(c for c in chars if c.isprintable()).strip()
        except (ValueError, IndexError):
            return ""

    # ── Full scan ─────────────────────────────────────────────────────────────

    def full_scan(self) -> dict:
        """Escaneo completo: PIDs soportados + monitor status + freeze frame."""
        return full_vehicle_scan(self)
