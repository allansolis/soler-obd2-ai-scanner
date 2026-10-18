"""
ELM327 Mock Server — emulador offline de ECU para tests.

Basado en patrones de Ircama/ELM327-emulator (688★, MIT).
Simula una ECU que responde a comandos AT y solicitudes UDS/OBD.

Uso:
    mock = MockELM327()
    mock.add_uds_response(0x7E0, bytes([0x22, 0xF1, 0x90]), b"1HGCM82633A004352")
    elm = mock.as_elm327_protocol()
    client = UDSClient(elm)
"""
from __future__ import annotations

import re
import time
from typing import Callable, Optional


# ── Tabla de respuestas AT ────────────────────────────────────────────────────

_AT_RESPONSES: dict[str, str] = {
    "ATZ":      "ELM327 v1.5",
    "ATE0":     "OK",
    "ATL0":     "OK",
    "ATS0":     "OK",
    "ATH0":     "OK",
    "ATH1":     "OK",
    "ATD0":     "OK",
    "ATSP0":    "OK",
    "ATSP6":    "OK",
    "ATAT1":    "OK",
    "ATST19":   "OK",
    "ATDP":     "ISO 15765-4 (CAN 11/500)",
    "ATDPN":    "6",
    "ATRV":     "12.1V",
    "ATIGN":    "ON",
    "ATAL":     "OK",
    "ATMA":     "STOPPED",
    "ATFCSM1":  "OK",
    "ATFCSM 1": "OK",
}

_AT_PREFIX_RESPONSES: dict[str, str] = {
    "ATSH":   "OK",
    "ATFCSH": "OK",
    "ATFCSD": "OK",
    "ATCF":   "OK",
    "ATCM":   "OK",
    "ATCP":   "OK",
    "ATSR":   "OK",
    "ATTA":   "OK",
    "ATIB":   "OK",
    "ATIF":   "OK",
    "ATST":   "OK",
}


class MockECU:
    """Simula una ECU con respuestas UDS configurables."""

    def __init__(self, tx_id: int = 0x7E8, name: str = "ECU"):
        self.tx_id = tx_id
        self.name = name
        self._responses: dict[bytes, bytes] = {}
        self._handlers: list[tuple[Callable[[bytes], bool], Callable[[bytes], bytes]]] = []
        self._dtcs: list[str] = []
        self._vin: str = "1HGCM82633A004352"
        self._session = 0x01
        self._security_level: Optional[int] = None
        self._security_seed = b"\x12\x34\x56\x78"

    def add_response(self, request: bytes, response: bytes) -> "MockECU":
        self._responses[request] = response
        return self

    def add_handler(
        self,
        matcher: Callable[[bytes], bool],
        handler: Callable[[bytes], bytes],
    ) -> "MockECU":
        self._handlers.append((matcher, handler))
        return self

    def set_vin(self, vin: str) -> "MockECU":
        self._vin = vin
        return self

    def set_dtcs(self, dtcs: list[str]) -> "MockECU":
        self._dtcs = dtcs
        return self

    def respond(self, request_bytes: bytes) -> Optional[bytes]:
        if not request_bytes:
            return None

        sid = request_bytes[0]

        # 1. Búsqueda exacta en tabla
        if request_bytes in self._responses:
            return self._responses[request_bytes]

        # 2. Handlers dinámicos
        for matcher, handler in self._handlers:
            if matcher(request_bytes):
                return handler(request_bytes)

        # 3. Servicios UDS genéricos
        return self._handle_generic(sid, request_bytes)

    def _handle_generic(self, sid: int, req: bytes) -> Optional[bytes]:
        if sid == 0x10:  # DiagnosticSessionControl
            if len(req) >= 2:
                self._session = req[1]
                return bytes([0x50, req[1], 0x00, 0x32, 0x01, 0xF4])
            return bytes([0x7F, 0x10, 0x13])

        if sid == 0x3E:  # TesterPresent
            return bytes([0x7E, 0x00])

        if sid == 0x11:  # ECUReset
            reset_type = req[1] if len(req) > 1 else 0x01
            return bytes([0x51, reset_type])

        if sid == 0x22:  # ReadDataByIdentifier
            return self._handle_rdbi(req)

        if sid == 0x27:  # SecurityAccess
            return self._handle_security_access(req)

        if sid == 0x19:  # ReadDTCInformation
            return self._handle_read_dtc(req)

        if sid == 0x14:  # ClearDiagnosticInformation
            return bytes([0x54])

        if sid == 0x31:  # RoutineControl
            if len(req) >= 4:
                return bytes([0x71, req[1], req[2], req[3], 0x00])
            return bytes([0x7F, 0x31, 0x13])

        # Servicio no soportado
        return bytes([0x7F, sid, 0x11])

    def _handle_rdbi(self, req: bytes) -> bytes:
        if len(req) < 3:
            return bytes([0x7F, 0x22, 0x13])
        did = (req[1] << 8) | req[2]

        if did == 0xF190:  # VIN
            vin_bytes = self._vin.encode("ascii")
            return bytes([0x62, 0xF1, 0x90]) + vin_bytes

        if did == 0xF187:  # ECU part number
            return bytes([0x62, 0xF1, 0x87]) + b"12345-67890-A"

        if did == 0xF189:  # SW version
            return bytes([0x62, 0xF1, 0x89]) + b"SW_1.2.3"

        if did == 0xF191:  # HW version
            return bytes([0x62, 0xF1, 0x91]) + b"HW_1.0"

        if did == 0xF18C:  # Serial
            return bytes([0x62, 0xF1, 0x8C]) + b"SN_MOCK001"

        # DID no disponible
        return bytes([0x7F, 0x22, 0x31])

    def _handle_security_access(self, req: bytes) -> bytes:
        if len(req) < 2:
            return bytes([0x7F, 0x27, 0x13])

        sub = req[1]
        if sub % 2 == 1:  # seed request (odd)
            return bytes([0x67, sub]) + self._security_seed

        # key send (even)
        expected_key = bytes([b ^ 0xFF for b in self._security_seed])
        if len(req) >= 2 + len(expected_key):
            received_key = req[2:2 + len(expected_key)]
            if received_key == expected_key:
                self._security_level = sub - 1
                return bytes([0x67, sub])
        return bytes([0x7F, 0x27, 0x35])  # invalidKey

    def _handle_read_dtc(self, req: bytes) -> bytes:
        if len(req) >= 2 and req[1] == 0x02:  # reportDTCByStatusMask
            result = bytes([0x59, 0x02, 0xFF])  # DTCStatusAvailabilityMask
            for dtc_str in self._dtcs:
                # P0300 → 0x00, 0x03, 0x00
                letter = dtc_str[0].upper()
                prefix = {"P": 0, "C": 1, "B": 2, "U": 3}.get(letter, 0)
                try:
                    num = int(dtc_str[1:], 16)
                    high = (prefix << 6) | ((num >> 8) & 0x3F)
                    low  = num & 0xFF
                    result += bytes([high, low, 0x00, 0x29])
                except ValueError:
                    continue
            return result
        return bytes([0x7F, 0x19, 0x12])


class MockELM327Protocol:
    """
    Protocolo ELM327 mock — implementa la misma interfaz que ELM327Protocol
    pero responde desde ECUs simuladas sin hardware.
    """

    def __init__(self) -> None:
        self._ecus: dict[int, MockECU] = {}
        self._header: int = 0x7E0   # TX ID actual
        self._fc_header: Optional[int] = None
        self._connected = False
        self.port: str = "MOCK"
        self._log: list[str] = []

    def add_ecu(self, ecu: MockECU) -> "MockELM327Protocol":
        rx_id = ecu.tx_id  # La ECU responde desde su tx_id
        self._ecus[rx_id] = ecu
        return self

    def connect(self, port: str = "MOCK", baudrate: int = 38400) -> bool:
        self.port = port
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def send_command(self, command: str, timeout: float = 2.0) -> str:
        cmd = command.strip().upper()
        self._log.append(f">> {cmd}")

        # Comando vacío
        if not cmd:
            return ""

        # Comandos AT
        if cmd.startswith("AT"):
            resp = self._handle_at(cmd)
            self._log.append(f"<< {resp}")
            return resp

        # Solicitud OBD/UDS en hex
        tokens = [t for t in cmd.split() if re.match(r'^[0-9A-F]{2}$', t)]
        if tokens:
            try:
                payload = bytes(int(t, 16) for t in tokens)
            except ValueError:
                return "NO DATA"

            response = self._dispatch_uds(payload)
            if response is None:
                return "NO DATA"

            # Formato: bytes separados por espacio, con header si ATH1
            rx_id = self._get_rx_id_for(self._header)
            # No incluir el byte de longitud CAN en la cadena — send_receive lo trataría como dato
            resp_str = f"{rx_id:03X} " + " ".join(f"{b:02X}" for b in response)
            self._log.append(f"<< {resp_str}")
            return resp_str

        return "?"

    def _handle_at(self, cmd: str) -> str:
        if cmd in _AT_RESPONSES:
            return _AT_RESPONSES[cmd]

        # Prefijos con argumentos
        for prefix, resp in _AT_PREFIX_RESPONSES.items():
            if cmd.startswith(prefix):
                # Extraer dirección para ATSH
                if prefix == "ATSH":
                    try:
                        addr_str = cmd[4:].replace(" ", "")
                        self._header = int(addr_str, 16)
                    except ValueError:
                        pass
                return resp

        return "OK"

    def _dispatch_uds(self, payload: bytes) -> Optional[bytes]:
        """Enruta la solicitud UDS a la ECU correcta según el TX header actual."""
        rx_id = self._get_rx_id_for(self._header)
        ecu = self._ecus.get(rx_id)
        if ecu is None:
            # Si solo hay una ECU, usarla por defecto
            if len(self._ecus) == 1:
                ecu = next(iter(self._ecus.values()))
            else:
                return None
        return ecu.respond(payload)

    def _get_rx_id_for(self, tx_id: int) -> int:
        """Mapeo estándar: 0x7E0 → 0x7E8, 0x7E1 → 0x7E9, etc."""
        if 0x7E0 <= tx_id <= 0x7E7:
            return tx_id + 8
        return tx_id + 8

    @property
    def command_log(self) -> list[str]:
        return list(self._log)

    def clear_log(self) -> None:
        self._log.clear()


def make_standard_mock(vin: str = "TEST12345678901234", dtcs: Optional[list[str]] = None) -> MockELM327Protocol:
    """
    Crea un mock preconfigurado con una ECU estándar.

    Útil para tests básicos sin configuración manual.
    """
    mock = MockELM327Protocol()
    ecu = MockECU(tx_id=0x7E8, name="ENGINE_ECU")
    ecu.set_vin(vin)
    if dtcs:
        ecu.set_dtcs(dtcs)
    mock.add_ecu(ecu)
    mock.connect("MOCK")
    return mock
