"""
SOLER OBD2 AI Scanner - DTC Diagnostic Module

Reads stored (Mode 03), pending (Mode 07), and permanent (Mode 0A) DTCs,
decodes raw bytes to standard format (P/C/B/U 0xxx), reads Freeze Frame
data (Mode 02), classifies severity, and can clear codes (Mode 04).

Includes a built-in database of 200+ common DTC descriptions in Spanish.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import obd
from obd import OBDResponse

from backend.config import settings
from backend.obd.connection import OBDConnectionManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums / data models
# ---------------------------------------------------------------------------

class DTCType(str, Enum):
    STORED = "stored"          # Mode 03
    PENDING = "pending"        # Mode 07
    PERMANENT = "permanent"    # Mode 0A


class DTCSeverity(str, Enum):
    CRITICAL = "critical"  # Immediate stop / engine damage risk
    HIGH = "high"          # Drivability / safety affected
    MEDIUM = "medium"      # Emissions / efficiency reduced
    LOW = "low"            # Informational / intermittent


class DTCCategory(str, Enum):
    POWERTRAIN = "P"
    CHASSIS = "C"
    BODY = "B"
    NETWORK = "U"


@dataclass
class DTCRecord:
    """One decoded DTC with metadata."""
    code: str                           # e.g. "P0301"
    type: DTCType
    category: DTCCategory
    severity: DTCSeverity
    description_es: str                 # Spanish description
    description_en: str                 # English fallback
    freeze_frame: Optional[dict[str, Any]] = None
    timestamp: float = 0.0


@dataclass
class DTCScanResult:
    """Full DTC scan output."""
    stored: list[DTCRecord] = field(default_factory=list)
    pending: list[DTCRecord] = field(default_factory=list)
    permanent: list[DTCRecord] = field(default_factory=list)
    mil_on: bool = False
    dtc_count: int = 0
    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# Severity classification rules
# ---------------------------------------------------------------------------

_SEVERITY_RULES: list[tuple[str, DTCSeverity]] = [
    # Critical - misfire, overheating, oil pressure, transmission critical
    ("P030",  DTCSeverity.CRITICAL),   # Cylinder misfires
    ("P0217", DTCSeverity.CRITICAL),   # Engine overtemp
    ("P0218", DTCSeverity.CRITICAL),   # Transmission overtemp
    ("P0520", DTCSeverity.CRITICAL),   # Oil pressure sensor
    ("P0524", DTCSeverity.CRITICAL),   # Oil pressure low
    ("P061",  DTCSeverity.CRITICAL),   # Internal control module
    ("P062",  DTCSeverity.CRITICAL),   # Internal control module
    ("U010",  DTCSeverity.CRITICAL),   # Lost comm with ECU
    ("U0100", DTCSeverity.CRITICAL),   # Lost comm with ECM/PCM

    # High - fuel system, ignition, catalyst, transmission
    ("P010",  DTCSeverity.HIGH),
    ("P011",  DTCSeverity.HIGH),
    ("P020",  DTCSeverity.HIGH),       # Injector circuits
    ("P0300", DTCSeverity.HIGH),       # Random misfire
    ("P040",  DTCSeverity.HIGH),       # EGR
    ("P042",  DTCSeverity.HIGH),       # Catalyst efficiency
    ("P050",  DTCSeverity.HIGH),       # O2 / A-F sensor
    ("P06",   DTCSeverity.HIGH),
    ("P07",   DTCSeverity.HIGH),       # Transmission
    ("C0",    DTCSeverity.HIGH),       # Chassis - ABS / stability
    ("B16",   DTCSeverity.HIGH),       # Airbag

    # Medium - emissions, EVAP, sensors
    ("P04",   DTCSeverity.MEDIUM),
    ("P01",   DTCSeverity.MEDIUM),
    ("P02",   DTCSeverity.MEDIUM),
    ("P044",  DTCSeverity.MEDIUM),     # EVAP
    ("P045",  DTCSeverity.MEDIUM),
    ("B0",    DTCSeverity.MEDIUM),

    # Everything else
    ("",      DTCSeverity.LOW),
]


def classify_severity(code: str) -> DTCSeverity:
    """Return the severity level for a DTC code."""
    for prefix, severity in _SEVERITY_RULES:
        if code.startswith(prefix):
            return severity
    return DTCSeverity.LOW


def get_category(code: str) -> DTCCategory:
    """Extract the category letter from a DTC code."""
    if not code:
        return DTCCategory.POWERTRAIN
    first = code[0].upper()
    return DTCCategory(first) if first in ("P", "C", "B", "U") else DTCCategory.POWERTRAIN


# ---------------------------------------------------------------------------
# DTC Database - Spanish descriptions (200+ codes)
# ---------------------------------------------------------------------------

DTC_DATABASE: dict[str, tuple[str, str]] = {
    # --- Powertrain: fuel / air metering ---
    "P0100": ("Circuito del sensor de flujo de masa de aire (MAF) - mal funcionamiento", "Mass Air Flow Circuit Malfunction"),
    "P0101": ("Rango/rendimiento del circuito MAF", "Mass Air Flow Circuit Range/Performance"),
    "P0102": ("Circuito MAF - entrada baja", "Mass Air Flow Circuit Low Input"),
    "P0103": ("Circuito MAF - entrada alta", "Mass Air Flow Circuit High Input"),
    "P0104": ("Circuito MAF - intermitente", "Mass Air Flow Circuit Intermittent"),
    "P0105": ("Circuito de presion absoluta del colector (MAP) - mal funcionamiento", "MAP Circuit Malfunction"),
    "P0106": ("Rango/rendimiento del circuito MAP/presion barometrica", "MAP/Barometric Pressure Circuit Range/Performance"),
    "P0107": ("Circuito MAP - entrada baja", "MAP Circuit Low Input"),
    "P0108": ("Circuito MAP - entrada alta", "MAP Circuit High Input"),
    "P0110": ("Circuito del sensor de temperatura de aire de admision (IAT) - mal funcionamiento", "Intake Air Temperature Circuit Malfunction"),
    "P0111": ("Rango/rendimiento del circuito IAT", "Intake Air Temperature Circuit Range/Performance"),
    "P0112": ("Circuito IAT - entrada baja", "Intake Air Temperature Circuit Low Input"),
    "P0113": ("Circuito IAT - entrada alta", "Intake Air Temperature Circuit High Input"),
    "P0115": ("Circuito del sensor de temperatura del refrigerante (ECT) - mal funcionamiento", "Engine Coolant Temperature Circuit Malfunction"),
    "P0116": ("Rango/rendimiento del circuito ECT", "Engine Coolant Temperature Circuit Range/Performance"),
    "P0117": ("Circuito ECT - entrada baja", "Engine Coolant Temperature Circuit Low Input"),
    "P0118": ("Circuito ECT - entrada alta", "Engine Coolant Temperature Circuit High Input"),
    "P0120": ("Circuito del sensor de posicion del acelerador (TPS) - mal funcionamiento", "Throttle Position Sensor Circuit Malfunction"),
    "P0121": ("Rango/rendimiento del circuito TPS", "Throttle Position Sensor Circuit Range/Performance"),
    "P0122": ("Circuito TPS - entrada baja", "Throttle Position Sensor Circuit Low Input"),
    "P0123": ("Circuito TPS - entrada alta", "Throttle Position Sensor Circuit High Input"),
    "P0125": ("Temperatura del refrigerante insuficiente para control de combustible", "Insufficient Coolant Temperature for Closed Loop"),
    "P0128": ("Termostato del refrigerante - temperatura debajo del rango", "Coolant Thermostat Below Thermostat Regulating Temperature"),
    "P0130": ("Circuito del sensor de oxigeno (O2) banco 1 sensor 1 - mal funcionamiento", "O2 Sensor Circuit Malfunction Bank 1 Sensor 1"),
    "P0131": ("Circuito O2 banco 1 sensor 1 - voltaje bajo", "O2 Sensor Circuit Low Voltage Bank 1 Sensor 1"),
    "P0132": ("Circuito O2 banco 1 sensor 1 - voltaje alto", "O2 Sensor Circuit High Voltage Bank 1 Sensor 1"),
    "P0133": ("Respuesta lenta del sensor O2 banco 1 sensor 1", "O2 Sensor Slow Response Bank 1 Sensor 1"),
    "P0134": ("Sin actividad del sensor O2 banco 1 sensor 1", "O2 Sensor No Activity Detected Bank 1 Sensor 1"),
    "P0135": ("Circuito del calentador del sensor O2 banco 1 sensor 1 - mal funcionamiento", "O2 Sensor Heater Circuit Malfunction Bank 1 Sensor 1"),
    "P0136": ("Circuito del sensor O2 banco 1 sensor 2 - mal funcionamiento", "O2 Sensor Circuit Malfunction Bank 1 Sensor 2"),
    "P0137": ("Circuito O2 banco 1 sensor 2 - voltaje bajo", "O2 Sensor Circuit Low Voltage Bank 1 Sensor 2"),
    "P0138": ("Circuito O2 banco 1 sensor 2 - voltaje alto", "O2 Sensor Circuit High Voltage Bank 1 Sensor 2"),
    "P0139": ("Respuesta lenta del sensor O2 banco 1 sensor 2", "O2 Sensor Slow Response Bank 1 Sensor 2"),
    "P0140": ("Sin actividad del sensor O2 banco 1 sensor 2", "O2 Sensor No Activity Detected Bank 1 Sensor 2"),
    "P0141": ("Circuito del calentador del sensor O2 banco 1 sensor 2 - mal funcionamiento", "O2 Sensor Heater Circuit Malfunction Bank 1 Sensor 2"),
    "P0150": ("Circuito del sensor O2 banco 2 sensor 1 - mal funcionamiento", "O2 Sensor Circuit Malfunction Bank 2 Sensor 1"),
    "P0151": ("Circuito O2 banco 2 sensor 1 - voltaje bajo", "O2 Sensor Circuit Low Voltage Bank 2 Sensor 1"),
    "P0152": ("Circuito O2 banco 2 sensor 1 - voltaje alto", "O2 Sensor Circuit High Voltage Bank 2 Sensor 1"),
    "P0153": ("Respuesta lenta del sensor O2 banco 2 sensor 1", "O2 Sensor Slow Response Bank 2 Sensor 1"),
    "P0154": ("Sin actividad del sensor O2 banco 2 sensor 1", "O2 Sensor No Activity Detected Bank 2 Sensor 1"),
    "P0155": ("Circuito del calentador del sensor O2 banco 2 sensor 1 - mal funcionamiento", "O2 Sensor Heater Circuit Malfunction Bank 2 Sensor 1"),

    # --- Fuel system ---
    "P0170": ("Mal funcionamiento del ajuste de combustible banco 1", "Fuel Trim Malfunction Bank 1"),
    "P0171": ("Sistema demasiado pobre - banco 1", "System Too Lean Bank 1"),
    "P0172": ("Sistema demasiado rico - banco 1", "System Too Rich Bank 1"),
    "P0173": ("Mal funcionamiento del ajuste de combustible banco 2", "Fuel Trim Malfunction Bank 2"),
    "P0174": ("Sistema demasiado pobre - banco 2", "System Too Lean Bank 2"),
    "P0175": ("Sistema demasiado rico - banco 2", "System Too Rich Bank 2"),
    "P0176": ("Circuito del sensor de composicion de combustible - mal funcionamiento", "Fuel Composition Sensor Circuit Malfunction"),
    "P0190": ("Circuito del sensor de presion del riel de combustible - mal funcionamiento", "Fuel Rail Pressure Sensor Circuit Malfunction"),
    "P0191": ("Rango/rendimiento del circuito de presion del riel", "Fuel Rail Pressure Sensor Circuit Range/Performance"),
    "P0192": ("Circuito de presion del riel de combustible - entrada baja", "Fuel Rail Pressure Sensor Circuit Low Input"),
    "P0193": ("Circuito de presion del riel de combustible - entrada alta", "Fuel Rail Pressure Sensor Circuit High Input"),

    # --- Ignition / misfire ---
    "P0200": ("Circuito del inyector - mal funcionamiento", "Injector Circuit Malfunction"),
    "P0201": ("Circuito del inyector - cilindro 1", "Injector Circuit Malfunction Cylinder 1"),
    "P0202": ("Circuito del inyector - cilindro 2", "Injector Circuit Malfunction Cylinder 2"),
    "P0203": ("Circuito del inyector - cilindro 3", "Injector Circuit Malfunction Cylinder 3"),
    "P0204": ("Circuito del inyector - cilindro 4", "Injector Circuit Malfunction Cylinder 4"),
    "P0205": ("Circuito del inyector - cilindro 5", "Injector Circuit Malfunction Cylinder 5"),
    "P0206": ("Circuito del inyector - cilindro 6", "Injector Circuit Malfunction Cylinder 6"),
    "P0207": ("Circuito del inyector - cilindro 7", "Injector Circuit Malfunction Cylinder 7"),
    "P0208": ("Circuito del inyector - cilindro 8", "Injector Circuit Malfunction Cylinder 8"),
    "P0217": ("Sobretemperatura del motor", "Engine Overtemperature Condition"),
    "P0218": ("Sobretemperatura de la transmision", "Transmission Over Temperature Condition"),
    "P0219": ("Exceso de revoluciones del motor", "Engine Overspeed Condition"),
    "P0220": ("Circuito del sensor de posicion del acelerador B - mal funcionamiento", "Throttle Position Sensor B Circuit Malfunction"),
    "P0230": ("Circuito primario de la bomba de combustible - mal funcionamiento", "Fuel Pump Primary Circuit Malfunction"),
    "P0261": ("Circuito del inyector cilindro 1 - bajo", "Cylinder 1 Injector Circuit Low"),
    "P0262": ("Circuito del inyector cilindro 1 - alto", "Cylinder 1 Injector Circuit High"),
    "P0300": ("Fallo de encendido aleatorio detectado en multiples cilindros", "Random/Multiple Cylinder Misfire Detected"),
    "P0301": ("Fallo de encendido detectado - cilindro 1", "Cylinder 1 Misfire Detected"),
    "P0302": ("Fallo de encendido detectado - cilindro 2", "Cylinder 2 Misfire Detected"),
    "P0303": ("Fallo de encendido detectado - cilindro 3", "Cylinder 3 Misfire Detected"),
    "P0304": ("Fallo de encendido detectado - cilindro 4", "Cylinder 4 Misfire Detected"),
    "P0305": ("Fallo de encendido detectado - cilindro 5", "Cylinder 5 Misfire Detected"),
    "P0306": ("Fallo de encendido detectado - cilindro 6", "Cylinder 6 Misfire Detected"),
    "P0307": ("Fallo de encendido detectado - cilindro 7", "Cylinder 7 Misfire Detected"),
    "P0308": ("Fallo de encendido detectado - cilindro 8", "Cylinder 8 Misfire Detected"),
    "P0325": ("Circuito del sensor de detonacion 1 - mal funcionamiento", "Knock Sensor 1 Circuit Malfunction"),
    "P0326": ("Rango/rendimiento del circuito del sensor de detonacion 1", "Knock Sensor 1 Circuit Range/Performance"),
    "P0327": ("Circuito del sensor de detonacion 1 - entrada baja", "Knock Sensor 1 Circuit Low Input"),
    "P0328": ("Circuito del sensor de detonacion 1 - entrada alta", "Knock Sensor 1 Circuit High Input"),
    "P0335": ("Circuito del sensor de posicion del ciguenal (CKP) - mal funcionamiento", "Crankshaft Position Sensor Circuit Malfunction"),
    "P0336": ("Rango/rendimiento del circuito del sensor CKP", "Crankshaft Position Sensor Circuit Range/Performance"),
    "P0340": ("Circuito del sensor de posicion del arbol de levas (CMP) - mal funcionamiento", "Camshaft Position Sensor Circuit Malfunction"),
    "P0341": ("Rango/rendimiento del circuito del sensor CMP", "Camshaft Position Sensor Circuit Range/Performance"),

    # --- EGR / Emissions ---
    "P0400": ("Flujo de recirculacion de gases de escape (EGR) - mal funcionamiento", "Exhaust Gas Recirculation Flow Malfunction"),
    "P0401": ("Flujo EGR insuficiente detectado", "Exhaust Gas Recirculation Flow Insufficient"),
    "P0402": ("Flujo EGR excesivo detectado", "Exhaust Gas Recirculation Flow Excessive"),
    "P0403": ("Circuito de control EGR - mal funcionamiento", "Exhaust Gas Recirculation Control Circuit Malfunction"),
    "P0404": ("Rango/rendimiento del circuito de control EGR", "EGR Control Circuit Range/Performance"),
    "P0405": ("Circuito del sensor de posicion EGR A - bajo", "EGR Sensor A Circuit Low"),
    "P0406": ("Circuito del sensor de posicion EGR A - alto", "EGR Sensor A Circuit High"),
    "P0410": ("Sistema de inyeccion de aire secundario - mal funcionamiento", "Secondary Air Injection System Malfunction"),
    "P0411": ("Flujo incorrecto del sistema de inyeccion de aire secundario", "Secondary Air Injection System Incorrect Flow"),
    "P0420": ("Eficiencia del catalizador por debajo del umbral - banco 1", "Catalyst System Efficiency Below Threshold Bank 1"),
    "P0421": ("Eficiencia del catalizador en calentamiento por debajo del umbral - banco 1", "Warm Up Catalyst Efficiency Below Threshold Bank 1"),
    "P0430": ("Eficiencia del catalizador por debajo del umbral - banco 2", "Catalyst System Efficiency Below Threshold Bank 2"),
    "P0440": ("Sistema de control de emisiones evaporativas (EVAP) - mal funcionamiento", "Evaporative Emission Control System Malfunction"),
    "P0441": ("Flujo de purga incorrecto del sistema EVAP", "Evaporative Emission Control System Incorrect Purge Flow"),
    "P0442": ("Fuga pequena detectada en el sistema EVAP", "Evaporative Emission Control System Leak Detected Small"),
    "P0443": ("Circuito de control de la valvula de purga EVAP - mal funcionamiento", "EVAP Purge Control Valve Circuit Malfunction"),
    "P0446": ("Circuito de control de ventilacion del sistema EVAP - mal funcionamiento", "EVAP Vent Control Circuit Malfunction"),
    "P0449": ("Circuito de la valvula/solenoide de ventilacion del sistema EVAP - mal funcionamiento", "EVAP Vent Valve/Solenoid Circuit Malfunction"),
    "P0450": ("Circuito del sensor de presion del sistema EVAP - mal funcionamiento", "EVAP Pressure Sensor Circuit Malfunction"),
    "P0451": ("Rango/rendimiento del sensor de presion del sistema EVAP", "EVAP Pressure Sensor Circuit Range/Performance"),
    "P0452": ("Circuito del sensor de presion EVAP - entrada baja", "EVAP Pressure Sensor Circuit Low Input"),
    "P0453": ("Circuito del sensor de presion EVAP - entrada alta", "EVAP Pressure Sensor Circuit High Input"),
    "P0455": ("Fuga grande detectada en el sistema EVAP", "EVAP System Leak Detected Gross Leak"),
    "P0456": ("Fuga muy pequena detectada en el sistema EVAP", "EVAP System Leak Detected Very Small"),

    # --- Vehicle speed / idle ---
    "P0500": ("Sensor de velocidad del vehiculo - mal funcionamiento", "Vehicle Speed Sensor Malfunction"),
    "P0501": ("Rango/rendimiento del sensor de velocidad del vehiculo", "Vehicle Speed Sensor Range/Performance"),
    "P0505": ("Sistema de control de velocidad de ralenti - mal funcionamiento", "Idle Control System Malfunction"),
    "P0506": ("Sistema de control de ralenti - RPM mas bajo de lo esperado", "Idle Control System RPM Lower Than Expected"),
    "P0507": ("Sistema de control de ralenti - RPM mas alto de lo esperado", "Idle Control System RPM Higher Than Expected"),
    "P0510": ("Interruptor de posicion del acelerador cerrado - mal funcionamiento", "Closed Throttle Position Switch Malfunction"),
    "P0520": ("Circuito del sensor de presion de aceite del motor - mal funcionamiento", "Engine Oil Pressure Sensor Circuit Malfunction"),
    "P0521": ("Rango/rendimiento del sensor de presion de aceite del motor", "Engine Oil Pressure Sensor Range/Performance"),
    "P0522": ("Circuito del sensor de presion de aceite - voltaje bajo", "Engine Oil Pressure Sensor Low Voltage"),
    "P0523": ("Circuito del sensor de presion de aceite - voltaje alto", "Engine Oil Pressure Sensor High Voltage"),
    "P0524": ("Presion de aceite del motor demasiado baja", "Engine Oil Pressure Too Low"),

    # --- A/C, alternator ---
    "P0530": ("Circuito del sensor de presion del refrigerante de A/C - mal funcionamiento", "A/C Refrigerant Pressure Sensor Circuit Malfunction"),
    "P0560": ("Voltaje del sistema electrico - mal funcionamiento", "System Voltage Malfunction"),
    "P0562": ("Voltaje del sistema electrico - bajo", "System Voltage Low"),
    "P0563": ("Voltaje del sistema electrico - alto", "System Voltage High"),

    # --- Internal control module ---
    "P0600": ("Enlace de comunicacion serial (bus de datos) - mal funcionamiento", "Serial Communication Link Malfunction"),
    "P0601": ("Memoria interna del modulo de control - error de checksum", "Internal Control Module Memory Check Sum Error"),
    "P0602": ("Error de programacion del modulo de control", "Control Module Programming Error"),
    "P0603": ("Memoria KAM del modulo de control - error", "Internal Control Module KAM Error"),
    "P0604": ("Memoria RAM del modulo de control - error", "Internal Control Module RAM Error"),
    "P0605": ("Memoria ROM del modulo de control - error", "Internal Control Module ROM Error"),
    "P0606": ("Procesador del modulo de control - mal funcionamiento", "PCM Processor Fault"),
    "P0607": ("Rendimiento del modulo de control", "Control Module Performance"),

    # --- Transmission ---
    "P0700": ("Sistema de control de la transmision - mal funcionamiento", "Transmission Control System Malfunction"),
    "P0705": ("Circuito del sensor de rango de la transmision - mal funcionamiento", "Transmission Range Sensor Circuit Malfunction"),
    "P0710": ("Circuito del sensor de temperatura del fluido de transmision - mal funcionamiento", "Transmission Fluid Temperature Sensor Circuit Malfunction"),
    "P0715": ("Circuito del sensor de velocidad de entrada/turbina de la transmision - mal funcionamiento", "Input/Turbine Speed Sensor Circuit Malfunction"),
    "P0720": ("Circuito del sensor de velocidad de salida - mal funcionamiento", "Output Speed Sensor Circuit Malfunction"),
    "P0725": ("Circuito de entrada de velocidad del motor - mal funcionamiento", "Engine Speed Input Circuit Malfunction"),
    "P0730": ("Relacion de cambio incorrecta", "Incorrect Gear Ratio"),
    "P0731": ("Relacion de cambio incorrecta - primera marcha", "Gear 1 Incorrect Ratio"),
    "P0732": ("Relacion de cambio incorrecta - segunda marcha", "Gear 2 Incorrect Ratio"),
    "P0733": ("Relacion de cambio incorrecta - tercera marcha", "Gear 3 Incorrect Ratio"),
    "P0734": ("Relacion de cambio incorrecta - cuarta marcha", "Gear 4 Incorrect Ratio"),
    "P0740": ("Circuito del solenoide del embrague del convertidor de par - mal funcionamiento", "Torque Converter Clutch Circuit Malfunction"),
    "P0741": ("Rendimiento del circuito del embrague del convertidor de par o atascado en apagado", "Torque Converter Clutch Circuit Performance or Stuck Off"),
    "P0743": ("Circuito del embrague del convertidor de par - electrico", "Torque Converter Clutch Circuit Electrical"),
    "P0748": ("Circuito del solenoide de control de presion - electrico", "Pressure Control Solenoid Electrical"),
    "P0750": ("Solenoide de cambio A - mal funcionamiento", "Shift Solenoid A Malfunction"),
    "P0755": ("Solenoide de cambio B - mal funcionamiento", "Shift Solenoid B Malfunction"),
    "P0760": ("Solenoide de cambio C - mal funcionamiento", "Shift Solenoid C Malfunction"),
    "P0765": ("Solenoide de cambio D - mal funcionamiento", "Shift Solenoid D Malfunction"),

    # --- Chassis codes ---
    "C0035": ("Circuito del sensor de velocidad de la rueda delantera izquierda - mal funcionamiento", "Left Front Wheel Speed Circuit Malfunction"),
    "C0040": ("Circuito del sensor de velocidad de la rueda delantera derecha - mal funcionamiento", "Right Front Wheel Speed Circuit Malfunction"),
    "C0045": ("Circuito del sensor de velocidad de la rueda trasera izquierda - mal funcionamiento", "Left Rear Wheel Speed Circuit Malfunction"),
    "C0050": ("Circuito del sensor de velocidad de la rueda trasera derecha - mal funcionamiento", "Right Rear Wheel Speed Circuit Malfunction"),
    "C0060": ("Circuito del solenoide de la valvula ABS delantera izquierda - mal funcionamiento", "Left Front ABS Solenoid Valve Circuit Malfunction"),
    "C0065": ("Circuito del solenoide de la valvula ABS delantera derecha - mal funcionamiento", "Right Front ABS Solenoid Valve Circuit Malfunction"),
    "C0070": ("Circuito del solenoide de la valvula ABS trasera izquierda - mal funcionamiento", "Left Rear ABS Solenoid Valve Circuit Malfunction"),
    "C0075": ("Circuito del solenoide de la valvula ABS trasera derecha - mal funcionamiento", "Right Rear ABS Solenoid Valve Circuit Malfunction"),
    "C0110": ("Circuito de la bomba del motor ABS - mal funcionamiento", "ABS Pump Motor Circuit Malfunction"),
    "C0196": ("Error del sensor de viraje (yaw) del sistema de estabilidad", "Stability System Yaw Rate Sensor Error"),
    "C0200": ("Mal funcionamiento del circuito de la valvula del solenoide ABS", "ABS Solenoid Valve Circuit Malfunction"),
    "C0242": ("Circuito del sensor de presion del modulo de frenos PCM - mal funcionamiento", "PCM Indicated Brake Pressure Circuit Malfunction"),
    "C0300": ("Circuito del sensor del angulo de direccion - mal funcionamiento", "Steering Angle Sensor Circuit Malfunction"),

    # --- Body codes ---
    "B0001": ("Circuito de encendido del airbag del conductor - alto", "Driver Frontal Stage 1 Deployment Control High"),
    "B0002": ("Circuito de encendido del airbag del pasajero - alto", "Passenger Frontal Stage 1 Deployment Control High"),
    "B0010": ("Circuito del pretensor del cinturon del conductor - mal funcionamiento", "Driver Seat Belt Pretensioner Circuit Malfunction"),
    "B0015": ("Circuito del pretensor del cinturon del pasajero - mal funcionamiento", "Passenger Seat Belt Pretensioner Circuit Malfunction"),
    "B0050": ("Circuito del sensor de ocupacion del asiento del pasajero - mal funcionamiento", "Passenger Seat Occupant Sensor Circuit Malfunction"),
    "B0100": ("Circuito de control de la puerta del conductor - mal funcionamiento", "Driver Door Lock Control Circuit Malfunction"),
    "B0105": ("Circuito de control de la puerta del pasajero - mal funcionamiento", "Passenger Door Lock Control Circuit Malfunction"),
    "B1000": ("Mal funcionamiento del circuito de alimentacion del modulo ECU", "ECU Power Supply Circuit Malfunction"),
    "B1015": ("Circuito de la bateria del SRS - voltaje bajo", "SRS Battery Voltage Low"),
    "B1050": ("Circuito de la lampara del airbag - mal funcionamiento", "Airbag Warning Lamp Circuit Malfunction"),
    "B1200": ("Circuito del sensor de temperatura del climatizador - mal funcionamiento", "Climate Control Temperature Sensor Circuit Malfunction"),
    "B1325": ("Voltaje del sistema de frenado electrico fuera de rango", "Electronic Brake System Voltage Out of Range"),
    "B1600": ("Circuito del modulo de control del airbag - mal funcionamiento", "Airbag Control Module Circuit Malfunction"),
    "B1601": ("Error de comunicacion del modulo del airbag", "Airbag Module Communication Error"),
    "B1650": ("Circuito de la luz de advertencia del cinturon de seguridad - mal funcionamiento", "Seat Belt Warning Lamp Circuit Malfunction"),
    "B1811": ("Fallo del sensor de impacto lateral del pasajero", "Passenger Side Impact Sensor Fault"),

    # --- Network / communication codes ---
    "U0001": ("Bus CAN de alta velocidad - sin comunicacion", "High Speed CAN Communication Bus No Communication"),
    "U0002": ("Bus CAN de alta velocidad - rendimiento del bus", "High Speed CAN Communication Bus Performance"),
    "U0073": ("Bus de comunicacion del modulo de control - apagado", "Control Module Communication Bus Off"),
    "U0100": ("Perdida de comunicacion con el ECM/PCM", "Lost Communication with ECM/PCM"),
    "U0101": ("Perdida de comunicacion con el TCM", "Lost Communication with TCM"),
    "U0102": ("Perdida de comunicacion con el modulo de control de transferencia", "Lost Communication with Transfer Case Control Module"),
    "U0103": ("Perdida de comunicacion con el solenoide de cambio de marchas", "Lost Communication with Gear Shift Module"),
    "U0107": ("Perdida de comunicacion con el modulo de control del acelerador", "Lost Communication with Throttle Actuator Control Module"),
    "U0121": ("Perdida de comunicacion con el modulo de control ABS", "Lost Communication with ABS Control Module"),
    "U0122": ("Perdida de comunicacion con el modulo de control de estabilidad", "Lost Communication with Vehicle Dynamics Control Module"),
    "U0126": ("Perdida de comunicacion con el modulo de control de la direccion", "Lost Communication with Steering Angle Sensor Module"),
    "U0140": ("Perdida de comunicacion con el modulo de control de carroceria", "Lost Communication with Body Control Module"),
    "U0141": ("Perdida de comunicacion con el modulo de control del A/C", "Lost Communication with A/C Control Module"),
    "U0151": ("Perdida de comunicacion con el modulo de restricciones (SRS)", "Lost Communication with Restraints Control Module"),
    "U0155": ("Perdida de comunicacion con el modulo de instrumentos", "Lost Communication with Instrument Panel Cluster"),
    "U0164": ("Perdida de comunicacion con el modulo HVAC", "Lost Communication with HVAC Control Module"),
    "U0184": ("Perdida de comunicacion con el modulo de audio", "Lost Communication with Radio/Audio Module"),
    "U0293": ("Rendimiento del bus de comunicacion del modulo de control", "Control Module Communication Bus Performance"),
    "U0300": ("Incompatibilidad de software del modulo de control interno", "Internal Control Module Software Incompatibility"),
    "U0401": ("Datos invalidos recibidos del ECM/PCM", "Invalid Data Received from ECM/PCM"),
    "U0402": ("Datos invalidos recibidos del TCM", "Invalid Data Received from TCM"),
    "U0426": ("Datos invalidos recibidos del modulo del inmovilizador", "Invalid Data Received from Immobilizer Module"),

    # --- Additional common PIDs: variable valve timing ---
    "P0010": ("Circuito del actuador de posicion del arbol de levas de admision A - banco 1", "Intake Camshaft Position Actuator Circuit Bank 1"),
    "P0011": ("Posicion del arbol de levas de admision A - adelantada o rendimiento del sistema - banco 1", "Intake Camshaft Position Timing Over-Advanced Bank 1"),
    "P0012": ("Posicion del arbol de levas de admision A - retrasada - banco 1", "Intake Camshaft Position Timing Over-Retarded Bank 1"),
    "P0013": ("Circuito del actuador de posicion del arbol de levas de escape B - banco 1", "Exhaust Camshaft Position Actuator Circuit Bank 1"),
    "P0014": ("Posicion del arbol de levas de escape B - adelantada o rendimiento del sistema - banco 1", "Exhaust Camshaft Position Timing Over-Advanced Bank 1"),
    "P0016": ("Correlacion de posicion del ciguenal/arbol de levas - banco 1 sensor A", "Crankshaft/Camshaft Position Correlation Bank 1 Sensor A"),
    "P0017": ("Correlacion de posicion del ciguenal/arbol de levas - banco 1 sensor B", "Crankshaft/Camshaft Position Correlation Bank 1 Sensor B"),

    # --- Turbo / boost ---
    "P0234": ("Condicion de sobreimpulsion del turbocompresor/supercargador", "Turbo/Super Charger Overboost Condition"),
    "P0235": ("Circuito del sensor de presion de sobreimpulsion del turbocompresor A - mal funcionamiento", "Turbocharger Boost Sensor A Circuit Malfunction"),
    "P0236": ("Rango/rendimiento del sensor de presion del turbocompresor A", "Turbocharger Boost Sensor A Range/Performance"),
    "P0243": ("Solenoide de control de la valvula wastegate del turbocompresor A - mal funcionamiento", "Turbocharger Wastegate Solenoid A Malfunction"),
    "P0244": ("Rango/rendimiento del solenoide de la valvula wastegate del turbocompresor A", "Turbocharger Wastegate Solenoid A Range/Performance"),
    "P0299": ("Turbocompresor/supercargador - sobreimpulsion baja", "Turbo/Supercharger Underboost"),

    # --- DPF / diesel ---
    "P2002": ("Eficiencia del filtro de particulas por debajo del umbral - banco 1", "Diesel Particulate Filter Efficiency Below Threshold Bank 1"),
    "P2031": ("Circuito del sensor de temperatura de gases de escape banco 1 sensor 2", "Exhaust Gas Temperature Sensor Circuit Bank 1 Sensor 2"),
    "P2032": ("Circuito del sensor de temperatura de gases de escape banco 1 sensor 2 - bajo", "Exhaust Gas Temp Sensor Circuit Bank 1 Sensor 2 Low"),
    "P2033": ("Circuito del sensor de temperatura de gases de escape banco 1 sensor 2 - alto", "Exhaust Gas Temp Sensor Circuit Bank 1 Sensor 2 High"),
    "P2100": ("Circuito del actuador de control del acelerador - circuito abierto", "Throttle Actuator Control Motor Circuit Open"),
    "P2101": ("Rango/rendimiento del actuador de control del acelerador", "Throttle Actuator Control Motor Range/Performance"),
    "P2106": ("Sistema de control del actuador del acelerador - fuerza limitada de potencia", "Throttle Actuator Control System Forced Limited Power"),
    "P2108": ("Modulo de control del actuador del acelerador - rendimiento", "Throttle Actuator Control Module Performance"),
    "P2110": ("Sistema de control del actuador del acelerador - RPM de aire forzado limitado", "Throttle Actuator Control System Forced Limited RPM"),
    "P2111": ("Sistema del actuador del acelerador - atascado abierto", "Throttle Actuator Control System Stuck Open"),
    "P2112": ("Sistema del actuador del acelerador - atascado cerrado", "Throttle Actuator Control System Stuck Closed"),
    "P2118": ("Corriente del motor del actuador de control del acelerador - rango/rendimiento", "Throttle Actuator Control Motor Current Range/Performance"),
    "P2122": ("Circuito del sensor de posicion del pedal del acelerador D - bajo", "Throttle/Pedal Position Sensor D Circuit Low"),
    "P2123": ("Circuito del sensor de posicion del pedal del acelerador D - alto", "Throttle/Pedal Position Sensor D Circuit High"),
    "P2127": ("Circuito del sensor de posicion del pedal del acelerador E - bajo", "Throttle/Pedal Position Sensor E Circuit Low"),
    "P2128": ("Circuito del sensor de posicion del pedal del acelerador E - alto", "Throttle/Pedal Position Sensor E Circuit High"),
    "P2135": ("Correlacion de voltaje del sensor de posicion del acelerador A/B", "Throttle Position Sensor A/B Voltage Correlation"),
    "P2138": ("Correlacion de voltaje del sensor de posicion del pedal D/E", "Throttle/Pedal Position Sensor D/E Voltage Correlation"),
    "P2176": ("Sistema del actuador del acelerador - posicion de reposo no aprendida", "Throttle Actuator Control System Idle Position Not Learned"),
    "P2187": ("Sistema demasiado pobre en ralenti - banco 1", "System Too Lean at Idle Bank 1"),
    "P2188": ("Sistema demasiado rico en ralenti - banco 1", "System Too Rich at Idle Bank 1"),
    "P2195": ("Sensor de oxigeno senal atascada en pobre - banco 1 sensor 1", "O2 Sensor Signal Stuck Lean Bank 1 Sensor 1"),
    "P2196": ("Sensor de oxigeno senal atascada en rico - banco 1 sensor 1", "O2 Sensor Signal Stuck Rich Bank 1 Sensor 1"),
    "P2270": ("Sensor de oxigeno senal atascada en pobre - banco 1 sensor 2", "O2 Sensor Signal Biased/Stuck Lean Bank 1 Sensor 2"),
    "P2271": ("Sensor de oxigeno senal atascada en rico - banco 1 sensor 2", "O2 Sensor Signal Biased/Stuck Rich Bank 1 Sensor 2"),
    "P2279": ("Fuga en el sistema de admision de aire", "Intake Air System Leak"),
    "P2610": ("Temporizador de posicion de apagado del motor del modulo de control", "ECM/PCM Internal Engine Off Timer Performance"),
}


def lookup_dtc(code: str) -> tuple[str, str]:
    """Return ``(spanish, english)`` descriptions for a DTC code."""
    if code in DTC_DATABASE:
        return DTC_DATABASE[code]
    return (
        f"Codigo de falla {code} - descripcion no disponible",
        f"Fault code {code} - description not available",
    )


# ---------------------------------------------------------------------------
# DTC Reader
# ---------------------------------------------------------------------------

class DTCReader:
    """
    Reads, decodes, and classifies OBD-II Diagnostic Trouble Codes.

    Usage::

        mgr = OBDConnectionManager()
        await mgr.connect()
        reader = DTCReader(mgr)
        result = await reader.full_scan()
    """

    def __init__(self, manager: OBDConnectionManager) -> None:
        self._mgr = manager

    # -- public API ----------------------------------------------------------

    async def full_scan(self) -> DTCScanResult:
        """Read stored, pending, and permanent DTCs plus MIL status."""
        stored = await self.read_stored()
        pending = await self.read_pending()
        permanent = await self.read_permanent()
        mil = await self._check_mil()

        # Attach freeze frames to stored codes
        for rec in stored:
            rec.freeze_frame = await self.read_freeze_frame(rec.code)

        result = DTCScanResult(
            stored=stored,
            pending=pending,
            permanent=permanent,
            mil_on=mil,
            dtc_count=len(stored) + len(pending) + len(permanent),
            timestamp=time.time(),
        )
        logger.info(
            "DTC scan: stored=%d pending=%d permanent=%d MIL=%s",
            len(stored), len(pending), len(permanent), mil,
        )
        return result

    async def read_stored(self) -> list[DTCRecord]:
        """Mode 03 - stored DTCs."""
        return await self._read_dtcs(obd.commands.GET_DTC, DTCType.STORED)

    async def read_pending(self) -> list[DTCRecord]:
        """Mode 07 - pending DTCs."""
        cmd = getattr(obd.commands, "GET_FREEZE_DTC", None)
        if cmd is None:
            # python-OBD may label it differently
            cmd = obd.commands.GET_DTC
        return await self._read_dtcs(cmd, DTCType.PENDING)

    async def read_permanent(self) -> list[DTCRecord]:
        """Mode 0A - permanent DTCs (if supported)."""
        # python-OBD does not have a built-in Mode 0A command;
        # we craft a raw one.
        try:
            cmd = obd.OBDCommand(
                "PERMANENT_DTC",
                "Permanent DTCs",
                b"0A",
                0,
                self._decode_dtc_response,
                obd.ECU.ALL,
                False,
            )
            resp = await self._mgr.query(cmd)
            if resp is None or resp.is_null():
                return []
            codes: list[tuple[str, str]] = resp.value if isinstance(resp.value, list) else []
            return [self._build_record(c, DTCType.PERMANENT) for c, _ in codes]
        except Exception as exc:
            logger.warning("Permanent DTC read failed: %s", exc)
            return []

    async def read_freeze_frame(self, dtc_code: str) -> Optional[dict[str, Any]]:
        """
        Mode 02 - read freeze frame data associated with a DTC.

        Returns a dict of PID name -> value, or ``None`` on failure.
        """
        if not self._mgr.is_connected:
            return None

        frame: dict[str, Any] = {}
        # Freeze-frame PIDs mirror Mode 01 but use Mode 02 + frame number 0
        freeze_pids = [
            "COOLANT_TEMP", "ENGINE_LOAD", "RPM", "SPEED",
            "SHORT_FUEL_TRIM_1", "LONG_FUEL_TRIM_1",
            "INTAKE_PRESSURE", "TIMING_ADVANCE", "INTAKE_TEMP",
        ]
        for pid_name in freeze_pids:
            cmd = getattr(obd.commands, pid_name, None)
            if cmd is None:
                continue
            try:
                resp = await self._mgr.query(cmd)
                if resp and not resp.is_null():
                    val = resp.value
                    if hasattr(val, "magnitude"):
                        val = round(float(val.magnitude), 2)
                    frame[pid_name] = val
            except Exception:
                pass

        return frame if frame else None

    async def clear_dtcs(self) -> bool:
        """
        Mode 04 - clear all stored DTCs and reset MIL.

        Returns ``True`` on success.
        """
        try:
            cmd = obd.commands.CLEAR_DTC
            resp = await self._mgr.query(cmd)
            if resp is not None:
                logger.info("DTCs cleared successfully")
                return True
        except Exception as exc:
            logger.error("Failed to clear DTCs: %s", exc)
        return False

    # -- MIL status ----------------------------------------------------------

    async def _check_mil(self) -> bool:
        """Read the MIL (check-engine light) status via Mode 01 PID 01."""
        try:
            cmd = obd.commands.STATUS
            resp = await self._mgr.query(cmd)
            if resp and not resp.is_null():
                return bool(resp.value.MIL)
        except Exception as exc:
            logger.warning("MIL status check failed: %s", exc)
        return False

    # -- internal helpers ----------------------------------------------------

    async def _read_dtcs(
        self, command: obd.OBDCommand, dtc_type: DTCType,
    ) -> list[DTCRecord]:
        """Execute a DTC-reading command and decode the response."""
        try:
            resp = await self._mgr.query(command)
            if resp is None or resp.is_null():
                return []
            codes: list[tuple[str, str]] = resp.value if isinstance(resp.value, list) else []
            return [self._build_record(c, dtc_type) for c, _ in codes]
        except Exception as exc:
            logger.warning("DTC read (%s) failed: %s", dtc_type.value, exc)
            return []

    @staticmethod
    def _build_record(code: str, dtc_type: DTCType) -> DTCRecord:
        """Create a fully-populated DTCRecord from a raw code string."""
        desc_es, desc_en = lookup_dtc(code)
        return DTCRecord(
            code=code,
            type=dtc_type,
            category=get_category(code),
            severity=classify_severity(code),
            description_es=desc_es,
            description_en=desc_en,
            timestamp=time.time(),
        )

    @staticmethod
    def _decode_dtc_response(messages: list) -> list[tuple[str, str]]:
        """
        Decode raw DTC bytes into ``(code, description)`` tuples.

        Each DTC is 2 bytes:
        - Bits 15-14: first character  (00=P, 01=C, 10=B, 11=U)
        - Bits 13-12: second character (0-3)
        - Bits 11-8:  third character  (0-F hex)
        - Bits  7-4:  fourth character (0-F hex)
        - Bits  3-0:  fifth character  (0-F hex)
        """
        FIRST_CHAR = {0: "P", 1: "C", 2: "B", 3: "U"}
        results: list[tuple[str, str]] = []

        for msg in messages:
            data = msg.data if hasattr(msg, "data") else msg
            if not isinstance(data, (bytes, bytearray)):
                continue
            # Skip mode byte
            payload = data[1:] if len(data) > 1 else data
            for i in range(0, len(payload) - 1, 2):
                b0 = payload[i]
                b1 = payload[i + 1]
                if b0 == 0 and b1 == 0:
                    continue  # padding

                first_idx = (b0 >> 6) & 0x03
                first_char = FIRST_CHAR.get(first_idx, "P")
                second_char = str((b0 >> 4) & 0x03)
                third_char = format(b0 & 0x0F, "X")
                fourth_char = format((b1 >> 4) & 0x0F, "X")
                fifth_char = format(b1 & 0x0F, "X")

                code = f"{first_char}{second_char}{third_char}{fourth_char}{fifth_char}"
                desc_es, _ = lookup_dtc(code)
                results.append((code, desc_es))

        return results

    # -- serialisation -------------------------------------------------------

    @staticmethod
    def record_to_dict(rec: DTCRecord) -> dict[str, Any]:
        return {
            "code": rec.code,
            "type": rec.type.value,
            "category": rec.category.value,
            "severity": rec.severity.value,
            "description_es": rec.description_es,
            "description_en": rec.description_en,
            "freeze_frame": rec.freeze_frame,
            "timestamp": rec.timestamp,
        }

    @staticmethod
    def scan_result_to_dict(result: DTCScanResult) -> dict[str, Any]:
        return {
            "stored": [DTCReader.record_to_dict(r) for r in result.stored],
            "pending": [DTCReader.record_to_dict(r) for r in result.pending],
            "permanent": [DTCReader.record_to_dict(r) for r in result.permanent],
            "mil_on": result.mil_on,
            "dtc_count": result.dtc_count,
            "timestamp": result.timestamp,
        }
