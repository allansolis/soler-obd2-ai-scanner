"""
Siemens/Continental ECU flasher.

Covers SID series (Ford/PSA diesel), SIMOS gasoline family (3/7/8/9/10,
PCR2.1, 18), and EMS3120/3132/3134 engine management systems.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

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


SIEMENS_REGIONS: Dict[str, Region] = {
    "SID201":   (0x000000, 0x080000),
    "SID208":   (0x000000, 0x080000),
    "SID803":   (0x000000, 0x100000),
    "SID807":   (0x000000, 0x100000),
    "SIMOS3":   (0x000000, 0x040000),
    "SIMOS7":   (0x000000, 0x080000),
    "SIMOS8":   (0x000000, 0x100000),
    "SIMOS9":   (0x000000, 0x100000),
    "SIMOS10":  (0x000000, 0x200000),
    "SIMOS18":  (0x800000, 0xC00000),
    "PCR2.1":   (0x800000, 0xA00000),
    "EMS3120":  (0x000000, 0x080000),
    "EMS3132":  (0x000000, 0x100000),
    "EMS3134":  (0x000000, 0x100000),
}


class SiemensFlasher(BaseECUFlasher):
    """Flasher for Siemens/Continental ECUs."""

    def __init__(
        self, connection, variant: str = "SIMOS18", *, logger_=None
    ) -> None:
        super().__init__(connection, logger_=logger_)
        variant = variant.upper()
        if variant not in SIEMENS_REGIONS:
            raise UnsupportedECUError(f"Siemens variant {variant} not supported")
        self.ECU_TYPE = variant
        self.variant = variant
        self.BLOCK_SIZE = 0xFF2  # SIMOS typical TransferData payload
        self._security_level = 0x11 if variant == "SIMOS18" else 0x01

    def _default_calibration_region(self) -> Region:
        return SIEMENS_REGIONS[self.variant]

    # ---- preparation --------------------------------------------

    def prepare_flash(
        self, ecu_data: bytes, calibration_region: Region
    ) -> FlashPackage:
        start, end = calibration_region
        if end > len(ecu_data):
            raise ChecksumMismatchError(
                f"region 0x{end:X} beyond image 0x{len(ecu_data):X}"
            )
        patched, fixes = ChecksumFixer.detect_and_fix_all(
            ecu_data, self.variant
        )
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
            checksum_fixes_applied=fixes,
        )

    # ---- mode management ---------------------------------------

    def enter_programming_mode(self) -> bool:
        resp = self._uds_request(bytes([0x10, 0x02]), timeout=3.0)
        if not resp or resp[0] != 0x50:
            raise ProgrammingModeError("Siemens programming session refused")

        seed_resp = self._uds_request(
            bytes([0x27, self._security_level]), timeout=3.0
        )
        if not seed_resp or seed_resp[0] != 0x67:
            raise SeedKeyFailedError("Siemens seed request failed")
        seed = seed_resp[2:]
        if all(b == 0 for b in seed):
            return True

        algo = SeedKeyAlgorithms.get_algorithm(
            self.variant, self._security_level
        )
        if algo is None:
            raise SeedKeyFailedError(
                f"No seed-key algorithm for {self.variant} L{self._security_level:#x}"
            )
        key = algo(seed)
        key_resp = self._uds_request(
            bytes([0x27, self._security_level + 1]) + key, timeout=3.0
        )
        if not key_resp or key_resp[0] != 0x67:
            raise SeedKeyFailedError("Siemens key rejected")
        self._last_tester_present = time.monotonic()
        return True

    def exit_programming_mode(self) -> bool:
        resp = self._uds_request(bytes([0x11, 0x01]), timeout=3.0)
        return bool(resp and resp[0] == 0x51)

    # ---- erase/write --------------------------------------------

    def erase_flash_region(self, start_addr: int, length: int) -> bool:
        # SIMOS18 uses routine identifier 0xFF00 with 4-byte addr and 4-byte len.
        req = (
            bytes([0x31, 0x01, 0xFF, 0x00])
            + start_addr.to_bytes(4, "big")
            + length.to_bytes(4, "big")
        )
        resp = self._uds_request(req, timeout=90.0)
        if not resp or resp[0] != 0x71:
            raise EraseFailedError(
                f"Siemens erase NRC at 0x{start_addr:08X}",
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
                f"Siemens RequestDownload NRC at 0x{address:08X}",
                address=address,
            )
        counter = 1
        sent = 0
        while sent < len(data):
            chunk = data[sent : sent + self.BLOCK_SIZE]
            td = self._uds_request(
                bytes([0x36, counter & 0xFF]) + chunk, timeout=10.0
            )
            if not td or td[0] != 0x76:
                raise WriteFailedError(
                    f"Siemens TransferData NRC at 0x{address + sent:08X}",
                    address=address + sent,
                )
            counter = (counter + 1) & 0xFF
            sent += len(chunk)
        end = self._uds_request(bytes([0x37]), timeout=5.0)
        if not end or end[0] != 0x77:
            raise WriteFailedError(
                f"Siemens TransferExit NRC at 0x{address:08X}",
                address=address,
            )
        return True

    # ---- checksums ----------------------------------------------

    def calculate_checksum(self, data: bytes) -> bytes:
        fixed, _ = ChecksumFixer.detect_and_fix_all(data, self.variant)
        return fixed[-16:] if len(fixed) >= 16 else b""

    def fix_checksum(self, ecu_data: bytes) -> bytes:
        patched, _ = ChecksumFixer.detect_and_fix_all(ecu_data, self.variant)
        return patched
