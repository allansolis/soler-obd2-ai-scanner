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
from collections import deque
from enum import IntEnum
from typing import Optional, Sequence

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


# ===========================================================================
# EXTENSIONES — migradas desde extracted_group3.py
# Fuentes: muki01/OBD2_KLine_Library, muki01/I-K_Bus, kerpz/ArduinoHondaOBD
# ===========================================================================

# ---------------------------------------------------------------------------
# CONSTANTES DE TIMING POR PROTOCOLO
# ---------------------------------------------------------------------------

class KLineProtocol(IntEnum):
    ISO9141  = 0   # 10400 baud, 8N1, slow init 5-baud
    ISO14230 = 1   # 10400 baud, 8N1, fast o slow init
    KW1281   = 2   # 9600 baud, 8O1 init, byte-ACK
    DS2      = 3   # 9600 baud, 8E1, ping handshake
    KW82     = 4   # 4800 baud, 8N1, stream (sin req/resp)


# Timing ISO 14230-2 en milisegundos:
#   P1 = inter-byte gap (ECU→tester), P2 = timeout resp, P3 = gap inter-msg,
#   P4 = inter-byte gap (tester→ECU), W1-W4 = handshake timings
PROTOCOL_TIMING: dict[KLineProtocol, dict] = {
    KLineProtocol.ISO9141: {
        "baud": 10400, "serial_cfg": "8N1",
        "P1_ms": 20,   "P2_ms": 1000, "P3_ms": 55, "P4_ms": 5,
        "W1_ms": 300,  "W2_ms": 20,   "W3_ms": 20, "W4_ms": 50,
        "wakeup_delay_ms": 5500,
        "init_type": "5baud", "init_addr": 0x33,
        "checksum": "mod256",
    },
    KLineProtocol.ISO14230: {
        "baud": 10400, "serial_cfg": "8N1",
        "P1_ms": 20,   "P2_ms": 1000, "P3_ms": 55, "P4_ms": 5,
        "W1_ms": 300,  "W2_ms": 20,   "W3_ms": 20, "W4_ms": 50,
        "wakeup_delay_ms": 5500,
        "init_type": "fast",
        "checksum": "mod256",
    },
    KLineProtocol.KW1281: {
        "baud": 9600, "serial_cfg": "8O1",
        "P1_ms": 10,  "P2_ms": 1500, "P3_ms": 50,  "P4_ms": 5,
        "W1_ms": 300, "W2_ms": 20,   "W3_ms": 20,  "W4_ms": 50,
        "wakeup_delay_ms": 5500,
        "init_type": "5baud", "init_addr": None,
        "checksum": "none",
    },
    KLineProtocol.DS2: {
        "baud": 9600, "serial_cfg": "8E1",
        "P1_ms": 10,  "P2_ms": 1500, "P3_ms": 50,  "P4_ms": 5,
        "W1_ms": 0,   "W2_ms": 0,    "W3_ms": 0,   "W4_ms": 0,
        "wakeup_delay_ms": 0,
        "init_type": "ping",
        "checksum": "xor",
    },
    KLineProtocol.KW82: {
        "baud": 4800, "serial_cfg": "8N1",
        "P1_ms": 10,  "P2_ms": 1500, "P3_ms": 50,  "P4_ms": 5,
        "W1_ms": 0,   "W2_ms": 0,    "W3_ms": 0,   "W4_ms": 0,
        "wakeup_delay_ms": 0,
        "init_type": "none",
        "checksum": "mod256",
    },
}

BYTE_WRITE_INTERVAL_MS = 5
INTER_BYTE_TIMEOUT_MS  = 60
RESULT_BUFFER_SIZE     = 300


# ---------------------------------------------------------------------------
# FAST INIT PULSE (ISO 14230)
# ---------------------------------------------------------------------------

def fast_init_timing() -> dict:
    """Retorna parámetros para el pulso de fast init ISO 14230.
    El pin TX debe mantenerse LOW 25 ms, luego HIGH 25 ms.
    """
    return {
        "low_ms":  25,
        "high_ms": 25,
        "start_byte": 0x81,
        "expected_echo_byte3": 0xC1,
    }


def send_fast_init_pulse(ser) -> None:
    """Ejecuta el pulso de fast init en un puerto pyserial."""
    ser.break_condition = True
    time.sleep(0.025)
    ser.break_condition = False
    time.sleep(0.025)


# ---------------------------------------------------------------------------
# SLOW INIT 5-BAUD (bit-bang físico)
# ---------------------------------------------------------------------------

def slow_init_send_address(ser, address: int = 0x33) -> None:
    """Envía un byte a 5 baudios (200 ms/bit) usando break_condition de pyserial.
    Formato: start(0) | 7 bits LSB-first | paridad impar | stop(1)
    """
    bits: list[int] = [0]  # start bit
    val = address
    parity = 0
    for _ in range(7):
        b = val & 1
        bits.append(b)
        parity ^= b
        val >>= 1
    bits.append(parity & 1)
    bits.append(1)  # stop bit

    for bit in bits:
        ser.break_condition = (bit == 0)
        time.sleep(0.200)


# ---------------------------------------------------------------------------
# AUTO-DETECCIÓN DE PROTOCOLO
# ---------------------------------------------------------------------------

def detect_protocol_from_keywords(kw1: int, kw2: int) -> KLineProtocol:
    """Tras slow init, la ECU devuelve [0x55, KW1, KW2].
    KW1 == KW2 → ISO9141; KW1 != KW2 → ISO14230.
    """
    if kw1 == kw2:
        return KLineProtocol.ISO9141
    return KLineProtocol.ISO14230


def auto_detect_protocol(ser, init_addr: int = 0x33,
                          timeout_s: float = 3.0) -> Optional[KLineProtocol]:
    """Ronda 1: fast init → ISO14230 si byte[2]==0xC1.
    Ronda 2: slow init 5-baud → keywords para distinguir ISO9141/ISO14230.
    Devuelve None si no hay respuesta.
    """
    try:
        send_fast_init_pulse(ser)
        time.sleep(0.005)
        ser.write(bytes([0x81]))
        time.sleep(0.3)
        buf = ser.read(10)
        if len(buf) >= 3 and buf[2] == 0xC1:
            return KLineProtocol.ISO14230
    except Exception:
        pass

    try:
        slow_init_send_address(ser, init_addr)
        deadline = time.time() + timeout_s
        buf_list: list[int] = []
        while time.time() < deadline and len(buf_list) < 3:
            b = ser.read(1)
            if b:
                buf_list.append(b[0])
        if len(buf_list) >= 3 and buf_list[0] == 0x55:
            return detect_protocol_from_keywords(buf_list[1], buf_list[2])
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# CHECKSUMS ADICIONALES
# ---------------------------------------------------------------------------

def checksum_twos_complement(data: bytes | list[int]) -> int:
    """Checksum 8-bit complemento a dos: -(sum(data)) & 0xFF.
    Usado en algunos fabricantes europeos.
    """
    return (-(sum(data))) & 0xFF


def verify_checksum(data: bytes, checksum_type: str) -> bool:
    """Verifica checksum del frame completo (el último byte es el checksum).
    checksum_type: 'mod256' | 'xor' | 'twos'
    """
    if len(data) < 2:
        return False
    payload = data[:-1]
    received = data[-1]
    if checksum_type == "mod256":
        expected = checksum_iso9141(payload)
    elif checksum_type == "xor":
        expected = checksum_ibus(payload)
    elif checksum_type == "twos":
        expected = checksum_twos_complement(payload)
    else:
        return True  # "none"
    return expected == received


# ---------------------------------------------------------------------------
# DECODE DTC ESTÁNDAR OBD2
# ---------------------------------------------------------------------------

_DTC_SYSTEM_MAP = {0: "P", 1: "C", 2: "B", 3: "U"}


def decode_dtc_standard(b1: int, b2: int) -> str:
    """Convierte dos bytes ISO 15031-6 a código DTC string (ej. P0301)."""
    system = _DTC_SYSTEM_MAP[(b1 >> 6) & 0x03]
    d1 = (b1 >> 4) & 0x03
    d2 = b1 & 0x0F
    d3 = (b2 >> 4) & 0x0F
    d4 = b2 & 0x0F
    return f"{system}{d1:01X}{d2:01X}{d3:01X}{d4:01X}"


def decode_dtc_list(data: bytes) -> list[str]:
    """Procesa respuesta OBD2 Mode 03/07/0A: pares de bytes [B1, B2, ...]."""
    dtcs: list[str] = []
    for i in range(0, len(data) - 1, 2):
        b1, b2 = data[i], data[i + 1]
        if b1 == 0 and b2 == 0:
            continue
        dtcs.append(decode_dtc_standard(b1, b2))
    return dtcs


# ---------------------------------------------------------------------------
# PROTOCOLO DS2 (BMW)
# ---------------------------------------------------------------------------

DS2_PING_BYTE  = 0x00
DS2_BAUD       = 9600
DS2_SERIAL_CFG = "8E1"


def build_ds2_frame(ecu_addr: int, service: int, params: bytes = b"") -> bytes:
    """Trama DS2 BMW: [ADDR][LENGTH][SERVICE][PARAMS...][XOR_CHECKSUM].
    LENGTH incluye el frame completo (incluye a sí mismo y checksum).
    """
    frame = bytes([ecu_addr, 0, service]) + params
    length = len(frame) + 1   # +1 para el checksum
    frame = bytes([ecu_addr, length, service]) + params
    cs = checksum_ibus(frame)
    return frame + bytes([cs])


def parse_ds2_response(data: bytes) -> dict:
    """Parsea respuesta DS2: [ADDR][LENGTH][SERVICE+0x40][DATA...][XOR].
    Devuelve dict con addr, service, payload, checksum_ok, valid.
    """
    if len(data) < 4:
        return {"valid": False, "reason": "frame too short"}
    addr    = data[0]
    length  = data[1]
    service = data[2]
    if len(data) < length:
        return {"valid": False, "reason": f"expected {length} bytes, got {len(data)}"}
    frame   = data[:length - 1]
    cs_recv = data[length - 1]
    cs_calc = checksum_ibus(frame)
    return {
        "valid": cs_recv == cs_calc,
        "addr": addr,
        "service": service,
        "payload": data[3:length - 1],
        "checksum_ok": cs_recv == cs_calc,
    }


def ds2_ping(ser) -> bool:
    """Handshake DS2: escribe 0x00, retorna True si llega cualquier dato."""
    ser.write(bytes([DS2_PING_BYTE]))
    time.sleep(0.1)
    return ser.in_waiting > 0


# ---------------------------------------------------------------------------
# PROTOCOLO KW82 / GM-OPEL
# ---------------------------------------------------------------------------

KW82_BAUD = 4800


def kw82_sliding_window_sync(buf: bytes) -> Optional[tuple[int, bytes]]:
    """Localiza una trama válida en un buffer usando ventana deslizante.
    Formato KW82: [LENGTH][DATA[0..LENGTH-2]][CHECKSUM_MOD256].
    Retorna (offset, frame) o None si no se encuentra trama válida.
    """
    for offset in range(len(buf)):
        length = buf[offset]
        if length < 2:
            continue
        end = offset + length
        if end > len(buf):
            break
        frame   = buf[offset:end - 1]
        cs_recv = buf[end - 1]
        cs_calc = checksum_iso9141(frame)
        if cs_recv == cs_calc:
            return (offset, buf[offset:end])
    return None


def build_kw82_frame(service: int, params: bytes = b"") -> bytes:
    """Construye trama KW82: [LENGTH][SERVICE][PARAMS...][MOD256_CHECKSUM]."""
    payload = bytes([service]) + params
    length  = len(payload) + 2
    frame   = bytes([length]) + payload
    cs      = checksum_iso9141(frame)
    return frame + bytes([cs])


# ---------------------------------------------------------------------------
# KW1281 BLOCK ACK
# ---------------------------------------------------------------------------

KW1281_BAUD       = 9600
KW1281_ACK_MARKER = 0x09
KW1281_EOT_MARKER = 0xFF

# Tabla de tipos de bloque extendida (complementa KWP1281_BLOCK_TYPES)
KW1281_EXTENDED_BLOCK_TYPES = {
    0x05: "ClearDTCs",
    0x07: "GetDTCs",
    0x08: "GetDTCCount",
    0x09: "ACK",
    0x21: "ReadAdaptation",
    0x28: "WriteAdaptation",
    0x2A: "WriteAdaptationWithEEPROM",
    0x29: "ReadBasicSetting",
    0x2B: "WriteBasicSetting",
    0xF6: "ReadGroup",
    0xE7: "DataGroupReply",
    0xFC: "ReadID",
    0xFB: "ReadIDReply",
    0xFF: "EndOfTransmission",
}

# Tabla extendida de módulos IBUS (complementa BMW_IBUS_MODULES)
IBUS_MODULE_ADDRESSES = {
    0x00: "GM5",
    0x18: "CDC",
    0x3F: "DIA",
    0x44: "EWS",
    0x46: "CID",
    0x50: "MFL",
    0x5B: "IHKA",
    0x68: "RAD",
    0x6A: "DSP_MID",
    0x72: "BMBT",
    0x76: "HKM",
    0x7C: "RLS",
    0x7F: "SES",
    0x80: "IKE",
    0xBF: "ALL",
    0xC8: "TEL",
    0xD0: "LCM",
    0xD5: "DSP",
    0xE7: "CVM",
    0xF0: "BMB",
}


def kw1281_complement_ack(byte_received: int) -> int:
    """KW1281: el tester responde a cada byte del bloque con su complemento."""
    return (~byte_received) & 0xFF


def parse_kw1281_block(data: bytes) -> dict:
    """Parsea un bloque KW1281: [LENGTH][COUNTER][TYPE][DATA...].
    LENGTH incluye length+counter+type pero NO los datos de payload.
    """
    if len(data) < 3:
        return {"valid": False, "reason": "block too short"}
    length  = data[0]
    counter = data[1]
    btype   = data[2]
    payload_end = length
    payload = data[3:payload_end] if payload_end > 3 else b""
    return {
        "valid": True,
        "length": length,
        "counter": counter,
        "block_type": btype,
        "type_name": KW1281_EXTENDED_BLOCK_TYPES.get(btype, f"Unknown(0x{btype:02X})"),
        "payload": payload,
    }


def build_kw1281_block(counter: int, block_type: int,
                        payload: bytes = b"") -> bytes:
    """Construye un bloque KW1281 para enviar al módulo."""
    length = 2 + len(payload)
    return bytes([length, counter, block_type]) + payload


# ---------------------------------------------------------------------------
# DECODE SENSORES HONDA COMPLETO
# ---------------------------------------------------------------------------

def honda_decode_rpm(hi: int, lo: int, obd1: bool = False) -> float:
    """Decodifica RPM Honda.
    OBD1: 1875000/(hi*256+lo+1); OBD2: (hi*256+lo)/4.
    """
    raw = hi * 256 + lo
    if obd1:
        return 1875000.0 / (raw + 1)
    return raw / 4.0


def honda_decode_map(raw: int) -> float:
    """MAP en kPa."""
    return raw * 0.716 - 5.0


def honda_decode_baro(raw: int) -> float:
    """Presión barométrica en kPa."""
    return raw * 0.716 - 5.0


def honda_decode_tps(raw: int) -> float:
    """Posición del acelerador en %."""
    return (raw - 24) / 2.0


def honda_decode_o2(raw: int) -> float:
    """Voltaje sensor O2 (0-5 V, lineal)."""
    return raw * 5.0 / 255.0


def honda_decode_battery(raw: int) -> float:
    """Voltaje de batería / alimentación ECU en V."""
    return raw / 10.45


def honda_decode_vss(raw: int) -> float:
    """Velocidad del vehículo en km/h."""
    return float(raw)


def honda_decode_ign_timing(raw: int) -> float:
    """Avance de encendido en grados."""
    return (raw - 24) / 4.0


def honda_decode_injector_pw(hi: int, lo: int) -> float:
    """Ancho de pulso de inyector en ms."""
    return (hi * 256 + lo) / 250.0


def honda_decode_fuel_trim(raw: int) -> float:
    """Trim de combustible en %."""
    return (raw / 128.0 - 1.0) * 100.0


def honda_decode_knock(raw: int) -> float:
    """Corrección de knock."""
    return raw / 51.0


def honda_decode_all_sensors(registers: dict[int, int],
                               obd1: bool = False) -> dict[str, float]:
    """Recibe {dirección: valor_raw} y devuelve sensores decodificados.
    Compatible con HONDA_KLINE_REGISTERS.
    """
    out: dict[str, float] = {}
    if 0x00 in registers and 0x01 in registers:
        out["rpm"] = honda_decode_rpm(registers[0x00], registers[0x01], obd1)
    if 0x04 in registers:
        out["vss_kmh"] = honda_decode_vss(registers[0x04])
    if 0x10 in registers:
        out["ect_celsius"] = honda_temp_convert(registers[0x10])
    if 0x11 in registers:
        out["iat_celsius"] = honda_temp_convert(registers[0x11])
    if 0x12 in registers:
        out["map_kpa"] = honda_decode_map(registers[0x12])
    if 0x13 in registers:
        out["baro_kpa"] = honda_decode_baro(registers[0x13])
    if 0x14 in registers:
        out["tps_pct"] = honda_decode_tps(registers[0x14])
    if 0x15 in registers:
        out["o2_volts"] = honda_decode_o2(registers[0x15])
    if 0x17 in registers:
        out["battery_v"] = honda_decode_battery(registers[0x17])
    if 0x20 in registers:
        out["fuel_trim_st_pct"] = honda_decode_fuel_trim(registers[0x20])
    if 0x22 in registers:
        out["fuel_trim_lt_pct"] = honda_decode_fuel_trim(registers[0x22])
    if 0x26 in registers and 0x27 in registers:
        out["injector_pw_ms"] = honda_decode_injector_pw(registers[0x26], registers[0x27])
    if 0x28 in registers:
        out["ign_timing_deg"] = honda_decode_ign_timing(registers[0x28])
    if 0x3E in registers:
        out["knock_corr"] = honda_decode_knock(registers[0x3E])
    return out


# ---------------------------------------------------------------------------
# HONDA DTC NIBBLE PARSER
# ---------------------------------------------------------------------------

def honda_parse_dtcs_nibble(data: bytes) -> list[str]:
    """Parsea el bloque DTC Honda en dirección 0x40 (14 bytes).
    Cada nibble es un código; valor 0 = sin falla.
    """
    dtcs: list[str] = []
    for byte in data:
        hi = (byte >> 4) & 0x0F
        lo = byte & 0x0F
        if hi != 0:
            dtcs.append(f"Honda{hi:02d}")
        if lo != 0:
            dtcs.append(f"Honda{lo:02d}")
    return dtcs


# ---------------------------------------------------------------------------
# IBUS PARSER CON MÁQUINA DE ESTADOS
# ---------------------------------------------------------------------------

class IBusParserState(IntEnum):
    FIND_SOURCE   = 0
    FIND_LENGTH   = 1
    FIND_MESSAGE  = 2
    GOOD_CHECKSUM = 3
    BAD_CHECKSUM  = 4


IBUS_ALLOWED_SOURCES = {
    0x50, 0x68, 0x18, 0xD5, 0xC8, 0x7F, 0x7C,
}


class IBusParser:
    """Máquina de estados para parsear tramas IBUS en streaming.

    Uso:
        parser = IBusParser()
        frames = parser.feed(bytes_received)
        for f in frames: process(f)
    """

    def __init__(self, filter_sources: bool = True):
        self._state = IBusParserState.FIND_SOURCE
        self._buf: bytearray = bytearray()
        self._expected_length: int = 0
        self._filter_sources = filter_sources

    def reset(self) -> None:
        self._state = IBusParserState.FIND_SOURCE
        self._buf.clear()
        self._expected_length = 0

    def feed(self, data: bytes) -> list[dict]:
        """Alimenta bytes al parser. Retorna lista de tramas completas y válidas."""
        frames: list[dict] = []
        for byte in data:
            frames.extend(self._process_byte(byte))
        return frames

    def _process_byte(self, byte: int) -> list[dict]:
        frames: list[dict] = []

        if self._state == IBusParserState.FIND_SOURCE:
            if not self._filter_sources or byte in IBUS_ALLOWED_SOURCES:
                self._buf.clear()
                self._buf.append(byte)
                self._state = IBusParserState.FIND_LENGTH

        elif self._state == IBusParserState.FIND_LENGTH:
            if byte < 2 or byte > 30:
                self.reset()
            else:
                self._buf.append(byte)
                self._expected_length = byte
                self._state = IBusParserState.FIND_MESSAGE

        elif self._state == IBusParserState.FIND_MESSAGE:
            self._buf.append(byte)
            if len(self._buf) == 2 + self._expected_length:
                frame = self._validate_and_parse()
                if frame:
                    frames.append(frame)
                self.reset()

        return frames

    def _validate_and_parse(self) -> Optional[dict]:
        data = bytes(self._buf)
        if len(data) < 4:
            return None
        source      = data[0]
        length      = data[1]
        destination = data[2]
        payload     = data[3:-1]
        cs_received = data[-1]
        cs_expected = checksum_ibus(data[:-1])
        cs_ok = (cs_received == cs_expected)
        return {
            "source":      source,
            "source_name": IBUS_MODULE_ADDRESSES.get(source, f"0x{source:02X}"),
            "destination": destination,
            "dest_name":   IBUS_MODULE_ADDRESSES.get(destination, f"0x{destination:02X}"),
            "length":      length,
            "payload":     payload,
            "checksum_ok": cs_ok,
            "raw":         data,
        }


# ---------------------------------------------------------------------------
# IBUS FRAME BUILDER EXTENDIDO
# ---------------------------------------------------------------------------

def build_ibus_frame_extended(source: int, destination: int,
                               command: int, data: bytes = b"") -> bytes:
    """Construye trama IBUS con command byte explícito.
    Estructura: [SRC][LEN][DST][CMD][DATA...][XOR].
    """
    payload = bytes([command]) + data
    length  = len(payload) + 2
    frame   = bytes([source, length, destination]) + payload
    cs      = checksum_ibus(frame)
    return frame + bytes([cs])


# ---------------------------------------------------------------------------
# TABLA OBD2 PIDs ESTÁNDAR CON FÓRMULAS
# ---------------------------------------------------------------------------

def decode_pid_04(a: int) -> float:
    """Carga calculada del motor en %."""
    return a * 100.0 / 255.0


def decode_pid_05(a: int) -> float:
    """Temperatura del refrigerante (ECT) en °C."""
    return a - 40.0


def decode_pid_0c(a: int, b: int) -> float:
    """RPM del motor."""
    return (a * 256 + b) / 4.0


def decode_pid_0d(a: int) -> float:
    """Velocidad del vehículo en km/h."""
    return float(a)


def decode_pid_0e(a: int) -> float:
    """Avance de encendido en grados antes del TDC."""
    return a / 2.0 - 64.0


def decode_pid_0f(a: int) -> float:
    """Temperatura del aire de admisión (IAT) en °C."""
    return a - 40.0


def decode_pid_10(a: int, b: int) -> float:
    """Flujo de masa de aire (MAF) en g/s."""
    return (a * 256 + b) / 100.0


def decode_pid_11(a: int) -> float:
    """Posición del acelerador (TPS) en %."""
    return a * 100.0 / 255.0


def decode_pid_1f(a: int, b: int) -> float:
    """Tiempo de funcionamiento del motor en segundos."""
    return float(a * 256 + b)


def decode_pid_2f(a: int) -> float:
    """Nivel de combustible en %."""
    return a * 100.0 / 255.0


def decode_pid_33(a: int) -> float:
    """Presión barométrica en kPa."""
    return float(a)


def decode_pid_42(a: int, b: int) -> float:
    """Voltaje del módulo de control en V."""
    return (a * 256 + b) / 1000.0


def decode_pid_46(a: int) -> float:
    """Temperatura ambiente en °C."""
    return a - 40.0


def decode_pid_5c(a: int) -> float:
    """Temperatura del aceite de motor en °C."""
    return a - 40.0


def decode_pid_5e(a: int, b: int) -> float:
    """Consumo de combustible en L/h."""
    return (a * 256 + b) * 0.05


OBD2_PID_DECODERS: dict[int, tuple] = {
    0x04: ("engine_load_pct",     1, decode_pid_04),
    0x05: ("ect_celsius",         1, decode_pid_05),
    0x0C: ("rpm",                 2, decode_pid_0c),
    0x0D: ("vss_kmh",             1, decode_pid_0d),
    0x0E: ("ignition_timing_deg", 1, decode_pid_0e),
    0x0F: ("iat_celsius",         1, decode_pid_0f),
    0x10: ("maf_g_s",             2, decode_pid_10),
    0x11: ("tps_pct",             1, decode_pid_11),
    0x1F: ("engine_runtime_s",    2, decode_pid_1f),
    0x2F: ("fuel_level_pct",      1, decode_pid_2f),
    0x33: ("baro_kpa",            1, decode_pid_33),
    0x42: ("module_voltage_v",    2, decode_pid_42),
    0x46: ("ambient_temp_c",      1, decode_pid_46),
    0x5C: ("oil_temp_c",          1, decode_pid_5c),
    0x5E: ("fuel_rate_l_h",       2, decode_pid_5e),
}


def decode_obd2_pid(pid: int, response_bytes: bytes) -> Optional[dict]:
    """Decodifica la respuesta a un PID OBD2 estándar.
    Retorna dict con 'name' y 'value', o None si PID desconocido.
    """
    if pid not in OBD2_PID_DECODERS:
        return None
    name, num_bytes, fn = OBD2_PID_DECODERS[pid]
    if len(response_bytes) < num_bytes:
        return None
    args = list(response_bytes[:num_bytes])
    return {"name": name, "value": fn(*args), "pid": pid}


# ---------------------------------------------------------------------------
# RING BUFFER (pyserial helper)
# ---------------------------------------------------------------------------

class RingBuffer:
    """Buffer circular de bytes para acumular datos de puerto serie sin bloquear."""

    def __init__(self, maxlen: int = 512):
        self._buf: deque[int] = deque(maxlen=maxlen)

    def write(self, data: bytes) -> None:
        for b in data:
            self._buf.append(b)

    def read(self, n: int) -> bytes:
        out = bytearray()
        for _ in range(min(n, len(self._buf))):
            out.append(self._buf.popleft())
        return bytes(out)

    def peek(self, n: int) -> bytes:
        return bytes(list(self._buf)[:n])

    def available(self) -> int:
        return len(self._buf)

    def clear(self) -> None:
        self._buf.clear()


# ---------------------------------------------------------------------------
# UTILIDADES GENERALES
# ---------------------------------------------------------------------------

def bytes_to_hex_string(data: bytes) -> str:
    """Convierte bytes a string hexadecimal con espacios (para debug)."""
    return " ".join(f"{b:02X}" for b in data)


def hex_to_ascii(data: bytes) -> str:
    """Convierte bytes a ASCII imprimible.
    Bytes fuera de 0x20-0x7E se reemplazan por '.'.
    """
    return "".join(chr(b) if 0x20 <= b <= 0x7E else "." for b in data)


def compare_data(a: bytes, b: bytes) -> bool:
    """Compara dos secuencias de bytes."""
    return a == b


def is_in_array(data: bytes, value: int) -> bool:
    """Retorna True si value está en data."""
    return value in data
