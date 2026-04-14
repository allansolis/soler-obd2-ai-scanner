"""
Base Driver - Clase abstracta base para todos los controladores de ECU.

Define la interfaz común que todos los drivers específicos de protocolo
(UDS, KWP2000, OBD-II, etc.) deben implementar.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class DriverState(Enum):
    """Estados del controlador."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    SESSION_ACTIVE = "session_active"
    SECURITY_UNLOCKED = "security_unlocked"
    READING = "reading"
    ERROR = "error"


class DiagnosticSession(Enum):
    """Tipos de sesión diagnóstica."""
    DEFAULT = 0x01
    PROGRAMMING = 0x02
    EXTENDED = 0x03
    SAFETY_SYSTEM = 0x04


@dataclass
class ECUIdentification:
    """
    Identificación completa de una ECU.

    Contiene todos los datos de identificación leídos desde la ECU:
    VIN, versiones de software/hardware, números de parte, calibración, etc.
    """
    vin: Optional[str] = None
    ecu_name: Optional[str] = None
    manufacturer: Optional[str] = None
    part_number: Optional[str] = None
    hardware_number: Optional[str] = None
    software_number: Optional[str] = None
    software_version: Optional[str] = None
    hardware_version: Optional[str] = None
    calibration_id: Optional[str] = None
    calibration_verification_number: Optional[str] = None
    serial_number: Optional[str] = None
    supplier_id: Optional[str] = None
    programming_date: Optional[str] = None
    boot_software_id: Optional[str] = None
    application_software_id: Optional[str] = None
    application_data_id: Optional[str] = None
    raw_identifiers: dict[int, bytes] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convierte la identificación a diccionario serializable."""
        return {
            "vin": self.vin,
            "ecu_name": self.ecu_name,
            "manufacturer": self.manufacturer,
            "part_number": self.part_number,
            "hardware_number": self.hardware_number,
            "software_number": self.software_number,
            "software_version": self.software_version,
            "hardware_version": self.hardware_version,
            "calibration_id": self.calibration_id,
            "calibration_verification_number": self.calibration_verification_number,
            "serial_number": self.serial_number,
            "supplier_id": self.supplier_id,
            "programming_date": self.programming_date,
            "boot_software_id": self.boot_software_id,
            "application_software_id": self.application_software_id,
            "application_data_id": self.application_data_id,
            "raw_identifiers": {
                f"0x{k:04X}": v.hex() for k, v in self.raw_identifiers.items()
            },
        }


class ECUDriverError(Exception):
    """Excepción base para errores del driver de ECU."""


class ConnectionError(ECUDriverError):
    """Error al conectar con la ECU."""


class TimeoutError(ECUDriverError):
    """Timeout en la comunicación con la ECU."""


class SecurityError(ECUDriverError):
    """Error de acceso de seguridad."""


class NegativeResponseError(ECUDriverError):
    """Respuesta negativa de la ECU."""

    def __init__(self, service: int, nrc: int, message: str = ""):
        self.service = service
        self.nrc = nrc
        super().__init__(
            f"Respuesta negativa: servicio 0x{service:02X}, NRC 0x{nrc:02X} - {message}"
        )


class BaseECUDriver(ABC):
    """
    Clase base abstracta para controladores de ECU.

    Todos los drivers específicos (UDS, KWP2000, OBD) deben heredar de esta
    clase e implementar los métodos abstractos. Proporciona la interfaz
    unificada para el sistema SOLER.
    """

    def __init__(
        self,
        ecu_address: int = 0x7E0,
        response_address: int = 0x7E8,
        timeout: float = 2.0,
        tester_present_interval: float = 2.0,
    ):
        """
        Inicializa el driver base.

        Args:
            ecu_address: Dirección de la ECU (request ID)
            response_address: Dirección de respuesta (response ID)
            timeout: Timeout por defecto en segundos
            tester_present_interval: Intervalo del TesterPresent (segundos)
        """
        self.ecu_address = ecu_address
        self.response_address = response_address
        self.timeout = timeout
        self.tester_present_interval = tester_present_interval
        self.state: DriverState = DriverState.DISCONNECTED
        self._tester_present_task: Optional[asyncio.Task] = None
        self._progress_callback: Optional[Callable[[int, int], None]] = None
        self._log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ------------------------------------------------------------------
    # Métodos abstractos que deben implementar las subclases
    # ------------------------------------------------------------------

    @abstractmethod
    async def connect(self) -> bool:
        """
        Establece conexión con la ECU.

        Returns:
            True si la conexión fue exitosa, False en caso contrario.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Cierra la conexión con la ECU."""

    @abstractmethod
    async def read_ecu_id(self) -> ECUIdentification:
        """
        Lee toda la identificación de la ECU.

        Returns:
            Objeto ECUIdentification completo.
        """

    @abstractmethod
    async def read_vin(self) -> str:
        """Lee el VIN del vehículo."""

    @abstractmethod
    async def read_software_version(self) -> str:
        """Lee la versión del software de la ECU."""

    @abstractmethod
    async def read_hardware_version(self) -> str:
        """Lee la versión del hardware de la ECU."""

    @abstractmethod
    async def read_calibration_data(self, start_addr: int, length: int) -> bytes:
        """
        Lee una región de datos de calibración desde la ECU.

        Args:
            start_addr: Dirección inicial en memoria de la ECU
            length: Cantidad de bytes a leer

        Returns:
            Bytes leídos de la memoria de la ECU.
        """

    @abstractmethod
    async def send_tester_present(self) -> None:
        """Envía una petición TesterPresent para mantener la sesión activa."""

    @abstractmethod
    async def enter_diagnostic_session(
        self, session_type: DiagnosticSession
    ) -> bool:
        """
        Entra en una sesión diagnóstica específica.

        Args:
            session_type: Tipo de sesión a entrar.

        Returns:
            True si entró correctamente.
        """

    @abstractmethod
    async def security_access(
        self,
        level: int,
        seed_key_algorithm: Callable[[bytes], bytes],
    ) -> bool:
        """
        Realiza el acceso de seguridad (seed-key challenge).

        Args:
            level: Nivel de seguridad solicitado.
            seed_key_algorithm: Callable que recibe el seed y devuelve la key.

        Returns:
            True si el acceso fue concedido.
        """

    # ------------------------------------------------------------------
    # Métodos concretos reutilizables
    # ------------------------------------------------------------------

    async def read_full_calibration(
        self,
        start_addr: Optional[int] = None,
        total_length: Optional[int] = None,
        block_size: int = 0x100,
    ) -> bytes:
        """
        Lee toda la calibración de la ECU en bloques.

        Args:
            start_addr: Dirección inicial (usa memory_map si es None).
            total_length: Longitud total (usa memory_map si es None).
            block_size: Tamaño de cada bloque de lectura.

        Returns:
            Buffer completo con los datos de calibración.
        """
        if start_addr is None or total_length is None:
            raise ValueError(
                "Se requiere start_addr y total_length o un mapa de memoria válido"
            )

        self._log.info(
            "Iniciando lectura completa de calibración: 0x%X bytes desde 0x%X",
            total_length,
            start_addr,
        )
        self.state = DriverState.READING
        data = bytearray()
        offset = 0

        try:
            while offset < total_length:
                chunk_len = min(block_size, total_length - offset)
                chunk = await self.read_calibration_data(
                    start_addr + offset, chunk_len
                )
                if not chunk:
                    raise ECUDriverError(
                        f"Lectura vacía en 0x{start_addr + offset:08X}"
                    )
                data.extend(chunk)
                offset += chunk_len

                if self._progress_callback:
                    try:
                        self._progress_callback(offset, total_length)
                    except Exception:  # pragma: no cover
                        self._log.debug("Callback de progreso falló", exc_info=True)

            self._log.info(
                "Lectura completa finalizada: %d bytes extraídos", len(data)
            )
            return bytes(data)
        finally:
            self.state = DriverState.CONNECTED

    def set_progress_callback(self, callback: Callable[[int, int], None]) -> None:
        """Registra un callback de progreso (current, total)."""
        self._progress_callback = callback

    async def start_tester_present_loop(self) -> None:
        """Lanza el bucle en segundo plano del TesterPresent."""
        if self._tester_present_task and not self._tester_present_task.done():
            return

        async def _loop() -> None:
            while self.state in (
                DriverState.SESSION_ACTIVE,
                DriverState.SECURITY_UNLOCKED,
                DriverState.READING,
            ):
                try:
                    await self.send_tester_present()
                except Exception as exc:  # pragma: no cover
                    self._log.warning("TesterPresent falló: %s", exc)
                await asyncio.sleep(self.tester_present_interval)

        self._tester_present_task = asyncio.create_task(_loop())

    async def stop_tester_present_loop(self) -> None:
        """Detiene el bucle del TesterPresent."""
        if self._tester_present_task:
            self._tester_present_task.cancel()
            try:
                await self._tester_present_task
            except (asyncio.CancelledError, Exception):
                pass
            self._tester_present_task = None

    async def __aenter__(self) -> "BaseECUDriver":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.disconnect()
