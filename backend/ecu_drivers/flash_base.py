"""
Abstract base class and data structures for ECU flash drivers.

All concrete flashers (Bosch, Delphi, Siemens, Denso, Magneti Marelli)
inherit from ``BaseECUFlasher`` and implement the manufacturer-specific
protocol steps.  The base class provides the full orchestration loop for
``flash_full_calibration`` and safe, verified block writes.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional, Tuple

from .flash_exceptions import (
    ChecksumMismatchError,
    EraseFailedError,
    FlashInterruptedError,
    FlashVerificationError,
    ProgrammingModeError,
    SeedKeyFailedError,
    TesterPresentLostError,
    VoltageLowError,
    WriteFailedError,
)

logger = logging.getLogger(__name__)


# Region = (start_address, end_address_exclusive)
Region = Tuple[int, int]

# Callback signature: progress_callback(percent: float, message: str) -> None
ProgressCallback = Callable[[float, str], None]


class FlashPhase(str, Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    ENTERING = "entering_programming_mode"
    ERASING = "erasing"
    WRITING = "writing"
    VERIFYING = "verifying"
    EXITING = "exiting_programming_mode"
    COMPLETE = "complete"
    FAILED = "failed"
    RECOVERING = "recovering"


@dataclass
class FlashBlock:
    """A contiguous block of data to be written."""

    address: int
    data: bytes

    @property
    def length(self) -> int:
        return len(self.data)

    @property
    def end(self) -> int:
        return self.address + len(self.data)


@dataclass
class FlashPackage:
    """A prepared, checksum-corrected image ready to flash."""

    ecu_type: str
    calibration_region: Region
    blocks: List[FlashBlock]
    full_image: bytes
    checksum_fixes_applied: List[str] = field(default_factory=list)
    expected_total_bytes: int = 0

    def __post_init__(self) -> None:
        if not self.expected_total_bytes:
            self.expected_total_bytes = sum(b.length for b in self.blocks)


@dataclass
class FlashResult:
    """Outcome of a flash operation."""

    success: bool
    ecu_type: str
    bytes_written: int
    duration_seconds: float
    phase_reached: FlashPhase
    error_message: Optional[str] = None
    error_spanish: Optional[str] = None
    verification_passed: bool = False
    recovered_from_failure: bool = False


class BaseECUFlasher(ABC):
    """
    Abstract base for all ECU flash drivers.

    Concrete subclasses implement the manufacturer-specific protocol; the
    base class glues them together with safety checks, progress reporting
    and verified block writing.
    """

    #: ECU family identifier, e.g. "EDC17C54".
    ECU_TYPE: str = "GENERIC"

    #: Default block size for write_flash_block in bytes.
    BLOCK_SIZE: int = 0x100

    #: Minimum battery voltage required to keep flashing (volts).
    MIN_VOLTAGE: float = 12.5

    #: Seconds between tester-present heartbeats while in programming mode.
    TESTER_PRESENT_INTERVAL: float = 2.0

    #: Maximum retries for a single block write before aborting.
    MAX_BLOCK_RETRIES: int = 3

    def __init__(self, connection, *, logger_: Optional[logging.Logger] = None) -> None:
        """
        :param connection: a transport object exposing ``send(bytes)``,
            ``recv(timeout)`` (returns bytes), ``read_voltage()`` (float),
            and optionally ``read_temperature()`` (float).
        """
        self.connection = connection
        self.log = logger_ or logger
        self.phase: FlashPhase = FlashPhase.IDLE
        self._last_tester_present: float = 0.0

    # ------------------------------------------------------------------
    # Abstract operations -- implemented by concrete flashers.
    # ------------------------------------------------------------------

    @abstractmethod
    def prepare_flash(
        self, ecu_data: bytes, calibration_region: Region
    ) -> FlashPackage:
        """Prepare a FlashPackage from a modified image (fix checksums, slice)."""

    @abstractmethod
    def enter_programming_mode(self) -> bool:
        """Put the ECU into the programming session (UDS 0x10 02 + seed/key)."""

    @abstractmethod
    def erase_flash_region(self, start_addr: int, length: int) -> bool:
        """Erase ``length`` bytes of flash starting at ``start_addr``."""

    @abstractmethod
    def write_flash_block(self, address: int, data: bytes) -> bool:
        """Write a single block.  Must not perform read-back verification."""

    @abstractmethod
    def exit_programming_mode(self) -> bool:
        """Cleanly exit programming mode (UDS 0x11 01 or 0x10 01)."""

    @abstractmethod
    def calculate_checksum(self, data: bytes) -> bytes:
        """Calculate the ECU-specific checksum for a full image."""

    @abstractmethod
    def fix_checksum(self, ecu_data: bytes) -> bytes:
        """Return ``ecu_data`` with all relevant checksums patched."""

    # ------------------------------------------------------------------
    # Verified block write + orchestration -- shared by all flashers.
    # ------------------------------------------------------------------

    def verify_written_data(
        self, address: int, length: int, expected: bytes
    ) -> bool:
        """
        Read ``length`` bytes back from ``address`` and compare to
        ``expected``.  Default implementation uses UDS 0x23 ReadMemoryByAddress.
        Sub-classes may override for faster protocols.
        """
        try:
            read_back = self._read_memory(address, length)
        except Exception as exc:  # pragma: no cover - depends on transport
            self.log.error("verify read failed at 0x%08X: %s", address, exc)
            return False
        if read_back == expected:
            return True
        # Log up to 16 bytes of diff for forensic purposes.
        diff_at = next(
            (i for i, (a, b) in enumerate(zip(read_back, expected)) if a != b),
            min(len(read_back), len(expected)),
        )
        self.log.error(
            "verify mismatch at 0x%08X+0x%X: got %s expected %s",
            address,
            diff_at,
            read_back[diff_at : diff_at + 16].hex(),
            expected[diff_at : diff_at + 16].hex(),
        )
        return False

    def _read_memory(self, address: int, length: int) -> bytes:
        """
        Default UDS 0x23 ReadMemoryByAddress with a 4-byte address
        and 2-byte length descriptor.  Sub-classes may override.
        """
        alfid = 0x24  # addr=4 bytes, size=2 bytes
        req = bytes([0x23, alfid]) + address.to_bytes(4, "big") + length.to_bytes(2, "big")
        resp = self._uds_request(req, timeout=5.0)
        if not resp or resp[0] != 0x63:
            raise WriteFailedError(
                f"ReadMemoryByAddress negative response at 0x{address:08X}",
                address=address,
            )
        return resp[1:]

    # ------------------------------------------------------------------
    # Safety/health helpers.
    # ------------------------------------------------------------------

    def _check_voltage(self) -> float:
        try:
            v = float(self.connection.read_voltage())
        except Exception as exc:
            raise VoltageLowError(
                f"Unable to read battery voltage: {exc}"
            ) from exc
        if v < self.MIN_VOLTAGE:
            raise VoltageLowError(
                f"Battery voltage {v:.2f}V below minimum {self.MIN_VOLTAGE:.2f}V"
            )
        return v

    def _send_tester_present(self) -> None:
        """Send UDS 0x3E 0x80 (suppressed positive response) if due."""
        now = time.monotonic()
        if now - self._last_tester_present < self.TESTER_PRESENT_INTERVAL:
            return
        try:
            self.connection.send(bytes([0x3E, 0x80]))
        except Exception as exc:
            raise TesterPresentLostError(
                f"Failed to send tester present: {exc}"
            ) from exc
        self._last_tester_present = now

    def _uds_request(
        self, request: bytes, timeout: float = 2.0
    ) -> Optional[bytes]:
        """Send a UDS request and return the positive response payload."""
        self.connection.send(request)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            resp = self.connection.recv(timeout=deadline - time.monotonic())
            if not resp:
                continue
            if resp[0] == 0x7F and len(resp) >= 3:
                # 0x78 = response pending, keep waiting.
                if resp[2] == 0x78:
                    continue
                self.log.warning(
                    "UDS NRC: SID=0x%02X NRC=0x%02X", resp[1], resp[2]
                )
                return resp
            return resp
        return None

    # ------------------------------------------------------------------
    # Top-level orchestration.
    # ------------------------------------------------------------------

    def flash_full_calibration(
        self,
        data: bytes,
        progress_callback: Optional[ProgressCallback] = None,
        calibration_region: Optional[Region] = None,
    ) -> FlashResult:
        """
        Execute the full flash workflow with per-block verification.

        Raises exceptions on unrecoverable errors; callers should catch
        them and invoke ``FlashOrchestrator.emergency_recovery``.
        """
        start = time.monotonic()
        total_written = 0
        package: Optional[FlashPackage] = None

        def emit(pct: float, msg: str) -> None:
            self.log.info("[%5.1f%%] %s", pct, msg)
            if progress_callback:
                try:
                    progress_callback(pct, msg)
                except Exception:  # pragma: no cover - user callback
                    self.log.exception("progress_callback raised")

        try:
            self.phase = FlashPhase.PREPARING
            emit(0.0, "Preparing image and fixing checksums")
            self._check_voltage()
            region = calibration_region or self._default_calibration_region()
            package = self.prepare_flash(data, region)
            emit(
                3.0,
                f"Prepared {package.expected_total_bytes} bytes "
                f"(fixes: {', '.join(package.checksum_fixes_applied) or 'none'})",
            )

            self.phase = FlashPhase.ENTERING
            emit(5.0, "Entering programming mode")
            if not self.enter_programming_mode():
                raise ProgrammingModeError("ECU refused programming session")

            self.phase = FlashPhase.ERASING
            emit(10.0, "Erasing flash region")
            reg_start, reg_end = package.calibration_region
            if not self.erase_flash_region(reg_start, reg_end - reg_start):
                raise EraseFailedError(
                    f"Erase failed at 0x{reg_start:08X}", address=reg_start
                )

            self.phase = FlashPhase.WRITING
            total_bytes = package.expected_total_bytes or 1
            for idx, block in enumerate(package.blocks):
                self._check_voltage()
                self._send_tester_present()
                self._write_block_verified(block)
                total_written += block.length
                pct = 15.0 + 75.0 * (total_written / total_bytes)
                emit(
                    pct,
                    f"Wrote block {idx+1}/{len(package.blocks)} at "
                    f"0x{block.address:08X} ({block.length} B)",
                )

            self.phase = FlashPhase.VERIFYING
            emit(92.0, "Final verification")
            verified = self._final_verification(package)
            if not verified:
                raise FlashVerificationError(
                    "Final image verification failed after successful writes"
                )

            self.phase = FlashPhase.EXITING
            emit(97.0, "Exiting programming mode")
            self.exit_programming_mode()

            self.phase = FlashPhase.COMPLETE
            emit(100.0, "Flash complete")

            return FlashResult(
                success=True,
                ecu_type=self.ECU_TYPE,
                bytes_written=total_written,
                duration_seconds=time.monotonic() - start,
                phase_reached=FlashPhase.COMPLETE,
                verification_passed=True,
            )

        except (SeedKeyFailedError, ProgrammingModeError) as exc:
            self.phase = FlashPhase.FAILED
            return FlashResult(
                success=False,
                ecu_type=self.ECU_TYPE,
                bytes_written=total_written,
                duration_seconds=time.monotonic() - start,
                phase_reached=self.phase,
                error_message=str(exc),
                error_spanish=getattr(exc, "spanish_message", None),
            )
        except (
            EraseFailedError,
            WriteFailedError,
            FlashVerificationError,
            TesterPresentLostError,
            VoltageLowError,
            ChecksumMismatchError,
            FlashInterruptedError,
        ) as exc:
            self.phase = FlashPhase.FAILED
            self.log.exception("Flash failed during %s", self.phase)
            return FlashResult(
                success=False,
                ecu_type=self.ECU_TYPE,
                bytes_written=total_written,
                duration_seconds=time.monotonic() - start,
                phase_reached=self.phase,
                error_message=str(exc),
                error_spanish=getattr(exc, "spanish_message", None),
            )

    # ------------------------------------------------------------------
    # Per-block verified write.
    # ------------------------------------------------------------------

    def _write_block_verified(self, block: FlashBlock) -> None:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.MAX_BLOCK_RETRIES + 1):
            try:
                if not self.write_flash_block(block.address, block.data):
                    raise WriteFailedError(
                        f"write_flash_block returned False at "
                        f"0x{block.address:08X}",
                        address=block.address,
                    )
                if not self.verify_written_data(
                    block.address, block.length, block.data
                ):
                    raise FlashVerificationError(
                        f"Block verify failed at 0x{block.address:08X}",
                        address=block.address,
                    )
                return
            except (WriteFailedError, FlashVerificationError) as exc:
                last_error = exc
                self.log.warning(
                    "Block 0x%08X attempt %d/%d failed: %s",
                    block.address,
                    attempt,
                    self.MAX_BLOCK_RETRIES,
                    exc,
                )
                # Small backoff; re-enter programming mode as a last resort.
                time.sleep(0.2 * attempt)
                if attempt == self.MAX_BLOCK_RETRIES - 1:
                    # Refresh tester present + programming mode before last retry.
                    try:
                        self._send_tester_present()
                    except TesterPresentLostError:
                        self.enter_programming_mode()
        assert last_error is not None
        raise last_error

    # ------------------------------------------------------------------
    # Hooks for sub-classes.
    # ------------------------------------------------------------------

    def _default_calibration_region(self) -> Region:
        """Sub-classes override to return their default region."""
        raise NotImplementedError(
            f"{self.ECU_TYPE} flasher has no default region"
        )

    def _final_verification(self, package: FlashPackage) -> bool:
        """Verify the full calibration region matches ``package``."""
        start, end = package.calibration_region
        length = end - start
        expected = package.full_image[start : start + length] if len(
            package.full_image
        ) >= end else bytes().join(b.data for b in package.blocks)
        try:
            actual = self._read_memory(start, length)
        except Exception as exc:
            self.log.error("final verify read failed: %s", exc)
            return False
        return actual == expected
