"""
SOLER OBD2 AI Scanner - Self-Improvement Engine

El agente AI aprende y mejora automaticamente con cada escaneo,
diagnostico, reparacion y tune.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class NewPattern:
    pattern_id: str
    description: str
    confidence: float
    supporting_samples: int

    def to_dict(self) -> dict:
        return {
            "patternId": self.pattern_id,
            "description": self.description,
            "confidence": self.confidence,
            "supportingSamples": self.supporting_samples,
        }


@dataclass
class Report:
    period_start: float
    period_end: float
    new_patterns: list[NewPattern]
    threshold_updates: list[dict]
    summary_es: str

    def to_dict(self) -> dict:
        return {
            "periodStart": self.period_start,
            "periodEnd": self.period_end,
            "newPatterns": [p.to_dict() for p in self.new_patterns],
            "thresholdUpdates": self.threshold_updates,
            "summary": self.summary_es,
        }


@dataclass
class Proposal:
    proposal_id: str
    title: str
    rationale: str
    priority: str  # low|medium|high

    def to_dict(self) -> dict:
        return {
            "proposalId": self.proposal_id,
            "title": self.title,
            "rationale": self.rationale,
            "priority": self.priority,
        }


class SelfImprovementEngine:
    """
    El agente AI aprende y mejora automaticamente con cada escaneo,
    diagnostico, reparacion y tune.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or Path("data/ai_learning.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS scan_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS repair_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dtc_code TEXT NOT NULL,
                    action TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tune_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile TEXT NOT NULL,
                    before TEXT NOT NULL,
                    after TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS thresholds (
                    key TEXT PRIMARY KEY,
                    value REAL NOT NULL,
                    samples INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS patterns (
                    pattern_id TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    samples INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )
            conn.commit()

    # -----------------------------------------------------------------------
    # Recording
    # -----------------------------------------------------------------------
    async def record_scan_outcome(self, scan_data: dict, outcome: dict) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO scan_outcomes(data, outcome, created_at) VALUES(?,?,?)",
                (json.dumps(scan_data), json.dumps(outcome), time.time()),
            )
            conn.commit()

    async def record_repair_success(
        self, dtc_code: str, repair_action: str, success: bool
    ) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO repair_outcomes(dtc_code, action, success, created_at) VALUES(?,?,?,?)",
                (dtc_code, repair_action, 1 if success else 0, time.time()),
            )
            conn.commit()

    async def record_tune_result(
        self, tune_profile: str, before: dict, after: dict
    ) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO tune_outcomes(profile, before, after, created_at) VALUES(?,?,?,?)",
                (tune_profile, json.dumps(before), json.dumps(after), time.time()),
            )
            conn.commit()

    # -----------------------------------------------------------------------
    # Discovery
    # -----------------------------------------------------------------------
    async def discover_new_pattern(self) -> list[NewPattern]:
        """
        Mina datos historicos en busca de correlaciones (dtc -> accion exitosa).
        Devuelve solo patrones con >=3 muestras y >=70% exito.
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT dtc_code, action, "
                "       COUNT(*) as total, "
                "       SUM(success) as wins "
                "FROM repair_outcomes "
                "GROUP BY dtc_code, action "
                "HAVING total >= 3"
            ).fetchall()

        patterns: list[NewPattern] = []
        for dtc, action, total, wins in rows:
            confidence = (wins or 0) / total if total else 0.0
            if confidence >= 0.7:
                pid = f"{dtc}:{action}"[:128]
                patterns.append(
                    NewPattern(
                        pattern_id=pid,
                        description=(
                            f"{dtc} se resuelve con '{action}' "
                            f"en {int(confidence*100)}% de los casos."
                        ),
                        confidence=confidence,
                        supporting_samples=total,
                    )
                )
                with sqlite3.connect(str(self.db_path)) as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO patterns(pattern_id, description, confidence, samples, created_at) "
                        "VALUES(?,?,?,?,?)",
                        (pid, patterns[-1].description, confidence, total, time.time()),
                    )
                    conn.commit()
        return patterns

    # -----------------------------------------------------------------------
    # Thresholds
    # -----------------------------------------------------------------------
    async def update_thresholds(self) -> None:
        """
        Ajusta umbrales dinamicamente segun datos acumulados.
        Placeholder: mantiene entradas por sensor/vehiculo.
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM scan_outcomes"
            ).fetchone()
            samples = row[0] if row else 0
            if samples > 0:
                conn.execute(
                    "INSERT OR REPLACE INTO thresholds(key, value, samples, updated_at) "
                    "VALUES(?,?,?,?)",
                    ("global.health.baseline", 80.0, samples, time.time()),
                )
                conn.commit()

    # -----------------------------------------------------------------------
    # Reports
    # -----------------------------------------------------------------------
    async def generate_weekly_report(self) -> Report:
        end = time.time()
        start = end - 7 * 24 * 3600
        patterns = await self.discover_new_pattern()
        with sqlite3.connect(str(self.db_path)) as conn:
            updates = conn.execute(
                "SELECT key, value, samples, updated_at FROM thresholds WHERE updated_at >= ?",
                (start,),
            ).fetchall()
        threshold_updates = [
            {"key": k, "value": v, "samples": s, "updatedAt": u}
            for (k, v, s, u) in updates
        ]

        if patterns:
            top = patterns[0]
            summary = (
                f"Esta semana aprendi {len(patterns)} patrones nuevos. "
                f"Destacado: {top.description}"
            )
        else:
            summary = "Esta semana no detecte nuevos patrones con suficiente evidencia."

        return Report(
            period_start=start,
            period_end=end,
            new_patterns=patterns,
            threshold_updates=threshold_updates,
            summary_es=summary,
        )

    # -----------------------------------------------------------------------
    # Proposals
    # -----------------------------------------------------------------------
    async def propose_new_functionality(self) -> list[Proposal]:
        """
        Analiza lagunas en la base de conocimiento y propone nuevas skills.
        Heuristica simple: muchos DTCs con baja tasa de exito => proponer skill.
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT dtc_code, COUNT(*) AS total, SUM(success) AS wins "
                "FROM repair_outcomes GROUP BY dtc_code HAVING total >= 5"
            ).fetchall()

        proposals: list[Proposal] = []
        for dtc, total, wins in rows:
            rate = (wins or 0) / total if total else 0.0
            if rate < 0.4:
                pid = f"skill:{dtc}"
                proposals.append(
                    Proposal(
                        proposal_id=pid,
                        title=f"Nueva skill de diagnostico profundo para {dtc}",
                        rationale=(
                            f"Los usuarios resuelven {dtc} solo el {int(rate*100)}% de las veces "
                            f"(de {total} intentos). Sugiero una skill dedicada con arbol "
                            f"de decision detallado."
                        ),
                        priority="high" if total >= 10 else "medium",
                    )
                )
                with sqlite3.connect(str(self.db_path)) as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO proposals(proposal_id, title, rationale, priority, created_at) "
                        "VALUES(?,?,?,?,?)",
                        (
                            pid,
                            proposals[-1].title,
                            proposals[-1].rationale,
                            proposals[-1].priority,
                            time.time(),
                        ),
                    )
                    conn.commit()
        return proposals

    # -----------------------------------------------------------------------
    # Stats
    # -----------------------------------------------------------------------
    def get_stats(self) -> dict:
        with sqlite3.connect(str(self.db_path)) as conn:
            scans = conn.execute("SELECT COUNT(*) FROM scan_outcomes").fetchone()[0]
            repairs = conn.execute("SELECT COUNT(*) FROM repair_outcomes").fetchone()[0]
            tunes = conn.execute("SELECT COUNT(*) FROM tune_outcomes").fetchone()[0]
            patterns = conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
        return {
            "scans": scans,
            "repairs": repairs,
            "tunes": tunes,
            "lessonsLearned": patterns,
        }
