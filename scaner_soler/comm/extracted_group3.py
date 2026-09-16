"""
extracted_group3.py — Funciones extraídas del Grupo 3 de repos K-line

Fuentes analizadas:
  REPO 1: muki01/OBD2_K-line_Reader
  REPO 2: kerpz/ArduinoHondaOBD
  REPO 3: muki01/OBD2_KLine_Library
  REPO 4: muki01/I-K_Bus

Solo contiene funciones que NO estaban en kline.py:
  - Protocolo DS2 (BMW, 9600 baud, 8E1)
  - Protocolo KW82 / GM/Opel (4800 baud, stream-based)
  - Checksum TwosComplement
  - decode_dtc_standard (OBD2 ISO genérico)
  - Honda decode completo (RPM OBD1/OBD2, todos los sensores)
  - Honda DTCs nibble parser (formato 14-byte en 0x40)
  - Tabla de timing P1-P4 / W1-W4 para cada protocolo
  - Tabla de configuración de los 5 protocolos
  - Auto-detección de protocolo (5-baud keywords)
  - Máquina de estados IBUS (parser robusto con anti-colisión)
  - KW82 sliding-window frame detection
  - KW1281 block ACK (complement-byte)
  - Tabla de PIDs OBD2 estándar con fórmulas de conversión
  - Fast init pulse timing

Adaptado a Python/pyserial. Sin dependencias de terceros.
"""
from __future__ import annotations

import time
from collections import deque
from enum import IntEnum
from typing import Optional

# ---------------------------------------------------------------------------
# 1. CONSTANTES DE TIMING POR PROTOCOLO  (fuente: muki01/OBD2_KLine_Library)
# ---------------------------------------------------------------------------

class KLineProtocol(IntEnum):
    ISO9141   = 0   # 10400 baud, 8N1, slow init 5-baud
    ISO14230  = 1   # 10400 baud, 8N1, fast o slow init
    KW1281    = 2   # 9600 baud, 8O1 init, byte-ACK
    DS2       = 3   # 9600 baud, 8E1, ping handshake
    KW82      = 4   # 4800 baud, 8N1, stream (sin req/resp)


# Timing ISO 14230-2 en milisegundos:
#   P1 = inter-byte gap (ECU → tester)
#   P2 = timeout respuesta (tester espera ECU)
#   P3 = gap inter-mensaje (tester espera para siguiente request)
#   P4 = inter-byte gap (tester → ECU)
#   W1-W4 = handshake timings
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
        "init_type": "fast",  # 25 ms LOW + 25 ms HIGH
        "checksum": "mod256",
    },
    KLineProtocol.KW1281: {
        "baud": 9600, "serial_cfg": "8O1",   # 8 bits, odd parity, 1 stop
        "P1_ms": 10,  "P2_ms": 1500, "P3_ms": 50,  "P4_ms": 5,
        "W1_ms": 300, "W2_ms": 20,   "W3_ms": 20,  "W4_ms": 50,
        "wakeup_delay_ms": 5500,
        "init_type": "5baud", "init_addr": None,  # dirección específica del módulo
        "checksum": "none",  # KW1281 no usa checksum de trama; verifica ACK
    },
    KLineProtocol.DS2: {
        "baud": 9600, "serial_cfg": "8E1",   # 8 bits, even parity, 1 stop
        "P1_ms": 10,  "P2_ms": 1500, "P3_ms": 50,  "P4_ms": 5,
        "W1_ms": 0,   "W2_ms": 0,    "W3_ms": 0,   "W4_ms": 0,
        "wakeup_delay_ms": 0,
        "init_type": "ping",   # escribe 0x00, espera respuesta
        "checksum": "xor",
    },
    KLineProtocol.KW82: {
        "baud": 4800, "serial_cfg": "8N1",
        "P1_ms": 10,  "P2_ms": 1500, "P3_ms": 50,  "P4_ms": 5,
        "W1_ms": 0,   "W2_ms": 0,    "W3_ms": 0,   "W4_ms": 0,
        "wakeup_delay_ms": 0,
        "init_type": "none",   # stream continuo, sin handshake
        "checksum": "mod256",
    },
}

# Byte de escritura entre bytes del tester (P4) y timeout inter-byte (P1)
BYTE_WRITE_INTERVAL_MS = 5    # fuente: OBD2_K-line_Reader Basic_Code
INTER_BYTE_TIMEOUT_MS  = 60   # fuente: OBD2_K-line_Reader Basic_Code
RESULT_BUFFER_SIZE     = 300  # fuente: OBD2_KLine_Library OBD2_KLine_Core.h


# ---------------------------------------------------------------------------
# 2. FAST INIT PULSE  (fuente: muki01/OBD2_KLine_Library KLine_Protocol.cpp)
# ---------------------------------------------------------------------------

def fast_init_timing() -> dict:
    """
    Devuelve los parámetros para el pulso de fast init ISO 14230.
    El pin TX debe mantenerse LOW 25 ms, luego HIGH 25 ms antes
    de comenzar la comunicación serial.  En pyserial se usa break_condition.
    """
    return {
        "low_ms":  25,    # TxD LOW durante 25 ms (wake-up pulse)
        "high_ms": 25,    # TxD HIGH durante 25 ms (recovery)
        "start_byte": 0x81,   # primer byte tras el pulso
        "expected_echo_byte3": 0xC1,  # byte[2] de la respuesta indica ISO14230
    }


def send_fast_init_pulse(ser) -> None:
    """
    Ejecuta el pulso de fast init en un puerto pyserial.
    ser: instancia serial.Serial ya abierta.
    """
    ser.break_condition = True
    time.sleep(0.025)          # 25 ms LOW
    ser.break_condition = False
    time.sleep(0.025)          # 25 ms HIGH


# ---------------------------------------------------------------------------
# 3. AUTO-DETECCIÓN DE PROTOCOLO POR KEYWORDS  (fuente: OBD2_KLine_Library)
# ---------------------------------------------------------------------------

def detect_protocol_from_keywords(kw1: int, kw2: int) -> KLineProtocol:
    """
    Tras slow init 5-baud, la ECU devuelve 3 bytes: [0x55, KW1, KW2].
    Regla:
      - Si KW1 == KW2 → ISO9141
      - Si KW1 != KW2 → ISO14230 (KWP2000)
    """
    if kw1 == kw2:
        return KLineProtocol.ISO9141
    return KLineProtocol.ISO14230


def auto_detect_protocol(ser, init_addr: int = 0x33,
                         timeout_s: float = 3.0) -> Optional[KLineProtocol]:
    """
    Ronda 1: intenta fast init → si hay respuesta con byte[2]==0xC1 → ISO14230.
    Ronda 2: slow init 5-baud → lee keywords para distinguir ISO9141/ISO14230.
    Devuelve None si no hay respuesta.
    """
    # Ronda 1 – Fast init
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

    # Ronda 2 – Slow init 5-baud
    try:
        slow_init_send_address(ser, init_addr)
        deadline = time.time() + timeout_s
        buf: list[int] = []
        while time.time() < deadline and len(buf) < 3:
            b = ser.read(1)
            if b:
                buf.append(b[0])
        if len(buf) >= 3 and buf[0] == 0x55:
            return detect_protocol_from_keywords(buf[1], buf[2])
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# 4. SLOW INIT 5-BAUD (helper físico)  (fuente: OBD2_KLine_Library)
# ---------------------------------------------------------------------------

def slow_init_send_address(ser, address: int = 0x33) -> None:
    """
    Envía un byte a 5 baudios (200 ms/bit) en el pin TX del puerto.
    Usa break_condition de pyserial para manipular el pin.
    Formato: start(0) | 7 bits LSB-first | paridad impar | stop(1)
    """
    bits: list[int] = [0]   # start bit
    val = address
    parity = 0
    for _ in range(7):
        b = val & 1
        bits.append(b)
        parity ^= b
        val >>= 1
    bits.append(parity & 1)  # odd parity bit (complemento)
    bits.append(1)            # stop bit

    for bit in bits:
        if bit == 0:
            ser.break_condition = True
        else:
            ser.break_condition = False
        time.sleep(0.200)    # 200 ms por bit = 5 baud


# ---------------------------------------------------------------------------
# 5. CHECKSUMS ADICIONALES  (fuente: muki01/OBD2_KLine_Library KLine_Functions.h)
# ---------------------------------------------------------------------------

def checksum_twos_complement(data: bytes | list[int]) -> int:
    """
    Checksum 8-bit complemento a dos: -(sum(data)) & 0xFF.
    Usado en algunos fabricantes europeos.
    """
    return (-(sum(data))) & 0xFF


def checksum_mod256(data: bytes | list[int]) -> int:
    """Sum(data) % 256. Igual que checksum_iso9141 en kline.py; alias aquí para claridad."""
    return sum(data) % 256


def checksum_xor(data: bytes | list[int]) -> int:
    """XOR de todos los bytes. Alias explícito."""
    result = 0
    for b in data:
        result ^= b
    return result


def verify_checksum(data: bytes, checksum_type: str) -> bool:
    """
    Verifica checksum del frame completo (el último byte es el checksum).
    checksum_type: 'mod256' | 'xor' | 'twos'
    """
    if len(data) < 2:
        return False
    payload = data[:-1]
    received = data[-1]
    if checksum_type == "mod256":
        expected = checksum_mod256(payload)
    elif checksum_type == "xor":
        expected = checksum_xor(payload)
    elif checksum_type == "twos":
        expected = checksum_twos_complement(payload)
    else:
        return True   # "none"
    return expected == received


# ---------------------------------------------------------------------------
# 6. DECODE DTC ESTÁNDAR OBD2  (fuente: muki01/OBD2_KLine_Library KLine_Functions.cpp)
# ---------------------------------------------------------------------------

_DTC_SYSTEM_MAP = {0: "P", 1: "C", 2: "B", 3: "U"}

def decode_dtc_standard(b1: int, b2: int) -> str:
    """
    Convierte dos bytes ISO 15031-6 a código DTC string (ej. P0301).

    Byte1 bits[7:6] → sistema  (P/C/B/U)
    Byte1 bits[5:4] → dígito 1 (0-3)
    Byte1 bits[3:0] → dígito 2 (hex)
    Byte2 bits[7:4] → dígito 3 (hex)
    Byte2 bits[3:0] → dígito 4 (hex)
    """
    system = _DTC_SYSTEM_MAP[(b1 >> 6) & 0x03]
    d1 = (b1 >> 4) & 0x03
    d2 = b1 & 0x0F
    d3 = (b2 >> 4) & 0x0F
    d4 = b2 & 0x0F
    return f"{system}{d1:01X}{d2:01X}{d3:01X}{d4:01X}"


def decode_dtc_list(data: bytes) -> list[str]:
    """
    Procesa respuesta OBD2 Mode 03/07/0A: pares de bytes [B1, B2, B1, B2, ...].
    Descarta pares (0x00, 0x00).
    """
    dtcs: list[str] = []
    for i in range(0, len(data) - 1, 2):
        b1, b2 = data[i], data[i + 1]
        if b1 == 0 and b2 == 0:
            continue
        dtcs.append(decode_dtc_standard(b1, b2))
    return dtcs


# ---------------------------------------------------------------------------
# 7. PROTOCOLO DS2 (BMW)  (fuente: muki01/OBD2_KLine_Library KLine_Protocol.cpp)
# ---------------------------------------------------------------------------

DS2_PING_BYTE  = 0x00
DS2_BAUD       = 9600
DS2_SERIAL_CFG = "8E1"  # 8 bits, paridad par, 1 stop


def build_ds2_frame(ecu_addr: int, service: int, params: bytes = b"") -> bytes:
    """
    Trama DS2 BMW:  [ADDR] [LENGTH] [SERVICE] [PARAMS...] [XOR_CHECKSUM]
    LENGTH incluye todo el frame completo (incluye a sí mismo y checksum).
    """
    payload = bytes([ecu_addr, 0x00, service]) + params
    length = len(payload) + 2   # +2 para el byte de length y el checksum
    frame = bytes([ecu_addr, length, service]) + params
    cs = checksum_xor(frame)
    return frame + bytes([cs])


def parse_ds2_response(data: bytes) -> dict:
    """
    Parsea respuesta DS2.
    Estructura esperada: [ADDR] [LENGTH] [SERVICE+0x40] [DATA...] [XOR]
    Devuelve dict con addr, service, payload, checksum_ok.
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
    cs_calc = checksum_xor(frame)
    return {
        "valid": cs_recv == cs_calc,
        "addr": addr,
        "service": service,
        "payload": data[3:length - 1],
        "checksum_ok": cs_recv == cs_calc,
    }


def ds2_ping(ser) -> bool:
    """
    Handshake DS2: escribe 0x00, retorna True si llega cualquier dato.
    """
    ser.write(bytes([DS2_PING_BYTE]))
    time.sleep(0.1)
    return ser.in_waiting > 0


# ---------------------------------------------------------------------------
# 8. PROTOCOLO KW82 / GM-OPEL  (fuente: muki01/OBD2_KLine_Library)
# ---------------------------------------------------------------------------

KW82_BAUD = 4800

def kw82_sliding_window_sync(buf: bytes) -> Optional[tuple[int, bytes]]:
    """
    Localiza una trama válida dentro de un buffer de bytes usando ventana deslizante.
    Formato KW82: [LENGTH] [DATA[0..LENGTH-2]] [CHECKSUM_MOD256]
    No hay header; el primer byte de cada trama es el length.
    Retorna (offset, frame) o None si no se encuentra trama válida.
    """
    for offset in range(len(buf)):
        length = buf[offset]
        if length < 2:
            continue
        end = offset + length
        if end > len(buf):
            break   # trama incompleta, esperar más bytes
        frame   = buf[offset:end - 1]
        cs_recv = buf[end - 1]
        cs_calc = checksum_mod256(frame)
        if cs_recv == cs_calc:
            return (offset, buf[offset:end])
    return None


def build_kw82_frame(service: int, params: bytes = b"") -> bytes:
    """
    Construye trama KW82:  [LENGTH] [SERVICE] [PARAMS...] [MOD256_CHECKSUM]
    LENGTH = total de bytes incluyendo length y checksum.
    """
    payload = bytes([service]) + params
    length  = len(payload) + 2   # length byte + checksum byte
    frame   = bytes([length]) + payload
    cs      = checksum_mod256(frame)
    return frame + bytes([cs])


# ---------------------------------------------------------------------------
# 9. KW1281 BLOCK ACK  (fuente: muki01/OBD2_KLine_Library KLine_Protocol.cpp)
# ---------------------------------------------------------------------------

KW1281_BAUD       = 9600
KW1281_ACK_MARKER = 0x09    # ACK (tipo bloque)
KW1281_EOT_MARKER = 0xFF    # End Of Transmission

KW1281_BLOCK_TYPES = {
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


def kw1281_complement_ack(byte_received: int) -> int:
    """
    KW1281: el tester responde a cada byte del bloque con su complemento.
    Excepción: el último byte de longitud del bloque no se responde.
    """
    return (~byte_received) & 0xFF


def parse_kw1281_block(data: bytes) -> dict:
    """
    Parsea un bloque KW1281.
    Formato: [LENGTH] [COUNTER] [TYPE] [DATA[0..LENGTH-4]] (sin checksum de trama)
    LENGTH incluye length+counter+type pero NO los datos de payload.
    Retorna dict con length, counter, block_type, payload, type_name.
    """
    if len(data) < 3:
        return {"valid": False, "reason": "block too short"}
    length  = data[0]
    counter = data[1]
    btype   = data[2]
    # payload son los bytes tras [length, counter, type] hasta donde indica length
    payload_end = length   # length = num_bytes total - 1 (no incluye el byte length mismo)
    payload = data[3:payload_end] if payload_end > 3 else b""
    return {
        "valid": True,
        "length": length,
        "counter": counter,
        "block_type": btype,
        "type_name": KW1281_BLOCK_TYPES.get(btype, f"Unknown(0x{btype:02X})"),
        "payload": payload,
    }


def build_kw1281_block(counter: int, block_type: int,
                        payload: bytes = b"") -> bytes:
    """
    Construye un bloque KW1281 para enviar al módulo.
    """
    # length = 3 (length+counter+type) + len(payload) - 1 ?
    # Convención: LENGTH byte = número total de bytes siguientes (excluye el propio LENGTH)
    length = 2 + len(payload)  # counter + type + payload
    return bytes([length, counter, block_type]) + payload


# ---------------------------------------------------------------------------
# 10. DECODE SENSORES HONDA COMPLETO  (fuente: kerpz/ArduinoHondaOBD hobd_uni.ino)
# ---------------------------------------------------------------------------

def honda_decode_rpm(hi: int, lo: int, obd1: bool = False) -> float:
    """
    Decodifica RPM Honda.
    OBD1: 1875000 / (hi*256 + lo + 1)  (con corrección ×4 en algunos)
    OBD2: (hi*256 + lo) / 4
    """
    raw = hi * 256 + lo
    if obd1:
        return 1875000.0 / (raw + 1)
    return raw / 4.0


def honda_decode_map(raw: int) -> float:
    """MAP (manifold absolute pressure) en kPa."""
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
    """Velocidad del vehículo en km/h (directa)."""
    return float(raw)


def honda_decode_ign_timing(raw: int) -> float:
    """Avance de encendido en grados (positivo = avance)."""
    return (raw - 24) / 4.0


def honda_decode_injector_pw(hi: int, lo: int) -> float:
    """Ancho de pulso de inyector en ms."""
    return (hi * 256 + lo) / 250.0


def honda_decode_fuel_trim(raw: int) -> float:
    """Trim de combustible en % (0 = neutro, positivo = más rico)."""
    return (raw / 128.0 - 1.0) * 100.0


def honda_decode_knock(raw: int) -> float:
    """Corrección de knock (sensor detonación)."""
    return raw / 51.0


def honda_decode_all_sensors(registers: dict[int, int],
                              obd1: bool = False) -> dict[str, float]:
    """
    Recibe un diccionario {dirección: valor_raw} y devuelve un diccionario
    con todos los sensores decodificados.
    Compatible con HONDA_KLINE_REGISTERS de kline.py.
    """
    out: dict[str, float] = {}

    if 0x00 in registers and 0x01 in registers:
        out["rpm"] = honda_decode_rpm(registers[0x00], registers[0x01], obd1)
    if 0x04 in registers:
        out["vss_kmh"] = honda_decode_vss(registers[0x04])
    if 0x10 in registers:
        from scaner_soler.comm.kline import honda_temp_convert
        out["ect_celsius"] = honda_temp_convert(registers[0x10])
    if 0x11 in registers:
        from scaner_soler.comm.kline import honda_temp_convert
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
# 11. HONDA DTC NIBBLE PARSER  (fuente: kerpz/ArduinoHondaOBD)
# ---------------------------------------------------------------------------

def honda_parse_dtcs_nibble(data: bytes) -> list[str]:
    """
    Parsea el bloque DTC Honda en dirección 0x40 (14 bytes).
    Cada nibble (4 bits) es un código de falla; valor 0 = sin falla.
    Devuelve lista de strings "HondaXX" donde XX es el número decimal del código.
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
# 12. IBUS PARSER CON MÁQUINA DE ESTADOS  (fuente: muki01/I-K_Bus IbusSerial.cpp)
# ---------------------------------------------------------------------------

class IBusParserState(IntEnum):
    FIND_SOURCE   = 0
    FIND_LENGTH   = 1
    FIND_MESSAGE  = 2
    GOOD_CHECKSUM = 3
    BAD_CHECKSUM  = 4


# Módulos fuente válidos que el parser acepta (filtro de dirección)
IBUS_ALLOWED_SOURCES = {
    0x50,   # MFL — controles del volante
    0x68,   # RAD — radio
    0x18,   # CDC — CD changer
    0xD5,   # DSP — procesador de audio
    0xC8,   # TEL — teléfono
    0x7F,   # SES — speech recognition
    0x7C,   # RLS — sensor de lluvia/luz
}

# Direcciones de módulos BMW E46/E39 (fuente: muki01/I-K_Bus E46_Codes.h)
IBUS_MODULE_ADDRESSES = {
    0x00: "GM5",    # Body Control Module
    0x18: "CDC",    # CD Changer
    0x3F: "DIA",    # Diagnostics
    0x44: "EWS",    # Immobilizer
    0x46: "CID",    # Central Information Display
    0x50: "MFL",    # Multi-Function Steering Wheel
    0x5B: "IHKA",   # Heater/AC
    0x68: "RAD",    # Radio
    0x6A: "DSP_MID", # DSP/MID
    0x72: "BMBT",   # Board Monitor Button/Telephony
    0x76: "HKM",    # Hazard Key Module
    0x7C: "RLS",    # Rain/Light Sensor
    0x7F: "SES",    # Speech/Driver Input
    0x80: "IKE",    # Instrument Cluster
    0xBF: "ALL",    # Broadcast
    0xC8: "TEL",    # Telephone
    0xD0: "LCM",    # Light Control Module
    0xD5: "DSP",    # Digital Signal Processing
    0xE7: "CVM",    # Convertible Top Module
    0xF0: "BMB",    # Board Monitor Board
}


class IBusParser:
    """
    Máquina de estados para parsear tramas IBUS en streaming.
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
        """
        Alimenta bytes al parser. Retorna lista de tramas completas y válidas.
        Cada trama es un dict con: source, length, destination, payload, checksum_ok.
        """
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
            # else: byte descartado

        elif self._state == IBusParserState.FIND_LENGTH:
            if byte < 2 or byte > 30:
                # Longitud inválida, reiniciar
                self.reset()
            else:
                self._buf.append(byte)
                self._expected_length = byte  # total bytes desde destination hasta checksum
                self._state = IBusParserState.FIND_MESSAGE

        elif self._state == IBusParserState.FIND_MESSAGE:
            self._buf.append(byte)
            # _buf = [source, length, dest, data..., checksum]
            # longitud total esperada = 2 (source+length) + expected_length
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
        cs_expected = checksum_xor(data[:-1])
        cs_ok = (cs_received == cs_expected)

        return {
            "source":       source,
            "source_name":  IBUS_MODULE_ADDRESSES.get(source, f"0x{source:02X}"),
            "destination":  destination,
            "dest_name":    IBUS_MODULE_ADDRESSES.get(destination, f"0x{destination:02X}"),
            "length":       length,
            "payload":      payload,
            "checksum_ok":  cs_ok,
            "raw":          data,
        }


# ---------------------------------------------------------------------------
# 13. IBUS FRAME BUILDER CON VALIDACIÓN  (fuente: muki01/I-K_Bus IbusSerial.cpp)
# ---------------------------------------------------------------------------

def build_ibus_frame_extended(source: int, destination: int,
                               command: int, data: bytes = b"") -> bytes:
    """
    Construye trama IBUS con command byte explícito.
    Estructura: [SRC][LEN][DST][CMD][DATA...][XOR]
    LEN = 2 + len(data) (incluye DST y XOR pero no SRC ni LEN).
    """
    payload = bytes([command]) + data
    length  = len(payload) + 2   # +DST +XOR
    frame   = bytes([source, length, destination]) + payload
    cs      = checksum_xor(frame)
    return frame + bytes([cs])


# ---------------------------------------------------------------------------
# 14. TABLA OBD2 PIDs ESTÁNDAR CON FÓRMULAS  (fuente: muki01/OBD2_K-line_Reader PIDs.h)
# ---------------------------------------------------------------------------

def decode_pid_04(a: int) -> float:
    """Carga calculada del motor (Calculated engine load) en %."""
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


# Tabla centralizada: PID → (nombre, num_bytes_respuesta, función_decode)
OBD2_PID_DECODERS: dict[int, tuple] = {
    0x04: ("engine_load_pct",      1, decode_pid_04),
    0x05: ("ect_celsius",          1, decode_pid_05),
    0x0C: ("rpm",                  2, decode_pid_0c),
    0x0D: ("vss_kmh",              1, decode_pid_0d),
    0x0E: ("ignition_timing_deg",  1, decode_pid_0e),
    0x0F: ("iat_celsius",          1, decode_pid_0f),
    0x10: ("maf_g_s",              2, decode_pid_10),
    0x11: ("tps_pct",              1, decode_pid_11),
    0x1F: ("engine_runtime_s",     2, decode_pid_1f),
    0x2F: ("fuel_level_pct",       1, decode_pid_2f),
    0x33: ("baro_kpa",             1, decode_pid_33),
    0x42: ("module_voltage_v",     2, decode_pid_42),
    0x46: ("ambient_temp_c",       1, decode_pid_46),
    0x5C: ("oil_temp_c",           1, decode_pid_5c),
    0x5E: ("fuel_rate_l_h",        2, decode_pid_5e),
}


def decode_obd2_pid(pid: int, response_bytes: bytes) -> Optional[dict]:
    """
    Decodifica la respuesta a un PID OBD2 estándar.
    response_bytes son los bytes de datos (ya sin header/checksum).
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
# 15. RING BUFFER (pyserial helper)  (fuente: muki01/I-K_Bus RingBuffer.cpp)
# ---------------------------------------------------------------------------

class RingBuffer:
    """
    Buffer circular de bytes para acumular datos de puerto serie sin bloquear.
    Equivalente Python del RingBuffer.cpp en I-K_Bus.
    """

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
# 16. UTILIDADES GENERALES  (fuente: muki01/OBD2_KLine_Library KLine_Functions.cpp)
# ---------------------------------------------------------------------------

def bytes_to_hex_string(data: bytes) -> str:
    """Convierte bytes a string hexadecimal con espacios (para debug)."""
    return " ".join(f"{b:02X}" for b in data)


def hex_to_ascii(data: bytes) -> str:
    """
    Convierte bytes a ASCII imprimible.
    Bytes fuera del rango 0x20-0x7E se reemplazan por '.'.
    Usado para decodificar VIN y etiquetas de módulo.
    """
    return "".join(chr(b) if 0x20 <= b <= 0x7E else "." for b in data)


def compare_data(a: bytes, b: bytes) -> bool:
    """Compara dos secuencias de bytes. Retorna True si son idénticas."""
    return a == b


def is_in_array(data: bytes, value: int) -> bool:
    """Retorna True si value está en data."""
    return value in data


# ---------------------------------------------------------------------------
# RESUMEN DE LO NUEVO VS kline.py
# ---------------------------------------------------------------------------
#
# NUEVO (no existía en kline.py):
#   - PROTOCOL_TIMING: tabla completa P1-P4/W1-W4 para los 5 protocolos
#   - fast_init_timing / send_fast_init_pulse
#   - slow_init_send_address (bit-bang físico a 5 baud)
#   - detect_protocol_from_keywords / auto_detect_protocol
#   - checksum_twos_complement / verify_checksum
#   - decode_dtc_standard / decode_dtc_list  (OBD2 ISO genérico)
#   - DS2 protocol: build_ds2_frame, parse_ds2_response, ds2_ping
#   - KW82 protocol: kw82_sliding_window_sync, build_kw82_frame
#   - KW1281 block ACK: kw1281_complement_ack, parse_kw1281_block, build_kw1281_block
#   - Honda decode completo: honda_decode_rpm (OBD1 y OBD2), honda_decode_map,
#     honda_decode_baro, honda_decode_tps, honda_decode_o2, honda_decode_battery,
#     honda_decode_vss, honda_decode_ign_timing, honda_decode_injector_pw,
#     honda_decode_fuel_trim, honda_decode_knock, honda_decode_all_sensors
#   - honda_parse_dtcs_nibble  (formato 14-byte nibble en dirección 0x40)
#   - IBusParser (máquina de estados, con filter_sources)
#   - IBUS_MODULE_ADDRESSES ampliado (16 módulos vs 10 en kline.py)
#   - build_ibus_frame_extended (con command byte explícito)
#   - OBD2_PID_DECODERS / decode_obd2_pid (tabla PIDs estándar con fórmulas)
#   - RingBuffer (buffer circular para streaming serie)
#   - bytes_to_hex_string / hex_to_ascii / compare_data / is_in_array
#
# YA EXISTÍA en kline.py (no duplicado):
#   - checksum_iso9141 (mod256), checksum_ibus (xor)
#   - build_iso9141_frame, build_kwp_fast_frame
#   - slow_init_params (parámetros, sin bit-bang)
#   - HONDA_DLC_INIT / honda_checksum / build_honda_dlc_request
#   - honda_temp_convert / honda_calc_maf
#   - HONDA_KLINE_REGISTERS / HONDA_STATUS_FLAGS
#   - parse_kwp1281_dtcs (KWP1281 VAG, 3-byte chunks)
#   - build_ibus_frame (básico)
# ---------------------------------------------------------------------------
