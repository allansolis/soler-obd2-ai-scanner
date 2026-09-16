"""
Protocolos K-line: ISO 9141-2, ISO 14230 (KWP2000), Honda DLC propietario, KWP1281 (VAG).

Implementado a partir de:
- muki01/OBD2_K-line_Reader y OBD2_KLine_Library
- kerpz/ArduinoHondaOBD
- KoffeinFlummi/rustbucket (KWP1281/VAG)
- Ircama/ELM327-emulator

Timing estándar K-line:
  Baud K-line: 10400 bps
  5-baud bit time: 200 ms
  Delay entre bytes recibidos: 30–60 ms
  Timeout inicial ECU: 1000 ms
"""
from __future__ import annotations
import time
from typing import Sequence

KLINE_BAUD = 10400
TESTER_ADDR = 0xF1
ECU_ADDR    = 0x01

OBD2_MODES = {
    0x01: "Live Data",
    0x02: "Freeze Frame",
    0x03: "Stored DTCs",
    0x04: "Clear DTCs",
    0x05: "O2 Sensor Tests",
    0x06: "Other Component Tests",
    0x07: "Pending DTCs",
    0x08: "Control On-Board Components",
    0x09: "Vehicle Information",
    0x0A: "Permanent DTCs",
}

KWP1281_BLOCK_TYPES = {
    0x05: "ClearDTCs",
    0x07: "GetDTCs",
    0x21: "ReadAdaptation",
    0x2A: "WriteAdaptation",
    0xE7: "DataGroupReply",
    0x09: "ACK",
    0xFF: "EndOfTransmission",
}

BMW_IBUS_MODULES = {
    0x00: "GM5",
    0x3F: "DIA",
    0x44: "EWS",
    0x50: "MFL",
    0x5B: "IHKA",
    0x68: "RAD",
    0x80: "IKE",
    0xBF: "ALL",
    0xC8: "TEL",
    0xD0: "LCM",
}


def checksum_iso9141(data: bytes | Sequence[int]) -> int:
    return sum(data) % 256


def checksum_ibus(data: bytes | Sequence[int]) -> int:
    result = 0
    for b in data:
        result ^= b
    return result


def build_iso9141_frame(mode: int, pid: int) -> bytes:
    """Construye trama ISO 9141 funcional: [0x68, 0x6A, 0xF1, MODE, PID, CHECKSUM]."""
    header = bytes([0x68, 0x6A, TESTER_ADDR])
    payload = bytes([mode, pid])
    frame = header + payload
    return frame + bytes([checksum_iso9141(frame)])


def build_kwp_fast_frame(mode: int, pid: int, physical: bool = False,
                          ecu_addr: int = ECU_ADDR) -> bytes:
    """Construye trama ISO 14230 KWP2000 (fast init)."""
    if physical:
        header = bytes([0x80 + 2, ecu_addr, TESTER_ADDR])
    else:
        header = bytes([0xC1, 0x33, TESTER_ADDR])
    payload = bytes([mode, pid])
    frame = header + payload
    return frame + bytes([checksum_iso9141(frame)])


def slow_init_params() -> dict:
    """Devuelve los parámetros de temporización para slow init 5-baud."""
    return {
        "address": 0x33,
        "bit_time_ms": 200,
        "total_time_s": 2.0,
        "sync_byte": 0x55,
        "ack_byte": 0xCC,
    }


HONDA_DLC_INIT = bytes([
    0x68, 0x6A, 0xF5, 0xAF, 0xBF,
    0xB3, 0xB2, 0xC1, 0xDB, 0xB3, 0xE9
])
HONDA_DLC_INIT_DELAY_MS = 300


def honda_checksum(cmd: int, num_params: int, addr: int, length: int) -> int:
    return (0xFF - (cmd + num_params + addr + length - 0x01)) & 0xFF


def build_honda_dlc_request(addr: int, length: int = 1) -> bytes:
    """Construye request Honda K-line propietario (pre-OBD2, ~pre-2002)."""
    cmd = 0x20
    num = 1
    cs = honda_checksum(cmd, num, addr, length)
    return bytes([cmd, num, addr, length, cs])


def honda_temp_convert(raw: int) -> float:
    """Convierte byte crudo ECT/IAT Honda a °C (polinomio 5to grado de ArduinoHondaOBD)."""
    r = raw
    return (155.04149
            - r * 3.0414878
            + r ** 2 * 0.03952185
            - r ** 3 * 0.00029383913
            + r ** 4 * 0.0000010792568
            - r ** 5 * 0.0000000015618437)


def honda_calc_maf(rpm: float, map_kpa: float, iat_celsius: float,
                   eng_disp_liters: float = 1.6) -> float:
    """Estima MAF (g/s) desde RPM + MAP + IAT cuando no hay sensor físico."""
    iat_k = iat_celsius + 273.15
    imap = rpm * map_kpa / iat_k / 2
    VE = 80
    MMA = 28.97
    R = 8.314
    return (imap / 60) * (VE / 100) * eng_disp_liters * MMA / R


HONDA_KLINE_REGISTERS: dict[int, tuple] = {
    0x00: ("rpm_hi",           1, "OBD1: 1875000/(A*256+B+1) | OBD2: (A*256+B)/4"),
    0x01: ("rpm_lo",           1, "ver rpm_hi"),
    0x04: ("vss",              1, "km/h directo"),
    0x10: ("ect",              1, "polinomio 5to grado"),
    0x11: ("iat",              1, "polinomio 5to grado"),
    0x12: ("map",              1, "kPa = val * 0.716 - 5"),
    0x13: ("baro",             1, "kPa = val * 0.716 - 5"),
    0x14: ("tps",              1, "% = (val - 24) / 2"),
    0x15: ("o2_v",             1, "0-5V directo"),
    0x17: ("battery_v",        1, "V = val / 10.45"),
    0x20: ("fuel_trim_st",     1, "% = (val/128 - 1) * 100"),
    0x22: ("fuel_trim_lt",     1, "% = (val/128 - 1) * 100"),
    0x26: ("injector_pw_hi",   1, "ms = (A*256+B)/250"),
    0x27: ("injector_pw_lo",   1, "ver injector_pw_hi"),
    0x28: ("ign_timing",       1, "deg = (val - 24) / 4"),
    0x3E: ("knock_corr",       1, "val / 51"),
    0x40: ("dtc_block",       16, "16 bytes packed, nibble pairs = códigos de falla"),
}

HONDA_STATUS_FLAGS: dict[int, dict] = {
    0x2108: {0: "Starter_Switch", 1: "Aircon_Switch", 3: "Brake_Switch",
             4: "Park_Neutral", 7: "VTEC_Pressure"},
    0x2109: {3: "SCS"},
    0x210A: {2: "VTEC_Solenoid"},
    0x210B: {0: "Main_Relay", 1: "Aircon_Clutch", 2: "O2_Heater_1",
             5: "Check_Engine_Light", 7: "O2_Heater_2"},
    0x210C: {0: "Alternator_Control", 1: "Fan_Control", 2: "IAB", 7: "Econo"},
    0x210D: {3: "Engine_Mount"},
    0x210F: {0: "Closed_Loop"},
}


def parse_kwp1281_dtcs(data: bytes) -> list[dict]:
    """Lee DTCs KWP1281 en chunks de 3 bytes: [CODE_HI, CODE_LO, STATUS]."""
    dtcs = []
    i = 0
    while i + 2 < len(data):
        if data[i:i+3] == bytes([0xFF, 0xFF, 0x88]):
            break
        code = (data[i] << 8) | data[i+1]
        status = data[i+2]
        dtcs.append({"code": f"{code:04X}", "status": status})
        i += 3
    return dtcs


def build_ibus_frame(source: int, destination: int, data: bytes) -> bytes:
    """Construye trama BMW I-Bus: [SOURCE, LENGTH, DESTINATION, DATA..., CHECKSUM(XOR)]."""
    length = 2 + len(data)
    frame = bytes([source, length, destination]) + data
    cs = checksum_ibus(frame)
    return frame + bytes([cs])
