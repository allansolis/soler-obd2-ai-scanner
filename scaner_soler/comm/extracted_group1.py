"""
Funciones extraídas e integradas de repos GitHub — Grupo 1:

- jgamblin/CarHackingTools:
    Solo contiene scripts de instalación (Ubuntu), sin código OBD original.
    Veredicto: nada que extraer; sirve como referencia de herramientas del
    ecosistema (can-utils, SavvyCAN, CaringCaribou).

- Ircama/ELM327-emulator:
    IsoTpMultiframe — ensamblado/despiece de tramas ISO 15765-2 (SF/FF/CF).
    KWP2000Checksum — cálculo de checksum modulo-256 para ISO 14230.
    FlowControlFrame — generación de trama FC (30 00 00) para ISO-TP.
    INTEGRAR EN: scaner_soler/comm/ (usadas por elm327.py y kline.py cuando
    el mensaje supera 7 bytes, p.ej. lectura de VIN).

- provrb/obdium (Rust/Tauri):
    SupportedPIDScanner — detección jerárquica de PIDs soportados via rangos
    0x00/0x20/0x40/0x60/0x80/0xA0/0xC0 con parseo de bitmask 32 bits.
    FreezFrameSwitcher — sustitución automática service-01 → service-02 para
    Freeze Frame sin duplicar lógica de decodificación.
    DemoReplay — modo offline que reproduce pares request/response guardados.
    INTEGRAR EN: scaner_soler/comm/elm327.py (scan_supported_pids),
    scaner_soler/diagnostic/ (freeze frame support).

- rzetterberg/elmobd (Go):
    MonitorStatusParser — extrae MIL (bit 7) y conteo DTC (bits 0-6) de PID 0x01.
    PartSupportedBitmask — SupportsPID() con desplazamiento de bits por parte.
    ResponseValidator — verifica echo de modo (modo+0x40) y echo de PID.
    INTEGRAR EN: scaner_soler/comm/elm327.py (validación de respuestas),
    scaner_soler/ecu/pid_registry.py (soporte de PIDs).
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# =============================================================================
# 1. ISO-TP MULTIFRAME ASSEMBLY  (extraído de Ircama/ELM327-emulator)
#    Referencia: elm/elm.py — clase IsoTpMultiframe
# =============================================================================

class IsoTpMultiframe:
    """
    Ensamblador/despiece de tramas ISO 15765-2 (ISO-TP).

    Maneja los tres tipos de trama:
      - Single Frame  (SF): primer nibble = 0x0
      - First Frame   (FF): primer nibble = 0x1
      - Consecutive   (CF): primer nibble = 0x2

    Uso:
        mf = IsoTpMultiframe()
        # Para SF: mf.feed_hex("0703014E...") → bytes completos o None
        # Para FF+CF: llamar feed_hex en cada trama, None hasta completar.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._payload_hex: str = ""
        self._expected_len: int = 0
        self._next_sn: int = 1      # sequence number esperado para CF
        self._complete: bool = False

    @property
    def is_complete(self) -> bool:
        return self._complete

    def feed_hex(self, hex_str: str) -> Optional[bytes]:
        """
        Alimenta una trama (hex sin espacios).
        Devuelve bytes del payload completo cuando se ensambla, None si faltan tramas.
        """
        hex_str = hex_str.replace(" ", "").upper()
        if len(hex_str) < 2:
            return None

        frame_type = int(hex_str[0], 16)

        if frame_type == 0:          # Single Frame
            data_len = int(hex_str[1], 16)
            payload = hex_str[2:2 + data_len * 2]
            self._complete = True
            return bytes.fromhex(payload)

        elif frame_type == 1:        # First Frame
            self._expected_len = int(hex_str[1:4], 16)
            self._payload_hex = hex_str[4:]
            self._next_sn = 1
            self._complete = False
            return None              # esperar Consecutive Frames

        elif frame_type == 2:        # Consecutive Frame
            sn = int(hex_str[1], 16)
            if sn != (self._next_sn & 0xF):
                # Error de secuencia — reiniciar
                self.reset()
                return None
            self._payload_hex += hex_str[2:]
            self._next_sn = (self._next_sn + 1) & 0xF
            # Comprobar si hemos acumulado suficientes bytes
            accumulated = len(self._payload_hex) // 2
            if accumulated >= self._expected_len:
                complete_hex = self._payload_hex[:self._expected_len * 2]
                self._complete = True
                return bytes.fromhex(complete_hex)
            return None

        # Trama desconocida
        return None

    @staticmethod
    def build_flow_control(block_size: int = 0, st_min_ms: int = 0) -> str:
        """
        Genera la trama Flow Control (FC) para responder a un First Frame.

        block_size=0 → CTS sin límite de bloques
        st_min_ms   → separación mínima entre CF en ms (0 = lo más rápido posible)

        Devuelve hex listo para enviar por serial, ej. '30 00 00'.
        """
        fc_flag = 0x30          # Continue To Send
        bs_byte = block_size & 0xFF
        stmin_byte = st_min_ms & 0x7F   # 0x00-0x7F → 0-127 ms
        return f"{fc_flag:02X} {bs_byte:02X} {stmin_byte:02X}"


# =============================================================================
# 2. KWP2000 CHECKSUM  (extraído de Ircama/ELM327-emulator)
#    Referencia: elm/elm.py — método uds_answer, sección KWP2000 format
# =============================================================================

def kwp2000_checksum(data_bytes: bytes | list[int]) -> int:
    """
    Calcula el checksum KWP2000 / ISO 14230-2.

    El checksum es la suma módulo-256 de todos los bytes del mensaje
    (cabecera + datos) sin incluir el propio byte de checksum.

    Uso:
        msg = bytes([0x82, 0xF1, 0x01, 0x3E])
        cs  = kwp2000_checksum(msg)  # → 0x12
        frame = msg + bytes([cs])
    """
    return sum(data_bytes) & 0xFF


def kwp2000_build_request(
    service_id: int,
    data: bytes = b"",
    tester_addr: int = 0xF1,
    ecu_addr: int = 0x01,
) -> bytes:
    """
    Construye un frame KWP2000 con cabecera 3-byte y checksum.

    Formato (ISO 14230-2, dirección física):
      [LEN_FLAG | length]  [TARGET]  [SOURCE]  [SID]  [DATA...]  [CS]
    """
    payload = bytes([service_id]) + data
    length = len(payload)
    # LEN_FLAG: 0x80 base, bit 0-6 = longitud (si <= 0x3F)
    len_flag = 0x80 | (length & 0x3F)
    header = bytes([len_flag, ecu_addr, tester_addr])
    frame_no_cs = header + payload
    cs = kwp2000_checksum(frame_no_cs)
    return frame_no_cs + bytes([cs])


# =============================================================================
# 3. SUPPORTED PIDs SCANNER  (extraído de provrb/obdium)
#    Referencia: backend/src/obd.rs — get_service_supported_pids()
# =============================================================================

# Rangos de consulta de PIDs soportados por servicio
_SUPPORTED_PID_RANGES: dict[str, list[str]] = {
    "01": ["00", "20", "40", "60", "80", "A0", "C0"],
    "02": ["00"],           # Freeze Frame
    "05": ["00"],
    "09": ["00"],
}


def parse_supported_pids_bitmask(range_pid_hex: str, bitmask_bytes: list[int]) -> list[int]:
    """
    Decodifica los 4 bytes de bitmask de un PID "soporte" (ej. 0x00, 0x20...)
    y devuelve la lista de PIDs soportados en ese rango de 32.

    Algoritmo (rzetterberg/elmobd — PartSupported.SupportsPID):
      - El bit más significativo del primer byte representa el siguiente PID.
      - offset = range_pid_val + 1
      - Para cada bit i en [0..31]: bit_val = bitmask >> (31 - i) & 1
        si bit_val == 1 → PID (offset + i) está soportado.

    Args:
        range_pid_hex: PID de la consulta de soporte, ej. "00", "20".
        bitmask_bytes: 4 bytes raw de la respuesta (A, B, C, D).
    Returns:
        Lista de PIDs (int) soportados en ese rango.
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
    supported = []
    for i in range(32):
        if (combined >> (31 - i)) & 1:
            supported.append(base + i)
    return supported


class SupportedPIDScanner:
    """
    Detecta todos los PIDs soportados por la ECU consultando los rangos
    estándar (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0) para Mode 01.

    Uso:
        scanner = SupportedPIDScanner(elm327_protocol_instance)
        pids = scanner.scan(service=1)
        print(pids)  # [4, 5, 12, 13, ...]
    """

    def __init__(self, protocol) -> None:
        """protocol: instancia de ELM327Protocol o similar con read_pid()."""
        self._proto = protocol

    def scan(self, service: int = 1) -> list[int]:
        """
        Escanea todos los PIDs soportados para el servicio dado.
        Devuelve lista ordenada de PIDs soportados.
        """
        service_hex = f"{service:02X}"
        ranges = _SUPPORTED_PID_RANGES.get(service_hex, ["00"])
        all_pids: list[int] = []

        for range_pid in ranges:
            pid_int = int(range_pid, 16)
            try:
                result = self._proto.read_pid(pid_int, mode=service)
                raw_bytes = result.get("raw_bytes", [])
                if len(raw_bytes) >= 4:
                    pids = parse_supported_pids_bitmask(range_pid, raw_bytes[:4])
                    all_pids.extend(pids)
                    # Si el último rango soportado no incluye el siguiente
                    # rango de consulta, parar
                    next_range_pid = pid_int + 0x20
                    if next_range_pid not in pids:
                        break
            except Exception:
                break

        return sorted(set(all_pids))


# =============================================================================
# 4. MONITOR STATUS PARSER  (extraído de rzetterberg/elmobd)
#    Referencia: commands.go — MonitorStatus struct y SetValue()
# =============================================================================

@dataclass
class MonitorStatus:
    """
    Resultado del PID 0x01 (Monitor Status Since DTCs Cleared).

    mil_active : True si la Malfunction Indicator Lamp está encendida.
    dtc_count  : número de DTCs almacenados.
    """
    mil_active: bool = False
    dtc_count: int = 0

    # Flags de monitores (byte B)
    misfire_incomplete: bool = False
    fuel_system_incomplete: bool = False
    components_incomplete: bool = False

    # Byte C: monitores continuos
    misfire_supported: bool = False
    fuel_system_supported: bool = False
    components_supported: bool = False


def parse_monitor_status(raw_bytes: list[int]) -> MonitorStatus:
    """
    Decodifica los 4 bytes del PID 0x01.

    Byte A:
      bit 7 = MIL encendido
      bits 0-6 = número de DTCs confirmados

    Byte B:
      bits 4-6 = flags "incompleto" de monitores continuos
      bits 0-2 = flags "soportado" de monitores continuos

    Referencia SAE J1979 Tabla A-6.
    """
    ms = MonitorStatus()
    if len(raw_bytes) < 1:
        return ms

    a = raw_bytes[0]
    ms.mil_active = bool(a & 0x80)   # bit 7
    ms.dtc_count  = a & 0x7F          # bits 0-6

    if len(raw_bytes) >= 2:
        b = raw_bytes[1]
        ms.misfire_incomplete      = bool(b & 0x10)
        ms.fuel_system_incomplete  = bool(b & 0x20)
        ms.components_incomplete   = bool(b & 0x40)
        ms.misfire_supported       = bool(b & 0x01)
        ms.fuel_system_supported   = bool(b & 0x02)
        ms.components_supported    = bool(b & 0x04)

    return ms


# =============================================================================
# 5. RESPONSE VALIDATOR  (extraído de rzetterberg/elmobd)
#    Referencia: device.go — Validate() / parseOBDResponse()
# =============================================================================

class OBDResponseError(Exception):
    pass


def validate_obd_response(
    raw_line: str,
    expected_mode: int,
    expected_pid: int,
) -> list[int]:
    """
    Valida y decodifica una línea de respuesta OBD-II del ELM327.

    Verifica:
      1. No contiene errores conocidos del ELM327 ("NO DATA", "UNABLE TO CONNECT", etc.)
      2. El byte de modo en la respuesta == expected_mode + 0x40
      3. El byte de PID en la respuesta == expected_pid

    Devuelve la lista de bytes de datos (sin modo ni PID echo).
    Lanza OBDResponseError si la validación falla.

    Ejemplo:
        bytes_data = validate_obd_response("41 0C 1A F8", mode=0x01, pid=0x0C)
        # → [0x1A, 0xF8]
    """
    # Frases de error estándar del ELM327
    _ELM_ERRORS = [
        "NO DATA", "UNABLE TO CONNECT", "BUS INIT: ERROR",
        "CAN ERROR", "BUS BUSY", "FB ERROR", "DATA ERROR",
        "ERR", "STOPPED", "?",
    ]

    upper = raw_line.strip().upper()
    for err in _ELM_ERRORS:
        if err in upper:
            raise OBDResponseError(f"ELM327 error: '{upper}'")

    # Limpiar y convertir a bytes
    clean = upper.replace(" ", "")
    if len(clean) < 4 or len(clean) % 2 != 0:
        raise OBDResponseError(f"Respuesta malformada: '{raw_line}'")

    try:
        resp_bytes = [int(clean[i:i+2], 16) for i in range(0, len(clean), 2)]
    except ValueError as exc:
        raise OBDResponseError(f"No es hex válido: '{raw_line}'") from exc

    if len(resp_bytes) < 2:
        raise OBDResponseError("Respuesta demasiado corta")

    # Verificar echo de modo (modo + 0x40)
    mode_echo = expected_mode + 0x40
    if resp_bytes[0] != mode_echo:
        raise OBDResponseError(
            f"Echo de modo incorrecto: esperado {mode_echo:#04x}, "
            f"recibido {resp_bytes[0]:#04x}"
        )

    # Verificar echo de PID
    if resp_bytes[1] != expected_pid:
        raise OBDResponseError(
            f"Echo de PID incorrecto: esperado {expected_pid:#04x}, "
            f"recibido {resp_bytes[1]:#04x}"
        )

    return resp_bytes[2:]   # Bytes de datos útiles


# =============================================================================
# 6. FREEZE FRAME MODE SWITCHER  (extraído de provrb/obdium)
#    Referencia: backend/src/obd.rs — freeze_frame_query lógica
# =============================================================================

def switch_to_freeze_frame(service: int, pid: int) -> tuple[int, int]:
    """
    Convierte un request de datos en vivo (service 01) a Freeze Frame (service 02).

    Obdium lo implementa interceptando el PID antes de enviarlo:
      if freeze_frame_query && command_type == PIDCommand && pid.starts_with("01"):
          change to "02"

    Devuelve (service_nuevo, pid) — pid no cambia, solo el servicio.
    """
    if service == 0x01:
        return (0x02, pid)
    return (service, pid)


class FreezeFrameReader:
    """
    Lee datos de Freeze Frame (service 02) usando el mismo decodificador
    que datos en vivo (service 01), evitando duplicar fórmulas.

    Uso:
        ffr = FreezeFrameReader(elm327_protocol)
        data = ffr.read_pid(pid=0x0C)   # RPM en el momento del fallo
    """

    def __init__(self, protocol, frame_index: int = 0) -> None:
        """
        protocol   : instancia ELM327Protocol.
        frame_index: índice de Freeze Frame (normalmente 0).
        """
        self._proto = protocol
        self._frame_index = frame_index

    def read_pid(self, pid: int) -> dict:
        """Lee un PID del Freeze Frame (service 02)."""
        ff_service, ff_pid = switch_to_freeze_frame(0x01, pid)
        # Mode 02 requiere enviar el frame index como segundo byte
        cmd = f"{ff_service:02X}{ff_pid:02X}{self._frame_index:02X}"
        raw = self._proto._send_command(cmd, delay=0.15)
        # Reusar el decodificador de service 01 (mismas fórmulas)
        return self._proto._decode_pid(ff_pid, ff_service, raw)


# =============================================================================
# 7. DEMO REPLAY MODE  (extraído de provrb/obdium)
#    Referencia: backend/src/replay.rs — replay de requests.json
# =============================================================================

class DemoReplayProtocol:
    """
    Modo offline: reproduce pares request/response guardados en un JSON.

    Permite testear el scanner sin hardware conectado.

    Formato del archivo JSON:
    {
      "01 0C": "41 0C 1A F8",
      "01 0D": "41 0D 3C",
      "03":    "43 01 33 00 00 00 00",
      ...
    }

    Uso:
        proto = DemoReplayProtocol("sessions/demo_golf4.json")
        result = proto.read_pid(0x0C)   # → {'name': 'rpm', 'value': 1726.0, ...}
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
        """Busca la respuesta en el JSON de replay (insensible a espacios/mayúsculas)."""
        key = cmd.strip().upper().replace(" ", "")
        # Buscar con espacios o sin espacios
        for k, v in self._db.items():
            if k.replace(" ", "").upper() == key:
                return v
        return "NO DATA"

    def read_pid(self, pid: int, mode: int = 0x01) -> dict:
        """Emula read_pid() de ELM327Protocol usando datos del replay."""
        cmd = f"{mode:02X}{pid:02X}"
        raw = self._send_command(cmd)

        # Decodificación mínima reutilizando PID_TABLE de elm327.py
        try:
            from scaner_soler.comm.elm327 import PID_TABLE
        except ImportError:
            return {"raw": raw}

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
                return {"name": name, "value": value, "unit": unit, "raw": raw}
            except (IndexError, ZeroDivisionError):
                pass
        return {"raw": raw, "raw_bytes": data_bytes}

    @staticmethod
    def save_session(
        protocol,
        pid_list: list[int],
        output_file: str | Path,
        mode: int = 0x01,
    ) -> None:
        """
        Graba una sesión real en un JSON para usarla luego en replay.

        Uso:
            DemoReplayProtocol.save_session(proto, [0x0C, 0x0D, 0x05],
                                            "sessions/mi_coche.json")
        """
        db: dict[str, str] = {}
        for pid in pid_list:
            cmd = f"{mode:02X}{pid:02X}"
            raw = protocol._send_command(cmd, delay=0.15)
            db[cmd] = raw.strip()
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2)


# =============================================================================
# 8. ECU ADDRESS MAP  (extraído de Ircama/ELM327-emulator)
#    Referencia: elm/obd_message.py — ECU_ADDR_* constants
# =============================================================================

ECU_ADDRESSES = {
    # Direcciones de request (tester → ECU)
    "ECU_ADDR_E": 0x7E0,   # Engine Control Module
    "ECU_ADDR_T": 0x7E1,   # Transmission Control Module
    "ECU_ADDR_H": 0x7E2,   # Hybrid / Auxiliary Control
    "ECU_ADDR_B": 0x7E3,   # Battery Management System
    "ECU_ADDR_M": 0x7E5,   # Continental Powertrain ECU
    "ECU_ADDR_S": 0x7B0,   # ABS / Stability Control
    "ECU_ADDR_P": 0x7C4,   # Climate Control / HVAC
    # Direcciones de respuesta (ECU → tester)
    "ECU_R_ADDR_E": 0x7E8,  # Engine — respuesta
    "ECU_R_ADDR_T": 0x7E9,  # Transmission — respuesta
    "ECU_R_ADDR_H": 0x7EA,  # Hybrid — respuesta
    "ECU_R_ADDR_B": 0x7EB,  # BMS — respuesta
}

# Mapa inverso: dirección → nombre legible
ECU_ADDR_NAMES: dict[int, str] = {v: k for k, v in ECU_ADDRESSES.items()}


def parse_ecu_header(header_hex: str) -> dict:
    """
    Analiza la cabecera CAN de una respuesta multi-ECU.

    Para CAN 11-bit, el header son los 3 primeros bytes de la trama.
    Devuelve dict con 'ecu_addr', 'ecu_name' y 'is_response'.

    Ejemplo:
        parse_ecu_header("7E8")
        # → {'ecu_addr': 0x7E8, 'ecu_name': 'ECU_R_ADDR_E', 'is_response': True}
    """
    try:
        addr = int(header_hex.strip(), 16)
    except ValueError:
        return {"ecu_addr": None, "ecu_name": "UNKNOWN", "is_response": False}

    name = ECU_ADDR_NAMES.get(addr, f"0x{addr:03X}")
    is_response = (addr & 0x008) != 0   # Las respuestas tienen bit 3 a 1 respecto a la request
    return {
        "ecu_addr": addr,
        "ecu_name": name,
        "is_response": is_response,
    }


# =============================================================================
# FUNCIÓN UTILITARIA: ESCANEO COMPLETO DE VEHÍCULO
# Orquesta SupportedPIDScanner + MonitorStatus + IsoTpMultiframe
# =============================================================================

def full_vehicle_scan(protocol) -> dict:
    """
    Realiza un escaneo completo del vehículo y devuelve un dict con:
      - supported_pids: lista de PIDs soportados
      - monitor_status: estado MIL + conteo DTC
      - freeze_frame_available: si hay datos de freeze frame

    Uso:
        from scaner_soler.comm.elm327 import ELM327Protocol
        proto = ELM327Protocol()
        proto.connect("COM3")
        report = full_vehicle_scan(proto)
    """
    report: dict = {
        "supported_pids": [],
        "monitor_status": None,
        "freeze_frame_available": False,
    }

    # 1. PIDs soportados
    try:
        scanner = SupportedPIDScanner(protocol)
        report["supported_pids"] = scanner.scan(service=1)
    except Exception as exc:
        report["supported_pids_error"] = str(exc)

    # 2. Monitor status (PID 0x01)
    try:
        ms_raw = protocol.read_pid(0x01, mode=0x01)
        raw_bytes = ms_raw.get("raw_bytes", [])
        report["monitor_status"] = parse_monitor_status(raw_bytes)
    except Exception as exc:
        report["monitor_status_error"] = str(exc)

    # 3. Freeze frame: intentar leer PID 0x02 de service 02
    try:
        ffr = FreezeFrameReader(protocol)
        ff_result = ffr.read_pid(0x0C)   # RPM en Freeze Frame
        report["freeze_frame_available"] = "value" in ff_result
        report["freeze_frame_rpm"] = ff_result.get("value")
    except Exception:
        report["freeze_frame_available"] = False

    return report
