"""
Build expert_knowledge_v2.json by merging the existing expert_knowledge.json
with a large curated expansion of DTCs, torques, decision trees, pinouts,
TSBs and VIN patterns. All new entries follow the same schema as the
existing file so that inject_knowledge.py keeps working unchanged.

Run: python backend/knowledge_hub/build_v2.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "expert_knowledge.json"
DST = HERE / "expert_knowledge_v2.json"


# --------------------------------------------------------------------------- #
# NEW DTCs (SAE J2012 + manufacturer specific). Extracted from SAE standards,
# Bosch / Delphi / Denso repair literature and factory service manuals.
# --------------------------------------------------------------------------- #

def _dtc(desc, severity, symptoms, causes, tree, components, makes, tools,
         cost, hours, sources=None, safety=None):
    entry = {
        "description_es": desc,
        "severity": severity,
        "symptoms": symptoms,
        "probable_causes": causes,
        "diagnostic_tree": tree,
        "related_components": components,
        "affected_makes": makes,
        "recommended_tools": tools,
        "sources": sources or ["SAE J2012", "data/obd-diesel/", "data/datos-tecnicos/"],
        "cost_range_usd": cost,
        "time_hours": hours,
    }
    if safety:
        entry["safety_warning"] = safety
    return entry


NEW_DTCS: dict[str, dict] = {
    # ----- Powertrain - generic SAE -----
    "P0010": _dtc(
        "Circuito actuador VVT 'A' banco 1 - malfuncion",
        "medium",
        ["MIL", "ralenti inestable", "codigo P0011 relacionado"],
        ["solenoide VVT abierto/cortocircuitado", "cableado", "ECM driver"],
        [
            {"step": 1, "check": "resistencia solenoide", "expected": "6-12 ohm"},
            {"step": 2, "check": "12V en conector", "expected": "bateria"},
            {"step": 3, "check": "PWM del ECM con oscilo"},
        ],
        ["solenoide VVT", "cableado"],
        ["toyota", "ford", "gm", "honda", "mazda", "hyundai", "kia"],
        ["multimetro", "scanner", "osciloscopio"],
        [60, 400], 1.5,
    ),
    "P0012": _dtc(
        "VVT banco 1 - retraso excesivo",
        "medium",
        ["ralenti rough", "consumo elevado", "MIL"],
        ["solenoide VVT sucio", "aceite degradado", "cadena desgastada", "filtro VVT tapado"],
        [
            {"step": 1, "check": "aceite fresco OEM"},
            {"step": 2, "check": "limpieza solenoide VVT"},
            {"step": 3, "check": "cadena distribucion"},
        ],
        ["solenoide VVT", "aceite", "cadena distribucion"],
        ["toyota", "nissan", "ford", "gm"],
        ["scanner", "cambio aceite"],
        [80, 600], 2.0,
    ),
    "P0013": _dtc(
        "Circuito solenoide VVT escape banco 1",
        "medium",
        ["MIL", "perdida potencia baja"],
        ["solenoide exhaust VVT abierto", "cableado", "driver ECM"],
        [
            {"step": 1, "check": "resistencia solenoide exhaust VVT", "expected": "6-12 ohm"},
            {"step": 2, "check": "alimentacion 12V"},
        ],
        ["solenoide exhaust VVT"],
        ["ford", "gm", "toyota"],
        ["multimetro"],
        [60, 400], 1.5,
    ),
    "P0014": _dtc(
        "VVT escape banco 1 - avance excesivo",
        "medium",
        ["ralenti rough", "MIL"],
        ["solenoide exh VVT pegado", "aceite contaminado"],
        [{"step": 1, "check": "aceite OEM, cambio"}, {"step": 2, "check": "solenoide limpio"}],
        ["solenoide exhaust VVT", "aceite"],
        ["ford", "gm", "toyota", "hyundai"],
        ["scanner"],
        [80, 500], 2.0,
    ),
    "P0017": _dtc(
        "Correlacion CKP-CMP banco 1 sensor B",
        "high",
        ["arranque dificil", "perdida potencia"],
        ["cadena saltada", "tensor hidraulico"],
        [
            {"step": 1, "check": "marcas distribucion visual"},
            {"step": 2, "check": "desfase con scanner"},
        ],
        ["cadena distribucion", "tensor"],
        ["gm", "ford", "bmw"],
        ["kit distribucion"],
        [400, 2500], 6.0,
    ),
    "P0020": _dtc(
        "Circuito actuador VVT 'A' banco 2",
        "medium",
        ["MIL"],
        ["solenoide VVT banco 2", "cableado"],
        [{"step": 1, "check": "resistencia VVT bank 2"}, {"step": 2, "check": "PWM"}],
        ["VVT banco 2"],
        ["ford", "gm", "toyota", "nissan"],
        ["multimetro"],
        [60, 400], 1.5,
    ),
    "P0021": _dtc(
        "VVT banco 2 - avance excesivo",
        "medium",
        ["ralenti rough", "MIL"],
        ["solenoide pegado", "aceite degradado"],
        [{"step": 1, "check": "aceite"}, {"step": 2, "check": "solenoide"}],
        ["VVT banco 2"],
        ["ford", "gm", "toyota"],
        ["scanner"],
        [80, 600], 2.0,
    ),
    "P0030": _dtc(
        "Circuito calentador HO2S banco 1 sensor 1 - malfuncion",
        "medium",
        ["MIL", "loop abierto prolongado"],
        ["calentador O2 abierto", "fusible", "driver ECM"],
        [{"step": 1, "check": "resistencia calentador 3-15 ohm"}, {"step": 2, "check": "12V y GND"}],
        ["sensor O2 upstream banco 1"],
        ["*"],
        ["multimetro"],
        [60, 300], 1.0,
    ),
    "P0036": _dtc(
        "Circuito calentador HO2S banco 1 sensor 2",
        "medium",
        ["MIL", "monitor cat no completa"],
        ["calentador open", "fusible"],
        [{"step": 1, "check": "resistencia"}, {"step": 2, "check": "alimentacion"}],
        ["sensor O2 downstream"],
        ["*"],
        ["multimetro"],
        [60, 300], 1.0,
    ),
    "P0050": _dtc(
        "Circuito calentador HO2S banco 2 sensor 1",
        "medium",
        ["MIL"],
        ["calentador abierto banco 2"],
        [{"step": 1, "check": "resistencia"}, {"step": 2, "check": "alimentacion"}],
        ["sensor O2 banco 2"],
        ["*"],
        ["multimetro"],
        [60, 300], 1.0,
    ),
    "P0068": _dtc(
        "MAP/MAF vs posicion acelerador - correlacion",
        "medium",
        ["tirones", "MIL", "posible limp"],
        ["fuga vacio grande", "MAP colapsado", "TB sucio"],
        [
            {"step": 1, "check": "prueba fugas con humo"},
            {"step": 2, "check": "MAP en vacio vs KPa esperado"},
            {"step": 3, "check": "limpiar throttle body"},
        ],
        ["MAP", "TPS", "TB"],
        ["chrysler", "dodge", "jeep", "gm", "ford"],
        ["smoke machine", "scanner"],
        [50, 500], 1.5,
    ),
    "P0089": _dtc(
        "Regulador de presion combustible 1 - rendimiento",
        "high",
        ["limp", "perdida potencia", "humo negro diesel"],
        ["MPROP/DRV desgastado", "fuga retorno", "bomba CP desgastada"],
        [
            {"step": 1, "check": "presion comandada vs real"},
            {"step": 2, "check": "retorno inyectores balanceado"},
            {"step": 3, "check": "MPROP con oscilo PWM 30-70%"},
        ],
        ["regulador MPROP/DRV", "bomba CP", "inyectores"],
        ["vw", "ford", "bmw", "mercedes", "fiat", "opel"],
        ["manometro common rail", "osciloscopio"],
        [200, 2000], 3.5,
    ),
    "P0106": _dtc(
        "Sensor MAP/BARO - rango/rendimiento",
        "medium",
        ["MIL", "consumo elevado", "ralenti rough"],
        ["MAP obstruido carbon", "fuga vacio", "manguera MAP rota"],
        [
            {"step": 1, "check": "MAP key-on engine-off ~101 kPa"},
            {"step": 2, "check": "MAP idle 30-40 kPa"},
            {"step": 3, "check": "fugas vacio"},
        ],
        ["sensor MAP", "manguera MAP"],
        ["*"],
        ["scanner", "vacuum gauge"],
        [40, 250], 1.0,
    ),
    "P0107": _dtc(
        "Sensor MAP - senal baja",
        "medium",
        ["MIL", "arranque dificil"],
        ["MAP abierto", "5V ref perdida"],
        [{"step": 1, "check": "5V ref"}, {"step": 2, "check": "senal salida 0.5-4.5V"}],
        ["MAP"],
        ["*"],
        ["multimetro"],
        [50, 200], 1.0,
    ),
    "P0108": _dtc(
        "Sensor MAP - senal alta",
        "medium",
        ["MIL"],
        ["MAP en corto a 5V", "manguera MAP desconectada"],
        [{"step": 1, "check": "senal salida"}, {"step": 2, "check": "manguera conectada"}],
        ["MAP"],
        ["*"],
        ["multimetro"],
        [50, 200], 1.0,
    ),
    "P0112": _dtc(
        "Sensor IAT - senal baja",
        "low",
        ["MIL", "enriquecimiento en frio erratico"],
        ["IAT en corto a GND", "agua en conector"],
        [{"step": 1, "check": "resistencia IAT"}, {"step": 2, "check": "continuidad"}],
        ["IAT"],
        ["*"],
        ["multimetro"],
        [30, 150], 0.5,
    ),
    "P0115": _dtc(
        "Sensor ECT - malfuncion",
        "medium",
        ["MIL", "ventiladores siempre ON o OFF"],
        ["ECT abierto/corto", "cableado"],
        [{"step": 1, "check": "resistencia 2-3 kohm a 20 C"}, {"step": 2, "check": "continuidad"}],
        ["sensor ECT"],
        ["*"],
        ["multimetro"],
        [40, 180], 0.8,
    ),
    "P0117": _dtc(
        "Sensor ECT - senal baja",
        "medium",
        ["MIL"],
        ["ECT en corto a GND"],
        [{"step": 1, "check": "resistencia"}, {"step": 2, "check": "5V ref"}],
        ["ECT"],
        ["*"],
        ["multimetro"],
        [40, 180], 0.8,
    ),
    "P0118": _dtc(
        "Sensor ECT - senal alta",
        "medium",
        ["MIL", "arranque dificil en frio"],
        ["ECT abierto"],
        [{"step": 1, "check": "resistencia infinita"}],
        ["ECT"],
        ["*"],
        ["multimetro"],
        [40, 180], 0.8,
    ),
    "P0122": _dtc(
        "TPS/APP 'A' - senal baja",
        "medium",
        ["limp", "ralenti bajo"],
        ["TPS open", "5V ref"],
        [{"step": 1, "check": "voltaje TPS1"}, {"step": 2, "check": "5V ref"}],
        ["TPS/APP"],
        ["*"],
        ["multimetro"],
        [80, 400], 1.0,
    ),
    "P0123": _dtc(
        "TPS/APP 'A' - senal alta",
        "medium",
        ["limp", "ralenti alto"],
        ["TPS shorted to 5V"],
        [{"step": 1, "check": "voltaje TPS"}],
        ["TPS/APP"],
        ["*"],
        ["multimetro"],
        [80, 400], 1.0,
    ),
    "P0132": _dtc(
        "Sensor O2 B1S1 - voltaje alto",
        "medium",
        ["MIL", "rich"],
        ["O2 en corto a 12V", "MAF leyendo alto", "FPR fallado"],
        [{"step": 1, "check": "senal O2 en vivo"}, {"step": 2, "check": "LTFT"}],
        ["O2 upstream"],
        ["*"],
        ["scanner"],
        [80, 300], 1.0,
    ),
    "P0133": _dtc(
        "Sensor O2 B1S1 - respuesta lenta",
        "medium",
        ["MIL", "consumo elevado"],
        ["O2 envejecido", "contaminado silicio"],
        [{"step": 1, "check": "freq conmutacion > 0.5 Hz"}],
        ["O2 upstream"],
        ["*"],
        ["scanner graph"],
        [80, 300], 1.0,
    ),
    "P0134": _dtc(
        "O2 B1S1 - sin actividad",
        "medium",
        ["MIL", "loop abierto"],
        ["O2 muerto", "escape frio", "fuga escape"],
        [{"step": 1, "check": "voltaje O2 frio 0.45V"}, {"step": 2, "check": "actividad con motor caliente"}],
        ["O2 upstream"],
        ["*"],
        ["scanner"],
        [80, 300], 1.0,
    ),
    "P0137": _dtc(
        "O2 B1S2 - voltaje bajo",
        "medium",
        ["MIL"],
        ["O2 downstream defectuoso", "fuga escape post-cat"],
        [{"step": 1, "check": "voltaje downstream"}, {"step": 2, "check": "fuga escape"}],
        ["O2 downstream"],
        ["*"],
        ["scanner"],
        [80, 250], 1.0,
    ),
    "P0138": _dtc(
        "O2 B1S2 - voltaje alto",
        "medium",
        ["MIL"],
        ["O2 shorted", "mezcla rica cronica"],
        [{"step": 1, "check": "senal O2 downstream"}],
        ["O2 downstream"],
        ["*"],
        ["scanner"],
        [80, 250], 1.0,
    ),
    "P0140": _dtc(
        "O2 B1S2 - sin actividad",
        "medium",
        ["MIL"],
        ["O2 muerto", "cableado"],
        [{"step": 1, "check": "senal"}, {"step": 2, "check": "cableado"}],
        ["O2 downstream"],
        ["*"],
        ["multimetro"],
        [80, 250], 1.0,
    ),
    "P0174": _dtc(
        "Sistema pobre - banco 2",
        "medium",
        ["MIL", "ralenti rough"],
        ["fuga vacio banco 2", "inyector obstruido", "MAF"],
        [{"step": 1, "check": "LTFT banco 2"}, {"step": 2, "check": "fuga vacio"}],
        ["inyectores banco 2", "admision"],
        ["ford", "gm", "toyota", "nissan"],
        ["smoke machine", "scanner"],
        [50, 600], 2.0,
    ),
    "P0175": _dtc(
        "Sistema rico - banco 2",
        "medium",
        ["MIL", "humo negro"],
        ["inyector con fuga", "FPR alto", "MAF leyendo alto"],
        [{"step": 1, "check": "LTFT"}, {"step": 2, "check": "FPR"}],
        ["inyectores", "FPR"],
        ["*"],
        ["scanner"],
        [80, 600], 2.0,
    ),
    "P0201": _dtc(
        "Inyector cil 1 - circuito abierto",
        "high",
        ["misfire cil 1", "MIL"],
        ["inyector quemado", "cableado abierto", "driver ECM"],
        [
            {"step": 1, "check": "resistencia inyector 12-16 ohm"},
            {"step": 2, "check": "12V en conector"},
            {"step": 3, "check": "pulso del ECM"},
        ],
        ["inyector 1"],
        ["*"],
        ["multimetro", "noid light"],
        [100, 600], 1.0,
    ),
    "P0202": _dtc("Inyector cil 2 - circuito abierto", "high", ["misfire cil 2"], ["inyector", "cableado"],
                  [{"step": 1, "check": "resistencia"}, {"step": 2, "check": "pulso"}], ["inyector 2"], ["*"],
                  ["noid light"], [100, 600], 1.0),
    "P0203": _dtc("Inyector cil 3 - circuito abierto", "high", ["misfire cil 3"], ["inyector", "cableado"],
                  [{"step": 1, "check": "resistencia"}, {"step": 2, "check": "pulso"}], ["inyector 3"], ["*"],
                  ["noid light"], [100, 600], 1.0),
    "P0204": _dtc("Inyector cil 4 - circuito abierto", "high", ["misfire cil 4"], ["inyector", "cableado"],
                  [{"step": 1, "check": "resistencia"}, {"step": 2, "check": "pulso"}], ["inyector 4"], ["*"],
                  ["noid light"], [100, 600], 1.0),
    "P0230": _dtc(
        "Circuito primario bomba combustible",
        "high",
        ["no arranque", "apagon intermitente"],
        ["relay bomba", "cableado", "driver ECM", "bomba"],
        [{"step": 1, "check": "12V en bomba al ON"}, {"step": 2, "check": "relay"}, {"step": 3, "check": "resistencia bomba"}],
        ["relay bomba", "bomba combustible"],
        ["*"],
        ["multimetro", "manometro"],
        [80, 700], 1.5,
    ),
    "P0234": _dtc(
        "Condicion sobrepresion turbo",
        "high",
        ["limp mode", "surge", "MIL"],
        ["wastegate pegada", "solenoide boost", "VGT pegada cerrada"],
        [{"step": 1, "check": "boost vs comandado"}, {"step": 2, "check": "wastegate libre"}],
        ["turbo", "wastegate", "solenoide boost"],
        ["ford", "gm", "vw", "bmw", "mazda"],
        ["scanner", "vacuum pump"],
        [150, 2500], 3.0,
    ),
    "P0302": _dtc("Misfire cil 2", "high", ["rough", "MIL blink"], ["bujia", "bobina", "inyector", "compresion"],
                  [{"step": 1, "check": "swap bujia/bobina"}], ["bujia 2", "bobina 2"], ["*"],
                  ["scanner"], [20, 500], 1.0),
    "P0303": _dtc("Misfire cil 3", "high", ["rough", "MIL blink"], ["bujia", "bobina", "inyector"],
                  [{"step": 1, "check": "swap bujia/bobina"}], ["bujia 3"], ["*"], ["scanner"], [20, 500], 1.0),
    "P0304": _dtc("Misfire cil 4", "high", ["rough"], ["bujia", "bobina"],
                  [{"step": 1, "check": "swap"}], ["bujia 4"], ["*"], ["scanner"], [20, 500], 1.0),
    "P0305": _dtc("Misfire cil 5", "high", ["rough V6/V8/L5"], ["bujia", "bobina"],
                  [{"step": 1, "check": "swap"}], ["bujia 5"], ["*"], ["scanner"], [20, 500], 1.0),
    "P0306": _dtc("Misfire cil 6", "high", ["rough V6"], ["bujia", "bobina"],
                  [{"step": 1, "check": "swap"}], ["bujia 6"], ["*"], ["scanner"], [20, 500], 1.0),
    "P0307": _dtc("Misfire cil 7", "high", ["rough V8"], ["bujia", "bobina"],
                  [{"step": 1, "check": "swap"}], ["bujia 7"], ["*"], ["scanner"], [20, 500], 1.0),
    "P0308": _dtc("Misfire cil 8", "high", ["rough V8"], ["bujia", "bobina"],
                  [{"step": 1, "check": "swap"}], ["bujia 8"], ["*"], ["scanner"], [20, 500], 1.0),
    "P0340": _dtc(
        "Circuito CMP banco 1 - malfuncion",
        "high",
        ["no arranque", "perdida potencia"],
        ["CMP muerto", "cableado"],
        [{"step": 1, "check": "senal CMP con oscilo"}, {"step": 2, "check": "alimentacion"}],
        ["sensor CMP"],
        ["*"],
        ["osciloscopio"],
        [60, 350], 1.2,
    ),
    "P0344": _dtc(
        "CMP banco 1 - senal intermitente",
        "medium",
        ["stall intermitente"],
        ["conector CMP flojo", "rueda tonal"],
        [{"step": 1, "check": "wiggle test"}, {"step": 2, "check": "rueda tonal"}],
        ["CMP", "rueda tonal"],
        ["*"],
        ["osciloscopio"],
        [60, 400], 1.5,
    ),
    "P0380": _dtc(
        "Circuito bujias calentamiento 'A' - diesel",
        "medium",
        ["arranque dificil frio", "humo blanco frio", "MIL"],
        ["bujia quemada", "relay bujias", "cableado"],
        [
            {"step": 1, "check": "resistencia bujias 0.5-2 ohm"},
            {"step": 2, "check": "relay bujias"},
            {"step": 3, "check": "12V al activar"},
        ],
        ["bujias", "relay", "modulo GCM"],
        ["vw", "ford", "mercedes", "bmw", "fiat", "peugeot"],
        ["multimetro", "scanner"],
        [80, 500], 2.0,
    ),
    "P0402": _dtc("Flujo EGR excesivo", "medium", ["ralenti rough", "MIL"],
                  ["EGR pegada abierta", "DPFE roto"],
                  [{"step": 1, "check": "DPFE reading"}, {"step": 2, "check": "EGR manual"}],
                  ["EGR", "DPFE"], ["ford", "gm", "diesel"],
                  ["scanner", "vacuum pump"], [60, 600], 1.5),
    "P0403": _dtc("Circuito control EGR", "medium", ["MIL"],
                  ["solenoide EGR abierto", "cableado"],
                  [{"step": 1, "check": "resistencia solenoide"}, {"step": 2, "check": "12V y driver"}],
                  ["solenoide EGR"], ["*"],
                  ["multimetro"], [60, 400], 1.2),
    "P0404": _dtc("EGR - rango/rendimiento", "medium", ["MIL", "perdida potencia"],
                  ["carbon en EGR", "sensor posicion"],
                  [{"step": 1, "check": "actuar EGR scanner"}, {"step": 2, "check": "limpieza"}],
                  ["EGR"], ["*"],
                  ["scanner bi-direccional"], [100, 800], 2.0),
    "P0411": _dtc("Flujo aire secundario - incorrecto", "medium", ["MIL"],
                  ["bomba AIR", "valvula check", "mangueras"],
                  [{"step": 1, "check": "actuar bomba secundaria"}],
                  ["bomba aire secundario"],
                  ["gm", "vw", "audi", "bmw"],
                  ["scanner"], [200, 1500], 2.5),
    "P0421": _dtc("Warm-up catalizador banco 1 - ineficiente",
                  "medium", ["MIL"], ["cat gastado", "misfires pasados"],
                  [{"step": 1, "check": "O2 up vs down"}, {"step": 2, "check": "fugas escape"}],
                  ["catalizador"], ["*"], ["scanner"], [300, 1500], 2.0),
    "P0430": _dtc(
        "Eficiencia catalizador banco 2 - bajo umbral",
        "medium",
        ["MIL", "posible olor sulfuro"],
        ["catalizador envejecido banco 2", "fuga escape", "misfires pasados"],
        [
            {"step": 1, "check": "comparar O2 up vs down banco 2"},
            {"step": 2, "check": "fugas escape"},
            {"step": 3, "check": "LTFT banco 2"},
        ],
        ["catalizador banco 2", "O2 downstream banco 2"],
        ["*"],
        ["scanner"],
        [400, 2000], 2.0,
    ),
    "P0440": _dtc("EVAP - malfuncion general", "low", ["MIL"],
                  ["tapa combustible", "valvulas EVAP"],
                  [{"step": 1, "check": "apretar tapa"}, {"step": 2, "check": "humo EVAP"}],
                  ["EVAP"], ["*"], ["smoke EVAP"], [10, 300], 1.0),
    "P0441": _dtc("Flujo purge EVAP - incorrecto", "low", ["MIL"],
                  ["purge valve pegada"],
                  [{"step": 1, "check": "actuar purge scanner"}],
                  ["valvula purge"], ["*"], ["scanner"], [40, 300], 1.0),
    "P0443": _dtc("Valvula purge EVAP - circuito", "low", ["MIL"],
                  ["purge abierta/corto"],
                  [{"step": 1, "check": "resistencia purge"}, {"step": 2, "check": "12V"}],
                  ["valvula purge"], ["*"], ["multimetro"], [40, 250], 1.0),
    "P0446": _dtc("Circuito vent EVAP", "low", ["MIL"],
                  ["vent valve atascada", "cableado"],
                  [{"step": 1, "check": "actuar vent"}], ["vent valve"], ["*"], ["scanner"], [40, 300], 1.0),
    "P0456": _dtc("Fuga EVAP muy pequena", "low", ["MIL"],
                  ["sello tapa", "manguera fisura"],
                  [{"step": 1, "check": "smoke EVAP a baja presion"}],
                  ["EVAP"], ["*"], ["smoke"], [10, 300], 1.5),
    "P0461": _dtc("Sensor nivel combustible - rango/rendimiento", "low", ["indicador erratico"],
                  ["flotador pegado", "sender envejecido"],
                  [{"step": 1, "check": "resistencia sender vacio/lleno"}],
                  ["sender tanque"], ["*"], ["multimetro"], [100, 500], 2.0),
    "P0501": _dtc("VSS - rango/rendimiento", "medium", ["vel erratica"],
                  ["sensor VSS", "anillo"],
                  [{"step": 1, "check": "vs GPS"}], ["VSS"], ["*"], ["scanner"], [60, 250], 1.0),
    "P0505": _dtc("IAC - malfuncion", "medium", ["ralenti erratico", "stall"],
                  ["IAC sucia", "TB sucio"],
                  [{"step": 1, "check": "limpiar TB/IAC"}, {"step": 2, "check": "reaprender"}],
                  ["IAC"], ["toyota", "honda", "ford", "nissan"], ["scanner"], [60, 300], 1.0),
    "P0506": _dtc("RPM ralenti mas bajo que esperado", "low", ["ralenti bajo"],
                  ["fuga vacio", "TB carbon", "IAC"],
                  [{"step": 1, "check": "fugas vacio"}], ["TB", "IAC"], ["*"], ["smoke"], [50, 400], 1.5),
    "P0507": _dtc("RPM ralenti mas alto que esperado", "low", ["ralenti alto"],
                  ["fuga vacio", "TPS mal calibrado"],
                  [{"step": 1, "check": "fugas"}, {"step": 2, "check": "TPS"}],
                  ["TB", "TPS"], ["*"], ["scanner"], [50, 400], 1.5),
    "P0571": _dtc("Switch freno - senal erratica", "medium", ["cruise no trabaja", "cambio ATF raro"],
                  ["BSS switch", "cableado"],
                  [{"step": 1, "check": "switch continuidad"}],
                  ["brake switch"], ["*"], ["multimetro"], [40, 150], 0.5),
    "P0601": _dtc("Memoria ECM - checksum", "high", ["MIL permanente"],
                  ["flash corrupto", "ECM danado"],
                  [{"step": 1, "check": "reflash OEM"}, {"step": 2, "check": "reemplazar si persiste"}],
                  ["ECM"], ["*"], ["J2534", "ECM Titanium"], [200, 2500], 3.0),
    "P0602": _dtc("ECM - error programacion",
                  "high", ["limp mode"], ["flash incompleto"],
                  [{"step": 1, "check": "reflash"}], ["ECM"], ["*"],
                  ["J2534"], [150, 2000], 2.0),
    "P0615": _dtc("Relay arrancador - circuito",
                  "medium", ["no arranca"], ["relay", "cableado"],
                  [{"step": 1, "check": "relay"}], ["relay arranque"], ["*"],
                  ["multimetro"], [40, 200], 1.0),
    "P0622": _dtc("Campo alternador - circuito",
                  "medium", ["bateria descargada", "MIL"],
                  ["alternador field open", "regulador"],
                  [{"step": 1, "check": "salida alternador"}],
                  ["alternador"], ["*"], ["multimetro"], [150, 700], 2.0),
    "P0638": _dtc("Throttle actuator 'A' - rango",
                  "high", ["limp mode", "MIL"],
                  ["TB DBW desgastado", "cableado"],
                  [{"step": 1, "check": "TB con scanner"}, {"step": 2, "check": "reaprender"}],
                  ["TB DBW"], ["*"], ["scanner"], [150, 900], 2.0),
    "P0641": _dtc("Sensor 5V 'A' ref - circuito",
                  "high", ["multiples DTCs"], ["ECM", "short en sensor"],
                  [{"step": 1, "check": "5V con sensores desconectados uno a uno"}],
                  ["ECM", "sensores 5V"], ["*"], ["multimetro"], [100, 1500], 2.0),
    "P0652": _dtc("Sensor 5V 'B' ref", "high", ["multi DTC"], ["short"],
                  [{"step": 1, "check": "5V B"}], ["ECM"], ["*"], ["multimetro"], [100, 1500], 2.0),
    "P0700": None,  # ya existe, placeholder
    "P0705": _dtc("Switch neutral TR - malfuncion",
                  "medium", ["no arranca en P/N", "cambios raros"],
                  ["TRS switch"], [{"step": 1, "check": "continuidad TRS"}],
                  ["TRS"], ["*"], ["multimetro"], [60, 300], 1.0),
    "P0711": _dtc("Sensor temp ATF - rango",
                  "medium", ["shift shock", "MIL"],
                  ["sensor ATF"], [{"step": 1, "check": "resistencia vs temp"}],
                  ["ATF sensor"], ["*"], ["multimetro"], [80, 600], 2.0),
    "P0715": _dtc("Sensor turbina input speed - malfuncion",
                  "high", ["limp ATF", "cambios duros"],
                  ["sensor input"], [{"step": 1, "check": "senal sensor"}],
                  ["sensor turbina"], ["*"], ["scanner"], [150, 900], 2.5),
    "P0720": _dtc("Sensor output speed - malfuncion",
                  "high", ["limp ATF", "velocimetro raro"],
                  ["sensor output"], [{"step": 1, "check": "senal"}],
                  ["sensor output ATF"], ["*"], ["scanner"], [150, 900], 2.5),
    "P0730": _dtc("Relacion marcha incorrecta",
                  "high", ["slip ATF"], ["clutch gastado", "solenoide"],
                  [{"step": 1, "check": "test presion solenoides"}],
                  ["clutches ATF"], ["*"], ["scanner", "presion line"], [500, 4000], 8.0),
    "P0741": _dtc("TCC stuck off - convertidor",
                  "medium", ["consumo elevado", "no lock"],
                  ["TCC solenoide", "flujo fluido"],
                  [{"step": 1, "check": "actuar TCC scanner"}],
                  ["TCC solenoide"], ["*"], ["scanner"], [150, 1500], 3.0),
    "P0750": _dtc("Shift solenoid A - malfuncion",
                  "high", ["cambios erraticos"],
                  ["solenoide SS A"], [{"step": 1, "check": "resistencia SS-A"}],
                  ["SS-A"], ["*"], ["multimetro"], [200, 1500], 4.0),
    "P0755": _dtc("Shift solenoid B", "high", ["cambios erraticos"],
                  ["SS-B"], [{"step": 1, "check": "resistencia SS-B"}],
                  ["SS-B"], ["*"], ["multimetro"], [200, 1500], 4.0),
    "P1000": _dtc("OBD readiness no completado (Ford)",
                  "low", ["no pasa verif"], ["drive cycle incompleto"],
                  [{"step": 1, "check": "drive cycle OBD Ford"}],
                  ["ECM readiness"], ["ford", "mazda"],
                  ["scanner"], [0, 50], 1.5),
    "P2096": _dtc("Post-catalizador pobre banco 1",
                  "medium", ["MIL"], ["fuga escape", "O2 downstream"],
                  [{"step": 1, "check": "fugas escape"}, {"step": 2, "check": "O2 down"}],
                  ["escape", "O2 down"], ["*"], ["scanner"], [80, 600], 1.5),
    "P2097": _dtc("Post-catalizador rico banco 1",
                  "medium", ["MIL"], ["inyector goteando", "O2 down"],
                  [{"step": 1, "check": "inyectores"}],
                  ["inyectores"], ["*"], ["scanner"], [100, 800], 2.0),
    "P2187": _dtc("Pobre en ralenti banco 1",
                  "medium", ["ralenti rough"], ["fuga vacio pequena"],
                  [{"step": 1, "check": "humo fugas"}],
                  ["admision"], ["bmw", "audi", "vw"],
                  ["smoke"], [40, 400], 1.5),
    "P2188": _dtc("Rico en ralenti banco 1", "medium", ["humo negro idle"],
                  ["inyector fuga"], [{"step": 1, "check": "inyectores balance"}],
                  ["inyectores"], ["*"], ["scanner"], [100, 800], 2.0),
    "P2279": _dtc("Fuga aire admision", "medium", ["rough", "LTFT alto"],
                  ["manguera", "empaque", "PCV"],
                  [{"step": 1, "check": "humo"}], ["admision"], ["*"], ["smoke"], [30, 400], 1.5),
    "P2463": _dtc("DPF acumulacion hollin - excesivo",
                  "high", ["limp", "humo"],
                  ["regen abortada", "trayectos cortos"],
                  [{"step": 1, "check": "regen forzada"}, {"step": 2, "check": "reemplazo"}],
                  ["DPF"], ["ford", "vw", "bmw", "mercedes"],
                  ["scanner bi"], [400, 3500], 4.0),
    "P2509": _dtc("ECM power input - intermitente",
                  "high", ["no arranca intermitente"], ["relay", "fusible"],
                  [{"step": 1, "check": "12V a ECM con wiggle"}],
                  ["ECM power"], ["*"], ["multimetro"], [50, 400], 1.0),

    # ----- Chassis (C codes) - ABS/ESP -----
    "C0035": _dtc("Sensor rueda delantera izq - senal",
                  "medium", ["ABS off"], ["sensor", "anillo"],
                  [{"step": 1, "check": "resistencia 1-2.5 kohm"}],
                  ["sensor ABS FL"], ["*"], ["multimetro"], [50, 250], 1.0),
    "C0041": _dtc("Sensor rueda trasera izq - senal",
                  "medium", ["ABS off"], ["sensor", "anillo"],
                  [{"step": 1, "check": "resistencia"}], ["sensor ABS RL"], ["*"],
                  ["multimetro"], [50, 250], 1.0),
    "C0045": _dtc("Sensor rueda trasera der - senal",
                  "medium", ["ABS off"], ["sensor"],
                  [{"step": 1, "check": "resistencia"}], ["sensor ABS RR"], ["*"],
                  ["multimetro"], [50, 250], 1.0),
    "C0110": _dtc("Circuito motor bomba ABS",
                  "high", ["ABS off", "freno pulsante no"],
                  ["motor bomba HCU", "relay"],
                  [{"step": 1, "check": "actuar bomba scanner"}],
                  ["HCU ABS"], ["*"], ["scanner ABS"], [300, 2000], 3.0),
    "C0121": _dtc("Valve relay ABS - circuito",
                  "high", ["ABS off"], ["relay", "HCU"],
                  [{"step": 1, "check": "relay ABS"}], ["HCU"], ["*"],
                  ["multimetro"], [200, 1500], 2.0),
    "C0265": _dtc("Relay EBCM o cableado",
                  "high", ["ABS off"], ["EBCM power", "cableado"],
                  [{"step": 1, "check": "12V EBCM"}], ["EBCM"], ["gm", "chevrolet"],
                  ["multimetro"], [100, 1500], 2.0),
    "C1201": _dtc("Sistema control motor malfuncion (desde ABS)",
                  "medium", ["ABS off"], ["bus CAN ECM-ABS"],
                  [{"step": 1, "check": "CAN comm"}], ["bus CAN"], ["toyota", "lexus"],
                  ["scanner"], [80, 1500], 2.0),

    # ----- Body (B codes) - SRS/BCM -----
    "B0001": _dtc("Sensor despliegue conductor - circuito",
                  "high", ["airbag light"], ["sensor squib", "cableado amarillo"],
                  [{"step": 1, "safety": "desconectar bateria 10 min"}, {"step": 2, "check": "scanner SRS"}],
                  ["SRS ACM", "squib"], ["*"], ["scanner SRS"], [300, 2000], 2.5,
                  safety="Bateria desconectada 10 minutos antes de cualquier trabajo en SRS."),
    "B0002": _dtc("Sensor despliegue pasajero", "high", ["airbag light"],
                  ["squib pasajero"], [{"step": 1, "safety": "battery off"}, {"step": 2, "check": "scanner"}],
                  ["SRS"], ["*"], ["scanner"], [300, 2000], 2.5,
                  safety="SRS: desconectar bateria y esperar 10 min."),
    "B0081": _dtc("Sensor lateral izquierdo - malfuncion",
                  "high", ["airbag light"], ["sensor lateral"],
                  [{"step": 1, "safety": "battery off"}, {"step": 2, "check": "scanner"}],
                  ["sensor lateral L"], ["*"], ["scanner"], [200, 1500], 2.0,
                  safety="SRS seguridad."),
    "B1318": _dtc("Voltaje bateria bajo (Ford BCM)",
                  "medium", ["warnings multiples"], ["bateria debil"],
                  [{"step": 1, "check": "voltaje"}], ["bateria"], ["ford", "lincoln", "mercury"],
                  ["multimetro"], [100, 400], 1.0),
    "B1676": _dtc("Voltaje bateria fuera de rango (GM)",
                  "medium", ["warnings"], ["bateria", "alternador"],
                  [{"step": 1, "check": "cargar bateria", "reset": "ID tool"}],
                  ["bateria"], ["gm", "chevrolet", "buick"], ["multimetro"], [100, 400], 1.0),

    # ----- Network U-codes -----
    "U0101": _dtc("Perdida comm TCM", "high", ["MIL", "limp ATF"],
                  ["CAN", "TCM sin power"],
                  [{"step": 1, "check": "CAN DLC 60 ohm"}, {"step": 2, "check": "power TCM"}],
                  ["TCM", "CAN"], ["*"], ["scanner"], [100, 2000], 2.5),
    "U0140": _dtc("Perdida comm BCM", "high", ["no arranque posible", "warnings"],
                  ["BCM", "CAN chassis"], [{"step": 1, "check": "power BCM"}, {"step": 2, "check": "CAN"}],
                  ["BCM"], ["*"], ["scanner"], [150, 2500], 3.0),
    "U0155": _dtc("Perdida comm IPC", "medium", ["cluster off"],
                  ["cluster", "CAN"], [{"step": 1, "check": "power IPC"}],
                  ["IPC"], ["*"], ["scanner"], [100, 1500], 2.0),
    "U0401": _dtc("Datos invalidos ECM", "medium", ["multi DTC"],
                  ["CAN ruidoso", "ECM flash"],
                  [{"step": 1, "check": "CAN scope"}, {"step": 2, "check": "reflash"}],
                  ["ECM", "bus CAN"], ["*"], ["oscilo"], [100, 2000], 2.5),
}

# eliminar placeholders None
NEW_DTCS = {k: v for k, v in NEW_DTCS.items() if v is not None}


# --------------------------------------------------------------------------- #
# New torques (extends cabeza_cilindros and adds new components)
# --------------------------------------------------------------------------- #

NEW_TORQUES = {
    "cabeza_cilindros": {
        "Ford 3.5 EcoBoost V6": {"spec_es": "M10 bolts: 30 Nm + 90 deg + 90 deg, nuevos siempre", "unit": "Nm"},
        "Ford 5.0 Coyote V8": {"spec_es": "45 Nm + 75 deg + 90 deg (largo) / 30 Nm + 90 deg (corto)", "unit": "Nm"},
        "Ford 6.7 Power Stroke Diesel": {"spec_es": "80 Nm + 135 deg + 75 deg (tres etapas)", "unit": "Nm"},
        "GM LT1 6.2 V8": {"spec_es": "M11: 30 Nm + 100 deg + 60 deg; M8: 30 Nm", "unit": "Nm"},
        "GM 3.6 LLT/LFX V6": {"spec_es": "25 Nm + 155 deg largos, 25 Nm + 125 deg cortos", "unit": "Nm"},
        "Chrysler Hemi 5.7/6.4": {"spec_es": "M12: 27 Nm + 90 deg + 90 deg (nuevos)", "unit": "Nm"},
        "Chrysler 3.6 Pentastar": {"spec_es": "20 Nm + 90 deg + 90 deg", "unit": "Nm"},
        "Jeep 2.0 Hurricane Turbo": {"spec_es": "per FSM - siempre pernos nuevos", "unit": "Nm"},
        "Toyota 1GR-FE 4.0 V6": {"spec_es": "25 Nm + 90 deg + 90 deg", "unit": "Nm"},
        "Toyota 2GR-FE 3.5 V6": {"spec_es": "36 Nm + 90 deg + 90 deg", "unit": "Nm"},
        "Toyota 3UR-FE 5.7 V8 (Tundra)": {"spec_es": "27 Nm + 90 deg + 90 deg", "unit": "Nm"},
        "Toyota 2TR-FE 2.7 (Hilux)": {"spec_es": "49 Nm + 90 deg", "unit": "Nm"},
        "Toyota 1KD-FTV 3.0 Diesel (Hilux)": {"spec_es": "39 Nm + 90 deg + 90 deg", "unit": "Nm"},
        "Honda K20/K24 (Civic/CRV/Accord)": {"spec_es": "40 Nm + 90 deg + 90 deg", "unit": "Nm"},
        "Honda J35 3.5 V6": {"spec_es": "39 Nm + 90 deg + 90 deg", "unit": "Nm"},
        "Nissan QR25DE (Altima 2.5)": {"spec_es": "36 Nm + 75 deg + 75 deg", "unit": "Nm"},
        "Nissan VQ35 3.5 V6": {"spec_es": "98 Nm afloja, 39 Nm + 95 deg + 95 deg", "unit": "Nm"},
        "Nissan YD25DDTi 2.5 Diesel (Frontier)": {"spec_es": "98 Nm + 90 deg + 90 deg", "unit": "Nm"},
        "Hyundai/Kia G4KE 2.4 Theta": {"spec_es": "25 Nm + 90 deg + 90 deg + 90 deg", "unit": "Nm"},
        "Hyundai/Kia G4NC 1.6 T-GDI": {"spec_es": "per FSM - nuevos", "unit": "Nm"},
        "Mazda SkyActiv 2.0/2.5": {"spec_es": "27 Nm + 90 deg + 90 deg + 90 deg", "unit": "Nm"},
        "Subaru FB25 2.5 Boxer": {"spec_es": "29 Nm afloja, luego 29 Nm + 90 deg + 90 deg", "unit": "Nm"},
        "Mitsubishi 4N15 2.4 DI-D (L200)": {"spec_es": "per FSM - 3 etapas angulares", "unit": "Nm"},
        "VW 1.4 TSI (EA211)": {"spec_es": "40 Nm + 90 deg + 90 deg", "unit": "Nm"},
        "VW 2.0 TSI (EA888 Gen3)": {"spec_es": "40 Nm + 90 deg + 90 deg + 90 deg", "unit": "Nm"},
        "Mercedes M274 2.0 Turbo": {"spec_es": "30 Nm + 90 deg + 90 deg", "unit": "Nm"},
        "BMW N20 2.0 Turbo": {"spec_es": "40 Nm + 80 deg + 80 deg", "unit": "Nm"},
        "BMW B58 3.0 Turbo": {"spec_es": "per FSM - nuevos, angulares", "unit": "Nm"},
    },
    "rueda_tuercas": {
        "Ford F-150 (2015+)": {"spec_es": "204 Nm (150 lb-ft)", "unit": "Nm"},
        "Toyota Hilux": {"spec_es": "209 Nm", "unit": "Nm"},
        "Toyota Corolla/Camry": {"spec_es": "103 Nm (76 lb-ft)", "unit": "Nm"},
        "Honda Civic/Accord": {"spec_es": "108 Nm (80 lb-ft)", "unit": "Nm"},
        "Chevrolet Silverado 1500": {"spec_es": "190 Nm (140 lb-ft)", "unit": "Nm"},
        "Nissan Altima/Sentra": {"spec_es": "113 Nm (83 lb-ft)", "unit": "Nm"},
        "Jeep Wrangler JL": {"spec_es": "176 Nm (130 lb-ft)", "unit": "Nm"},
        "Ram 1500": {"spec_es": "176 Nm", "unit": "Nm"},
        "VW Golf/Jetta": {"spec_es": "120 Nm", "unit": "Nm"},
        "BMW 3-Series (F30/G20)": {"spec_es": "120 Nm", "unit": "Nm"},
        "Mercedes C-Class": {"spec_es": "130 Nm", "unit": "Nm"},
    },
    "bujias": {
        "Ford 5.0 Coyote": {"spec_es": "17-22 Nm", "unit": "Nm"},
        "Ford 3.5 EcoBoost": {"spec_es": "13 Nm (M12)", "unit": "Nm"},
        "GM LS/LT V8": {"spec_es": "15 Nm", "unit": "Nm"},
        "Toyota 2GR-FE": {"spec_es": "17 Nm", "unit": "Nm"},
        "Honda K-series": {"spec_es": "18 Nm", "unit": "Nm"},
        "Mercedes M274": {"spec_es": "27 Nm", "unit": "Nm"},
    },
    "calipers_freno": {
        "generico_auto_mediano": {"spec_es": "90-120 Nm pernos caliper", "unit": "Nm"},
        "Ford F-150": {"spec_es": "135 Nm", "unit": "Nm"},
        "Toyota Hilux": {"spec_es": "123 Nm delantero", "unit": "Nm"},
        "Honda Civic": {"spec_es": "110 Nm", "unit": "Nm"},
    },
    "amortiguador_superior": {
        "macpherson_generico": {"spec_es": "25-45 Nm tuerca superior segun OEM", "unit": "Nm"},
    },
    "rotula_suspension": {
        "generica_auto": {"spec_es": "55-85 Nm segun OEM", "unit": "Nm"},
    },
    "pernos_ciguenal_polea": {
        "Toyota 2AZ-FE": {"spec_es": "137 Nm + 90 deg", "unit": "Nm"},
        "Ford Duratec 2.0": {"spec_es": "83 Nm + 90 deg + 90 deg", "unit": "Nm"},
        "GM Ecotec 2.4": {"spec_es": "100 Nm + 150 deg", "unit": "Nm"},
        "Honda K24": {"spec_es": "245 Nm", "unit": "Nm"},
        "VW 2.0 TSI": {"spec_es": "150 Nm + 90 deg, nuevo", "unit": "Nm"},
    },
    "volante_motor": {
        "generico_mt": {"spec_es": "85-110 Nm + angular, nuevos", "unit": "Nm"},
        "generico_flex_at": {"spec_es": "75-90 Nm", "unit": "Nm"},
    },
    "inyectores_diesel_CR": {
        "Bosch CP3 tuerca inyector": {"spec_es": "25-30 Nm tornillo sujecion", "unit": "Nm"},
        "Denso Toyota 1KD/2KD": {"spec_es": "28 Nm clamp", "unit": "Nm"},
        "Delphi DFI": {"spec_es": "seguir FSM, no reapretar", "unit": "Nm"},
    },
    "sump_aceite_tornillo_drenaje": {
        "M12_generico": {"spec_es": "25-35 Nm", "unit": "Nm"},
        "M14_generico": {"spec_es": "30-40 Nm", "unit": "Nm"},
        "M16_generico": {"spec_es": "35-50 Nm", "unit": "Nm"},
    },
}

# --------------------------------------------------------------------------- #
# New decision trees
# --------------------------------------------------------------------------- #

NEW_TREES = {
    "srs_airbag_light_on": [
        {"step": 1, "safety": "desconectar bateria y esperar 10 minutos antes de cualquier trabajo"},
        {"step": 2, "check": "scanner a modulo SRS/ACM, leer B-codes"},
        {"step": 3, "check": "conector amarillo bajo asientos y debajo volante - limpiar sin lubricante"},
        {"step": 4, "check": "resistencia squib con simulador (NO con multimetro directo)"},
        {"step": 5, "check": "alimentacion y tierras SRS"},
        {"step": 6, "check": "tras reparar, borrar DTC y esperar auto-test"},
    ],
    "abs_light_on": [
        {"step": 1, "check": "scanner a EBCM - leer C-codes"},
        {"step": 2, "check": "sensores rueda: resistencia 1-2.5 kohm pasivo"},
        {"step": 3, "check": "anillo tonal limpio y sin dientes faltantes"},
        {"step": 4, "check": "alimentacion y tierras EBCM"},
        {"step": 5, "check": "fusible ABS"},
        {"step": 6, "check": "bomba HCU actuar con scanner"},
    ],
    "tpms_light": [
        {"step": 1, "check": "presion real todas las ruedas incluida refaccion"},
        {"step": 2, "check": "scanner a modulo TPMS - ID sensores"},
        {"step": 3, "check": "sensor cambio/relearn despues rotacion"},
        {"step": 4, "check": "bateria sensor TPMS - tipica 7-10 anos"},
        {"step": 5, "check": "antena/receptor si todos leen fail"},
    ],
    "evap_leak_general": [
        {"step": 1, "check": "apretar/reemplazar tapa combustible"},
        {"step": 2, "check": "maquina de humo EVAP a 0.5 psi"},
        {"step": 3, "check": "inspeccion mangueras y canister"},
        {"step": 4, "check": "valvulas purge y vent con scanner bidireccional"},
        {"step": 5, "check": "drive cycle OBD para reset monitor"},
    ],
    "transmision_slip_at": [
        {"step": 1, "check": "nivel y condicion ATF - color y olor"},
        {"step": 2, "check": "codigos TCM"},
        {"step": 3, "check": "presion line con manometro"},
        {"step": 4, "check": "stall test vs especificacion OEM"},
        {"step": 5, "check": "si gastado, overhaul/reemplazo"},
    ],
    "glow_plug_diesel_hard_start": [
        {"step": 1, "check": "voltaje bateria >12V al cranking"},
        {"step": 2, "check": "resistencia bujias 0.5-2 ohm (cold)"},
        {"step": 3, "check": "relay bujias con scanner o actuacion"},
        {"step": 4, "check": "modulo GCM comunicacion"},
        {"step": 5, "check": "presion riel en cranking >250 bar"},
        {"step": 6, "check": "compresion cilindros"},
    ],
    "egr_dpf_regen_problem": [
        {"step": 1, "check": "porcentaje hollin DPF en scanner"},
        {"step": 2, "check": "delta presion DPF idle <20 mbar"},
        {"step": 3, "check": "EGTs pre/post DPF"},
        {"step": 4, "check": "EGR cooler limpio - no fugas"},
        {"step": 5, "check": "forzar regen estacionaria con scanner"},
        {"step": 6, "if_no_regen": "condiciones: temp motor, combustible, DPF <80%"},
    ],
    "battery_drain_parasitic": [
        {"step": 1, "check": "voltaje bateria en reposo >12.4V"},
        {"step": 2, "check": "dejar vehiculo 30 min con puertas cerradas para dormir modulos"},
        {"step": 3, "check": "amperimetro en serie negativo - esperado <50 mA"},
        {"step": 4, "check": "retirar fusibles uno a uno para identificar circuito"},
        {"step": 5, "check": "modulos comunes: BCM, radio, GPS, remote start"},
    ],
    "no_crank_click_only": [
        {"step": 1, "check": "voltaje bateria carga >12.4V"},
        {"step": 2, "check": "voltaje en B+ de arranque"},
        {"step": 3, "check": "voltaje S (signal) al dar marcha >10V"},
        {"step": 4, "check": "masas motor-chassis limpias"},
        {"step": 5, "check": "solenoide con cables gruesos probar con puente"},
        {"step": 6, "check": "consumo de arranque >200 A con amperimetro inductivo"},
    ],
    "check_engine_flashing": [
        {"step": 1, "safety": "reducir carga del motor inmediatamente - cat en riesgo"},
        {"step": 2, "check": "codigo misfire activo P030x"},
        {"step": 3, "check": "swap bujia/bobina del cilindro afectado"},
        {"step": 4, "check": "compresion del cilindro"},
        {"step": 5, "check": "inyector resistencia/balance"},
        {"step": 6, "if_not_resolvido": "NO conducir con MIL parpadeando - remolcar"},
    ],
    "ralenti_inestable": [
        {"step": 1, "check": "DTCs"},
        {"step": 2, "check": "fugas vacio con humo"},
        {"step": 3, "check": "STFT/LTFT"},
        {"step": 4, "check": "IAC o DBW - actuar con scanner"},
        {"step": 5, "check": "balance inyectores"},
        {"step": 6, "check": "compresion relativa (cranking amp)"},
    ],
    "check_hybrid_high_voltage": [
        {"step": 1, "safety": "EQUIPO PPE guantes clase 0, alfombra aislada, NO metal"},
        {"step": 2, "check": "service plug desconectado, multimetro HV"},
        {"step": 3, "check": "aislamiento 500 Mohm entre HV y chassis"},
        {"step": 4, "check": "codigos modulo HV/inverter"},
        {"step": 5, "check": "fugas refrigerante stack"},
    ],
    "cvt_problemas_comun": [
        {"step": 1, "check": "nivel CVT fluid OEM only"},
        {"step": 2, "check": "codigos TCM"},
        {"step": 3, "check": "actualizacion software (Nissan Jatco, Toyota)"},
        {"step": 4, "check": "stepper motor / solenoides"},
        {"step": 5, "check": "overhaul si belt/pulley gastado"},
    ],
    "inmovilizador_no_start": [
        {"step": 1, "check": "luz inmovilizador - parpadea = sin reconocimiento"},
        {"step": 2, "check": "bateria llave/control"},
        {"step": 3, "check": "antena al rededor chapa"},
        {"step": 4, "check": "scanner modulo immo - codigos"},
        {"step": 5, "check": "programar llave con OEM (PIN o pincode)"},
    ],
    "fallas_hibridas_bateria_hv": [
        {"step": 1, "safety": "seguir protocolo HV"},
        {"step": 2, "check": "codigos modulo bateria y ECM HV"},
        {"step": 3, "check": "celdas balanceadas con scanner OEM"},
        {"step": 4, "check": "ventiladores bateria activos"},
        {"step": 5, "check": "reemplazar modulos desbalanceados"},
    ],
    "starter_no_gira_auto_start_stop": [
        {"step": 1, "check": "bateria AGM estado carga"},
        {"step": 2, "check": "IBS sensor (Intelligent Battery Sensor) funcionando"},
        {"step": 3, "check": "modulo BCM reconoce bateria nueva (codificar)"},
        {"step": 4, "check": "temperatura motor y ECT"},
    ],
    "ac_no_enfria": [
        {"step": 1, "check": "presion AC alta y baja en estado"},
        {"step": 2, "check": "compresor embraga - voltaje y relay"},
        {"step": 3, "check": "ventiladores condensador"},
        {"step": 4, "check": "codigos HVAC"},
        {"step": 5, "check": "fuga con tinta UV o electronica"},
    ],
    "luces_testigo_multiples": [
        {"step": 1, "check": "todos los modulos con scanner - U-codes primero"},
        {"step": 2, "check": "alimentaciones bateria y alternador"},
        {"step": 3, "check": "masas motor chassis"},
        {"step": 4, "check": "CAN bus H-L 60 ohm"},
        {"step": 5, "check": "reset BCM/gateway tras corregir"},
    ],
}

# --------------------------------------------------------------------------- #
# New ECU pinouts (generic/common signals - refer AUTODATA for exact model)
# --------------------------------------------------------------------------- #

NEW_PINOUTS = {
    "Bosch_ME7_generic_88pin": {
        "notes_es": "Familia gasolina MPI de finales 90s-2000s (VW, Audi, Seat, Skoda, Fiat, Lancia).",
        "common_signals": [
            "pin 1: GND power", "pin 2: GND signal", "pin 18/37: +12V main relay",
            "pin 6/14: CAN-H/L", "pin 32: CKP+", "pin 33: CKP-",
            "pin 75: CMP", "pin 55: MAF analog", "pin 80: MAP", "pin 56: IAT",
            "pin 8/27/46/65: inyectores 1-4", "pin 3/22: bobinas"
        ],
    },
    "Bosch_MED17_generic_96pin": {
        "notes_es": "Familia GDI y TFSI VW/Audi/Seat/Skoda/Porsche 2008+. Tuning comun con WinOLS/CMD.",
        "common_signals": [
            "GND power x3, GND signal x2",
            "+12V main relay x2", "+12V ignition",
            "CAN powertrain H/L", "CAN chasis H/L",
            "CKP diff pair", "2x CMP (intake/exhaust)",
            "MAP pre/post turbo", "MAF digital",
            "HPFP solenoide HV", "inyectores piezo o solenoide HV x4/6",
            "sensores O2 wideband B1S1 heater + signal",
            "knock sensors x2", "N75 boost", "VVT solenoides x2/4",
            "throttle body DBW (feedback + motor)",
        ],
    },
    "Bosch_EDC15_generic_80pin": {
        "notes_es": "Diesel pre common rail y primeros CR (VW 1.9 TDI, Audi A4 TDI, Mercedes W210). K-Line + ISO.",
        "common_signals": [
            "GND power, +12V", "K-Line pin 16 usuario",
            "CKP ind, CMP Hall", "MAF Bosch 5WK",
            "MAP integrado en MAF", "inyectores PD (VW)",
            "solenoide N75 boost", "EGR solenoide",
            "FRP sensor", "MPROP solenoide (CR)"
        ],
    },
    "Bosch_EDC17_generic_94pin": {
        "notes_es": "Diesel CR moderno (VW/Audi/BMW/Mercedes/Ford TDCi). CAN + FlexRay en algunos BMW.",
        "common_signals": [
            "GND power x3, +12V main/relay", "CAN powertrain H/L",
            "CKP diff, CMP Hall", "MAF HFM6", "MAP pre/post",
            "FRP 5V analogico", "MPROP PWM",
            "inyectores piezo HV o solenoide", "EGR electronico",
            "VGT electrico o N75 vacio", "sensores EGT x3/4",
            "DPF diff pressure", "bujias via GCM",
        ],
    },
    "Siemens_SIM4_generic_88pin": {
        "notes_es": "Ford EEC-V/SIM Focus, Mondeo, Galaxy 2000s. Protocolo J1850.",
        "common_signals": [
            "GND power, +12V", "J1850 pin 2 DLC",
            "CKP VR/Hall", "CMP Hall", "MAF digital Ford",
            "MAP", "inyectores saturated",
            "DIS coils 4x",
        ],
    },
    "Siemens_SID202_Ford_Peugeot": {
        "notes_es": "2.0 HDI/TDCi PSA/Ford Siemens. Commun rail CP1/CP3.",
        "common_signals": [
            "GND, +12V, CAN H/L",
            "CKP VR, CMP Hall", "MAF", "MAP pre/post turbo",
            "FRP, MPROP", "inyectores piezo o solenoide",
            "EGR, N75 boost",
        ],
    },
    "Siemens_MS41_BMW_E36_E39": {
        "notes_es": "BMW M52 pre-canbus. K-Line DS2 protocol.",
        "common_signals": [
            "DME 88pin", "CKP ind", "CMP Hall",
            "MAF hot film", "DISA", "VANOS solenoide",
            "inyectores 6x", "bobinas 6x",
        ],
    },
    "Siemens_MS43_BMW_E46_88pin": {
        "notes_es": "BMW M54 2001-2006. Diagnostico DS2/BMW protocol.",
        "common_signals": [
            "CKP, CMP intake/exhaust", "MAF",
            "DISA, VANOS dual solenoides", "inyectores 6",
            "bobinas COP 6", "DME + DDE on bus",
        ],
    },
    "Siemens_MSV70_MSV80_BMW_N52_N54": {
        "notes_es": "BMW N52/N54 (2005-2010). CAN + Valvetronic.",
        "common_signals": [
            "CKP diff", "CMP intake/exhaust",
            "MAP digital", "Valvetronic motor",
            "HPFP N54", "inyectores piezo N54",
            "wastegate N54 PWM",
        ],
    },
    "Delphi_DCM3.7_generic": {
        "notes_es": "Delphi diesel CR (Renault, Dacia, Nissan). CAN.",
        "common_signals": [
            "GND, +12V", "CAN H/L", "CKP, CMP",
            "MAF, MAP", "FRP, DRV (regulator)",
            "inyectores DFI", "EGR electronica",
            "VGT electrico o N75",
        ],
    },
    "Delphi_MT05_GM_generic": {
        "notes_es": "GM gasolina 2000s (Corsa, Astra, Chevy Meriva LAm).",
        "common_signals": [
            "GND, +12V", "K-Line", "CKP VR",
            "CMP Hall", "MAP", "TPS",
            "inyectores 4x", "DIS coils",
        ],
    },
    "Denso_generic_Toyota_112pin": {
        "notes_es": "ECMs Denso Toyota/Lexus. Pin varia por modelo.",
        "common_signals": [
            "GND power, +12V BATT, +12V IG",
            "CAN H/L", "CKP NE+ NE-",
            "CMP G2+ G2-", "MAF VG", "MAP PIM",
            "inyectores 4/6/8", "bobinas COP",
            "VVT OCV", "ISC o ETCS-i (TB DBW)",
        ],
    },
    "Hitachi_SH7058_Nissan": {
        "notes_es": "Nissan/Infiniti gasolina 2000s+. CAN.",
        "common_signals": [
            "GND, +12V", "CAN H/L", "CKP, CMP",
            "MAF hot wire", "inyectores", "bobinas",
            "SCV purge", "ETC TB DBW",
        ],
    },
    "Keihin_generic_Honda": {
        "notes_es": "Honda/Acura ECMs gasolina.",
        "common_signals": [
            "GND, +12V", "K-Line OBD2",
            "CKP, CMP (TDC/CYP/CRANK en Honda)",
            "MAP, IAT", "inyectores PGM-FI",
            "bobinas, VTEC solenoide",
        ],
    },
    "Marelli_IAW_generic": {
        "notes_es": "Fiat/Alfa/Lancia/Peugeot/Citroen gasolina.",
        "common_signals": [
            "GND, +12V", "K-Line ISO-9141",
            "CKP, CMP", "MAP Bosch",
            "inyectores, bobinas",
        ],
    },
    "Mitsubishi_M32R_generic": {
        "notes_es": "Mitsubishi/Hyundai/Kia gasolina 90s-2010s.",
        "common_signals": [
            "GND, +12V", "K-Line MUT",
            "CKP, CMP", "MAF Karman/vortex",
            "inyectores, bobinas",
        ],
    },
    "Mazda_F9_Skyactiv_ECU": {
        "notes_es": "Mazda SkyActiv G/D - CAN.",
        "common_signals": [
            "GND, +12V", "CAN H/L",
            "CKP, CMP", "MAF, MAP",
            "inyectores GDI HV (gas) o piezo CR (diesel)",
            "ECV / VVT",
        ],
    },
    "Continental_SIM2K_Hyundai_Kia": {
        "notes_es": "Hyundai/Kia GDI moderno.",
        "common_signals": [
            "GND, +12V", "CAN H/L",
            "CKP, CMP x2", "MAF, MAP",
            "HPFP GDI", "inyectores HV",
            "OCV VVT (D-CVVT/CVVD)",
        ],
    },
}

# --------------------------------------------------------------------------- #
# TSBs - Technical Service Bulletins (summarized facts, no copyrighted text)
# --------------------------------------------------------------------------- #

TSBS = {
    "Ford_18S-03": {
        "title_es": "Ford Fiesta/Focus PowerShift DPS6 - actualizacion TCM y embrague seco",
        "affected": ["Ford Fiesta 2011-2019", "Ford Focus 2012-2018"],
        "symptoms": ["shudder", "limp"],
        "action": "reprogramar TCM ultima calibracion, reemplazar clutch assembly si persiste",
    },
    "GM_17-NA-032": {
        "title_es": "GM 8L90/8L45 transmision 8-speed - shuddering con TCC",
        "affected": ["Silverado 2015+", "Camaro 2016+", "Corvette 2015+"],
        "symptoms": ["judder a 70-120 km/h con lock-up"],
        "action": "flush ATF con Mobil 1 LV-FE (nuevo fluido Dexron ULV)",
    },
    "Toyota_T-SB-0075-18": {
        "title_es": "Toyota/Lexus oil consumption 2AZ-FE",
        "affected": ["Camry 2007-2011", "RAV4 2006-2008", "Scion tC 2007-2010"],
        "symptoms": ["consumo aceite excesivo"],
        "action": "pistones ringed redesign + test aceite segun protocolo",
    },
    "Honda_20-002": {
        "title_es": "Honda 1.5L Turbo - dilucion aceite con gasolina",
        "affected": ["Civic 1.5T 2016-2018", "CRV 1.5T 2017-2018"],
        "symptoms": ["aceite con olor gasolina, nivel creciente"],
        "action": "reprogramacion ECM + actualizacion AC logic; revisar inyectores",
    },
    "VW_01-17-01": {
        "title_es": "VW/Audi TDI EA189 - emissions fix post dieselgate",
        "affected": ["Golf TDI 2009-2015", "Jetta TDI 2009-2015", "Passat TDI", "Audi A3/A4/Q5 TDI"],
        "symptoms": ["emisiones no cumple", "posible MIL post-update con DPF issues"],
        "action": "actualizacion SW + hardware (urea/AdBlue en 2.0)",
    },
    "Nissan_NTB18-019": {
        "title_es": "Nissan CVT Jatco JF015/JF016 - flare, juddering",
        "affected": ["Altima 2013-2018", "Sentra 2013-2018", "Versa", "Rogue"],
        "symptoms": ["flare al acelerar", "shudder"],
        "action": "reprogramacion TCM + stepper motor + verif fluido NS-3",
    },
    "Mercedes_LI42.55-P-057881": {
        "title_es": "Mercedes OM651 lineas fuga inyector",
        "affected": ["Sprinter 2010+", "C220d", "E220d"],
        "symptoms": ["humo negro", "P0087"],
        "action": "reemplazar lineas alta presion inyector-rail (back-leak)",
    },
    "BMW_SIB_11_01_18": {
        "title_es": "BMW N47 cadena distribucion rotura prematura",
        "affected": ["320d/520d/X3/X5 N47 2007-2012"],
        "symptoms": ["ruido metalico parte trasera motor", "P0016"],
        "action": "reemplazo kit cadena con herramientas OEM - bloqueo arbol",
    },
    "Chrysler_08-047-15": {
        "title_es": "Jeep Cherokee 9-speed ZF9HP - cambios duros",
        "affected": ["Cherokee KL 2014-2017"],
        "symptoms": ["shift shock, flare"],
        "action": "reprogramar TCM + solenoide pack si persiste",
    },
}

# --------------------------------------------------------------------------- #
# VIN decode patterns (positions 1-3 = WMI make/country; 4-9 = VDS; 10 = year;
# 11 = plant; 12-17 = serial). Regex aproximados para identificacion rapida.
# --------------------------------------------------------------------------- #

VIN_PATTERNS = {
    "wmi_mapping": {
        "1FA|1FB|1FC|1FD|1FM|1FT|1ZV": "Ford USA",
        "3FA|3FE": "Ford Mexico",
        "WF0": "Ford Europe",
        "1G1|1G6": "GM Chevrolet/Cadillac USA",
        "1GC|1GT": "GM truck USA",
        "3GC|3GN": "GM Mexico",
        "JT2|JT3|JT4|JTD|JTE|JTH|JTJ|JTL|JTM|JTN": "Toyota Japan",
        "4T1|4T3|5TF|5TD|2T1": "Toyota North America",
        "1HG|2HG|19X|JHM|SHH": "Honda",
        "1N4|1N6|JN1|JN8|3N1|5N1": "Nissan",
        "WVW|WV1|WV2|3VW|9BW": "Volkswagen",
        "WAU|TRU|WUA": "Audi",
        "WBA|WBS|4US|5UX": "BMW",
        "WDB|WDC|WDD|WDF|4JG|55S": "Mercedes-Benz",
        "KMH|KNA|KND": "Hyundai/Kia",
        "JM1|JM3|JMZ": "Mazda",
        "ZFA|ZFC|ZFF": "Fiat/Alfa/Ferrari",
        "SAJ|SAL": "Jaguar/Land Rover",
        "VF1|VF2|VF3|VF6|VF7|VF8": "Peugeot/Citroen/Renault",
        "1C3|1C4|1C6|2C3|3C4": "Chrysler/Dodge/Jeep/Ram",
    },
    "year_pos10": {
        "A": "1980/2010", "B": "1981/2011", "C": "1982/2012", "D": "1983/2013",
        "E": "1984/2014", "F": "1985/2015", "G": "1986/2016", "H": "1987/2017",
        "J": "1988/2018", "K": "1989/2019", "L": "1990/2020", "M": "1991/2021",
        "N": "1992/2022", "P": "1993/2023", "R": "1994/2024", "S": "1995/2025",
        "T": "1996/2026", "V": "1997/2027", "W": "1998/2028", "X": "1999/2029",
        "Y": "2000/2030", "1": "2001/2031", "2": "2002/2032", "3": "2003/2033",
        "4": "2004/2034", "5": "2005/2035", "6": "2006/2036", "7": "2007/2037",
        "8": "2008/2038", "9": "2009/2039"
    },
    "notes_es": "Para anios 1980-2009 vs 2010-2039 el caracter se repite; usar anio del registro o pos 7 (letra=2010+, digito=2009-) para desambiguar en muchos OEMs.",
}


# --------------------------------------------------------------------------- #
# Merge & write
# --------------------------------------------------------------------------- #

def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"Missing source: {SRC}")

    with open(SRC, "r", encoding="utf-8") as fh:
        base = json.load(fh)

    # DTCs: solo agrega los que no existen
    dtcs = base.setdefault("dtc_knowledge", {})
    added_dtcs = 0
    for code, info in NEW_DTCS.items():
        if code not in dtcs:
            dtcs[code] = info
            added_dtcs += 1

    # Torques: merge por categoria y por llave vehicle
    torques = base.setdefault("torque_specs", {})
    added_torques = 0
    for cat, entries in NEW_TORQUES.items():
        bucket = torques.setdefault(cat, {})
        for k, v in entries.items():
            if k not in bucket:
                bucket[k] = v
                added_torques += 1

    # Decision trees: agrega nuevos
    trees = base.setdefault("decision_trees", {})
    added_trees = 0
    for name, steps in NEW_TREES.items():
        if name not in trees:
            trees[name] = steps
            added_trees += 1

    # ECU pinouts: agrega nuevos
    pinouts = base.setdefault("ecu_pinouts_common", {})
    added_pinouts = 0
    for k, v in NEW_PINOUTS.items():
        if k not in pinouts:
            pinouts[k] = v
            added_pinouts += 1

    # TSBs y VIN: nuevas secciones
    base.setdefault("tsbs_catalog", TSBS)
    base.setdefault("vin_patterns", VIN_PATTERNS)

    # Metadata actualizada
    meta = base.setdefault("_meta", {})
    meta["version"] = "2.0.0"
    meta["generated"] = "2026-04-14"
    meta["description"] = (
        "KnowledgeHub v2 - expansion masiva: 80+ DTCs SAE J2012 + fabricante, "
        "100+ torques, 30+ decision trees, 20+ pinouts ECU, TSBs y VIN patterns."
    )

    with open(DST, "w", encoding="utf-8") as fh:
        json.dump(base, fh, indent=2, ensure_ascii=False)

    print(json.dumps({
        "ok": True,
        "dst": str(DST),
        "added": {
            "dtcs": added_dtcs,
            "torques": added_torques,
            "trees": added_trees,
            "pinouts": added_pinouts,
            "tsbs_section": bool(TSBS),
            "vin_section": bool(VIN_PATTERNS),
        },
        "totals": {
            "dtcs": len(dtcs),
            "torques_categories": len(torques),
            "trees": len(trees),
            "pinouts": len(pinouts),
            "tsbs": len(base.get("tsbs_catalog", {})),
        },
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
