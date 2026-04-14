"""
Bosch ECU flasher.

Covers Bosch diesel (EDC15/16/17) and gasoline (ME7/9, MED9/17, MEV17,
MEVD17) plus the newer MG1/MD1/MDG1 Tricore AURIX generations.
"""
from __future__ import annotations

import struct
import time
from typing import Dict, List, Optional, Tuple

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


# Default calibration regions per Bosch ECU variant.
BOSCH_REGIONS: Dict[str, Region] = {
    "EDC15":        (0x000000, 0x040000),
    "EDC16C39":     (0x000000, 0x040000),
    "EDC17":        (0x800000, 0x840000),
    "EDC17C54":     (0x800000, 0x840000),
    "EDC17CP14":    (0x800000, 0x840000),
    "EDC17C46":     (0x800000, 0x820000),
    "MED9":         (0x020000, 0x080000),
    "MED17":        (0x800000, 0x880000),
    "MED17.8.2":    (0x800000, 0x880000),
    "MED17.5":      (0x800000, 0x880000),
    "ME7":          (0x010000, 0x020000),
    "ME9":          (0x020000, 0x040000),
    "MEV17":        (0x800000, 0x880000),
    "MEVD17":       (0x800000, 0x880000),
    "MG1":          (0x80000000, 0x80400000),
    "MD1":          (0x80000000, 0x80400000),
    "MDG1":         (0x80000000, 0x80400000),
}

# Tricore-family variants use 2-byte length framing; older 16-bit MCUs use 1-byte.
TRICORE_VARIANTS = {
    "EDC17", "EDC17C54", "EDC17CP14", "EDC17C46",
    "MED17", "MED17.8.2", "MED17.5",
    "MEV17", "MEVD17",
    "MG1", "MD1", "MDG1",
}


class BoschFlasher(BaseECUFlasher):
    """Flasher for the Bosch ECU family."""

    def __init__(
        self,
        connection,
        variant: str = "EDC17",
        *,
        logger_=None,
        block_size: Optional[int] = None,
    ) -> None:
        super().__init__(connection, logger_=logger_)
        variant = variant.upper()
        if variant not in BOSCH_REGIONS:
            raise UnsupportedECUError(f"Bosch variant {variant} not supported")
        self.ECU_TYPE = variant
        self.variant = variant
        self.BLOCK_SIZE = block_size or (0x100 if variant in TRICORE_VARIANTS else 0x80)
        self._security_level = 0x01

    # ---- region helpers -----------------------------------------

    def _default_calibration_region(self) -> Region:
        return BOSCH_REGIONS[self.variant]

    # ---- image preparation --------------------------------------

    def prepare_flash(
        self, ecu_data: bytes, calibration_region: Region
    ) -> FlashPackage:
        start, end = calibration_region
        if end > len(ecu_data):
            raise ChecksumMismatchError(
                f"Calibration region 0x{end:X} beyond image size 0x{len(ecu_data):X}"
            )
        patched = self.fix_checksum(ecu_data)
        fixes: List[str]
        patched, fixes = ChecksumFixer.detect_and_fix_all(patched, self.variant)

        cal = patched[start:end]
        blocks: List[FlashBlock] = []
        for off in range(0, len(cal), self.BLOCK_SIZE):
            chunk = cal[off : off + self.BLOCK_SIZE]
            blocks.append(FlashBlock(address=start + off, data=chunk))

        return FlashPackage(
            ecu_type=self.variant,
            calibration_region=calibration_region,
            blocks=blocks,
            full_image=patched,
            checksum_fixes_applied=fixes,
        )

    # ---- programming mode ---------------------------------------

    def enter_programming_mode(self) -> bool:
        # 1. DiagnosticSessionControl -> Programming (0x10 0x02)
        resp = self._uds_request(bytes([0x10, 0x02]), timeout=3.0)
        if not resp or resp[0] != 0x50:
            raise ProgrammingModeError(
                f"DiagnosticSessionControl NRC: {resp.hex() if resp else 'timeout'}"
            )

        # 2. SecurityAccess seed request (0x27 0x01)
        seed_resp = self._uds_request(bytes([0x27, self._security_level]), timeout=3.0)
        if not seed_resp or seed_resp[0] != 0x67:
            raise SeedKeyFailedError(
                f"SecurityAccess seed NRC: {seed_resp.hex() if seed_resp else 'timeout'}"
            )
        seed = seed_resp[2:]
        if all(b == 0 for b in seed):
            # Zero seed = already unlocked.
            self._last_tester_present = time.monotonic()
            return True

        algo = SeedKeyAlgorithms.get_algorithm(self.variant, self._security_level)
        if algo is None:
            raise SeedKeyFailedError(
                f"No seed-key algorithm registered for {self.variant}"
            )
        key = algo(seed)

        # 3. SecurityAccess send-key (0x27 0x02)
        key_resp = self._uds_request(
            bytes([0x27, self._security_level + 1]) + key, timeout=3.0
        )
        if not key_resp or key_resp[0] != 0x67:
            raise SeedKeyFailedError(
                f"SecurityAccess key NRC: {key_resp.hex() if key_resp else 'timeout'}"
            )
        self._last_tester_present = time.monotonic()
        return True

    def exit_programming_mode(self) -> bool:
        # ECUReset (0x11 0x01)
        resp = self._uds_request(bytes([0x11, 0x01]), timeout=3.0)
        return bool(resp and resp[0] == 0x51)

    # ---- erase --------------------------------------------------

    def erase_flash_region(self, start_addr: int, length: int) -> bool:
        # RoutineControl (0x31 0x01 0xFF00) - EraseMemory routine on Bosch UDS.
        addr_bytes = start_addr.to_bytes(4, "big")
        len_bytes = length.to_bytes(4, "big")
        req = bytes([0x31, 0x01, 0xFF, 0x00]) + addr_bytes + len_bytes
        resp = self._uds_request(req, timeout=60.0)
        if not resp or resp[0] != 0x71:
            raise EraseFailedError(
                f"Erase routine NRC: {resp.hex() if resp else 'timeout'}",
                address=start_addr,
            )
        return True

    # ---- write --------------------------------------------------

    def write_flash_block(self, address: int, data: bytes) -> bool:
        # 1. RequestDownload (0x34) dataFormatIdentifier=0x00 addrLen=4 sizeLen=4
        req = (
            bytes([0x34, 0x00, 0x44])
            + address.to_bytes(4, "big")
            + len(data).to_bytes(4, "big")
        )
        resp = self._uds_request(req, timeout=5.0)
        if not resp or resp[0] != 0x74:
            raise WriteFailedError(
                f"RequestDownload NRC at 0x{address:08X}: "
                f"{resp.hex() if resp else 'timeout'}",
                address=address,
            )
        # resp[2:] encodes the max block length the ECU accepts; we rely on
        # caller sizing via self.BLOCK_SIZE and trust it.
        max_block = struct.unpack(">H", resp[2:4].ljust(2, b"\x00"))[0] or self.BLOCK_SIZE

        # 2. TransferData (0x36) with incrementing block counter.
        counter = 1
        sent = 0
        while sent < len(data):
            chunk = data[sent : sent + min(max_block - 2, self.BLOCK_SIZE)]
            td_req = bytes([0x36, counter & 0xFF]) + chunk
            td_resp = self._uds_request(td_req, timeout=5.0)
            if not td_resp or td_resp[0] != 0x76:
                raise WriteFailedError(
                    f"TransferData NRC at 0x{address + sent:08X}: "
                    f"{td_resp.hex() if td_resp else 'timeout'}",
                    address=address + sent,
                )
            counter = (counter + 1) & 0xFF
            sent += len(chunk)

        # 3. RequestTransferExit (0x37)
        exit_resp = self._uds_request(bytes([0x37]), timeout=5.0)
        if not exit_resp or exit_resp[0] != 0x77:
            raise WriteFailedError(
                f"RequestTransferExit NRC at 0x{address:08X}",
                address=address,
            )
        return True

    # ---- checksums ----------------------------------------------

    def calculate_checksum(self, data: bytes) -> bytes:
        """
        Returns the concatenated checksum bytes that would be stored in
        the multipoint table for ``self.variant``.  Intended for diagnostics.
        """
        fixed, _ = ChecksumFixer.detect_and_fix_all(data, self.variant)
        out = bytearray()
        from .checksum_fixers import BOSCH_MULTIPOINT_MAP

        for _region, addr in BOSCH_MULTIPOINT_MAP.get(self.variant, []):
            if addr + 4 <= len(fixed):
                out.extend(fixed[addr : addr + 4])
        return bytes(out)

    def fix_checksum(self, ecu_data: bytes) -> bytes:
        patched, _ = ChecksumFixer.detect_and_fix_all(ecu_data, self.variant)
        return patched

    # ---- variant-specific hooks ---------------------------------

    def flash_EDC17_TC1797(self, data: bytes, **kw) -> FlashPackage:
        """Convenience alias for EDC17 (Tricore TC1797)."""
        if not self.variant.startswith("EDC17"):
            raise UnsupportedECUError(
                f"flash_EDC17_TC1797 called on {self.variant}"
            )
        return self.prepare_flash(data, BOSCH_REGIONS["EDC17C54"])

    def flash_MED17_TC1767(self, data: bytes, **kw) -> FlashPackage:
        """Convenience alias for MED17 (Tricore TC1767)."""
        if not self.variant.startswith("MED17"):
            raise UnsupportedECUError(
                f"flash_MED17_TC1767 called on {self.variant}"
            )
        return self.prepare_flash(data, BOSCH_REGIONS["MED17.8.2"])

    def boot_upload(self) -> bytes:
        """
        Upload the recovery bootloader via the Bosch back-door for full
        flash read.  Placeholder: actual bootloader payload is proprietary
        and must be provided by the integrator.
        """
        raise UnsupportedECUError(
            "Boot-upload bootloader payload not bundled; "
            "supply via flasher.inject_bootloader(bytes)."
        )
