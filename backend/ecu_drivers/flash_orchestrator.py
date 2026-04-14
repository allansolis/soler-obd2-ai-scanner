"""
Top-level flash orchestrator.

Selects the correct manufacturer-specific flasher, runs safety checks,
and coordinates the read-back, write, verify, and recovery lifecycle.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from .bosch_flasher import BoschFlasher, BOSCH_REGIONS
from .delphi_flasher import DelphiFlasher, DELPHI_REGIONS
from .denso_flasher import DensoFlasher, DENSO_REGIONS
from .flash_base import (
    BaseECUFlasher,
    FlashPhase,
    FlashResult,
    ProgressCallback,
)
from .flash_exceptions import (
    FlashError,
    FlashInterruptedError,
    FlashVerificationError,
    PowerUnstableError,
    TemperatureOutOfRangeError,
    UnsupportedECUError,
    VoltageLowError,
)
from .magnetti_marelli_flasher import MagnettiMarelliFlasher, MM_REGIONS
from .siemens_flasher import SiemensFlasher, SIEMENS_REGIONS

logger = logging.getLogger(__name__)


# Callback signature for error notifications.
ErrorCallback = Callable[[FlashError], None]


_VARIANT_TO_FLASHER: List[Tuple[Dict, type]] = [
    (BOSCH_REGIONS, BoschFlasher),
    (DELPHI_REGIONS, DelphiFlasher),
    (SIEMENS_REGIONS, SiemensFlasher),
    (DENSO_REGIONS, DensoFlasher),
    (MM_REGIONS, MagnettiMarelliFlasher),
]


@dataclass
class SafetyReport:
    voltage: float
    voltage_ok: bool
    temperature: Optional[float]
    temperature_ok: bool
    power_stable: bool
    all_ok: bool


class FlashOrchestrator:
    """
    Selects the right flasher for a detected ECU and runs the full
    flash workflow with voltage/temperature/stability safety gates.
    """

    MIN_SAFE_VOLTAGE: float = 12.5
    VOLTAGE_STABILITY_SAMPLES: int = 5
    VOLTAGE_STABILITY_MAX_DELTA: float = 0.35  # V peak-to-peak
    MIN_TEMP_C: float = 10.0
    MAX_TEMP_C: float = 80.0

    def __init__(
        self,
        connection,
        *,
        variant_hint: Optional[str] = None,
        logger_: Optional[logging.Logger] = None,
    ) -> None:
        self.connection = connection
        self.variant_hint = variant_hint
        self.log = logger_ or logger
        self._selected: Optional[BaseECUFlasher] = None

    # ------------------------------------------------------------------
    # Flasher selection.
    # ------------------------------------------------------------------

    def detect_ecu_and_select_flasher(self, connection=None) -> BaseECUFlasher:
        """
        Detect the connected ECU by VIN/ECU-ID and return a ready flasher.

        If ``variant_hint`` is set, it is used directly.  Otherwise we try
        the generic UDS 0x22 F1 87 (ECU SW number) and fall back to
        0x22 F1 90 (VIN).  Real deployments should plug their own ECU
        fingerprinting in place of this simple heuristic.
        """
        conn = connection or self.connection
        if self.variant_hint:
            flasher = self._build_flasher(self.variant_hint, conn)
            self._selected = flasher
            return flasher

        # Try common ECU identification DIDs.
        identifier = None
        for did in (b"\x22\xF1\x87", b"\x22\xF1\x90", b"\x22\xF1\x9E"):
            try:
                conn.send(did)
                resp = conn.recv(timeout=2.0)
                if resp and resp[0] == 0x62:
                    identifier = resp[3:]
                    break
            except Exception:
                continue

        if not identifier:
            raise UnsupportedECUError(
                "ECU identification failed; pass variant_hint explicitly."
            )
        variant = self._identifier_to_variant(identifier)
        flasher = self._build_flasher(variant, conn)
        self._selected = flasher
        return flasher

    @staticmethod
    def _identifier_to_variant(identifier: bytes) -> str:
        text = identifier.decode("latin-1", errors="ignore").upper()
        candidates: List[Tuple[str, str]] = [
            ("EDC17C54", "EDC17C54"),
            ("EDC17",    "EDC17"),
            ("MED17",    "MED17"),
            ("ME7",      "ME7"),
            ("SIMOS18",  "SIMOS18"),
            ("SID208",   "SID208"),
            ("DCM6.2",   "DCM6.2"),
            ("DCM3.7",   "DCM3.7"),
            ("MJD",      "MJD8F3"),
            ("IAW",      "IAW5AF"),
            ("89661",    "DENSO_TOYOTA"),
        ]
        for needle, variant in candidates:
            if needle in text:
                return variant
        raise UnsupportedECUError(
            f"Unrecognized ECU identifier: {identifier.hex()}"
        )

    @staticmethod
    def _build_flasher(variant: str, connection) -> BaseECUFlasher:
        variant_u = variant.upper()
        for regions, cls in _VARIANT_TO_FLASHER:
            if variant_u in regions:
                return cls(connection, variant=variant_u)
        raise UnsupportedECUError(f"No flasher registered for {variant}")

    # ------------------------------------------------------------------
    # Safety gates.
    # ------------------------------------------------------------------

    def _safety_check_voltage(self) -> bool:
        try:
            v = float(self.connection.read_voltage())
        except Exception as exc:
            raise VoltageLowError(f"Voltage read failed: {exc}") from exc
        if v < self.MIN_SAFE_VOLTAGE:
            raise VoltageLowError(
                f"Voltage {v:.2f}V below {self.MIN_SAFE_VOLTAGE:.2f}V safe minimum"
            )
        return True

    def _safety_check_temperature(self) -> bool:
        read = getattr(self.connection, "read_temperature", None)
        if read is None:
            return True  # sensor optional
        try:
            t = float(read())
        except Exception:
            return True
        if not (self.MIN_TEMP_C <= t <= self.MAX_TEMP_C):
            raise TemperatureOutOfRangeError(
                f"Temperature {t:.1f} C outside [{self.MIN_TEMP_C}, {self.MAX_TEMP_C}]"
            )
        return True

    def _safety_check_power_stability(self) -> bool:
        samples: List[float] = []
        for _ in range(self.VOLTAGE_STABILITY_SAMPLES):
            try:
                samples.append(float(self.connection.read_voltage()))
            except Exception as exc:
                raise PowerUnstableError(
                    f"Voltage sampling failed: {exc}"
                ) from exc
            time.sleep(0.05)
        delta = max(samples) - min(samples)
        if delta > self.VOLTAGE_STABILITY_MAX_DELTA:
            raise PowerUnstableError(
                f"Voltage swing {delta:.2f}V > {self.VOLTAGE_STABILITY_MAX_DELTA}V"
            )
        return True

    def run_safety_checks(self) -> SafetyReport:
        v_ok = t_ok = p_ok = False
        voltage = 0.0
        temperature: Optional[float] = None
        try:
            self._safety_check_voltage()
            voltage = float(self.connection.read_voltage())
            v_ok = True
        except FlashError as exc:
            self.log.error("voltage check failed: %s", exc)
        try:
            self._safety_check_temperature()
            read = getattr(self.connection, "read_temperature", None)
            if read:
                try:
                    temperature = float(read())
                except Exception:
                    temperature = None
            t_ok = True
        except FlashError as exc:
            self.log.error("temperature check failed: %s", exc)
        try:
            self._safety_check_power_stability()
            p_ok = True
        except FlashError as exc:
            self.log.error("power-stability check failed: %s", exc)

        return SafetyReport(
            voltage=voltage,
            voltage_ok=v_ok,
            temperature=temperature,
            temperature_ok=t_ok,
            power_stable=p_ok,
            all_ok=v_ok and t_ok and p_ok,
        )

    # ------------------------------------------------------------------
    # Flash + verify + recover.
    # ------------------------------------------------------------------

    def flash_calibration(
        self,
        ecu_data: bytes,
        progress_callback: Optional[ProgressCallback] = None,
        on_error_callback: Optional[ErrorCallback] = None,
        backup_data: Optional[bytes] = None,
    ) -> FlashResult:
        """
        Run all safety checks, select a flasher, write the calibration,
        and perform a full read-back verification.  On any failure after
        the erase phase, attempt emergency recovery from ``backup_data``.
        """
        report = self.run_safety_checks()
        if not report.all_ok:
            err = VoltageLowError(
                f"Safety checks failed: voltage_ok={report.voltage_ok} "
                f"temperature_ok={report.temperature_ok} "
                f"power_stable={report.power_stable}"
            )
            if on_error_callback:
                on_error_callback(err)
            return FlashResult(
                success=False,
                ecu_type=self._selected.ECU_TYPE if self._selected else "UNKNOWN",
                bytes_written=0,
                duration_seconds=0.0,
                phase_reached=FlashPhase.PREPARING,
                error_message=str(err),
                error_spanish=err.spanish_message,
            )

        flasher = self._selected or self.detect_ecu_and_select_flasher()

        try:
            result = flasher.flash_full_calibration(
                ecu_data, progress_callback=progress_callback
            )
        except FlashError as exc:
            self.log.exception("flash aborted: %s", exc)
            if on_error_callback:
                on_error_callback(exc)
            recovered = False
            if backup_data is not None:
                try:
                    recovered = self.emergency_recovery(
                        backup_data, progress_callback=progress_callback
                    )
                except FlashError as rec_exc:
                    self.log.exception("recovery failed: %s", rec_exc)
            return FlashResult(
                success=False,
                ecu_type=flasher.ECU_TYPE,
                bytes_written=0,
                duration_seconds=0.0,
                phase_reached=flasher.phase,
                error_message=str(exc),
                error_spanish=exc.spanish_message,
                recovered_from_failure=recovered,
            )

        if not result.success:
            if on_error_callback and result.error_message:
                on_error_callback(
                    FlashInterruptedError(
                        result.error_message,
                        spanish_message=result.error_spanish,
                    )
                )
            if backup_data is not None:
                try:
                    result.recovered_from_failure = self.emergency_recovery(
                        backup_data, progress_callback=progress_callback
                    )
                except FlashError:
                    result.recovered_from_failure = False
        return result

    def verify_flash(self, original_data: bytes, written_data: bytes) -> bool:
        """Compare the expected post-flash image with a fresh read-back."""
        if len(original_data) != len(written_data):
            self.log.error(
                "verify length mismatch: expected %d got %d",
                len(original_data),
                len(written_data),
            )
            return False
        if original_data == written_data:
            return True
        # Report first divergence for diagnostics.
        for i, (a, b) in enumerate(zip(original_data, written_data)):
            if a != b:
                self.log.error(
                    "verify diff at 0x%08X: expected 0x%02X got 0x%02X",
                    i, a, b,
                )
                break
        return False

    def emergency_recovery(
        self,
        backup_data: bytes,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> bool:
        """
        Re-flash the ECU with a known-good backup image.

        Returns True on successful verified recovery, False otherwise.
        Never raises -- recovery should degrade gracefully.
        """
        flasher = self._selected
        if flasher is None:
            try:
                flasher = self.detect_ecu_and_select_flasher()
            except FlashError as exc:
                self.log.error("recovery cannot select flasher: %s", exc)
                return False

        # Recovery uses the same flow but with the backup image; we do not
        # re-run safety checks (we may be mid-crisis) but we still verify.
        try:
            result = flasher.flash_full_calibration(
                backup_data, progress_callback=progress_callback
            )
        except FlashError as exc:
            self.log.error("recovery flash raised: %s", exc)
            return False
        if not result.success:
            self.log.error(
                "recovery flash unsuccessful: %s", result.error_message
            )
            return False
        self.log.warning(
            "Emergency recovery succeeded on %s (%d bytes)",
            result.ecu_type,
            result.bytes_written,
        )
        return True
