"""
Resets de servicio y adaptaciones de ECU — Scaner Soler Pro.

Cubre:
  - Resets OBD-II estándar (Mode 04, Mode 08)
  - Resets propietarios UDS / KWP2000 / ISO 9141-2
  - Adaptaciones y calibraciones de actuadores

Fuentes de referencia:
  - ISO 15031-5 (SAE J1979): Modos 04 y 08
  - ISO 14229-1 (UDS): servicios 0x27, 0x2E, 0x31, 0x85, 0x3E
  - ISO 14230-3 (KWP2000): servicios propietarios de aceite/DPF/batería
  - Bosch EDC17 / MED17 service manuals (DPF, adaptaciones inyectores)
"""
from __future__ import annotations

import time
from typing import Any

from ..comm.elm327 import ELM327Protocol

# ---------------------------------------------------------------------------
# Catálogo completo de resets disponibles
# ---------------------------------------------------------------------------
AVAILABLE_RESETS: list[dict] = [
    {
        "id": "oil_service",
        "name": "Reset intervalo aceite / servicio de aceite",
        "standard": False,
        "protocol": "KWP2000|UDS",
        "obd_mode": None,
        "note": "Propietario por fabricante. Requiere acceso KWP2000 (0x3E) o UDS (0x31 0x03).",
    },
    {
        "id": "brake_service",
        "name": "Reset servicio de frenos",
        "standard": False,
        "protocol": "KWP2000|UDS",
        "obd_mode": None,
        "note": "Propietario. En VAG: VCDS coding. En BMW: acceso UDS 0x31.",
    },
    {
        "id": "battery_registration",
        "name": "Registro/adaptación de batería",
        "standard": False,
        "protocol": "UDS",
        "obd_mode": None,
        "note": "BMW/VAG/Mercedes requieren registrar capacidad Ah vía UDS 0x2E.",
    },
    {
        "id": "throttle_adaptation",
        "name": "Reset adaptación mariposa (throttle body reset)",
        "standard": False,
        "protocol": "KWP2000|UDS|ISO9141",
        "obd_mode": None,
        "note": "En muchos vehículos es suficiente borrar DTCs (Mode 04) y desconectar batería.",
    },
    {
        "id": "dpf_counter",
        "name": "Reset contador de regeneraciones DPF",
        "standard": False,
        "protocol": "UDS",
        "obd_mode": None,
        "note": "Bosch EDC17: UDS 0x2E con DID 0xF1xx o 0xA0xx según mapa del proveedor.",
    },
    {
        "id": "steering_angle",
        "name": "Calibración / reset sensor ángulo de dirección (SAS)",
        "standard": False,
        "protocol": "UDS|ISO15765",
        "obd_mode": None,
        "note": "Requiere UDS 0x31 01 (RoutineControl startRoutine) con routine ID específico.",
    },
    {
        "id": "tpms",
        "name": "Reset / reinicialización TPMS",
        "standard": False,
        "protocol": "UDS|ISO15765",
        "obd_mode": None,
        "note": "TPMS learning: UDS 0x31 para iniciar el ciclo de reaprendizaje.",
    },
    {
        "id": "clear_dtcs",
        "name": "Borrar DTCs y datos de diagnóstico (Mode 04)",
        "standard": True,
        "protocol": "OBD-II Mode 04",
        "obd_mode": 0x04,
        "note": "Estándar SAE J1979. Compatible con todos los vehículos OBD-II (post-2001 EU).",
    },
    {
        "id": "fuel_pump_actuator",
        "name": "Activar bomba de combustible (actuador Mode 08)",
        "standard": True,
        "protocol": "OBD-II Mode 08",
        "obd_mode": 0x08,
        "note": "Mode 08 PID 0x01 (bomba combustible). Soporte variable según fabricante.",
    },
    {
        "id": "fan_actuator",
        "name": "Activar ventilador (actuador Mode 08)",
        "standard": True,
        "protocol": "OBD-II Mode 08",
        "obd_mode": 0x08,
        "note": "Mode 08 PID 0x0B (ventilador). Soporte variable según fabricante.",
    },
    {
        "id": "throttle_body_calibration",
        "name": "Calibración mariposa electrónica (TPS zero-point)",
        "standard": False,
        "protocol": "UDS|KWP2000",
        "obd_mode": None,
        "note": "UDS 0x31 startRoutine con ID de calibración. Variante KWP2000 0x30.",
    },
    {
        "id": "injector_corrections",
        "name": "Reset correcciones de inyectores (IQ / C2I)",
        "standard": False,
        "protocol": "UDS",
        "obd_mode": None,
        "note": "Bosch EDC: UDS 0x2E con DID de correcciones IQ. Varía entre EDC15/16/17.",
    },
    {
        "id": "idle_speed",
        "name": "Programar velocidad de ralentí objetivo",
        "standard": False,
        "protocol": "UDS|KWP2000",
        "obd_mode": None,
        "note": "UDS 0x2E WriteDataByIdentifier con DID de idle target RPM.",
    },
]


# ---------------------------------------------------------------------------
# Respuesta canónica para resets que requieren extensión propietaria
# ---------------------------------------------------------------------------
def _requires_extension(protocol: str, command_hex: str, note: str = "") -> dict:
    return {
        "status": "requires_obd_extension",
        "protocol": protocol,
        "command_hex": command_hex,
        "note": note,
    }


# ---------------------------------------------------------------------------
# Clase principal
# ---------------------------------------------------------------------------
class ServiceResetManager:
    """
    Gestiona resets de servicio, adaptaciones y activaciones de actuadores.

    Parámetros
    ----------
    elm : ELM327Protocol
        Instancia ya inicializada y conectada al adaptador ELM327.
    """

    def __init__(self, elm: ELM327Protocol = None, backend=None) -> None:
        self._elm = elm or backend

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _send_raw(self, cmd: str, delay: float = 0.3) -> str:
        """Envía un comando AT/OBD al ELM327 y devuelve la respuesta limpia."""
        if self._elm is None:
            return ""
        send_fn = getattr(self._elm, 'send_command', None) or getattr(self._elm, '_send_command', None)
        if send_fn is None:
            return ""
        resp = send_fn(cmd)
        time.sleep(delay)
        return (resp or "").strip()

    def _obd_raw(self, hex_cmd: str, delay: float = 0.4) -> str:
        """
        Envía un comando OBD en hexadecimal (p. ej. '04', '0801').
        Devuelve la respuesta bruta del ELM.
        """
        return self._send_raw(hex_cmd, delay)

    def _is_positive_response(self, raw: str) -> bool:
        """
        Heurística básica: respuesta positiva si no contiene
        ERROR / NO DATA / UNABLE / ? y no está vacía.
        """
        raw_up = raw.upper()
        if not raw_up:
            return False
        negative_tokens = ("ERROR", "NO DATA", "UNABLE", "STOPPED", "?")
        return not any(tok in raw_up for tok in negative_tokens)

    # ------------------------------------------------------------------
    # Resets de mantenimiento
    # ------------------------------------------------------------------

    def reset_oil_service(self) -> dict:
        """
        Reset del indicador de servicio de aceite.

        Protocolo propietario — NO existe comando OBD-II estándar.

        Implementación real por fabricante:
          - VAG (KWP1281 / KWP2000):
              Bloque 0x2A WriteAdaptation, canal 63 (Service Reminder)
              Frame hex: [len] [counter] 2A [canal 0x3F] [valor 0x00] [checksum]
          - BMW (UDS ISO 14229):
              0x31 01 [RoutineID 0xF040]   → startRoutine "CBS Oil reset"
          - Renault (CAN ISO 15765):
              0x04 (borrar DTCs) + CAN PID propietario 0x222701 = 0x00

        Para ejecutar en producción necesitas:
          1. Sesión de diagnóstico extendida: UDS 0x10 03
          2. SecurityAccess: UDS 0x27 01 / 0x27 02 (seed-key)
          3. RoutineControl o WriteDataByIdentifier con DID del fabricante
        """
        return _requires_extension(
            protocol="KWP2000|UDS",
            command_hex="31 01 F0 40",  # UDS RoutineControl startRoutine "Oil CBS" (BMW ejemplo)
            note=(
                "VAG KWP2000: bloque 0x2A canal 0x3F valor 0x00.  "
                "BMW UDS: 0x31 01 F040.  "
                "Renault CAN: 0x22 27 01 luego 0x2E 27 01 00."
            ),
        )

    def reset_brake_service(self) -> dict:
        """
        Reset del indicador de servicio de frenos.

        Propietario — no existe PID OBD estándar para esto.

        BMW (UDS): 0x31 01 [RoutineID 0xF041]  → CBS Brake reset
        VAG: canal de adaptación 64 vía KWP2000 0x2A
        Mercedes: acceso propietario vía XENTRY (UDS extendido)
        """
        return _requires_extension(
            protocol="KWP2000|UDS",
            command_hex="31 01 F0 41",  # UDS startRoutine CBS Brake (BMW)
            note=(
                "BMW UDS: 0x31 01 F041.  "
                "VAG KWP2000: 0x2A canal 0x40 valor 0x00.  "
                "Requiere sesión extendida (0x10 03) y SecurityAccess."
            ),
        )

    def reset_battery_registration(self, capacity_ah: int = 70) -> dict:
        """
        Registra una batería nueva con su capacidad en Ah.

        Propietario BMW / VAG / Mercedes — UDS WriteDataByIdentifier.

        BMW (UDS ISO 14229):
          DID 0xF1A7 = "Battery Capacity" (1 byte = capacidad en pasos de 5 Ah)
          Secuencia:
            0x10 03          → DiagnosticSessionControl extendedDiagnosticSession
            0x27 01          → SecurityAccess requestSeed
            0x27 02 [key]    → SecurityAccess sendKey
            0x2E F1 A7 [val] → WriteDataByIdentifier DID=0xF1A7, value=capacity_ah//5

        VAG (UDS/KWP2000):
          DID 0x0600 (adaptación batería)
          Canal 0x55 = capacidad, Canal 0x56 = tipo (AGM/EFB/etc.)

        Parámetros
        ----------
        capacity_ah : int
            Capacidad nominal de la batería en amperios-hora (default 70 Ah).
        """
        encoded = capacity_ah // 5  # BMW: unidad = 5 Ah
        did_bytes = f"F1 A7 {encoded:02X}"
        return _requires_extension(
            protocol="UDS",
            command_hex=f"2E {did_bytes}",  # WriteDataByIdentifier
            note=(
                f"BMW UDS: 0x10 03 → 0x27 01/02 (seed-key) → 0x2E F1A7 {encoded:02X} "
                f"(={capacity_ah} Ah en pasos de 5 Ah).  "
                "VAG: KWP2000 0x2A canal 0x55."
            ),
        )

    def reset_throttle_adaptation(self) -> dict:
        """
        Reset de la adaptación de la mariposa electrónica.

        Dos vías posibles:

        1. OBD-II básico (Mode 04 + reconexión batería):
           Borrar DTCs limpia las adaptaciones en muchas ECUs.
           Luego se realiza el procedimiento de aprendizaje con clave encendida.

        2. UDS propietario:
           VAG: RoutineControl 0x31 01 [ID de calibración 0x0000 o similar]
           Toyota: escáner específico (procedimiento "Throttle Valve Closed Position")

        Intenta primero vía Mode 04; si falla, devuelve la ruta propietaria.
        """
        # Intento estándar: Mode 04 borra las adaptaciones en muchas ECUs
        raw = self._obd_raw("04")
        if self._is_positive_response(raw):
            return {"status": "ok", "method": "Mode04_clear", "raw": raw}

        return _requires_extension(
            protocol="UDS|KWP2000",
            command_hex="31 01 00 00",  # UDS RoutineControl startRoutine (ID varía)
            note=(
                "Mode 04 no respondió. "
                "VAG: 0x31 01 0000 o procedimiento manual con llave (KOEO 60 s). "
                "Toyota: tester específico con secuencia DTC-clear + ciclo de calentamiento."
            ),
        )

    def reset_dpf_counter(self) -> dict:
        """
        Reset del contador de regeneraciones y cenizas del DPF.

        Propietario — Bosch EDC15 / EDC16 / EDC17 / Delphi DCM:

        Bosch EDC17 (UDS):
          DID 0xA001 = "DPF Ash Load" (valor normalizado 0x00 = limpio)
          DID 0xA002 = "DPF Soot Load"
          DID 0xF155 = "Regeneration Counter"
          Secuencia completa:
            0x10 03          → extendedSession
            0x27 01/02       → SecurityAccess
            0x2E A0 01 00    → WriteDataByIdentifier Ash=0
            0x2E A0 02 00    → WriteDataByIdentifier Soot=0
            0x2E F1 55 00 00 → WriteDataByIdentifier RegenCounter=0

        Delphi DCM3.5:
          KWP2000 0x3D (WriteMemoryByAddress) con dirección de mapa específica

        ADVERTENCIA: Resetear el contador de cenizas sin limpiar físicamente
        el DPF puede dañar la ECU. Solo hacerlo tras limpieza mecánica validada.
        """
        return _requires_extension(
            protocol="UDS",
            command_hex="2E A0 01 00",  # WriteDataByIdentifier DID=0xA001, value=0x00
            note=(
                "Bosch EDC17 UDS: 0x10 03 → 0x27 01/02 → "
                "0x2E A001 00 (ash) + 0x2E A002 00 (soot) + 0x2E F155 0000 (counter).  "
                "Delphi DCM: KWP2000 0x3D con dirección específica del mapa.  "
                "¡Solo resetear tras limpieza física del DPF!"
            ),
        )

    def reset_steering_angle(self) -> dict:
        """
        Calibración / reset del sensor de ángulo de dirección (SAS).

        Propietario — requiere RoutineControl UDS con el vehículo en
        posición recto y ruedas centradas.

        VAG (UDS ISO 15765):
          0x31 01 06 AD   → startRoutine "SAS Calibration"
        BMW (UDS):
          0x31 01 D0 5A   → startRoutine "DSC Steering Angle Calibration"
        Toyota / Lexus:
          0x31 01 02 02   → startRoutine (con VSC desactivado temporalmente)

        Condiciones previas obligatorias:
          - Ruedas rectas, posición centrada
          - Motor en marcha (KOER) o KOEO según fabricante
          - Sesión extendida activa
        """
        return _requires_extension(
            protocol="UDS|ISO15765",
            command_hex="31 01 06 AD",  # VAG UDS SAS Calibration startRoutine
            note=(
                "VAG: 0x31 01 06AD.  "
                "BMW: 0x31 01 D05A.  "
                "Toyota: 0x31 01 0202.  "
                "Condición: ruedas rectas, sesión extendida (0x10 03)."
            ),
        )

    def reset_tpms(self) -> dict:
        """
        Reinicialización del sistema de monitoreo de presión de neumáticos (TPMS).

        Propietario — el proceso de 'relearn' varía mucho:

        Honda/Acura (CAN-UDS):
          0x31 01 00 FE → startRoutine "TPMS Learning Mode" (5 minutos a >35 km/h)
        Ford / Lincoln:
          Secuencia físico-manual con válvula de llenado, sin OBD directo
        VAG (UDS):
          0x31 01 02 0A → startRoutine TPMS relearn, luego confirmación 0x31 03 02 0A

        Para TPMS directo (con sensores RF en cada rueda) también se necesita
        la herramienta de activación de sensor (315/433 MHz) para "despertar"
        cada sensor en secuencia.
        """
        return _requires_extension(
            protocol="UDS|ISO15765",
            command_hex="31 01 00 FE",  # Honda UDS TPMS Learning Mode
            note=(
                "Honda: 0x31 01 00FE (luego conducir >35 km/h 5 min).  "
                "VAG: 0x31 01 020A → 0x31 03 020A.  "
                "Ford: procedimiento manual con válvula.  "
                "TPMS directo requiere herramienta de activación 315/433 MHz."
            ),
        )

    # ------------------------------------------------------------------
    # Adaptaciones y calibraciones
    # ------------------------------------------------------------------

    def calibrate_throttle_body(self) -> dict:
        """
        Calibración del cuerpo de mariposa electrónica (TPS zero-point).

        Propietario UDS / KWP2000:

        Toyota (KWP2000 → UDS en modelos post-2005):
          Procedimiento: KOEO, esperar 10 s, encender, esperar 3 s, apagar.
          Vía OBD no hay un routine ID estándar; cada fabricante tiene el suyo.

        Subaru / Nissan (ISO 15765 UDS):
          0x31 01 01 01 → startRoutine "TP Calibration"

        VAG (KWP2000 0x30):
          0x30 01 [canal 0x04] → startRoutine "Throttle Basic Setting"

        Nota: en muchos vehículos el procedimiento manual (sin escáner)
        consiste en ciclo de encendido específico; esta función intenta
        la vía automática vía OBD.
        """
        return _requires_extension(
            protocol="UDS|KWP2000",
            command_hex="31 01 01 01",  # Nissan/Subaru UDS TP Calibration
            note=(
                "Nissan/Subaru UDS: 0x31 01 0101.  "
                "VAG KWP2000: 0x30 01 04.  "
                "Toyota: procedimiento KOEO manual (consultar manual de taller).  "
                "Requiere sesión extendida (0x10 03)."
            ),
        )

    def reset_injector_corrections(self) -> dict:
        """
        Reset de las correcciones individuales de inyectores (IQ / C2I / IMA).

        Propietario — Bosch CRDi (EDC16/17), Siemens/Continental SID:

        Bosch EDC17 (UDS):
          DIDs típicos de correcciones IQ:
            0xA020..0xA023 = corrección cil. 1..4 (valor neutro = 0x0000)
          Secuencia:
            0x10 03 → sesión extendida
            0x27 01/02 → SecurityAccess
            0x2E A0 20 00 00 → resetear corrección cil.1
            0x2E A0 21 00 00 → ... cil.2  (etc.)

        Siemens SID206/SID807 (UDS):
          DID 0x6030..0x6033 = correcciones inyectores

        ADVERTENCIA: Solo resetear tras sustitución de inyectores o
        tras haber introducido los códigos IMA del fabricante de inyector.
        """
        return _requires_extension(
            protocol="UDS",
            command_hex="2E A0 20 00 00",  # Bosch EDC17 WriteDataByIdentifier inj.corr cil.1
            note=(
                "Bosch EDC17 UDS: 0x2E A020-A023 00 00 (un DID por cilindro).  "
                "Siemens SID: 0x2E 6030-6033 00 00.  "
                "¡Solo tras cambio de inyectores o introducción de códigos IMA!"
            ),
        )

    def set_idle_speed(self, target_rpm: int) -> dict:
        """
        Programa la velocidad de ralentí objetivo en la ECU.

        Propietario — UDS WriteDataByIdentifier:

        Bosch ME7 / MED17 (gasolina):
          DID 0x1F40 = "Idle Speed Target" (uint16, valor = RPM directas)
          Rango típico: 650..1000 RPM

        Bosch EDC17 (diesel):
          DID 0x1F41 = "Idle Speed Diesel" (uint16, valor = RPM)

        Parámetros
        ----------
        target_rpm : int
            RPM objetivo de ralentí (rango recomendado: 650-950 RPM).
        """
        if not (400 <= target_rpm <= 1500):
            return {
                "status": "error",
                "message": f"target_rpm={target_rpm} fuera del rango seguro (400-1500 RPM)",
            }

        hi = (target_rpm >> 8) & 0xFF
        lo = target_rpm & 0xFF
        return _requires_extension(
            protocol="UDS|KWP2000",
            command_hex=f"2E 1F 40 {hi:02X} {lo:02X}",  # WriteDataByIdentifier DID=0x1F40
            note=(
                f"Bosch ME7/MED17: 0x2E 1F40 {hi:02X}{lo:02X} ({target_rpm} RPM).  "
                "Bosch EDC17 diesel: DID 0x1F41.  "
                "Requiere sesión extendida + SecurityAccess."
            ),
        )

    # ------------------------------------------------------------------
    # Activaciones de actuadores (Mode 08 — OBD-II estándar)
    # ------------------------------------------------------------------

    def activate_fuel_pump(self, duration_sec: int = 2) -> bool:
        """
        Activa la bomba de combustible mediante OBD-II Mode 08.

        Mode 08 PID 0x01 = "Fuel Pump" (SAE J1979).
        No todos los fabricantes implementan Mode 08; si el vehículo no
        responde se devuelve False sin lanzar excepción.

        Parámetros
        ----------
        duration_sec : int
            Segundos de activación (0-255, default 2).
        """
        duration_sec = max(0, min(255, duration_sec))
        # Mode 08 = 0x08, PID = 0x01 (fuel pump), duración en segundos
        cmd = f"08 01 {duration_sec:02X}"
        raw = self._obd_raw(cmd)
        ok = self._is_positive_response(raw)
        if ok:
            time.sleep(duration_sec)
            # Enviar comando de desactivación (duración 0)
            self._obd_raw(f"08 01 00")
        return ok

    def activate_fan(self, speed: int = 1) -> bool:
        """
        Activa el ventilador de refrigeración mediante OBD-II Mode 08.

        Mode 08 PID 0x0B = "A/C Refrigerant / Cooling Fan" (SAE J1979).
        speed: 1 = baja velocidad, 2 = alta velocidad (si aplica).

        Parámetros
        ----------
        speed : int
            Velocidad del ventilador (1 = baja, 2 = alta).
        """
        pid = 0x0B  # Cooling fan
        speed_byte = 0x01 if speed <= 1 else 0x02
        cmd = f"08 {pid:02X} {speed_byte:02X}"
        raw = self._obd_raw(cmd)
        return self._is_positive_response(raw)

    # ------------------------------------------------------------------
    # Información y estado
    # ------------------------------------------------------------------

    def get_available_resets(self) -> list[dict]:
        """
        Devuelve el catálogo completo de resets disponibles.

        Cada entrada incluye:
          - id: identificador único
          - name: descripción legible
          - standard: True si es OBD-II estándar, False si es propietario
          - protocol: protocolo requerido
          - obd_mode: número de modo OBD (None si propietario)
          - note: descripción técnica y comandos reales
        """
        return AVAILABLE_RESETS

    def get_service_status(self) -> dict:
        """
        Obtiene el estado de diagnóstico actual del vehículo.

        Combina datos estándar OBD (Mode 01 PIDs de estado) con información
        sobre qué resets están disponibles.

        Devuelve
        --------
        dict con:
          - dtc_count: número de DTCs activos (Mode 01 PID 0x01)
          - mil_on: estado de la luz MIL
          - dist_since_dtc_clear: km desde último borrado (PID 0x31)
          - warmups_since_clear: calentamientos desde borrado (PID 0x30)
          - available_standard: lista de resets estándar OBD
          - available_proprietary: lista de resets propietarios
        """
        status: dict[str, Any] = {
            "dtc_count": None,
            "mil_on": None,
            "dist_since_dtc_clear": None,
            "warmups_since_clear": None,
            "available_standard": [],
            "available_proprietary": [],
        }

        # PID 0x01 — número de DTCs y estado MIL
        raw_01 = self._obd_raw("0101")
        if self._is_positive_response(raw_01):
            try:
                bytes_hex = raw_01.replace(" ", "").replace("\r", "").replace("\n", "")
                # La respuesta típica es "41 01 XX XX XX XX"
                idx = bytes_hex.upper().find("4101")
                if idx != -1:
                    data_hex = bytes_hex[idx + 4 :]
                    b0 = int(data_hex[0:2], 16)
                    status["mil_on"] = bool(b0 & 0x80)
                    status["dtc_count"] = b0 & 0x7F
            except (ValueError, IndexError):
                pass

        # PID 0x30 — calentamientos desde limpieza DTCs
        raw_30 = self._obd_raw("0130")
        if self._is_positive_response(raw_30):
            try:
                idx = raw_30.upper().replace(" ", "").find("4130")
                if idx != -1:
                    val = int(raw_30.replace(" ", "")[idx + 4 : idx + 6], 16)
                    status["warmups_since_clear"] = val
            except (ValueError, IndexError):
                pass

        # PID 0x31 — distancia desde limpieza DTCs
        raw_31 = self._obd_raw("0131")
        if self._is_positive_response(raw_31):
            try:
                idx = raw_31.upper().replace(" ", "").find("4131")
                if idx != -1:
                    hi = int(raw_31.replace(" ", "")[idx + 4 : idx + 6], 16)
                    lo = int(raw_31.replace(" ", "")[idx + 6 : idx + 8], 16)
                    status["dist_since_dtc_clear"] = hi * 256 + lo
            except (ValueError, IndexError):
                pass

        # Clasificar resets disponibles
        for r in AVAILABLE_RESETS:
            if r["standard"]:
                status["available_standard"].append(r["id"])
            else:
                status["available_proprietary"].append(r["id"])

        return status
