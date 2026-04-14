"""
Checksum repair utilities for modified ECU calibrations.

A modified calibration image written without repaired checksums will be
rejected by virtually every modern ECU.  This module provides the most
common repair routines used across Bosch, Delphi, Siemens, and Denso ECUs.

All functions are *pure*: they take a ``bytes`` image and return a new
``bytes`` image with the updated checksum words written in place.  They do
not mutate the caller's buffer.
"""
from __future__ import annotations

import binascii
import struct
from typing import Dict, List, Tuple

from .flash_exceptions import ChecksumMismatchError

Region = Tuple[int, int]  # (start, end_exclusive)


# ----------------------------------------------------------------------
# ECU-specific checksum region tables.  Addresses are file offsets, not
# absolute flash addresses -- callers are expected to pass calibration
# images already aligned to offset 0.
# ----------------------------------------------------------------------

BOSCH_MULTIPOINT_MAP: Dict[str, List[Tuple[Region, int]]] = {
    # (region_to_sum, checksum_storage_offset)
    "EDC17C54": [
        ((0x020000, 0x03FFFF), 0x03FFFC),
        ((0x040000, 0x05FFFF), 0x05FFFC),
        ((0x060000, 0x07FFFF), 0x07FFFC),
    ],
    "EDC17C46": [
        ((0x020000, 0x03FFFF), 0x03FFFC),
        ((0x040000, 0x07FFFF), 0x07FFFC),
    ],
    "MED17.8.2": [
        ((0x020000, 0x03FFFF), 0x03FFFC),
        ((0x040000, 0x07FFFF), 0x07FFFC),
    ],
    "MED17.5": [
        ((0x020000, 0x07FFFF), 0x07FFFC),
    ],
    "EDC16C39": [
        ((0x014000, 0x03FFFF), 0x03FFFC),
    ],
    "ME7": [
        ((0x010000, 0x01FFFF), 0x01FFFC),
    ],
}

DELPHI_MULTIPOINT_MAP: Dict[str, List[Tuple[Region, int]]] = {
    "DCM3.5": [((0x020000, 0x0FFFFF), 0x0FFFFC)],
    "DCM3.7": [((0x020000, 0x0FFFFF), 0x0FFFFC)],
    "DCM6.2": [
        ((0x020000, 0x0FFFFF), 0x0FFFFC),
        ((0x100000, 0x1FFFFF), 0x1FFFFC),
    ],
    "DCM7.1": [
        ((0x020000, 0x0FFFFF), 0x0FFFFC),
    ],
}

SIEMENS_KSU_MAP: Dict[str, List[Tuple[Region, int, int]]] = {
    # (region, sum_storage, inverse_storage)
    "SID208": [((0x004000, 0x07FFFF), 0x07FFF8, 0x07FFFC)],
    "SID807": [((0x004000, 0x0FFFFF), 0x0FFFF8, 0x0FFFFC)],
    "SIMOS18": [((0x020000, 0x3FFFFF), 0x3FFFF8, 0x3FFFFC)],
    "EMS3132": [((0x004000, 0x0FFFFF), 0x0FFFF8, 0x0FFFFC)],
}


class ChecksumFixer:
    """Comprehensive checksum repair dispatcher."""

    # ---- Primitive checksum/CRC routines ---------------------------

    @staticmethod
    def _sum16(data: bytes) -> int:
        total = 0
        # Process 16-bit words big-endian; pad odd trailing byte with 0x00.
        for i in range(0, len(data) - 1, 2):
            total = (total + ((data[i] << 8) | data[i + 1])) & 0xFFFF
        if len(data) & 1:
            total = (total + (data[-1] << 8)) & 0xFFFF
        return total

    @staticmethod
    def _sum32(data: bytes) -> int:
        total = 0
        for i in range(0, len(data) - 3, 4):
            total = (total + struct.unpack_from(">I", data, i)[0]) & 0xFFFFFFFF
        return total

    @staticmethod
    def _crc16_modbus(data: bytes) -> int:
        crc = 0xFFFF
        for b in data:
            crc ^= b
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF

    @staticmethod
    def _crc32(data: bytes) -> int:
        return binascii.crc32(data) & 0xFFFFFFFF

    # ---- Public fix_* helpers --------------------------------------

    @classmethod
    def fix_sum16_checksum(
        cls, data: bytes, region: Region, checksum_addr: int
    ) -> bytes:
        start, end = region
        if not (0 <= start < end <= len(data)):
            raise ChecksumMismatchError(
                f"sum16 region out of bounds: 0x{start:X}-0x{end:X} (file={len(data)})"
            )
        if checksum_addr + 2 > len(data):
            raise ChecksumMismatchError(
                f"sum16 storage 0x{checksum_addr:X} out of bounds"
            )
        buf = bytearray(data)
        # Zero the stored field before summing so recomputation is stable.
        buf[checksum_addr : checksum_addr + 2] = b"\x00\x00"
        s = cls._sum16(bytes(buf[start:end]))
        struct.pack_into(">H", buf, checksum_addr, s)
        return bytes(buf)

    @classmethod
    def fix_sum32_checksum(
        cls, data: bytes, region: Region, checksum_addr: int
    ) -> bytes:
        start, end = region
        if not (0 <= start < end <= len(data)) or checksum_addr + 4 > len(data):
            raise ChecksumMismatchError("sum32 region/storage out of bounds")
        buf = bytearray(data)
        buf[checksum_addr : checksum_addr + 4] = b"\x00\x00\x00\x00"
        s = cls._sum32(bytes(buf[start:end]))
        struct.pack_into(">I", buf, checksum_addr, s)
        return bytes(buf)

    @classmethod
    def fix_crc16_modbus(
        cls, data: bytes, region: Region, crc_addr: int
    ) -> bytes:
        start, end = region
        if not (0 <= start < end <= len(data)) or crc_addr + 2 > len(data):
            raise ChecksumMismatchError("crc16 region/storage out of bounds")
        buf = bytearray(data)
        buf[crc_addr : crc_addr + 2] = b"\x00\x00"
        crc = cls._crc16_modbus(bytes(buf[start:end]))
        struct.pack_into("<H", buf, crc_addr, crc)
        return bytes(buf)

    @classmethod
    def fix_crc32(cls, data: bytes, region: Region, crc_addr: int) -> bytes:
        start, end = region
        if not (0 <= start < end <= len(data)) or crc_addr + 4 > len(data):
            raise ChecksumMismatchError("crc32 region/storage out of bounds")
        buf = bytearray(data)
        buf[crc_addr : crc_addr + 4] = b"\x00\x00\x00\x00"
        crc = cls._crc32(bytes(buf[start:end]))
        struct.pack_into(">I", buf, crc_addr, crc)
        return bytes(buf)

    # ---- Manufacturer-family helpers -------------------------------

    @classmethod
    def fix_bosch_multipoint(cls, data: bytes, ecu_type: str) -> bytes:
        entries = BOSCH_MULTIPOINT_MAP.get(ecu_type.upper())
        if not entries:
            raise ChecksumMismatchError(
                f"No Bosch multipoint map for {ecu_type}"
            )
        out = data
        for region, addr in entries:
            if region[1] + 1 > len(out):
                # Trim region to file length if the map is a superset.
                region = (region[0], min(region[1] + 1, len(out)))
            else:
                region = (region[0], region[1] + 1)
            out = cls.fix_sum32_checksum(out, region, addr)
        return out

    @classmethod
    def fix_delphi_multipoint(cls, data: bytes, ecu_type: str) -> bytes:
        entries = DELPHI_MULTIPOINT_MAP.get(ecu_type.upper())
        if not entries:
            raise ChecksumMismatchError(
                f"No Delphi multipoint map for {ecu_type}"
            )
        out = data
        for region, addr in entries:
            region = (region[0], min(region[1] + 1, len(out)))
            out = cls.fix_sum16_checksum(out, region, addr)
            out = cls.fix_sum32_checksum(out, region, addr + 4 if addr + 8 <= len(out) else addr)
        return out

    @classmethod
    def fix_siemens_ksu(cls, data: bytes, ecu_type: str) -> bytes:
        entries = SIEMENS_KSU_MAP.get(ecu_type.upper())
        if not entries:
            raise ChecksumMismatchError(
                f"No Siemens KSU map for {ecu_type}"
            )
        out = data
        for region, sum_addr, inv_addr in entries:
            region = (region[0], min(region[1] + 1, len(out)))
            s = cls._sum32(bytes(out[region[0] : region[1]]))
            buf = bytearray(out)
            struct.pack_into(">I", buf, sum_addr, s)
            struct.pack_into(">I", buf, inv_addr, (~s) & 0xFFFFFFFF)
            out = bytes(buf)
        return out

    @classmethod
    def fix_tricore_bank_checksum(cls, data: bytes, bank: int) -> bytes:
        """Infineon Tricore per-bank CRC32 (EDC17/MED17/SIMOS18)."""
        bank_size = 0x40000  # 256 KB banks
        start = bank * bank_size
        end = start + bank_size
        if end > len(data):
            raise ChecksumMismatchError(
                f"Tricore bank {bank} outside file (0x{end:X} > 0x{len(data):X})"
            )
        # CRC is traditionally stored in the last 4 bytes of the bank.
        crc_addr = end - 4
        return cls.fix_crc32(data, (start, crc_addr), crc_addr)

    # ---- Master dispatcher -----------------------------------------

    @classmethod
    def detect_and_fix_all(
        cls, data: bytes, ecu_type: str
    ) -> Tuple[bytes, List[str]]:
        """
        Apply every known checksum repair for ``ecu_type`` and return
        ``(patched_image, list_of_repair_descriptions)``.
        """
        applied: List[str] = []
        key = ecu_type.upper()
        out = data

        try:
            if key in BOSCH_MULTIPOINT_MAP:
                out = cls.fix_bosch_multipoint(out, key)
                applied.append(f"Bosch multipoint ({key})")
            if key in DELPHI_MULTIPOINT_MAP:
                out = cls.fix_delphi_multipoint(out, key)
                applied.append(f"Delphi multipoint ({key})")
            if key in SIEMENS_KSU_MAP:
                out = cls.fix_siemens_ksu(out, key)
                applied.append(f"Siemens KSU ({key})")
        except ChecksumMismatchError as exc:
            applied.append(f"WARN: {exc.message}")

        # Tricore bank CRCs are attempted for any Tricore-family ECU.
        if any(tag in key for tag in ("EDC17", "MED17", "SIMOS18", "MG1", "MD1")):
            banks = max(1, len(out) // 0x40000)
            for b in range(banks):
                try:
                    out = cls.fix_tricore_bank_checksum(out, b)
                    applied.append(f"Tricore bank {b} CRC32")
                except ChecksumMismatchError:
                    break

        return out, applied
