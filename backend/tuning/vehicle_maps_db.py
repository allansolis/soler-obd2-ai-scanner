"""
SOLER OBD2 AI Scanner - Base de Datos de Configuraciones ECU por Vehiculo
==========================================================================
Contiene una base de datos completa de vehiculos conocidos con sus
configuraciones de ECU, mapas disponibles y notas de calibracion.
Todos los vehiculos provienen de los paquetes de mapas (Drive 4LAP)
y datos OBD Diesel del proyecto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Vehicle ECU configuration dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VehicleECUConfig:
    """Configuracion completa de ECU para un vehiculo especifico."""

    make: str
    model: str
    year_range: str
    engine: str
    ecu_type: str
    ecu_manufacturer: str
    fuel_type: str
    turbo: bool
    available_maps: list[str]
    known_issues: list[str]
    tuning_notes: str
    supported_operations: list[str]


# ---------------------------------------------------------------------------
# Map type constants (aligned with tuning module)
# ---------------------------------------------------------------------------

MAP_FUEL = "fuel_map"
MAP_IGNITION = "ignition_map"
MAP_BOOST = "boost_map"
MAP_VVT = "vvt_map"
MAP_THROTTLE = "throttle_map"
MAP_EGR = "egr_map"
MAP_DPF = "dpf_map"
MAP_TORQUE_LIMITER = "torque_limiter"
MAP_INJECTION_TIMING = "injection_timing"
MAP_RAIL_PRESSURE = "rail_pressure"
MAP_SMOKE_LIMITER = "smoke_limiter"
MAP_TURBO_PRESSURE = "turbo_pressure"
MAP_SPEED_LIMITER = "speed_limiter"
MAP_START_QUANTITY = "start_quantity"
MAP_IDLE_SPEED = "idle_speed"
MAP_LAMBDA = "lambda_map"


# ---------------------------------------------------------------------------
# Common diesel map sets
# ---------------------------------------------------------------------------

_DIESEL_MAPS_FULL = [
    MAP_FUEL, MAP_BOOST, MAP_THROTTLE, MAP_EGR, MAP_DPF,
    MAP_TORQUE_LIMITER, MAP_INJECTION_TIMING, MAP_RAIL_PRESSURE,
    MAP_SMOKE_LIMITER, MAP_TURBO_PRESSURE, MAP_SPEED_LIMITER,
    MAP_START_QUANTITY, MAP_IDLE_SPEED,
]

_DIESEL_MAPS_BASIC = [
    MAP_FUEL, MAP_BOOST, MAP_THROTTLE, MAP_EGR,
    MAP_TORQUE_LIMITER, MAP_INJECTION_TIMING, MAP_RAIL_PRESSURE,
    MAP_SMOKE_LIMITER, MAP_TURBO_PRESSURE,
]

_GASOLINE_MAPS_FULL = [
    MAP_FUEL, MAP_IGNITION, MAP_BOOST, MAP_VVT, MAP_THROTTLE,
    MAP_TORQUE_LIMITER, MAP_SPEED_LIMITER, MAP_LAMBDA,
    MAP_IDLE_SPEED,
]

_FLEX_MAPS = [
    MAP_FUEL, MAP_IGNITION, MAP_THROTTLE, MAP_VVT,
    MAP_TORQUE_LIMITER, MAP_SPEED_LIMITER, MAP_LAMBDA,
    MAP_IDLE_SPEED,
]

# ---------------------------------------------------------------------------
# Common supported operations
# ---------------------------------------------------------------------------

_OPS_DIESEL_FULL = [
    "read", "write", "dpf_off", "egr_off", "dtc_off",
    "adblue_off", "stage1", "stage2",
]

_OPS_DIESEL_BASIC = ["read", "write", "egr_off", "stage1"]

_OPS_DIESEL_MEDIUM = [
    "read", "write", "dpf_off", "egr_off", "dtc_off", "stage1",
]

_OPS_GASOLINE = ["read", "write", "stage1", "stage2", "dtc_off"]

_OPS_FLEX = ["read", "write", "stage1", "dtc_off"]


# ---------------------------------------------------------------------------
# Vehicle database entries
# ---------------------------------------------------------------------------

VEHICLE_DATABASE: list[VehicleECUConfig] = [

    # -----------------------------------------------------------------------
    # 1. Chevrolet S10 EDC16C39
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Chevrolet",
        model="S10 2.8 CTDi",
        year_range="2012-2016",
        engine="2.8L Duramax Diesel",
        ecu_type="EDC16C39",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Falla frecuente en sensor de presion de riel comun",
            "Problemas de regeneracion de DPF en uso urbano",
            "Sensor MAF contaminado genera perdida de potencia",
        ],
        tuning_notes=(
            "ECU EDC16C39 con protocolo K-Line y CAN. Lectura por OBD sin "
            "problemas. El mapa de inyeccion principal esta en el bloque 0x30000. "
            "Limitador de torque en zona 0x50000. Se recomienda stage1 con "
            "incremento de presion de riel de hasta 15% y ajuste de timing "
            "de inyeccion para ganancia de 30-40CV."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 2. Fiat Ducato 2.3 MJD_8F3
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Fiat",
        model="Ducato 2.3 Multijet",
        year_range="2010-2018",
        engine="2.3L Multijet Diesel",
        ecu_type="MJD_8F3",
        ecu_manufacturer="Magneti Marelli",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Turbo de geometria variable se traba por carbonilla",
            "Valvula EGR obstruida genera humo negro excesivo",
            "Sensor de temperatura de escape con fallas intermitentes",
        ],
        tuning_notes=(
            "ECU Magneti Marelli MJD_8F3 con lectura por OBD. Mapas de "
            "inyeccion accesibles. Se puede desactivar EGR y DPF por software. "
            "En stage1 se obtienen entre 20-30CV adicionales ajustando presion "
            "de riel y limitador de humo. Cuidado con el turbo de geometria "
            "variable al aumentar presion de boost."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 3. Fiat Toro HW0281031204
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Fiat",
        model="Toro 2.0 Diesel",
        year_range="2016-2023",
        engine="2.0L Multijet II Diesel",
        ecu_type="EDC17C69",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Sistema SCR/AdBlue con fallas de sensor NOx",
            "DPF con regeneracion incompleta en ciclos cortos",
            "Inyectores con deriva despues de 80.000km",
        ],
        tuning_notes=(
            "Hardware 0281031204 con ECU Bosch EDC17C69. Lectura por OBD "
            "via protocolo UDS. Mapas principales de inyeccion, presion de "
            "riel y limitador de torque modificables. Stage1 rinde entre "
            "25-35CV adicionales. Se puede desactivar DPF, EGR y AdBlue "
            "por software. Verificar version de SW antes de grabar."
        ),
        supported_operations=_OPS_DIESEL_FULL + ["adblue_off"],
    ),

    # -----------------------------------------------------------------------
    # 4. Fiat IAW 7GF (Flex/Gasolina)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Fiat",
        model="Palio / Siena 1.4",
        year_range="2008-2016",
        engine="1.4L Fire Flex",
        ecu_type="IAW_7GF",
        ecu_manufacturer="Magneti Marelli",
        fuel_type="flex",
        turbo=False,
        available_maps=_FLEX_MAPS,
        known_issues=[
            "Sensor de oxigeno con lectura lenta despues de 60.000km",
            "Bobina de encendido con falla intermitente",
            "Cuerpo de aceleracion electronico sucio genera ralenti inestable",
        ],
        tuning_notes=(
            "ECU IAW 7GF con hardware HSW 203. Lectura por protocolo KWP2000. "
            "Mapas de inyeccion y encendido accesibles. Ajuste de avance de "
            "encendido de hasta 3 grados en zona de carga media. Mapa de "
            "aceleracion electronica mejorable para mejor respuesta. "
            "Ganancia estimada de 5-8CV en modo nafta."
        ),
        supported_operations=_OPS_FLEX,
    ),

    # -----------------------------------------------------------------------
    # 5. Ford Focus MED 17.8.2
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Ford",
        model="Focus 2.0 Duratec",
        year_range="2013-2019",
        engine="2.0L Duratec GDI",
        ecu_type="MED17.8.2",
        ecu_manufacturer="Bosch",
        fuel_type="gasoline",
        turbo=False,
        available_maps=_GASOLINE_MAPS_FULL,
        known_issues=[
            "Inyectores GDI con depositos de carbon en valvulas",
            "Sensor de fase con error intermitente en frio",
            "Bomba de combustible de alta presion con ruido despues de 100.000km",
        ],
        tuning_notes=(
            "ECU Bosch MED17.8.2 con inyeccion directa. Lectura por OBD "
            "protocolo UDS. Mapas de encendido e inyeccion completos. "
            "Se puede ajustar avance de encendido +2 a +4 grados con nafta "
            "de 98 octanos. Mapa de VVT modificable para mejor llenado. "
            "Ganancia de 8-12CV en stage1."
        ),
        supported_operations=_OPS_GASOLINE,
    ),

    # -----------------------------------------------------------------------
    # 6. Ford Ranger 2.2 SID208
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Ford",
        model="Ranger 2.2 TDCi",
        year_range="2012-2019",
        engine="2.2L Duratorq TDCi",
        ecu_type="SID208",
        ecu_manufacturer="Continental",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Inyectores piezoelectricos con deriva frecuente",
            "DPF se obstruye rapidamente en uso urbano",
            "Turbo con juego axial despues de 120.000km",
        ],
        tuning_notes=(
            "ECU Continental SID208 con protocolo CAN/UDS. Lectura por OBD "
            "directa. Mapas de inyeccion, presion de riel y boost accesibles. "
            "Stage1 con +30-40CV ajustando presion de riel y limitador de "
            "torque. DPF y EGR desactivables. Atencion: los inyectores "
            "piezoelectricos requieren calibracion IMA despues de cambio."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 7. Ford Ranger 3.2 SID208
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Ford",
        model="Ranger 3.2 TDCi",
        year_range="2012-2019",
        engine="3.2L Duratorq 5-cyl TDCi",
        ecu_type="SID208",
        ecu_manufacturer="Continental",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Motor 5 cilindros con vibracion caracteristica a ralenti",
            "Volante bimasa con desgaste prematuro",
            "EGR con acumulacion severa de carbonilla",
        ],
        tuning_notes=(
            "Misma ECU SID208 que la 2.2 pero con mapas distintos para el "
            "motor 5 cilindros de 200CV. Stage1 lleva a 230-240CV con ajuste "
            "de presion de riel, boost y limitador de torque. Stage2 con "
            "escape deportivo alcanza 260CV. Transmision automatica requiere "
            "ajuste de mapa de cambios (ATM)."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 8. Ford Ranger 3.0D Siemens SID 901C
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Ford",
        model="Ranger 3.0 Power Stroke",
        year_range="2005-2012",
        engine="3.0L Power Stroke Diesel",
        ecu_type="SID901C",
        ecu_manufacturer="Siemens",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Inyectores con goteo frecuente despues de 100.000km",
            "Bomba de vacio con fallas que afectan frenado",
            "Enfriador de EGR con fugas de refrigerante",
        ],
        tuning_notes=(
            "ECU Siemens SID 901C de generacion anterior. Lectura por OBD "
            "protocolo CAN. Mapas basicos de inyeccion y presion de riel. "
            "Stage1 con +20-25CV. No tiene DPF de fabrica. EGR desactivable "
            "por software. Verificar estado de inyectores antes de aumentar "
            "presion de riel."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM,
    ),

    # -----------------------------------------------------------------------
    # 9. GM Prisma 1.0 FJNX
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Chevrolet",
        model="Prisma 1.0",
        year_range="2013-2019",
        engine="1.0L SPE/4 Flex",
        ecu_type="FJNX",
        ecu_manufacturer="Continental",
        fuel_type="flex",
        turbo=False,
        available_maps=_FLEX_MAPS,
        known_issues=[
            "Cuerpo de aceleracion electronico con desgaste prematuro",
            "Sensor de detonacion con falsos positivos en verano",
            "Bobina de encendido sequencial con falla en cilindro 1",
        ],
        tuning_notes=(
            "ECU Continental FJNX con lectura por protocolo CAN/UDS. "
            "Motor 1.0 SPE/4 con poca ganancia disponible. Ajuste de "
            "encendido +2 grados y mapa de aceleracion para mejor "
            "respuesta. Ganancia de 3-5CV. Se recomienda solo ajuste de "
            "respuesta de acelerador y eliminacion de limitador de velocidad."
        ),
        supported_operations=_OPS_FLEX,
    ),

    # -----------------------------------------------------------------------
    # 10. Hyundai HR 2.5 DCM 3.7 Delphi
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Hyundai",
        model="HR 2.5 CRDi",
        year_range="2006-2018",
        engine="2.5L CRDi Diesel",
        ecu_type="DCM3.7",
        ecu_manufacturer="Delphi",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Turbo con carbonilla en geometria variable",
            "Inyectores con retorno excesivo despues de 80.000km",
            "Sensor de presion del riel con lecturas erraticas",
        ],
        tuning_notes=(
            "ECU Delphi DCM 3.7 con lectura por OBD protocolo CAN. "
            "Mapas de inyeccion y presion de riel accesibles. Stage1 "
            "con +15-20CV ajustando presion de riel y timing de inyeccion. "
            "No tiene DPF. EGR desactivable. Motor robusto que acepta "
            "bien el aumento de potencia para uso en carga."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM,
    ),

    # -----------------------------------------------------------------------
    # 11. Iveco Daily EDC17CP52
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Iveco",
        model="Daily 35S14 / 55C17",
        year_range="2012-2019",
        engine="2.3L / 3.0L F1C Diesel",
        ecu_type="EDC17CP52",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Sistema SCR con falla de calentador de AdBlue",
            "DPF con regeneracion forzada frecuente en reparto urbano",
            "Turbo de geometria variable trabado por carbon",
        ],
        tuning_notes=(
            "ECU Bosch EDC17CP52 con protocolo UDS. Lectura por OBD "
            "completa. Mapas de inyeccion, boost, torque y DPF accesibles. "
            "Stage1 con +25-35CV. Desactivacion de DPF, EGR y AdBlue "
            "muy solicitada para uso en reparto. Verificar version de "
            "calibracion antes de grabar."
        ),
        supported_operations=_OPS_DIESEL_FULL + ["adblue_off"],
    ),

    # -----------------------------------------------------------------------
    # 12. Iveco Daily EDC17CP54
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Iveco",
        model="Daily 70C17",
        year_range="2014-2021",
        engine="3.0L F1C Euro 5 Diesel",
        ecu_type="EDC17CP54",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Sensor NOx con falla recurrente",
            "Bomba de AdBlue con cristalizacion",
            "Valvula EGR electronica con codigo de error permanente",
        ],
        tuning_notes=(
            "ECU Bosch EDC17CP54 evolucion de la CP52 con mejoras en "
            "control de emisiones. Lectura y escritura por OBD. Stage1 "
            "con +30-40CV. La desactivacion de AdBlue requiere anular "
            "tambien el sensor NOx. DPF off disponible. Misma familia "
            "de mapas que EDC17CP52 pero con offsets diferentes."
        ),
        supported_operations=_OPS_DIESEL_FULL + ["adblue_off"],
    ),

    # -----------------------------------------------------------------------
    # 13. Iveco Euro Cargo Tector
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Iveco",
        model="Euro Cargo Tector",
        year_range="2008-2018",
        engine="5.9L Tector Diesel",
        ecu_type="EDC7UC31",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Bomba de inyeccion con desgaste interno en alta kilometraje",
            "Turbo con juego excesivo en camiones de larga distancia",
            "Sensor de posicion del ciguenal con intermitencia",
        ],
        tuning_notes=(
            "ECU Bosch EDC7UC31 de camion. Lectura por OBD protocolo J1939. "
            "Mapas basicos de inyeccion y limitador de torque/velocidad. "
            "Stage1 orientado a mejorar torque bajo para arranque en pendiente. "
            "Eliminacion de limitador de velocidad disponible. Motor robusto "
            "que acepta aumentos moderados de 10-15%."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM + ["speed_limiter_off"],
    ),

    # -----------------------------------------------------------------------
    # 14. Kia Bongo DC3.5 2.5BT
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Kia",
        model="Bongo K2500",
        year_range="2008-2020",
        engine="2.5L CRDi Diesel",
        ecu_type="DCM3.5",
        ecu_manufacturer="Delphi",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Inyectores con retorno excesivo comun despues de 60.000km",
            "Turbo con juego axial por uso en carga pesada",
            "Sensor MAP con lectura incorrecta en altura",
        ],
        tuning_notes=(
            "ECU Delphi DCM 3.5 con lectura por OBD protocolo CAN. "
            "Mapas de inyeccion y presion de riel accesibles. Stage1 "
            "con +15-20CV para mejorar capacidad de carga. Sin DPF de "
            "fabrica. EGR desactivable. Motor compartido con Hyundai HR, "
            "misma base de mapas."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM,
    ),

    # -----------------------------------------------------------------------
    # 14b. Mercedes C280 2008 (nuevo)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Mercedes-Benz",
        model="C280 W204",
        year_range="2008",
        engine="3.0L V6 M272 E30 (231 CV)",
        ecu_type="ME9.7",
        ecu_manufacturer="Bosch",
        fuel_type="gasoline",
        turbo=False,
        available_maps=_GASOLINE_MAPS_FULL,
        known_issues=[
            "M272: desgaste prematuro del engranaje del balanceador (balance shaft gear) tipico en 2005-2008, revisar antes de tunear",
            "Cadenas de distribucion estiradas con alto kilometraje",
            "Sensores de masa de aire (MAF) propensos a suciedad",
            "Bobinas de encendido individuales con fallas recurrentes",
            "Sellos de inyectores perdiendo compresion y causando misfires",
            "Tapones del camshaft adjuster solenoid - fuga de aceite comun",
        ],
        tuning_notes=(
            "ECU Bosch ME9.7 con OBD-II CAN (500k). Motor M272 V6 3.0L naturalmente aspirado. "
            "Stage 1: +15-25 CV via avance de encendido optimizado, tabla de combustible mas precisa, "
            "y remocion del limitador suave en bajas RPM. Se pueden ganar +20 Nm de torque. "
            "IMPORTANTE: revisar estado del balance shaft gear antes de tunear - si hay ruido, "
            "reparar primero. Combustible recomendado 95 RON minimo. No aumentar rev limit sobre "
            "6800 RPM sin inspeccionar resortes de valvulas. Mejora notable en respuesta de "
            "mariposa con tabla de respuesta mas lineal."
        ),
        supported_operations=["stage1", "read", "write", "backup", "restore", "verify_cs", "checksum_fix"],
    ),

    # -----------------------------------------------------------------------
    # 15. Mercedes 1620
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Mercedes-Benz",
        model="1620 / L-1620",
        year_range="2006-2015",
        engine="6.4L OM-906LA Diesel",
        ecu_type="PLD_MR2",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Unidad PLD con fallas electricas por vibracion",
            "Sensor de posicion del arbol de levas desgastado",
            "Cableado de inyectores con aislamiento danado",
        ],
        tuning_notes=(
            "ECU Bosch PLD (Pump-Line-Düse) con comunicacion CAN/J1939. "
            "Mapas de inyeccion y limitador de velocidad/torque accesibles. "
            "Ajuste orientado a mejorar torque bajo y medio para transporte "
            "de carga. Ganancia de 20-30CV en stage1. Limitador de velocidad "
            "modificable."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM + ["speed_limiter_off"],
    ),

    # -----------------------------------------------------------------------
    # 16. Mercedes 2644
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Mercedes-Benz",
        model="Actros 2644 / 2646",
        year_range="2012-2020",
        engine="12.8L OM-501LA Diesel",
        ecu_type="MCM2",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Sistema AdBlue/SCR con fallas de sensor NOx",
            "Turbocompresor de doble etapa con desgaste en etapa alta",
            "Centralita MCM con errores de comunicacion CAN",
        ],
        tuning_notes=(
            "ECU Bosch MCM2 de camion pesado. Lectura por protocolo J1939. "
            "Mapas de inyeccion, limitador de torque y velocidad. Ajuste "
            "orientado a economia de combustible y torque bajo para arranque "
            "con carga. Eliminacion de limitador de velocidad y AdBlue "
            "disponible. Ganancia moderada de 15-25CV."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM + ["speed_limiter_off", "adblue_off"],
    ),

    # -----------------------------------------------------------------------
    # 17. Mercedes Sprinter 415 DCM3.5
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Mercedes-Benz",
        model="Sprinter 415 CDI",
        year_range="2012-2020",
        engine="2.2L OM651 CDI Diesel",
        ecu_type="DCM3.5",
        ecu_manufacturer="Delphi",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Cadena de distribucion con estiramiento prematuro",
            "DPF con regeneracion incompleta en recorridos cortos",
            "Inyectores con goteo y dilusion de aceite",
        ],
        tuning_notes=(
            "ECU Delphi DCM 3.5 con lectura por OBD protocolo UDS. "
            "Mapas completos de inyeccion, presion de riel, boost y DPF. "
            "Stage1 con +25-35CV. DPF y EGR desactivables. Motor OM651 "
            "muy popular en flotas, la eliminacion de DPF es el servicio "
            "mas demandado. Verificar estado de cadena antes de tunear."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 18. Mercedes Accelo
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Mercedes-Benz",
        model="Accelo 815 / 1016",
        year_range="2012-2020",
        engine="4.8L OM-924LA Diesel",
        ecu_type="PLD_MR2",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Unidad PLD con codigos de error por vibracion del chasis",
            "Turbo con desgaste acelerado en uso con sobrecarga",
            "Sensor de temperatura de escape con lectura erronea",
        ],
        tuning_notes=(
            "ECU Bosch PLD para camion mediano. Lectura por J1939. "
            "Mapas de inyeccion y limitadores accesibles. Ajuste de "
            "torque bajo para uso urbano en reparto. Ganancia de 15-20CV. "
            "Limitador de velocidad modificable. Motor OM-924 robusto "
            "para incrementos moderados."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM + ["speed_limiter_off"],
    ),

    # -----------------------------------------------------------------------
    # 19. Mercedes Actros (OBD Diesel)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Mercedes-Benz",
        model="Actros 2041 / 2646",
        year_range="2010-2022",
        engine="12.8L OM-501LA / OM-471 Diesel",
        ecu_type="MCM2.1",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Sistema SCR con cristalizacion de AdBlue en climas frios",
            "Turbo compound con fallas mecanicas en alta carga",
            "Caja automatizada PowerShift con adaptacion lenta",
        ],
        tuning_notes=(
            "ECU Bosch MCM 2.1 de ultima generacion Actros. Protocolo "
            "J1939/UDS. Mapas de inyeccion, torque y velocidad. Ajuste "
            "orientado a economia de combustible con ganancia de 20-30CV. "
            "Desactivacion de AdBlue y limitador de velocidad. Requiere "
            "herramienta especializada para lectura completa."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM + ["speed_limiter_off", "adblue_off"],
    ),

    # -----------------------------------------------------------------------
    # 20. Mitsubishi Triton / L200
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Mitsubishi",
        model="L200 Triton 2.4 DI-D",
        year_range="2015-2023",
        engine="2.4L MIVEC DI-D Diesel",
        ecu_type="DI-D_ECU",
        ecu_manufacturer="Denso",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "DPF con obstruccion frecuente en uso todoterreno",
            "Valvula EGR con acumulacion de hollin severa",
            "Sensor de presion diferencial de DPF con falla",
        ],
        tuning_notes=(
            "ECU Denso con protocolo CAN/UDS. Mapas de inyeccion, "
            "presion de riel y boost accesibles. Stage1 con +25-30CV. "
            "DPF y EGR desactivables. Motor MIVEC diesel con respuesta "
            "mejorada despues del ajuste. Popular en uso rural donde "
            "la eliminacion de DPF es prioritaria."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 21. Mitsubishi L200 Triton 3.2 DI-D
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Mitsubishi",
        model="L200 Triton 3.2 DI-D",
        year_range="2008-2016",
        engine="3.2L DI-D Diesel",
        ecu_type="DI-D_ECU",
        ecu_manufacturer="Denso",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Bomba de inyeccion con desgaste interno en alto kilometraje",
            "Turbo con fuga de aceite por sellos desgastados",
            "Inyectores con retorno excesivo comun despues de 100.000km",
        ],
        tuning_notes=(
            "ECU Denso para motor 3.2 DI-D de generacion anterior. "
            "Lectura por OBD protocolo CAN. Mapas de inyeccion y presion "
            "de riel. Stage1 con +20-25CV. Sin DPF en versiones anteriores "
            "a 2012. EGR desactivable. Motor muy fiable que responde bien "
            "a ajustes moderados de presion de riel."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM,
    ),

    # -----------------------------------------------------------------------
    # 22. Mitsubishi Pajero 3.2 TD
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Mitsubishi",
        model="Pajero 3.2 DI-D",
        year_range="2007-2019",
        engine="3.2L DI-D Turbo Diesel",
        ecu_type="DI-D_ECU",
        ecu_manufacturer="Denso",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Turbo con desgaste en uso off-road intensivo",
            "DPF con fallas en vehiculos usados en ciudad",
            "Caja automatica INVECS con adaptacion problematica",
        ],
        tuning_notes=(
            "ECU Denso compartida con L200. Mapas de inyeccion, boost "
            "y DPF accesibles. Stage1 con +25-35CV ideal para uso "
            "todoterreno. Eliminacion de DPF muy solicitada. Ajuste "
            "de torque bajo mejora la traccion en terreno dificil. "
            "Caja automatica requiere reset de adaptacion post-tuning."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 23. Nissan Frontier 2.3 dCi
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Nissan",
        model="Frontier 2.3 dCi",
        year_range="2016-2023",
        engine="2.3L dCi Biturbo Diesel",
        ecu_type="EDC17C84",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Sistema biturbo con fallas en turbo de baja presion",
            "DPF con regeneracion excesiva en uso mixto",
            "Cadena de distribucion con estiramiento prematuro",
        ],
        tuning_notes=(
            "ECU Bosch EDC17C84 con motor Renault M9T biturbo. Lectura "
            "por OBD protocolo UDS. Mapas completos accesibles. Stage1 "
            "con +30-40CV aprovechando el sistema biturbo. DPF y EGR "
            "desactivables. El sistema biturbo permite ganancias "
            "importantes sin estresar componentes."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 24. Nissan Frontier 190CV
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Nissan",
        model="Frontier 2.3 190CV",
        year_range="2016-2023",
        engine="2.3L dCi 190CV Diesel",
        ecu_type="EDC17C84",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Version de mayor potencia con mayor exigencia termica",
            "Intercooler subdimensionado para uso en temperatura alta",
            "Sensor de presion de sobrealimentacion con deriva",
        ],
        tuning_notes=(
            "Version de 190CV del motor 2.3 dCi con calibracion mas "
            "agresiva de fabrica. Stage1 con +25-35CV adicionales. "
            "Stage2 con escape deportivo e intercooler mejorado llega "
            "a 240CV. Misma ECU EDC17C84 que version de 160CV pero "
            "con mapas de boost y torque mas altos de base."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 25. Nissan Frontier (OBD Diesel - generacion anterior)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Nissan",
        model="Frontier 2.5 dCi",
        year_range="2008-2015",
        engine="2.5L YD25DDTi Diesel",
        ecu_type="DCM3.7",
        ecu_manufacturer="Delphi",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Cadena de distribucion con estiramiento conocido",
            "Turbo con desgaste de sellos y consumo de aceite",
            "Inyectores con retorno excesivo en alto kilometraje",
        ],
        tuning_notes=(
            "ECU Delphi DCM 3.7 con motor YD25. Lectura por OBD CAN. "
            "Mapas de inyeccion y presion de riel accesibles. Stage1 "
            "con +20-25CV. Sin DPF en la mayoria de versiones. EGR "
            "desactivable. Importante verificar estado de cadena antes "
            "de aumentar potencia."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM,
    ),

    # -----------------------------------------------------------------------
    # 26. VW Amarok EDC17C54 (2.0 TDI)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Volkswagen",
        model="Amarok 2.0 TDI",
        year_range="2010-2017",
        engine="2.0L TDI Biturbo Diesel",
        ecu_type="EDC17C54",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Cadena de distribucion con estiramiento despues de 120.000km",
            "DPF con obstruccion en uso urbano",
            "Inyectores piezoelectricos con deriva de caudal",
        ],
        tuning_notes=(
            "ECU Bosch EDC17C54 con multiples versiones de SW. Motor "
            "2.0 TDI biturbo de 180CV de fabrica. Stage1 con +35-45CV "
            "ajustando presion de riel, boost y limitador de torque. "
            "DPF y EGR desactivables. Verificar version exacta de SW "
            "antes de grabar ya que hay muchas variantes."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 27. VW Amarok EDC17C54 (2.0 TDI 140CV)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Volkswagen",
        model="Amarok 2.0 TDI 140CV",
        year_range="2010-2017",
        engine="2.0L TDI Monoturbo Diesel",
        ecu_type="EDC17C54",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Turbo unico con menos reserva que version biturbo",
            "EGR con acumulacion de hollin severa",
            "Bomba de combustible de alta presion con ruido",
        ],
        tuning_notes=(
            "Version monoturbo de 140CV con ECU EDC17C54. Stage1 lleva "
            "a 170-175CV con ajuste de presion de riel y boost. La "
            "ganancia porcentual es mayor que en la version biturbo. "
            "DPF y EGR desactivables. Popular para conversion a mayor "
            "potencia igualando la version biturbo."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 28. VW Amarok EDC17CP20 (3.0 V6 TDI)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Volkswagen",
        model="Amarok 3.0 V6 TDI",
        year_range="2016-2023",
        engine="3.0L V6 TDI Diesel",
        ecu_type="EDC17CP20",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Sistema SCR con fallas de sensor NOx",
            "DPF con regeneracion fallida en uso urbano intensivo",
            "Turbo con actuador electronico con codigos de error",
        ],
        tuning_notes=(
            "ECU Bosch EDC17CP20 con motor V6 TDI de 258CV. Stage1 con "
            "+40-50CV alcanzando 300CV. Stage2 con escape deportivo "
            "supera los 320CV. DPF, EGR y AdBlue desactivables. "
            "Motor V6 con excelente reserva de potencia. Verificar "
            "transmision 8AT antes de stage2."
        ),
        supported_operations=_OPS_DIESEL_FULL + ["adblue_off"],
    ),

    # -----------------------------------------------------------------------
    # 29. VW Constellation 17.250
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Volkswagen",
        model="Constellation 17.250",
        year_range="2010-2020",
        engine="4.6L ISBe Cummins Diesel",
        ecu_type="CM2150",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Motor Cummins con fallas de sensor de presion de aceite",
            "Turbo con desgaste en uso de larga distancia con carga",
            "Sistema electronico con intermitencia por vibracion",
        ],
        tuning_notes=(
            "ECU Bosch con motor Cummins ISBe. Lectura por protocolo "
            "J1939. Mapas de inyeccion y limitadores de torque/velocidad. "
            "Ajuste orientado a economia y torque bajo para arranque. "
            "Ganancia de 20-30CV. Limitador de velocidad modificable. "
            "Motor Cummins muy robusto para incrementos moderados."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM + ["speed_limiter_off"],
    ),

    # -----------------------------------------------------------------------
    # 30. Volvo VM 270
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Volvo",
        model="VM 270",
        year_range="2012-2020",
        engine="7.2L D7E Diesel",
        ecu_type="EMS2",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Inyector unitario (EUI) con desgaste en alto kilometraje",
            "Sistema de post-tratamiento SCR con fallas de dosificacion",
            "Turbo con erosion de alabes por particulas",
        ],
        tuning_notes=(
            "ECU Bosch EMS2 con motor D7E de 270CV. Lectura por J1939. "
            "Mapas de inyeccion y limitadores accesibles. Ajuste orientado "
            "a mejorar torque bajo/medio para uso en ruta con carga. "
            "Ganancia de 20-30CV. Limitador de velocidad modificable."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM + ["speed_limiter_off"],
    ),

    # -----------------------------------------------------------------------
    # 31. Volvo VM 6.5 / 4.8 / 7.2 (OBD Diesel)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Volvo",
        model="VM 210 / 260 / 330",
        year_range="2008-2022",
        engine="4.8L / 6.5L / 7.2L D-series Diesel",
        ecu_type="EMS2",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Variante de 4.8L con menos reserva termica en carga pesada",
            "Motor 7.2L con consumo de aceite elevado en alto kilometraje",
            "Sensor de presion de sobrealimentacion con deriva",
        ],
        tuning_notes=(
            "Familia Volvo VM con ECU Bosch EMS2. Motores de 4.8L a 7.2L "
            "con potencias de 210CV a 330CV. Lectura por J1939. Mapas "
            "compartidos entre variantes con diferentes limitadores. "
            "Ajuste de torque y velocidad. Ganancia variable segun motor. "
            "Motor D7E y D5K muy robustos."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM + ["speed_limiter_off"],
    ),

    # -----------------------------------------------------------------------
    # 32. Agrale Furgovan / Volare
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Agrale",
        model="Furgovan / Volare 8150",
        year_range="2008-2018",
        engine="3.0L MWM Diesel",
        ecu_type="EDC7UC31",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Motor MWM con consumo de aceite elevado",
            "Turbo con desgaste acelerado por uso en reparto urbano",
            "Sistema electrico con interferencias por alternador",
        ],
        tuning_notes=(
            "ECU Bosch EDC7UC31 con motor MWM. Lectura por J1939. "
            "Mapas de inyeccion y limitadores basicos. Ajuste orientado "
            "a mejorar torque bajo para uso en reparto y transporte de "
            "pasajeros. Ganancia de 10-15CV. Limitador de velocidad "
            "modificable para microbus."
        ),
        supported_operations=_OPS_DIESEL_BASIC + ["speed_limiter_off"],
    ),

    # -----------------------------------------------------------------------
    # 33. Agrale Marrua / MA12
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Agrale",
        model="Marrua AM200 / MA12",
        year_range="2006-2018",
        engine="2.8L MWM Sprint Diesel",
        ecu_type="EDC16C39",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Motor MWM Sprint con vibracion excesiva en ralenti",
            "Inyectores con retorno elevado despues de 80.000km",
            "Sistema de precalentamiento de bujias con fallas",
        ],
        tuning_notes=(
            "ECU Bosch EDC16C39 con motor MWM Sprint 2.8. Lectura por "
            "OBD protocolo CAN. Mapas de inyeccion y presion de riel. "
            "Stage1 con +15-20CV para uso todoterreno militar/civil. "
            "Sin DPF. EGR desactivable. Motor robusto pero con menor "
            "reserva de potencia que motores mas modernos."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM,
    ),

    # -----------------------------------------------------------------------
    # 34. Citroen Jumper
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Citroen",
        model="Jumper 2.3 HDi",
        year_range="2010-2020",
        engine="2.3L HDi Diesel",
        ecu_type="MJD_8F3",
        ecu_manufacturer="Magneti Marelli",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Motor compartido con Fiat Ducato, mismos problemas de EGR",
            "Turbo de geometria variable trabado por carbon",
            "DPF con regeneracion fallida en recorridos cortos",
        ],
        tuning_notes=(
            "Mismo motor y ECU que Fiat Ducato 2.3 (MJD_8F3). Aplican "
            "los mismos mapas y procedimientos. Stage1 con +20-30CV. "
            "DPF y EGR desactivables. Muy solicitado para flotas de "
            "reparto donde la regeneracion de DPF causa paradas."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 35. Fiat Ducato 2.8 JTD
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Fiat",
        model="Ducato 2.8 JTD",
        year_range="2002-2010",
        engine="2.8L JTD Diesel",
        ecu_type="EDC15C7",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Bomba de inyeccion Bosch CP1 con desgaste interno",
            "Inyectores con goteo y humo blanco en frio",
            "Turbo con juego axial en vehiculos de alto kilometraje",
        ],
        tuning_notes=(
            "ECU Bosch EDC15C7 de generacion anterior. Lectura por OBD "
            "protocolo K-Line. Mapas de inyeccion y presion de riel "
            "basicos. Stage1 con +15-20CV. Sin DPF. EGR desactivable. "
            "Motor JTD 2.8 muy robusto pero con inyectores que requieren "
            "verificacion antes del ajuste."
        ),
        supported_operations=_OPS_DIESEL_BASIC,
    ),

    # -----------------------------------------------------------------------
    # 36. Fiat Ducato Cargo 2.3 (generacion actual)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Fiat",
        model="Ducato Cargo 2.3 Multijet II",
        year_range="2014-2023",
        engine="2.3L Multijet II Euro 5 Diesel",
        ecu_type="MJD_9DF",
        ecu_manufacturer="Magneti Marelli",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Sensor de presion diferencial de DPF defectuoso",
            "Valvula EGR electronica con bloqueo mecanico",
            "Turbo con actuador electronico con fallas intermitentes",
        ],
        tuning_notes=(
            "ECU Magneti Marelli MJD_9DF evolucion del MJD_8F3. Mapas "
            "mas complejos con control de emisiones Euro 5. Stage1 con "
            "+25-35CV. DPF y EGR desactivables. AdBlue presente en "
            "algunas versiones. Verificar version exacta de calibracion."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 37. GM Tracker 2.0 Diesel
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Chevrolet",
        model="Tracker 2.0 VCDi",
        year_range="2013-2017",
        engine="2.0L VCDi Diesel",
        ecu_type="EDC17C59",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "DPF con obstruccion prematura en uso urbano",
            "Inyectores con problema de codificacion IMA",
            "Turbo con actuador electronico defectuoso",
        ],
        tuning_notes=(
            "ECU Bosch EDC17C59 con motor 2.0 VCDi. Lectura por OBD "
            "protocolo UDS. Mapas completos accesibles. Stage1 con "
            "+20-25CV. DPF y EGR desactivables. Motor compacto con "
            "buena respuesta al tuning. Verificar codificacion de "
            "inyectores despues de cualquier cambio."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 38. GM S10 2.8 (OBD Diesel)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Chevrolet",
        model="S10 2.8 CTDi High Country",
        year_range="2017-2023",
        engine="2.8L Duramax Gen II Diesel",
        ecu_type="EDC17C69",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Sistema SCR con fallas de inyeccion de AdBlue",
            "DPF con regeneracion activa demasiado frecuente",
            "Sensor de NOx con lecturas erraticas",
        ],
        tuning_notes=(
            "ECU Bosch EDC17C69 generacion nueva con control Euro 5. "
            "Lectura por OBD protocolo UDS. Stage1 con +35-45CV. DPF, "
            "EGR y AdBlue desactivables. Motor Duramax Gen II con buena "
            "reserva de potencia. Transmision automatica 6AT requiere "
            "adaptacion post-tuning."
        ),
        supported_operations=_OPS_DIESEL_FULL + ["adblue_off"],
    ),

    # -----------------------------------------------------------------------
    # 39. Peugeot Partner
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Peugeot",
        model="Partner 1.6 HDi",
        year_range="2010-2020",
        engine="1.6L HDi Diesel",
        ecu_type="EDC17C10",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Turbo con desgaste de sellos y consumo de aceite",
            "DPF con problemas de regeneracion en uso exclusivamente urbano",
            "Valvula de descarga de turbo con pegado",
        ],
        tuning_notes=(
            "ECU Bosch EDC17C10 con motor PSA 1.6 HDi. Lectura por OBD "
            "protocolo UDS. Mapas completos accesibles. Stage1 con "
            "+15-20CV. DPF y EGR desactivables. Motor pequeno con "
            "ganancia limitada pero mejora notable en torque bajo "
            "para uso en reparto con carga."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 40. Renault Master 2.5
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Renault",
        model="Master 2.5 dCi",
        year_range="2006-2016",
        engine="2.5L dCi G9U Diesel",
        ecu_type="EDC16C36",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Inyectores con goteo y dilusion de aceite del motor",
            "Turbo con desgaste acelerado en uso con sobrecarga",
            "Sensor de presion del riel con fallas intermitentes",
        ],
        tuning_notes=(
            "ECU Bosch EDC16C36 con motor G9U. Lectura por OBD protocolo "
            "CAN. Mapas de inyeccion y presion de riel accesibles. Stage1 "
            "con +15-20CV. Sin DPF en versiones hasta 2010. EGR "
            "desactivable. Motor robusto para incrementos moderados de "
            "potencia orientados a mejorar torque con carga."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM,
    ),

    # -----------------------------------------------------------------------
    # 41. Renault Master 2.8
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Renault",
        model="Master 2.8 dTI",
        year_range="2002-2010",
        engine="2.8L dTI S9W Diesel",
        ecu_type="EDC15C3",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Bomba de inyeccion Bosch VP44 con fallas electronicas",
            "Motor S9W Sofim con junta de culata debil",
            "Turbo con desgaste en vehiculos de alto kilometraje",
        ],
        tuning_notes=(
            "ECU Bosch EDC15C3 de generacion anterior. Lectura por "
            "protocolo K-Line. Mapas basicos de inyeccion. Stage1 con "
            "+10-15CV. Sin DPF. Motor Sofim 2.8 compartido con Iveco "
            "Daily antigua. Ajuste conservador recomendado por edad "
            "del motor."
        ),
        supported_operations=_OPS_DIESEL_BASIC,
    ),

    # -----------------------------------------------------------------------
    # 42. Scania G380
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Scania",
        model="G380 / P380",
        year_range="2008-2018",
        engine="11.7L DC12 Diesel",
        ecu_type="EMS_S6",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Inyectores unitarios XPI con desgaste en alto kilometraje",
            "Sistema EGR con acumulacion severa de hollin",
            "Sensor de presion de sobrealimentacion con deriva",
        ],
        tuning_notes=(
            "ECU Scania EMS S6 con comunicacion J1939. Mapas de inyeccion "
            "y limitadores de torque/velocidad. Ajuste orientado a economia "
            "de combustible con ganancia de 20-30CV. Motor DC12 muy "
            "robusto. Limitador de velocidad modificable. Requiere "
            "herramienta Scania VCI o compatible para acceso completo."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM + ["speed_limiter_off"],
    ),

    # -----------------------------------------------------------------------
    # 43. Scania G420
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Scania",
        model="G420 / R420",
        year_range="2008-2018",
        engine="11.7L DC12 420CV Diesel",
        ecu_type="EMS_S6",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Version de mayor potencia con mayor exigencia termica",
            "Turbocompresor con erosion de alabes en uso intensivo",
            "Sistema SCR con cristalizacion de AdBlue",
        ],
        tuning_notes=(
            "Misma plataforma EMS S6 que G380 pero con calibracion de "
            "420CV. Stage1 orientado a economia con ganancia de 15-25CV. "
            "Stage2 con +40CV requiere verificacion de turbo. Limitador "
            "de velocidad modificable. Motor con buena reserva mecanica "
            "para incrementos moderados."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM + ["speed_limiter_off", "adblue_off"],
    ),

    # -----------------------------------------------------------------------
    # 44. Toyota Hilux 2.5 D4D
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Toyota",
        model="Hilux 2.5 D-4D",
        year_range="2005-2015",
        engine="2.5L 2KD-FTV D-4D Diesel",
        ecu_type="D4D_ECU",
        ecu_manufacturer="Denso",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Inyectores con problema de codificacion y drift",
            "Turbo con desgaste de sellos en uso off-road",
            "Sensor MAF con contaminacion por polvo",
        ],
        tuning_notes=(
            "ECU Denso con motor 2KD-FTV. Lectura por OBD protocolo "
            "CAN/ISO. Mapas de inyeccion y presion de riel accesibles. "
            "Stage1 con +15-20CV. Sin DPF en mayoria de versiones. "
            "EGR desactivable. Motor Toyota muy fiable pero conservador "
            "de fabrica, responde bien a ajustes moderados."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM,
    ),

    # -----------------------------------------------------------------------
    # 45. Toyota Hilux 3.0 D4D
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Toyota",
        model="Hilux 3.0 D-4D",
        year_range="2005-2015",
        engine="3.0L 1KD-FTV D-4D Diesel",
        ecu_type="D4D_ECU",
        ecu_manufacturer="Denso",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Inyector numero 5 con falla conocida de goteo",
            "DPF presente en versiones Euro 4+ con obstruccion",
            "Turbo de geometria variable con actuador lento",
        ],
        tuning_notes=(
            "ECU Denso con motor 1KD-FTV de 171CV. Mapas completos "
            "accesibles. Stage1 con +25-30CV. DPF desactivable en "
            "versiones que lo tienen. EGR off popular. Motor 1KD-FTV "
            "legendario por fiabilidad, acepta bien stage1 sin "
            "problemas de durabilidad."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 46. Toyota Land Cruiser Prado D4D
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Toyota",
        model="Land Cruiser Prado 3.0 D-4D",
        year_range="2007-2015",
        engine="3.0L 1KD-FTV D-4D Diesel",
        ecu_type="D4D_ECU",
        ecu_manufacturer="Denso",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "DPF con obstruccion en uso todoterreno con polvo",
            "Inyectores con drift en vehiculos de alto kilometraje",
            "Turbo con desgaste en altitud elevada",
        ],
        tuning_notes=(
            "Mismo motor 1KD-FTV que Hilux pero con calibracion para "
            "vehiculo mas pesado. Stage1 con +25-30CV mejora notablemente "
            "la respuesta con carga. DPF off muy solicitado para uso "
            "off-road. ECU compartida con Hilux, misma base de mapas."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 47. Ranger 3.2 ATM SID208 (automatica)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Ford",
        model="Ranger 3.2 TDCi Automatica",
        year_range="2013-2019",
        engine="3.2L Duratorq 5-cyl TDCi ATM",
        ecu_type="SID208",
        ecu_manufacturer="Continental",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL + ["transmission_map"],
        known_issues=[
            "Transmision automatica 6R80 con cambios bruscos en caliente",
            "Convertidor de torque con vibracion despues de tuning",
            "Mapas de transmision requieren ajuste post-tuning",
        ],
        tuning_notes=(
            "Misma ECU SID208 que version manual pero con mapa de "
            "transmision automatica 6R80. Stage1 requiere ajuste de "
            "presion de linea y puntos de cambio de la transmision. "
            "Sin ajuste de ATM el convertidor sufre. Ganancia de "
            "30-40CV con ajuste coordinado motor + transmision."
        ),
        supported_operations=_OPS_DIESEL_FULL + ["transmission_tune"],
    ),

    # -----------------------------------------------------------------------
    # 48. Fiat Ducato 2.3 (version Euro 6)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Fiat",
        model="Ducato 2.3 Multijet Euro 6",
        year_range="2019-2023",
        engine="2.3L Multijet III Euro 6 Diesel",
        ecu_type="MJD_9DF2",
        ecu_manufacturer="Magneti Marelli",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Sistema SCR con dosificacion de AdBlue incorrecta",
            "DPF con sensor de presion diferencial defectuoso",
            "Software de ECU con actualizaciones OTA problematicas",
        ],
        tuning_notes=(
            "ECU Magneti Marelli MJD_9DF2 ultima generacion Euro 6. "
            "Mayor complejidad en control de emisiones. Stage1 con "
            "+25-35CV. DPF, EGR y AdBlue desactivables pero requiere "
            "calibracion completa. Verificar version de SW y si tiene "
            "actualizaciones OTA pendientes antes de intervenir."
        ),
        supported_operations=_OPS_DIESEL_FULL + ["adblue_off"],
    ),

    # -----------------------------------------------------------------------
    # 49. GM S10 2.5 Flex
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Chevrolet",
        model="S10 2.5 Flex Advantage",
        year_range="2014-2019",
        engine="2.5L Ecotec Flex",
        ecu_type="E83",
        ecu_manufacturer="Continental",
        fuel_type="flex",
        turbo=False,
        available_maps=_FLEX_MAPS,
        known_issues=[
            "Motor flex con perdida de potencia con etanol de baja calidad",
            "Sensor de detonacion sensible en verano con nafta comun",
            "Cuerpo de aceleracion con acumulacion de carbonilla",
        ],
        tuning_notes=(
            "ECU Continental E83 con motor 2.5 Ecotec flex. Lectura por "
            "OBD protocolo CAN/UDS. Mapas de encendido e inyeccion para "
            "ambos combustibles. Ajuste de avance +2-3 grados con nafta "
            "premium. Mapa de aceleracion mejorable. Ganancia de 8-12CV. "
            "Sin turbo, la ganancia es limitada."
        ),
        supported_operations=_OPS_FLEX,
    ),

    # -----------------------------------------------------------------------
    # 50. Chevrolet S10 2.8 EDC16C39 (version anterior)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Chevrolet",
        model="S10 2.8 MWM",
        year_range="2006-2011",
        engine="2.8L MWM Sprint 4.07 Diesel",
        ecu_type="EDC16C39",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_BASIC,
        known_issues=[
            "Motor MWM con vibracion excesiva a ralenti",
            "Bomba de inyeccion CP3 con desgaste interno",
            "Turbo con juego axial en alto kilometraje",
        ],
        tuning_notes=(
            "ECU Bosch EDC16C39 con motor MWM Sprint. Lectura por OBD "
            "protocolo CAN/K-Line. Mapas de inyeccion y presion de riel. "
            "Stage1 con +20-25CV. Sin DPF. EGR desactivable. Version "
            "anterior de la S10 con motor MWM, distinto al Duramax."
        ),
        supported_operations=_OPS_DIESEL_MEDIUM,
    ),

    # -----------------------------------------------------------------------
    # 51. Peugeot Partner (version mas nueva)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Peugeot",
        model="Partner 1.6 BlueHDi",
        year_range="2016-2022",
        engine="1.6L BlueHDi Euro 6 Diesel",
        ecu_type="EDC17C60",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Sistema SCR con fallas de sensor de temperatura de AdBlue",
            "DPF con regeneracion incompleta cronica",
            "Turbo de geometria variable con actuador defectuoso",
        ],
        tuning_notes=(
            "ECU Bosch EDC17C60 con motor BlueHDi Euro 6. Mayor "
            "complejidad que version anterior. Stage1 con +15-20CV. "
            "DPF, EGR y AdBlue desactivables. Requiere anulacion "
            "completa de sensores de emisiones para eliminacion "
            "correcta de DPF."
        ),
        supported_operations=_OPS_DIESEL_FULL + ["adblue_off"],
    ),

    # -----------------------------------------------------------------------
    # 52. Citroen Jumper (version nueva)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Citroen",
        model="Jumper 2.0 BlueHDi",
        year_range="2017-2023",
        engine="2.0L BlueHDi Euro 6 Diesel",
        ecu_type="EDC17C60",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "Motor 2.0 BlueHDi con problema de dilucion de aceite",
            "Sistema AdBlue con bomba de dosificacion defectuosa",
            "DPF con acumulacion de cenizas prematuro",
        ],
        tuning_notes=(
            "ECU Bosch EDC17C60 con motor PSA 2.0 BlueHDi. Plataforma "
            "compartida con Fiat Ducato y Peugeot Boxer. Stage1 con "
            "+20-30CV. DPF, EGR y AdBlue desactivables. Procedimiento "
            "identico a Peugeot Boxer y Fiat Ducato de misma generacion."
        ),
        supported_operations=_OPS_DIESEL_FULL + ["adblue_off"],
    ),

    # -----------------------------------------------------------------------
    # 53. Ford Focus 2.0 TDCi (diesel)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Ford",
        model="Focus 2.0 TDCi",
        year_range="2012-2018",
        engine="2.0L Duratorq TDCi Diesel",
        ecu_type="SID807EVO",
        ecu_manufacturer="Continental",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "DPF con obstruccion prematura en conduccion urbana",
            "Inyectores con codificacion IMA perdida tras desconexion",
            "Bomba de alta presion con ruido metalico en frio",
        ],
        tuning_notes=(
            "ECU Continental SID807EVO con motor Duratorq 2.0 TDCi. "
            "Lectura por OBD protocolo UDS. Mapas completos accesibles. "
            "Stage1 con +25-30CV. DPF y EGR desactivables. Motor con "
            "buena respuesta al tuning. Popular en version sedan y "
            "hatchback para uso diario mejorado."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 54. Hyundai HR (version Euro 5)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Hyundai",
        model="HR 2.5 CRDi Euro 5",
        year_range="2014-2020",
        engine="2.5L CRDi Euro 5 Diesel",
        ecu_type="EDC17C57",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "DPF con regeneracion activa excesiva en uso urbano",
            "Sensor de presion diferencial de DPF con falla",
            "EGR con acumulacion de hollin y reduccion de potencia",
        ],
        tuning_notes=(
            "ECU Bosch EDC17C57 en versiones mas nuevas con DPF. "
            "Lectura por OBD protocolo UDS. Mapas completos accesibles. "
            "Stage1 con +20-25CV. DPF y EGR desactivables. Mismo motor "
            "base que version con Delphi pero con ECU Bosch y control "
            "de emisiones mas complejo."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 55. Kia Bongo (version Euro 5)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Kia",
        model="Bongo K2500 Euro 5",
        year_range="2016-2022",
        engine="2.5L CRDi Euro 5 Diesel",
        ecu_type="EDC17C57",
        ecu_manufacturer="Bosch",
        fuel_type="diesel",
        turbo=True,
        available_maps=_DIESEL_MAPS_FULL,
        known_issues=[
            "DPF con obstruccion en uso exclusivo de reparto urbano",
            "Sensor NOx con lectura erronea despues de regeneracion",
            "Valvula EGR electronica con bloqueo mecanico",
        ],
        tuning_notes=(
            "ECU Bosch EDC17C57 compartida con Hyundai HR Euro 5. "
            "Mismos mapas y procedimientos. Stage1 con +20-25CV. DPF "
            "y EGR desactivables. Orientado a mejorar torque bajo para "
            "uso en carga y reparto."
        ),
        supported_operations=_OPS_DIESEL_FULL,
    ),

    # -----------------------------------------------------------------------
    # 56. Mazda 6 2004 2.3L (nuevo)
    # -----------------------------------------------------------------------
    VehicleECUConfig(
        make="Mazda",
        model="Mazda6 (GG1)",
        year_range="2003-2005",
        engine="2.3L L3-VE (166 CV) MZR",
        ecu_type="Denso 275800",
        ecu_manufacturer="Denso",
        fuel_type="gasoline",
        turbo=False,
        available_maps=_GASOLINE_MAPS_FULL,
        known_issues=[
            "Bobinas de encendido COP con fallas por temperatura - causa P0300-P0304",
            "VVT solenoid con acumulacion de carbonilla (P0012, P0011)",
            "Sensor MAF contaminado produce STFT/LTFT fuera de rango",
            "Corrosion en conectores de sensores O2 posteriores",
            "Termostato trabado abierto - P0128",
            "Tapas de valvulas con fuga de aceite - comun despues de 150,000km",
            "Sensor de posicion de cigueñal (CKP) con fallas intermitentes",
        ],
        tuning_notes=(
            "ECU Denso 275800 con protocolo KWP2000 (ISO 14230) fast init. "
            "Motor L3-VE MZR 2.3L naturalmente aspirado con VVT en admision. "
            "Stage 1: +8-12 CV via tabla de encendido optimizada y AFR mas rico "
            "bajo carga. Aprovechar margen antiknock hasta 37 deg BTDC seguros. "
            "El swap a la version MPS (turbo) es comun en esta plataforma. "
            "IMPORTANTE: verificar VVT antes de tunear - si hay codigos P0011/P0012 "
            "limpiar solenoide y actuador primero. Rev limit original 6500 RPM - "
            "se puede subir a 6700 RPM con bujias un grado mas frias. "
            "Respuesta de mariposa electronica (drive-by-wire) mejora notablemente."
        ),
        supported_operations=["stage1", "read", "write", "backup", "restore", "checksum_fix"],
    ),
]


# ---------------------------------------------------------------------------
# VehicleMapDatabase - clase de consulta
# ---------------------------------------------------------------------------

class VehicleMapDatabase:
    """Base de datos de configuraciones ECU de vehiculos conocidos.

    Provee metodos de busqueda por fabricante, modelo, tipo de ECU
    y busqueda difusa por texto libre.
    """

    def __init__(self, entries: list[VehicleECUConfig] | None = None) -> None:
        self._entries: list[VehicleECUConfig] = list(entries or VEHICLE_DATABASE)

    # -- Consultas ---------------------------------------------------------

    def get_by_make(self, make: str) -> list[VehicleECUConfig]:
        """Devuelve todos los vehiculos de un fabricante (case-insensitive)."""
        make_lower = make.lower()
        return [v for v in self._entries if v.make.lower() == make_lower]

    def get_by_ecu(self, ecu_type: str) -> list[VehicleECUConfig]:
        """Devuelve todos los vehiculos con un tipo de ECU especifico."""
        ecu_lower = ecu_type.lower()
        return [
            v for v in self._entries
            if v.ecu_type.lower() == ecu_lower
        ]

    def get_by_model(self, make: str, model: str) -> list[VehicleECUConfig]:
        """Devuelve vehiculos que coincidan con fabricante y modelo.

        La comparacion de *model* es parcial: busca si el texto aparece
        dentro del campo ``model`` del registro.
        """
        make_lower = make.lower()
        model_lower = model.lower()
        return [
            v for v in self._entries
            if v.make.lower() == make_lower
            and model_lower in v.model.lower()
        ]

    def search(self, query: str) -> list[VehicleECUConfig]:
        """Busqueda difusa por texto libre.

        Busca coincidencias parciales en los campos ``make``, ``model``,
        ``engine``, ``ecu_type`` y ``tuning_notes``.  Devuelve resultados
        ordenados por cantidad de coincidencias de tokens (mayor primero).
        """
        tokens = query.lower().split()
        if not tokens:
            return []

        scored: list[tuple[int, VehicleECUConfig]] = []
        for v in self._entries:
            haystack = " ".join([
                v.make, v.model, v.engine, v.ecu_type,
                v.ecu_manufacturer, v.fuel_type, v.tuning_notes,
            ]).lower()
            hits = sum(1 for t in tokens if t in haystack)
            if hits > 0:
                scored.append((hits, v))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [v for _, v in scored]

    def get_all_makes(self) -> list[str]:
        """Devuelve lista ordenada de todos los fabricantes unicos."""
        return sorted({v.make for v in self._entries})

    def get_all_ecus(self) -> list[str]:
        """Devuelve lista ordenada de todos los tipos de ECU unicos."""
        return sorted({v.ecu_type for v in self._entries})

    def get_by_fuel_type(self, fuel_type: str) -> list[VehicleECUConfig]:
        """Devuelve vehiculos filtrados por tipo de combustible."""
        fuel_lower = fuel_type.lower()
        return [v for v in self._entries if v.fuel_type.lower() == fuel_lower]

    def get_by_manufacturer(self, ecu_manufacturer: str) -> list[VehicleECUConfig]:
        """Devuelve vehiculos filtrados por fabricante de ECU."""
        mfr_lower = ecu_manufacturer.lower()
        return [
            v for v in self._entries
            if v.ecu_manufacturer.lower() == mfr_lower
        ]

    def get_turbocharged(self) -> list[VehicleECUConfig]:
        """Devuelve todos los vehiculos turboalimentados."""
        return [v for v in self._entries if v.turbo]

    @property
    def count(self) -> int:
        """Cantidad total de vehiculos en la base de datos."""
        return len(self._entries)

    def __len__(self) -> int:
        return self.count

    def __iter__(self):
        return iter(self._entries)


# ---------------------------------------------------------------------------
# Singleton de conveniencia
# ---------------------------------------------------------------------------

vehicle_db = VehicleMapDatabase()
