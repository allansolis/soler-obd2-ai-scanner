"""
Memory Map - Mapas de memoria de ECUs conocidos.

Define las regiones de memoria relevantes para la extracción y reprogramación
de calibración para ECUs populares. Los offsets y tamaños provienen de
documentación pública y de tools de la comunidad (WinOLS, ECM Titanium,
TunerPro, nefmoto, digital-kaos, etc.).

Cada mapa incluye:
  - Rango total de memoria flash
  - Región de calibración
  - Región de programa
  - Localización del checksum
  - Localización del VIN
  - Localización del Cal-ID (DAMOS)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class RegionType(Enum):
    """Tipos de región dentro de la memoria de la ECU."""
    BOOTLOADER = "bootloader"
    PROGRAM = "program"
    CALIBRATION = "calibration"
    DATA = "data"
    CHECKSUM = "checksum"
    VIN = "vin"
    CALIBRATION_ID = "calibration_id"
    EEPROM = "eeprom"


@dataclass
class MemoryRegion:
    """Región de memoria en la ECU."""
    name: str
    region_type: RegionType
    start_address: int
    end_address: int
    description: str = ""
    erasable: bool = True
    readable: bool = True
    writable: bool = False

    @property
    def size(self) -> int:
        return self.end_address - self.start_address + 1

    def contains(self, address: int) -> bool:
        return self.start_address <= address <= self.end_address

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "region_type": self.region_type.value,
            "start_address": f"0x{self.start_address:08X}",
            "end_address": f"0x{self.end_address:08X}",
            "size": self.size,
            "description": self.description,
            "erasable": self.erasable,
            "readable": self.readable,
            "writable": self.writable,
        }


@dataclass
class MemoryMap:
    """Mapa de memoria completo de una ECU."""
    ecu_type: str
    manufacturer: str
    total_flash_size: int
    regions: list[MemoryRegion] = field(default_factory=list)
    checksum_algorithm: Optional[str] = None
    endianness: str = "big"
    address_size_bytes: int = 4
    notes: str = ""

    def get_region(self, region_type: RegionType) -> Optional[MemoryRegion]:
        """Devuelve la primera región del tipo especificado."""
        for region in self.regions:
            if region.region_type == region_type:
                return region
        return None

    def get_all_regions(self, region_type: RegionType) -> list[MemoryRegion]:
        """Devuelve todas las regiones del tipo especificado."""
        return [r for r in self.regions if r.region_type == region_type]

    def region_for_address(self, address: int) -> Optional[MemoryRegion]:
        """Devuelve la región que contiene una dirección."""
        for region in self.regions:
            if region.contains(address):
                return region
        return None

    def to_dict(self) -> dict:
        return {
            "ecu_type": self.ecu_type,
            "manufacturer": self.manufacturer,
            "total_flash_size": self.total_flash_size,
            "checksum_algorithm": self.checksum_algorithm,
            "endianness": self.endianness,
            "address_size_bytes": self.address_size_bytes,
            "notes": self.notes,
            "regions": [r.to_dict() for r in self.regions],
        }


# ---------------------------------------------------------------------------
# Mapas conocidos
# ---------------------------------------------------------------------------


def _bosch_edc17c54() -> MemoryMap:
    """Bosch EDC17C54 - Diesel VAG/PSA (Tricore TC1796/TC1797)."""
    return MemoryMap(
        ecu_type="EDC17C54",
        manufacturer="Bosch",
        total_flash_size=0x400000,  # 4 MB total
        checksum_algorithm="Bosch-EDC17 CRC32 + checksums internos",
        endianness="little",
        notes="Región de calibración tipica 256 KB en 0x80820000-0x8085FFFF",
        regions=[
            MemoryRegion(
                name="Bootloader",
                region_type=RegionType.BOOTLOADER,
                start_address=0x80000000,
                end_address=0x8001FFFF,
                description="ROM bootloader protegido",
                writable=False,
                erasable=False,
            ),
            MemoryRegion(
                name="Program",
                region_type=RegionType.PROGRAM,
                start_address=0x80020000,
                end_address=0x8081FFFF,
                description="Código de aplicación (ASW)",
                writable=True,
            ),
            MemoryRegion(
                name="Calibration",
                region_type=RegionType.CALIBRATION,
                start_address=0x80820000,
                end_address=0x8085FFFF,
                description="Calibración (DAMOS) - 256 KB",
                writable=True,
            ),
            MemoryRegion(
                name="Checksum",
                region_type=RegionType.CHECKSUM,
                start_address=0x8085FF80,
                end_address=0x8085FFFF,
                description="Checksum de la calibración",
            ),
        ],
    )


def _bosch_med17_8_2() -> MemoryMap:
    """Bosch MED17.8.2 - Gasolina VAG (Tricore TC1797)."""
    return MemoryMap(
        ecu_type="MED17.8.2",
        manufacturer="Bosch",
        total_flash_size=0x400000,
        checksum_algorithm="Bosch-MED17 CRC32",
        endianness="little",
        regions=[
            MemoryRegion(
                name="Bootloader",
                region_type=RegionType.BOOTLOADER,
                start_address=0x80000000,
                end_address=0x8001FFFF,
                writable=False,
                erasable=False,
            ),
            MemoryRegion(
                name="Program",
                region_type=RegionType.PROGRAM,
                start_address=0x80020000,
                end_address=0x807FFFFF,
                writable=True,
            ),
            MemoryRegion(
                name="Calibration",
                region_type=RegionType.CALIBRATION,
                start_address=0x80800000,
                end_address=0x8087FFFF,
                description="Calibración MED17 - 512 KB",
                writable=True,
            ),
            MemoryRegion(
                name="Checksum",
                region_type=RegionType.CHECKSUM,
                start_address=0x8087FF00,
                end_address=0x8087FFFF,
            ),
        ],
    )


def _bosch_edc16c39() -> MemoryMap:
    """Bosch EDC16C39 - Diesel PSA/Ford (ST10F280/ST10F276)."""
    return MemoryMap(
        ecu_type="EDC16C39",
        manufacturer="Bosch",
        total_flash_size=0x180000,
        checksum_algorithm="Bosch-EDC16 Summen",
        endianness="little",
        regions=[
            MemoryRegion(
                name="Bootloader",
                region_type=RegionType.BOOTLOADER,
                start_address=0x000000,
                end_address=0x00FFFF,
                writable=False,
                erasable=False,
            ),
            MemoryRegion(
                name="Program",
                region_type=RegionType.PROGRAM,
                start_address=0x010000,
                end_address=0x0BFFFF,
                writable=True,
            ),
            MemoryRegion(
                name="Calibration",
                region_type=RegionType.CALIBRATION,
                start_address=0x0C0000,
                end_address=0x0FFFFF,
                description="256 KB de calibración EDC16",
                writable=True,
            ),
            MemoryRegion(
                name="Checksum",
                region_type=RegionType.CHECKSUM,
                start_address=0x0FFF00,
                end_address=0x0FFFFF,
            ),
        ],
    )


def _delphi_dcm37() -> MemoryMap:
    """Delphi DCM3.7 - Diesel Renault/Nissan (MPC5554/MPC5566)."""
    return MemoryMap(
        ecu_type="DCM3.7",
        manufacturer="Delphi",
        total_flash_size=0x100000,
        checksum_algorithm="Delphi CRC + bootsum",
        endianness="big",
        regions=[
            MemoryRegion(
                name="Bootloader",
                region_type=RegionType.BOOTLOADER,
                start_address=0x00000000,
                end_address=0x0001FFFF,
                writable=False,
                erasable=False,
            ),
            MemoryRegion(
                name="Program",
                region_type=RegionType.PROGRAM,
                start_address=0x00020000,
                end_address=0x000DFFFF,
                writable=True,
            ),
            MemoryRegion(
                name="Calibration",
                region_type=RegionType.CALIBRATION,
                start_address=0x000E0000,
                end_address=0x000FFFFF,
                description="Calibración DCM3.7",
                writable=True,
            ),
            MemoryRegion(
                name="Checksum",
                region_type=RegionType.CHECKSUM,
                start_address=0x000FFF80,
                end_address=0x000FFFFF,
            ),
        ],
    )


def _siemens_sid208() -> MemoryMap:
    """Siemens/Continental SID208 - Diesel PSA/Ford (MPC5566)."""
    return MemoryMap(
        ecu_type="SID208",
        manufacturer="Siemens/Continental",
        total_flash_size=0x200000,
        checksum_algorithm="Continental CRC16/32",
        endianness="big",
        regions=[
            MemoryRegion(
                name="Bootloader",
                region_type=RegionType.BOOTLOADER,
                start_address=0x00000000,
                end_address=0x0001FFFF,
                writable=False,
                erasable=False,
            ),
            MemoryRegion(
                name="Program",
                region_type=RegionType.PROGRAM,
                start_address=0x00020000,
                end_address=0x0017FFFF,
                writable=True,
            ),
            MemoryRegion(
                name="Calibration",
                region_type=RegionType.CALIBRATION,
                start_address=0x00180000,
                end_address=0x001FFFFF,
                description="Calibración SID208 - 512 KB",
                writable=True,
            ),
            MemoryRegion(
                name="Checksum",
                region_type=RegionType.CHECKSUM,
                start_address=0x001FFF00,
                end_address=0x001FFFFF,
            ),
        ],
    )


def _siemens_simos_pcr21() -> MemoryMap:
    """Siemens SIMOS PCR2.1 - Diesel VAG (Infineon TC1767)."""
    return MemoryMap(
        ecu_type="SIMOS PCR2.1",
        manufacturer="Siemens/Continental",
        total_flash_size=0x200000,
        checksum_algorithm="SIMOS CRC32",
        endianness="little",
        regions=[
            MemoryRegion(
                name="Bootloader",
                region_type=RegionType.BOOTLOADER,
                start_address=0x80000000,
                end_address=0x8001FFFF,
                writable=False,
                erasable=False,
            ),
            MemoryRegion(
                name="Program",
                region_type=RegionType.PROGRAM,
                start_address=0x80020000,
                end_address=0x8017FFFF,
                writable=True,
            ),
            MemoryRegion(
                name="Calibration",
                region_type=RegionType.CALIBRATION,
                start_address=0x80180000,
                end_address=0x801FFFFF,
                description="Calibración SIMOS PCR2.1",
                writable=True,
            ),
        ],
    )


def _denso_275000() -> MemoryMap:
    """Denso 275000 series - Toyota/Lexus (SH7058/SH7059)."""
    return MemoryMap(
        ecu_type="Denso 275000",
        manufacturer="Denso",
        total_flash_size=0x100000,
        checksum_algorithm="Denso sum + CRC",
        endianness="big",
        regions=[
            MemoryRegion(
                name="Bootloader",
                region_type=RegionType.BOOTLOADER,
                start_address=0x00000000,
                end_address=0x0000FFFF,
                writable=False,
                erasable=False,
            ),
            MemoryRegion(
                name="Program",
                region_type=RegionType.PROGRAM,
                start_address=0x00010000,
                end_address=0x000DFFFF,
                writable=True,
            ),
            MemoryRegion(
                name="Calibration",
                region_type=RegionType.CALIBRATION,
                start_address=0x000E0000,
                end_address=0x000FFFFF,
                description="Calibración Denso",
                writable=True,
            ),
            MemoryRegion(
                name="Checksum",
                region_type=RegionType.CHECKSUM,
                start_address=0x000FFF80,
                end_address=0x000FFFFF,
            ),
        ],
    )


def _marelli_mjd6() -> MemoryMap:
    """Magneti Marelli MJD6.x - Fiat/Alfa diesel (MPC563)."""
    return MemoryMap(
        ecu_type="MJD6",
        manufacturer="Magneti Marelli",
        total_flash_size=0x100000,
        checksum_algorithm="Marelli CRC",
        endianness="big",
        regions=[
            MemoryRegion(
                name="Bootloader",
                region_type=RegionType.BOOTLOADER,
                start_address=0x00000000,
                end_address=0x0001FFFF,
                writable=False,
                erasable=False,
            ),
            MemoryRegion(
                name="Program",
                region_type=RegionType.PROGRAM,
                start_address=0x00020000,
                end_address=0x000CFFFF,
                writable=True,
            ),
            MemoryRegion(
                name="Calibration",
                region_type=RegionType.CALIBRATION,
                start_address=0x000D0000,
                end_address=0x000FFFFF,
                description="Calibración MJD",
                writable=True,
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------


class ECUMemoryMaps:
    """Registro de mapas de memoria disponibles."""

    _MAPS: dict[str, MemoryMap] = {
        "EDC17C54": _bosch_edc17c54(),
        "MED17.8.2": _bosch_med17_8_2(),
        "EDC16C39": _bosch_edc16c39(),
        "DCM3.7": _delphi_dcm37(),
        "SID208": _siemens_sid208(),
        "SIMOS PCR2.1": _siemens_simos_pcr21(),
        "Denso 275000-series": _denso_275000(),
        "MJD": _marelli_mjd6(),
    }

    @classmethod
    def list_supported(cls) -> list[str]:
        """Devuelve los tipos de ECU con mapa de memoria conocido."""
        return sorted(cls._MAPS.keys())

    @classmethod
    def get(cls, ecu_type: str) -> Optional[MemoryMap]:
        """Obtiene el mapa por nombre exacto."""
        return cls._MAPS.get(ecu_type)

    @classmethod
    def find(cls, ecu_type: str) -> Optional[MemoryMap]:
        """Búsqueda tolerante (case-insensitive, prefijo)."""
        if not ecu_type:
            return None
        key = ecu_type.upper().strip()
        for name, m in cls._MAPS.items():
            if name.upper() == key:
                return m
        for name, m in cls._MAPS.items():
            if key.startswith(name.upper()) or name.upper().startswith(key):
                return m
        return None

    @classmethod
    def register(cls, memory_map: MemoryMap) -> None:
        """Registra un mapa nuevo en tiempo de ejecución."""
        cls._MAPS[memory_map.ecu_type] = memory_map


# ---------------------------------------------------------------------------
# Helpers a nivel módulo
# ---------------------------------------------------------------------------


def get_memory_map(ecu_type: str) -> Optional[MemoryMap]:
    """Obtiene el mapa de memoria para un tipo de ECU."""
    return ECUMemoryMaps.find(ecu_type)


def get_cal_region(ecu_type: str) -> Optional[MemoryRegion]:
    """Obtiene la región de calibración para un tipo de ECU."""
    m = get_memory_map(ecu_type)
    if m is None:
        return None
    return m.get_region(RegionType.CALIBRATION)


def get_checksum_location(ecu_type: str) -> Optional[MemoryRegion]:
    """Obtiene la región de checksum para un tipo de ECU."""
    m = get_memory_map(ecu_type)
    if m is None:
        return None
    return m.get_region(RegionType.CHECKSUM)
