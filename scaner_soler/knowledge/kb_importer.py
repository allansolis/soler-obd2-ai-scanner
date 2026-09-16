"""
kb_importer.py — Enrich dtc_codes.db with professional data from the backend.

Run as:
    python -m scaner_soler.knowledge.kb_importer

Sources
-------
1. <backend>/data/dtc_database/professional_dtc_database.json
   → populates / updates table: dtc_extended

2. <backend>/backend/knowledge_hub/expert_profiles.json
   → populates / updates table: expert_tools

Both sources are idempotent (INSERT OR REPLACE).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).parent
_DB_PATH = _THIS_DIR.parent / "database" / "dtc_codes.db"

# Backend repo lives at a fixed location on the dev machine.
_BACKEND_BASE = Path(r"C:\Users\Usuario\AppData\Local\Temp\soler-obd2-ai-scanner")
_PROF_DTC_JSON = _BACKEND_BASE / "data" / "dtc_database" / "professional_dtc_database.json"
_EXPERT_JSON   = _BACKEND_BASE / "backend" / "knowledge_hub" / "expert_profiles.json"


# ── DDL ────────────────────────────────────────────────────────────────────────
_DDL_DTC_EXTENDED = """
CREATE TABLE IF NOT EXISTS dtc_extended (
    code                  TEXT NOT NULL,
    source                TEXT NOT NULL DEFAULT 'professional',
    symptoms              TEXT,
    technical_diagnosis   TEXT,
    real_solution         TEXT,
    probable_causes       TEXT,
    tools_needed          TEXT,
    estimated_time_hours  REAL,
    cost_min_usd          INTEGER,
    cost_max_usd          INTEGER,
    cost_labor_usd        INTEGER,
    PRIMARY KEY (code, source)
)
"""

_DDL_EXPERT_TOOLS = """
CREATE TABLE IF NOT EXISTS expert_tools (
    tool_id          TEXT PRIMARY KEY,
    name             TEXT,
    category         TEXT,
    publisher        TEXT,
    description      TEXT,
    brands           TEXT,
    use_cases        TEXT,
    strengths        TEXT,
    limitations      TEXT,
    license_type     TEXT,
    price_range      TEXT,
    hardware_required INTEGER,
    official_url     TEXT
)
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _jdumps(value) -> str | None:
    """Serialize a list/dict to JSON string; return None for empty/None."""
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _conn(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


# ── Import functions ──────────────────────────────────────────────────────────

def import_professional_dtcs(db_path: Path, json_path: Path) -> int:
    """
    Read professional_dtc_database.json and populate dtc_extended.
    Returns the number of rows inserted/replaced.
    """
    if not json_path.exists():
        print(f"[WARN] professional DTC JSON not found: {json_path}", file=sys.stderr)
        return 0

    with open(json_path, encoding="utf-8") as fh:
        data = json.load(fh)

    dtcs: list[dict] = data.get("dtcs", [])
    if not dtcs:
        print("[WARN] professional_dtc_database.json has no 'dtcs' list.", file=sys.stderr)
        return 0

    rows = []
    for entry in dtcs:
        code = (entry.get("code") or "").upper().strip()
        if not code:
            continue
        cost = entry.get("estimated_cost_usd") or {}
        rows.append((
            code,
            "professional",
            _jdumps(entry.get("symptoms")),
            entry.get("technical_diagnosis"),
            entry.get("real_solution"),
            _jdumps(entry.get("probable_causes")),
            _jdumps(entry.get("tools_needed")),
            entry.get("estimated_time_hours"),
            cost.get("parts_min"),
            cost.get("parts_max"),
            cost.get("labor"),
        ))

    with _conn(db_path) as con:
        con.execute(_DDL_DTC_EXTENDED)
        con.executemany(
            """INSERT OR REPLACE INTO dtc_extended
               (code, source, symptoms, technical_diagnosis, real_solution,
                probable_causes, tools_needed, estimated_time_hours,
                cost_min_usd, cost_max_usd, cost_labor_usd)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )

    return len(rows)


def import_expert_tools(db_path: Path, json_path: Path) -> int:
    """
    Read expert_profiles.json and populate expert_tools.
    Returns the number of rows inserted/replaced.
    """
    if not json_path.exists():
        print(f"[WARN] expert_profiles JSON not found: {json_path}", file=sys.stderr)
        return 0

    with open(json_path, encoding="utf-8") as fh:
        data = json.load(fh)

    tools_dict: dict = data.get("tools", {})
    if not tools_dict:
        print("[WARN] expert_profiles.json has no 'tools' dict.", file=sys.stderr)
        return 0

    rows = []
    for tool_key, entry in tools_dict.items():
        tool_id = entry.get("id") or tool_key

        # Brands live under supports.brands
        supports = entry.get("supports") or {}
        brands = supports.get("brands", [])

        # hardware_required may be a list of strings or a boolean
        hw_raw = entry.get("hardware_required")
        if isinstance(hw_raw, list):
            hardware_required = 1 if hw_raw else 0
        elif isinstance(hw_raw, bool):
            hardware_required = 1 if hw_raw else 0
        else:
            hardware_required = 0

        rows.append((
            tool_id,
            entry.get("name"),
            entry.get("category"),
            entry.get("publisher"),
            entry.get("description_es") or entry.get("description"),
            _jdumps(brands),
            _jdumps(entry.get("use_cases")),
            _jdumps(entry.get("strengths")),
            _jdumps(entry.get("limitations")),
            entry.get("license"),
            entry.get("price_range_usd"),
            hardware_required,
            entry.get("official_url"),
        ))

    with _conn(db_path) as con:
        con.execute(_DDL_EXPERT_TOOLS)
        con.executemany(
            """INSERT OR REPLACE INTO expert_tools
               (tool_id, name, category, publisher, description,
                brands, use_cases, strengths, limitations,
                license_type, price_range, hardware_required, official_url)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )

    return len(rows)


# ── Stats ─────────────────────────────────────────────────────────────────────

def print_stats(db_path: Path) -> None:
    """Print a summary of everything in the knowledge base."""
    with _conn(db_path) as con:
        tbls = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}

        def _count(t: str) -> int:
            return con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] if t in tbls else 0

        print("\n═══════════════════════════════════════")
        print("  Scaner Soler Pro — Knowledge Base Stats")
        print("═══════════════════════════════════════")
        print(f"  dtc_codes        : {_count('dtc_codes'):>6} registros")
        print(f"  oem_desc         : {_count('oem_desc'):>6} variantes OEM")
        print(f"  dtc_extended     : {_count('dtc_extended'):>6} DTCs profesionales")
        print(f"  ecu_models       : {_count('ecu_models'):>6} modelos de ECU")
        print(f"  ecu_faults       : {_count('ecu_faults'):>6} fallas de ECU")
        print(f"  ecu_components   : {_count('ecu_components'):>6} componentes / pinouts")
        print(f"  expert_tools     : {_count('expert_tools'):>6} herramientas profesionales")
        print("═══════════════════════════════════════")
        print(f"  Tablas presentes : {', '.join(sorted(tbls))}")
        print()


# ── CLI entry-point ───────────────────────────────────────────────────────────

def main() -> None:
    print(f"Base de datos   : {_DB_PATH}")
    print(f"DTC JSON        : {_PROF_DTC_JSON}")
    print(f"Expert JSON     : {_EXPERT_JSON}")
    print()

    n_dtc = import_professional_dtcs(_DB_PATH, _PROF_DTC_JSON)
    print(f"[OK] dtc_extended  — {n_dtc} DTCs importados/actualizados")

    n_tools = import_expert_tools(_DB_PATH, _EXPERT_JSON)
    print(f"[OK] expert_tools  — {n_tools} herramientas importadas/actualizadas")

    print_stats(_DB_PATH)


if __name__ == "__main__":
    main()
