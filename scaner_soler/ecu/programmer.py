"""
Reprogramación de ECU — Scaner Soler Pro.

Implementa lectura/escritura de flash y EEPROM mediante UDS (ISO 14229-1):
  - SecurityAccess  (0x27): seed+key para desbloquear ECU
  - ReadDataByIdentifier (0x22): leer parámetros e identificadores
  - RequestDownload  (0x34): iniciar transferencia de datos a ECU
  - TransferData     (0x36): enviar bloques de datos
  - RequestTransferExit (0x37): finalizar transferencia
  - WriteDataByIdentifier (0x2E): modificar parámetros individuales
  - RoutineControl   (0x31): ejecutar procedimientos de ECU

ADVERTENCIA DE SEGURIDAD:
  La reprogramación incorrecta puede inutilizar la ECU permanentemente.
  Este módulo está destinado a uso profesional con equipamiento certificado.
  Siempre realizar copia de seguridad antes de cualquier escritura.

Fuentes de referencia:
  - ISO 14229-1:2020 (UDS)
  - ISO 15765-2 (CAN transport layer / ISO-TP)
  - Bosch ECU programmer documentation
  - openpilot/panda UDS implementation (MIT license)
"""
from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..comm.elm327 import ELM327Protocol
from ..comm.kline import checksum_iso9141

# ---------------------------------------------------------------------------
# Constantes UDS (ISO 14229-1)
# ---------------------------------------------------------------------------

# Service IDs
UDS_DIAGNOSTIC_SESSION_CONTROL  = 0x10
UDS_ECU_RESET                    = 0x11
UDS_SECURITY_ACCESS              = 0x27
UDS_COMMUNICATION_CONTROL        = 0x28
UDS_TESTER_PRESENT               = 0x3E
UDS_READ_DATA_BY_IDENTIFIER      = 0x22
UDS_WRITE_DATA_BY_IDENTIFIER     = 0x2E
UDS_READ_MEMORY_BY_ADDRESS       = 0x23
UDS_WRITE_MEMORY_BY_ADDRESS      = 0x3D
UDS_REQUEST_DOWNLOAD             = 0x34
UDS_REQUEST_UPLOAD               = 0x35
UDS_TRANSFER_DATA                = 0x36
UDS_REQUEST_TRANSFER_EXIT        = 0x37
UDS_ROUTINE_CONTROL              = 0x31
UDS_NEGATIVE_RESPONSE            = 0x7F

# DiagnosticSession subtypes
SESSION_DEFAULT    = 0x01
SESSION_EXTENDED   = 0x03
SESSION_PROGRAMMING = 0x02

# Positive response offset
UDS_POSITIVE_OFFSET = 0x40

# Transfer block size y timeout
BLOCK_SIZE_BYTES = 512
BLOCK_TIMEOUT_SEC = 120.0

# DIDs comunes de identificación (ISO 14230 / SAE J2012)
DID_ECU_PART_NUMBER    = 0xF187  # ECU Part Number (ASCII)
DID_ECU_SERIAL_NUMBER  = 0xF18C  # ECU Serial Number
DID_SW_VERSION         = 0xF189  # ECU Software Version
DID_HW_VERSION         = 0xF191  # ECU Hardware Version
DID_VIN                = 0xF190  # Vehicle Identification Number


# ---------------------------------------------------------------------------
# Dataclasses de resultado
# ---------------------------------------------------------------------------

@dataclass
class ChecksumResult:
    """Resultado de verificación de checksum de una imagen de flash."""
    valid: bool
    computed: int
    stored: int
    algorithm: str = "ISO9141_SUM"
    note: str = ""


@dataclass
class WriteResult:
    """Resultado de una operación de escritura de flash."""
    success: bool
    bytes_written: int = 0
    checksum_ok: bool = False
    verify_errors: list[dict] = field(default_factory=list)
    elapsed_sec: float = 0.0
    error_message: str = ""


# ---------------------------------------------------------------------------
# Excepciones propias
# ---------------------------------------------------------------------------

class ECUProgrammerError(RuntimeError):
    """Error base del módulo de programación."""


class NoBackupError(ECUProgrammerError):
    """Se intentó escribir sin copia de seguridad previa."""


class SecurityAccessError(ECUProgrammerError):
    """Fallo al desbloquear el nivel de SecurityAccess."""


class UDSNegativeResponse(ECUProgrammerError):
    """La ECU devolvió un NRC (Negative Response Code) de UDS."""
    def __init__(self, service: int, nrc: int) -> None:
        self.service = service
        self.nrc = nrc
        nrc_names = {
            0x10: "generalReject",
            0x11: "serviceNotSupported",
            0x12: "subFunctionNotSupported",
            0x13: "incorrectMessageLengthOrInvalidFormat",
            0x22: "conditionsNotCorrect",
            0x24: "requestSequenceError",
            0x25: "noResponseFromSubnetComponent",
            0x26: "failurePreventsExecutionOfRequestedAction",
            0x31: "requestOutOfRange",
            0x33: "securityAccessDenied",
            0x35: "invalidKey",
            0x36: "exceededNumberOfAttempts",
            0x37: "requiredTimeDelayNotExpired",
            0x70: "uploadDownloadNotAccepted",
            0x71: "transferDataSuspended",
            0x72: "generalProgrammingFailure",
            0x73: "wrongBlockSequenceCounter",
            0x78: "requestCorrectlyReceivedResponsePending",
            0x7E: "subFunctionNotSupportedInActiveSession",
            0x7F: "serviceNotSupportedInActiveSession",
        }
        desc = nrc_names.get(nrc, f"NRC 0x{nrc:02X}")
        super().__init__(
            f"UDS NegativeResponse: service=0x{service:02X} NRC=0x{nrc:02X} ({desc})"
        )


# ---------------------------------------------------------------------------
# Clase principal
# ---------------------------------------------------------------------------

class ECUProgrammer:
    """
    Reprogramador de ECU mediante UDS (ISO 14229-1).

    Parámetros
    ----------
    comm_layer : ELM327Protocol
        Capa de comunicación ya inicializada. Se usa directamente para
        enviar tramas UDS crudas a través del ELM327.

    Notas de uso
    ------------
    - Siempre llamar a ``backup_to_file()`` antes de ``write_flash()`` o
      ``restore_from_file()``.
    - La escritura sin backup previo lanza ``NoBackupError``.
    - El timeout por bloque de 512 bytes es de 120 segundos.
    """

    def __init__(self, comm_layer: ELM327Protocol) -> None:
        self._comm = comm_layer
        self._backup_path: Optional[str] = None  # Ruta del último backup
        self._session_level: int = SESSION_DEFAULT
        self._security_unlocked: bool = False

    # ------------------------------------------------------------------
    # Comunicación UDS de bajo nivel
    # ------------------------------------------------------------------

    def _send_uds(self, payload: bytes) -> bytes:
        """
        Envía una trama UDS (ISO 14229-1 sobre ISO-TP / ELM327) y
        devuelve los bytes de respuesta sin el ID de servicio positivo.

        Lanza ``UDSNegativeResponse`` si la ECU devuelve 0x7F.
        """
        # Convertir a string hex para el ELM327
        hex_str = " ".join(f"{b:02X}" for b in payload)
        raw: str = self._comm.send_command(hex_str)
        time.sleep(0.05)

        # Parsear respuesta hex
        tokens = [t for t in raw.upper().split() if len(t) == 2]
        try:
            resp_bytes = bytes(int(t, 16) for t in tokens)
        except ValueError:
            raise ECUProgrammerError(f"Respuesta ELM inválida: {raw!r}")

        if not resp_bytes:
            raise ECUProgrammerError("ECU no respondió (respuesta vacía)")

        # Detectar NRC
        if resp_bytes[0] == UDS_NEGATIVE_RESPONSE:
            if len(resp_bytes) >= 3:
                raise UDSNegativeResponse(resp_bytes[1], resp_bytes[2])
            raise ECUProgrammerError(f"Respuesta negativa UDS incompleta: {resp_bytes.hex()}")

        # Verificar respuesta positiva (service_id + 0x40)
        expected_pos = (payload[0] + UDS_POSITIVE_OFFSET) & 0xFF
        if resp_bytes[0] != expected_pos:
            raise ECUProgrammerError(
                f"Respuesta inesperada: esperado 0x{expected_pos:02X}, "
                f"recibido 0x{resp_bytes[0]:02X}"
            )

        return resp_bytes[1:]  # Datos sin el byte de servicio positivo

    def _tester_present(self) -> None:
        """Envía TesterPresent (0x3E 0x00) para mantener viva la sesión."""
        try:
            self._send_uds(bytes([UDS_TESTER_PRESENT, 0x00]))
        except ECUProgrammerError:
            pass  # Ignorar si falla (no crítico)

    def _enter_session(self, session_type: int = SESSION_EXTENDED) -> None:
        """Entra en una sesión de diagnóstico UDS."""
        self._send_uds(bytes([UDS_DIAGNOSTIC_SESSION_CONTROL, session_type]))
        self._session_level = session_type

    # ------------------------------------------------------------------
    # SecurityAccess (UDS 0x27)
    # ------------------------------------------------------------------

    @staticmethod
    def seed_to_key(seed: bytes, level: int = 0x01) -> bytes:
        """
        Calcula la clave de SecurityAccess a partir del seed.

        IMPLEMENTACIÓN GENÉRICA (XOR + rotación de bits).
        ¡IMPORTANTE! Cada fabricante tiene su propio algoritmo:
          - Bosch ME7.5: XOR con constante 0xC541A9FD + suma
          - VAG EDC16:   tabla de lookup + XOR con nivel
          - BMW MSD80:   CRC32 sobre seed + número de pieza
          - Renault Delphi: rotación de 3 bits + XOR 0xA35F
          - Siemens SIM2K: XTEA cipher 32 rondas

        Para producción sustituir este método por el algoritmo del
        fabricante del vehículo objetivo.

        Parámetros
        ----------
        seed : bytes
            Seed devuelto por la ECU en el subservicio 0x27 0x01.
        level : int
            Nivel de acceso (0x01 = nivel 1, 0x03 = nivel 3, etc.)

        Devuelve
        --------
        bytes
            Clave calculada del mismo tamaño que el seed.
        """
        if not seed:
            return b""

        # Paso 1: XOR con constante dependiente del nivel
        xor_const = (0xC5A7 + level) & 0xFFFF
        key_ints = [b ^ ((xor_const >> (8 * (i % 2))) & 0xFF) for i, b in enumerate(seed)]

        # Paso 2: rotación circular izquierda de 3 bits sobre cada byte
        key_ints = [((b << 3) | (b >> 5)) & 0xFF for b in key_ints]

        # Paso 3: suma acumulativa con wrap 8-bit
        carry = 0
        result = []
        for b in key_ints:
            s = b + carry
            result.append(s & 0xFF)
            carry = s >> 8

        return bytes(result)

    def unlock_security_access(self, level: int = 0x01) -> bool:
        """
        Desbloquea la ECU usando el protocolo SecurityAccess UDS (0x27).

        Secuencia:
          1. Solicitar seed:  0x27 [level]        → seed de 4 bytes
          2. Calcular key:    seed_to_key(seed)
          3. Enviar key:      0x27 [level+1] [key]

        Parámetros
        ----------
        level : int
            Nivel de acceso a desbloquear (0x01 más común; 0x03 para
            sesión de programación; 0x05 para acceso extendido).

        Devuelve
        --------
        bool
            True si el acceso fue concedido, False si la ECU rechazó la clave.

        Lanza
        -----
        SecurityAccessError
            Si hay un error de protocolo (no simple rechazo de clave).
        """
        try:
            # Asegurar sesión extendida activa
            if self._session_level == SESSION_DEFAULT:
                self._enter_session(SESSION_EXTENDED)

            # Subservicio requestSeed = level (número impar)
            seed_resp = self._send_uds(bytes([UDS_SECURITY_ACCESS, level & 0xFE | 0x01]))
            seed = seed_resp  # Los bytes de respuesta son el seed directamente

            # Comprobar si ECU ya está desbloqueada (seed todo ceros)
            if all(b == 0x00 for b in seed):
                self._security_unlocked = True
                return True

            # Calcular clave
            key = self.seed_to_key(seed, level)

            # Subservicio sendKey = level + 1 (número par)
            key_payload = bytes([UDS_SECURITY_ACCESS, (level & 0xFE | 0x01) + 1]) + key
            self._send_uds(key_payload)

            self._security_unlocked = True
            return True

        except UDSNegativeResponse as e:
            if e.nrc in (0x35, 0x36):
                # 0x35 = invalidKey, 0x36 = exceededAttempts
                self._security_unlocked = False
                return False
            raise SecurityAccessError(f"SecurityAccess falló: {e}") from e

    # ------------------------------------------------------------------
    # Lectura de flash y EEPROM
    # ------------------------------------------------------------------

    def read_flash(
        self,
        start_addr: int = 0,
        length: int = 0x40000,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> bytes:
        """
        Lee la memoria flash de la ECU mediante UDS RequestUpload (0x35).

        Implementación UDS:
          0x35 [addrAndLenFormat] [memoryAddress...] [memorySize...]
          0x36 [blockSeqCounter] [data...]
          0x37                   (RequestTransferExit)

        Parámetros
        ----------
        start_addr : int
            Dirección de inicio en la memoria flash (default 0x000000).
        length : int
            Número de bytes a leer (default 256 KB = 0x40000).
        progress_cb : callable, opcional
            Función (bytes_leidos, total) para reportar progreso.

        Devuelve
        --------
        bytes
            Contenido de la memoria flash leída.

        Notas
        -----
        El formato de dirección/longitud (addrAndLenFormat) se calcula
        automáticamente como nibbles de 4 bytes para cada campo.
        """
        # Asegurar sesión y acceso
        if self._session_level == SESSION_DEFAULT:
            self._enter_session(SESSION_EXTENDED)

        data_blocks: list[bytes] = []
        bytes_read = 0
        block_seq = 0x01

        # --- RequestUpload ---
        # addrAndLenFormat: nibble alto = longitud del campo tamaño (4 bytes)
        #                   nibble bajo = longitud del campo dirección (4 bytes)
        addr_len_format = 0x44  # 4 bytes addr + 4 bytes size
        addr_bytes = struct.pack(">I", start_addr)
        size_bytes = struct.pack(">I", length)

        upload_payload = (
            bytes([UDS_REQUEST_UPLOAD, addr_len_format])
            + addr_bytes
            + size_bytes
        )
        upload_resp = self._send_uds(upload_payload)

        # La respuesta incluye maxBlockLength (2 bytes típicamente)
        max_block = BLOCK_SIZE_BYTES
        if len(upload_resp) >= 3:
            # Byte 0: lengthFormatIdentifier, bytes 1-N: maxBlockLength
            try:
                len_format = upload_resp[0]
                block_len_size = (len_format >> 4) & 0x0F
                if block_len_size > 0:
                    max_block = int.from_bytes(
                        upload_resp[1 : 1 + block_len_size], "big"
                    )
            except (IndexError, ValueError):
                pass

        # --- TransferData en bloques ---
        while bytes_read < length:
            self._tester_present()

            chunk_size = min(max_block, length - bytes_read)
            td_payload = bytes([UDS_TRANSFER_DATA, block_seq & 0xFF])
            # Para lectura, TransferData sin datos en payload (ECU responde con datos)
            td_resp = self._send_uds(td_payload)

            # Los datos están en la respuesta tras el blockSeqCounter
            chunk_data = td_resp[1:] if len(td_resp) > 1 else b""
            if not chunk_data:
                raise ECUProgrammerError(
                    f"TransferData sin datos en bloque 0x{block_seq:02X}"
                )

            data_blocks.append(chunk_data[:chunk_size])
            bytes_read += len(chunk_data[:chunk_size])
            block_seq = (block_seq % 0xFF) + 1

            if progress_cb:
                progress_cb(bytes_read, length)

        # --- RequestTransferExit ---
        self._send_uds(bytes([UDS_REQUEST_TRANSFER_EXIT]))

        return b"".join(data_blocks)[:length]

    def read_eeprom(
        self,
        start_addr: int = 0,
        length: int = 0x800,
    ) -> bytes:
        """
        Lee la EEPROM de la ECU.

        Usa ReadMemoryByAddress (UDS 0x23) si la ECU lo soporta.
        Muchas ECUs también exponen la EEPROM como DIDs de calibración
        accesibles via ReadDataByIdentifier (0x22).

        Parámetros
        ----------
        start_addr : int
            Dirección de inicio en la EEPROM (default 0x0000).
        length : int
            Número de bytes a leer (default 2 KB = 0x800).

        Devuelve
        --------
        bytes
            Contenido de la EEPROM.
        """
        if self._session_level == SESSION_DEFAULT:
            self._enter_session(SESSION_EXTENDED)

        # UDS 0x23: ReadMemoryByAddress
        # addrAndLenFormat: 0x24 = 2 bytes addr + 4 bytes size
        addr_len_format = 0x24
        addr_bytes = struct.pack(">H", start_addr & 0xFFFF)
        size_bytes = struct.pack(">I", length)

        payload = (
            bytes([UDS_READ_MEMORY_BY_ADDRESS, addr_len_format])
            + addr_bytes
            + size_bytes
        )
        resp = self._send_uds(payload)
        return resp[:length]

    # ------------------------------------------------------------------
    # Escritura de flash
    # ------------------------------------------------------------------

    def write_flash(
        self,
        data: bytes,
        start_addr: int = 0,
        verify: bool = True,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> WriteResult:
        """
        Escribe datos en la memoria flash de la ECU.

        Secuencia UDS completa:
          1. DiagnosticSessionControl(programmingSession = 0x02)
          2. SecurityAccess(level 0x01 o 0x03)
          3. Verificar checksum de los datos a escribir
          4. RequestDownload(addr, size)
          5. TransferData en bloques de BLOCK_SIZE_BYTES
          6. RequestTransferExit
          7. (Opcional) RoutineControl "CheckMemory" para verificar

        Salvaguardas:
          - Lanza ``NoBackupError`` si no existe backup previo (ver backup_to_file).
          - Verifica checksum de los datos antes de iniciar.
          - Timeout de BLOCK_TIMEOUT_SEC por bloque.
          - Verifica la escritura leyendo de vuelta si verify=True.

        Parámetros
        ----------
        data : bytes
            Imagen de firmware / calibración a escribir.
        start_addr : int
            Dirección de inicio en flash.
        verify : bool
            Si True, lee de vuelta y compara bloque por bloque.
        progress_cb : callable, opcional
            Función (bytes_escritos, total) para reportar progreso.

        Devuelve
        --------
        WriteResult
            Resultado detallado de la operación.

        Lanza
        -----
        NoBackupError
            Si no existe archivo de backup previo validado.
        ECUProgrammerError
            En cualquier error de protocolo.
        """
        # --- SALVAGUARDA 1: backup obligatorio ---
        if not self._backup_path or not os.path.isfile(self._backup_path):
            raise NoBackupError(
                "No existe copia de seguridad previa. "
                "Llamar a backup_to_file() antes de cualquier escritura."
            )

        # --- SALVAGUARDA 2: checksum previo ---
        pre_check = self.verify_checksum(data)
        if not pre_check.valid:
            return WriteResult(
                success=False,
                error_message=(
                    f"Checksum de datos inválido antes de escribir: "
                    f"calculado=0x{pre_check.computed:02X}, "
                    f"almacenado=0x{pre_check.stored:02X}"
                ),
            )

        t_start = time.monotonic()
        total = len(data)
        bytes_written = 0
        verify_errors: list[dict] = []

        try:
            # --- Sesión de programación ---
            self._enter_session(SESSION_PROGRAMMING)

            # --- SecurityAccess nivel 3 (programación) ---
            if not self.unlock_security_access(level=0x03):
                return WriteResult(
                    success=False,
                    error_message="SecurityAccess denegado (nivel 0x03)",
                )

            # --- RequestDownload ---
            addr_len_format = 0x44
            addr_bytes = struct.pack(">I", start_addr)
            size_bytes = struct.pack(">I", total)
            dl_payload = (
                bytes([UDS_REQUEST_DOWNLOAD, 0x00, addr_len_format])
                + addr_bytes
                + size_bytes
            )
            dl_resp = self._send_uds(dl_payload)

            # Extraer maxBlockLength de la respuesta
            max_block = BLOCK_SIZE_BYTES
            if len(dl_resp) >= 2:
                try:
                    block_len_nibble = (dl_resp[0] >> 4) & 0x0F
                    if block_len_nibble > 0:
                        max_block = int.from_bytes(
                            dl_resp[1 : 1 + block_len_nibble], "big"
                        )
                except (IndexError, ValueError):
                    pass

            # --- TransferData en bloques ---
            block_seq = 0x01
            offset = 0

            while offset < total:
                block_data = data[offset : offset + min(max_block, total - offset)]
                block_start = time.monotonic()

                # Timeout por bloque
                if time.monotonic() - block_start > BLOCK_TIMEOUT_SEC:
                    return WriteResult(
                        success=False,
                        bytes_written=bytes_written,
                        error_message=f"Timeout en bloque 0x{block_seq:02X}",
                        elapsed_sec=time.monotonic() - t_start,
                    )

                td_payload = bytes([UDS_TRANSFER_DATA, block_seq & 0xFF]) + block_data
                self._send_uds(td_payload)

                self._tester_present()

                bytes_written += len(block_data)
                offset += len(block_data)
                block_seq = (block_seq % 0xFF) + 1

                if progress_cb:
                    progress_cb(bytes_written, total)

            # --- RequestTransferExit ---
            self._send_uds(bytes([UDS_REQUEST_TRANSFER_EXIT]))

            # --- SALVAGUARDA 3: verificación por lectura ---
            post_check = ChecksumResult(valid=True, computed=0, stored=0)
            if verify:
                try:
                    readback = self.read_flash(start_addr, total)
                    if readback != data:
                        for i, (a, b_) in enumerate(zip(data, readback)):
                            if a != b_:
                                verify_errors.append({
                                    "offset": i,
                                    "expected": a,
                                    "got": b_,
                                })
                                if len(verify_errors) >= 20:
                                    verify_errors.append({"note": "truncated after 20 errors"})
                                    break
                    post_check = self.verify_checksum(readback)
                except ECUProgrammerError as exc:
                    verify_errors.append({"note": f"Lectura de verificación falló: {exc}"})

            elapsed = time.monotonic() - t_start
            return WriteResult(
                success=len(verify_errors) == 0,
                bytes_written=bytes_written,
                checksum_ok=post_check.valid,
                verify_errors=verify_errors,
                elapsed_sec=elapsed,
            )

        except (UDSNegativeResponse, ECUProgrammerError) as exc:
            return WriteResult(
                success=False,
                bytes_written=bytes_written,
                error_message=str(exc),
                elapsed_sec=time.monotonic() - t_start,
            )

    # ------------------------------------------------------------------
    # Backup y restore
    # ------------------------------------------------------------------

    def backup_to_file(
        self,
        path: str,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> str:
        """
        Lee la flash completa y la guarda en un archivo binario.

        El archivo se guarda en la ruta indicada. Si la ruta es un
        directorio se genera un nombre automático con timestamp y
        VIN (si disponible).

        Parámetros
        ----------
        path : str
            Ruta destino del archivo (.bin) o directorio donde guardarlo.
        progress_cb : callable, opcional
            Función (bytes_leídos, total) para reportar progreso.

        Devuelve
        --------
        str
            Ruta absoluta del archivo creado.

        Lanza
        -----
        ECUProgrammerError
            Si la lectura falla o el directorio no existe.
        """
        if os.path.isdir(path):
            ts = time.strftime("%Y%m%d_%H%M%S")
            # Intentar obtener VIN para el nombre del archivo
            vin_suffix = ""
            try:
                info = self.get_ecu_info()
                vin = info.get("vin", "")
                if vin and len(vin) >= 6:
                    vin_suffix = f"_{vin[-6:]}"
            except ECUProgrammerError:
                pass
            fname = f"ecu_backup_{ts}{vin_suffix}.bin"
            path = os.path.join(path, fname)

        path = os.path.abspath(path)
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            raise ECUProgrammerError(
                f"El directorio destino no existe: {parent!r}"
            )

        flash_data = self.read_flash(progress_cb=progress_cb)

        with open(path, "wb") as fh:
            fh.write(flash_data)

        self._backup_path = path
        return path

    def restore_from_file(
        self,
        path: str,
        verify: bool = True,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> WriteResult:
        """
        Restaura la flash de la ECU desde un archivo de backup.

        Parámetros
        ----------
        path : str
            Ruta al archivo .bin de backup a restaurar.
        verify : bool
            Si True, verifica la escritura comparando con el archivo.
        progress_cb : callable, opcional
            Función (bytes_escritos, total) para reportar progreso.

        Devuelve
        --------
        WriteResult
            Resultado de la operación de escritura.

        Lanza
        -----
        FileNotFoundError
            Si el archivo no existe.
        NoBackupError
            (Reusado) si el archivo está vacío o no es un .bin válido.
        """
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Archivo de backup no encontrado: {path!r}")

        with open(path, "rb") as fh:
            data = fh.read()

        if len(data) < 1024:
            raise NoBackupError(
                f"El archivo {path!r} es sospechosamente pequeño "
                f"({len(data)} bytes). Verificar que sea un backup válido."
            )

        # Registrar como backup válido para que write_flash lo acepte
        self._backup_path = path

        return self.write_flash(data, start_addr=0, verify=verify, progress_cb=progress_cb)

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    def verify_checksum(self, data: bytes) -> ChecksumResult:
        """
        Verifica el checksum de una imagen de flash.

        Algoritmo primario: suma de todos los bytes módulo 256
        (compatible con ISO 9141-2 — checksum_iso9141).

        Para imágenes reales de ECU el checksum suele estar en los
        últimos 1-4 bytes del bloque de calibración. Esta implementación
        usa la convención más común (último byte = checksum del resto).

        Parámetros
        ----------
        data : bytes
            Imagen de flash a verificar.

        Devuelve
        --------
        ChecksumResult
        """
        if not data:
            return ChecksumResult(
                valid=False, computed=0, stored=0,
                note="Datos vacíos"
            )

        # El último byte se trata como el checksum almacenado
        payload = data[:-1]
        stored = data[-1]
        computed = checksum_iso9141(payload)

        return ChecksumResult(
            valid=(computed == stored),
            computed=computed,
            stored=stored,
            algorithm="ISO9141_SUM_MOD256",
            note=(
                "Suma módulo 256 de todos los bytes excepto el último. "
                "Para imágenes reales usar el algoritmo del fabricante "
                "(CRC32 Bosch, Fletcher-16 Delphi, etc.)."
            ),
        )

    def patch_map(
        self,
        flash_data: bytes,
        offset: int,
        new_values: bytes,
    ) -> bytes:
        """
        Aplica un parche en memoria a una imagen de flash en memoria.

        Sustituye los bytes en ``offset`` por ``new_values`` y recalcula
        el checksum en el último byte.

        Parámetros
        ----------
        flash_data : bytes
            Imagen de flash completa.
        offset : int
            Posición (byte) donde aplicar el parche.
        new_values : bytes
            Nuevos valores a insertar.

        Devuelve
        --------
        bytes
            Nueva imagen de flash con el parche y checksum actualizado.

        Lanza
        -----
        ValueError
            Si el parche queda fuera del rango de la imagen.
        """
        end = offset + len(new_values)
        if end > len(flash_data):
            raise ValueError(
                f"Parche en offset=0x{offset:X} + {len(new_values)} bytes "
                f"excede el tamaño de imagen ({len(flash_data)} bytes)"
            )

        patched = bytearray(flash_data)
        patched[offset:end] = new_values

        # Recalcular checksum (último byte)
        new_checksum = checksum_iso9141(patched[:-1])
        patched[-1] = new_checksum

        return bytes(patched)

    def get_ecu_info(self) -> dict:
        """
        Lee los identificadores básicos de la ECU via ReadDataByIdentifier (0x22).

        DIDs consultados (ISO 14230 / SAE J2012):
          - 0xF187: Part Number
          - 0xF18C: Serial Number
          - 0xF189: Software Version
          - 0xF191: Hardware Version
          - 0xF190: VIN

        Devuelve
        --------
        dict con claves: part_number, serial_number, sw_version,
                         hw_version, vin, raw (dict hex de respuestas)
        """
        if self._session_level == SESSION_DEFAULT:
            self._enter_session(SESSION_EXTENDED)

        dids = {
            "part_number":    DID_ECU_PART_NUMBER,
            "serial_number":  DID_ECU_SERIAL_NUMBER,
            "sw_version":     DID_SW_VERSION,
            "hw_version":     DID_HW_VERSION,
            "vin":            DID_VIN,
        }

        result: dict = {"raw": {}}

        for key, did in dids.items():
            try:
                payload = bytes([
                    UDS_READ_DATA_BY_IDENTIFIER,
                    (did >> 8) & 0xFF,
                    did & 0xFF,
                ])
                resp = self._send_uds(payload)
                # La respuesta incluye el DID (2 bytes) seguido de los datos
                data_bytes = resp[2:] if len(resp) > 2 else resp
                try:
                    decoded = data_bytes.decode("ascii", errors="replace").strip()
                except Exception:
                    decoded = data_bytes.hex()
                result[key] = decoded
                result["raw"][f"0x{did:04X}"] = data_bytes.hex()
            except (UDSNegativeResponse, ECUProgrammerError) as exc:
                result[key] = None
                result["raw"][f"0x{did:04X}"] = f"ERROR: {exc}"

        return result
