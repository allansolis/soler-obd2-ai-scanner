"""
UDS Driver - Unified Diagnostic Services (ISO 14229).

Implementa el protocolo UDS sobre ISO-TP (CAN). Es el protocolo moderno
utilizado prácticamente por todas las ECUs fabricadas desde ~2008 (VAG MED17,
BMW MSD80+, Mercedes MED/SID, Ford/GM global, etc.).

Este módulo se apoya en la librería udsoncan (pylessard/python-udsoncan)
cuando está disponible, con un fallback mínimo si no lo está (útil para
entornos de desarrollo sin dependencias instaladas).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Callable, Optional, Protocol

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
# Detección opcional de udsoncan
# ---------------------------------------------------------------------------

try:
    import udsoncan  # type: ignore
    from udsoncan.client import Client  # type: ignore
    from udsoncan.connections import IsoTPSocketConnection  # type: ignore
    from udsoncan.services import (  # type: ignore
        DiagnosticSessionControl,
        ECUReset,
        ReadDataByIdentifier,
        ReadMemoryByAddress,
        SecurityAccess,
        WriteDataByIdentifier,
        RoutineControl,
        RequestDownload,
        TransferData,
        RequestTransferExit,
        TesterPresent,
        CommunicationControl,
    )
    UDSONCAN_AVAILABLE = True
except Exception:  # pragma: no cover
    UDSONCAN_AVAILABLE = False
    udsoncan = None  # type: ignore


# ---------------------------------------------------------------------------
# Servicios UDS
# ---------------------------------------------------------------------------


class UDSService(IntEnum):
    """Service IDs de UDS (ISO 14229)."""
    DIAGNOSTIC_SESSION_CONTROL = 0x10
    ECU_RESET = 0x11
    CLEAR_DIAGNOSTIC_INFORMATION = 0x14
    READ_DTC_INFORMATION = 0x19
    READ_DATA_BY_IDENTIFIER = 0x22
    READ_MEMORY_BY_ADDRESS = 0x23
    READ_SCALING_DATA_BY_IDENTIFIER = 0x24
    SECURITY_ACCESS = 0x27
    COMMUNICATION_CONTROL = 0x28
    READ_DATA_BY_PERIODIC_IDENTIFIER = 0x2A
    DYNAMICALLY_DEFINE_DATA_IDENTIFIER = 0x2C
    WRITE_DATA_BY_IDENTIFIER = 0x2E
    INPUT_OUTPUT_CONTROL_BY_IDENTIFIER = 0x2F
    ROUTINE_CONTROL = 0x31
    REQUEST_DOWNLOAD = 0x34
    REQUEST_UPLOAD = 0x35
    TRANSFER_DATA = 0x36
    REQUEST_TRANSFER_EXIT = 0x37
    WRITE_MEMORY_BY_ADDRESS = 0x3D
    TESTER_PRESENT = 0x3E
    ACCESS_TIMING_PARAMETERS = 0x83
    SECURED_DATA_TRANSMISSION = 0x84
    CONTROL_DTC_SETTING = 0x85
    RESPONSE_ON_EVENT = 0x86
    LINK_CONTROL = 0x87


class UDSSubFunction:
    """Subfunciones comunes."""

    # DiagnosticSessionControl
    DEFAULT_SESSION = 0x01
    PROGRAMMING_SESSION = 0x02
    EXTENDED_DIAGNOSTIC_SESSION = 0x03
    SAFETY_SYSTEM_DIAGNOSTIC_SESSION = 0x04

    # ECUReset
    HARD_RESET = 0x01
    KEY_OFF_ON_RESET = 0x02
    SOFT_RESET = 0x03

    # ReadDTCInformation subfunctions
    REPORT_NUMBER_OF_DTC_BY_STATUS = 0x01
    REPORT_DTC_BY_STATUS = 0x02
    REPORT_DTC_SNAPSHOT_RECORD = 0x04
    REPORT_DTC_EXT_DATA_RECORD = 0x06
    REPORT_SUPPORTED_DTC = 0x0A

    # RoutineControl
    START_ROUTINE = 0x01
    STOP_ROUTINE = 0x02
    REQUEST_ROUTINE_RESULTS = 0x03


# DIDs comunes (ISO 14229-1 Annex F)
class CommonDID(IntEnum):
    BOOT_SOFTWARE_IDENTIFICATION = 0xF180
    APPLICATION_SOFTWARE_IDENTIFICATION = 0xF181
    APPLICATION_DATA_IDENTIFICATION = 0xF182
    BOOT_SOFTWARE_FINGERPRINT = 0xF183
    APPLICATION_SOFTWARE_FINGERPRINT = 0xF184
    APPLICATION_DATA_FINGERPRINT = 0xF185
    ACTIVE_DIAGNOSTIC_SESSION = 0xF186
    VEHICLE_MANUFACTURER_SPARE_PART_NUMBER = 0xF187
    VEHICLE_MANUFACTURER_ECU_SW_NUMBER = 0xF188
    VEHICLE_MANUFACTURER_ECU_SW_VERSION = 0xF189
    SYSTEM_SUPPLIER_IDENTIFIER = 0xF18A
    ECU_MANUFACTURING_DATE = 0xF18B
    ECU_SERIAL_NUMBER = 0xF18C
    SUPPORTED_FUNCTIONAL_UNITS = 0xF18D
    VEHICLE_MANUFACTURER_KIT_ASSEMBLY_PART_NUMBER = 0xF18E
    VIN = 0xF190
    VEHICLE_MANUFACTURER_ECU_HARDWARE_NUMBER = 0xF191
    SYSTEM_SUPPLIER_ECU_HARDWARE_NUMBER = 0xF192
    SYSTEM_SUPPLIER_ECU_HARDWARE_VERSION = 0xF193
    SYSTEM_SUPPLIER_ECU_SOFTWARE_NUMBER = 0xF194
    SYSTEM_SUPPLIER_ECU_SOFTWARE_VERSION = 0xF195
    EXHAUST_REGULATION_OR_TYPE_APPROVAL_NUMBER = 0xF196
    SYSTEM_NAME_OR_ENGINE_TYPE = 0xF197
    REPAIR_SHOP_CODE_OR_TESTER_SERIAL = 0xF198
    PROGRAMMING_DATE = 0xF199


# NRC codes (ISO 14229-1 Table A.1)
NEGATIVE_RESPONSE_CODES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x14: "responseTooLong",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x25: "noResponseFromSubnetComponent",
    0x26: "failurePreventsExecutionOfRequestedAction",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceedNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x70: "uploadDownloadNotAccepted",
    0x71: "transferDataSuspended",
    0x72: "generalProgrammingFailure",
    0x73: "wrongBlockSequenceCounter",
    0x78: "requestCorrectlyReceivedResponsePending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}


class UDSError(ECUDriverError):
    """Excepción específica UDS."""


# ---------------------------------------------------------------------------
# Transport abstracto
# ---------------------------------------------------------------------------


class UDSTransport(Protocol):
    """Interfaz para transporte ISO-TP usado por UDSDriver."""

    async def open(self) -> None: ...
    async def close(self) -> None: ...
    async def send(self, data: bytes) -> None: ...
    async def recv(self, timeout: float) -> bytes: ...


@dataclass
class UDSConfig:
    """Configuración del driver UDS."""
    tx_id: int = 0x7E0
    rx_id: int = 0x7E8
    extended_id: bool = False
    p2_timeout: float = 1.0
    p2_star_timeout: float = 5.0
    block_size: int = 0xFE  # Bytes por lectura via 0x23
    address_length: int = 4  # Bytes del campo address
    length_length: int = 2   # Bytes del campo length (0x23)


# ---------------------------------------------------------------------------
# Driver UDS
# ---------------------------------------------------------------------------


class UDSDriver(BaseECUDriver):
    """
    Driver UDS (ISO 14229).

    Implementa todos los servicios necesarios para identificación de ECU,
    lectura de calibración, seguridad y reprogramación. Soporta ambos modos
    de direccionamiento CAN (11-bit y 29-bit).

    Si udsoncan está instalado, delega en Client de udsoncan para el parseo
    y gestión de servicios. Si no, utiliza una implementación en Python
    puro sobre el transport ISO-TP proporcionado.
    """

    def __init__(
        self,
        transport: UDSTransport,
        config: Optional[UDSConfig] = None,
    ):
        cfg = config or UDSConfig()
        super().__init__(
            ecu_address=cfg.tx_id,
            response_address=cfg.rx_id,
            timeout=cfg.p2_timeout,
        )
        self.transport = transport
        self.config = cfg
        self._security_unlocked_level: Optional[int] = None

    # ------------------------------------------------------------------
    # Conexión
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Abre el transporte y entra en sesión extendida."""
        self.state = DriverState.CONNECTING
        try:
            await self.transport.open()
            await self.enter_diagnostic_session(DiagnosticSession.EXTENDED)
            self.state = DriverState.SESSION_ACTIVE
            await self.start_tester_present_loop()
            self._log.info(
                "Conexión UDS establecida con ECU 0x%X", self.config.tx_id
            )
            return True
        except Exception as exc:
            self.state = DriverState.ERROR
            self._log.error("Fallo al conectar UDS: %s", exc)
            raise

    async def disconnect(self) -> None:
        await self.stop_tester_present_loop()
        try:
            await self.transport.close()
        finally:
            self.state = DriverState.DISCONNECTED

    # ------------------------------------------------------------------
    # Request/response core
    # ------------------------------------------------------------------

    async def _request(
        self,
        service: int,
        payload: bytes = b"",
        expect_response: bool = True,
        timeout: Optional[float] = None,
        suppress_positive: bool = False,
    ) -> bytes:
        """
        Envía una petición UDS cruda y procesa la respuesta.

        Maneja 0x78 (response pending) reintentando hasta P2* timeout.
        """
        request = bytes([service]) + payload
        self._log.debug("TX UDS: %s", request.hex())
        await self.transport.send(request)

        if not expect_response or suppress_positive:
            return b""

        p2 = timeout if timeout is not None else self.config.p2_timeout
        p2_star = self.config.p2_star_timeout
        loop = asyncio.get_event_loop()
        deadline = loop.time() + p2_star + p2 + 2.0

        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise ECUTimeoutError(
                    f"Timeout UDS servicio 0x{service:02X}"
                )
            try:
                response = await self.transport.recv(min(p2_star, remaining))
            except asyncio.TimeoutError as exc:
                raise ECUTimeoutError(
                    f"Timeout UDS servicio 0x{service:02X}"
                ) from exc

            if not response:
                continue
            self._log.debug("RX UDS: %s", response.hex())

            if response[0] == 0x7F:
                if len(response) < 3:
                    raise UDSError(
                        f"Respuesta negativa malformada: {response.hex()}"
                    )
                nr_service, nrc = response[1], response[2]
                if nrc == 0x78:
                    self._log.debug(
                        "NRC 0x78 (pending) servicio 0x%02X", nr_service
                    )
                    continue
                raise NegativeResponseError(
                    nr_service,
                    nrc,
                    NEGATIVE_RESPONSE_CODES.get(nrc, "desconocido"),
                )

            if response[0] != service + 0x40:
                self._log.debug(
                    "Respuesta con SID inesperado: 0x%02X", response[0]
                )
                continue

            return response[1:]

    # ------------------------------------------------------------------
    # Servicios estándar
    # ------------------------------------------------------------------

    async def enter_diagnostic_session(
        self, session_type: DiagnosticSession
    ) -> bool:
        """Service 0x10 - DiagnosticSessionControl."""
        mapping = {
            DiagnosticSession.DEFAULT: UDSSubFunction.DEFAULT_SESSION,
            DiagnosticSession.PROGRAMMING: UDSSubFunction.PROGRAMMING_SESSION,
            DiagnosticSession.EXTENDED: UDSSubFunction.EXTENDED_DIAGNOSTIC_SESSION,
            DiagnosticSession.SAFETY_SYSTEM: UDSSubFunction.SAFETY_SYSTEM_DIAGNOSTIC_SESSION,
        }
        sub = mapping.get(session_type, UDSSubFunction.EXTENDED_DIAGNOSTIC_SESSION)
        await self._request(
            UDSService.DIAGNOSTIC_SESSION_CONTROL, bytes([sub])
        )
        self.state = DriverState.SESSION_ACTIVE
        self._log.info("Sesión UDS activa: 0x%02X", sub)
        return True

    async def ecu_reset(
        self, reset_type: int = UDSSubFunction.HARD_RESET
    ) -> None:
        """Service 0x11 - ECUReset."""
        await self._request(UDSService.ECU_RESET, bytes([reset_type]))

    async def clear_diagnostic_information(
        self, group_of_dtc: int = 0xFFFFFF
    ) -> None:
        """Service 0x14 - ClearDiagnosticInformation."""
        await self._request(
            UDSService.CLEAR_DIAGNOSTIC_INFORMATION,
            group_of_dtc.to_bytes(3, "big"),
        )

    async def read_dtc_information(
        self,
        subfunction: int = UDSSubFunction.REPORT_DTC_BY_STATUS,
        status_mask: int = 0xFF,
    ) -> bytes:
        """Service 0x19 - ReadDTCInformation."""
        resp = await self._request(
            UDSService.READ_DTC_INFORMATION,
            bytes([subfunction, status_mask]),
        )
        return resp

    async def read_data_by_identifier(self, did: int) -> bytes:
        """Service 0x22 - ReadDataByIdentifier."""
        payload = did.to_bytes(2, "big")
        resp = await self._request(UDSService.READ_DATA_BY_IDENTIFIER, payload)
        # Respuesta: [DID_H DID_L DATA...]
        if len(resp) < 2 or resp[0] != payload[0] or resp[1] != payload[1]:
            raise UDSError(
                f"Respuesta RDBI con DID inesperado (esperaba 0x{did:04X})"
            )
        return resp[2:]

    async def read_memory_by_address(
        self,
        address: int,
        length: int,
        address_length: Optional[int] = None,
        length_length: Optional[int] = None,
    ) -> bytes:
        """
        Service 0x23 - ReadMemoryByAddress.

        Usa el addressAndLengthFormatIdentifier codificado al estilo UDS.
        """
        al = address_length or self.config.address_length
        ll = length_length or self.config.length_length
        if al not in (1, 2, 3, 4) or ll not in (1, 2, 3, 4):
            raise ValueError("address_length y length_length deben ser 1-4")

        format_id = (ll << 4) | al
        payload = (
            bytes([format_id])
            + address.to_bytes(al, "big")
            + length.to_bytes(ll, "big")
        )
        resp = await self._request(
            UDSService.READ_MEMORY_BY_ADDRESS,
            payload,
            timeout=max(self.timeout, 2.0),
        )
        return resp

    async def security_access(
        self,
        level: int,
        seed_key_algorithm: Callable[[bytes], bytes],
    ) -> bool:
        """
        Service 0x27 - SecurityAccess (seed-key).

        Args:
            level: Nivel impar (request seed).
            seed_key_algorithm: Callable seed -> key.
        """
        if level % 2 == 0:
            raise ValueError("El nivel debe ser impar (request seed)")

        resp = await self._request(
            UDSService.SECURITY_ACCESS, bytes([level])
        )
        # resp = [level SEED...]
        if len(resp) < 2 or resp[0] != level:
            raise SecurityError("Respuesta inválida a RequestSeed")
        seed = resp[1:]
        if all(b == 0 for b in seed):
            self._log.info("Seguridad UDS ya estaba desbloqueada")
            self._security_unlocked_level = level + 1
            self.state = DriverState.SECURITY_UNLOCKED
            return True

        try:
            key = seed_key_algorithm(seed)
        except Exception as exc:
            raise SecurityError(
                f"Algoritmo seed->key falló: {exc}"
            ) from exc

        await self._request(
            UDSService.SECURITY_ACCESS,
            bytes([level + 1]) + bytes(key),
        )
        self._security_unlocked_level = level + 1
        self.state = DriverState.SECURITY_UNLOCKED
        self._log.info("Seguridad UDS desbloqueada nivel %d", level + 1)
        return True

    async def communication_control(
        self,
        control_type: int,
        communication_type: int = 0x01,
    ) -> None:
        """Service 0x28 - CommunicationControl."""
        await self._request(
            UDSService.COMMUNICATION_CONTROL,
            bytes([control_type, communication_type]),
        )

    async def write_data_by_identifier(self, did: int, data: bytes) -> None:
        """Service 0x2E - WriteDataByIdentifier."""
        payload = did.to_bytes(2, "big") + data
        await self._request(UDSService.WRITE_DATA_BY_IDENTIFIER, payload)

    async def routine_control(
        self,
        routine_id: int,
        subfunction: int = UDSSubFunction.START_ROUTINE,
        parameters: bytes = b"",
    ) -> bytes:
        """Service 0x31 - RoutineControl."""
        payload = bytes([subfunction]) + routine_id.to_bytes(2, "big") + parameters
        resp = await self._request(UDSService.ROUTINE_CONTROL, payload)
        return resp

    async def request_download(
        self,
        address: int,
        size: int,
        data_format: int = 0x00,
        address_length: int = 4,
        length_length: int = 4,
    ) -> int:
        """
        Service 0x34 - RequestDownload.

        Returns:
            max_number_of_block_length (bytes por bloque en TransferData).
        """
        alfid = (length_length << 4) | address_length
        payload = (
            bytes([data_format, alfid])
            + address.to_bytes(address_length, "big")
            + size.to_bytes(length_length, "big")
        )
        resp = await self._request(UDSService.REQUEST_DOWNLOAD, payload)
        # resp = [lengthFormatId maxNumberOfBlockLength...]
        if not resp:
            raise UDSError("Respuesta vacía a RequestDownload")
        length_format = (resp[0] >> 4) & 0x0F
        max_block = int.from_bytes(resp[1:1 + length_format], "big")
        return max_block

    async def transfer_data(
        self, block_sequence_counter: int, data: bytes
    ) -> bytes:
        """Service 0x36 - TransferData."""
        resp = await self._request(
            UDSService.TRANSFER_DATA,
            bytes([block_sequence_counter & 0xFF]) + data,
            timeout=5.0,
        )
        return resp

    async def request_transfer_exit(self, checksum: bytes = b"") -> bytes:
        """Service 0x37 - RequestTransferExit."""
        resp = await self._request(
            UDSService.REQUEST_TRANSFER_EXIT, checksum
        )
        return resp

    async def write_memory_by_address(
        self,
        address: int,
        data: bytes,
        address_length: int = 4,
        length_length: int = 2,
    ) -> None:
        """Service 0x3D - WriteMemoryByAddress."""
        alfid = (length_length << 4) | address_length
        payload = (
            bytes([alfid])
            + address.to_bytes(address_length, "big")
            + len(data).to_bytes(length_length, "big")
            + data
        )
        await self._request(UDSService.WRITE_MEMORY_BY_ADDRESS, payload)

    async def send_tester_present(self) -> None:
        """Service 0x3E - TesterPresent (con suppress positive response)."""
        # 0x80 en subfunción -> suppressPosRspMsgIndicationBit
        try:
            await self._request(
                UDSService.TESTER_PRESENT,
                bytes([0x00]),
                expect_response=True,
                timeout=0.5,
            )
        except ECUTimeoutError:
            # Algunas ECUs usan suppress positive response
            pass

    # ------------------------------------------------------------------
    # Implementación BaseECUDriver
    # ------------------------------------------------------------------

    async def read_ecu_id(self) -> ECUIdentification:
        """Lee identificadores estándar F180-F199."""
        ident = ECUIdentification()
        mapping: dict[CommonDID, str] = {
            CommonDID.VIN: "vin",
            CommonDID.VEHICLE_MANUFACTURER_SPARE_PART_NUMBER: "part_number",
            CommonDID.VEHICLE_MANUFACTURER_ECU_HARDWARE_NUMBER: "hardware_number",
            CommonDID.VEHICLE_MANUFACTURER_ECU_SW_NUMBER: "software_number",
            CommonDID.VEHICLE_MANUFACTURER_ECU_SW_VERSION: "software_version",
            CommonDID.SYSTEM_SUPPLIER_ECU_HARDWARE_VERSION: "hardware_version",
            CommonDID.SYSTEM_SUPPLIER_IDENTIFIER: "supplier_id",
            CommonDID.ECU_MANUFACTURING_DATE: "programming_date",
            CommonDID.ECU_SERIAL_NUMBER: "serial_number",
            CommonDID.BOOT_SOFTWARE_IDENTIFICATION: "boot_software_id",
            CommonDID.APPLICATION_SOFTWARE_IDENTIFICATION: "application_software_id",
            CommonDID.APPLICATION_DATA_IDENTIFICATION: "application_data_id",
            CommonDID.PROGRAMMING_DATE: "programming_date",
        }

        for did, attr in mapping.items():
            try:
                data = await self.read_data_by_identifier(int(did))
                ident.raw_identifiers[int(did)] = data
                try:
                    value = data.rstrip(b"\x00\xFF ").decode("ascii")
                except UnicodeDecodeError:
                    value = data.hex().upper()
                if not getattr(ident, attr, None):
                    setattr(ident, attr, value)
            except (NegativeResponseError, ECUTimeoutError) as exc:
                self._log.debug(
                    "DID 0x%04X no disponible: %s", int(did), exc
                )

        return ident

    async def read_vin(self) -> str:
        data = await self.read_data_by_identifier(int(CommonDID.VIN))
        return data.rstrip(b"\x00\xFF ").decode("ascii", errors="replace")

    async def read_software_version(self) -> str:
        data = await self.read_data_by_identifier(
            int(CommonDID.VEHICLE_MANUFACTURER_ECU_SW_VERSION)
        )
        return data.rstrip(b"\x00\xFF ").decode("ascii", errors="replace")

    async def read_hardware_version(self) -> str:
        try:
            data = await self.read_data_by_identifier(
                int(CommonDID.SYSTEM_SUPPLIER_ECU_HARDWARE_VERSION)
            )
        except (NegativeResponseError, ECUTimeoutError):
            data = await self.read_data_by_identifier(
                int(CommonDID.VEHICLE_MANUFACTURER_ECU_HARDWARE_NUMBER)
            )
        return data.rstrip(b"\x00\xFF ").decode("ascii", errors="replace")

    async def read_calibration_data(
        self, start_addr: int, length: int
    ) -> bytes:
        """Lectura de memoria en bloques con Service 0x23."""
        chunk_size = min(length, self.config.block_size)
        data = bytearray()
        offset = 0
        while offset < length:
            to_read = min(chunk_size, length - offset)
            chunk = await self.read_memory_by_address(
                start_addr + offset, to_read
            )
            if not chunk:
                raise UDSError(
                    f"Lectura vacía en 0x{start_addr + offset:08X}"
                )
            data.extend(chunk)
            offset += len(chunk)
        return bytes(data)
