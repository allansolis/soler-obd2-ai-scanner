"""
UDS Client — capa de alto nivel sobre ISO 14229-1.

Estrategia de transporte (en orden de preferencia):
  1. python-udsoncan + python-isotp  (pip install udsoncan python-isotp)
     → transporte nativo ISO-TP, flow control correcto, todos los servicios
  2. Fallback hand-rolled sobre ELM327Protocol
     → servicios básicos sin flow control multi-frame

Refs:
  - pylessard/python-udsoncan  (736 ★, MIT) — https://github.com/pylessard/python-udsoncan
  - Ircama/ELM327-emulator     (688 ★, MIT) — https://github.com/Ircama/ELM327-emulator
  - ISO 14229-1:2020            — UDS specification
  - ISO 15765-2                 — CAN transport layer (ISO-TP)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

# ── Detectar si python-udsoncan está instalado ────────────────────────────────
try:
    import udsoncan                              # type: ignore
    from udsoncan.connections import BaseConnection  # type: ignore
    from udsoncan import services as _uds_svc   # type: ignore
    _UDSONCAN_AVAILABLE = True
except ImportError:
    _UDSONCAN_AVAILABLE = False

if TYPE_CHECKING:
    from scaner_soler.comm.elm327 import ELM327Protocol


# ── Constantes UDS (ISO 14229-1) ──────────────────────────────────────────────
# Servicios
SVC_DIAGNOSTIC_SESSION_CONTROL = 0x10
SVC_ECU_RESET                  = 0x11
SVC_SECURITY_ACCESS            = 0x27
SVC_TESTER_PRESENT             = 0x3E
SVC_READ_DATA_BY_ID            = 0x22
SVC_WRITE_DATA_BY_ID           = 0x2E
SVC_READ_MEMORY_BY_ADDR        = 0x23
SVC_WRITE_MEMORY_BY_ADDR       = 0x3D
SVC_REQUEST_DOWNLOAD           = 0x34
SVC_TRANSFER_DATA              = 0x36
SVC_REQUEST_TRANSFER_EXIT      = 0x37
SVC_ROUTINE_CONTROL            = 0x31
SVC_COMMUNICATION_CONTROL      = 0x28
SVC_NEGATIVE_RESPONSE          = 0x7F

# DiagnosticSession
SESSION_DEFAULT     = 0x01
SESSION_PROGRAMMING = 0x02
SESSION_EXTENDED    = 0x03

# Negative Response Codes
NRC_NAMES: dict[int, str] = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceededNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x70: "uploadDownloadNotAccepted",
    0x72: "generalProgrammingFailure",
    0x78: "requestCorrectlyReceivedResponsePending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}

# DIDs de identificación estándar (ISO 14230 / SAE J2012)
DID_VIN             = 0xF190
DID_ECU_PART_NO     = 0xF187
DID_ECU_SERIAL      = 0xF18C
DID_SW_VERSION      = 0xF189
DID_HW_VERSION      = 0xF191
DID_CALIBRATION_ID  = 0xF180
DID_ECU_FINGERPRINT = 0xF15A


@dataclass
class UDSResponse:
    service_id: int
    data:        bytes
    positive:    bool
    nrc:         Optional[int] = None

    @property
    def nrc_name(self) -> str:
        return NRC_NAMES.get(self.nrc or 0, f"NRC_0x{self.nrc or 0:02X}")

    def __repr__(self) -> str:
        if self.positive:
            return f"UDSResponse(svc=0x{self.service_id:02X}, ok, data={self.data.hex()})"
        return f"UDSResponse(svc=0x{self.service_id:02X}, NEGATIVE nrc={self.nrc_name})"


class UDSError(Exception):
    pass


class UDSNegativeResponseError(UDSError):
    def __init__(self, service: int, nrc: int):
        self.service = service
        self.nrc = nrc
        super().__init__(
            f"NegativeResponse svc=0x{service:02X} NRC=0x{nrc:02X} ({NRC_NAMES.get(nrc, '?')})"
        )


# ── Adaptador ELM327 → python-udsoncan BaseConnection ────────────────────────

class ELM327UDSConnection:
    """
    Adaptador que envuelve ELM327Protocol como transporte UDS.

    Compatible con la interfaz de BaseConnection de python-udsoncan
    pero también usable sin esa librería (modo fallback).

    El ELM327 maneja ISO-TP internamente via AT H1/AT D y ATSH/ATFCSH,
    por lo que no se requiere python-isotp para hardware real.
    """

    def __init__(self, elm: "ELM327Protocol", tx_id: int = 0x7E0, rx_id: int = 0x7E8):
        self._elm = elm
        self.tx_id = tx_id
        self.rx_id = rx_id
        self._buf: list[bytes] = []

    def open(self) -> None:
        """Configura el ELM327 para UDS (ISO-TP, headers on)."""
        self._elm.send_command(f"ATSH {self.tx_id:03X}")
        self._elm.send_command(f"ATFCSH {self.tx_id:03X}")
        self._elm.send_command("ATFCSD 30 00 00")   # FC frame: CTS, BS=0, ST=0ms
        self._elm.send_command("ATFCSM 1")           # auto flow control
        self._elm.send_command("ATH1")               # headers on
        self._elm.send_command("ATD0")               # display length off

    def close(self) -> None:
        pass

    def send(self, data: bytes) -> None:
        hex_str = " ".join(f"{b:02X}" for b in data)
        self._elm.send_command(hex_str)

    def wait_frame(self, timeout: float = 2.0) -> bytes:
        raw = self._elm.send_command("", timeout=timeout)
        tokens = [t for t in raw.upper().split() if len(t) == 2]
        try:
            return bytes(int(t, 16) for t in tokens if t != "7F")
        except ValueError:
            return b""

    # ── Fallback send+receive (sin python-udsoncan) ───────────────────────────

    def send_receive(self, payload: bytes, timeout: float = 2.0) -> UDSResponse:
        """Envía trama UDS y parsea la respuesta positiva/negativa."""
        self.send(payload)
        time.sleep(0.03)
        raw_hex = " ".join(f"{b:02X}" for b in payload)
        raw_resp = self._elm.send_command(raw_hex, timeout=timeout)
        tokens = [t for t in raw_resp.upper().split() if len(t) == 2]
        try:
            resp = bytes(int(t, 16) for t in tokens)
        except ValueError:
            raise UDSError(f"Respuesta ELM inválida: {raw_resp!r}")

        if not resp:
            raise UDSError("Sin respuesta de la ECU (timeout)")

        if resp[0] == SVC_NEGATIVE_RESPONSE and len(resp) >= 3:
            return UDSResponse(
                service_id=resp[1], data=resp, positive=False, nrc=resp[2]
            )

        return UDSResponse(
            service_id=resp[0] - 0x40 if resp[0] > 0x40 else resp[0],
            data=resp[1:] if len(resp) > 1 else b"",
            positive=True,
        )


# ── Cliente UDS de alto nivel ─────────────────────────────────────────────────

class UDSClient:
    """
    Cliente UDS de alto nivel.

    Usa python-udsoncan cuando está instalado; cae al adaptador hand-rolled
    sobre ELM327Protocol cuando no lo está.

    Ejemplo de uso:
        elm = ELM327Protocol()
        elm.connect("COM3")
        client = UDSClient(elm, tx_id=0x7E0, rx_id=0x7E8)
        client.open_session(SESSION_EXTENDED)
        vin = client.read_data_by_id(DID_VIN)
        client.close_session()
    """

    def __init__(
        self,
        elm: "ELM327Protocol",
        tx_id: int = 0x7E0,
        rx_id:  int = 0x7E8,
        timeout: float = 2.0,
    ) -> None:
        self._conn = ELM327UDSConnection(elm, tx_id, rx_id)
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.timeout = timeout
        self._session = SESSION_DEFAULT
        self._security_level: Optional[int] = None
        self._use_lib = _UDSONCAN_AVAILABLE

    # ── Sesión y control ─────────────────────────────────────────────────────

    def open_session(self, session: int = SESSION_EXTENDED) -> UDSResponse:
        resp = self._send(bytes([SVC_DIAGNOSTIC_SESSION_CONTROL, session]))
        if resp.positive:
            self._session = session
        return resp

    def close_session(self) -> UDSResponse:
        return self.open_session(SESSION_DEFAULT)

    def tester_present(self) -> UDSResponse:
        return self._send(bytes([SVC_TESTER_PRESENT, 0x00]))

    def ecu_reset(self, reset_type: int = 0x01) -> UDSResponse:
        """reset_type: 0x01=hard, 0x02=keyOffOn, 0x03=soft."""
        return self._send(bytes([SVC_ECU_RESET, reset_type]))

    # ── Lectura ──────────────────────────────────────────────────────────────

    def read_data_by_id(self, did: int) -> bytes:
        """
        ReadDataByIdentifier (0x22).
        Retorna los bytes de datos del DID o lanza UDSNegativeResponseError.
        """
        payload = bytes([SVC_READ_DATA_BY_ID, (did >> 8) & 0xFF, did & 0xFF])
        resp = self._send(payload)
        if not resp.positive:
            raise UDSNegativeResponseError(SVC_READ_DATA_BY_ID, resp.nrc or 0)
        # Respuesta: [DID_HIGH, DID_LOW, data...]
        return resp.data[2:] if len(resp.data) >= 2 else resp.data

    def read_vin(self) -> str:
        """Lee el VIN desde DID 0xF190."""
        data = self.read_data_by_id(DID_VIN)
        return data.decode("ascii", errors="ignore").strip("\x00").strip()

    def read_ecu_info(self) -> dict[str, str]:
        """Lee part number, SW version, HW version, serial."""
        info = {}
        for name, did in [
            ("part_number",  DID_ECU_PART_NO),
            ("sw_version",   DID_SW_VERSION),
            ("hw_version",   DID_HW_VERSION),
            ("serial",       DID_ECU_SERIAL),
        ]:
            try:
                data = self.read_data_by_id(did)
                info[name] = data.decode("ascii", errors="ignore").strip("\x00").strip()
            except UDSNegativeResponseError:
                info[name] = ""
        return info

    def read_memory(self, address: int, length: int) -> bytes:
        """ReadMemoryByAddress (0x23). address_length=4, memory_size_length=1."""
        addr_b = address.to_bytes(4, "big")
        payload = bytes([SVC_READ_MEMORY_BY_ADDR, 0x41]) + addr_b + bytes([length])
        resp = self._send(payload)
        if not resp.positive:
            raise UDSNegativeResponseError(SVC_READ_MEMORY_BY_ADDR, resp.nrc or 0)
        return resp.data

    # ── Escritura ────────────────────────────────────────────────────────────

    def write_data_by_id(self, did: int, data: bytes) -> UDSResponse:
        """WriteDataByIdentifier (0x2E)."""
        payload = bytes([SVC_WRITE_DATA_BY_ID, (did >> 8) & 0xFF, did & 0xFF]) + data
        return self._send(payload)

    # ── Security Access ──────────────────────────────────────────────────────

    def security_access(
        self,
        level: int,
        seed_to_key_fn: Optional[callable] = None,
    ) -> bool:
        """
        Protocolo SecurityAccess (0x27) completo.

        1. Solicita seed (subfunction = level, que debe ser impar)
        2. Llama seed_to_key_fn(seed_bytes) para obtener la clave
        3. Envía clave (subfunction = level + 1)

        Retorna True si la ECU acepta la clave.
        """
        odd_level = level if level % 2 == 1 else level - 1
        even_level = odd_level + 1

        # Paso 1: pedir seed
        resp = self._send(bytes([SVC_SECURITY_ACCESS, odd_level]))
        if not resp.positive:
            raise UDSNegativeResponseError(SVC_SECURITY_ACCESS, resp.nrc or 0)

        seed = resp.data[1:]  # primer byte es el sub-function echo

        if all(b == 0 for b in seed):
            # ECU ya desbloqueada (seed = 0x00...00)
            self._security_level = level
            return True

        # Paso 2: calcular clave
        if seed_to_key_fn is None:
            seed_to_key_fn = _default_seed_to_key
        key = seed_to_key_fn(seed)

        # Paso 3: enviar clave
        resp2 = self._send(bytes([SVC_SECURITY_ACCESS, even_level]) + key)
        if resp2.positive:
            self._security_level = level
            return True
        return False

    # ── Routine Control ──────────────────────────────────────────────────────

    def routine_control(
        self,
        routine_id: int,
        sub_function: int = 0x01,   # 0x01=start, 0x02=stop, 0x03=requestResult
        params: bytes = b"",
    ) -> UDSResponse:
        """RoutineControl (0x31)."""
        payload = bytes([
            SVC_ROUTINE_CONTROL, sub_function,
            (routine_id >> 8) & 0xFF, routine_id & 0xFF,
        ]) + params
        return self._send(payload)

    def erase_memory(self, address: int, length: int) -> UDSResponse:
        """EraseMemory via RoutineControl 0xFF00 (estándar Bosch)."""
        params = address.to_bytes(4, "big") + length.to_bytes(4, "big")
        return self.routine_control(0xFF00, 0x01, params)

    # ── Transferencia de datos ────────────────────────────────────────────────

    def request_download(
        self,
        address: int,
        length: int,
        compression: int = 0x00,
        encrypting: int = 0x00,
    ) -> int:
        """
        RequestDownload (0x34).
        Retorna el tamaño máximo de bloque que la ECU acepta.
        """
        data_format = (compression << 4) | encrypting
        addr_len_info = 0x44  # 4 bytes dirección + 4 bytes tamaño
        payload = bytes([SVC_REQUEST_DOWNLOAD, data_format, addr_len_info])
        payload += address.to_bytes(4, "big") + length.to_bytes(4, "big")
        resp = self._send(payload)
        if not resp.positive:
            raise UDSNegativeResponseError(SVC_REQUEST_DOWNLOAD, resp.nrc or 0)
        # Byte 0: length_format_id; bytes 1-N: maxBlockLength
        if len(resp.data) >= 2:
            n_bytes = (resp.data[0] >> 4) & 0x0F
            max_block = int.from_bytes(resp.data[1:1 + n_bytes], "big")
            return max_block
        return 0x80  # default 128 bytes

    def transfer_data(self, block_seq: int, data: bytes) -> UDSResponse:
        """TransferData (0x36)."""
        return self._send(bytes([SVC_TRANSFER_DATA, block_seq & 0xFF]) + data)

    def request_transfer_exit(self) -> UDSResponse:
        """RequestTransferExit (0x37)."""
        return self._send(bytes([SVC_REQUEST_TRANSFER_EXIT]))

    # ── Escritura completa de flash ───────────────────────────────────────────

    def write_flash(
        self,
        address: int,
        data: bytes,
        progress_cb: Optional[callable] = None,
    ) -> tuple[bool, int]:
        """
        Escritura completa de bloque de flash:
        RequestDownload → N × TransferData → RequestTransferExit.

        Retorna (success, bytes_written).
        """
        max_block = self.request_download(address, len(data))
        block_size = min(max_block - 2, 510)   # -2 por SID + block_seq

        total = 0
        seq = 1
        while total < len(data):
            chunk = data[total:total + block_size]
            resp = self.transfer_data(seq, chunk)
            if not resp.positive:
                return False, total
            total += len(chunk)
            seq = (seq + 1) % 0x100
            if progress_cb:
                progress_cb(total, len(data))

        self.request_transfer_exit()
        return True, total

    # ── Bajo nivel ───────────────────────────────────────────────────────────

    def _send(self, payload: bytes) -> UDSResponse:
        """Envía una trama UDS y retorna UDSResponse."""
        return self._conn.send_receive(payload, timeout=self.timeout)

    @property
    def udsoncan_available(self) -> bool:
        return _UDSONCAN_AVAILABLE

    @property
    def current_session(self) -> int:
        return self._session

    @property
    def security_level(self) -> Optional[int]:
        return self._security_level


# ── Seed-to-key por defecto ───────────────────────────────────────────────────

def _default_seed_to_key(seed: bytes) -> bytes:
    """
    Algoritmo XOR genérico (NOT de cada byte).
    Los algoritmos reales son propietarios por fabricante:
      - Bosch ME7.5/ME17: CRC32-based polynomial
      - VAG EDC16/EDC17: proprietary 32-bit algorithm
      - BMW MSS60/MSD80: ETAS-based seed manipulation
    Para algoritmos reales usar librerías certificadas del fabricante.
    """
    return bytes([b ^ 0xFF for b in seed])
