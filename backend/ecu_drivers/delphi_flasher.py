"""
Delphi (now BorgWarner) ECU flasher.

Covers DCM diesel (3.5, 3.7, 6.1, 6.2, 7.1), DCI, and the legacy
MT-series controllers (MT05, MT22, MT60, MT86).
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


DELPHI_REGIONS: Dict[str, Region] = {
    "DCM3.5": (0x000000, 0x100000),
    "DCM3.7": (0x000000, 0x100000),
    "DCM6.1": (0x000000, 0x100000),
    "DCM6.2": (0x000000, 0x200000),
    "DCM7.1": (0x000000, 0x200000),
    "DCI":    (0x000000, 0x080000),
    "MT05":   (0x000000, 0x020000),
    "MT22":   (0x000000, 0x040000),
    "MT60":   (0x000000, 0x080000),
    "MT86":   (0x000000, 0x100000),
}


class DelphiFlasher(BaseECUFlasher):
    """Flasher for Delphi/BorgWarner ECUs (MPC5xxx-based)."""

    def __init__(
        self, connection, variant: str = "DCM3.7", *, logger_=None
    ) -> None:
        super().__init__(connection, logger_=logger_)
        variant = variant.upper()
        if variant not in DELPHI_REGIONS:
            raise UnsupportedECUError(f"Delphi variant {variant} not supported")
        self.ECU_TYPE = variant
        self.variant = variant
        self.BLOCK_SIZE = 0x100

    def _default_calibration_region(self) -> Region:
        return DELPHI_REGIONS[self.variant]

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
        blocks: List[FlashBlock] = [
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

    # ---- programming mode ---------------------------------------

    def enter_programming_mode(self) -> bool:
        # Delphi extended diagnostic 0x10 0x03 first, then programming 0x10 0x02.
        ext = self._uds_request(bytes([0x10, 0x03]), timeout=3.0)
        if not ext or ext[0] != 0x50:
            raise ProgrammingModeError(
                "Delphi extended session refused"
            )
        prog = self._uds_request(bytes([0x10, 0x02]), timeout=3.0)
        if not prog or prog[0] != 0x50:
            raise ProgrammingModeError(
                "Delphi programming session refused"
            )

        seed_resp = self._uds_request(bytes([0x27, 0x01]), timeout=3.0)
        if not seed_resp or seed_resp[0] != 0x67:
            raise SeedKeyFailedError("Delphi seed request failed")
        seed = seed_resp[2:]
        if all(b == 0 for b in seed):
            self._last_tester_present = time.monotonic()
            return True

        algo = SeedKeyAlgorithms.get_algorithm(self.variant, 0x01)
        if algo is None:
            raise SeedKeyFailedError(
                f"No seed-key algorithm for {self.variant}"
            )
        key = algo(seed)
        key_resp = self._uds_request(bytes([0x27, 0x02]) + key, timeout=3.0)
        if not key_resp or key_resp[0] != 0x67:
            raise SeedKeyFailedError("Delphi key rejected")
        self._last_tester_present = time.monotonic()
        return True

    def exit_programming_mode(self) -> bool:
        resp = self._uds_request(bytes([0x11, 0x01]), timeout=3.0)
        return bool(resp and resp[0] == 0x51)

    # ---- erase/write --------------------------------------------

    def erase_flash_region(self, start_addr: int, length: int) -> bool:
        # Delphi EraseMemory routine id = 0xFF00 (KWP-like)
        req = (
            bytes([0x31, 0x01, 0xFF, 0x00])
            + start_addr.to_bytes(4, "big")
            + length.to_bytes(4, "big")
        )
        resp = self._uds_request(req, timeout=60.0)
        if not resp or resp[0] != 0x71:
            raise EraseFailedError(
                f"Delphi erase failed at 0x{start_addr:08X}",
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
                f"Delphi RequestDownload NRC at 0x{address:08X}",
                address=address,
            )
        counter = 1
        sent = 0
        chunk_size = self.BLOCK_SIZE
        while sent < len(data):
            chunk = data[sent : sent + chunk_size]
            td = self._uds_request(
                bytes([0x36, counter & 0xFF]) + chunk, timeout=5.0
            )
            if not td or td[0] != 0x76:
                raise WriteFailedError(
                    f"Delphi TransferData NRC at 0x{address + sent:08X}",
                    address=address + sent,
                )
            counter = (counter + 1) & 0xFF
            sent += len(chunk)
        end = self._uds_request(bytes([0x37]), timeout=5.0)
        if not end or end[0] != 0x77:
            raise WriteFailedError(
                f"Delphi TransferExit NRC at 0x{address:08X}",
                address=address,
            )
        return True

    # ---- checksums ----------------------------------------------

    def calculate_checksum(self, data: bytes) -> bytes:
        fixed, _ = ChecksumFixer.detect_and_fix_all(data, self.variant)
        return fixed[-8:] if len(fixed) >= 8 else b""

    def fix_checksum(self, ecu_data: bytes) -> bytes:
        patched, _ = ChecksumFixer.detect_and_fix_all(ecu_data, self.variant)
        return patched
