"""
ECU Identifier - Identificación de ECU basada en lecturas de DIDs y patrones.

Cada fabricante codifica de forma distinta sus identificadores de hardware y
software. Este módulo analiza los valores leídos de la ECU y determina:

  - Fabricante (Bosch, Delphi, Siemens/Continental, Denso, Marelli, etc.)
  - Familia / modelo específico (EDC17C54, MED17.5, SID208...)
  - Part number OEM
  - Protocolos soportados

Los patrones están basados en la documentación pública y bases de datos de
la comunidad (nefmoto, digital-kaos, EVC, etc.).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .base_driver import BaseECUDriver, ECUIdentification

logger = logging.getLogger(__name__)


class ECUManufacturer(Enum):
    """Fabricantes de ECU soportados."""
    BOSCH = "Bosch"
    DELPHI = "Delphi"
    SIEMENS_CONTINENTAL = "Siemens/Continental"
    DENSO = "Denso"
    MAGNETI_MARELLI = "Magneti Marelli"
    HITACHI = "Hitachi"
    VISTEON = "Visteon"
    MELCO = "Mitsubishi Electric"
    UNKNOWN = "Desconocido"


@dataclass
class ECUInfo:
    """Información consolidada de la ECU identificada."""
    manufacturer: ECUManufacturer = ECUManufacturer.UNKNOWN
    family: Optional[str] = None
    model: Optional[str] = None
    part_number: Optional[str] = None
    supported_protocols: list[str] = field(default_factory=list)
    raw_software_number: Optional[str] = None
    raw_hardware_number: Optional[str] = None
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "manufacturer": self.manufacturer.value,
            "family": self.family,
            "model": self.model,
            "part_number": self.part_number,
            "supported_protocols": self.supported_protocols,
            "raw_software_number": self.raw_software_number,
            "raw_hardware_number": self.raw_hardware_number,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# Patrones de identificación por fabricante
# ---------------------------------------------------------------------------

# Patrones Bosch - formato típico: 0281016000, 0261S01234, etc.
BOSCH_FAMILY_PATTERNS = [
    # EDC (Diesel)
    (re.compile(r"EDC15[A-Z]?\d*", re.I), "EDC15"),
    (re.compile(r"EDC16[A-Z]?\d*", re.I), "EDC16"),
    (re.compile(r"EDC17[A-Z]?\d+", re.I), "EDC17"),
    (re.compile(r"MD1C[PS]", re.I), "MD1CP"),
    (re.compile(r"MG1C[SP]", re.I), "MG1"),
    # ME/MED/MEV (Gasolina)
    (re.compile(r"\bME7(\.\d+)?\b", re.I), "ME7"),
    (re.compile(r"\bME9(\.\d+)?\b", re.I), "ME9"),
    (re.compile(r"\bMED9(\.\d+)?\b", re.I), "MED9"),
    (re.compile(r"MED17(\.\d+(\.\d+)?)?", re.I), "MED17"),
    (re.compile(r"MEV17(\.\d+(\.\d+)?)?", re.I), "MEV17"),
    (re.compile(r"MEVD17(\.\d+(\.\d+)?)?", re.I), "MEVD17"),
    (re.compile(r"MG1", re.I), "MG1"),
    # Motronic BMW
    (re.compile(r"MSD8[015]", re.I), "MSD80/MSD81/MSD85"),
    (re.compile(r"MSV7\d", re.I), "MSV70/MSV80"),
    (re.compile(r"MSS6\d", re.I), "MSS60/MSS65"),
]

BOSCH_NUMBER_PREFIXES = ("0281", "0261", "0280", "0265")


# Patrones Delphi - DCM* (Diesel), MT* (Gasolina)
DELPHI_FAMILY_PATTERNS = [
    (re.compile(r"DCM3\.5", re.I), "DCM3.5"),
    (re.compile(r"DCM3\.7", re.I), "DCM3.7"),
    (re.compile(r"DCM6\.1", re.I), "DCM6.1"),
    (re.compile(r"DCM6\.2", re.I), "DCM6.2"),
    (re.compile(r"DCM7\.1[AB]?", re.I), "DCM7.1"),
    (re.compile(r"MT0[56]", re.I), "MT05/MT06"),
]

DELPHI_NUMBER_HINTS = ("28", "DCM", "DELPHI")


# Patrones Siemens/Continental
SIEMENS_FAMILY_PATTERNS = [
    (re.compile(r"SID201", re.I), "SID201"),
    (re.compile(r"SID20[3-9]", re.I), "SID203-209"),
    (re.compile(r"SID208", re.I), "SID208"),
    (re.compile(r"SID80[37]", re.I), "SID803/SID807"),
    (re.compile(r"SIMOS\s*PCR2\.1", re.I), "SIMOS PCR2.1"),
    (re.compile(r"SIMOS\s*1[08]", re.I), "SIMOS 10/18"),
    (re.compile(r"EMS3\d{3}", re.I), "EMS3120/EMS3132"),
    (re.compile(r"C(?:onti)?\s*SID", re.I), "Continental SID"),
]


# Patrones Denso - Part numbers tipo 275000-XXXX, 89560-XXXXX
DENSO_FAMILY_PATTERNS = [
    (re.compile(r"2750\d{2}"), "Denso 275000-series"),
    (re.compile(r"2760\d{2}"), "Denso 276000-series"),
    (re.compile(r"2790\d{2}"), "Denso 279000-series"),
    (re.compile(r"89560-[A-Z0-9]+"), "Denso Toyota"),
    (re.compile(r"MB\d{9}"), "Denso Mitsubishi"),
]


# Patrones Magneti Marelli
MARELLI_FAMILY_PATTERNS = [
    (re.compile(r"IAW\s*\d[A-Z]?(\.[A-Z]+)?", re.I), "IAW"),
    (re.compile(r"MJD\s*\d\.\d+", re.I), "MJD"),
    (re.compile(r"8DP\d+|8DF\d+"), "Marelli 8DF/8DP"),
]


# Protocolos soportados por familia
FAMILY_PROTOCOLS: dict[str, list[str]] = {
    "EDC15": ["KWP2000"],
    "EDC16": ["KWP2000", "UDS"],
    "EDC17": ["UDS", "KWP2000"],
    "MD1CP": ["UDS"],
    "MG1": ["UDS"],
    "ME7": ["KWP2000"],
    "ME9": ["KWP2000", "UDS"],
    "MED9": ["KWP2000"],
    "MED17": ["UDS"],
    "MEV17": ["UDS"],
    "MEVD17": ["UDS"],
    "MSD80/MSD81/MSD85": ["UDS", "KWP2000"],
    "MSV70/MSV80": ["KWP2000"],
    "MSS60/MSS65": ["KWP2000"],
    "DCM3.5": ["KWP2000"],
    "DCM3.7": ["KWP2000", "UDS"],
    "DCM6.1": ["UDS"],
    "DCM6.2": ["UDS"],
    "DCM7.1": ["UDS"],
    "MT05/MT06": ["KWP2000"],
    "SID201": ["KWP2000"],
    "SID203-209": ["UDS", "KWP2000"],
    "SID208": ["UDS"],
    "SID803/SID807": ["UDS"],
    "SIMOS PCR2.1": ["UDS"],
    "SIMOS 10/18": ["UDS"],
    "EMS3120/EMS3132": ["UDS"],
    "IAW": ["KWP2000"],
    "MJD": ["KWP2000", "UDS"],
    "Denso 275000-series": ["UDS", "KWP2000"],
    "Denso 276000-series": ["UDS"],
    "Denso 279000-series": ["UDS"],
}


# ---------------------------------------------------------------------------
# Identificador
# ---------------------------------------------------------------------------


class ECUIdentifier:
    """
    Identifica el modelo exacto de una ECU analizando sus identificadores.

    Uso:
        ident = await driver.read_ecu_id()
        info = ECUIdentifier.identify(ident)
        print(info.manufacturer, info.family, info.supported_protocols)
    """

    @staticmethod
    def identify(identification: ECUIdentification) -> ECUInfo:
        """
        Clasifica una ECU a partir de su ECUIdentification.

        Args:
            identification: Datos crudos leídos de la ECU.

        Returns:
            ECUInfo con fabricante, familia, modelo, part number y protocolos.
        """
        info = ECUInfo(
            raw_software_number=identification.software_number,
            raw_hardware_number=identification.hardware_number,
        )

        # Concatenamos todos los strings candidatos
        candidates = [
            identification.software_number,
            identification.software_version,
            identification.hardware_number,
            identification.hardware_version,
            identification.part_number,
            identification.ecu_name,
            identification.calibration_id,
            identification.application_software_id,
            identification.boot_software_id,
            identification.supplier_id,
        ]
        search_text = " ".join(c for c in candidates if c)

        # También incluimos raw_identifiers decodificados
        for raw in identification.raw_identifiers.values():
            try:
                decoded = raw.rstrip(b"\x00\xFF ").decode("ascii")
                search_text += " " + decoded
            except UnicodeDecodeError:
                continue

        if not search_text.strip():
            logger.warning("No hay datos suficientes para identificar la ECU")
            return info

        # 1) Intentar Bosch
        manuf, family, confidence = ECUIdentifier._match_bosch(search_text)
        if manuf:
            info.manufacturer = manuf
            info.family = family
            info.confidence = confidence

        # 2) Delphi
        if info.manufacturer is ECUManufacturer.UNKNOWN:
            manuf, family, confidence = ECUIdentifier._match_delphi(search_text)
            if manuf:
                info.manufacturer = manuf
                info.family = family
                info.confidence = confidence

        # 3) Siemens/Continental
        if info.manufacturer is ECUManufacturer.UNKNOWN:
            manuf, family, confidence = ECUIdentifier._match_siemens(search_text)
            if manuf:
                info.manufacturer = manuf
                info.family = family
                info.confidence = confidence

        # 4) Denso
        if info.manufacturer is ECUManufacturer.UNKNOWN:
            manuf, family, confidence = ECUIdentifier._match_denso(search_text)
            if manuf:
                info.manufacturer = manuf
                info.family = family
                info.confidence = confidence

        # 5) Magneti Marelli
        if info.manufacturer is ECUManufacturer.UNKNOWN:
            manuf, family, confidence = ECUIdentifier._match_marelli(search_text)
            if manuf:
                info.manufacturer = manuf
                info.family = family
                info.confidence = confidence

        # Part number
        info.part_number = (
            identification.part_number
            or identification.hardware_number
            or identification.software_number
        )

        # Modelo específico (por defecto = familia, puede refinarse)
        info.model = info.family

        # Protocolos soportados
        if info.family and info.family in FAMILY_PROTOCOLS:
            info.supported_protocols = list(FAMILY_PROTOCOLS[info.family])
        else:
            info.supported_protocols = ["UDS", "KWP2000"]

        return info

    # ------------------------------------------------------------------
    # Matchers
    # ------------------------------------------------------------------

    @staticmethod
    def _match_bosch(
        text: str,
    ) -> tuple[Optional[ECUManufacturer], Optional[str], float]:
        for regex, family in BOSCH_FAMILY_PATTERNS:
            if regex.search(text):
                return ECUManufacturer.BOSCH, family, 0.95
        for prefix in BOSCH_NUMBER_PREFIXES:
            if prefix in text:
                return ECUManufacturer.BOSCH, None, 0.7
        if "BOSCH" in text.upper():
            return ECUManufacturer.BOSCH, None, 0.6
        return None, None, 0.0

    @staticmethod
    def _match_delphi(
        text: str,
    ) -> tuple[Optional[ECUManufacturer], Optional[str], float]:
        for regex, family in DELPHI_FAMILY_PATTERNS:
            if regex.search(text):
                return ECUManufacturer.DELPHI, family, 0.95
        for hint in DELPHI_NUMBER_HINTS:
            if hint in text.upper():
                return ECUManufacturer.DELPHI, None, 0.65
        return None, None, 0.0

    @staticmethod
    def _match_siemens(
        text: str,
    ) -> tuple[Optional[ECUManufacturer], Optional[str], float]:
        for regex, family in SIEMENS_FAMILY_PATTERNS:
            if regex.search(text):
                return ECUManufacturer.SIEMENS_CONTINENTAL, family, 0.95
        if any(
            k in text.upper()
            for k in ("SIEMENS", "CONTINENTAL", "VDO", "TEMIC")
        ):
            return ECUManufacturer.SIEMENS_CONTINENTAL, None, 0.65
        return None, None, 0.0

    @staticmethod
    def _match_denso(
        text: str,
    ) -> tuple[Optional[ECUManufacturer], Optional[str], float]:
        for regex, family in DENSO_FAMILY_PATTERNS:
            if regex.search(text):
                return ECUManufacturer.DENSO, family, 0.9
        if "DENSO" in text.upper():
            return ECUManufacturer.DENSO, None, 0.6
        return None, None, 0.0

    @staticmethod
    def _match_marelli(
        text: str,
    ) -> tuple[Optional[ECUManufacturer], Optional[str], float]:
        for regex, family in MARELLI_FAMILY_PATTERNS:
            if regex.search(text):
                return ECUManufacturer.MAGNETI_MARELLI, family, 0.9
        if "MARELLI" in text.upper() or "MAGNETI" in text.upper():
            return ECUManufacturer.MAGNETI_MARELLI, None, 0.6
        return None, None, 0.0

    # ------------------------------------------------------------------
    # Async helper
    # ------------------------------------------------------------------

    @staticmethod
    async def identify_from_driver(driver: BaseECUDriver) -> ECUInfo:
        """Lee la identificación desde un driver y clasifica la ECU."""
        ident = await driver.read_ecu_id()
        return ECUIdentifier.identify(ident)
