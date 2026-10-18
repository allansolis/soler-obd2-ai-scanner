"""
security.py — Módulo de Seguridad Automotriz para Scaner Soler Pro.

Capas de protección:
  1. CommandSanitizer    → valida/sanitiza comandos OBD/UDS/AT antes de enviar
  2. CANAnomalyDetector  → detecta flood, replay, entropía anómala en tráfico CAN
  3. SecurityAuditLog    → log inmutable de comandos enviados (diagnóstico forense)
  4. UDSRiskGuard        → requiere confirmación explícita para servicios UDS peligrosos
  5. create_secure_send_fn → envuelve raw_send con todas las capas

Basado en patrones de:
  - mukul975/anthropic-cybersecurity-skills : entropy check, traffic stats
  - OWASP Automotive Top 10                 : command injection, replay attacks
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


# =============================================================================
# SecurityAlert — estructura de alerta de seguridad
# =============================================================================

@dataclass
class SecurityAlert:
    severity: str           # "info" | "warning" | "critical"
    alert_type: str         # "flood" | "replay" | "entropy_anomaly" | "unexpected_id" | "blocked_cmd"
    description: str
    raw_data: str
    timestamp: float = field(default_factory=time.time)

    def __str__(self) -> str:
        t = time.strftime("%H:%M:%S", time.localtime(self.timestamp))
        return f"[{t}] {self.severity.upper()} | {self.alert_type} | {self.description}"


# =============================================================================
# CommandSanitizer
# =============================================================================

class CommandSanitizer:
    """
    Valida y sanitiza comandos OBD/UDS/AT antes de enviarlos al ELM327.
    Previene: command injection, comandos AT destructivos, servicios UDS peligrosos.
    """

    # Regex para hex puro: "XX" o "XX XX XX ..." (bytes separados por espacios)
    _VALID_HEX_CMD = re.compile(r'^[0-9A-Fa-f]{2}(\s[0-9A-Fa-f]{2})*$')

    # Comandos AT válidos: "AT" + opcional espacio + alfanumérico y símbolos seguros
    _VALID_AT_CMD = re.compile(r'^AT\s?[A-Z0-9\s@&+\-?#]{1,20}$', re.IGNORECASE)

    # Comandos AT bloqueados (reset completo / warm start irreversible)
    _BLOCKED_AT: set[str] = {"AT WS", "ATZ", "ATWS", "AT Z", "ATRST", "AT RST", "ATPP FF ON", "ATFI", "ATSI"}

    # Servicios UDS que requieren confirmación explícita (primer byte = service ID)
    _DANGER_SERVICES: dict[int, str] = {
        0x10: "DiagnosticSessionControl — puede cambiar a sesión programadora",
        0x11: "ECUReset — reinicia la ECU en caliente o frío",
        0x27: "SecurityAccess — intento de desbloquear seguridad ECU",
        0x28: "CommunicationControl — puede silenciar comunicaciones CAN",
        0x2E: "WriteDataByIdentifier — escritura de datos en ECU",
        0x34: "RequestDownload — inicio de descarga de firmware",
        0x35: "RequestUpload — inicio de carga desde ECU",
        0x36: "TransferData — transferencia de bloque de datos",
        0x37: "RequestTransferExit — fin de transferencia de datos",
        0x3D: "WriteMemoryByAddress — escritura directa en memoria ECU",
        0x3E: "TesterPresent — mantiene sesión extendida activa",
        0x2F: "InputOutputControlByIdentifier — control de actuadores ECU",
        0x14: "ClearDiagnosticInformation — borra todos los DTCs",
        0x85: "ControlDTCSetting — activa/desactiva el registro de DTCs",
    }

    def validate(self, cmd: str) -> tuple[bool, str]:
        """
        Retorna (is_valid, reason).
        - Verifica que el comando sea hex válido o AT válido.
        - Verifica que no sea un AT bloqueado.
        - Si es UDS de riesgo, retorna (True, "DANGER: ...") como advertencia.
        """
        sanitized = self.sanitize(cmd)
        if not sanitized:
            return False, "Comando vacío"

        upper = sanitized.upper()

        # Detectar intentos de inyección: caracteres peligrosos fuera de hex/AT
        dangerous_chars = set(sanitized) - set("0123456789ABCDEFabcdef ATSPIRHLZWM?@&+-#\r\n")
        if dangerous_chars:
            bad = "".join(sorted(dangerous_chars))
            return False, f"Caracteres no permitidos: {bad!r}"

        # Verificar comandos AT bloqueados
        if upper in {b.upper() for b in self._BLOCKED_AT}:
            return False, f"Comando AT bloqueado (reset destructivo): {upper!r}"

        # Verificar si es comando AT válido
        if upper.startswith("AT"):
            if self._VALID_AT_CMD.match(upper):
                return True, "AT válido"
            return False, f"Formato AT inválido: {upper!r}"

        # Verificar si es hex puro válido
        if self._VALID_HEX_CMD.match(sanitized):
            # Comprobar si es servicio UDS peligroso
            is_danger, danger_reason = self.is_dangerous_uds(sanitized)
            if is_danger:
                return True, f"DANGER: {danger_reason}"
            return True, "Comando hex válido"

        # Ni AT ni hex válido
        return False, f"Formato no reconocido (ni AT ni hex): {sanitized!r}"

    def sanitize(self, cmd: str) -> str:
        """Normaliza el comando: strip, upper, colapsa espacios múltiples."""
        if not cmd:
            return ""
        result = cmd.strip().upper()
        # Colapsar múltiples espacios en uno
        result = re.sub(r'\s+', ' ', result)
        return result

    def is_dangerous_uds(self, cmd: str) -> tuple[bool, str]:
        """True si el primer byte es un servicio UDS de nivel danger."""
        clean = cmd.replace(" ", "").upper()
        if len(clean) < 2:
            return False, ""
        try:
            first_byte = int(clean[:2], 16)
        except ValueError:
            return False, ""
        if first_byte in self._DANGER_SERVICES:
            return True, f"Servicio 0x{first_byte:02X}: {self._DANGER_SERVICES[first_byte]}"
        return False, ""


# =============================================================================
# CANAnomalyDetector
# =============================================================================

class CANAnomalyDetector:
    """
    Detecta anomalías en tráfico CAN:
    - Flood detection: demasiados frames del mismo ID en poco tiempo
    - Replay attack: frames idénticos repetidos
    - Entropy anomaly: respuesta con entropía inusualmente baja
    - Unexpected responder: respuesta de CAN ID inesperado
    """

    def __init__(
        self,
        flood_threshold: int = 50,   # frames/segundo por ID
        entropy_min: float = 1.5,    # entropía mínima esperada
        window_s: float = 5.0,       # ventana de tiempo para flood
    ) -> None:
        self._flood_threshold = flood_threshold
        self._entropy_min = entropy_min
        self._window_s = window_s

        # Historial de timestamps por CAN ID: {can_id: deque[timestamp]}
        self._id_timestamps: dict[int, deque] = {}
        # Historial de frames por CAN ID para replay: {can_id: deque[(data_hex, ts)]}
        self._frame_history: dict[int, deque] = {}
        # Máximo de frames a guardar por ID para replay
        self._replay_window = 200
        self._lock = threading.Lock()

    def feed_frame(self, can_id: int, data_hex: str) -> Optional[SecurityAlert]:
        """
        Procesa un frame CAN y retorna SecurityAlert si detecta anomalía.
        Evalúa flood primero, luego replay.
        """
        now = time.time()
        data_hex_clean = data_hex.replace(" ", "").upper()

        with self._lock:
            # ── Flood detection ───────────────────────────────────────────────
            if can_id not in self._id_timestamps:
                self._id_timestamps[can_id] = deque()
            ts_q = self._id_timestamps[can_id]
            ts_q.append(now)
            # Purgar timestamps fuera de la ventana
            while ts_q and ts_q[0] < now - self._window_s:
                ts_q.popleft()

            # Usar tiempo real transcurrido (no ventana completa) para rate preciso
            if len(ts_q) >= 2:
                elapsed = max(now - ts_q[0], 0.001)  # evitar división por cero
                rate = len(ts_q) / min(elapsed, self._window_s)
            else:
                rate = 0.0
            if rate > self._flood_threshold:
                return SecurityAlert(
                    severity="critical",
                    alert_type="flood",
                    description=(
                        f"CAN ID 0x{can_id:03X}: {rate:.0f} frames/s "
                        f"(umbral={self._flood_threshold})"
                    ),
                    raw_data=f"0x{can_id:03X} {data_hex_clean}",
                )

            # ── Replay detection ──────────────────────────────────────────────
            replay_alert = self._check_replay_locked(can_id, data_hex_clean, now)
            if replay_alert:
                return replay_alert

        return None

    def _check_replay_locked(
        self, can_id: int, data_hex: str, now: float
    ) -> Optional[SecurityAlert]:
        """Versión interna de check_replay (asume lock ya adquirido)."""
        if can_id not in self._frame_history:
            self._frame_history[can_id] = deque(maxlen=self._replay_window)
        history = self._frame_history[can_id]

        # Contar cuántas veces vimos este frame exacto en la ventana
        cutoff = now - self._window_s
        recent_identical = sum(
            1 for (d, t) in history if d == data_hex and t >= cutoff
        )
        history.append((data_hex, now))

        if recent_identical >= 3:
            return SecurityAlert(
                severity="warning",
                alert_type="replay",
                description=(
                    f"CAN ID 0x{can_id:03X}: frame idéntico visto "
                    f"{recent_identical + 1} veces en {self._window_s:.0f}s — "
                    f"posible replay attack"
                ),
                raw_data=f"0x{can_id:03X} {data_hex}",
            )
        return None

    def check_entropy(
        self, response_hex: str, context: str = ""
    ) -> Optional[SecurityAlert]:
        """
        Calcula entropía Shannon del response.
        Si < entropy_min → posible respuesta mock/estática (warning).
        Si = 0           → respuesta constante (critical, salvo "NO DATA").
        Adaptado de mukul975/anthropic-cybersecurity-skills calculate_entropy().
        """
        clean = response_hex.replace(" ", "").upper()

        # Excluir respuestas conocidas de ELM327 que son legítimamente constantes
        if clean in ("NODATA", "UNABLETOCONNECT", "CANERROR", "BUSBUSY", ""):
            return None

        if len(clean) < 2:
            return None

        # Calcular entropía sobre bytes (pares de caracteres hex)
        byte_list = [clean[i:i+2] for i in range(0, len(clean) - 1, 2)]
        if not byte_list:
            return None

        freq = Counter(byte_list)
        length = len(byte_list)
        entropy = -sum(
            (c / length) * math.log2(c / length) for c in freq.values()
        )

        ctx = f" [{context}]" if context else ""
        if entropy == 0.0:
            return SecurityAlert(
                severity="critical",
                alert_type="entropy_anomaly",
                description=(
                    f"Entropía = 0.0{ctx}: respuesta completamente constante — "
                    f"posible mock o datos fabricados"
                ),
                raw_data=response_hex,
            )
        if entropy < self._entropy_min:
            return SecurityAlert(
                severity="warning",
                alert_type="entropy_anomaly",
                description=(
                    f"Entropía baja = {entropy:.3f}{ctx} "
                    f"(mínimo esperado = {self._entropy_min}) — "
                    f"posible respuesta estática o simulada"
                ),
                raw_data=response_hex,
            )
        return None

    def check_replay(
        self, can_id: int, data_hex: str
    ) -> Optional[SecurityAlert]:
        """Detecta si este frame exacto ya fue visto recientemente (replay attack)."""
        now = time.time()
        with self._lock:
            return self._check_replay_locked(can_id, data_hex.replace(" ", "").upper(), now)

    def get_stats(self) -> dict:
        """
        Estadísticas de tráfico por CAN ID.
        Adaptado de compute_traffic_stats del repo mukul975/anthropic-cybersecurity-skills.
        Devuelve: {can_id_hex: {frames_in_window, rate_fps, unique_payloads}}
        """
        now = time.time()
        cutoff = now - self._window_s
        stats: dict = {}

        with self._lock:
            for can_id, ts_q in self._id_timestamps.items():
                recent = [t for t in ts_q if t >= cutoff]
                rate = len(recent) / self._window_s if recent else 0.0
                history = self._frame_history.get(can_id, deque())
                unique = len({d for d, t in history if t >= cutoff})
                stats[f"0x{can_id:03X}"] = {
                    "frames_in_window": len(recent),
                    "rate_fps": round(rate, 2),
                    "unique_payloads": unique,
                }
        return stats


# =============================================================================
# SecurityAuditLog
# =============================================================================

class SecurityAuditLog:
    """
    Log inmutable (thread-safe) de todos los comandos enviados.
    Importante para diagnóstico forense post-incidente.
    """

    def __init__(self, max_entries: int = 10_000) -> None:
        self._entries: list[dict] = []
        self._lock = threading.Lock()
        self._max_entries = max_entries

    def log_command(
        self,
        cmd: str,
        response: str,
        sanitized: bool,
        alert: Optional[SecurityAlert] = None,
    ) -> None:
        """Registra un par comando/respuesta con timestamp."""
        entry: dict = {
            "timestamp": time.time(),
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "command": cmd,
            "response": response[:200],   # Truncar respuestas muy largas
            "sanitized": sanitized,
        }
        if alert:
            entry["alert"] = {
                "severity": alert.severity,
                "alert_type": alert.alert_type,
                "description": alert.description,
            }
        with self._lock:
            if len(self._entries) >= self._max_entries:
                # FIFO: eliminar la entrada más antigua
                self._entries.pop(0)
            self._entries.append(entry)

    def export_json(self, path: Path | str) -> Path:
        """Exporta el log completo a JSON."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            data = list(self._entries)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return out

    def get_alerts(self, severity: str | None = None) -> list[dict]:
        """Retorna entradas con alertas, filtradas por severity si se especifica."""
        with self._lock:
            entries = list(self._entries)
        result = [e for e in entries if "alert" in e]
        if severity:
            result = [e for e in result if e["alert"]["severity"] == severity]
        return result

    def summary(self) -> dict:
        """Resumen: total comandos, alertas por tipo, blocked commands."""
        with self._lock:
            entries = list(self._entries)

        total = len(entries)
        alert_entries = [e for e in entries if "alert" in e]

        alert_by_type: dict[str, int] = Counter(
            e["alert"]["alert_type"] for e in alert_entries
        )  # type: ignore[arg-type]
        alert_by_severity: dict[str, int] = Counter(
            e["alert"]["severity"] for e in alert_entries
        )  # type: ignore[arg-type]

        blocked = sum(
            1 for e in alert_entries
            if e["alert"]["alert_type"] == "blocked_cmd"
        )

        return {
            "total_commands": total,
            "total_alerts": len(alert_entries),
            "blocked_commands": blocked,
            "alerts_by_type": dict(alert_by_type),
            "alerts_by_severity": dict(alert_by_severity),
        }


# =============================================================================
# UDSRiskGuard + UDSSecurityError
# =============================================================================

class UDSSecurityError(Exception):
    """Lanzada cuando se intenta un servicio UDS peligroso sin confirmación."""
    pass


class UDSRiskGuard:
    """
    Intercede antes de enviar servicios UDS de nivel danger.
    Requiere confirmación explícita o lanza UDSSecurityError.
    """

    # Descripción detallada del riesgo por servicio
    _SERVICE_RISKS: dict[int, str] = {
        0x10: (
            "DiagnosticSessionControl puede habilitar modos de programación. "
            "En sesión extendida o de programación, otros servicios destructivos "
            "quedan desbloqueados automáticamente."
        ),
        0x11: (
            "ECUReset reinicia la unidad de control. Un reset en caliente puede "
            "causar pérdida de datos no guardados. Un reset de fábrica puede "
            "borrar adaptaciones aprendidas (ralentí, transmisión, ABS)."
        ),
        0x27: (
            "SecurityAccess intenta desbloquear la ECU usando un seed-key. "
            "Múltiples intentos fallidos pueden activar el lockout de seguridad "
            "y dejar la ECU inaccesible."
        ),
        0x28: (
            "CommunicationControl puede silenciar mensajes CAN normales o de "
            "diagnóstico. Un vehículo con comunicación CAN suprimida puede "
            "tener comportamiento impredecible."
        ),
        0x2E: (
            "WriteDataByIdentifier escribe datos en la ECU. Valores incorrectos "
            "pueden corromper la calibración del motor, el VIN, o datos críticos "
            "de seguridad."
        ),
        0x34: (
            "RequestDownload inicia una secuencia de descarga de firmware. "
            "Flashear firmware incorrecto puede dañar permanentemente la ECU."
        ),
        0x35: (
            "RequestUpload inicia una lectura de memoria de la ECU. "
            "Puede exponer calibraciones propietarias o datos de seguridad."
        ),
        0x36: (
            "TransferData transfiere un bloque de datos durante una operación "
            "de flash. Solo usar dentro de una secuencia 0x34/0x35 controlada."
        ),
        0x37: (
            "RequestTransferExit finaliza una transferencia de flash. "
            "Un exit prematuro puede dejar la ECU en estado parcialmente flasheado."
        ),
        0x3D: (
            "WriteMemoryByAddress escribe directamente en una dirección de memoria "
            "de la ECU. Un valor incorrecto puede corromper código ejecutable "
            "o tablas de calibración críticas."
        ),
        0x3E: (
            "TesterPresent mantiene activa una sesión de diagnóstico extendida. "
            "Mantener la sesión abierta innecesariamente aumenta la superficie "
            "de ataque."
        ),
        0x2F: (
            "InputOutputControlByIdentifier puede activar actuadores directamente "
            "(inyectores, solenoides, etc.) sin la lógica de control normal. "
            "Puede causar daño mecánico o poner en riesgo la seguridad."
        ),
        0x14: (
            "ClearDiagnosticInformation borra TODOS los DTCs almacenados, "
            "datos de freeze frame y readiness monitors. Esta acción no puede "
            "deshacerse."
        ),
        0x85: (
            "ControlDTCSetting puede deshabilitar el registro de fallas. "
            "Un vehículo con DTCs desactivados puede fallar silenciosamente "
            "sin dejar rastro diagnóstico."
        ),
    }

    def __init__(self) -> None:
        self._confirmed: set[int] = set()
        self._lock = threading.Lock()

    def require_confirmation(self, service_id: int, reason: str) -> None:
        """
        Si el servicio no fue confirmado, lanza UDSSecurityError con descripción
        de qué puede hacer ese servicio. El caller debe llamar confirm() primero.
        """
        with self._lock:
            already_confirmed = service_id in self._confirmed

        if not already_confirmed:
            risk_desc = self._SERVICE_RISKS.get(
                service_id,
                "Servicio UDS de alto riesgo sin descripción específica disponible.",
            )
            raise UDSSecurityError(
                f"Servicio UDS 0x{service_id:02X} requiere confirmación explícita.\n"
                f"Razón de validación: {reason}\n"
                f"Riesgo: {risk_desc}\n"
                f"Llama risk_guard.confirm(0x{service_id:02X}) para autorizar."
            )

    def confirm(self, service_id: int, pin: str | None = None) -> None:
        """Marca el servicio como confirmado. pin es opcional (para implementaciones futuras)."""
        with self._lock:
            self._confirmed.add(service_id)

    def is_confirmed(self, service_id: int) -> bool:
        """Retorna True si el servicio fue previamente confirmado."""
        with self._lock:
            return service_id in self._confirmed

    def revoke(self, service_id: int) -> None:
        """Revoca la confirmación de un servicio (útil al cerrar sesión)."""
        with self._lock:
            self._confirmed.discard(service_id)

    def revoke_all(self) -> None:
        """Revoca todas las confirmaciones de la sesión."""
        with self._lock:
            self._confirmed.clear()


# =============================================================================
# create_secure_send_fn — factory de envío seguro
# =============================================================================

def create_secure_send_fn(
    raw_send: Callable[[str], str],
    audit_log: SecurityAuditLog,
    anomaly_detector: CANAnomalyDetector,
    risk_guard: UDSRiskGuard,
    sanitizer: CommandSanitizer,
    on_alert: Optional[Callable[[SecurityAlert], None]] = None,
) -> Callable[[str], str]:
    """
    Envuelve raw_send con todas las capas de seguridad:
    1. sanitize()                 → normaliza formato
    2. validate()                 → verifica que sea hex/AT válido y no bloqueado
    3. is_dangerous_uds()         → llama risk_guard.require_confirmation si aplica
    4. raw_send(cmd)              → ejecuta el envío real
    5. check_entropy(response)    → detecta anomalías en la respuesta
    6. audit_log.log_command()    → registra todo (con o sin alerta)
    7. retorna respuesta
    """

    def _dispatch_alert(alert: SecurityAlert) -> None:
        if on_alert is not None:
            try:
                on_alert(alert)
            except Exception:
                pass  # El callback nunca debe interrumpir el flujo

    def secure_send(cmd: str) -> str:
        # ── Paso 1: sanitize ──────────────────────────────────────────────────
        clean_cmd = sanitizer.sanitize(cmd)

        # ── Paso 2: validar formato ───────────────────────────────────────────
        is_valid, reason = sanitizer.validate(clean_cmd)
        if not is_valid:
            alert = SecurityAlert(
                severity="critical",
                alert_type="blocked_cmd",
                description=f"Comando bloqueado: {reason}",
                raw_data=cmd,
            )
            _dispatch_alert(alert)
            audit_log.log_command(cmd, "BLOCKED", sanitized=True, alert=alert)
            raise ValueError(f"Comando bloqueado por seguridad: {reason}")

        # ── Paso 3: verificar servicios UDS peligrosos ────────────────────────
        is_danger, danger_reason = sanitizer.is_dangerous_uds(clean_cmd)
        if is_danger:
            first_byte_str = clean_cmd.replace(" ", "")[:2]
            try:
                service_id = int(first_byte_str, 16)
            except ValueError:
                service_id = 0
            # Puede lanzar UDSSecurityError si no está confirmado
            risk_guard.require_confirmation(service_id, danger_reason)

        # ── Paso 4: ejecutar envío real ───────────────────────────────────────
        response = raw_send(clean_cmd)

        # ── Paso 5: comprobar entropía de la respuesta ────────────────────────
        entropy_alert: Optional[SecurityAlert] = anomaly_detector.check_entropy(
            response, context=clean_cmd
        )
        if entropy_alert:
            _dispatch_alert(entropy_alert)

        # ── Paso 6: registrar en audit log ────────────────────────────────────
        audit_log.log_command(
            cmd=clean_cmd,
            response=response,
            sanitized=True,
            alert=entropy_alert,
        )

        return response

    return secure_send


# =============================================================================
# Prueba rápida
# =============================================================================

if __name__ == "__main__":
    print("=" * 65)
    print("TEST: CommandSanitizer")
    print("=" * 65)

    s = CommandSanitizer()
    tests = [
        ("01 00",       True,  "OBD mode 1 PID 0"),
        ("22 F1 90",    True,  "UDS ReadDataByIdentifier"),
        ("AT I",        True,  "AT identify"),
        ("AT Z",        False, "AT reset — bloqueado"),
        ("ATZ",         False, "ATZ reset — bloqueado"),
        ("rm -rf /",    False, "injection attempt"),
        ("34 00 44",    True,  "UDS RequestDownload — peligroso pero válido"),
        ("2E F1 90 41", True,  "UDS WriteDataByIdentifier — peligroso"),
        ("03",          True,  "OBD leer DTCs"),
        ("0A",          True,  "OBD DTCs permanentes"),
        ("GG ZZ",       False, "hex inválido"),
        ("",            False, "vacío"),
        ("AT SP 0",     True,  "AT set protocol"),
    ]

    all_ok = True
    for cmd, expected_valid, note in tests:
        valid, reason = s.validate(cmd)
        status = "OK" if valid == expected_valid else "FAIL"
        if status == "FAIL":
            all_ok = False
        print(f"  [{status}] {cmd!r:18} expected={expected_valid} got={valid} | {reason[:50]}")

    print()
    print("=" * 65)
    print("TEST: CANAnomalyDetector — Flood")
    print("=" * 65)

    det = CANAnomalyDetector(flood_threshold=50, window_s=5.0)
    last_alert = None
    # Usar datos variables para evitar que replay dispare antes que flood
    for i in range(60):
        payload = f"41 00 BE {i:02X} A8 13"
        a = det.feed_frame(0x7E8, payload)
        if a:
            last_alert = a
    print(f"  Flood alert: {last_alert}")
    assert last_alert is not None and last_alert.alert_type == "flood", "FAIL: flood no detectado"
    print("  -> OK: flood detectado correctamente")

    print()
    print("=" * 65)
    print("TEST: CANAnomalyDetector — Entropy")
    print("=" * 65)

    det2 = CANAnomalyDetector()
    # Respuesta de entropía cero (todos bytes iguales)
    alert2 = det2.check_entropy("00 00 00 00 00 00 00 00", "test_zeros")
    print(f"  Entropy alert (zeros): {alert2}")
    assert alert2 is not None and alert2.severity == "critical", "FAIL: entropía cero no detectada"

    # Respuesta de entropía baja (pocos bytes distintos)
    alert3 = det2.check_entropy("41 00 41 00 41 00 41 00", "test_low_entropy")
    print(f"  Entropy alert (low):   {alert3}")
    assert alert3 is not None, "FAIL: entropía baja no detectada"

    # Respuesta normal: datos con variedad
    alert4 = det2.check_entropy("41 00 BE 3F A8 13 7E 21", "normal_response")
    print(f"  Entropy alert (normal): {alert4}")
    assert alert4 is None, "FAIL: alerta falsa en respuesta normal"
    print("  -> OK: entropía evaluada correctamente")

    print()
    print("=" * 65)
    print("TEST: SecurityAuditLog")
    print("=" * 65)

    log = SecurityAuditLog()
    log.log_command("01 00", "41 00 BE 3F A8 13", sanitized=True)
    log.log_command("AT Z", "BLOCKED", sanitized=True,
                    alert=SecurityAlert("critical", "blocked_cmd", "ATZ bloqueado", "AT Z"))
    log.log_command("03", "NO DATA", sanitized=True)

    summary = log.summary()
    print(f"  Summary: {summary}")
    assert summary["total_commands"] == 3, "FAIL: conteo total incorrecto"
    assert summary["total_alerts"] == 1, "FAIL: conteo alertas incorrecto"
    alerts = log.get_alerts(severity="critical")
    assert len(alerts) == 1, "FAIL: filtro severity incorrecto"
    print("  -> OK: audit log funciona correctamente")

    print()
    print("=" * 65)
    print("TEST: UDSRiskGuard")
    print("=" * 65)

    guard = UDSRiskGuard()
    # Sin confirmar debe lanzar error
    try:
        guard.require_confirmation(0x34, "RequestDownload sin confirmar")
        print("  FAIL: no lanzó UDSSecurityError")
        all_ok = False
    except UDSSecurityError as e:
        print(f"  OK: UDSSecurityError lanzada correctamente")
        print(f"  Mensaje: {str(e)[:80]}...")

    # Con confirmación no debe lanzar
    guard.confirm(0x34)
    try:
        guard.require_confirmation(0x34, "RequestDownload confirmado")
        print("  OK: servicio confirmado pasa sin error")
    except UDSSecurityError:
        print("  FAIL: lanzó error en servicio confirmado")
        all_ok = False

    print()
    print("=" * 65)
    print("TEST: create_secure_send_fn")
    print("=" * 65)

    audit = SecurityAuditLog()
    detector = CANAnomalyDetector()
    risk_g = UDSRiskGuard()
    san = CommandSanitizer()

    calls: list[str] = []
    def _mock_send(cmd: str) -> str:
        calls.append(cmd)
        return "41 00 BE 3F A8 13"

    alerts_received: list[SecurityAlert] = []
    secure = create_secure_send_fn(
        raw_send=_mock_send,
        audit_log=audit,
        anomaly_detector=detector,
        risk_guard=risk_g,
        sanitizer=san,
        on_alert=lambda a: alerts_received.append(a),
    )

    # Comando normal
    resp = secure("01 00")
    assert resp == "41 00 BE 3F A8 13", "FAIL: respuesta incorrecta"
    assert calls == ["01 00"], "FAIL: comando no llegó a mock"
    print(f"  OK: comando normal enviado → {resp}")

    # Comando bloqueado
    try:
        secure("ATZ")
        print("  FAIL: ATZ no fue bloqueado")
        all_ok = False
    except ValueError as e:
        print(f"  OK: ATZ bloqueado → {e}")

    # Servicio UDS peligroso sin confirmar
    try:
        secure("34 00 44 FF FF FF")
        print("  FAIL: 0x34 sin confirmar no lanzó error")
        all_ok = False
    except UDSSecurityError:
        print("  OK: 0x34 sin confirmar lanzó UDSSecurityError")

    # Servicio UDS peligroso confirmado
    risk_g.confirm(0x34)
    resp2 = secure("34 00 44")
    print(f"  OK: 0x34 confirmado enviado → {resp2}")

    print()
    summary2 = audit.summary()
    print(f"  Audit summary final: {summary2}")

    print()
    print("=" * 65)
    result = "TODOS LOS TESTS PASARON" if all_ok else "ALGUNOS TESTS FALLARON"
    print(f"  RESULTADO: {result}")
    print("=" * 65)
