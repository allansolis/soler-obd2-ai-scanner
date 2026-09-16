import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "database" / "dtc_codes.db"

# Generic OBD-II P0xxx descriptions (subset — extend with full SAE J2012 table)
GENERIC_DTCS = {
    "P0100": ("MAF Circuit Malfunction", "Fuel/Air Metering", "critical"),
    "P0101": ("MAF Circuit Range/Performance", "Fuel/Air Metering", "warning"),
    "P0102": ("MAF Circuit Low Input", "Fuel/Air Metering", "critical"),
    "P0103": ("MAF Circuit High Input", "Fuel/Air Metering", "critical"),
    "P0110": ("IAT Sensor Circuit Malfunction", "Fuel/Air Metering", "warning"),
    "P0113": ("IAT Sensor Circuit High Input", "Fuel/Air Metering", "warning"),
    "P0116": ("Engine Coolant Temp Circuit Range", "Cooling System", "warning"),
    "P0117": ("Engine Coolant Temp Circuit Low", "Cooling System", "critical"),
    "P0118": ("Engine Coolant Temp Circuit High", "Cooling System", "critical"),
    "P0120": ("TPS Circuit Malfunction", "Throttle Body", "critical"),
    "P0121": ("TPS Circuit Range/Performance", "Throttle Body", "warning"),
    "P0130": ("O2 Sensor Circuit Malfunction B1S1", "Fuel System", "warning"),
    "P0131": ("O2 Sensor Low Voltage B1S1", "Fuel System", "warning"),
    "P0132": ("O2 Sensor High Voltage B1S1", "Fuel System", "warning"),
    "P0133": ("O2 Sensor Slow Response B1S1", "Fuel System", "warning"),
    "P0134": ("O2 Sensor No Activity B1S1", "Fuel System", "warning"),
    "P0171": ("System Too Lean Bank 1", "Fuel System", "critical"),
    "P0172": ("System Too Rich Bank 1", "Fuel System", "critical"),
    "P0174": ("System Too Lean Bank 2", "Fuel System", "critical"),
    "P0175": ("System Too Rich Bank 2", "Fuel System", "critical"),
    "P0201": ("Injector Circuit Malfunction Cyl 1", "Fuel System", "critical"),
    "P0202": ("Injector Circuit Malfunction Cyl 2", "Fuel System", "critical"),
    "P0203": ("Injector Circuit Malfunction Cyl 3", "Fuel System", "critical"),
    "P0204": ("Injector Circuit Malfunction Cyl 4", "Fuel System", "critical"),
    "P0230": ("Fuel Pump Primary Circuit", "Fuel System", "critical"),
    "P0261": ("Cyl 1 Injector Low", "Fuel System", "critical"),
    "P0300": ("Random/Multiple Cylinder Misfire", "Ignition System", "critical"),
    "P0301": ("Cyl 1 Misfire Detected", "Ignition System", "critical"),
    "P0302": ("Cyl 2 Misfire Detected", "Ignition System", "critical"),
    "P0303": ("Cyl 3 Misfire Detected", "Ignition System", "critical"),
    "P0304": ("Cyl 4 Misfire Detected", "Ignition System", "critical"),
    "P0320": ("Ignition/Distributor Engine Speed Input Circuit", "Ignition System", "critical"),
    "P0325": ("Knock Sensor 1 Circuit Malfunction Bank 1", "Ignition System", "warning"),
    "P0326": ("Knock Sensor 1 Circuit Range/Performance", "Ignition System", "warning"),
    "P0327": ("Knock Sensor 1 Circuit Low Input Bank 1", "Ignition System", "critical"),
    "P0328": ("Knock Sensor 1 Circuit High Input Bank 1", "Ignition System", "critical"),
    "P0335": ("CKP Sensor A Circuit Malfunction", "Ignition System", "critical"),
    "P0336": ("CKP Sensor A Circuit Range/Performance", "Ignition System", "critical"),
    "P0340": ("CMP Sensor Circuit Malfunction Bank 1", "Valve Train", "critical"),
    "P0341": ("CMP Sensor Circuit Range/Performance", "Valve Train", "critical"),
    "P0400": ("EGR Flow Malfunction", "Emissions", "warning"),
    "P0401": ("EGR Flow Insufficient Detected", "Emissions", "warning"),
    "P0402": ("EGR Flow Excessive Detected", "Emissions", "warning"),
    "P0420": ("Catalyst System Efficiency Below Threshold B1", "Emissions", "warning"),
    "P0430": ("Catalyst System Efficiency Below Threshold B2", "Emissions", "warning"),
    "P0440": ("Evaporative Emission System Malfunction", "Emissions", "warning"),
    "P0441": ("Evaporative Emission System Incorrect Purge Flow", "Emissions", "warning"),
    "P0442": ("Evaporative Emission System Leak Detected (small)", "Emissions", "warning"),
    "P0455": ("Evaporative Emission System Leak Detected (large)", "Emissions", "warning"),
    "P0500": ("VSS Malfunction", "Speed/Cruise Control", "warning"),
    "P0505": ("Idle Control System Malfunction", "Idle Control", "warning"),
    "P0506": ("Idle Control System RPM Too Low", "Idle Control", "warning"),
    "P0507": ("Idle Control System RPM Too High", "Idle Control", "warning"),
    "P0560": ("System Voltage Malfunction", "Electrical", "critical"),
    "P0562": ("System Voltage Low", "Electrical", "critical"),
    "P0563": ("System Voltage High", "Electrical", "critical"),
    "P0600": ("Serial Communication Link Malfunction", "Computer/Output", "critical"),
    "P0601": ("Internal Control Module Memory Check Sum Error", "Computer/Output", "critical"),
    "P0605": ("Internal Control Module ROM Error", "Computer/Output", "critical"),
    "P0700": ("Transmission Control System Malfunction", "Transmission", "critical"),
    "P0720": ("Output Speed Sensor Circuit Malfunction", "Transmission", "warning"),
    "P0730": ("Incorrect Gear Ratio", "Transmission", "critical"),
}

SUGGESTIONS = {
    "critical": "Revisar inmediatamente. Puede causar daño al motor si se ignora.",
    "warning":  "Revisar pronto. Puede afectar emisiones o rendimiento.",
    "info":     "Monitorear. No requiere accion inmediata.",
}


class DTCDatabase:

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            # dtc_codes may have composite PK (code, source) if migrated, or old single PK
            con.execute("""
                CREATE TABLE IF NOT EXISTS dtc_codes (
                    code     TEXT NOT NULL,
                    description TEXT,
                    system   TEXT,
                    severity TEXT,
                    source   TEXT NOT NULL DEFAULT 'SAE J2012',
                    PRIMARY KEY (code, source)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS oem_desc (
                    code TEXT,
                    make TEXT,
                    description TEXT,
                    fix_hint TEXT,
                    PRIMARY KEY (code, make)
                )
            """)
            existing = con.execute("SELECT COUNT(*) FROM dtc_codes").fetchone()[0]
            if existing == 0:
                con.executemany(
                    "INSERT OR IGNORE INTO dtc_codes (code,description,system,severity,source) VALUES (?,?,?,?,?)",
                    [(code, desc, system, sev, "SAE J2012") for code, (desc, system, sev) in GENERIC_DTCS.items()]
                )

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def lookup(self, code: str, make: str = "") -> dict:
        code = code.upper().strip()
        with self._conn() as con:
            if make:
                row = con.execute(
                    "SELECT description, fix_hint FROM oem_desc WHERE code=? AND make=?",
                    (code, make.upper())
                ).fetchone()
                if row:
                    return {"code": code, "description": row[0], "fix_hint": row[1], "source": "oem"}
                # Also check dtc_codes with OEM source
                row = con.execute(
                    "SELECT description, system, severity, source FROM dtc_codes "
                    "WHERE code=? AND LOWER(source) LIKE ?",
                    (code, f"%{make.lower()}%")
                ).fetchone()
                if row:
                    return {
                        "code": code, "description": row[0], "system": row[1],
                        "severity": row[2], "suggested_action": SUGGESTIONS.get(row[2], ""),
                        "source": row[3],
                    }
            # Generic SAE lookup — return all matches, prefer SAE J2012
            rows = con.execute(
                "SELECT description, system, severity, source FROM dtc_codes WHERE code=? ORDER BY source",
                (code,)
            ).fetchall()
            if rows:
                # Prefer SAE J2012 generic entry
                sae = next((r for r in rows if "SAE" in (r[3] or "")), rows[0])
                return {
                    "code": code, "description": sae[0], "system": sae[1],
                    "severity": sae[2], "suggested_action": SUGGESTIONS.get(sae[2], ""),
                    "source": sae[3],
                    "oem_variants": len(rows) - 1,
                }
        return {"code": code, "description": "Codigo desconocido", "severity": "info", "source": "unknown"}

    def add_oem(self, code: str, make: str, description: str, fix_hint: str = ""):
        with self._conn() as con:
            con.execute(
                "INSERT OR REPLACE INTO oem_desc VALUES (?,?,?,?)",
                (code.upper(), make.upper(), description, fix_hint)
            )

    def search(self, query: str, make: str = "") -> list[dict]:
        q = f"%{query.upper()}%"
        with self._conn() as con:
            if make:
                rows = con.execute(
                    "SELECT code, description, system, severity, source FROM dtc_codes "
                    "WHERE (code LIKE ? OR description LIKE ?) AND LOWER(source) LIKE ?",
                    (q, q, f"%{make.lower()}%")
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT code, description, system, severity, source FROM dtc_codes "
                    "WHERE code LIKE ? OR description LIKE ?",
                    (q, q)
                ).fetchall()
        return [{"code": r[0], "description": r[1], "system": r[2], "severity": r[3], "source": r[4]} for r in rows]

    # ── ECU repair knowledge (from Guia Completo de Reparo de ECUs) ──────────

    def search_ecu_faults(self, make: str = "", keyword: str = "") -> list[dict]:
        """Search ECU repair knowledge by vehicle make and/or symptom keyword."""
        with self._conn() as con:
            if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ecu_faults'").fetchone():
                return []
            clauses, params = [], []
            if make:
                clauses.append("LOWER(m.make) LIKE ?")
                params.append(f"%{make.lower()}%")
            if keyword:
                clauses.append("(LOWER(f.symptom) LIKE ? OR LOWER(f.solution) LIKE ?)")
                params += [f"%{keyword.lower()}%"] * 2
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = con.execute(f"""
                SELECT m.ecu_code, m.make, f.symptom, f.solution, f.page_ref
                FROM ecu_faults f JOIN ecu_models m ON f.ecu_id = m.id
                {where}
                ORDER BY m.make, m.ecu_code
                LIMIT 50
            """, params).fetchall()
        return [{"ecu": r[0], "make": r[1], "symptom": r[2], "solution": r[3], "page": r[4]} for r in rows]

    def get_ecu_components(self, ecu_code: str) -> list[dict]:
        """Return components/pinout for a given ECU module code."""
        with self._conn() as con:
            if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ecu_components'").fetchone():
                return []
            rows = con.execute("""
                SELECT c.pin_number, c.description
                FROM ecu_components c JOIN ecu_models m ON c.ecu_id = m.id
                WHERE LOWER(m.ecu_code) LIKE ?
                ORDER BY CAST(c.pin_number AS INTEGER)
            """, (f"%{ecu_code.lower()}%",)).fetchall()
        return [{"pin": r[0], "description": r[1]} for r in rows]

    def ecu_stats(self) -> dict:
        """Summary counts of indexed ECU knowledge."""
        with self._conn() as con:
            tbls = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "ecu_models" not in tbls:
                return {}
            models = con.execute("SELECT COUNT(*) FROM ecu_models").fetchone()[0]
            faults = con.execute("SELECT COUNT(*) FROM ecu_faults").fetchone()[0]
            comps  = con.execute("SELECT COUNT(*) FROM ecu_components").fetchone()[0]
            by_make = {r[0]: r[1] for r in con.execute(
                "SELECT make, COUNT(*) FROM ecu_models GROUP BY make ORDER BY COUNT(*) DESC"
            ).fetchall()}
        return {"models": models, "faults": faults, "components": comps, "by_make": by_make}
