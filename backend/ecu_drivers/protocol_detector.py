"""
Protocol Detector - Auto-detección del protocolo de diagnóstico soportado.

Intenta secuencialmente:
  1. UDS (ISO 14229 sobre ISO-TP CAN, 11-bit y 29-bit)
  2. KWP2000 (ISO 14230-3 sobre CAN)
  3. KWP2000 K-line (ISO 14230-1, iniciación 5-baud o fast-init)
  4. ISO 9141-2 (K-line legacy)

Devuelve el primer protocolo que responda correctamente a un probe mínimo
(TesterPresent o StartCommunication).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .base_driver import (
    BaseECUDriver,
    ECUDriverError,
    NegativeResponseError,
    TimeoutError as ECUTimeoutError,
)

logger = logging.getLogger(__name__)


class ProtocolType(Enum):
    """Protocolos detectables."""
    UDS_CAN_11BIT = "UDS (ISO 14229) - CAN 11-bit"
    UDS_CAN_29BIT = "UDS (ISO 14229) - CAN 29-bit"
    KWP2000_CAN = "KWP2000 (ISO 14230) - CAN"
    KWP2000_KLINE = "KWP2000 (ISO 14230) - K-line"
    ISO9141 = "ISO 9141-2 - K-line"
    J1850_PWM = "SAE J1850 PWM"
    J1850_VPW = "SAE J1850 VPW"
    UNKNOWN = "Desconocido"


@dataclass
class DetectedProtocol:
    """Resultado de la detección."""
    protocol: ProtocolType = ProtocolType.UNKNOWN
    baud_rate: int = 500000
    tx_id: int = 0x7E0
    rx_id: int = 0x7E8
    extended_id: bool = False
    driver_class: Optional[str] = None
    detected: bool = False
    probe_log: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol.value,
            "baud_rate": self.baud_rate,
            "tx_id": f"0x{self.tx_id:X}",
            "rx_id": f"0x{self.rx_id:X}",
            "extended_id": self.extended_id,
            "driver_class": self.driver_class,
            "detected": self.detected,
            "probe_log": self.probe_log,
        }


# IDs estándar a sondear
STANDARD_CAN_IDS_11BIT: list[tuple[int, int]] = [
    (0x7E0, 0x7E8),   # ECM
    (0x7E1, 0x7E9),   # TCM
    (0x7DF, 0x7E8),   # OBD-II functional broadcast
    (0x7E2, 0x7EA),
    (0x7E3, 0x7EB),
    (0x7E4, 0x7EC),
    (0x7E5, 0x7ED),
]

STANDARD_CAN_IDS_29BIT: list[tuple[int, int]] = [
    (0x18DA10F1, 0x18DAF110),  # Dirección ECM (ISO 15765-2 ext.)
    (0x18DB33F1, 0x18DAF110),  # Broadcast funcional
    (0x18DA18F1, 0x18DAF118),
]


class ProtocolDetector:
    """
    Detecta el protocolo y la configuración de direcciones de la ECU.

    Uso:
        detector = ProtocolDetector(transport_factory)
        result = await detector.detect()
        print(result.protocol, result.tx_id, result.rx_id)
    """

    def __init__(
        self,
        transport_factory,
        timeout: float = 1.0,
        try_kline: bool = False,
    ):
        """
        Args:
            transport_factory: Callable(protocol_type, tx_id, rx_id, extended)
                que devuelve un transport configurado.
            timeout: Timeout de cada sonda individual.
            try_kline: Si True, intentará K-line además de CAN.
        """
        self.transport_factory = transport_factory
        self.timeout = timeout
        self.try_kline = try_kline
        self._log = logging.getLogger(f"{__name__}.ProtocolDetector")

    async def detect(self) -> DetectedProtocol:
        """Ejecuta la cadena de detección y devuelve el primer match."""
        result = DetectedProtocol()

        for (tx, rx) in STANDARD_CAN_IDS_11BIT:
            if await self._probe_uds(tx, rx, extended=False, result=result):
                return result
        for (tx, rx) in STANDARD_CAN_IDS_29BIT:
            if await self._probe_uds(tx, rx, extended=True, result=result):
                return result
        for (tx, rx) in STANDARD_CAN_IDS_11BIT:
            if await self._probe_kwp2000_can(tx, rx, result=result):
                return result

        if self.try_kline:
            if await self._probe_kwp2000_kline(result):
                return result
            if await self._probe_iso9141(result):
                return result

        result.detected = False
        result.protocol = ProtocolType.UNKNOWN
        result.probe_log.append("Ningún protocolo respondió al sondeo")
        return result

    # ------------------------------------------------------------------
    # Sondas
    # ------------------------------------------------------------------

    async def _probe_uds(
        self,
        tx: int,
        rx: int,
        extended: bool,
        result: DetectedProtocol,
    ) -> bool:
        """Envía TesterPresent UDS y espera respuesta positiva."""
        from .uds_driver import UDSConfig, UDSDriver
        try:
            transport = self.transport_factory(
                ProtocolType.UDS_CAN_29BIT if extended else ProtocolType.UDS_CAN_11BIT,
                tx, rx, extended,
            )
        except Exception as exc:
            result.probe_log.append(f"UDS tx=0x{tx:X}: transport error ({exc})")
            return False

        cfg = UDSConfig(tx_id=tx, rx_id=rx, extended_id=extended)
        driver = UDSDriver(transport, cfg)
        try:
            await driver.transport.open()
            # Enviar TesterPresent con subfunción 0x00
            await driver._request(
                0x3E, bytes([0x00]), expect_response=True, timeout=self.timeout
            )
            result.protocol = (
                ProtocolType.UDS_CAN_29BIT if extended else ProtocolType.UDS_CAN_11BIT
            )
            result.tx_id = tx
            result.rx_id = rx
            result.extended_id = extended
            result.driver_class = "UDSDriver"
            result.detected = True
            result.probe_log.append(
                f"UDS OK tx=0x{tx:X} rx=0x{rx:X} ext={extended}"
            )
            return True
        except (ECUTimeoutError, NegativeResponseError, ECUDriverError) as exc:
            result.probe_log.append(f"UDS tx=0x{tx:X}: {exc}")
            return False
        finally:
            try:
                await driver.transport.close()
            except Exception:
                pass

    async def _probe_kwp2000_can(
        self, tx: int, rx: int, result: DetectedProtocol
    ) -> bool:
        """Sondea KWP2000 sobre CAN."""
        from .kwp2000_driver import KWP2000Driver
        try:
            transport = self.transport_factory(
                ProtocolType.KWP2000_CAN, tx, rx, False
            )
        except Exception as exc:
            result.probe_log.append(
                f"KWP2000 CAN tx=0x{tx:X}: transport error ({exc})"
            )
            return False

        driver = KWP2000Driver(transport, ecu_address=tx, response_address=rx)
        try:
            await driver.transport.open()
            await driver._send_request(
                bytes([0x3E, 0x01]),
                expect_response=True,
                timeout=self.timeout,
            )
            result.protocol = ProtocolType.KWP2000_CAN
            result.tx_id = tx
            result.rx_id = rx
            result.extended_id = False
            result.driver_class = "KWP2000Driver"
            result.detected = True
            result.probe_log.append(f"KWP2000/CAN OK tx=0x{tx:X}")
            return True
        except (ECUTimeoutError, NegativeResponseError, ECUDriverError) as exc:
            result.probe_log.append(f"KWP2000 CAN tx=0x{tx:X}: {exc}")
            return False
        finally:
            try:
                await driver.transport.close()
            except Exception:
                pass

    async def _probe_kwp2000_kline(
        self, result: DetectedProtocol
    ) -> bool:
        """Sondea KWP2000 sobre K-line con fast-init."""
        try:
            transport = self.transport_factory(
                ProtocolType.KWP2000_KLINE, 0x00, 0x00, False
            )
        except Exception as exc:
            result.probe_log.append(f"KWP2000 K-line: transport error ({exc})")
            return False

        try:
            await transport.open()
            # StartCommunication
            await transport.send(bytes([0x81]))
            resp = await transport.recv(self.timeout)
            if resp and resp[0] == 0xC1:
                result.protocol = ProtocolType.KWP2000_KLINE
                result.baud_rate = 10400
                result.driver_class = "KWP2000Driver"
                result.detected = True
                result.probe_log.append("KWP2000/K-line OK")
                return True
        except Exception as exc:
            result.probe_log.append(f"KWP2000 K-line: {exc}")
        finally:
            try:
                await transport.close()
            except Exception:
                pass
        return False

    async def _probe_iso9141(self, result: DetectedProtocol) -> bool:
        """Sondea ISO 9141-2 con init 5-baud."""
        try:
            transport = self.transport_factory(
                ProtocolType.ISO9141, 0x00, 0x00, False
            )
        except Exception as exc:
            result.probe_log.append(f"ISO9141: transport error ({exc})")
            return False

        try:
            await transport.open()
            await transport.send(bytes([0x01, 0x00]))  # Mode 01 PID 00
            resp = await transport.recv(self.timeout)
            if resp:
                result.protocol = ProtocolType.ISO9141
                result.baud_rate = 10400
                result.driver_class = "OBDReadDriver"
                result.detected = True
                result.probe_log.append("ISO 9141-2 OK")
                return True
        except Exception as exc:
            result.probe_log.append(f"ISO9141: {exc}")
        finally:
            try:
                await transport.close()
            except Exception:
                pass
        return False
