"""
J2534 PassThru Driver - Interfaz con hardware J2534 (Tactrix, Drew Tech, etc.).

SAE J2534 es el estándar para herramientas de diagnóstico PassThru. Este módulo
carga la DLL del fabricante correspondiente (Tactrix Openport, Drew Tech
MongoosePro, Scanmatik, etc.) mediante ctypes en Windows, y expone una API
Python segura y tipada.

Referencia: SAE J2534-1 y J2534-2 (2004/2006).
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import sys
from ctypes import (
    POINTER,
    Structure,
    c_char,
    c_char_p,
    c_long,
    c_ubyte,
    c_ulong,
    c_void_p,
    byref,
)
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constantes J2534
# ---------------------------------------------------------------------------


class J2534Protocol(IntEnum):
    """Protocolos soportados por J2534."""
    J1850VPW = 1
    J1850PWM = 2
    ISO9141 = 3
    ISO14230 = 4      # KWP2000
    CAN = 5
    ISO15765 = 6      # UDS / ISO-TP
    SCI_A_ENGINE = 7
    SCI_A_TRANS = 8
    SCI_B_ENGINE = 9
    SCI_B_TRANS = 10


class J2534Ioctl(IntEnum):
    """IDs de IOCTL."""
    GET_CONFIG = 0x01
    SET_CONFIG = 0x02
    READ_VBATT = 0x03
    FIVE_BAUD_INIT = 0x04
    FAST_INIT = 0x05
    CLEAR_TX_BUFFER = 0x07
    CLEAR_RX_BUFFER = 0x08
    CLEAR_PERIODIC_MSGS = 0x09
    CLEAR_MSG_FILTERS = 0x0A
    CLEAR_FUNCT_MSG_LOOKUP_TABLE = 0x0B
    ADD_TO_FUNCT_MSG_LOOKUP_TABLE = 0x0C
    DELETE_FROM_FUNCT_MSG_LOOKUP_TABLE = 0x0D
    READ_PROG_VOLTAGE = 0x0E


class J2534FilterType(IntEnum):
    PASS_FILTER = 1
    BLOCK_FILTER = 2
    FLOW_CONTROL_FILTER = 3


class J2534ReturnCode(IntEnum):
    """Códigos de retorno J2534."""
    STATUS_NOERROR = 0x00
    ERR_NOT_SUPPORTED = 0x01
    ERR_INVALID_CHANNEL_ID = 0x02
    ERR_INVALID_PROTOCOL_ID = 0x03
    ERR_NULL_PARAMETER = 0x04
    ERR_INVALID_IOCTL_VALUE = 0x05
    ERR_INVALID_FLAGS = 0x06
    ERR_FAILED = 0x07
    ERR_DEVICE_NOT_CONNECTED = 0x08
    ERR_TIMEOUT = 0x09
    ERR_INVALID_MSG = 0x0A
    ERR_INVALID_TIME_INTERVAL = 0x0B
    ERR_EXCEEDED_LIMIT = 0x0C
    ERR_INVALID_MSG_ID = 0x0D
    ERR_DEVICE_IN_USE = 0x0E
    ERR_INVALID_IOCTL_ID = 0x0F
    ERR_BUFFER_EMPTY = 0x10
    ERR_BUFFER_FULL = 0x11
    ERR_BUFFER_OVERFLOW = 0x12
    ERR_PIN_INVALID = 0x13
    ERR_CHANNEL_IN_USE = 0x14
    ERR_MSG_PROTOCOL_ID = 0x15
    ERR_INVALID_FILTER_ID = 0x16
    ERR_NO_FLOW_CONTROL = 0x17
    ERR_NOT_UNIQUE = 0x18
    ERR_INVALID_BAUDRATE = 0x19
    ERR_INVALID_DEVICE_ID = 0x1A


# Flags ISO15765
ISO15765_FRAME_PAD = 0x00000040
ISO15765_ADDR_TYPE = 0x00000080
CAN_29BIT_ID = 0x00000100
CAN_ID_BOTH = 0x00000800
TX_DONE = 0x00000400


# ---------------------------------------------------------------------------
# Estructuras ctypes
# ---------------------------------------------------------------------------


class PASSTHRU_MSG(Structure):
    """Estructura de mensaje J2534."""
    _fields_ = [
        ("ProtocolID", c_ulong),
        ("RxStatus", c_ulong),
        ("TxFlags", c_ulong),
        ("Timestamp", c_ulong),
        ("DataSize", c_ulong),
        ("ExtraDataIndex", c_ulong),
        ("Data", c_ubyte * 4128),
    ]


class SCONFIG(Structure):
    _fields_ = [
        ("Parameter", c_ulong),
        ("Value", c_ulong),
    ]


class SCONFIG_LIST(Structure):
    _fields_ = [
        ("NumOfParams", c_ulong),
        ("ConfigPtr", POINTER(SCONFIG)),
    ]


class SBYTE_ARRAY(Structure):
    _fields_ = [
        ("NumOfBytes", c_ulong),
        ("BytePtr", POINTER(c_ubyte)),
    ]


# ---------------------------------------------------------------------------
# Excepciones
# ---------------------------------------------------------------------------


class J2534Error(Exception):
    """Error en operación J2534."""

    def __init__(self, code: int, dll_message: str = ""):
        self.code = code
        try:
            name = J2534ReturnCode(code).name
        except ValueError:
            name = f"UNKNOWN_0x{code:02X}"
        super().__init__(
            f"Error J2534: {name} (0x{code:02X}) - {dll_message}"
        )


# ---------------------------------------------------------------------------
# Rutas conocidas de DLLs J2534
# ---------------------------------------------------------------------------


KNOWN_DLL_PATHS = {
    "tactrix": [
        r"C:\Program Files (x86)\OpenECU\OpenPort 2.0 J2534 ISO CAN\op20pt32.dll",
        r"C:\Program Files\OpenECU\OpenPort 2.0 J2534 ISO CAN\op20pt32.dll",
    ],
    "drewtech_mongoose": [
        r"C:\Program Files (x86)\Drew Technologies, Inc\J2534\MongoosePro GM II\monpa432.dll",
    ],
    "scanmatik": [
        r"C:\Program Files (x86)\Scanmatik\SMJ2534.dll",
    ],
    "godiag": [
        r"C:\Program Files (x86)\GODIAG\J2534\GODIAG.dll",
    ],
}


# ---------------------------------------------------------------------------
# Driver J2534
# ---------------------------------------------------------------------------


@dataclass
class J2534ChannelConfig:
    """Configuración de canal J2534."""
    protocol: J2534Protocol = J2534Protocol.ISO15765
    baud_rate: int = 500000
    flags: int = 0


class J2534Driver:
    """
    Driver J2534 PassThru.

    Carga la DLL del fabricante y provee una interfaz Python a las funciones
    PassThru estándar. Usa ctypes para la comunicación directa con la DLL.

    Ejemplo:
        driver = J2534Driver()
        driver.load_dll("C:/ruta/j2534.dll")
        driver.open()
        channel = driver.connect_channel(J2534Protocol.ISO15765, 500000)
        driver.write_message(channel, tx_id=0x7E0, data=b"\\x22\\xF1\\x90")
        resp = driver.read_messages(channel)
    """

    def __init__(self, dll_path: Optional[str] = None):
        if platform.system() != "Windows":
            logger.warning(
                "J2534 está diseñado principalmente para Windows. "
                "En otros SOs podría requerir implementación alternativa."
            )
        self.dll_path = dll_path
        self.dll: Optional[ctypes.WinDLL] = None  # type: ignore[attr-defined]
        self.device_id: Optional[c_ulong] = None
        self.channels: dict[int, J2534ChannelConfig] = {}
        self._log = logging.getLogger(f"{__name__}.J2534Driver")

    # ------------------------------------------------------------------
    # Carga de DLL
    # ------------------------------------------------------------------

    def load_dll(self, dll_path: Optional[str] = None) -> None:
        """
        Carga la DLL J2534.

        Args:
            dll_path: Ruta explícita a la DLL. Si es None intenta auto-detección.
        """
        path = dll_path or self.dll_path or self._auto_detect_dll()
        if not path:
            raise J2534Error(
                J2534ReturnCode.ERR_DEVICE_NOT_CONNECTED,
                "No se encontró ninguna DLL J2534 instalada",
            )
        if not os.path.isfile(path):
            raise FileNotFoundError(f"DLL J2534 no encontrada: {path}")

        try:
            if platform.system() == "Windows":
                self.dll = ctypes.WinDLL(path)  # type: ignore[attr-defined]
            else:
                self.dll = ctypes.CDLL(path)  # type: ignore[assignment]
        except OSError as exc:
            raise J2534Error(
                J2534ReturnCode.ERR_FAILED,
                f"No se pudo cargar la DLL '{path}': {exc}",
            ) from exc

        self.dll_path = path
        self._setup_function_signatures()
        self._log.info("DLL J2534 cargada: %s", path)

    @staticmethod
    def _auto_detect_dll() -> Optional[str]:
        """Intenta localizar una DLL J2534 instalada en el sistema."""
        for paths in KNOWN_DLL_PATHS.values():
            for candidate in paths:
                if os.path.isfile(candidate):
                    return candidate
        return None

    def _setup_function_signatures(self) -> None:
        """Configura los prototipos de las funciones de la DLL."""
        assert self.dll is not None

        self.dll.PassThruOpen.argtypes = [c_void_p, POINTER(c_ulong)]
        self.dll.PassThruOpen.restype = c_long

        self.dll.PassThruClose.argtypes = [c_ulong]
        self.dll.PassThruClose.restype = c_long

        self.dll.PassThruConnect.argtypes = [
            c_ulong,
            c_ulong,
            c_ulong,
            c_ulong,
            POINTER(c_ulong),
        ]
        self.dll.PassThruConnect.restype = c_long

        self.dll.PassThruDisconnect.argtypes = [c_ulong]
        self.dll.PassThruDisconnect.restype = c_long

        self.dll.PassThruReadMsgs.argtypes = [
            c_ulong,
            POINTER(PASSTHRU_MSG),
            POINTER(c_ulong),
            c_ulong,
        ]
        self.dll.PassThruReadMsgs.restype = c_long

        self.dll.PassThruWriteMsgs.argtypes = [
            c_ulong,
            POINTER(PASSTHRU_MSG),
            POINTER(c_ulong),
            c_ulong,
        ]
        self.dll.PassThruWriteMsgs.restype = c_long

        self.dll.PassThruStartPeriodicMsg.argtypes = [
            c_ulong,
            POINTER(PASSTHRU_MSG),
            POINTER(c_ulong),
            c_ulong,
        ]
        self.dll.PassThruStartPeriodicMsg.restype = c_long

        self.dll.PassThruStopPeriodicMsg.argtypes = [c_ulong, c_ulong]
        self.dll.PassThruStopPeriodicMsg.restype = c_long

        self.dll.PassThruStartMsgFilter.argtypes = [
            c_ulong,
            c_ulong,
            POINTER(PASSTHRU_MSG),
            POINTER(PASSTHRU_MSG),
            POINTER(PASSTHRU_MSG),
            POINTER(c_ulong),
        ]
        self.dll.PassThruStartMsgFilter.restype = c_long

        self.dll.PassThruStopMsgFilter.argtypes = [c_ulong, c_ulong]
        self.dll.PassThruStopMsgFilter.restype = c_long

        self.dll.PassThruSetProgrammingVoltage.argtypes = [
            c_ulong,
            c_ulong,
            c_ulong,
        ]
        self.dll.PassThruSetProgrammingVoltage.restype = c_long

        self.dll.PassThruReadVersion.argtypes = [
            c_ulong,
            c_char_p,
            c_char_p,
            c_char_p,
        ]
        self.dll.PassThruReadVersion.restype = c_long

        self.dll.PassThruGetLastError.argtypes = [c_char_p]
        self.dll.PassThruGetLastError.restype = c_long

        self.dll.PassThruIoctl.argtypes = [c_ulong, c_ulong, c_void_p, c_void_p]
        self.dll.PassThruIoctl.restype = c_long

    # ------------------------------------------------------------------
    # Manejo de errores
    # ------------------------------------------------------------------

    def _check(self, return_code: int) -> None:
        """Verifica un código de retorno y lanza excepción si es un error."""
        if return_code != J2534ReturnCode.STATUS_NOERROR:
            message = self._get_last_error()
            raise J2534Error(return_code, message)

    def _get_last_error(self) -> str:
        """Obtiene el último mensaje de error desde la DLL."""
        if self.dll is None:
            return ""
        buffer = ctypes.create_string_buffer(80)
        try:
            self.dll.PassThruGetLastError(buffer)
            return buffer.value.decode("ascii", errors="replace")
        except Exception:  # pragma: no cover
            return ""

    # ------------------------------------------------------------------
    # Apertura / cierre del dispositivo
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Abre el dispositivo J2534 físico."""
        if self.dll is None:
            self.load_dll()
        assert self.dll is not None
        device_id = c_ulong(0)
        rc = self.dll.PassThruOpen(None, byref(device_id))
        self._check(rc)
        self.device_id = device_id
        self._log.info("Dispositivo J2534 abierto (DeviceID=%d)", device_id.value)

    def close(self) -> None:
        """Cierra el dispositivo J2534."""
        if self.dll is None or self.device_id is None:
            return
        # Desconectar canales pendientes
        for ch_id in list(self.channels.keys()):
            try:
                self.disconnect_channel(ch_id)
            except Exception:
                pass
        rc = self.dll.PassThruClose(self.device_id)
        self.device_id = None
        self._check(rc)
        self._log.info("Dispositivo J2534 cerrado")

    def read_version(self) -> tuple[str, str, str]:
        """Lee la versión del firmware, DLL y API del dispositivo."""
        assert self.dll is not None and self.device_id is not None
        firmware = ctypes.create_string_buffer(80)
        dll_ver = ctypes.create_string_buffer(80)
        api_ver = ctypes.create_string_buffer(80)
        rc = self.dll.PassThruReadVersion(
            self.device_id, firmware, dll_ver, api_ver
        )
        self._check(rc)
        return (
            firmware.value.decode("ascii", errors="replace"),
            dll_ver.value.decode("ascii", errors="replace"),
            api_ver.value.decode("ascii", errors="replace"),
        )

    # ------------------------------------------------------------------
    # Canal
    # ------------------------------------------------------------------

    def connect_channel(
        self,
        protocol: J2534Protocol,
        baud_rate: int = 500000,
        flags: int = 0,
    ) -> int:
        """
        Conecta un canal al protocolo especificado.

        Args:
            protocol: Protocolo J2534.
            baud_rate: Velocidad en baudios.
            flags: Flags (p.ej. CAN_29BIT_ID).

        Returns:
            ID del canal conectado.
        """
        assert self.dll is not None and self.device_id is not None
        channel_id = c_ulong(0)
        rc = self.dll.PassThruConnect(
            self.device_id,
            c_ulong(int(protocol)),
            c_ulong(flags),
            c_ulong(baud_rate),
            byref(channel_id),
        )
        self._check(rc)
        self.channels[channel_id.value] = J2534ChannelConfig(
            protocol=protocol, baud_rate=baud_rate, flags=flags
        )
        self._log.info(
            "Canal J2534 conectado: id=%d protocol=%s baud=%d",
            channel_id.value,
            protocol.name,
            baud_rate,
        )
        return channel_id.value

    def disconnect_channel(self, channel_id: int) -> None:
        """Desconecta un canal."""
        assert self.dll is not None
        rc = self.dll.PassThruDisconnect(c_ulong(channel_id))
        self.channels.pop(channel_id, None)
        self._check(rc)

    # ------------------------------------------------------------------
    # Mensajes
    # ------------------------------------------------------------------

    def write_message(
        self,
        channel_id: int,
        tx_id: int,
        data: bytes,
        timeout_ms: int = 1000,
        extended_id: bool = False,
    ) -> None:
        """
        Envía un mensaje por el canal indicado.

        Args:
            channel_id: ID del canal.
            tx_id: ID CAN de transmisión.
            data: Payload a enviar.
            timeout_ms: Timeout en ms.
            extended_id: True para CAN 29-bit.
        """
        assert self.dll is not None
        config = self.channels.get(channel_id)
        if config is None:
            raise J2534Error(
                J2534ReturnCode.ERR_INVALID_CHANNEL_ID,
                f"Canal {channel_id} no registrado",
            )

        msg = PASSTHRU_MSG()
        msg.ProtocolID = int(config.protocol)
        msg.TxFlags = ISO15765_FRAME_PAD | (
            CAN_29BIT_ID if extended_id else 0
        )

        if config.protocol in (J2534Protocol.ISO15765, J2534Protocol.CAN):
            header = tx_id.to_bytes(4, "big")
            payload = header + data
        else:
            payload = data

        if len(payload) > 4128:
            raise J2534Error(
                J2534ReturnCode.ERR_BUFFER_OVERFLOW,
                f"Payload demasiado grande ({len(payload)} bytes)",
            )

        msg.DataSize = len(payload)
        ctypes.memmove(msg.Data, payload, len(payload))

        num = c_ulong(1)
        rc = self.dll.PassThruWriteMsgs(
            c_ulong(channel_id),
            byref(msg),
            byref(num),
            c_ulong(timeout_ms),
        )
        self._check(rc)

    def read_messages(
        self,
        channel_id: int,
        max_messages: int = 1,
        timeout_ms: int = 1000,
    ) -> list[bytes]:
        """
        Lee mensajes entrantes del canal.

        Args:
            channel_id: ID del canal.
            max_messages: Número máximo de mensajes a leer.
            timeout_ms: Timeout en ms.

        Returns:
            Lista de payloads (sin el header CAN).
        """
        assert self.dll is not None
        config = self.channels.get(channel_id)
        if config is None:
            raise J2534Error(
                J2534ReturnCode.ERR_INVALID_CHANNEL_ID,
                f"Canal {channel_id} no registrado",
            )

        MsgArr = PASSTHRU_MSG * max_messages
        msgs = MsgArr()
        num = c_ulong(max_messages)

        rc = self.dll.PassThruReadMsgs(
            c_ulong(channel_id),
            msgs,
            byref(num),
            c_ulong(timeout_ms),
        )

        if rc == J2534ReturnCode.ERR_BUFFER_EMPTY:
            return []
        if rc == J2534ReturnCode.ERR_TIMEOUT and num.value == 0:
            return []
        self._check(rc)

        results: list[bytes] = []
        for i in range(num.value):
            m = msgs[i]
            if m.RxStatus & TX_DONE:
                continue  # Loopback de nuestro propio mensaje
            size = m.DataSize
            raw = bytes(bytearray(m.Data[:size]))
            if config.protocol in (J2534Protocol.ISO15765, J2534Protocol.CAN):
                # El header (4 bytes) es el CAN ID; lo descartamos
                results.append(raw[4:])
            else:
                results.append(raw)
        return results

    # ------------------------------------------------------------------
    # Filtros (necesarios para ISO-TP)
    # ------------------------------------------------------------------

    def start_flow_control_filter(
        self,
        channel_id: int,
        rx_id: int,
        tx_id: int,
        extended: bool = False,
    ) -> int:
        """
        Crea un filtro de flow control para ISO-TP.

        Args:
            channel_id: ID del canal.
            rx_id: ID CAN de recepción esperado.
            tx_id: ID CAN usado para respuestas de flow control.
            extended: True para CAN 29-bit.

        Returns:
            ID del filtro creado.
        """
        assert self.dll is not None
        config = self.channels[channel_id]

        def _mk(id_value: int) -> PASSTHRU_MSG:
            m = PASSTHRU_MSG()
            m.ProtocolID = int(config.protocol)
            m.TxFlags = ISO15765_FRAME_PAD | (CAN_29BIT_ID if extended else 0)
            m.DataSize = 4
            header = id_value.to_bytes(4, "big")
            ctypes.memmove(m.Data, header, 4)
            return m

        mask = _mk(0xFFFFFFFF)
        pattern = _mk(rx_id)
        flow = _mk(tx_id)

        filter_id = c_ulong(0)
        rc = self.dll.PassThruStartMsgFilter(
            c_ulong(channel_id),
            c_ulong(int(J2534FilterType.FLOW_CONTROL_FILTER)),
            byref(mask),
            byref(pattern),
            byref(flow),
            byref(filter_id),
        )
        self._check(rc)
        return filter_id.value

    def stop_filter(self, channel_id: int, filter_id: int) -> None:
        """Elimina un filtro activo."""
        assert self.dll is not None
        rc = self.dll.PassThruStopMsgFilter(
            c_ulong(channel_id), c_ulong(filter_id)
        )
        self._check(rc)

    # ------------------------------------------------------------------
    # Mensajes periódicos
    # ------------------------------------------------------------------

    def start_periodic_message(
        self,
        channel_id: int,
        tx_id: int,
        data: bytes,
        interval_ms: int,
        extended: bool = False,
    ) -> int:
        """
        Inicia un mensaje periódico (p.ej. TesterPresent automático).

        Returns:
            ID del mensaje periódico creado.
        """
        assert self.dll is not None
        config = self.channels[channel_id]
        msg = PASSTHRU_MSG()
        msg.ProtocolID = int(config.protocol)
        msg.TxFlags = ISO15765_FRAME_PAD | (CAN_29BIT_ID if extended else 0)
        payload = tx_id.to_bytes(4, "big") + data
        msg.DataSize = len(payload)
        ctypes.memmove(msg.Data, payload, len(payload))

        msg_id = c_ulong(0)
        rc = self.dll.PassThruStartPeriodicMsg(
            c_ulong(channel_id),
            byref(msg),
            byref(msg_id),
            c_ulong(interval_ms),
        )
        self._check(rc)
        return msg_id.value

    def stop_periodic_message(self, channel_id: int, msg_id: int) -> None:
        """Detiene un mensaje periódico."""
        assert self.dll is not None
        rc = self.dll.PassThruStopPeriodicMsg(
            c_ulong(channel_id), c_ulong(msg_id)
        )
        self._check(rc)

    # ------------------------------------------------------------------
    # IOCTL
    # ------------------------------------------------------------------

    def ioctl(
        self,
        channel_id: int,
        ioctl_id: J2534Ioctl,
        input_ptr: Optional[ctypes.c_void_p] = None,
        output_ptr: Optional[ctypes.c_void_p] = None,
    ) -> None:
        """Ejecuta una llamada IOCTL arbitraria."""
        assert self.dll is not None
        rc = self.dll.PassThruIoctl(
            c_ulong(channel_id),
            c_ulong(int(ioctl_id)),
            input_ptr,
            output_ptr,
        )
        self._check(rc)

    def read_battery_voltage(self) -> float:
        """Lee la tensión de batería en voltios (IOCTL READ_VBATT)."""
        assert self.dll is not None and self.device_id is not None
        voltage_mv = c_ulong(0)
        rc = self.dll.PassThruIoctl(
            self.device_id,
            c_ulong(int(J2534Ioctl.READ_VBATT)),
            None,
            byref(voltage_mv),
        )
        self._check(rc)
        return voltage_mv.value / 1000.0

    def clear_tx_buffer(self, channel_id: int) -> None:
        """Limpia el buffer de transmisión del canal."""
        self.ioctl(channel_id, J2534Ioctl.CLEAR_TX_BUFFER)

    def clear_rx_buffer(self, channel_id: int) -> None:
        """Limpia el buffer de recepción del canal."""
        self.ioctl(channel_id, J2534Ioctl.CLEAR_RX_BUFFER)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "J2534Driver":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
