"""
Denso ECU flasher.

Covers Denso 275000/276000/279000 series and Toyota 89661 part numbers,
plus Honda PGM-FI and Mazda Skyactiv engine controllers built by Denso.
"""
from __future__ import annotations

import time
from typing import Dict, List

from .checksum_fixers import ChecksumFixer
from .flash_base import (
    BaseECUFlasher,
    FlashBlock,
    FlashPackage,
    Region,
)
from .flash_exceptions import (
    ChecksumMismatchError,
    EraseFailedError,
    ProgrammingModeError,
    SeedKeyFailedError,
    UnsupportedECUError,
    WriteFailedError,
)
from .seed_key_algorithms import SeedKeyAlgorithms


DENSO_REGIONS: Dict[str, Region] = {
    "DENSO_275000": (0x000000, 0x100000),
    "DENSO_276000": (0x000000, 0x100000),
    "DENSO_279000": (0x000000, 0x200000),
    "DENSO_89661":  (0x000000, 0x100000),
    "DENSO_TOYOTA": (0x000000, 0x100000),
    "DENSO_HONDA":  (0x000000, 0x080000),
    "DENSO_MAZDA":  (0x000000, 0x200000),
}


class DensoFlasher(BaseECUFlasher):
    """Flasher for Denso family ECUs (Toyota/Honda/Mazda)."""

    def __init__(
        self, connection, variant: str = "DENSO_TOYOTA", *, logger_=None
    ) -> None:
        super().__init__(connection, logger_=logger_)
        variant = variant.upper()
        if variant not in DENSO_REGIONS:
            raise UnsupportedECUError(f"Denso variant {variant} not supported")
        self.ECU_TYPE = variant
        self.variant = variant
        self.BLOCK_SIZE = 0x80

    def _default_calibration_region(self) -> Region:
        return DENSO_REGIONS[self.variant]

    def prepare_flash(
        self, ecu_data: bytes, calibration_region: Region
    ) -> FlashPackage:
        start, end = calibration_region
        if end > len(ecu_data):
            raise ChecksumMismatchError(
                f"region 0x{end:X} beyond image 0x{len(ecu_data):X}"
            )
        patched = self.fix_checksum(ecu_data)
        cal = patched[start:end]
        blocks = [
            FlashBlock(start + off, cal[off : off + self.BLOCK_SIZE])
            for off in range(0, len(cal), self.BLOCK_SIZE)
        ]
        return FlashPackage(
            ecu_type=self.variant,
            calibration_region=calibration_region,
            blocks=blocks,
            full_image=patched,
            checksum_fixes_applied=["Denso multipoint (approx.)"],
        )

    def enter_programming_mode(self) -> bool:
        # Toyota diagnostic sessions 0x81 (SMR) + 0x85 (programming) over KWP2000.
        # We emulate via UDS 0x10 0x02 first; Toyota UDS gateways accept it.
        resp = self._uds_request(bytes([0x10, 0x02]), timeout=3.0)
        if not resp or resp[0] != 0x50:
            raise ProgrammingModeError("Denso programming session refused")
        seed_resp = self._uds_request(bytes([0x27, 0x01]), timeout=3.0)
        if not seed_resp or seed_resp[0] != 0x67:
            raise SeedKeyFailedError("Denso seed request failed")
        seed = seed_resp[2:]
        if all(b == 0 for b in seed):
            return True
        algo_key = "DENSO_HONDA" if self.variant == "DENSO_HONDA" else "DENSO_TOYOTA"
        algo = SeedKeyAlgorithms.get_algorithm(algo_key, 0x01)
        if algo is None:
            raise SeedKeyFailedError(
                f"No seed-key algorithm for {algo_key}"
            )
        key = algo(seed)
        key_resp = self._uds_request(bytes([0x27, 0x02]) + key, timeout=3.0)
        if not key_resp or key_resp[0] != 0x67:
            raise SeedKeyFailedError("Denso key rejected")
        self._last_tester_present = time.monotonic()
        return True

    def exit_programming_mode(self) -> bool:
        resp = self._uds_request(bytes([0x11, 0x01]), timeout=3.0)
        return bool(resp and resp[0] == 0x51)

    def erase_flash_region(self, start_addr: int, length: int) -> bool:
        req = (
            bytes([0x31, 0x01, 0xFF, 0x00])
            + start_addr.to_bytes(4, "big")
            + length.to_bytes(4, "big")
        )
        resp = self._uds_request(req, timeout=60.0)
        if not resp or resp[0] != 0x71:
            raise EraseFailedError(
                f"Denso erase NRC at 0x{start_addr:08X}",
                address=start_addr,
            )
        return True

    def write_flash_block(self, address: int, data: bytes) -> bool:
        req = (
            bytes([0x34, 0x00, 0x44])
            + address.to_bytes(4, "big")
            + len(data).to_bytes(4, "big")
        )
        resp = self._uds_request(req, timeout=5.0)
        if not resp or resp[0] != 0x74:
            raise WriteFailedError(
                f"Denso RequestDownload NRC at 0x{address:08X}",
                address=address,
            )
        counter = 1
        sent = 0
        while sent < len(data):
            chunk = data[sent : sent + self.BLOCK_SIZE]
            td = self._uds_request(
                bytes([0x36, counter & 0xFF]) + chunk, timeout=5.0
            )
            if not td or td[0] != 0x76:
                raise WriteFailedError(
                    f"Denso TransferData NRC at 0x{address + sent:08X}",
                    address=address + sent,
                )
            counter = (counter + 1) & 0xFF
            sent += len(chunk)
        end = self._uds_request(bytes([0x37]), timeout=5.0)
        if not end or end[0] != 0x77:
            raise WriteFailedError(
                f"Denso TransferExit NRC at 0x{address:08X}",
                address=address,
            )
        return True

    def calculate_checksum(self, data: bytes) -> bytes:
        # Denso images typically store a 32-bit sum at the last 4 bytes.
        s = ChecksumFixer._sum32(data[:-4]) if len(data) > 4 else 0
        return s.to_bytes(4, "big")

    def fix_checksum(self, ecu_data: bytes) -> bytes:
        if len(ecu_data) < 4:
            return ecu_data
        buf = bytearray(ecu_data)
        buf[-4:] = b"\x00\x00\x00\x00"
        s = ChecksumFixer._sum32(bytes(buf[:-4]))
        buf[-4:] = s.to_bytes(4, "big")
        return bytes(buf)
