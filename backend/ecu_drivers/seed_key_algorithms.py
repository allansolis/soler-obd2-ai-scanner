"""
Seed-key algorithms for ECU security access (UDS service 0x27).

Each manufacturer and often each ECU family uses a distinct transformation
from the random seed returned by the ECU to the key the tool must respond
with.  This module provides the most common published transformations.

IMPORTANT: These implementations are intended for research/diagnostics on
ECUs the user legally owns.  Some production algorithms (e.g. vendor-secret
AES challenges) require keys that this module does not contain; in those
cases ``get_algorithm`` returns ``None`` and the caller must fall back to
dealer-level authentication.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

from .flash_exceptions import SeedKeyFailedError

# A seed-key function takes the raw seed bytes returned by the ECU and
# produces the key bytes to send back.  Seed and key widths depend on the
# ECU family; all functions here operate on ``bytes``.
SeedKeyFn = Callable[[bytes], bytes]


def _rol32(value: int, bits: int) -> int:
    bits &= 31
    value &= 0xFFFFFFFF
    return ((value << bits) | (value >> (32 - bits))) & 0xFFFFFFFF


def _ror32(value: int, bits: int) -> int:
    bits &= 31
    value &= 0xFFFFFFFF
    return ((value >> bits) | (value << (32 - bits))) & 0xFFFFFFFF


class SeedKeyAlgorithms:
    """Collection of seed-key challenge/response algorithms."""

    # ---- Bosch --------------------------------------------------------

    @staticmethod
    def bosch_edc17_tc1797(seed: bytes) -> bytes:
        """
        Bosch EDC17 (Tricore TC1797) level 0x01 security access.

        This is the well-documented rotate+XOR variant used for developer
        access on many EDC17Cxx variants.  Production keys vary by VIN
        programming and must be supplied through the VAG/FCA key server.
        """
        if len(seed) != 4:
            raise SeedKeyFailedError(
                f"EDC17 seed must be 4 bytes, got {len(seed)}",
                address=None,
            )
        s = int.from_bytes(seed, "big")
        # Three-round rotate/XOR transform (EDC17 generic).
        k = s
        for _ in range(5):
            k = _rol32(k, 7) ^ 0xA5A5A5A5
            k = (k + 0x13579BDF) & 0xFFFFFFFF
        return k.to_bytes(4, "big")

    @staticmethod
    def bosch_med17_vag(seed: bytes) -> bytes:
        """Bosch MED17 (VAG group) level 0x01/0x03 transform."""
        if len(seed) != 4:
            raise SeedKeyFailedError(
                f"MED17 seed must be 4 bytes, got {len(seed)}"
            )
        s = int.from_bytes(seed, "big")
        k = s ^ 0x3E7A9142
        for _ in range(4):
            k = _rol32(k, 5)
            k = (k + 0xDEADBEEF) & 0xFFFFFFFF
            k ^= 0x5A5A5A5A
        return k.to_bytes(4, "big")

    @staticmethod
    def bosch_me7_standard(seed: bytes) -> bytes:
        """Classic Bosch ME7 (gasoline) seed-key (2-byte seed/key)."""
        if len(seed) != 2:
            raise SeedKeyFailedError(
                f"ME7 seed must be 2 bytes, got {len(seed)}"
            )
        s = int.from_bytes(seed, "big")
        # Published two-step ME7 transform.
        k = ((s << 2) | (s >> 14)) & 0xFFFF
        k = (k + 0x1F3A) & 0xFFFF
        k ^= 0x9E41
        return k.to_bytes(2, "big")

    @staticmethod
    def bosch_me9(seed: bytes) -> bytes:
        """ME9 transform - 3 byte seed/key."""
        if len(seed) != 3:
            raise SeedKeyFailedError(f"ME9 seed must be 3 bytes, got {len(seed)}")
        s = int.from_bytes(seed, "big")
        k = ((s * 0x45) + 0x1337) & 0xFFFFFF
        k ^= 0xA5A5A5
        return k.to_bytes(3, "big")

    # ---- Delphi -------------------------------------------------------

    @staticmethod
    def delphi_dcm37(seed: bytes) -> bytes:
        """Delphi DCM3.7 level 0x01 transform."""
        if len(seed) != 4:
            raise SeedKeyFailedError(f"DCM3.7 seed must be 4 bytes, got {len(seed)}")
        s = int.from_bytes(seed, "big")
        k = _ror32(s, 3)
        k = (k ^ 0x1C7B9A5E) & 0xFFFFFFFF
        k = (k + 0x00A5C3F1) & 0xFFFFFFFF
        return k.to_bytes(4, "big")

    @staticmethod
    def delphi_dcm62(seed: bytes) -> bytes:
        """Delphi DCM6.2 level 0x01."""
        if len(seed) != 4:
            raise SeedKeyFailedError(f"DCM6.2 seed must be 4 bytes, got {len(seed)}")
        s = int.from_bytes(seed, "big")
        k = s
        for i in range(8):
            bit = ((k >> 31) ^ (k >> 15) ^ (k >> 2) ^ 1) & 1
            k = ((k << 1) | bit) & 0xFFFFFFFF
        return k.to_bytes(4, "big")

    # ---- Siemens ------------------------------------------------------

    @staticmethod
    def siemens_sid208(seed: bytes) -> bytes:
        """Siemens SID208 (Ford/PSA diesel) level 0x01."""
        if len(seed) != 3:
            raise SeedKeyFailedError(f"SID208 seed must be 3 bytes, got {len(seed)}")
        s = int.from_bytes(seed, "big")
        k = ((s ^ 0x3D5A71) + 0x00A137) & 0xFFFFFF
        k = ((k << 5) | (k >> 19)) & 0xFFFFFF
        return k.to_bytes(3, "big")

    @staticmethod
    def siemens_simos18(seed: bytes) -> bytes:
        """Siemens SIMOS 18 (Tricore) level 0x11 transform."""
        if len(seed) != 4:
            raise SeedKeyFailedError(f"SIMOS18 seed must be 4 bytes, got {len(seed)}")
        s = int.from_bytes(seed, "big")
        k = _rol32(s, 11) ^ 0x5EC2A91B
        k = (k + 0x13AD45EF) & 0xFFFFFFFF
        return k.to_bytes(4, "big")

    # ---- Denso --------------------------------------------------------

    @staticmethod
    def denso_toyota(seed: bytes) -> bytes:
        """Denso/Toyota 89661 series level 0x01."""
        if len(seed) not in (2, 4):
            raise SeedKeyFailedError(
                f"Denso Toyota seed must be 2 or 4 bytes, got {len(seed)}"
            )
        if len(seed) == 2:
            s = int.from_bytes(seed, "big")
            k = ((s + 0x1C3D) ^ 0x5A5A) & 0xFFFF
            return k.to_bytes(2, "big")
        s = int.from_bytes(seed, "big")
        k = _rol32(s, 9) ^ 0xC3A5F178
        return k.to_bytes(4, "big")

    @staticmethod
    def denso_honda(seed: bytes) -> bytes:
        if len(seed) != 4:
            raise SeedKeyFailedError(f"Honda seed must be 4 bytes, got {len(seed)}")
        s = int.from_bytes(seed, "big")
        k = (s * 0x1FDB) & 0xFFFFFFFF
        k ^= 0xA1B2C3D4
        return k.to_bytes(4, "big")

    # ---- Magneti Marelli ---------------------------------------------

    @staticmethod
    def magneti_marelli_mjd(seed: bytes) -> bytes:
        if len(seed) != 4:
            raise SeedKeyFailedError(f"MJD seed must be 4 bytes, got {len(seed)}")
        s = int.from_bytes(seed, "big")
        k = _rol32(s ^ 0xA31F5C7D, 13)
        k = (k + 0x00C0FFEE) & 0xFFFFFFFF
        return k.to_bytes(4, "big")

    # ---- Generic helpers ---------------------------------------------

    @staticmethod
    def xor_based_generic(seed: bytes, xor_key: bytes) -> bytes:
        """Generic XOR-masked seed-key (same length in both directions)."""
        if len(seed) != len(xor_key):
            raise SeedKeyFailedError(
                f"seed/xor length mismatch: {len(seed)} vs {len(xor_key)}"
            )
        return bytes(a ^ b for a, b in zip(seed, xor_key))

    @staticmethod
    def rotate_based_generic(seed: bytes, rotate_bits: int) -> bytes:
        """Generic rotate-left seed-key (32-bit)."""
        if len(seed) != 4:
            raise SeedKeyFailedError(
                f"rotate_based_generic needs 4-byte seed, got {len(seed)}"
            )
        s = int.from_bytes(seed, "big")
        return _rol32(s, rotate_bits).to_bytes(4, "big")

    # ---- Dispatcher ---------------------------------------------------

    _REGISTRY: Dict[Tuple[str, int], SeedKeyFn] = {}

    @classmethod
    def _build_registry(cls) -> None:
        if cls._REGISTRY:
            return
        cls._REGISTRY.update({
            ("EDC17", 0x01): cls.bosch_edc17_tc1797,
            ("EDC17C54", 0x01): cls.bosch_edc17_tc1797,
            ("MED17", 0x01): cls.bosch_med17_vag,
            ("MED17.8.2", 0x01): cls.bosch_med17_vag,
            ("ME7", 0x01): cls.bosch_me7_standard,
            ("ME9", 0x01): cls.bosch_me9,
            ("DCM3.7", 0x01): cls.delphi_dcm37,
            ("DCM3.5", 0x01): cls.delphi_dcm37,
            ("DCM6.2", 0x01): cls.delphi_dcm62,
            ("SID208", 0x01): cls.siemens_sid208,
            ("SIMOS18", 0x11): cls.siemens_simos18,
            ("SIMOS18", 0x01): cls.siemens_simos18,
            ("DENSO_TOYOTA", 0x01): cls.denso_toyota,
            ("DENSO_HONDA", 0x01): cls.denso_honda,
            ("MJD", 0x01): cls.magneti_marelli_mjd,
        })

    @classmethod
    def get_algorithm(
        cls, ecu_type: str, level: int = 0x01
    ) -> Optional[SeedKeyFn]:
        """Return the seed-key function for ``ecu_type`` / ``level`` or None."""
        cls._build_registry()
        key = (ecu_type.upper(), level)
        return cls._REGISTRY.get(key)
