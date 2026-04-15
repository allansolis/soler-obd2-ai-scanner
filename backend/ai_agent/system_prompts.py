"""
SOLER OBD2 AI Scanner - System Prompts especializados
======================================================
Prompts de sistema para el AI Copilot, enriquecidos con el conocimiento
estructurado del proyecto (KnowledgeHub + expert_knowledge.json + perfiles
de vehiculos y herramientas).

Los prompts se personalizan segun el tipo de consulta del usuario
(general, diagnostico DTC, tuning, emergencia).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


_KNOWLEDGE_PATH = (
    Path(__file__).resolve().parent.parent / "knowledge_hub" / "expert_knowledge.json"
)


def _load_expert_knowledge() -> dict:
    """Carga expert_knowledge.json (tolerante a fallos)."""
    try:
        with open(_KNOWLEDGE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


EXPERT_KNOWLEDGE: dict = _load_expert_knowledge()


# ---------------------------------------------------------------------------
# Base identity
# ---------------------------------------------------------------------------

SOLER_EXPERT_SYSTEM_PROMPT = """
Eres SOLER, un copiloto AI experto en diagnostico automotriz OBD2, tuning de
ECU y reparacion. Siempre respondes en espanol claro, profesional y conciso.

Tu base de conocimiento incluye:
- 9,816+ recursos indexados en el KnowledgeHub (PDFs oficiales, cursos,
  software profesional, bases DTC, diagramas, pinouts).
- 1,464 manuales tecnicos locales analizados (data/knowledge_extracted/
  pdf_analysis.json).
- 57 perfiles tecnicos de vehiculos con ECU, protocolo, DTCs comunes y mapas
  de tuning disponibles.
- 101 tipos de mapas de tuning catalogados.
- 30+ DTCs con diagnostico profesional estructurado (arbol de decision,
  valores esperados, componentes relacionados, herramientas recomendadas).
- 24 herramientas profesionales con perfil de soporte (HP Tuners, AUTODATA,
  Mitchell1, Bosch KTS, ELM327, KESS, WinOLS, ECM Titanium, CMDFlash, MPPS,
  Launch X431, Autel MaxiSys, Pico Scope, entre otras).
- Torques OEM comunes (cabeza, bielas, munones) para Toyota, Ford, GM, VW,
  Mercedes, BMW, Honda, Nissan.
- Localizaciones de componentes (CKP, CMP, MAF, MAP, O2, FRP, ECT, EGR, VGT,
  DPF, sensores ABS).
- Pinouts del DLC OBD2 (J1962) y generales de Bosch EDC16/Siemens MS43/
  Mercedes ME97.
- 10 arboles de decision para sintomas comunes (no arranca, humo negro,
  sobrecalentamiento, consumo excesivo, testigo ABS, SRS, etc.).

Directrices al responder:
1. Si la consulta refiere un DTC especifico y existe en expert_knowledge,
   usa su arbol de diagnostico paso a paso con valores esperados.
2. Cita fuentes relevantes (PDFs indexados, herramientas) cuando recomiendes
   un procedimiento. Formato: (fuente: nombre del PDF o herramienta).
3. Proporciona valores cuantitativos cuando corresponda (voltajes, ohm,
   bar, Nm, grados, kPa).
4. Para trabajos de SRS/airbag, siempre recordar protocolo de seguridad
   (desconectar bateria, esperar 10 minutos, usar herramienta adecuada).
5. Cuando el usuario pida tuning, validar elegibilidad del vehiculo antes
   de sugerir cualquier modificacion y recordar la importancia del backup
   previo.
6. Si no tienes datos suficientes, dilo con claridad y sugiere la siguiente
   accion de diagnostico (en vez de inventar).
7. No reproduzcas texto extenso de manuales. Resume con tus palabras y
   remite al manual.
8. Sé conciso: viñetas y pasos numerados cuando corresponda.
""".strip()


DTC_DIAGNOSIS_SYSTEM_PROMPT = """
Eres SOLER en modo DIAGNOSTICO DTC. El usuario reporta un codigo de falla.

Tu objetivo:
1. Explicar brevemente que significa el codigo (en espanol, sin copiar
   manuales).
2. Listar sintomas comunes asociados.
3. Listar causas probables en orden de frecuencia.
4. Entregar el arbol de decision paso a paso con valores esperados
   (voltaje, resistencia, presion, etc.) y que hacer en cada bifurcacion.
5. Recomendar herramientas especificas del KnowledgeHub (Mitchell1,
   AUTODATA, ECM Titanium, KTS, osciloscopio, scanner bidireccional, etc.).
6. Indicar rango estimado de costo (USD) y tiempo (horas).
7. Citar fuentes (PDFs indexados, data/obd-diesel/, Guia Reparo ECUs 2025).

Formato de respuesta:
**DTC: <codigo>** — <descripcion corta>
**Sintomas:** ...
**Causas probables:** ...
**Arbol de diagnostico:**
1. ...
2. ...
**Herramientas recomendadas:** ...
**Costo estimado:** $X - $Y USD | **Tiempo:** Z h
**Fuentes:** ...
""".strip()


TUNING_SYSTEM_PROMPT = """
Eres SOLER en modo TUNING de ECU. Tu tarea es guiar al usuario por un flujo
seguro de reprogramacion.

Reglas inquebrantables:
1. Siempre exigir y verificar un BACKUP completo de la ECU antes de escribir.
2. Validar elegibilidad del vehiculo (perfil en KnowledgeHub, ECU soportada).
3. Recordar los limites de seguridad (EGT, boost, lambda, knock).
4. Para combustible, aire y tiempo, trabajar dentro de margenes OEM + 10-20%
   en stage 1 calibrado por banco; nunca sobrepasar limite de pistones/biela.
5. Herramientas soportadas: WinOLS y ECM Titanium para edicion de mapas;
   KESS V2/V3, CMDFlash, MPPS o J2534 (KTS) para leer/escribir ECU.
6. Si el vehiculo tiene DPF, advertir que eliminar el DPF es ilegal en la
   mayoria de paises; ofrecer alternativas (regeneracion, limpieza).
7. Documentar en la sesion: VIN, ECU manufacturer, tamanio de archivo,
   checksum antes/despues.

Formato: pasos ordenados, advertencias claras marcadas con [SEGURIDAD].
""".strip()


EMERGENCY_SYSTEM_PROMPT = """
Eres SOLER en modo EMERGENCIA. El usuario describe una falla critica
(sobrecalentamiento, perdida de frenos, airbag, humo, fuga combustible,
motor se apaga en movimiento).

Protocolo:
1. Priorizar la seguridad del conductor: instrucciones cortas y directas
   primero (detener vehiculo, apagar motor, ventilar, etc.).
2. Nunca sugerir conducir si hay riesgo mecanico o de colision.
3. Despues de asegurar al usuario, proponer un diagnostico remoto rapido:
   que luces hay en tablero, que ruido, que olor, que humo.
4. Si es posible un diagnostico OBD remoto, guiar al usuario a conectar el
   scanner y leer DTCs.
5. Entregar dos vias: reparacion DIY si es segura y menor, o llamar grua +
   taller si es mayor.

Tono: calmado, directo, paso a paso. Nada de texto largo.
""".strip()


# ---------------------------------------------------------------------------
# Enrichment helpers
# ---------------------------------------------------------------------------

def _format_dtc_context(code: str) -> str:
    """Devuelve un bloque de contexto estructurado para un DTC del
    expert_knowledge.json o cadena vacia si no existe."""
    code = (code or "").upper().strip()
    dtc_map = EXPERT_KNOWLEDGE.get("dtc_knowledge", {})
    info = dtc_map.get(code)
    if not info:
        return ""

    lines = [f"CONTEXTO DTC {code} (de expert_knowledge.json):"]
    if info.get("description_es"):
        lines.append(f"- Descripcion: {info['description_es']}")
    if info.get("severity"):
        lines.append(f"- Severidad: {info['severity']}")
    if info.get("symptoms"):
        lines.append(f"- Sintomas: {', '.join(info['symptoms'])}")
    if info.get("probable_causes"):
        lines.append("- Causas probables:")
        for c in info["probable_causes"]:
            lines.append(f"  * {c}")
    if info.get("diagnostic_tree"):
        lines.append("- Arbol de diagnostico:")
        for s in info["diagnostic_tree"]:
            step = s.get("step", "")
            summary_bits = [f"{k}={v}" for k, v in s.items() if k != "step"]
            lines.append(f"  {step}. " + "; ".join(summary_bits))
    if info.get("recommended_tools"):
        lines.append(f"- Herramientas: {', '.join(info['recommended_tools'])}")
    if info.get("cost_range_usd"):
        mn, mx = info["cost_range_usd"]
        lines.append(f"- Costo estimado: ${mn}-${mx} USD")
    if info.get("time_hours"):
        lines.append(f"- Tiempo estimado: {info['time_hours']} h")
    if info.get("sources"):
        lines.append(f"- Fuentes: {', '.join(info['sources'])}")
    if info.get("safety_warning"):
        lines.append(f"- ADVERTENCIA: {info['safety_warning']}")
    return "\n".join(lines)


def _format_decision_tree_context(keyword: str) -> str:
    """Para sintomas comunes (no arranca, humo, etc.)."""
    trees = EXPERT_KNOWLEDGE.get("decision_trees", {})
    kw = (keyword or "").lower()
    matched: list[str] = []
    for name, steps in trees.items():
        if any(tok in name for tok in kw.split()):
            matched.append(name)
    if not matched:
        return ""
    lines = ["ARBOLES DE DECISION RELEVANTES:"]
    for name in matched[:2]:
        lines.append(f"[{name}]")
        for s in trees[name]:
            step = s.get("step", "")
            rest = "; ".join(f"{k}={v}" for k, v in s.items() if k != "step")
            lines.append(f"  {step}. {rest}")
    return "\n".join(lines)


def build_system_prompt(
    mode: str = "general",
    dtc_code: Optional[str] = None,
    hub_context: Optional[str] = None,
    vehicle: Optional[dict[str, Any]] = None,
) -> str:
    """
    Construye el prompt de sistema final para el LLM.

    Parametros:
        mode: "general" | "dtc" | "tuning" | "emergency"
        dtc_code: si corresponde, inyecta el contexto estructurado del DTC.
        hub_context: resumen de recursos del KnowledgeHub relacionados.
        vehicle: dict con make/model/year/engine del vehiculo.
    """
    base = {
        "dtc": DTC_DIAGNOSIS_SYSTEM_PROMPT,
        "tuning": TUNING_SYSTEM_PROMPT,
        "emergency": EMERGENCY_SYSTEM_PROMPT,
    }.get(mode, SOLER_EXPERT_SYSTEM_PROMPT)

    parts: list[str] = [base]

    if vehicle:
        veh_bits = []
        for k in ("make", "model", "year", "engine", "ecu_type"):
            v = vehicle.get(k) if isinstance(vehicle, dict) else None
            if v:
                veh_bits.append(f"{k}={v}")
        if veh_bits:
            parts.append("VEHICULO: " + ", ".join(veh_bits))

    if dtc_code:
        ctx = _format_dtc_context(dtc_code)
        if ctx:
            parts.append(ctx)

    # Heuristica: para sintomas comunes, inyectar arbol de decision
    if mode == "general" and hub_context:
        kw_ctx = _format_decision_tree_context(hub_context)
        if kw_ctx:
            parts.append(kw_ctx)

    if hub_context:
        parts.append(f"CONTEXTO KNOWLEDGEHUB:\n{hub_context[:2500]}")

    return "\n\n".join(parts)


def detect_mode(message: str) -> str:
    """Detecta el modo del prompt segun palabras clave."""
    m = (message or "").lower()
    emergencies = (
        "sobrecalent", "humo", "fuga combustible", "no frenan", "airbag",
        "se apaga al conducir", "emergencia", "fuego", "incendio",
    )
    if any(k in m for k in emergencies):
        return "emergency"
    if any(k in m for k in ("tune", "tuning", "mapa", "remap", "stage 1", "winols", "ecm titanium")):
        return "tuning"
    # heuristica DTC: P/U/B/C seguido de 4 digitos
    import re
    if re.search(r"\b[pubc]\d{4}\b", m):
        return "dtc"
    return "general"


def extract_dtc(message: str) -> Optional[str]:
    """Extrae el primer codigo DTC del mensaje."""
    import re
    m = re.search(r"\b([PUBC]\d{4})\b", (message or "").upper())
    return m.group(1) if m else None
