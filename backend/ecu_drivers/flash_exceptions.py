"""
Custom exceptions for the ECU flashing subsystem.

All user-facing exceptions carry both an English technical message and a
Spanish message suitable for direct display to end users.
"""
from __future__ import annotations

from typing import Optional


class FlashError(Exception):
    """Base class for all flash-related errors."""

    default_spanish: str = "Error durante la operacion de flasheo de la ECU."

    def __init__(
        self,
        message: str,
        spanish_message: Optional[str] = None,
        address: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.spanish_message = spanish_message or self.default_spanish
        self.address = address

    def __str__(self) -> str:
        if self.address is not None:
            return f"{self.message} (addr=0x{self.address:08X})"
        return self.message


class FlashInterruptedError(FlashError):
    """Raised when a flash operation is interrupted (power loss, user abort, tester present fail)."""

    default_spanish = (
        "El proceso de flasheo fue interrumpido. NO apague el vehiculo. "
        "Inicie el modo de recuperacion inmediatamente."
    )


class ChecksumMismatchError(FlashError):
    """Raised when a calculated checksum does not match the expected value."""

    default_spanish = (
        "La verificacion del checksum ha fallado. La calibracion no es valida "
        "y NO sera escrita en la ECU."
    )


class SeedKeyFailedError(FlashError):
    """Raised when the seed-key security access challenge fails."""

    default_spanish = (
        "La autenticacion de seguridad (seed-key) ha fallado. "
        "La ECU ha rechazado el acceso para programacion."
    )


class VoltageLowError(FlashError):
    """Raised when battery voltage drops below safe flashing level."""

    default_spanish = (
        "Voltaje de bateria demasiado bajo para flashear de forma segura. "
        "Conecte un mantenedor de carga (>13.2V) antes de continuar."
    )


class FlashVerificationError(FlashError):
    """Raised when written data does not match expected data after verification read-back."""

    default_spanish = (
        "La verificacion post-escritura ha fallado. Los datos escritos no "
        "coinciden con los esperados. Iniciando recuperacion."
    )


class UnsupportedECUError(FlashError):
    """Raised when no flasher is available for the detected ECU."""

    default_spanish = "Esta ECU no es compatible con el modulo de flasheo."


class ProgrammingModeError(FlashError):
    """Raised when the ECU cannot be placed into programming mode."""

    default_spanish = (
        "No se pudo entrar en modo de programacion. "
        "Verifique la conexion y el estado del vehiculo."
    )


class EraseFailedError(FlashError):
    """Raised when a flash region erase operation fails."""

    default_spanish = "El borrado de la memoria flash ha fallado."


class WriteFailedError(FlashError):
    """Raised when a block write operation fails."""

    default_spanish = "La escritura de un bloque de flash ha fallado."


class TesterPresentLostError(FlashError):
    """Raised when the tester-present heartbeat is lost during programming."""

    default_spanish = (
        "Se perdio la comunicacion con la ECU durante el flasheo. "
        "Iniciando recuperacion de emergencia."
    )


class TemperatureOutOfRangeError(FlashError):
    """Raised when ambient/engine temperature is outside safe flashing range."""

    default_spanish = (
        "Temperatura fuera del rango seguro para flasheo. "
        "Espere a que el motor este entre 10 C y 80 C."
    )


class PowerUnstableError(FlashError):
    """Raised when voltage fluctuates beyond safe stability margin."""

    default_spanish = (
        "La alimentacion electrica es inestable. "
        "Use un cargador de bateria de laboratorio para flashear."
    )
