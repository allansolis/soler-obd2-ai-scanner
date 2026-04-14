"""
SOLER OBD2 AI Scanner - ECU Map Type Catalog
=============================================
Definitive reference of ALL ECU map types used in professional tuning
(WinOLS, ECM Titanium, DAMOS, EVC, etc.).

Contains 100+ map type definitions organized by category with full
metadata including axes, units, safe ranges, and Spanish descriptions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MapCategory(str, Enum):
    """Top-level ECU map categories."""

    FUEL = "fuel_system"
    IGNITION = "ignition_system"
    BOOST = "boost_turbo"
    AIR = "air_management"
    VVT = "variable_valve_timing"
    EMISSIONS = "emission_control"
    TORQUE = "torque_management"
    TRANSMISSION = "transmission"
    COOLING = "cooling_thermal"
    LIMITERS = "speed_rpm_limiters"
    DIESEL = "diesel_specific"
    DELETES = "deletes_disables"


class FuelType(str, Enum):
    """Supported fuel types."""

    GASOLINE = "gasoline"
    DIESEL = "diesel"
    FLEX = "flex_fuel"
    ETHANOL = "ethanol_e85"
    LPG = "lpg"
    CNG = "cng"
    HYDROGEN = "hydrogen"


# ---------------------------------------------------------------------------
# Map type definition dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ECUMapType:
    """Definition of a single ECU calibration map type.

    This is a *type definition* (schema), not actual map data.  It
    describes what the map represents, its axes, units, safe ranges,
    and professional-tuning metadata.
    """

    # Identifiers
    name: str                          # English snake_case identifier
    display_name: str                  # Spanish descriptive name
    category: MapCategory

    # Description
    description: str                   # Spanish description of purpose

    # Axis definitions
    x_axis_name: str
    x_axis_unit: str
    y_axis_name: str = ""
    y_axis_unit: str = ""

    # Value definition
    value_unit: str = ""
    value_min: float = 0.0
    value_max: float = 0.0

    # Relationships & metadata
    affects: tuple[str, ...] = ()
    safety_critical: bool = False
    requires_dyno: bool = False
    supported_fuel_types: tuple[str, ...] = (
        FuelType.GASOLINE,
        FuelType.DIESEL,
    )

    # Optional notes for tuners
    tuning_notes: str = ""


# ===================================================================
# 1. FUEL SYSTEM MAPS (Mapas de Combustible)
# ===================================================================

FUEL_INJECTION_BASE = ECUMapType(
    name="fuel_injection_base",
    display_name="Mapa base de inyeccion de combustible",
    category=MapCategory.FUEL,
    description=(
        "Mapa principal de ancho de pulso del inyector. Define la cantidad "
        "base de combustible inyectado en funcion de RPM y carga del motor. "
        "Es el mapa mas importante para la calibracion de mezcla aire-combustible."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="ms",
    value_min=0.0,
    value_max=25.0,
    affects=("potencia", "consumo", "emisiones", "lambda", "temperatura_escape"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL, FuelType.LPG, FuelType.CNG,
    ),
    tuning_notes="Verificar lambda en cada celda con wideband. Nunca empobrecer mas de lambda 0.85 en WOT.",
)

FUEL_COLD_START_ENRICHMENT = ECUMapType(
    name="fuel_cold_start_enrichment",
    display_name="Enriquecimiento de arranque en frio",
    category=MapCategory.FUEL,
    description=(
        "Porcentaje de enriquecimiento de combustible adicional durante el "
        "arranque en frio, en funcion de la temperatura del refrigerante. "
        "Compensa la mala vaporizacion del combustible con motor frio."
    ),
    x_axis_name="Temperatura refrigerante",
    x_axis_unit="degC",
    y_axis_name="",
    y_axis_unit="",
    value_unit="% enriquecimiento",
    value_min=0.0,
    value_max=80.0,
    affects=("arranque_frio", "emisiones_frio", "consumo", "catalizador"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL,
        FuelType.LPG, FuelType.CNG,
    ),
)

FUEL_ACCEL_ENRICHMENT = ECUMapType(
    name="fuel_accel_enrichment",
    display_name="Enriquecimiento por aceleracion (AE)",
    category=MapCategory.FUEL,
    description=(
        "Combustible adicional inyectado durante aceleración rapida. Se basa "
        "en la tasa de cambio de la posicion del acelerador (dTPS/dt). "
        "Previene empobrecimiento transitorio y huecos de potencia."
    ),
    x_axis_name="dTPS/dt",
    x_axis_unit="%/s",
    y_axis_name="RPM",
    y_axis_unit="rpm",
    value_unit="ms adicional",
    value_min=0.0,
    value_max=5.0,
    affects=("respuesta_acelerador", "driveability", "emisiones_transitorias"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
)

FUEL_DECEL_CUTOFF = ECUMapType(
    name="fuel_decel_cutoff",
    display_name="Corte de inyeccion en desaceleracion (DFCO)",
    category=MapCategory.FUEL,
    description=(
        "Mapa de activacion/desactivacion del corte de combustible durante "
        "desaceleracion. Reduce consumo y emisiones cuando el conductor "
        "levanta el pie del acelerador a RPM medias/altas."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="on/off",
    value_min=0.0,
    value_max=1.0,
    affects=("consumo", "emisiones", "freno_motor"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
)

FUEL_CRANKING_PULSE = ECUMapType(
    name="fuel_cranking_pulse",
    display_name="Pulso de inyeccion durante arranque (cranking)",
    category=MapCategory.FUEL,
    description=(
        "Ancho de pulso del inyector durante el arranque del motor, en funcion "
        "de la temperatura del refrigerante. Valores mas altos con motor frio "
        "para garantizar arranque confiable."
    ),
    x_axis_name="Temperatura refrigerante",
    x_axis_unit="degC",
    y_axis_name="",
    y_axis_unit="",
    value_unit="ms",
    value_min=0.5,
    value_max=30.0,
    affects=("arranque", "arranque_frio", "bateria"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
)

LAMBDA_TARGET = ECUMapType(
    name="lambda_target",
    display_name="Mapa objetivo de Lambda / AFR",
    category=MapCategory.FUEL,
    description=(
        "Define la relacion aire-combustible objetivo (valor lambda) para cada "
        "punto de operacion RPM x Carga. Lambda 1.0 = estequiometrico, "
        "<1.0 = rico (potencia), >1.0 = pobre (economia)."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="lambda",
    value_min=0.70,
    value_max=1.20,
    affects=("potencia", "consumo", "emisiones", "temperatura_escape", "catalizador"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL,
        FuelType.LPG, FuelType.CNG,
    ),
    tuning_notes="En WOT gasolina: lambda 0.78-0.85. Nunca >0.90 en carga maxima.",
)

FUEL_PRESSURE_TARGET = ECUMapType(
    name="fuel_pressure_target",
    display_name="Presion objetivo de combustible",
    category=MapCategory.FUEL,
    description=(
        "Presion de combustible objetivo en el riel de inyeccion. En sistemas "
        "con regulador de presion electronico o bombas de alta presion GDI."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="bar",
    value_min=2.0,
    value_max=350.0,
    affects=("atomizacion", "potencia", "emisiones", "ruido_inyector"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX),
)

INJECTOR_DEAD_TIME = ECUMapType(
    name="injector_dead_time",
    display_name="Tiempo muerto del inyector / offset de bateria",
    category=MapCategory.FUEL,
    description=(
        "Compensacion del tiempo de apertura mecanica del inyector en funcion "
        "del voltaje de bateria. Sin esta correccion, la mezcla se empobrece "
        "con voltaje bajo."
    ),
    x_axis_name="Voltaje bateria",
    x_axis_unit="V",
    y_axis_name="",
    y_axis_unit="",
    value_unit="ms",
    value_min=0.0,
    value_max=3.0,
    affects=("precision_inyeccion", "lambda", "ralenti"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL, FuelType.LPG, FuelType.CNG,
    ),
)

FUEL_RAIL_PRESSURE_GDI = ECUMapType(
    name="fuel_rail_pressure_gdi",
    display_name="Presion de riel GDI (inyeccion directa)",
    category=MapCategory.FUEL,
    description=(
        "Presion objetivo del riel de alta presion en motores de inyeccion "
        "directa de gasolina (GDI/FSI/TFSI). Presiones tipicas de 50-200 bar, "
        "controladas por la bomba de alta presion mecanica."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="bar",
    value_min=30.0,
    value_max=350.0,
    affects=("atomizacion", "potencia", "emisiones_particulas", "ruido"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
)

DIESEL_INJECTION_TIMING = ECUMapType(
    name="diesel_injection_timing",
    display_name="Timing de inyeccion diesel (SOI)",
    category=MapCategory.FUEL,
    description=(
        "Angulo de inicio de inyeccion principal en motores diesel, en grados "
        "antes del PMS (BTDC). Controla el inicio de la combustion, afecta "
        "NOx, ruido y eficiencia."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="deg BTDC",
    value_min=-5.0,
    value_max=25.0,
    affects=("potencia", "emisiones_nox", "ruido_diesel", "eficiencia", "temperatura_escape"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(FuelType.DIESEL,),
)

PILOT_INJECTION_QTY = ECUMapType(
    name="pilot_injection_qty",
    display_name="Cantidad de inyeccion piloto (diesel)",
    category=MapCategory.FUEL,
    description=(
        "Cantidad de combustible en la pre-inyeccion piloto en motores diesel "
        "common rail. Reduce el ruido de combustion y las emisiones de NOx "
        "al pre-calentar la camara de combustion."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="mm3/stroke",
    value_min=0.0,
    value_max=5.0,
    affects=("ruido_diesel", "emisiones_nox", "suavidad_marcha"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL,),
)

MAIN_INJECTION_QTY = ECUMapType(
    name="main_injection_qty",
    display_name="Cantidad de inyeccion principal (diesel)",
    category=MapCategory.FUEL,
    description=(
        "Cantidad de combustible en la inyeccion principal diesel. Es el mapa "
        "mas critico en motores diesel, determina directamente la potencia "
        "y el par motor."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="mm3/stroke",
    value_min=0.0,
    value_max=80.0,
    affects=("potencia", "par_motor", "consumo", "emisiones", "humo"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(FuelType.DIESEL,),
)

POST_INJECTION_QTY = ECUMapType(
    name="post_injection_qty",
    display_name="Cantidad de inyeccion post (regeneracion DPF)",
    category=MapCategory.FUEL,
    description=(
        "Cantidad de combustible en la post-inyeccion para regeneracion del "
        "filtro de particulas (DPF/FAP). El combustible sin quemar llega al "
        "escape para elevar la temperatura y quemar el hollin acumulado."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="mm3/stroke",
    value_min=0.0,
    value_max=10.0,
    affects=("regeneracion_dpf", "temperatura_escape", "consumo", "aceite"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL,),
)

INJECTION_COUNT = ECUMapType(
    name="injection_count_per_cycle",
    display_name="Numero de inyecciones por ciclo",
    category=MapCategory.FUEL,
    description=(
        "Numero total de eventos de inyeccion por ciclo de combustion "
        "(piloto + pre + principal + post). Motores modernos usan hasta "
        "7-9 inyecciones por ciclo para optimizar combustion."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="count",
    value_min=1.0,
    value_max=9.0,
    affects=("ruido", "emisiones", "suavidad", "consumo"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL, FuelType.GASOLINE),
)

FUEL_WARMUP_ENRICHMENT = ECUMapType(
    name="fuel_warmup_enrichment",
    display_name="Enriquecimiento de calentamiento del motor",
    category=MapCategory.FUEL,
    description=(
        "Factor de enriquecimiento progresivo durante la fase de calentamiento "
        "del motor, desde arranque hasta temperatura de operacion normal. "
        "Se reduce gradualmente conforme sube la temperatura."
    ),
    x_axis_name="Temperatura refrigerante",
    x_axis_unit="degC",
    y_axis_name="Tiempo desde arranque",
    y_axis_unit="s",
    value_unit="factor multiplicador",
    value_min=1.0,
    value_max=1.5,
    affects=("emisiones_frio", "consumo", "calentamiento_catalizador"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
)

FUEL_ALTITUDE_COMPENSATION = ECUMapType(
    name="fuel_altitude_compensation",
    display_name="Compensacion de combustible por altitud",
    category=MapCategory.FUEL,
    description=(
        "Correccion del pulso de inyeccion basada en la presion barometrica "
        "para compensar la menor densidad del aire en altitud. Evita mezcla "
        "rica a grandes alturas."
    ),
    x_axis_name="Presion barometrica",
    x_axis_unit="kPa",
    y_axis_name="",
    y_axis_unit="",
    value_unit="factor multiplicador",
    value_min=0.60,
    value_max=1.05,
    affects=("lambda", "consumo", "potencia_altitud"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL, FuelType.LPG, FuelType.CNG,
    ),
)

CLOSED_LOOP_LAMBDA_LIMITS = ECUMapType(
    name="closed_loop_lambda_limits",
    display_name="Limites de correccion lambda en lazo cerrado",
    category=MapCategory.FUEL,
    description=(
        "Limites maximos de la correccion de combustible por retroalimentacion "
        "de la sonda lambda. Define cuanto puede corregir la ECU antes de "
        "generar un codigo de error de trim de combustible."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="% correccion",
    value_min=-25.0,
    value_max=25.0,
    affects=("adaptacion_combustible", "diagnostico", "dtc"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
)


# ===================================================================
# 2. IGNITION SYSTEM MAPS (Mapas de Encendido)
# ===================================================================

IGNITION_BASE_TIMING = ECUMapType(
    name="ignition_base_timing",
    display_name="Mapa base de avance de encendido",
    category=MapCategory.IGNITION,
    description=(
        "Mapa principal de avance de encendido en grados antes del PMS "
        "(BTDC). Mayor avance = mas potencia pero mayor riesgo de "
        "detonacion. Mapa critico para performance y seguridad del motor."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="deg BTDC",
    value_min=0.0,
    value_max=45.0,
    affects=("potencia", "par_motor", "detonacion", "temperatura_escape", "consumo"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL,
        FuelType.LPG, FuelType.CNG,
    ),
    tuning_notes="Avanzar gradualmente 1-2 grados. Monitorear knock con sensor de detonacion.",
)

KNOCK_RETARD_LIMIT = ECUMapType(
    name="knock_retard_limit",
    display_name="Limite de retardo por detonacion (knock)",
    category=MapCategory.IGNITION,
    description=(
        "Maximo retardo de encendido permitido cuando se detecta detonacion. "
        "La ECU retarda el timing hasta este limite para proteger el motor."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="deg retardo max",
    value_min=0.0,
    value_max=20.0,
    affects=("proteccion_motor", "potencia", "detonacion"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL,
        FuelType.LPG, FuelType.CNG,
    ),
)

KNOCK_SENSITIVITY = ECUMapType(
    name="knock_sensitivity",
    display_name="Sensibilidad del sensor de detonacion",
    category=MapCategory.IGNITION,
    description=(
        "Umbral de deteccion del sensor de knock. Valores mas bajos = mayor "
        "sensibilidad (detecta detonacion mas leve). Se ajusta por RPM y "
        "carga para filtrar ruido mecanico normal."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="umbral (V o conteo)",
    value_min=0.0,
    value_max=10.0,
    affects=("deteccion_knock", "proteccion_motor", "falsos_positivos"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL,
        FuelType.LPG, FuelType.CNG,
    ),
)

DWELL_TIME = ECUMapType(
    name="dwell_time",
    display_name="Tiempo de carga de bobina (dwell)",
    category=MapCategory.IGNITION,
    description=(
        "Tiempo de carga de la bobina de encendido antes de la chispa. "
        "Depende de RPM y voltaje de bateria. Dwell insuficiente = chispa "
        "debil, excesivo = sobrecalentamiento de bobina."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Voltaje bateria",
    y_axis_unit="V",
    value_unit="ms",
    value_min=0.5,
    value_max=8.0,
    affects=("calidad_chispa", "arranque", "bobina_vida_util"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL,
        FuelType.LPG, FuelType.CNG,
    ),
)

IGNITION_COLD_CORRECTION = ECUMapType(
    name="ignition_cold_correction",
    display_name="Correccion de encendido por temperatura (frio)",
    category=MapCategory.IGNITION,
    description=(
        "Grados de avance adicional cuando el motor esta frio. El combustible "
        "se vaporiza peor con motor frio, requiriendo mas avance para "
        "compensar la combustion mas lenta."
    ),
    x_axis_name="Temperatura refrigerante",
    x_axis_unit="degC",
    y_axis_name="",
    y_axis_unit="",
    value_unit="deg adicional",
    value_min=-5.0,
    value_max=15.0,
    affects=("ralenti_frio", "calentamiento", "emisiones_frio"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL,
        FuelType.LPG, FuelType.CNG,
    ),
)

INDIVIDUAL_CYLINDER_TRIM = ECUMapType(
    name="individual_cylinder_trim",
    display_name="Ajuste individual de timing por cilindro",
    category=MapCategory.IGNITION,
    description=(
        "Offset de avance de encendido individual para cada cilindro. "
        "Compensa diferencias de detonacion entre cilindros por variaciones "
        "termicas, flujo de aire o tolerancias de fabricacion."
    ),
    x_axis_name="Numero de cilindro",
    x_axis_unit="cyl #",
    y_axis_name="RPM",
    y_axis_unit="rpm",
    value_unit="deg offset",
    value_min=-5.0,
    value_max=5.0,
    affects=("balance_cilindros", "detonacion", "suavidad"),
    safety_critical=False,
    requires_dyno=True,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL,
    ),
)

KNOCK_RECOVERY_RATE = ECUMapType(
    name="knock_recovery_rate",
    display_name="Tasa de recuperacion tras detonacion",
    category=MapCategory.IGNITION,
    description=(
        "Velocidad a la que el avance de encendido se recupera tras un "
        "evento de detonacion. Define cuantos grados por segundo o por "
        "ciclo se anade de vuelta el avance retardado."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="deg/s",
    value_min=0.1,
    value_max=5.0,
    affects=("respuesta_potencia", "proteccion_motor"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL,
        FuelType.LPG, FuelType.CNG,
    ),
)


# ===================================================================
# 3. BOOST / TURBO MAPS (Mapas de Turbo)
# ===================================================================

BOOST_TARGET = ECUMapType(
    name="boost_target",
    display_name="Mapa de presion de turbo objetivo",
    category=MapCategory.BOOST,
    description=(
        "Presion de sobrealimentacion objetivo (boost) en funcion de RPM "
        "y posicion del acelerador. Define cuanto boost pide el conductor "
        "en cada punto de operacion."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Posicion acelerador",
    y_axis_unit="%",
    value_unit="bar",
    value_min=0.0,
    value_max=3.5,
    affects=("potencia", "par_motor", "turbo_vida_util", "fiabilidad"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL),
    tuning_notes="No exceder presion maxima de intercooler y limites mecanicos del bloque.",
)

WASTEGATE_DUTY = ECUMapType(
    name="wastegate_duty",
    display_name="Ciclo de trabajo de la wastegate",
    category=MapCategory.BOOST,
    description=(
        "Porcentaje de duty cycle de la solenoide de la wastegate. "
        "Controla la apertura de la valvula de alivio del turbo. "
        "Mayor duty = mas boost (wastegate mas cerrada)."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Boost objetivo",
    y_axis_unit="bar",
    value_unit="% duty",
    value_min=0.0,
    value_max=100.0,
    affects=("control_boost", "respuesta_turbo", "spool_up"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL),
)

VGT_POSITION = ECUMapType(
    name="vgt_vnt_position",
    display_name="Posicion de la turbina de geometria variable (VGT/VNT)",
    category=MapCategory.BOOST,
    description=(
        "Posicion de los alabes de la turbina de geometria variable. "
        "Controla el flujo de gases de escape sobre la rueda de la turbina. "
        "Posicion cerrada = mas boost a bajas RPM."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="% posicion",
    value_min=0.0,
    value_max=100.0,
    affects=("boost_baja_rpm", "respuesta", "contrapresion_escape", "egr"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(FuelType.DIESEL, FuelType.GASOLINE),
)

BOOST_LIMIT = ECUMapType(
    name="boost_limit",
    display_name="Limite maximo de boost por RPM",
    category=MapCategory.BOOST,
    description=(
        "Presion maxima absoluta de boost permitida en funcion de RPM. "
        "Proteccion contra sobreboost. Si se excede, la ECU abre la "
        "wastegate completamente o reduce combustible."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="",
    y_axis_unit="",
    value_unit="bar max",
    value_min=0.0,
    value_max=4.0,
    affects=("proteccion_turbo", "proteccion_motor", "fiabilidad"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL),
)

OVERBOOST = ECUMapType(
    name="overboost",
    display_name="Mapa de overboost (sobrealimentacion temporal)",
    category=MapCategory.BOOST,
    description=(
        "Boost adicional temporal permitido durante aceleracion agresiva. "
        "Proporciona pico de potencia extra por tiempo limitado (tipico "
        "5-15 segundos) antes de decaer al boost normal."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Tiempo",
    y_axis_unit="s",
    value_unit="bar extra",
    value_min=0.0,
    value_max=0.5,
    affects=("potencia_pico", "aceleracion", "turbo_esfuerzo"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL),
)

COMPRESSOR_SURGE_LIMIT = ECUMapType(
    name="compressor_surge_limit",
    display_name="Limite de surge del compresor",
    category=MapCategory.BOOST,
    description=(
        "Mapa de limite de surge (compressor surge) que define la presion "
        "maxima permitida para un flujo de aire dado. Protege el compresor "
        "del turbo contra flujo invertido destructivo."
    ),
    x_axis_name="Flujo masico de aire",
    x_axis_unit="g/s",
    y_axis_name="",
    y_axis_unit="",
    value_unit="pressure ratio",
    value_min=1.0,
    value_max=4.0,
    affects=("proteccion_turbo", "compressor_surge", "fiabilidad"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL),
)

EXHAUST_BACKPRESSURE_TARGET = ECUMapType(
    name="exhaust_backpressure_target",
    display_name="Contrapresion de escape objetivo",
    category=MapCategory.BOOST,
    description=(
        "Presion objetivo en el colector de escape, aguas arriba de la "
        "turbina. Relevante para control de EGR y proteccion de "
        "componentes de escape."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="bar",
    value_min=0.0,
    value_max=4.0,
    affects=("egr", "turbo", "temperatura_escape", "valvulas"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL, FuelType.GASOLINE),
)

BOOST_SCRAMBLE = ECUMapType(
    name="boost_scramble",
    display_name="Boost scramble / kickdown boost extra",
    category=MapCategory.BOOST,
    description=(
        "Boost adicional activado por kickdown completo del acelerador. "
        "Similar a overboost pero vinculado a la posicion maxima del "
        "pedal. Comun en vehiculos europeos modernos."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Marcha",
    y_axis_unit="gear #",
    value_unit="bar extra",
    value_min=0.0,
    value_max=0.3,
    affects=("potencia_pico", "aceleracion", "respuesta"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL),
)


# ===================================================================
# 4. AIR MANAGEMENT MAPS (Mapas de Aire)
# ===================================================================

THROTTLE_TARGET = ECUMapType(
    name="throttle_target",
    display_name="Mapa de apertura del cuerpo de aceleracion",
    category=MapCategory.AIR,
    description=(
        "Traduce la posicion del pedal del acelerador a apertura real del "
        "cuerpo de aceleracion (drive-by-wire). Incluye curvas no lineales "
        "para suavidad y respuesta controlada."
    ),
    x_axis_name="Posicion pedal",
    x_axis_unit="%",
    y_axis_name="RPM",
    y_axis_unit="rpm",
    value_unit="% apertura mariposa",
    value_min=0.0,
    value_max=100.0,
    affects=("respuesta_acelerador", "driveability", "consumo"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL,
        FuelType.LPG, FuelType.CNG,
    ),
)

ELECTRONIC_THROTTLE_POSITION = ECUMapType(
    name="electronic_throttle_position",
    display_name="Posicion electronica de la mariposa (ETC)",
    category=MapCategory.AIR,
    description=(
        "Posicion objetivo de la mariposa de aceleracion electronica "
        "considerando modo de conduccion (eco, normal, sport), control "
        "de crucero y limitaciones de torque."
    ),
    x_axis_name="Torque demandado",
    x_axis_unit="Nm",
    y_axis_name="RPM",
    y_axis_unit="rpm",
    value_unit="% apertura",
    value_min=0.0,
    value_max=100.0,
    affects=("respuesta", "control_torque", "modos_conduccion"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
)

IDLE_AIR_CONTROL = ECUMapType(
    name="idle_air_control",
    display_name="Control de aire de ralenti (IAC/IACV)",
    category=MapCategory.AIR,
    description=(
        "Posicion de la valvula de control de aire de ralenti en funcion "
        "de la temperatura del refrigerante. Mayor apertura con motor frio "
        "para mantener RPM de ralenti estable."
    ),
    x_axis_name="Temperatura refrigerante",
    x_axis_unit="degC",
    y_axis_name="",
    y_axis_unit="",
    value_unit="pasos / % apertura",
    value_min=0.0,
    value_max=255.0,
    affects=("ralenti", "estabilidad_ralenti", "arranque_frio"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
)

INTAKE_MANIFOLD_FLAP = ECUMapType(
    name="intake_manifold_flap",
    display_name="Posicion de aleta del colector de admision",
    category=MapCategory.AIR,
    description=(
        "Posicion de las aletas/flaps del colector de admision (tumble o "
        "swirl flaps). Mejoran la turbulencia del aire a baja carga para "
        "mejorar combustion y reducir emisiones."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="% posicion",
    value_min=0.0,
    value_max=100.0,
    affects=("turbulencia_aire", "combustion", "emisiones", "par_bajo"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL),
)

VARIABLE_INTAKE_RUNNER = ECUMapType(
    name="variable_intake_runner",
    display_name="Longitud variable del colector de admision (VICS/DISA)",
    category=MapCategory.AIR,
    description=(
        "Control de la longitud del conducto de admision variable. "
        "Conducto largo = mas torque a bajas RPM, conducto corto = mas "
        "potencia a altas RPM. Conmutacion basada en RPM."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="",
    y_axis_unit="",
    value_unit="posicion (corto/largo)",
    value_min=0.0,
    value_max=1.0,
    affects=("par_motor", "potencia", "eficiencia_volumetrica"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
)

MAF_CALIBRATION = ECUMapType(
    name="maf_calibration",
    display_name="Calibracion del sensor MAF (caudalimetro)",
    category=MapCategory.AIR,
    description=(
        "Tabla de conversion del sensor de flujo masico de aire (MAF). "
        "Convierte el voltaje de salida del sensor a gramos por segundo "
        "de aire. Critico para calculo correcto de combustible."
    ),
    x_axis_name="Voltaje sensor MAF",
    x_axis_unit="V",
    y_axis_name="",
    y_axis_unit="",
    value_unit="g/s",
    value_min=0.0,
    value_max=500.0,
    affects=("calculo_combustible", "lambda", "potencia", "diagnostico"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL, FuelType.LPG, FuelType.CNG,
    ),
)

MAP_SENSOR_CALIBRATION = ECUMapType(
    name="map_sensor_calibration",
    display_name="Calibracion del sensor MAP (presion de admision)",
    category=MapCategory.AIR,
    description=(
        "Tabla de conversion del sensor de presion absoluta del colector "
        "(MAP). Convierte voltaje a kilopascales. Usado como referencia "
        "principal de carga en motores speed-density."
    ),
    x_axis_name="Voltaje sensor MAP",
    x_axis_unit="V",
    y_axis_name="",
    y_axis_unit="",
    value_unit="kPa",
    value_min=0.0,
    value_max=400.0,
    affects=("calculo_carga", "combustible", "encendido", "boost"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL, FuelType.LPG, FuelType.CNG,
    ),
)

IDLE_RPM_TARGET = ECUMapType(
    name="idle_rpm_target",
    display_name="RPM objetivo de ralenti",
    category=MapCategory.AIR,
    description=(
        "RPM objetivo del ralenti en funcion de la temperatura del motor "
        "y carga electrica. Mayor RPM con motor frio o con cargas "
        "electricas activas (A/C, luces, etc.)."
    ),
    x_axis_name="Temperatura refrigerante",
    x_axis_unit="degC",
    y_axis_name="Carga electrica",
    y_axis_unit="on/off",
    value_unit="rpm",
    value_min=500.0,
    value_max=1500.0,
    affects=("ralenti", "consumo", "vibracion", "confort"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL, FuelType.LPG, FuelType.CNG,
    ),
)


# ===================================================================
# 5. VARIABLE VALVE TIMING (VVT)
# ===================================================================

VVT_INTAKE_ADVANCE = ECUMapType(
    name="vvt_intake_advance",
    display_name="Avance de arbol de levas de admision (VVT intake)",
    category=MapCategory.VVT,
    description=(
        "Angulo de avance del arbol de levas de admision controlado por "
        "actuador hidraulico o electrico. Optimiza llenado del cilindro "
        "y cruce de valvulas segun RPM y carga."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="deg avance",
    value_min=0.0,
    value_max=60.0,
    affects=("par_motor", "potencia", "consumo", "emisiones", "egr_interno"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
    tuning_notes="Verificar que no haya contacto piston-valvula en avance maximo.",
)

VVT_EXHAUST_ADVANCE = ECUMapType(
    name="vvt_exhaust_advance",
    display_name="Avance de arbol de levas de escape (VVT exhaust)",
    category=MapCategory.VVT,
    description=(
        "Angulo de avance/retardo del arbol de levas de escape. Controla "
        "la cantidad de gases residuales y EGR interno. Afecta el cruce "
        "de valvulas y la eficiencia de barrido."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="deg avance",
    value_min=-30.0,
    value_max=30.0,
    affects=("egr_interno", "par_motor", "emisiones_nox", "eficiencia_barrido"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
)

VALVE_LIFT_SWITCH = ECUMapType(
    name="valve_lift_switch",
    display_name="Conmutacion de alzada de valvula (VTEC/Valvetronic)",
    category=MapCategory.VVT,
    description=(
        "Umbral de RPM para conmutacion entre perfiles de leva de baja y "
        "alta alzada (VTEC, MIVEC, Valvetronic, MultiAir). Alzada alta = "
        "mayor flujo = mas potencia a altas RPM."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="",
    y_axis_unit="",
    value_unit="perfil leva (bajo/alto)",
    value_min=0.0,
    value_max=1.0,
    affects=("potencia_alta_rpm", "par_baja_rpm", "sonido_motor"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
)

CAM_PHASER_OCV_DUTY = ECUMapType(
    name="cam_phaser_ocv_duty",
    display_name="Ciclo de trabajo de valvula OCV del cam phaser",
    category=MapCategory.VVT,
    description=(
        "Duty cycle de la valvula de control de aceite (OCV) que mueve "
        "el actuador del cam phaser. Controla la velocidad y posicion "
        "del avance/retardo del arbol de levas."
    ),
    x_axis_name="Posicion cam objetivo",
    x_axis_unit="deg",
    y_axis_name="Presion aceite",
    y_axis_unit="bar",
    value_unit="% duty",
    value_min=0.0,
    value_max=100.0,
    affects=("velocidad_respuesta_vvt", "precision_cam", "ruido_hidraulico"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
)

CONTINUOUS_VALVE_LIFT = ECUMapType(
    name="continuous_valve_lift",
    display_name="Alzada de valvula continua (Valvetronic/MultiAir)",
    category=MapCategory.VVT,
    description=(
        "Alzada de valvula objetivo en sistemas de control continuo como "
        "BMW Valvetronic o Fiat MultiAir. Reemplaza la mariposa "
        "convencional controlando directamente el flujo de aire."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="mm alzada",
    value_min=0.2,
    value_max=12.0,
    affects=("flujo_aire", "perdidas_bombeo", "consumo", "respuesta"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(FuelType.GASOLINE,),
)


# ===================================================================
# 6. EMISSION CONTROL MAPS (Mapas de Emisiones)
# ===================================================================

EGR_VALVE_POSITION = ECUMapType(
    name="egr_valve_position",
    display_name="Posicion de la valvula EGR",
    category=MapCategory.EMISSIONS,
    description=(
        "Porcentaje de apertura de la valvula de recirculacion de gases "
        "de escape (EGR). Recircula gases de escape al colector de "
        "admision para reducir NOx bajando la temperatura de combustion."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="% apertura",
    value_min=0.0,
    value_max=100.0,
    affects=("emisiones_nox", "potencia", "consumo", "hollin", "dpf"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL),
)

DPF_REGEN_TRIGGER = ECUMapType(
    name="dpf_regen_trigger",
    display_name="Activacion de regeneracion del DPF",
    category=MapCategory.EMISSIONS,
    description=(
        "Umbral de carga de hollin que dispara la regeneracion activa del "
        "filtro de particulas (DPF/FAP). Cuando el hollin acumulado alcanza "
        "el limite, la ECU inicia el proceso de regeneracion."
    ),
    x_axis_name="Carga de hollin",
    x_axis_unit="g o g/L",
    y_axis_name="",
    y_axis_unit="",
    value_unit="activar/no activar",
    value_min=0.0,
    value_max=1.0,
    affects=("regeneracion_dpf", "consumo", "temperatura_escape"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL, FuelType.GASOLINE),
)

DPF_REGEN_TEMP_TARGET = ECUMapType(
    name="dpf_regen_temp_target",
    display_name="Temperatura objetivo durante regeneracion DPF",
    category=MapCategory.EMISSIONS,
    description=(
        "Temperatura objetivo del filtro de particulas durante la "
        "regeneracion activa. Tipicamente 550-650 degC para oxidar el "
        "hollin acumulado sin danar el sustrato ceramico."
    ),
    x_axis_name="Fase de regeneracion",
    x_axis_unit="fase",
    y_axis_name="",
    y_axis_unit="",
    value_unit="degC",
    value_min=400.0,
    value_max=700.0,
    affects=("eficiencia_regen", "vida_util_dpf", "seguridad"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL, FuelType.GASOLINE),
)

SCR_ADBLUE_INJECTION = ECUMapType(
    name="scr_adblue_injection",
    display_name="Tasa de inyeccion de AdBlue/DEF (SCR)",
    category=MapCategory.EMISSIONS,
    description=(
        "Cantidad de urea (AdBlue/DEF) inyectada en el sistema SCR para "
        "reducir emisiones de NOx. Dosificacion precisa en funcion de "
        "temperatura del catalizador y concentracion de NOx."
    ),
    x_axis_name="Temperatura catalizador SCR",
    x_axis_unit="degC",
    y_axis_name="NOx pre-SCR",
    y_axis_unit="ppm",
    value_unit="ml/min",
    value_min=0.0,
    value_max=20.0,
    affects=("emisiones_nox", "consumo_adblue", "cristalizacion_scr"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL,),
)

CATALYST_HEATING = ECUMapType(
    name="catalyst_heating_strategy",
    display_name="Estrategia de calentamiento de catalizador",
    category=MapCategory.EMISSIONS,
    description=(
        "Retardo de encendido y enriquecimiento durante arranque en frio "
        "para calentar rapidamente el catalizador hasta su temperatura "
        "de activacion (light-off ~300 degC). Reduce emisiones en frio."
    ),
    x_axis_name="Tiempo desde arranque",
    x_axis_unit="s",
    y_axis_name="Temperatura catalizador",
    y_axis_unit="degC",
    value_unit="deg retardo encendido",
    value_min=0.0,
    value_max=30.0,
    affects=("emisiones_frio", "calentamiento_catalizador", "consumo"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
)

SECONDARY_AIR_INJECTION = ECUMapType(
    name="secondary_air_injection",
    display_name="Inyeccion de aire secundario (SAI)",
    category=MapCategory.EMISSIONS,
    description=(
        "Activacion de la bomba de aire secundario que inyecta aire fresco "
        "en el colector de escape durante arranque en frio. Promueve "
        "post-combustion de HC y CO para calentar el catalizador."
    ),
    x_axis_name="Temperatura refrigerante",
    x_axis_unit="degC",
    y_axis_name="Tiempo desde arranque",
    y_axis_unit="s",
    value_unit="activado/desactivado",
    value_min=0.0,
    value_max=1.0,
    affects=("emisiones_frio", "calentamiento_catalizador"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE,),
)

CANISTER_PURGE = ECUMapType(
    name="canister_purge_duty",
    display_name="Ciclo de trabajo de purga del canister EVAP",
    category=MapCategory.EMISSIONS,
    description=(
        "Duty cycle de la valvula de purga del canister de carbon activado "
        "(sistema EVAP). Purga los vapores de combustible acumulados "
        "reintroduciendolos al motor para su combustion."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="% duty",
    value_min=0.0,
    value_max=100.0,
    affects=("emisiones_evaporativas", "lambda", "ralenti"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
)

LAMBDA_HEATER_CONTROL = ECUMapType(
    name="lambda_sensor_heater",
    display_name="Control del calentador de sonda lambda",
    category=MapCategory.EMISSIONS,
    description=(
        "Duty cycle del calentador de la sonda lambda/O2. Mantiene la "
        "sonda a temperatura optima de operacion (~600-800 degC) para "
        "medicion precisa de oxigeno en el escape."
    ),
    x_axis_name="Temperatura escape estimada",
    x_axis_unit="degC",
    y_axis_name="",
    y_axis_unit="",
    value_unit="% duty",
    value_min=0.0,
    value_max=100.0,
    affects=("precision_lambda", "control_combustible", "emisiones"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL, FuelType.LPG, FuelType.CNG,
    ),
)

NOX_STORAGE_CATALYST = ECUMapType(
    name="nox_storage_catalyst",
    display_name="Regeneracion de catalizador acumulador de NOx (NSC/LNT)",
    category=MapCategory.EMISSIONS,
    description=(
        "Control de regeneracion del catalizador de almacenamiento de NOx "
        "(Lean NOx Trap). Requiere fases periodicas de mezcla rica para "
        "liberar y convertir los NOx acumulados."
    ),
    x_axis_name="NOx acumulado",
    x_axis_unit="g",
    y_axis_name="Temperatura catalizador",
    y_axis_unit="degC",
    value_unit="lambda objetivo regen",
    value_min=0.70,
    value_max=1.0,
    affects=("emisiones_nox", "consumo", "lambda"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL),
)


# ===================================================================
# 7. TORQUE MANAGEMENT MAPS
# ===================================================================

DRIVER_DEMAND_TORQUE = ECUMapType(
    name="driver_demand_torque",
    display_name="Torque demandado por el conductor",
    category=MapCategory.TORQUE,
    description=(
        "Traduce la posicion del pedal del acelerador a una solicitud de "
        "torque en Nm. Es la base del sistema de gestion de torque "
        "moderno (torque-based engine management)."
    ),
    x_axis_name="Posicion pedal",
    x_axis_unit="%",
    y_axis_name="RPM",
    y_axis_unit="rpm",
    value_unit="Nm",
    value_min=0.0,
    value_max=800.0,
    affects=("respuesta_acelerador", "potencia_percibida", "modos_conduccion"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL, FuelType.LPG, FuelType.CNG,
    ),
)

MAX_TORQUE_LIMIT = ECUMapType(
    name="max_torque_limit",
    display_name="Limite maximo de torque del motor",
    category=MapCategory.TORQUE,
    description=(
        "Torque maximo permitido en funcion de RPM. Protege transmision, "
        "embrague y tren motriz. Nunca se supera independientemente de "
        "la demanda del conductor."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="",
    y_axis_unit="",
    value_unit="Nm max",
    value_min=0.0,
    value_max=1000.0,
    affects=("proteccion_transmision", "potencia_maxima", "fiabilidad"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL, FuelType.LPG, FuelType.CNG,
    ),
)

TORQUE_REDUCTION_GEARSHIFT = ECUMapType(
    name="torque_reduction_gearshift",
    display_name="Reduccion de torque para cambio de marcha",
    category=MapCategory.TORQUE,
    description=(
        "Porcentaje de reduccion temporal de torque durante cambios de "
        "marcha en transmisiones automaticas/DCT. Suaviza el cambio y "
        "reduce el desgaste del embrague/sincronizadores."
    ),
    x_axis_name="Velocidad de cambio",
    x_axis_unit="ms",
    y_axis_name="Torque actual",
    y_axis_unit="Nm",
    value_unit="% reduccion",
    value_min=0.0,
    value_max=100.0,
    affects=("suavidad_cambio", "vida_transmision", "confort"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
    ),
)

TORQUE_REDUCTION_TRACTION = ECUMapType(
    name="torque_reduction_traction",
    display_name="Reduccion de torque por control de traccion (TCS)",
    category=MapCategory.TORQUE,
    description=(
        "Reduccion de torque del motor cuando el control de traccion "
        "detecta patinaje de ruedas. La ECU reduce potencia cortando "
        "combustible y/o retardando encendido."
    ),
    x_axis_name="Diferencia velocidad ruedas",
    x_axis_unit="km/h",
    y_axis_name="Velocidad vehiculo",
    y_axis_unit="km/h",
    value_unit="% reduccion torque",
    value_min=0.0,
    value_max=100.0,
    affects=("traccion", "estabilidad", "potencia_rueda"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL, FuelType.LPG, FuelType.CNG,
    ),
)

TORQUE_LIMIT_COOLANT_TEMP = ECUMapType(
    name="torque_limit_coolant_temp",
    display_name="Limitacion de torque por temperatura de refrigerante",
    category=MapCategory.TORQUE,
    description=(
        "Reduccion progresiva del torque maximo cuando la temperatura "
        "del refrigerante supera los limites normales. Proteccion termica "
        "del motor contra sobrecalentamiento."
    ),
    x_axis_name="Temperatura refrigerante",
    x_axis_unit="degC",
    y_axis_name="",
    y_axis_unit="",
    value_unit="Nm max permitido",
    value_min=0.0,
    value_max=800.0,
    affects=("proteccion_termica", "potencia_caliente", "fiabilidad"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL, FuelType.LPG, FuelType.CNG,
    ),
)

TORQUE_LIMIT_IAT = ECUMapType(
    name="torque_limit_iat",
    display_name="Limitacion de torque por temperatura de aire de admision",
    category=MapCategory.TORQUE,
    description=(
        "Reduccion de torque cuando la temperatura del aire de admision "
        "(IAT) es excesiva. Previene detonacion y protege el turbo. "
        "Muy relevante en motores turbo con intercooler insuficiente."
    ),
    x_axis_name="Temperatura aire admision",
    x_axis_unit="degC",
    y_axis_name="",
    y_axis_unit="",
    value_unit="Nm max permitido",
    value_min=0.0,
    value_max=800.0,
    affects=("proteccion_detonacion", "proteccion_turbo", "potencia"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL),
)

CRUISE_CONTROL_TORQUE = ECUMapType(
    name="cruise_control_torque",
    display_name="Torque del control de crucero",
    category=MapCategory.TORQUE,
    description=(
        "Torque objetivo para mantener la velocidad de crucero deseada. "
        "Incluye control PID para mantener velocidad constante en "
        "subidas, bajadas y viento."
    ),
    x_axis_name="Error velocidad",
    x_axis_unit="km/h",
    y_axis_name="Pendiente estimada",
    y_axis_unit="%",
    value_unit="Nm",
    value_min=-200.0,
    value_max=500.0,
    affects=("velocidad_crucero", "consumo", "confort"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL, FuelType.LPG, FuelType.CNG,
    ),
)

TORQUE_LIMIT_OIL_TEMP = ECUMapType(
    name="torque_limit_oil_temp",
    display_name="Limitacion de torque por temperatura de aceite",
    category=MapCategory.TORQUE,
    description=(
        "Reduccion de torque cuando la temperatura del aceite del motor "
        "supera el limite seguro. Aceite demasiado caliente pierde "
        "viscosidad y capacidad de lubricacion."
    ),
    x_axis_name="Temperatura aceite",
    x_axis_unit="degC",
    y_axis_name="",
    y_axis_unit="",
    value_unit="Nm max permitido",
    value_min=0.0,
    value_max=800.0,
    affects=("proteccion_motor", "lubricacion", "fiabilidad"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
    ),
)

TORQUE_LIMIT_EXHAUST_TEMP = ECUMapType(
    name="torque_limit_exhaust_temp",
    display_name="Limitacion de torque por temperatura de escape",
    category=MapCategory.TORQUE,
    description=(
        "Reduccion de potencia cuando la temperatura de gases de escape "
        "excede limites seguros (EGT). Protege turbo, catalizador y "
        "colector de escape de dano termico."
    ),
    x_axis_name="Temperatura escape",
    x_axis_unit="degC",
    y_axis_name="RPM",
    y_axis_unit="rpm",
    value_unit="Nm max permitido",
    value_min=0.0,
    value_max=800.0,
    affects=("proteccion_turbo", "proteccion_catalizador", "fiabilidad"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL),
)


# ===================================================================
# 8. TRANSMISSION MAPS (for automatic/DCT)
# ===================================================================

SHIFT_UPSHIFT = ECUMapType(
    name="shift_upshift",
    display_name="Puntos de cambio ascendente (upshift)",
    category=MapCategory.TRANSMISSION,
    description=(
        "Mapa de velocidad y posicion de acelerador donde la transmision "
        "automatica sube de marcha. Mayor apertura de acelerador = cambio "
        "a RPM mas altas para mantener potencia."
    ),
    x_axis_name="Velocidad vehiculo",
    x_axis_unit="km/h",
    y_axis_name="Posicion acelerador",
    y_axis_unit="%",
    value_unit="marcha objetivo",
    value_min=1.0,
    value_max=10.0,
    affects=("rendimiento", "consumo", "confort", "rpm_cambio"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX),
)

SHIFT_DOWNSHIFT = ECUMapType(
    name="shift_downshift",
    display_name="Puntos de cambio descendente (downshift)",
    category=MapCategory.TRANSMISSION,
    description=(
        "Mapa de velocidad y posicion de acelerador donde la transmision "
        "baja de marcha. Kickdown agresivo baja multiples marchas para "
        "respuesta inmediata de potencia."
    ),
    x_axis_name="Velocidad vehiculo",
    x_axis_unit="km/h",
    y_axis_name="Posicion acelerador",
    y_axis_unit="%",
    value_unit="marcha objetivo",
    value_min=1.0,
    value_max=10.0,
    affects=("respuesta", "kickdown", "freno_motor"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX),
)

TORQUE_CONVERTER_LOCKUP = ECUMapType(
    name="torque_converter_lockup",
    display_name="Bloqueo del convertidor de par (TCC lockup)",
    category=MapCategory.TRANSMISSION,
    description=(
        "Mapa que define cuando el embrague del convertidor de par se "
        "bloquea (lockup) para eliminar deslizamiento y mejorar "
        "eficiencia. Crucial para consumo en carretera."
    ),
    x_axis_name="Velocidad vehiculo",
    x_axis_unit="km/h",
    y_axis_name="Posicion acelerador",
    y_axis_unit="%",
    value_unit="lockup/slip/open",
    value_min=0.0,
    value_max=2.0,
    affects=("consumo", "eficiencia", "temperatura_transmision"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX),
)

LINE_PRESSURE = ECUMapType(
    name="line_pressure",
    display_name="Presion de linea de la transmision",
    category=MapCategory.TRANSMISSION,
    description=(
        "Presion hidraulica en los clutches/bandas de la transmision "
        "automatica. Mayor presion = cambios mas firmes pero mas bruscos. "
        "Debe aumentarse proporcionalmente al torque."
    ),
    x_axis_name="Marcha actual",
    x_axis_unit="gear #",
    y_axis_name="Torque motor",
    y_axis_unit="Nm",
    value_unit="bar",
    value_min=2.0,
    value_max=30.0,
    affects=("firmeza_cambio", "vida_clutches", "deslizamiento"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX),
)

SHIFT_SPEED_FIRMNESS = ECUMapType(
    name="shift_speed_firmness",
    display_name="Velocidad y firmeza de los cambios",
    category=MapCategory.TRANSMISSION,
    description=(
        "Tiempo de llenado de los embragues durante un cambio de marcha. "
        "Cambios rapidos = mas deportivos pero mas bruscos. Cambios "
        "lentos = mas suaves pero mayor desgaste del clutch."
    ),
    x_axis_name="Torque motor",
    x_axis_unit="Nm",
    y_axis_name="Tipo de cambio",
    y_axis_unit="up/down",
    value_unit="ms tiempo de cambio",
    value_min=50.0,
    value_max=800.0,
    affects=("confort", "deportividad", "vida_clutches"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX),
)

DCT_CLUTCH_PRESSURE = ECUMapType(
    name="dct_clutch_pressure",
    display_name="Presion de embrague DCT (doble embrague)",
    category=MapCategory.TRANSMISSION,
    description=(
        "Presion aplicada al embrague mojado o seco de una transmision "
        "de doble embrague (DSG/PDK/DCT). Controla el patinaje durante "
        "arranque y cambios."
    ),
    x_axis_name="RPM motor",
    x_axis_unit="rpm",
    y_axis_name="Torque demandado",
    y_axis_unit="Nm",
    value_unit="bar",
    value_min=0.0,
    value_max=25.0,
    affects=("arranque", "cambios", "vida_embrague"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL),
)


# ===================================================================
# 9. COOLING / THERMAL MAPS
# ===================================================================

THERMOSTAT_TARGET = ECUMapType(
    name="thermostat_target",
    display_name="Temperatura objetivo del termostato electronico",
    category=MapCategory.COOLING,
    description=(
        "Temperatura objetivo del refrigerante controlada por termostato "
        "electronico. Motores modernos varian la temperatura: mas caliente "
        "en carga parcial (eficiencia) y mas fria en carga plena (potencia)."
    ),
    x_axis_name="Carga del motor",
    x_axis_unit="%",
    y_axis_name="RPM",
    y_axis_unit="rpm",
    value_unit="degC",
    value_min=70.0,
    value_max=115.0,
    affects=("eficiencia", "potencia", "emisiones", "temperatura_motor"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
    ),
)

FAN_ACTIVATION = ECUMapType(
    name="electric_fan_activation",
    display_name="Activacion del electroventilador",
    category=MapCategory.COOLING,
    description=(
        "Umbrales de temperatura para activacion de los ventiladores "
        "electricos del radiador. Incluye velocidades baja, media y alta "
        "segun temperatura y presion de A/C."
    ),
    x_axis_name="Temperatura refrigerante",
    x_axis_unit="degC",
    y_axis_name="Presion A/C",
    y_axis_unit="bar",
    value_unit="velocidad ventilador",
    value_min=0.0,
    value_max=3.0,
    affects=("refrigeracion", "temperatura_motor", "confort_ac"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL, FuelType.LPG, FuelType.CNG,
    ),
)

ELECTRIC_WATER_PUMP = ECUMapType(
    name="electric_water_pump_speed",
    display_name="Velocidad de bomba de agua electrica",
    category=MapCategory.COOLING,
    description=(
        "Velocidad de la bomba de agua electrica en funcion de la "
        "temperatura del motor y carga. Permite control independiente "
        "del flujo de refrigerante del regimen del motor."
    ),
    x_axis_name="Temperatura refrigerante",
    x_axis_unit="degC",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="% velocidad",
    value_min=0.0,
    value_max=100.0,
    affects=("refrigeracion", "calentamiento_rapido", "consumo_electrico"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL),
)

OIL_COOLER_THERMOSTAT = ECUMapType(
    name="oil_cooler_thermostat",
    display_name="Termostato del enfriador de aceite",
    category=MapCategory.COOLING,
    description=(
        "Control del termostato del enfriador de aceite del motor. "
        "Permite calentar el aceite rapidamente y luego mantenerlo "
        "en rango optimo de temperatura y viscosidad."
    ),
    x_axis_name="Temperatura aceite",
    x_axis_unit="degC",
    y_axis_name="",
    y_axis_unit="",
    value_unit="% apertura bypass",
    value_min=0.0,
    value_max=100.0,
    affects=("temperatura_aceite", "viscosidad", "lubricacion"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL),
)

TRANSMISSION_COOLER = ECUMapType(
    name="transmission_cooler_control",
    display_name="Control de enfriamiento de transmision",
    category=MapCategory.COOLING,
    description=(
        "Control del sistema de enfriamiento de la transmision automatica. "
        "Activa el circuito de enfriamiento cuando la temperatura del "
        "aceite ATF supera el umbral seguro."
    ),
    x_axis_name="Temperatura ATF",
    x_axis_unit="degC",
    y_axis_name="",
    y_axis_unit="",
    value_unit="% enfriamiento",
    value_min=0.0,
    value_max=100.0,
    affects=("temperatura_transmision", "vida_atf", "fiabilidad"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL),
)


# ===================================================================
# 10. SPEED / RPM LIMITERS
# ===================================================================

REV_LIMITER_HARD = ECUMapType(
    name="rev_limiter_hard",
    display_name="Limitador de RPM - corte duro (hard cut)",
    category=MapCategory.LIMITERS,
    description=(
        "RPM maximo absoluto del motor. Al alcanzarse, la ECU corta "
        "completamente la inyeccion de combustible. Protege el tren "
        "valvular, bielas y ciguenal de sobre-revolucion."
    ),
    x_axis_name="Condicion",
    x_axis_unit="gear/neutral",
    y_axis_name="",
    y_axis_unit="",
    value_unit="rpm",
    value_min=3000.0,
    value_max=12000.0,
    affects=("proteccion_motor", "rpm_maximo"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL, FuelType.LPG, FuelType.CNG,
    ),
)

REV_LIMITER_SOFT = ECUMapType(
    name="rev_limiter_soft",
    display_name="Limitador de RPM - corte suave (soft cut)",
    category=MapCategory.LIMITERS,
    description=(
        "RPM donde comienza la intervencion progresiva antes del corte "
        "duro. La ECU retarda encendido y/o corta combustible en "
        "cilindros alternos para desacelerar suavemente."
    ),
    x_axis_name="Condicion",
    x_axis_unit="gear/neutral",
    y_axis_name="",
    y_axis_unit="",
    value_unit="rpm",
    value_min=3000.0,
    value_max=11500.0,
    affects=("proteccion_motor", "suavidad_limite"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL, FuelType.LPG, FuelType.CNG,
    ),
)

SPEED_LIMITER = ECUMapType(
    name="speed_limiter",
    display_name="Limitador de velocidad maxima",
    category=MapCategory.LIMITERS,
    description=(
        "Velocidad maxima del vehiculo. La ECU corta combustible o reduce "
        "torque al alcanzar el limite. Tipicamente 250 km/h en vehiculos "
        "alemanes o limites regionales."
    ),
    x_axis_name="Marcha actual",
    x_axis_unit="gear #",
    y_axis_name="",
    y_axis_unit="",
    value_unit="km/h",
    value_min=100.0,
    value_max=350.0,
    affects=("velocidad_maxima", "seguridad"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL, FuelType.LPG, FuelType.CNG,
    ),
)

LAUNCH_CONTROL = ECUMapType(
    name="launch_control_rpm",
    display_name="Control de lanzamiento (Launch Control)",
    category=MapCategory.LIMITERS,
    description=(
        "RPM objetivo durante launch control. Mantiene el motor a RPM "
        "optimo de lanzamiento con retardo de encendido para generar "
        "anti-lag y maximo boost antes de la salida."
    ),
    x_axis_name="Modo",
    x_axis_unit="modo",
    y_axis_name="",
    y_axis_unit="",
    value_unit="rpm",
    value_min=2000.0,
    value_max=8000.0,
    affects=("aceleracion_salida", "boost_estacionario", "clutch"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
)

FLAT_SHIFT = ECUMapType(
    name="flat_shift",
    display_name="Cambio plano / No-lift shift",
    category=MapCategory.LIMITERS,
    description=(
        "Permite cambiar de marcha sin levantar el pie del acelerador "
        "en transmisiones manuales. La ECU corta brevemente encendido o "
        "combustible durante el cambio manteniendo el turbo en spool."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="",
    y_axis_unit="",
    value_unit="corte (ms)",
    value_min=10.0,
    value_max=150.0,
    affects=("tiempo_cambio", "boost_sostenido", "transmision"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
)

ANTI_LAG_SYSTEM = ECUMapType(
    name="anti_lag_system",
    display_name="Sistema anti-lag (ALS / bang-bang)",
    category=MapCategory.LIMITERS,
    description=(
        "Sistema que mantiene el turbo en spool inyectando combustible "
        "y retardando encendido para que la combustion ocurra en el "
        "escape. Genera las tipicas llamaradas. Muy agresivo con "
        "componentes del escape y turbo."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Boost actual",
    y_axis_unit="bar",
    value_unit="deg retardo / ms combustible extra",
    value_min=0.0,
    value_max=40.0,
    affects=("respuesta_turbo", "lag", "fiabilidad_turbo", "temperatura_escape"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.ETHANOL),
    tuning_notes="PRECAUCION: reduce drasticamente vida util del turbo y colector de escape.",
)

PIT_LANE_LIMITER = ECUMapType(
    name="pit_lane_limiter",
    display_name="Limitador de pit lane / velocidad programable",
    category=MapCategory.LIMITERS,
    description=(
        "Limitador de velocidad secundario programable, tipicamente "
        "usado para pit lane en competicion o zonas de limite de "
        "velocidad. Activable con boton."
    ),
    x_axis_name="Modo",
    x_axis_unit="modo",
    y_axis_name="",
    y_axis_unit="",
    value_unit="km/h",
    value_min=20.0,
    value_max=120.0,
    affects=("velocidad_limitada", "seguridad_pit"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL,
    ),
)


# ===================================================================
# 11. DIESEL-SPECIFIC MAPS
# ===================================================================

DIESEL_RAIL_PRESSURE = ECUMapType(
    name="diesel_rail_pressure",
    display_name="Presion de riel common rail (diesel)",
    category=MapCategory.DIESEL,
    description=(
        "Presion objetivo del sistema common rail en funcion de RPM y "
        "cantidad de inyeccion. Presiones de 200-2500 bar en sistemas "
        "modernos. Mayor presion = mejor atomizacion y potencia."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Cantidad inyeccion (IQ)",
    y_axis_unit="mm3/stroke",
    value_unit="bar",
    value_min=150.0,
    value_max=2500.0,
    affects=("atomizacion", "potencia", "emisiones", "ruido_diesel"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(FuelType.DIESEL,),
    tuning_notes="No exceder limites de presion del inyector y bomba de alta presion.",
)

INJECTION_QUANTITY_LIMITER = ECUMapType(
    name="injection_quantity_limiter",
    display_name="Limitador de cantidad de inyeccion (IQ limiter)",
    category=MapCategory.DIESEL,
    description=(
        "Cantidad maxima de combustible inyectable en funcion de RPM y "
        "boost disponible. Previene exceso de humo y protege el turbo "
        "limitando el combustible cuando no hay suficiente aire."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Presion boost",
    y_axis_unit="bar",
    value_unit="mm3/stroke max",
    value_min=0.0,
    value_max=100.0,
    affects=("humo", "potencia", "proteccion_turbo", "egt"),
    safety_critical=True,
    requires_dyno=True,
    supported_fuel_types=(FuelType.DIESEL,),
)

SMOKE_LIMITER = ECUMapType(
    name="smoke_limiter",
    display_name="Limitador de humo (smoke limiter)",
    category=MapCategory.DIESEL,
    description=(
        "Limita la cantidad maxima de combustible para evitar exceso de "
        "humo negro (opacidad). Vinculado a la cantidad de aire disponible "
        "medida por MAF o calculada por modelo."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Flujo masico aire",
    y_axis_unit="mg/stroke",
    value_unit="mm3/stroke max IQ",
    value_min=0.0,
    value_max=80.0,
    affects=("humo", "emisiones_particulas", "opacidad"),
    safety_critical=False,
    requires_dyno=True,
    supported_fuel_types=(FuelType.DIESEL,),
)

GLOW_PLUG_DURATION = ECUMapType(
    name="glow_plug_duration",
    display_name="Duracion de bujias de precalentamiento (glow plugs)",
    category=MapCategory.DIESEL,
    description=(
        "Tiempo de activacion de las bujias de precalentamiento antes "
        "y despues del arranque en funcion de la temperatura del motor. "
        "Critico para arranque diesel en clima frio."
    ),
    x_axis_name="Temperatura refrigerante",
    x_axis_unit="degC",
    y_axis_name="",
    y_axis_unit="",
    value_unit="s",
    value_min=0.0,
    value_max=60.0,
    affects=("arranque_frio", "emisiones_frio", "humo_arranque"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL,),
)

SWIRL_FLAP_POSITION = ECUMapType(
    name="swirl_flap_position",
    display_name="Posicion de aleta de turbulencia (swirl flap) diesel",
    category=MapCategory.DIESEL,
    description=(
        "Posicion de las aletas de turbulencia en el colector de admision "
        "diesel. Cerradas a baja carga para crear vortice y mejorar "
        "mezcla. Abiertas a alta carga para maximo flujo."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="% posicion",
    value_min=0.0,
    value_max=100.0,
    affects=("turbulencia", "combustion", "emisiones", "potencia"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL,),
)

DPF_DIFFERENTIAL_PRESSURE = ECUMapType(
    name="dpf_differential_pressure",
    display_name="Umbral de presion diferencial del DPF",
    category=MapCategory.DIESEL,
    description=(
        "Umbral de presion diferencial a traves del filtro de particulas "
        "que indica nivel de obstruccion. Usado junto con modelo de "
        "hollin para decidir cuando iniciar regeneracion."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Flujo exhaust",
    y_axis_unit="kg/h",
    value_unit="mbar",
    value_min=0.0,
    value_max=300.0,
    affects=("regeneracion_dpf", "contrapresion", "diagnostico"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL, FuelType.GASOLINE),
)

EGR_COOLER_BYPASS = ECUMapType(
    name="egr_cooler_bypass",
    display_name="Bypass del enfriador de EGR (diesel)",
    category=MapCategory.DIESEL,
    description=(
        "Control de la valvula de bypass del enfriador de EGR. En frio "
        "se bypasea el enfriador para calentar motor mas rapido. En "
        "caliente se usa el enfriador para reducir temperatura del EGR."
    ),
    x_axis_name="Temperatura refrigerante",
    x_axis_unit="degC",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="% bypass",
    value_min=0.0,
    value_max=100.0,
    affects=("temperatura_egr", "emisiones_nox", "calentamiento"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL,),
)

DIESEL_PILOT_TIMING = ECUMapType(
    name="diesel_pilot_timing",
    display_name="Timing de inyeccion piloto (diesel)",
    category=MapCategory.DIESEL,
    description=(
        "Angulo de inicio de la pre-inyeccion piloto en grados antes "
        "del PMS. Tipicamente 15-30 grados antes de la inyeccion "
        "principal para pre-calentar la camara."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Carga del motor",
    y_axis_unit="%",
    value_unit="deg BTDC",
    value_min=5.0,
    value_max=40.0,
    affects=("ruido_diesel", "emisiones_nox", "suavidad"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL,),
)

DIESEL_PILOT_SEPARATION = ECUMapType(
    name="diesel_pilot_separation",
    display_name="Separacion piloto-principal (diesel)",
    category=MapCategory.DIESEL,
    description=(
        "Separacion angular entre la inyeccion piloto y la principal. "
        "Afecta la tasa de liberacion de calor y el ruido de combustion. "
        "Menor separacion = combustion mas suave."
    ),
    x_axis_name="RPM",
    x_axis_unit="rpm",
    y_axis_name="Cantidad inyeccion principal",
    y_axis_unit="mm3",
    value_unit="deg separacion",
    value_min=3.0,
    value_max=25.0,
    affects=("ruido", "tasa_liberacion_calor", "emisiones"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL,),
)


# ===================================================================
# 12. DELETES / DISABLES (Deshabilitaciones)
# ===================================================================

DPF_DELETE = ECUMapType(
    name="dpf_delete",
    display_name="Eliminacion de DPF (DPF delete / off)",
    category=MapCategory.DELETES,
    description=(
        "Desactivacion del filtro de particulas diesel. Elimina "
        "regeneraciones, post-inyecciones y codigos de error "
        "relacionados con el DPF. Requiere remocion fisica del filtro."
    ),
    x_axis_name="Parametro",
    x_axis_unit="param",
    y_axis_name="",
    y_axis_unit="",
    value_unit="activado/desactivado",
    value_min=0.0,
    value_max=1.0,
    affects=("regeneracion_dpf", "contrapresion", "consumo", "dtc"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL, FuelType.GASOLINE),
    tuning_notes="ADVERTENCIA: Ilegal en vias publicas en la mayoria de jurisdicciones. Solo competicion.",
)

EGR_DELETE = ECUMapType(
    name="egr_delete",
    display_name="Eliminacion de EGR (EGR delete / off)",
    category=MapCategory.DELETES,
    description=(
        "Desactivacion de la recirculacion de gases de escape. Cierra "
        "la valvula EGR permanentemente y desactiva codigos de error. "
        "Reduce obstruccion del colector de admision."
    ),
    x_axis_name="Parametro",
    x_axis_unit="param",
    y_axis_name="",
    y_axis_unit="",
    value_unit="activado/desactivado",
    value_min=0.0,
    value_max=1.0,
    affects=("egr", "admision_limpia", "emisiones_nox", "dtc"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL, FuelType.GASOLINE),
    tuning_notes="ADVERTENCIA: Ilegal en vias publicas en la mayoria de jurisdicciones. Solo competicion.",
)

CAT_DELETE = ECUMapType(
    name="cat_delete",
    display_name="Eliminacion de catalizador (decat)",
    category=MapCategory.DELETES,
    description=(
        "Desactivacion de los monitores del catalizador y eliminacion "
        "de codigos de error relacionados. Permite instalar downpipe "
        "sin catalizador (decat) o con catalizador deportivo."
    ),
    x_axis_name="Parametro",
    x_axis_unit="param",
    y_axis_name="",
    y_axis_unit="",
    value_unit="activado/desactivado",
    value_min=0.0,
    value_max=1.0,
    affects=("contrapresion_escape", "emisiones", "dtc_catalizador"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.DIESEL),
    tuning_notes="ADVERTENCIA: Ilegal en vias publicas en la mayoria de jurisdicciones. Solo competicion.",
)

ADBLUE_DELETE = ECUMapType(
    name="adblue_scr_delete",
    display_name="Eliminacion de AdBlue/SCR",
    category=MapCategory.DELETES,
    description=(
        "Desactivacion del sistema de reduccion catalitica selectiva "
        "(SCR) y la inyeccion de AdBlue/DEF. Elimina codigos de error, "
        "contadores y modo limp relacionados."
    ),
    x_axis_name="Parametro",
    x_axis_unit="param",
    y_axis_name="",
    y_axis_unit="",
    value_unit="activado/desactivado",
    value_min=0.0,
    value_max=1.0,
    affects=("scr", "adblue", "emisiones_nox", "dtc", "modo_emergencia"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL,),
    tuning_notes="ADVERTENCIA: Ilegal en vias publicas en la mayoria de jurisdicciones. Solo competicion.",
)

SWIRL_FLAP_DELETE = ECUMapType(
    name="swirl_flap_delete",
    display_name="Eliminacion de aletas de turbulencia (swirl flap delete)",
    category=MapCategory.DELETES,
    description=(
        "Desactivacion del control de aletas de turbulencia del colector "
        "de admision. Comun cuando se remueven fisicamente por riesgo de "
        "rotura y aspiracion al motor."
    ),
    x_axis_name="Parametro",
    x_axis_unit="param",
    y_axis_name="",
    y_axis_unit="",
    value_unit="activado/desactivado",
    value_min=0.0,
    value_max=1.0,
    affects=("swirl_flaps", "dtc", "admision"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.DIESEL, FuelType.GASOLINE),
)

SECONDARY_O2_DELETE = ECUMapType(
    name="secondary_o2_delete",
    display_name="Eliminacion de segunda sonda lambda",
    category=MapCategory.DELETES,
    description=(
        "Desactivacion del monitor de la sonda lambda post-catalizador. "
        "Elimina el codigo P0420/P0430 de eficiencia de catalizador. "
        "Necesario tras instalar downpipe deportivo."
    ),
    x_axis_name="Parametro",
    x_axis_unit="param",
    y_axis_name="",
    y_axis_unit="",
    value_unit="activado/desactivado",
    value_min=0.0,
    value_max=1.0,
    affects=("monitor_catalizador", "dtc_p0420", "lambda_post"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE, FuelType.FLEX, FuelType.ETHANOL),
    tuning_notes="ADVERTENCIA: Ilegal en vias publicas en la mayoria de jurisdicciones. Solo competicion.",
)

SPEED_LIMITER_REMOVAL = ECUMapType(
    name="speed_limiter_removal",
    display_name="Remocion del limitador de velocidad",
    category=MapCategory.DELETES,
    description=(
        "Eliminacion o aumento del limite de velocidad maxima del "
        "vehiculo. Se modifica o desactiva el mapa del limitador "
        "electronico de velocidad."
    ),
    x_axis_name="Parametro",
    x_axis_unit="param",
    y_axis_name="",
    y_axis_unit="",
    value_unit="km/h nuevo limite",
    value_min=200.0,
    value_max=350.0,
    affects=("velocidad_maxima", "seguridad"),
    safety_critical=True,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL,
    ),
    tuning_notes="ADVERTENCIA: Verificar que neumaticos y frenos soporten la velocidad eliminada.",
)

START_STOP_DISABLE = ECUMapType(
    name="start_stop_disable",
    display_name="Desactivacion de Start-Stop automatico",
    category=MapCategory.DELETES,
    description=(
        "Desactivacion permanente del sistema Start-Stop que apaga el "
        "motor en semaforos y paradas. Elimina la molestia del apagado "
        "y encendido automatico del motor."
    ),
    x_axis_name="Parametro",
    x_axis_unit="param",
    y_axis_name="",
    y_axis_unit="",
    value_unit="activado/desactivado",
    value_min=0.0,
    value_max=1.0,
    affects=("start_stop", "confort", "bateria", "arranque"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
    ),
)

FLAP_EXHAUST_DELETE = ECUMapType(
    name="exhaust_flap_delete",
    display_name="Eliminacion de valvula de escape (exhaust flap)",
    category=MapCategory.DELETES,
    description=(
        "Desactivacion de la valvula de escape controlada "
        "electronicamente. Se usa para mantener el escape abierto "
        "permanentemente (modo sport) o cerrado."
    ),
    x_axis_name="Parametro",
    x_axis_unit="param",
    y_axis_name="",
    y_axis_unit="",
    value_unit="posicion fija",
    value_min=0.0,
    value_max=1.0,
    affects=("sonido_escape", "contrapresion", "dtc"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE,),
)

GPF_DELETE = ECUMapType(
    name="gpf_delete",
    display_name="Eliminacion de filtro de particulas gasolina (GPF/OPF)",
    category=MapCategory.DELETES,
    description=(
        "Desactivacion del filtro de particulas de gasolina (GPF/OPF) "
        "presente en motores GDI Euro 6d. Similar al DPF delete pero "
        "para motores de gasolina de inyeccion directa."
    ),
    x_axis_name="Parametro",
    x_axis_unit="param",
    y_axis_name="",
    y_axis_unit="",
    value_unit="activado/desactivado",
    value_min=0.0,
    value_max=1.0,
    affects=("contrapresion", "emisiones_particulas", "dtc"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(FuelType.GASOLINE,),
    tuning_notes="ADVERTENCIA: Ilegal en vias publicas en la mayoria de jurisdicciones. Solo competicion.",
)

READINESS_MONITORS_DISABLE = ECUMapType(
    name="readiness_monitors_disable",
    display_name="Desactivacion de monitores OBD2 readiness",
    category=MapCategory.DELETES,
    description=(
        "Desactivacion selectiva de monitores de preparacion OBD2 para "
        "evitar que el vehiculo reporte DTCs tras modificaciones. "
        "Incluye monitores de catalizador, EVAP, O2, EGR."
    ),
    x_axis_name="Monitor",
    x_axis_unit="tipo_monitor",
    y_axis_name="",
    y_axis_unit="",
    value_unit="activado/desactivado",
    value_min=0.0,
    value_max=1.0,
    affects=("diagnostico_obd2", "dtc", "inspeccion_vehicular"),
    safety_critical=False,
    requires_dyno=False,
    supported_fuel_types=(
        FuelType.GASOLINE, FuelType.DIESEL, FuelType.FLEX,
        FuelType.ETHANOL,
    ),
    tuning_notes="ADVERTENCIA: Puede impedir pasar inspecciones tecnicas vehiculares.",
)


# ===================================================================
# MASTER CATALOG - all map type instances
# ===================================================================

_ALL_MAP_TYPES: tuple[ECUMapType, ...] = (
    # 1. Fuel System
    FUEL_INJECTION_BASE,
    FUEL_COLD_START_ENRICHMENT,
    FUEL_ACCEL_ENRICHMENT,
    FUEL_DECEL_CUTOFF,
    FUEL_CRANKING_PULSE,
    LAMBDA_TARGET,
    FUEL_PRESSURE_TARGET,
    INJECTOR_DEAD_TIME,
    FUEL_RAIL_PRESSURE_GDI,
    DIESEL_INJECTION_TIMING,
    PILOT_INJECTION_QTY,
    MAIN_INJECTION_QTY,
    POST_INJECTION_QTY,
    INJECTION_COUNT,
    FUEL_WARMUP_ENRICHMENT,
    FUEL_ALTITUDE_COMPENSATION,
    CLOSED_LOOP_LAMBDA_LIMITS,
    # 2. Ignition System
    IGNITION_BASE_TIMING,
    KNOCK_RETARD_LIMIT,
    KNOCK_SENSITIVITY,
    DWELL_TIME,
    IGNITION_COLD_CORRECTION,
    INDIVIDUAL_CYLINDER_TRIM,
    KNOCK_RECOVERY_RATE,
    # 3. Boost / Turbo
    BOOST_TARGET,
    WASTEGATE_DUTY,
    VGT_POSITION,
    BOOST_LIMIT,
    OVERBOOST,
    COMPRESSOR_SURGE_LIMIT,
    EXHAUST_BACKPRESSURE_TARGET,
    BOOST_SCRAMBLE,
    # 4. Air Management
    THROTTLE_TARGET,
    ELECTRONIC_THROTTLE_POSITION,
    IDLE_AIR_CONTROL,
    INTAKE_MANIFOLD_FLAP,
    VARIABLE_INTAKE_RUNNER,
    MAF_CALIBRATION,
    MAP_SENSOR_CALIBRATION,
    IDLE_RPM_TARGET,
    # 5. VVT
    VVT_INTAKE_ADVANCE,
    VVT_EXHAUST_ADVANCE,
    VALVE_LIFT_SWITCH,
    CAM_PHASER_OCV_DUTY,
    CONTINUOUS_VALVE_LIFT,
    # 6. Emissions
    EGR_VALVE_POSITION,
    DPF_REGEN_TRIGGER,
    DPF_REGEN_TEMP_TARGET,
    SCR_ADBLUE_INJECTION,
    CATALYST_HEATING,
    SECONDARY_AIR_INJECTION,
    CANISTER_PURGE,
    LAMBDA_HEATER_CONTROL,
    NOX_STORAGE_CATALYST,
    # 7. Torque Management
    DRIVER_DEMAND_TORQUE,
    MAX_TORQUE_LIMIT,
    TORQUE_REDUCTION_GEARSHIFT,
    TORQUE_REDUCTION_TRACTION,
    TORQUE_LIMIT_COOLANT_TEMP,
    TORQUE_LIMIT_IAT,
    CRUISE_CONTROL_TORQUE,
    TORQUE_LIMIT_OIL_TEMP,
    TORQUE_LIMIT_EXHAUST_TEMP,
    # 8. Transmission
    SHIFT_UPSHIFT,
    SHIFT_DOWNSHIFT,
    TORQUE_CONVERTER_LOCKUP,
    LINE_PRESSURE,
    SHIFT_SPEED_FIRMNESS,
    DCT_CLUTCH_PRESSURE,
    # 9. Cooling / Thermal
    THERMOSTAT_TARGET,
    FAN_ACTIVATION,
    ELECTRIC_WATER_PUMP,
    OIL_COOLER_THERMOSTAT,
    TRANSMISSION_COOLER,
    # 10. Speed / RPM Limiters
    REV_LIMITER_HARD,
    REV_LIMITER_SOFT,
    SPEED_LIMITER,
    LAUNCH_CONTROL,
    FLAT_SHIFT,
    ANTI_LAG_SYSTEM,
    PIT_LANE_LIMITER,
    # 11. Diesel-Specific
    DIESEL_RAIL_PRESSURE,
    INJECTION_QUANTITY_LIMITER,
    SMOKE_LIMITER,
    GLOW_PLUG_DURATION,
    SWIRL_FLAP_POSITION,
    DPF_DIFFERENTIAL_PRESSURE,
    EGR_COOLER_BYPASS,
    DIESEL_PILOT_TIMING,
    DIESEL_PILOT_SEPARATION,
    # 12. Deletes / Disables
    DPF_DELETE,
    EGR_DELETE,
    CAT_DELETE,
    ADBLUE_DELETE,
    SWIRL_FLAP_DELETE,
    SECONDARY_O2_DELETE,
    SPEED_LIMITER_REMOVAL,
    START_STOP_DISABLE,
    FLAP_EXHAUST_DELETE,
    GPF_DELETE,
    READINESS_MONITORS_DISABLE,
)


# ===================================================================
# MapCatalog class
# ===================================================================

class MapCatalog:
    """Catalog of all ECU map type definitions.

    Provides filtering and lookup utilities for the complete set of
    professional ECU map types.

    Usage
    -----
    >>> catalog = MapCatalog()
    >>> len(catalog.get_all())
    100  # or more
    >>> fuel_maps = catalog.get_by_category(MapCategory.FUEL)
    >>> diesel_maps = catalog.get_by_fuel_type(FuelType.DIESEL)
    """

    def __init__(
        self,
        map_types: Optional[tuple[ECUMapType, ...]] = None,
    ) -> None:
        self._map_types = map_types or _ALL_MAP_TYPES
        # Build lookup indexes
        self._by_name: dict[str, ECUMapType] = {
            m.name: m for m in self._map_types
        }
        self._by_category: dict[MapCategory, list[ECUMapType]] = {}
        for m in self._map_types:
            self._by_category.setdefault(m.category, []).append(m)

    # ------------------------------------------------------------------
    # Basic accessors
    # ------------------------------------------------------------------

    def get_all(self) -> list[ECUMapType]:
        """Return all map type definitions."""
        return list(self._map_types)

    def get_by_name(self, name: str) -> Optional[ECUMapType]:
        """Look up a single map type by its English identifier."""
        return self._by_name.get(name)

    def get_by_category(self, category: MapCategory) -> list[ECUMapType]:
        """Return all map types in a given category."""
        return list(self._by_category.get(category, []))

    def get_by_fuel_type(self, fuel_type: str | FuelType) -> list[ECUMapType]:
        """Return all map types that support a specific fuel type."""
        ft = FuelType(fuel_type) if isinstance(fuel_type, str) else fuel_type
        return [m for m in self._map_types if ft in m.supported_fuel_types]

    # ------------------------------------------------------------------
    # Advanced filters
    # ------------------------------------------------------------------

    def get_safety_critical(self) -> list[ECUMapType]:
        """Return all safety-critical map types."""
        return [m for m in self._map_types if m.safety_critical]

    def get_requiring_dyno(self) -> list[ECUMapType]:
        """Return all map types that require dynamometer verification."""
        return [m for m in self._map_types if m.requires_dyno]

    def get_by_vehicle_type(
        self,
        fuel_type: str | FuelType,
        has_turbo: bool = False,
        has_auto_trans: bool = False,
        has_vvt: bool = True,
    ) -> list[ECUMapType]:
        """Return map types applicable to a specific vehicle configuration.

        Parameters
        ----------
        fuel_type:
            Primary fuel type of the vehicle.
        has_turbo:
            Whether the vehicle has turbo/supercharging.
        has_auto_trans:
            Whether the vehicle has automatic or DCT transmission.
        has_vvt:
            Whether the vehicle has variable valve timing.
        """
        ft = FuelType(fuel_type) if isinstance(fuel_type, str) else fuel_type
        results: list[ECUMapType] = []

        for m in self._map_types:
            # Must support this fuel type
            if ft not in m.supported_fuel_types:
                continue

            # Filter turbo-specific maps
            if m.category == MapCategory.BOOST and not has_turbo:
                continue

            # Filter transmission maps
            if m.category == MapCategory.TRANSMISSION and not has_auto_trans:
                continue

            # Filter VVT maps
            if m.category == MapCategory.VVT and not has_vvt:
                continue

            # Filter diesel-specific for non-diesel
            if m.category == MapCategory.DIESEL and ft != FuelType.DIESEL:
                continue

            results.append(m)

        return results

    def get_categories(self) -> list[MapCategory]:
        """Return all categories that have at least one map type."""
        return list(self._by_category.keys())

    def get_category_summary(self) -> dict[str, int]:
        """Return a count of map types per category."""
        return {
            cat.value: len(maps)
            for cat, maps in self._by_category.items()
        }

    def search(self, query: str) -> list[ECUMapType]:
        """Search map types by keyword in name, display_name, or description."""
        q = query.lower()
        return [
            m for m in self._map_types
            if q in m.name.lower()
            or q in m.display_name.lower()
            or q in m.description.lower()
        ]

    @property
    def total_count(self) -> int:
        """Total number of map type definitions."""
        return len(self._map_types)

    def __len__(self) -> int:
        return len(self._map_types)

    def __repr__(self) -> str:
        return f"MapCatalog(total={self.total_count} map types, categories={len(self._by_category)})"
