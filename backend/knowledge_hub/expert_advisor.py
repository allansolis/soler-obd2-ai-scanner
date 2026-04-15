"""
SOLER OBD2 AI Scanner - Expert Advisor
=======================================
Sistema asesor experto que conoce a fondo cada herramienta automotriz
del inventario (HP Tuners, BMW ISTA, Hyundai/Kia GDS, ECM Titanium,
KESS, KTAG, WinOLS, Autodata, Mitchell, etc.) y recomienda la mejor
herramienta + workflow para cada escenario (DTC, tuning, programacion).

Fuente: backend/knowledge_hub/expert_profiles.json
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Optional

try:  # opcional: si aun no se genero pdf_analysis.json, degradacion silenciosa
    from .knowledge_graph import get_graph, KnowledgeGraph  # type: ignore
except Exception:  # pragma: no cover
    try:
        from knowledge_graph import get_graph, KnowledgeGraph  # type: ignore
    except Exception:
        get_graph = None  # type: ignore
        KnowledgeGraph = None  # type: ignore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses publicas
# ---------------------------------------------------------------------------

@dataclass
class ToolRecommendation:
    """Recomendacion de una herramienta para un caso especifico."""
    tool_id: str
    name: str
    category: str
    score: float                # 0..100
    reason_es: str              # razon en espanol
    confidence: str             # "alta" | "media" | "baja"
    workflow_summary: str
    license: str
    learning_curve: str
    alternatives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WorkflowStep:
    step: int
    title: str
    detail: str


@dataclass
class Workflow:
    tool_id: str
    tool_name: str
    task: str
    estimated_time_min: int
    difficulty: str             # "facil" | "intermedio" | "avanzado" | "experto"
    steps: list[WorkflowStep]
    required_hardware: list[str]
    safety_notes: list[str]

    def to_dict(self) -> dict:
        return {
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "task": self.task,
            "estimated_time_min": self.estimated_time_min,
            "difficulty": self.difficulty,
            "steps": [asdict(s) for s in self.steps],
            "required_hardware": self.required_hardware,
            "safety_notes": self.safety_notes,
        }


@dataclass
class ComparisonRow:
    feature: str
    values: dict[str, str]      # tool_id -> value


@dataclass
class ComparisonMatrix:
    tool_ids: list[str]
    tool_names: dict[str, str]
    rows: list[ComparisonRow]

    def to_dict(self) -> dict:
        return {
            "tool_ids": self.tool_ids,
            "tool_names": self.tool_names,
            "rows": [{"feature": r.feature, "values": r.values} for r in self.rows],
        }


# ---------------------------------------------------------------------------
# ExpertAdvisor
# ---------------------------------------------------------------------------

class ExpertAdvisor:
    """
    Asesor experto que usa expert_profiles.json para razonar sobre que
    herramienta usar en cada escenario y como usarla.
    """

    DEFAULT_PROFILES = (
        Path(__file__).resolve().parent / "expert_profiles.json"
    )

    def __init__(self, profiles_path: Optional[Path] = None):
        self.profiles_path = profiles_path or self.DEFAULT_PROFILES
        self._data: dict[str, Any] = {}
        self._tools: dict[str, dict[str, Any]] = {}
        self._graph = None  # cargado on-demand si hay pdf_analysis.json
        self.reload()

    # ----- Grafo de conocimiento (lazy) -----

    def _get_graph(self):
        if self._graph is not None:
            return self._graph
        if get_graph is None:
            return None
        try:
            self._graph = get_graph()
        except Exception as e:
            logger.warning("no se pudo cargar KnowledgeGraph: %s", e)
            self._graph = None
        return self._graph

    # ----- IO -----

    def reload(self) -> None:
        if not self.profiles_path.is_file():
            logger.warning("expert_profiles.json no encontrado en %s", self.profiles_path)
            self._data = {"tools": {}, "categories": {}}
            self._tools = {}
            return
        with self.profiles_path.open("r", encoding="utf-8") as fp:
            self._data = json.load(fp)
        self._tools = self._data.get("tools", {})
        logger.info("ExpertAdvisor: cargados %d perfiles", len(self._tools))

    # ----- API publica -----

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "id": tid,
                "name": t.get("name", tid),
                "category": t.get("category", "unknown"),
                "publisher": t.get("publisher", ""),
                "license": t.get("license", ""),
                "learning_curve": t.get("learning_curve", ""),
            }
            for tid, t in self._tools.items()
        ]

    def get_tool(self, tool_id: str) -> Optional[dict[str, Any]]:
        return self._tools.get(tool_id)

    # ----- Recomendaciones -----

    def recommend_tools_for_dtc(
        self,
        dtc: str,
        make: Optional[str] = None,
        year: Optional[int] = None,
    ) -> list[ToolRecommendation]:
        """Recomienda herramientas para diagnosticar un DTC."""
        dtc_up = (dtc or "").strip().upper()
        make_up = (make or "").strip().lower()
        recs: list[ToolRecommendation] = []

        # --- 1. Scanner OEM segun marca ---
        oem_map = {
            "hyundai": "hyundai_kia_gds",
            "kia": "hyundai_kia_gds",
            "genesis": "hyundai_kia_gds",
            "bmw": "bmw_ista",
            "mini": "bmw_ista",
            "rolls": "bmw_ista",
            "toyota": "toyota_gsic",
            "lexus": "toyota_gsic",
            "vw": "etka_elsawin",
            "volkswagen": "etka_elsawin",
            "audi": "etka_elsawin",
            "skoda": "etka_elsawin",
            "seat": "etka_elsawin",
            "renault": "renault_dialogys",
            "dacia": "renault_dialogys",
            "scania": "scania_sdp3",
            "alfa": "alfa_test",
            "fiat": "alfa_test",
            "lancia": "alfa_test",
        }
        if make_up:
            for key, tid in oem_map.items():
                if key in make_up and tid in self._tools:
                    t = self._tools[tid]
                    recs.append(self._mk_rec(
                        tid, t,
                        score=95,
                        reason=f"Scanner/SW OEM oficial para {make}: acceso completo a DTCs especificos del fabricante (incluyendo P1xxx, B1xxx, U1xxx) y procedimientos guiados.",
                        confidence="alta",
                        workflow=f"Conectar interfaz OEM ({(t.get('hardware_required') or ['N/A'])[0]}) -> Auto-scan -> ver DTC {dtc_up} con descripcion oficial -> ejecutar test plan.",
                    ))

        # --- 2. Multimarca general ---
        if "delphi_ds150e" in self._tools:
            t = self._tools["delphi_ds150e"]
            recs.append(self._mk_rec(
                "delphi_ds150e", t, 75,
                reason="Scanner multimarca util como segunda opinion o si no hay OEM disponible. Cobertura europea/asiatica amplia.",
                confidence="media",
                workflow="Conectar DS150E via Bluetooth -> seleccionar marca/modelo -> auto-scan -> revisar DTC.",
            ))
        if "launch_x431" in self._tools:
            t = self._tools["launch_x431"]
            recs.append(self._mk_rec(
                "launch_x431", t, 78,
                reason="Tablet handheld profesional con cobertura mundial; ideal para diagnostico rapido en taller multimarca.",
                confidence="media",
                workflow="Auto-VIN -> Auto-scan todos los modulos -> tap en el DTC para datos en vivo + freeze frame.",
            ))

        # --- 3. Database de servicio para causa raiz ---
        if "mitchell_prodemand" in self._tools:
            t = self._tools["mitchell_prodemand"]
            recs.append(self._mk_rec(
                "mitchell_prodemand", t, 90,
                reason=f"Mitchell Real Fix muestra los fixes mas exitosos para {dtc_up} en este vehiculo segun reportes reales de talleres - acelera el diagnostico 5-10x.",
                confidence="alta",
                workflow=f"Login Mitchell -> ingresar VIN -> buscar DTC '{dtc_up}' -> revisar Real Fix top 3 -> validar con wiring diagram.",
            ))
        if "autodata_3_45" in self._tools:
            t = self._tools["autodata_3_45"]
            recs.append(self._mk_rec(
                "autodata_3_45", t, 80,
                reason="Autodata da causa probable priorizada y pasos de inspeccion para casi cualquier DTC multimarca.",
                confidence="alta",
                workflow="Seleccionar marca/modelo/motor -> DTCs -> buscar codigo -> seguir lista de causas y pruebas.",
            ))

        # --- 4. Pinout para DTC de circuito ---
        if dtc_up.endswith(("CIRCUIT", "OPEN", "SHORT")) or any(
            x in dtc_up for x in ["P02", "P00", "P05", "P06", "P07", "P08"]
        ):
            if "ecm_pinout_8" in self._tools:
                t = self._tools["ecm_pinout_8"]
                recs.append(self._mk_rec(
                    "ecm_pinout_8", t, 85,
                    reason=f"DTC '{dtc_up}' aparenta ser de circuito; ECM PINOUT permite identificar el pin exacto de la senal afectada para medir con multimetro/oscilloscopio.",
                    confidence="alta",
                    workflow="Identificar PCM/ECM del vehiculo -> buscar pinout -> ubicar pin del sensor afectado -> medir tension/resistencia.",
                ))

        return sorted(recs, key=lambda r: r.score, reverse=True)

    def recommend_tools_for_tuning(
        self,
        make: str,
        model: Optional[str] = None,
        year: Optional[int] = None,
        goal: str = "stage1",
    ) -> list[ToolRecommendation]:
        """Recomienda herramientas para un proyecto de tuning."""
        make_up = (make or "").strip().lower()
        recs: list[ToolRecommendation] = []

        gm_makes = ("chevrolet", "gm", "cadillac", "gmc", "buick", "holden", "pontiac")
        ford_makes = ("ford", "lincoln", "mercury", "mustang")
        chrysler_makes = ("dodge", "chrysler", "jeep", "ram", "srt")
        vag_makes = ("vw", "volkswagen", "audi", "skoda", "seat", "porsche")
        bmw_makes = ("bmw", "mini")

        # --- HP Tuners para US domestic ---
        if any(k in make_up for k in gm_makes + ford_makes + chrysler_makes):
            if "hp_tuners" in self._tools:
                t = self._tools["hp_tuners"]
                recs.append(self._mk_rec(
                    "hp_tuners", t, 96,
                    reason=f"HP Tuners es el estandar de la industria para tuning de {make}: soporte profundo de tablas, ecosistema cloud, soporte oficial extenso.",
                    confidence="alta",
                    workflow="MPVI3 al OBD -> Read calibracion -> editar tablas en VCM Editor -> Write -> validar con VCM Scanner datalog.",
                ))

        # --- ECM Titanium / WinOLS / KESS para europeos y resto ---
        if any(k in make_up for k in vag_makes + bmw_makes) or "diesel" in goal.lower():
            for tid, score, reason in [
                ("ecm_titanium", 92, "ECM Titanium tiene drivers para casi cualquier ECU Bosch MED/EDC, ideal para mapas claramente identificados."),
                ("winols", 95, "WinOLS es el editor profesional con Damos para mapas exactamente nombrados como en Bosch original."),
                ("kess_v2_v3", 90, "KESS V3 lee/escribe la ECU via OBD sin desmontar; combo ideal con ECM Titanium o WinOLS."),
            ]:
                if tid in self._tools:
                    t = self._tools[tid]
                    recs.append(self._mk_rec(
                        tid, t, score,
                        reason=reason,
                        confidence="alta",
                        workflow="KESS V3 read BIN -> abrir en WinOLS/ECM Titanium -> editar mapas -> recalcular checksum -> KESS V3 write.",
                    ))

        # --- KTAG si el goal sugiere ECU moderna protegida ---
        if any(k in goal.lower() for k in ["bench", "boot", "tprot", "med17.5", "edc17", "med17"]):
            if "ktag" in self._tools:
                t = self._tools["ktag"]
                recs.append(self._mk_rec(
                    "ktag", t, 88,
                    reason="ECU moderna con TPROT requiere bench/boot mode; KTAG accede via JTAG/BDM/Boot.",
                    confidence="alta",
                    workflow="Desmontar ECU -> conectar adaptador KTAG correcto -> bench power -> read flash + EEPROM -> editar -> write.",
                ))

        return sorted(recs, key=lambda r: r.score, reverse=True)

    def recommend_tools_for_programming(
        self,
        make: str,
        model: Optional[str] = None,
        year: Optional[int] = None,
        task: str = "key_programming",
    ) -> list[ToolRecommendation]:
        """Recomienda herramientas para programacion (llaves, modulos, inmo)."""
        make_up = (make or "").strip().lower()
        task_l = (task or "").lower()
        recs: list[ToolRecommendation] = []

        # OEM por marca
        oem_map = {
            "hyundai": "hyundai_kia_gds", "kia": "hyundai_kia_gds",
            "bmw": "bmw_ista", "mini": "bmw_ista",
            "vw": "etka_elsawin", "audi": "etka_elsawin",
        }
        for key, tid in oem_map.items():
            if key in make_up and tid in self._tools:
                t = self._tools[tid]
                recs.append(self._mk_rec(
                    tid, t, 95,
                    reason=f"Para programacion oficial de {make}, el SW OEM es lo mas seguro (no riesgo de brick).",
                    confidence="alta",
                    workflow="Conectar VCI OEM -> autenticar -> seleccionar funcion (key learn / module replacement) -> seguir wizard.",
                ))

        # J2534 generico
        if "j2534_passthru" in self._tools:
            t = self._tools["j2534_passthru"]
            recs.append(self._mk_rec(
                "j2534_passthru", t, 80,
                reason="J2534 + software OEM oficial permite reflash/programacion sin scanner OEM completo.",
                confidence="media",
                workflow="Comprar suscripcion SW OEM -> instalar -> conectar J2534 device -> ejecutar programacion oficial.",
            ))

        # Inmovilizador especifico
        if any(k in task_l for k in ["immo", "key", "llave", "pin"]):
            if "immo_code_calc" in self._tools:
                t = self._tools["immo_code_calc"]
                recs.append(self._mk_rec(
                    "immo_code_calc", t, 75,
                    reason="Para programar llaves cuando se pierden todas, IMMO Code Calc obtiene el PIN desde el dump EEPROM del BCM/BSI.",
                    confidence="media",
                    workflow="Dumpear EEPROM con TL866/XPROG -> calcular PIN con IMMO Code Calc -> usar PIN en scanner para programar llaves.",
                ))

        return sorted(recs, key=lambda r: r.score, reverse=True)

    # ----- Workflow detallado -----

    def get_workflow(self, tool_id: str, task: str) -> Optional[Workflow]:
        """Retorna workflow paso a paso para una herramienta + tarea."""
        tool = self._tools.get(tool_id)
        if not tool:
            return None

        task_l = task.lower()
        steps: list[WorkflowStep] = []
        difficulty = tool.get("learning_curve", "intermedio")
        time_min = 30
        safety = ["Bateria estable >12.5V durante todo el proceso.",
                  "No interrumpir comunicacion durante read/write."]

        # Workflow generico desde 'typical_workflow'
        tw = tool.get("typical_workflow", "")
        if tw:
            for i, line in enumerate(tw.split("\n"), 1):
                line = line.strip()
                if not line:
                    continue
                # quitar prefijo numerico tipo "1. "
                clean = line.split(". ", 1)[-1] if line[:2].rstrip().isdigit() else line
                steps.append(WorkflowStep(step=i, title=f"Paso {i}", detail=clean))

        # Ajustes especificos por task
        if "tuning" in task_l or "stage" in task_l:
            time_min = 90
            safety.append("Hacer SIEMPRE backup del archivo stock antes de escribir.")
            safety.append("Validar la calibracion con datalog antes de entregar al cliente.")
        elif "dtc" in task_l or "diagnost" in task_l:
            time_min = 15
        elif "key" in task_l or "llave" in task_l:
            time_min = 45
            safety.append("Tener todas las llaves originales presentes si el procedimiento las requiere.")

        return Workflow(
            tool_id=tool_id,
            tool_name=tool.get("name", tool_id),
            task=task,
            estimated_time_min=time_min,
            difficulty=difficulty,
            steps=steps or [WorkflowStep(1, "Workflow generico", "Consultar documentacion oficial.")],
            required_hardware=tool.get("hardware_required", []),
            safety_notes=safety,
        )

    # ----- Comparacion -----

    def compare_tools(self, tool_ids: list[str]) -> ComparisonMatrix:
        """Compara N herramientas en una matriz."""
        tool_ids = [t for t in tool_ids if t in self._tools]
        names = {tid: self._tools[tid].get("name", tid) for tid in tool_ids}

        features = [
            ("Categoria", "category"),
            ("Editor/Publisher", "publisher"),
            ("Licencia", "license"),
            ("Curva aprendizaje", "learning_curve"),
            ("Precio (USD)", "price_range_usd"),
        ]
        rows: list[ComparisonRow] = []
        for label, key in features:
            row = ComparisonRow(feature=label, values={
                tid: str(self._tools[tid].get(key, "-")) for tid in tool_ids
            })
            rows.append(row)

        # Marcas soportadas (resumen)
        rows.append(ComparisonRow(feature="Marcas soportadas", values={
            tid: ", ".join((self._tools[tid].get("supports", {}) or {}).get("brands", [])[:6]) or "-"
            for tid in tool_ids
        }))
        # Hardware requerido
        rows.append(ComparisonRow(feature="Hardware requerido", values={
            tid: ", ".join(self._tools[tid].get("hardware_required", [])) or "-"
            for tid in tool_ids
        }))
        # Funciones principales
        rows.append(ComparisonRow(feature="Funciones", values={
            tid: ", ".join(((self._tools[tid].get("supports", {}) or {}).get("functions", []))[:5]) or "-"
            for tid in tool_ids
        }))
        # Strengths (resumido)
        rows.append(ComparisonRow(feature="Fortalezas", values={
            tid: " | ".join((self._tools[tid].get("strengths", []))[:3]) or "-"
            for tid in tool_ids
        }))
        # Limitations
        rows.append(ComparisonRow(feature="Limitaciones", values={
            tid: " | ".join((self._tools[tid].get("limitations", []))[:3]) or "-"
            for tid in tool_ids
        }))

        return ComparisonMatrix(tool_ids=tool_ids, tool_names=names, rows=rows)

    # ----- Evidencia real desde PDFs (knowledge graph) -----

    def get_evidence(self, tool_id: str, dtc: Optional[str] = None,
                     limit: int = 8) -> dict[str, Any]:
        """
        Retorna pruebas reales de un tool (+ opcional DTC) extraidas de los
        manuales locales analizados. Si no hay grafo disponible, retorna un
        payload vacio con `available=False`.
        """
        g = self._get_graph()
        if g is None:
            return {"available": False, "tool_id": tool_id, "pdfs": [],
                    "dtc_pdfs": [], "message": "pdf_analysis.json aun no generado"}
        tool_ev = [e.to_dict() for e in g.evidence_for_tool(tool_id, limit=limit)]
        dtc_ev = [e.to_dict() for e in g.evidence_for_dtc(dtc, limit=limit)] if dtc else []
        return {
            "available": True,
            "tool_id": tool_id,
            "dtc": (dtc or "").upper() or None,
            "pdfs": tool_ev,
            "dtc_pdfs": dtc_ev,
        }

    def context_for_vehicle(self, make: str, model: str = "",
                            year: Optional[int] = None,
                            dtc: Optional[str] = None) -> dict[str, Any]:
        """Contexto completo (PDFs + tools + procedimientos) para un vehiculo."""
        g = self._get_graph()
        if g is None:
            return {"available": False, "make": make, "pdfs": [], "tools": []}
        ctx = g.get_complete_context(make=make, model=model, year=year, dtc=dtc)
        return {"available": True, **ctx.to_dict()}

    def recommend_tools_for_dtc_with_evidence(
        self,
        dtc: str,
        make: Optional[str] = None,
        year: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """
        Igual que recommend_tools_for_dtc pero adjunta para cada recomendacion
        los PDFs reales que citan el tool y/o el DTC.
        """
        base = self.recommend_tools_for_dtc(dtc, make=make, year=year)
        g = self._get_graph()
        out: list[dict[str, Any]] = []
        for r in base:
            item = r.to_dict()
            if g is not None:
                tool_ev = [e.to_dict() for e in g.evidence_for_tool(r.tool_id, limit=4)]
                dtc_ev = [e.to_dict() for e in g.evidence_for_dtc(dtc, limit=4)]
                item["evidence"] = {"tool_pdfs": tool_ev, "dtc_pdfs": dtc_ev}
            else:
                item["evidence"] = {"tool_pdfs": [], "dtc_pdfs": []}
            out.append(item)
        return out

    # ----- Helpers internos -----

    def _mk_rec(
        self,
        tool_id: str,
        tool: dict[str, Any],
        score: float,
        reason: str,
        confidence: str,
        workflow: str,
    ) -> ToolRecommendation:
        return ToolRecommendation(
            tool_id=tool_id,
            name=tool.get("name", tool_id),
            category=tool.get("category", "unknown"),
            score=score,
            reason_es=reason,
            confidence=confidence,
            workflow_summary=workflow,
            license=tool.get("license", "-"),
            learning_curve=tool.get("learning_curve", "-"),
            alternatives=tool.get("alternatives", []),
        )


# Singleton lazy
_advisor: Optional[ExpertAdvisor] = None


def get_advisor() -> ExpertAdvisor:
    global _advisor
    if _advisor is None:
        _advisor = ExpertAdvisor()
    return _advisor
