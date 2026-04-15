"""
SOLER OBD2 AI Scanner - PDF Knowledge Extractor
===============================================
Analiza en profundidad los PDFs de manuales automotrices y software
(carpeta `data/`) y extrae conocimiento estructurado:

    * metadatos (titulo, paginas, autor)
    * DTCs mencionados (P/U/B/C + 4 digitos con tolerancia a espacios/guiones)
    * vehiculos (marca/modelo/ano) inferidos por path + contenido
    * ECUs y part numbers Bosch/Siemens/Delphi
    * torque specs (Nm / lb-ft / kgfm)
    * pinouts / pin numbers
    * herramientas citadas (KTS, ELM327, KESS, KTAG, WinOLS, ...)
    * procedimientos numerados

Salidas:
    data/knowledge_extracted/pdf_analysis.json  (uno por PDF + stats)
    data/knowledge_extracted/dtc_sources.json   (mapa inverso DTC -> PDFs)
    data/knowledge_extracted/_cache/*.json      (cache incremental por PDF)

Uso tipico:

    python backend/knowledge_hub/pdf_analyzer.py            # todo
    python backend/knowledge_hub/pdf_analyzer.py --limit 100
    python backend/knowledge_hub/pdf_analyzer.py --only obd-diesel,datos-tecnicos
    python backend/knowledge_hub/pdf_analyzer.py --workers 6 --max-pages 50

Requisitos: pip install pymupdf
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Paths y constantes
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
OUT_DIR = DATA_DIR / "knowledge_extracted"
CACHE_DIR = OUT_DIR / "_cache"
PDF_ANALYSIS_JSON = OUT_DIR / "pdf_analysis.json"
DTC_SOURCES_JSON = OUT_DIR / "dtc_sources.json"

# Prioridad - carpetas mas ricas en conocimiento diagnostico.
PRIORITY_DIRS = [
    "downloaded_pdfs",
    "obd-diesel",
    "datos-tecnicos",
    "abs-esp",
    "airbag",
    "localizacion-componentes",
    "aire-acondicionado",
    "transmision",
    "kit-scaner",
    "knowledge_base",
    "4lap",
    "tuning_maps",
    "vehicle_profiles",
]

# ---------------------------------------------------------------------------
# Regex - compiladas una sola vez por proceso
# ---------------------------------------------------------------------------

# DTC: letra (P/U/B/C) + opcional espacio/guion + 4 hex/digitos.
# Evita falsos positivos: rechaza si el siguiente char es letra/digit.
DTC_RE = re.compile(
    r"\b([PUBC])\s*[-]?\s*([0-9A-F]{4})\b(?![A-Z0-9])",
    re.IGNORECASE,
)

# Torque: numero seguido de unidad.
TORQUE_RE = re.compile(
    r"(\d{1,4}(?:[.,]\d{1,2})?)\s*(Nm|N\.m|N·m|lb[-\s]?ft|lbf[-\s]?ft|kgf?\.?m|kgm)",
    re.IGNORECASE,
)

# ECU/part numbers Bosch (0 281 xxx xxx), Siemens, Delphi, Denso, Marelli.
ECU_PN_RE = re.compile(
    r"\b("
    r"0\s?28[01]\s?\d{3}\s?\d{3}"         # Bosch EDC/ME
    r"|5W[KS]\s?\d{5}"                    # Siemens/Continental
    r"|28[0-9]{6,8}"                      # Delphi
    r"|89[0-9]{2}-[0-9A-Z]{5}"            # Denso Toyota
    r"|IAW\s?\d[A-Z0-9.]{2,}"             # Magneti Marelli
    r"|MED\s?\d{1,2}(?:\.\d{1,2})?"       # Bosch MED family
    r"|EDC\s?\d{1,2}(?:[CP]\s?\d{1,3})?"  # Bosch EDC family
    r"|ME\s?\d{1,2}(?:\.\d{1,2})?"        # Bosch ME family
    r"|MEV\s?D?\s?\d{1,4}"                # Bosch MEV
    r"|SIM\s?\d{2,4}"                     # SIM Siemens
    r"|DCM\s?\d(?:\.\d)?"                 # Delphi DCM
    r")",
    re.IGNORECASE,
)

# Pinout: "pin 23 ..." / "pino 4 ..." / "terminal 17 ...".
PIN_RE = re.compile(
    r"\b(?:pin|pino|terminal|borne)\s*[:#]?\s*(\d{1,3})\b",
    re.IGNORECASE,
)

# Procedimientos: listas numeradas "1. ..." / "1) ...".
STEP_RE = re.compile(r"(?m)^\s*(\d{1,2})[.)\-]\s+([A-Za-zÀ-ÿ].{8,200})$")

# Herramientas citadas.
TOOL_PATTERNS = {
    "KTS": re.compile(r"\bKTS\s?(?:5\d{2}|6\d{2}|2\d{2}|5\d{3})?\b", re.I),
    "ELM327": re.compile(r"\bELM\s?327\b", re.I),
    "KESS": re.compile(r"\bKESS\s?V?\d?\b", re.I),
    "KTAG": re.compile(r"\bK-?TAG\b", re.I),
    "WinOLS": re.compile(r"\bWin\s?OLS\b", re.I),
    "ECM Titanium": re.compile(r"\bECM\s?Titanium\b", re.I),
    "HP Tuners": re.compile(r"\bHP\s?Tuners?\b", re.I),
    "Autodata": re.compile(r"\bAutodata\b", re.I),
    "Mitchell": re.compile(r"\bMitchell\b|\bProDemand\b", re.I),
    "ISTA": re.compile(r"\bISTA(?:/?[DP])?\b", re.I),
    "GDS": re.compile(r"\bGDS(?:\s?Mobile)?\b", re.I),
    "G-Scan": re.compile(r"\bG-?Scan\b", re.I),
    "Launch X431": re.compile(r"\bLaunch\s?X-?431\b", re.I),
    "Delphi DS150E": re.compile(r"\bDS\s?150E?\b", re.I),
    "Autel MaxiSys": re.compile(r"\bAutel\s?Maxi\S*\b", re.I),
    "compresometro": re.compile(r"\bcompres[oó]metro|compression\s?tester\b", re.I),
    "osciloscopio": re.compile(r"\boscilosc[oó]pi[oa]|oscilloscope\b", re.I),
    "multimetro": re.compile(r"\bmult[ií]metro|multimeter\b", re.I),
    "J2534": re.compile(r"\bJ-?2534\b|\bPass\s?Thru\b", re.I),
    "XPROG": re.compile(r"\bXPROG\b", re.I),
    "TL866": re.compile(r"\bTL-?866\b", re.I),
}

# Makes - para deteccion en contenido (se complementa con path).
VEHICLE_MAKES = [
    "Alfa Romeo", "Audi", "BMW", "Chevrolet", "Chrysler", "Citroen",
    "Dacia", "Daihatsu", "Dodge", "Fiat", "Ford", "Honda", "Hyundai",
    "Jeep", "Kia", "Lancia", "Land Rover", "Lexus", "Mazda", "Mercedes",
    "Mini", "Mitsubishi", "Nissan", "Opel", "Peugeot", "Porsche",
    "Renault", "Seat", "Skoda", "Smart", "Subaru", "Suzuki", "Toyota",
    "Volkswagen", "VW", "Volvo", "Cummins", "Scania", "Iveco",
    "John Deere", "Caterpillar", "Perkins", "Maxion", "MWM",
]
MAKE_RE = re.compile(
    r"\b(" + "|".join(re.escape(m) for m in VEHICLE_MAKES) + r")\b",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")

# Clasificacion por categoria (derivada del path)
CATEGORY_MAP = {
    "obd-diesel": "obd_diesel",
    "datos-tecnicos": "technical_specs",
    "abs-esp": "abs_esp",
    "airbag": "airbag_srs",
    "aire-acondicionado": "hvac",
    "localizacion-componentes": "component_location",
    "transmision": "transmission",
    "kit-scaner": "scan_tools",
    "knowledge_base": "knowledge_base",
    "tuning_maps": "tuning",
    "vehicle_profiles": "vehicle_profiles",
    "downloaded_pdfs": "reference_manual",
    "4lap": "misc",
}

SYSTEM_HINTS = {
    "engine": ["motor", "engine", "common rail", "diesel", "inyector", "turbo", "egr", "dpf"],
    "abs": ["abs", "esp", "esc", "brake", "freno"],
    "airbag": ["airbag", "srs", "restraint", "pretensor"],
    "transmission": ["transmisi", "gearbox", "caixa", "cvt", "dsg", "automatic"],
    "hvac": ["aire acondicionado", "ac ", "hvac", "climatronic", "evaporador"],
    "body": ["bcm", "ipm", "comfort", "conveniencia", "confort"],
}

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PdfRecord:
    file: str
    file_hash: str
    title: str
    pages: int
    category: str
    system: str
    dtcs_mentioned: list[str] = field(default_factory=list)
    vehicles_mentioned: list[dict[str, str]] = field(default_factory=list)
    ecus_mentioned: list[str] = field(default_factory=list)
    tools_required: list[str] = field(default_factory=list)
    pin_numbers_seen: list[int] = field(default_factory=list)
    procedures: list[str] = field(default_factory=list)
    torque_specs: list[dict[str, Any]] = field(default_factory=list)
    summary_es: str = ""
    error: str = ""

# ---------------------------------------------------------------------------
# Extraction helpers (stateless - pickleable for multiprocessing)
# ---------------------------------------------------------------------------

def _category_from_path(rel_parts: list[str]) -> str:
    for p in rel_parts:
        key = p.lower()
        if key in CATEGORY_MAP:
            return CATEGORY_MAP[key]
    return "misc"

def _system_from_text(text_lower: str, category: str) -> str:
    for sys_name, hints in SYSTEM_HINTS.items():
        if any(h in text_lower for h in hints):
            return sys_name
    if category in ("abs_esp",):
        return "abs"
    if category == "airbag_srs":
        return "airbag"
    if category == "hvac":
        return "hvac"
    if category == "transmission":
        return "transmission"
    if category in ("obd_diesel", "technical_specs", "tuning"):
        return "engine"
    return "unknown"

def _normalize_dtc(letter: str, digits: str) -> str:
    return f"{letter.upper()}{digits.upper()}"

def _extract_vehicles(text: str, path_hint: str) -> list[dict[str, str]]:
    makes_found = {m.title() for m in MAKE_RE.findall(text)}
    # Agregar make desde el path (p. ej. .../Ford/...)
    for part in path_hint.split(os.sep):
        for mk in VEHICLE_MAKES:
            if part.lower() == mk.lower():
                makes_found.add(mk)
    years = YEAR_RE.findall(text)
    year_range = ""
    if years:
        ys = sorted({int(y) for y in years})
        year_range = f"{ys[0]}-{ys[-1]}" if len(ys) > 1 else str(ys[0])
    out = []
    for mk in sorted(makes_found):
        out.append({"make": mk, "model": "", "year_range": year_range})
    return out

def _file_hash(path: Path) -> str:
    h = hashlib.sha1()
    h.update(str(path).encode("utf-8", "ignore"))
    try:
        h.update(str(path.stat().st_size).encode())
        h.update(str(int(path.stat().st_mtime)).encode())
    except OSError:
        pass
    return h.hexdigest()[:16]

# ---------------------------------------------------------------------------
# Core per-PDF worker
# ---------------------------------------------------------------------------

def analyze_pdf(args: tuple[str, str, int]) -> dict[str, Any]:
    """Worker: devuelve dict PdfRecord. Importa fitz dentro para multiproc."""
    pdf_path_s, data_root_s, max_pages = args
    pdf_path = Path(pdf_path_s)
    data_root = Path(data_root_s)
    rel = pdf_path.relative_to(data_root)
    rel_parts = [p.lower() for p in rel.parts]

    record = PdfRecord(
        file=str(Path("data") / rel).replace("\\", "/"),
        file_hash=_file_hash(pdf_path),
        title=pdf_path.stem,
        pages=0,
        category=_category_from_path(rel_parts),
        system="unknown",
    )

    try:
        import fitz  # PyMuPDF
    except Exception as e:
        record.error = f"pymupdf_import_failed: {e}"
        return asdict(record)

    try:
        doc = fitz.open(pdf_path_s)
    except Exception as e:
        record.error = f"open_failed: {e}"
        return asdict(record)

    try:
        meta = doc.metadata or {}
        if meta.get("title"):
            record.title = meta["title"][:200]
        record.pages = doc.page_count

        pages_to_read = min(doc.page_count, max_pages)
        texts: list[str] = []
        dtc_set: set[str] = set()
        ecu_set: set[str] = set()
        tools_set: set[str] = set()
        pin_set: set[int] = set()
        torques: list[dict[str, Any]] = []
        procedures: list[str] = []

        for pg_idx in range(pages_to_read):
            try:
                page = doc.load_page(pg_idx)
                text = page.get_text("text") or ""
            except Exception:
                continue
            texts.append(text)

            for m in DTC_RE.finditer(text):
                dtc_set.add(_normalize_dtc(m.group(1), m.group(2)))
            for m in ECU_PN_RE.finditer(text):
                ecu_set.add(re.sub(r"\s+", " ", m.group(1).strip()))
            for tool_name, patt in TOOL_PATTERNS.items():
                if patt.search(text):
                    tools_set.add(tool_name)
            for m in PIN_RE.finditer(text):
                try:
                    pin_set.add(int(m.group(1)))
                except ValueError:
                    pass
            for m in TORQUE_RE.finditer(text):
                val, unit = m.group(1), m.group(2)
                # Captura contexto previo como "componente".
                start = max(0, m.start() - 60)
                ctx = text[start:m.start()].strip().splitlines()[-1] if text[start:m.start()].strip() else ""
                torques.append({
                    "component": ctx[:80],
                    "value": f"{val} {unit}",
                    "page": pg_idx + 1,
                })
            for m in STEP_RE.finditer(text):
                step_text = m.group(2).strip()
                if 10 <= len(step_text) <= 180 and step_text not in procedures:
                    procedures.append(step_text)
                if len(procedures) >= 40:
                    break

        doc.close()

        full_text = "\n".join(texts)
        text_lower = full_text.lower()
        record.system = _system_from_text(text_lower, record.category)
        record.dtcs_mentioned = sorted(dtc_set)
        record.vehicles_mentioned = _extract_vehicles(full_text, str(pdf_path))
        record.ecus_mentioned = sorted(ecu_set)
        record.tools_required = sorted(tools_set)
        record.pin_numbers_seen = sorted(pin_set)[:40]
        record.procedures = procedures[:20]
        record.torque_specs = torques[:40]
        # Resumen corto en espanol.
        summary_bits = []
        if record.vehicles_mentioned:
            mks = ", ".join(v["make"] for v in record.vehicles_mentioned[:3])
            summary_bits.append(f"Vehiculos: {mks}")
        summary_bits.append(f"Sistema: {record.system}")
        if record.dtcs_mentioned:
            summary_bits.append(f"{len(record.dtcs_mentioned)} DTCs")
        if record.torque_specs:
            summary_bits.append(f"{len(record.torque_specs)} torques")
        if record.procedures:
            summary_bits.append(f"{len(record.procedures)} pasos")
        record.summary_es = " | ".join(summary_bits)

    except Exception:
        record.error = "analyze_failed: " + traceback.format_exc().splitlines()[-1]

    return asdict(record)

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def iter_pdfs(data_root: Path, only: Optional[set[str]] = None) -> Iterable[Path]:
    """Genera PDFs en orden de prioridad (carpetas ricas primero)."""
    seen: set[str] = set()
    dirs = PRIORITY_DIRS if not only else [d for d in PRIORITY_DIRS if d in only]
    # prioritizadas
    for d in dirs:
        base = data_root / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.pdf")):
            key = str(p).lower()
            if key in seen:
                continue
            seen.add(key)
            yield p
    # resto (si no hay filtro `only`)
    if not only:
        for p in sorted(data_root.rglob("*.pdf")):
            key = str(p).lower()
            if key in seen:
                continue
            seen.add(key)
            yield p

def load_cache(pdf_path: Path) -> Optional[dict]:
    cache_file = CACHE_DIR / f"{_file_hash(pdf_path)}.json"
    if cache_file.is_file():
        try:
            with cache_file.open("r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            return None
    return None

def save_cache(record: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{record['file_hash']}.json"
    with cache_file.open("w", encoding="utf-8") as fp:
        json.dump(record, fp, ensure_ascii=False, indent=2)

def write_partial(records: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stats = _compute_stats(records)
    payload = {"pdfs": records, "stats": stats, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    tmp = PDF_ANALYSIS_JSON.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    tmp.replace(PDF_ANALYSIS_JSON)

def _compute_stats(records: list[dict]) -> dict[str, Any]:
    total = len(records)
    dtcs: set[str] = set()
    vehicles: set[str] = set()
    tools: set[str] = set()
    errs = 0
    for r in records:
        if r.get("error"):
            errs += 1
        dtcs.update(r.get("dtcs_mentioned") or [])
        tools.update(r.get("tools_required") or [])
        for v in r.get("vehicles_mentioned") or []:
            vehicles.add(v.get("make", ""))
    return {
        "total_analyzed": total,
        "total_errors": errs,
        "total_dtcs_extracted": len(dtcs),
        "total_vehicles_identified": len(vehicles),
        "unique_tools": len(tools),
    }

def build_dtc_sources(records: list[dict]) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = {}
    for r in records:
        file = r["file"]
        vehicles = [f"{v.get('make','')} {v.get('year_range','')}".strip()
                    for v in r.get("vehicles_mentioned") or []]
        for dtc in r.get("dtcs_mentioned") or []:
            slot = out.setdefault(dtc, {"sources": [], "vehicles_affected": [], "pages_with_info": []})
            if file not in slot["sources"]:
                slot["sources"].append(file)
            for v in vehicles:
                if v and v not in slot["vehicles_affected"]:
                    slot["vehicles_affected"].append(v)
    return out

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="max PDFs (0 = todos)")
    ap.add_argument("--only", default="", help="coma-sep dirs a incluir")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    ap.add_argument("--max-pages", type=int, default=50)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--save-every", type=int, default=50)
    args = ap.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    only = {s.strip() for s in args.only.split(",") if s.strip()} or None
    all_pdfs = list(iter_pdfs(DATA_DIR, only=only))
    if args.limit > 0:
        all_pdfs = all_pdfs[: args.limit]
    print(f"[pdf_analyzer] descubiertos {len(all_pdfs)} PDFs "
          f"(workers={args.workers}, max_pages={args.max_pages})", flush=True)

    # Cargar resultados previos para salida incremental.
    records: list[dict] = []
    if PDF_ANALYSIS_JSON.is_file():
        try:
            with PDF_ANALYSIS_JSON.open("r", encoding="utf-8") as fp:
                prev = json.load(fp)
            records = prev.get("pdfs", [])
            print(f"[pdf_analyzer] cargados {len(records)} registros previos", flush=True)
        except Exception:
            records = []
    done_files = {r["file"] for r in records}

    # Separar los que ya estan (cache) de los que hay que procesar.
    to_process: list[Path] = []
    for p in all_pdfs:
        rel_file = str(Path("data") / p.relative_to(DATA_DIR)).replace("\\", "/")
        if rel_file in done_files:
            continue
        if not args.no_cache:
            cached = load_cache(p)
            if cached:
                records.append(cached)
                done_files.add(cached["file"])
                continue
        to_process.append(p)

    print(f"[pdf_analyzer] pendientes {len(to_process)}", flush=True)
    if to_process:
        tasks = [(str(p), str(DATA_DIR), args.max_pages) for p in to_process]
        processed = 0
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(analyze_pdf, t): t for t in tasks}
            for fut in as_completed(futures):
                try:
                    rec = fut.result()
                except Exception as e:
                    rec = {"file": futures[fut][0], "error": f"worker_crash: {e}"}
                records.append(rec)
                if rec.get("file_hash") and not rec.get("error"):
                    save_cache(rec)
                processed += 1
                if processed % 10 == 0:
                    print(f"  ... {processed}/{len(to_process)} "
                          f"(errors={sum(1 for r in records if r.get('error'))})", flush=True)
                if processed % args.save_every == 0:
                    write_partial(records)

    write_partial(records)
    dtc_sources = build_dtc_sources(records)
    with DTC_SOURCES_JSON.open("w", encoding="utf-8") as fp:
        json.dump(dtc_sources, fp, ensure_ascii=False, indent=2)

    stats = _compute_stats(records)
    print("[pdf_analyzer] FINAL STATS:", json.dumps(stats, indent=2))
    print(f"  -> {PDF_ANALYSIS_JSON}")
    print(f"  -> {DTC_SOURCES_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
