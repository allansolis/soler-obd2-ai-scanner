"""
KWP2000 Driver - Implementación ISO 14230 en Python puro.

Implementa el protocolo KeyWord Protocol 2000 utilizado masivamente en
vehículos europeos 1999-2008 (VAG EDC15/ME7, BMW DME/DDE, PSA, etc.).

Soporta ambos transportes:
  - ISO 14230-1 (línea K serial con init 5-baud, fast init)
  - ISO 14230-3 sobre CAN (KWPonCAN, p.ej. Mercedes, algunos VAG)

Servicios implementados (SIDs): 10, 11, 14, 18, 1A, 21, 22, 23, 27, 2E,
3D, 31, 33, 3E.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Awaitable, Callable, Optional, Protocol

from .base_driver import (
    BaseECUDriver,
    DiagnosticSession,
    DriverState,
    ECUDriverError,
    ECUIdentification,
    NegativeResponseError,
    SecurityError,
    TimeoutError as ECUTimeoutError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Servicios y constantes
# ---------------------------------------------------------------------------


class KWP2000Service(IntEnum):
    """Service IDs de KWP2000."""
    START_DIAGNOSTIC_SESSION = 0x10
    ECU_RESET = 0x11
    CLEAR_DIAGNOSTIC_INFORMATION = 0x14
    READ_DTC_BY_STATUS = 0x18
    READ_ECU_IDENTIFICATION = 0x1A
    READ_DATA_BY_LOCAL_ID = 0x21
    READ_DATA_BY_COMMON_ID = 0x22
    READ_MEMORY_BY_ADDRESS = 0x23
    SECURITY_ACCESS = 0x27
    DISABLE_NORMAL_MESSAGE_TX = 0x28
    ENABLE_NORMAL_MESSAGE_TX = 0x29
    DYNAMICALLY_DEFINE_LOCAL_ID = 0x2C
    WRITE_DATA_BY_COMMON_ID = 0x2E
    INPUT_OUTPUT_CONTROL_BY_LOCAL_ID = 0x30
    START_ROUTINE_BY_LOCAL_ID = 0x31
    STOP_ROUTINE_BY_LOCAL_ID = 0x32
    REQUEST_ROUTINE_RESULTS_BY_LOCAL_ID = 0x33
    REQUEST_DOWNLOAD = 0x34
    REQUEST_UPLOAD = 0x35
    TRANSFER_DATA = 0x36
    REQUEST_TRANSFER_EXIT = 0x37
    START_COMMUNICATION = 0x81
    STOP_COMMUNICATION = 0x82
    ACCESS_TIMING_PARAMETERS = 0x83
    WRITE_MEMORY_BY_ADDRESS = 0x3D
    TESTER_PRESENT = 0x3E


NEGATIVE_RESPONSE = 0x7F
POSITIVE_RESPONSE_OFFSET = 0x40


NEGATIVE_RESPONSE_CODES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x23: "routineNotComplete",
    0x24: "requestSequenceError",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceedNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x40: "downloadNotAccepted",
    0x41: "improperDownloadType",
    0x42: "canNotDownloadToSpecifiedAddress",
    0x43: "canNotDownloadNumberOfBytesRequested",
    0x50: "uploadNotAccepted",
    0x51: "improperUploadType",
    0x52: "canNotUploadFromSpecifiedAddress",
    0x53: "canNotUploadNumberOfBytesRequested",
    0x71: "transferSuspended",
    0x72: "transferAborted",
    0x74: "illegalAddressInBlockTransfer",
    0x75: "illegalByteCountInBlockTransfer",
    0x76: "illegalBlockTransferType",
    0x77: "blockTransferDataChecksumError",
    0x78: "reqCorrectlyRxed_RspPending",
    0x79: "incorrectByteCountDuringBlockTransfer",
    0x80: "serviceNotSupportedInActiveDiagnosticSession",
}


# IDs comunes de identificación ECU (KWP2000 service 0x1A)
class KWP2000ECUIdentifier(IntEnum):
    VIN = 0x90
    VEHICLE_MANUFACTURER_ECU_HW_NUMBER = 0x91
    VEHICLE_MANUFACTURER_ECU_SW_NUMBER = 0x92
    VEHICLE_MANUFACTURER_ECU_SW_VERSION = 0x94
    SYSTEM_SUPPLIER = 0x95
    ECU_MANUFACTURING_DATE = 0x99
    ECU_SERIAL_NUMBER = 0x9B
    VEHICLE_MANUFACTURER_SPARE_PART_NUMBER = 0x9C
    CALIBRATION_ID = 0x96
    CALIBRATION_VERIFICATION_NUMBER = 0x9F


class KWP2000Error(ECUDriverError):
    """Error específico de KWP2000."""


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class KWP2000Transport(Protocol):
    """Interfaz de transporte para KWP2000."""

    async def send(self, data: bytes) -> None: ...
    async def recv(self, timeout: float) -> bytes: ...
    async def open(self) -> None: ...
    async def close(self) -> None: ...


@dataclass
class TimingParameters:
    """Parámetros de temporización KWP2000 (en ms)."""
    p1_min: float = 0.0
    p1_max: float = 20.0
    p2_min: float = 25.0
    p2_max: float = 50.0
    p3_min: float = 55.0
    p3_max: float = 5000.0
    p4_min: float = 5.0
    p4_max: float = 20.0


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


class KWP2000Driver(BaseECUDriver):
    """
    Driver KWP2000 (ISO 14230).

    Implementa la capa de aplicación del protocolo. El transporte físico
    (K-line serial, ISO-TP sobre CAN, J2534) se inyecta como dependencia.
    """

    def __init__(
        self,
        transport: KWP2000Transport,
        ecu_address: int = 0x7E0,
        response_address: int = 0x7E8,
        timeout: float = 2.0,
    ):
        super().__init__(
            ecu_address=ecu_address,
            response_address=response_address,
            timeout=timeout,
        )
        self.transport = transport
        self.timing = TimingParameters()
        self._security_unlocked_level: Optional[int] = None

    # ------------------------------------------------------------------
    # Conexión
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Establece la comunicación con la ECU (StartCommunication)."""
        self.state = DriverState.CONNECTING
        try:
            await self.transport.open()
            # StartCommunication (puede ser omitido en KWPonCAN)
            try:
                await self._send_request(
                    bytes([KWP2000Service.START_COMMUNICATION]),
                    expect_response=True,
                    timeout=3.0,
                )
            except (ECUTimeoutError, NegativeResponseError):
                self._log.debug(
                    "StartCommunication sin respuesta (puede ser normal en CAN)"
                )

            await self.enter_diagnostic_session(DiagnosticSession.EXTENDED)
            self.state = DriverState.SESSION_ACTIVE
            await self.start_tester_present_loop()
            self._log.info("Conexión KWP2000 establecida")
            return True
        except Exception as exc:
            self.state = DriverState.ERROR
            self._log.error("Fallo al conectar KWP2000: %s", exc)
            raise

    async def disconnect(self) -> None:
        """Cierra la comunicación con la ECU (StopCommunication)."""
        await self.stop_tester_present_loop()
        try:
            await self._send_request(
                bytes([KWP2000Service.STOP_COMMUNICATION]),
                expect_response=False,
            )
        except Exception:
            pass
        try:
            await self.transport.close()
        finally:
            self.state = DriverState.DISCONNECTED

    # ------------------------------------------------------------------
    # Core request/response
    # ------------------------------------------------------------------

    async def _send_request(
        self,
        request: bytes,
        expect_response: bool = True,
        timeout: Optional[float] = None,
    ) -> bytes:
        """
        Envía una petición y espera la respuesta, manejando 0x78 (pending).
        """
        if not request:
            raise KWP2000Error("Petición vacía")

        service = request[0]
        to = timeout if timeout is not None else self.timeout

        await self.transport.send(request)
        if not expect_response:
            return b""

        # Bucle para manejar respuesta pendiente (NRC 0x78)
        deadline = asyncio.get_event_loop().time() + to + 5.0
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise ECUTimeoutError(
                    f"Timeout esperando respuesta al servicio 0x{service:02X}"
                )
            try:
                response = await self.transport.recv(min(to, remaining))
            except asyncio.TimeoutError as exc:
                raise ECUTimeoutError(
                    f"Timeout esperando respuesta al servicio 0x{service:02X}"
                ) from exc

            if not response:
                continue

            if response[0] == NEGATIVE_RESPONSE:
                if len(response) < 3:
                    raise KWP2000Error(
                        f"Respuesta negativa malformada: {response.hex()}"
                    )
                nr_service, nrc = response[1], response[2]
                if nrc == 0x78:
                    # Request correctly received, response pending
                    self._log.debug(
                        "0x78 pending para servicio 0x%02X, esperando...",
                        nr_service,
                    )
                    continue
                raise NegativeResponseError(
                    nr_service,
                    nrc,
                    NEGATIVE_RESPONSE_CODES.get(nrc, "desconocido"),
                )

            if response[0] != service + POSITIVE_RESPONSE_OFFSET:
                self._log.debug(
                    "Respuesta inesperada (esperaba 0x%02X, recibí 0x%02X)",
                    service + POSITIVE_RESPONSE_OFFSET,
                    response[0],
                )
                continue
            return response

    # ------------------------------------------------------------------
    # Servicios
    # ------------------------------------------------------------------

    async def enter_diagnostic_session(
        self, session_type: DiagnosticSession
    ) -> bool:
        """Service 0x10 - StartDiagnosticSession."""
        session_byte = {
            DiagnosticSession.DEFAULT: 0x81,
            DiagnosticSession.PROGRAMMING: 0x85,
            DiagnosticSession.EXTENDED: 0x92,
            DiagnosticSession.SAFETY_SYSTEM: 0x92,
        }.get(session_type, 0x92)

        await self._send_request(
            bytes([KWP2000Service.START_DIAGNOSTIC_SESSION, session_byte])
        )
        self.state = DriverState.SESSION_ACTIVE
        self._log.info("Sesión diagnóstica KWP2000 activa: 0x%02X", session_byte)
        return True

    async def ecu_reset(self, reset_type: int = 0x01) -> None:
        """Service 0x11 - ECUReset."""
        await self._send_request(
            bytes([KWP2000Service.ECU_RESET, reset_type])
        )

    async def clear_diagnostic_information(
        self, group: int = 0xFF00
    ) -> None:
        """Service 0x14 - ClearDiagnosticInformation."""
        await self._send_request(
            bytes([
                KWP2000Service.CLEAR_DIAGNOSTIC_INFORMATION,
                (group >> 8) & 0xFF,
                group & 0xFF,
            ])
        )

    async def read_dtc_by_status(self, status_mask: int = 0x00) -> list[int]:
        """Service 0x18 - ReadDTCByStatus. Devuelve lista de DTCs (int)."""
        req = bytes([
            KWP2000Service.READ_DTC_BY_STATUS,
            status_mask,
            0xFF,
            0x00,
        ])
        resp = await self._send_request(req)
        # Respuesta: 58 NNN [DTC_H DTC_L STATUS]*
        dtcs: list[int] = []
        if len(resp) < 2:
            return dtcs
        num = resp[1]
        payload = resp[2:]
        for i in range(num):
            idx = i * 3
            if idx + 3 <= len(payload):
                dtc = (payload[idx] << 8) | payload[idx + 1]
                dtcs.append(dtc)
        return dtcs

    async def read_ecu_identification(self, identifier: int) -> bytes:
        """
        Service 0x1A - ReadECUIdentification.

        Args:
            identifier: Byte identificador (ej. 0x90 = VIN).
        """
        req = bytes([KWP2000Service.READ_ECU_IDENTIFICATION, identifier])
        resp = await self._send_request(req)
        # 5A ID DATA...
        if len(resp) < 3 or resp[1] != identifier:
            raise KWP2000Error(
                f"Respuesta inválida a readECUIdentification(0x{identifier:02X})"
            )
        return resp[2:]

    async def read_data_by_local_id(self, local_id: int) -> bytes:
        """Service 0x21 - ReadDataByLocalIdentifier."""
        req = bytes([KWP2000Service.READ_DATA_BY_LOCAL_ID, local_id])
        resp = await self._send_request(req)
        if len(resp) < 2 or resp[1] != local_id:
            raise KWP2000Error(
                f"Respuesta inválida a RDBLI(0x{local_id:02X})"
            )
        return resp[2:]

    async def read_data_by_common_id(self, did: int) -> bytes:
        """Service 0x22 - ReadDataByCommonIdentifier (KWP variant)."""
        req = bytes([
            KWP2000Service.READ_DATA_BY_COMMON_ID,
            (did >> 8) & 0xFF,
            did & 0xFF,
        ])
        resp = await self._send_request(req)
        if len(resp) < 3:
            raise KWP2000Error("Respuesta RDBCI demasiado corta")
        return resp[3:]

    async def read_memory_by_address(
        self,
        address: int,
        length: int,
        address_size: int = 3,
    ) -> bytes:
        """
        Service 0x23 - ReadMemoryByAddress.

        Args:
            address: Dirección en memoria.
            length: Cantidad de bytes a leer (máx depende de la ECU, normalmente 254).
            address_size: Tamaño de la dirección en bytes (2, 3 o 4).
        """
        if length <= 0 or length > 254:
            raise ValueError("Longitud fuera de rango (1-254)")
        if address_size not in (2, 3, 4):
            raise ValueError("address_size debe ser 2, 3 o 4")

        addr_bytes = address.to_bytes(address_size, "big")
        req = bytes([KWP2000Service.READ_MEMORY_BY_ADDRESS]) + addr_bytes + bytes([length])
        resp = await self._send_request(req)
        # 63 DATA...
        data = resp[1:]
        if len(data) != length:
            self._log.warning(
                "RMBA devolvió %d bytes, esperaba %d", len(data), length
            )
        return data

    async def security_access(
        self,
        level: int,
        seed_key_algorithm: Callable[[bytes], bytes],
    ) -> bool:
        """
        Service 0x27 - SecurityAccess (seed-key challenge).

        Args:
            level: Nivel impar = request seed, par = send key.
            seed_key_algorithm: Función que calcula la key a partir del seed.
        """
        if level % 2 == 0:
            raise ValueError("El nivel solicitado debe ser impar (request seed)")

        # 1) Request seed
        resp = await self._send_request(
            bytes([KWP2000Service.SECURITY_ACCESS, level])
        )
        seed = resp[2:]
        if all(b == 0 for b in seed):
            self._log.info("Seguridad ya desbloqueada (seed=0)")
            self._security_unlocked_level = level + 1
            self.state = DriverState.SECURITY_UNLOCKED
            return True

        try:
            key = seed_key_algorithm(seed)
        except Exception as exc:
            raise SecurityError(
                f"Algoritmo seed->key falló: {exc}"
            ) from exc

        # 2) Send key
        await self._send_request(
            bytes([KWP2000Service.SECURITY_ACCESS, level + 1]) + bytes(key)
        )
        self._security_unlocked_level = level + 1
        self.state = DriverState.SECURITY_UNLOCKED
        self._log.info("Seguridad KWP2000 desbloqueada nivel %d", level + 1)
        return True

    async def write_data_by_common_id(self, did: int, data: bytes) -> None:
        """Service 0x2E - WriteDataByCommonIdentifier."""
        req = bytes([
            KWP2000Service.WRITE_DATA_BY_COMMON_ID,
            (did >> 8) & 0xFF,
            did & 0xFF,
        ]) + data
        await self._send_request(req)

    async def write_memory_by_address(
        self, address: int, data: bytes, address_size: int = 3
    ) -> None:
        """Service 0x3D - WriteMemoryByAddress."""
        addr_bytes = address.to_bytes(address_size, "big")
        req = (
            bytes([KWP2000Service.WRITE_MEMORY_BY_ADDRESS])
            + addr_bytes
            + bytes([len(data)])
            + data
        )
        await self._send_request(req)

    async def start_routine_by_local_id(
        self, routine_id: int, parameters: bytes = b""
    ) -> bytes:
        """Service 0x31 - StartRoutineByLocalIdentifier."""
        req = (
            bytes([KWP2000Service.START_ROUTINE_BY_LOCAL_ID, routine_id])
            + parameters
        )
        resp = await self._send_request(req)
        return resp[2:]

    async def request_routine_results_by_local_id(
        self, routine_id: int
    ) -> bytes:
        """Service 0x33 - RequestRoutineResultsByLocalIdentifier."""
        req = bytes([
            KWP2000Service.REQUEST_ROUTINE_RESULTS_BY_LOCAL_ID,
            routine_id,
        ])
        resp = await self._send_request(req)
        return resp[2:]

    async def send_tester_present(self) -> None:
        """Service 0x3E - TesterPresent."""
        try:
            await self._send_request(
                bytes([KWP2000Service.TESTER_PRESENT, 0x01]),
                expect_response=True,
                timeout=1.0,
            )
        except ECUTimeoutError:
            # Muchos ECUs responden en modo "no response required" (subfunc 0x80)
            pass

    async def access_timing_parameters(
        self,
        read_limits: bool = True,
    ) -> Optional[TimingParameters]:
        """Service 0x83 - AccessTimingParameters."""
        subfunc = 0x01 if read_limits else 0x02
        resp = await self._send_request(
            bytes([KWP2000Service.ACCESS_TIMING_PARAMETERS, subfunc])
        )
        if len(resp) >= 8:
            # [83 subfunc P2min P2max P3min P3max P4min P4max]
            self.timing.p2_min = resp[2] * 0.5
            self.timing.p2_max = resp[3] * 25.0
            self.timing.p3_min = resp[4] * 0.5
            self.timing.p3_max = resp[5] * 250.0
            self.timing.p4_min = resp[6] * 0.5
            self.timing.p4_max = resp[7] * 0.5
            return self.timing
        return None

    # ------------------------------------------------------------------
    # Implementación BaseECUDriver
    # ------------------------------------------------------------------

    async def read_ecu_id(self) -> ECUIdentification:
        """Lee todos los identificadores estándar de la ECU."""
        ident = ECUIdentification()
        identifiers_to_read = [
            (KWP2000ECUIdentifier.VIN, "vin"),
            (KWP2000ECUIdentifier.VEHICLE_MANUFACTURER_ECU_HW_NUMBER, "hardware_number"),
            (KWP2000ECUIdentifier.VEHICLE_MANUFACTURER_ECU_SW_NUMBER, "software_number"),
            (KWP2000ECUIdentifier.VEHICLE_MANUFACTURER_ECU_SW_VERSION, "software_version"),
            (KWP2000ECUIdentifier.SYSTEM_SUPPLIER, "supplier_id"),
            (KWP2000ECUIdentifier.ECU_MANUFACTURING_DATE, "programming_date"),
            (KWP2000ECUIdentifier.ECU_SERIAL_NUMBER, "serial_number"),
            (KWP2000ECUIdentifier.VEHICLE_MANUFACTURER_SPARE_PART_NUMBER, "part_number"),
            (KWP2000ECUIdentifier.CALIBRATION_ID, "calibration_id"),
            (KWP2000ECUIdentifier.CALIBRATION_VERIFICATION_NUMBER, "calibration_verification_number"),
        ]

        for ident_id, attr in identifiers_to_read:
            try:
                data = await self.read_ecu_identification(int(ident_id))
                ident.raw_identifiers[int(ident_id)] = data
                try:
                    value = data.rstrip(b"\x00\xFF ").decode("ascii")
                except UnicodeDecodeError:
                    value = data.hex().upper()
                setattr(ident, attr, value)
            except (NegativeResponseError, ECUTimeoutError) as exc:
                self._log.debug(
                    "ID 0x%02X no disponible: %s", int(ident_id), exc
                )
        return ident

    async def read_vin(self) -> str:
        data = await self.read_ecu_identification(int(KWP2000ECUIdentifier.VIN))
        return data.rstrip(b"\x00\xFF ").decode("ascii", errors="replace")

    async def read_software_version(self) -> str:
        data = await self.read_ecu_identification(
            int(KWP2000ECUIdentifier.VEHICLE_MANUFACTURER_ECU_SW_VERSION)
        )
        return data.rstrip(b"\x00\xFF ").decode("ascii", errors="replace")

    async def read_hardware_version(self) -> str:
        data = await self.read_ecu_identification(
            int(KWP2000ECUIdentifier.VEHICLE_MANUFACTURER_ECU_HW_NUMBER)
        )
        return data.rstrip(b"\x00\xFF ").decode("ascii", errors="replace")

    async def read_calibration_data(
        self, start_addr: int, length: int
    ) -> bytes:
        """Usa Service 0x23 ReadMemoryByAddress para leer calibración."""
        return await self.read_memory_by_address(start_addr, length)
