"""
SOLER OBD2 AI Scanner - Knowledge Graph
=======================================
Grafo en memoria que conecta:

    Vehiculos  ->  ECUs  ->  DTCs  ->  Tools  ->  PDFs (paginas, torques,
                                                       procedimientos)

Se construye a partir de:
    * backend/knowledge_hub/expert_profiles.json   (tools + marcas soportadas)
    * data/knowledge_extracted/pdf_analysis.json   (knowledge extraido)
    * data/knowledge_extracted/dtc_sources.json    (mapa inverso)

Permite consultas transitivas sin recorrer los JSON manualmente.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Paths por defecto -----------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILES_JSON = Path(__file__).resolve().parent / "expert_profiles.json"
PDF_ANALYSIS_JSON = PROJECT_ROOT / "data" / "knowledge_extracted" / "pdf_analysis.json"
DTC_SOURCES_JSON = PROJECT_ROOT / "data" / "knowledge_extracted" / "dtc_sources.json"


# ---------------------------------------------------------------------------
# Dataclasses publicas
# ---------------------------------------------------------------------------

@dataclass
class Evidence:
    """Evidencia de un tool en manuales reales."""
    pdf: str
    title: str
    category: str
    system: str
    pages: int
    why: str = ""                 # razon por la que este PDF es evidencia

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Context:
    """Contexto completo para un vehiculo + (opcional) DTC."""
    make: str
    model: str
    year: Optional[int]
    dtc: Optional[str]
    pdfs: list[dict] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    dtcs_related: list[str] = field(default_factory=list)
    procedures: list[str] = field(default_factory=list)
    torque_specs: list[dict] = field(default_factory=list)
    ecus: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# KnowledgeGraph
# ---------------------------------------------------------------------------

class KnowledgeGraph:
    """
    Grafo que conecta Vehiculos -> ECUs -> DTCs -> Tools -> PDFs.
    Carga perezosa; tolera ausencia de pdf_analysis.json (se comporta como vacio).
    """

    def __init__(
        self,
        profiles_path: Path = PROFILES_JSON,
        pdf_analysis_path: Path = PDF_ANALYSIS_JSON,
        dtc_sources_path: Path = DTC_SOURCES_JSON,
    ):
        self.profiles_path = profiles_path
        self.pdf_analysis_path = pdf_analysis_path
        self.dtc_sources_path = dtc_sources_path

        self._profiles: dict[str, Any] = {}
        self._tools: dict[str, dict[str, Any]] = {}
        self._pdfs_by_file: dict[str, dict[str, Any]] = {}
        self._dtc_sources: dict[str, dict[str, Any]] = {}

        # indices derivados
        self._pdfs_by_make: dict[str, list[str]] = defaultdict(list)
        self._pdfs_by_dtc: dict[str, list[str]] = defaultdict(list)
        self._pdfs_by_tool: dict[str, list[str]] = defaultdict(list)
        self._tools_by_dtc_hint: dict[str, list[str]] = defaultdict(list)

        self.reload()

    # ----- Carga -----

    def reload(self) -> None:
        self._profiles = self._read_json(self.profiles_path, default={"tools": {}})
        self._tools = self._profiles.get("tools", {})
        pdf_payload = self._read_json(self.pdf_analysis_path, default={"pdfs": []})
        pdfs = pdf_payload.get("pdfs", []) if isinstance(pdf_payload, dict) else []
        self._pdfs_by_file = {p["file"]: p for p in pdfs if isinstance(p, dict) and p.get("file")}
        self._dtc_sources = self._read_json(self.dtc_sources_path, default={})

        self._build_indices()
        logger.info(
            "KnowledgeGraph listo: tools=%d, pdfs=%d, dtcs=%d",
            len(self._tools), len(self._pdfs_by_file), len(self._dtc_sources),
        )

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.is_file():
            return default
        try:
            with path.open("r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception as e:
            logger.warning("no se pudo leer %s: %s", path, e)
            return default

    def _build_indices(self) -> None:
        self._pdfs_by_make.clear()
        self._pdfs_by_dtc.clear()
        self._pdfs_by_tool.clear()
        self._tools_by_dtc_hint.clear()

        for fpath, pdf in self._pdfs_by_file.items():
            for v in pdf.get("vehicles_mentioned") or []:
                mk = (v.get("make") or "").strip().lower()
                if mk:
                    self._pdfs_by_make[mk].append(fpath)
            for dtc in pdf.get("dtcs_mentioned") or []:
                self._pdfs_by_dtc[dtc.upper()].append(fpath)
            for tool in pdf.get("tools_required") or []:
                self._pdfs_by_tool[tool].append(fpath)

        # tool -> pdfs: tambien marcar por nombre del tool en expert_profiles.
        for tid, t in self._tools.items():
            name = t.get("name", tid)
            needle = name.split(" (")[0]
            for fpath, pdf in self._pdfs_by_file.items():
                if any(n.lower() == needle.lower() for n in (pdf.get("tools_required") or [])):
                    if fpath not in self._pdfs_by_tool.get(tid, []):
                        self._pdfs_by_tool[tid].append(fpath)

    # ----- API publica -----

    def get_complete_context(
        self,
        make: str = "",
        model: str = "",
        year: Optional[int] = None,
        dtc: Optional[str] = None,
    ) -> Context:
        """Devuelve todo lo que sabemos para (vehiculo, dtc)."""
        mk = (make or "").strip().lower()
        model_l = (model or "").strip().lower()
        dtc_u = (dtc or "").strip().upper() or None

        candidate_files = set()
        if mk:
            candidate_files.update(self._pdfs_by_make.get(mk, []))
        if dtc_u:
            candidate_files.update(self._pdfs_by_dtc.get(dtc_u, []))
        if not candidate_files and not mk and not dtc_u:
            candidate_files.update(self._pdfs_by_file.keys())

        pdfs = []
        procedures: list[str] = []
        torques: list[dict] = []
        ecus: set[str] = set()
        dtcs_related: set[str] = set()
        tools_set: set[str] = set()

        for fpath in candidate_files:
            pdf = self._pdfs_by_file.get(fpath)
            if not pdf:
                continue
            if model_l:
                # filtrar por modelo si aparece en path/titulo
                hay = (pdf.get("file", "") + " " + pdf.get("title", "")).lower()
                if model_l not in hay:
                    continue
            pdfs.append({
                "file": pdf["file"],
                "title": pdf.get("title"),
                "category": pdf.get("category"),
                "system": pdf.get("system"),
                "pages": pdf.get("pages"),
            })
            for s in (pdf.get("procedures") or [])[:5]:
                if s not in procedures:
                    procedures.append(s)
            for t in (pdf.get("torque_specs") or [])[:10]:
                torques.append({**t, "source": pdf["file"]})
            for e in pdf.get("ecus_mentioned") or []:
                ecus.add(e)
            for d in pdf.get("dtcs_mentioned") or []:
                dtcs_related.add(d)
            for t in pdf.get("tools_required") or []:
                tools_set.add(t)

        # Convertir tools citados a registros de expert_profiles cuando match.
        tools_out = []
        for tid, t in self._tools.items():
            tname = t.get("name", tid)
            if tname.split(" (")[0] in tools_set or self._tool_supports_make(t, make):
                tools_out.append({
                    "tool_id": tid,
                    "name": tname,
                    "category": t.get("category"),
                    "cited_in_manuals": tname.split(" (")[0] in tools_set,
                })

        return Context(
            make=make, model=model, year=year, dtc=dtc_u,
            pdfs=sorted(pdfs, key=lambda x: (x.get("category") or "", x.get("file") or ""))[:25],
            tools=tools_out,
            dtcs_related=sorted(dtcs_related)[:60],
            procedures=procedures[:12],
            torque_specs=torques[:25],
            ecus=sorted(ecus)[:20],
        )

    def evidence_for_tool(self, tool_id: str, limit: int = 8) -> list[Evidence]:
        """Lista de PDFs que mencionan el tool + razon."""
        tool = self._tools.get(tool_id)
        if not tool:
            return []
        tname = tool.get("name", tool_id).split(" (")[0]
        files = list(self._pdfs_by_tool.get(tool_id, []))
        # fallback: buscar por nombre case-insensitive
        if not files:
            for fpath, pdf in self._pdfs_by_file.items():
                tools = [t.lower() for t in (pdf.get("tools_required") or [])]
                if any(tname.lower() == t for t in tools):
                    files.append(fpath)
        out: list[Evidence] = []
        seen = set()
        for fpath in files:
            if fpath in seen:
                continue
            seen.add(fpath)
            pdf = self._pdfs_by_file.get(fpath) or {}
            out.append(Evidence(
                pdf=fpath,
                title=pdf.get("title", Path(fpath).stem),
                category=pdf.get("category", "misc"),
                system=pdf.get("system", "unknown"),
                pages=pdf.get("pages", 0),
                why=f"{tname} citado en el manual",
            ))
            if len(out) >= limit:
                break
        return out

    def evidence_for_dtc(self, dtc: str, limit: int = 8) -> list[Evidence]:
        """Lista de PDFs que mencionan el DTC."""
        dtc_u = (dtc or "").strip().upper()
        files = self._pdfs_by_dtc.get(dtc_u, [])
        out: list[Evidence] = []
        for fpath in files[:limit]:
            pdf = self._pdfs_by_file.get(fpath) or {}
            out.append(Evidence(
                pdf=fpath,
                title=pdf.get("title", Path(fpath).stem),
                category=pdf.get("category", "misc"),
                system=pdf.get("system", "unknown"),
                pages=pdf.get("pages", 0),
                why=f"DTC {dtc_u} mencionado en el manual",
            ))
        return out

    def pdfs_for_make(self, make: str, limit: int = 25) -> list[dict]:
        mk = (make or "").strip().lower()
        out = []
        for fpath in self._pdfs_by_make.get(mk, [])[:limit]:
            pdf = self._pdfs_by_file.get(fpath) or {}
            out.append({
                "file": fpath,
                "title": pdf.get("title"),
                "category": pdf.get("category"),
                "system": pdf.get("system"),
                "pages": pdf.get("pages"),
            })
        return out

    def dtc_info(self, dtc: str) -> dict:
        dtc_u = (dtc or "").strip().upper()
        info = self._dtc_sources.get(dtc_u, {"sources": [], "vehicles_affected": []})
        return {"dtc": dtc_u, **info}

    # ----- Helpers -----

    def _tool_supports_make(self, tool: dict[str, Any], make: str) -> bool:
        if not make:
            return False
        brands = (tool.get("supports") or {}).get("brands") or []
        make_l = make.strip().lower()
        return any(make_l in b.lower() for b in brands)


# Singleton lazy --------------------------------------------------------------

_graph: Optional[KnowledgeGraph] = None


def get_graph() -> KnowledgeGraph:
    global _graph
    if _graph is None:
        _graph = KnowledgeGraph()
    return _graph
