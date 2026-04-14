"""
SOLER OBD2 AI SCANNER - ECU Drivers Package
============================================

Paquete de controladores para comunicación con ECUs automotrices.

Este paquete implementa el subsistema completo de lectura de ECU para la
extracción de calibraciones binarias reales. Incluye soporte para:

- UDS (ISO 14229) - protocolo moderno de diagnóstico unificado
- KWP2000 (ISO 14230) - protocolo keyword legacy
- OBD-II Mode 22/23 - lectura extendida de memoria
- J2534 PassThru - interfaz con hardware de diagnóstico profesional
- Auto-detección de protocolo y ECU
- Mapas de memoria para ECUs conocidos (Bosch, Delphi, Siemens, Denso, etc.)

Uso típico:
    from backend.ecu_drivers import UDSDriver, ProtocolDetector

    protocol = await ProtocolDetector.detect()
    driver = UDSDriver(transport=...)
    await driver.connect()
    calibration = await driver.read_full_calibration()
"""

from .base_driver import BaseECUDriver, ECUIdentification, DriverState
from .j2534_driver import J2534Driver, J2534Protocol, J2534Error
from .kwp2000_driver import KWP2000Driver, KWP2000Service, KWP2000Error
from .uds_driver import UDSDriver, UDSService, UDSError
from .obd_read_driver import OBDReadDriver
from .ecu_identifier import ECUIdentifier, ECUManufacturer, ECUInfo
from .protocol_detector import ProtocolDetector, DetectedProtocol
from .memory_map import (
    MemoryMap,
    MemoryRegion,
    ECUMemoryMaps,
    get_memory_map,
    get_cal_region,
    get_checksum_location,
)

# Flash (write) subsystem
from .flash_base import (
    BaseECUFlasher,
    FlashBlock,
    FlashPackage,
    FlashPhase,
    FlashResult,
)
from .flash_exceptions import (
    ChecksumMismatchError,
    EraseFailedError,
    FlashError,
    FlashInterruptedError,
    FlashVerificationError,
    PowerUnstableError,
    ProgrammingModeError,
    SeedKeyFailedError,
    TemperatureOutOfRangeError,
    TesterPresentLostError,
    UnsupportedECUError,
    VoltageLowError,
    WriteFailedError,
)
from .seed_key_algorithms import SeedKeyAlgorithms
from .checksum_fixers import ChecksumFixer
from .bosch_flasher import BoschFlasher, BOSCH_REGIONS
from .delphi_flasher import DelphiFlasher, DELPHI_REGIONS
from .siemens_flasher import SiemensFlasher, SIEMENS_REGIONS
from .denso_flasher import DensoFlasher, DENSO_REGIONS
from .magnetti_marelli_flasher import MagnettiMarelliFlasher, MM_REGIONS
from .flash_orchestrator import FlashOrchestrator, SafetyReport

__all__ = [
    # Base
    "BaseECUDriver",
    "ECUIdentification",
    "DriverState",
    # J2534
    "J2534Driver",
    "J2534Protocol",
    "J2534Error",
    # KWP2000
    "KWP2000Driver",
    "KWP2000Service",
    "KWP2000Error",
    # UDS
    "UDSDriver",
    "UDSService",
    "UDSError",
    # OBD
    "OBDReadDriver",
    # Identification
    "ECUIdentifier",
    "ECUManufacturer",
    "ECUInfo",
    # Protocol detection
    "ProtocolDetector",
    "DetectedProtocol",
    # Memory maps
    "MemoryMap",
    "MemoryRegion",
    "ECUMemoryMaps",
    "get_memory_map",
    "get_cal_region",
    "get_checksum_location",
    # Flash subsystem
    "BaseECUFlasher",
    "FlashBlock",
    "FlashPackage",
    "FlashPhase",
    "FlashResult",
    "FlashError",
    "FlashInterruptedError",
    "ChecksumMismatchError",
    "SeedKeyFailedError",
    "VoltageLowError",
    "FlashVerificationError",
    "UnsupportedECUError",
    "ProgrammingModeError",
    "EraseFailedError",
    "WriteFailedError",
    "TesterPresentLostError",
    "TemperatureOutOfRangeError",
    "PowerUnstableError",
    "SeedKeyAlgorithms",
    "ChecksumFixer",
    "BoschFlasher",
    "BOSCH_REGIONS",
    "DelphiFlasher",
    "DELPHI_REGIONS",
    "SiemensFlasher",
    "SIEMENS_REGIONS",
    "DensoFlasher",
    "DENSO_REGIONS",
    "MagnettiMarelliFlasher",
    "MM_REGIONS",
    "FlashOrchestrator",
    "SafetyReport",
]

__version__ = "1.0.0"
