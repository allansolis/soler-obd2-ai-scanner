"""
OBD Read Driver - Lectura de calibración vía OBD-II (Modes 22 y 23).

Permite extraer información de ECUs que no exponen pila UDS/KWP2000
completa. Mode 22 es ReadDataByIdentifier genérico (muchos fabricantes
usan PIDs extendidos aquí), y Mode 23 es ReadMemoryByAddress obligatorio
para cumplir CARB en algunos grupos.

Es un fallback - funciona en más vehículos pero con limitaciones de
velocidad y rango de memoria accesible.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from .base_driver import (
    BaseECUDriver,
    DiagnosticSession,
    DriverState,
    ECUDriverError,
    ECUIdentification,
    NegativeResponseError,
    TimeoutError as ECUTimeoutError,
)

logger = logging.getLogger(__name__)


try:
    import obd  # type: ignore
    PYOBD_AVAILABLE = True
except Exception:  # pragma: no cover
    PYOBD_AVAILABLE = False
    obd = None  # type: ignore


# OBD-II Mode 09 PIDs (Vehicle Information)
MODE_09_PIDS = {
    "VIN": 0x02,
    "CALIBRATION_ID": 0x04,
    "CALIBRATION_VERIFICATION_NUMBER": 0x06,
    "ECU_NAME": 0x0A,
}


class OBDReadDriver(BaseECUDriver):
    """
    Driver OBD-II para lectura de identificación y memoria limitada.

    Usa Modes estándar:
      - Mode 09: Vehicle Information (VIN, Cal ID, CVN, ECU name)
      - Mode 22: ReadDataByIdentifier (DIDs extendidos)
      - Mode 23: ReadMemoryByAddress (memoria directa)
    """

    def __init__(
        self,
        transport,
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

    async def connect(self) -> bool:
        self.state = DriverState.CONNECTING
        try:
            await self.transport.open()
            self.state = DriverState.CONNECTED
            self._log.info("OBD-II conectado")
            return True
        except Exception as exc:
            self.state = DriverState.ERROR
            raise ECUDriverError(f"No se pudo conectar OBD-II: {exc}") from exc

    async def disconnect(self) -> None:
        try:
            await self.transport.close()
        finally:
            self.state = DriverState.DISCONNECTED

    # ------------------------------------------------------------------
    # Request helpers
    # ------------------------------------------------------------------

    async def _request(
        self,
        service: int,
        payload: bytes = b"",
        timeout: Optional[float] = None,
    ) -> bytes:
        """Envía petición y recibe respuesta OBD."""
        request = bytes([service]) + payload
        await self.transport.send(request)
        to = timeout or self.timeout
        try:
            response = await self.transport.recv(to)
        except asyncio.TimeoutError as exc:
            raise ECUTimeoutError(
                f"Timeout en OBD servicio 0x{service:02X}"
            ) from exc

        if not response:
            raise ECUDriverError("Respuesta OBD vacía")

        if response[0] == 0x7F:
            if len(response) >= 3:
                raise NegativeResponseError(response[1], response[2])
            raise ECUDriverError("NRC malformado")

        if response[0] != service + 0x40:
            raise ECUDriverError(
                f"SID inesperado: esperaba 0x{service + 0x40:02X}, "
                f"recibí 0x{response[0]:02X}"
            )
        return response[1:]

    # ------------------------------------------------------------------
    # Servicios
    # ------------------------------------------------------------------

    async def mode_09(self, pid: int) -> bytes:
        """OBD Mode 09 - Vehicle Information."""
        return await self._request(0x09, bytes([pid]))

    async def mode_22(self, did: int) -> bytes:
        """OBD Mode 22 - ReadDataByIdentifier (extensión)."""
        resp = await self._request(0x22, did.to_bytes(2, "big"))
        # resp = [DID_H DID_L data...]
        if len(resp) < 2:
            raise ECUDriverError("Respuesta mode 22 demasiado corta")
        return resp[2:]

    async def mode_23(
        self,
        address: int,
        length: int,
        address_bytes: int = 3,
    ) -> bytes:
        """OBD Mode 23 - ReadMemoryByAddress."""
        if length <= 0 or length > 255:
            raise ValueError("length debe estar entre 1 y 255")
        payload = address.to_bytes(address_bytes, "big") + bytes([length])
        resp = await self._request(0x23, payload, timeout=3.0)
        return resp

    # ------------------------------------------------------------------
    # Implementación BaseECUDriver
    # ------------------------------------------------------------------

    async def read_vin(self) -> str:
        """Lee VIN vía Mode 09 PID 02."""
        data = await self.mode_09(MODE_09_PIDS["VIN"])
        # Primer byte es el número de mensajes
        vin_bytes = data[1:] if len(data) > 17 else data
        return vin_bytes.rstrip(b"\x00 ").decode("ascii", errors="replace")

    async def read_software_version(self) -> str:
        data = await self.mode_09(MODE_09_PIDS["CALIBRATION_ID"])
        return data.rstrip(b"\x00 ").decode("ascii", errors="replace")

    async def read_hardware_version(self) -> str:
        try:
            data = await self.mode_09(MODE_09_PIDS["ECU_NAME"])
            return data.rstrip(b"\x00 ").decode("ascii", errors="replace")
        except (NegativeResponseError, ECUTimeoutError):
            return ""

    async def read_ecu_id(self) -> ECUIdentification:
        """Lee identificación disponible por OBD."""
        ident = ECUIdentification()
        for label, pid in MODE_09_PIDS.items():
            try:
                data = await self.mode_09(pid)
                ident.raw_identifiers[pid] = data
                decoded = data.rstrip(b"\x00\xFF ").decode(
                    "ascii", errors="replace"
                )
                if label == "VIN":
                    ident.vin = decoded
                elif label == "CALIBRATION_ID":
                    ident.calibration_id = decoded
                    ident.software_version = decoded
                elif label == "CALIBRATION_VERIFICATION_NUMBER":
                    ident.calibration_verification_number = data.hex().upper()
                elif label == "ECU_NAME":
                    ident.ecu_name = decoded
            except (NegativeResponseError, ECUTimeoutError) as exc:
                self._log.debug("PID Mode09 0x%02X no disponible: %s", pid, exc)
        return ident

    async def read_calibration_data(
        self, start_addr: int, length: int
    ) -> bytes:
        """Lectura vía Mode 23 en bloques."""
        data = bytearray()
        offset = 0
        CHUNK = 0xFE
        while offset < length:
            to_read = min(CHUNK, length - offset)
            chunk = await self.mode_23(start_addr + offset, to_read)
            if not chunk:
                raise ECUDriverError(
                    f"Lectura vacía en 0x{start_addr + offset:08X}"
                )
            data.extend(chunk)
            offset += len(chunk)
        return bytes(data)

    async def enter_diagnostic_session(
        self, session_type: DiagnosticSession
    ) -> bool:
        """OBD-II estándar no tiene sesiones; éste es un no-op."""
        self._log.debug("OBD no soporta sesiones diagnósticas; ignorando")
        return True

    async def send_tester_present(self) -> None:
        """OBD-II puro no usa TesterPresent. Mantiene compatibilidad."""
        return

    async def security_access(
        self,
        level: int,
        seed_key_algorithm: Callable[[bytes], bytes],
    ) -> bool:
        """OBD estándar no implementa seguridad."""
        raise ECUDriverError(
            "SecurityAccess no disponible en OBD-II estándar. "
            "Use UDSDriver o KWP2000Driver."
        )
