"""
SOLER OBD2 AI Scanner - Guia profesional de reparacion por DTC
===============================================================
Integra la base de datos profesional con sintomas, diagnostico tecnico,
soluciones verificadas y estimaciones de costo/tiempo por codigo.

Basado en experiencia real de taller + comunidad profesional automotriz.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DTCRepairGuide:
    """Guia completa de reparacion para un DTC especifico."""
    code: str
    system: str
    severity: str  # critical, high, medium, low
    description: str
    symptoms: list[str] = field(default_factory=list)
    technical_diagnosis: str = ""
    real_solution: str = ""
    probable_causes: list[str] = field(default_factory=list)
    tools_needed: list[str] = field(default_factory=list)
    estimated_time_hours: float = 1.0
    estimated_cost_parts_min: float = 0
    estimated_cost_parts_max: float = 0
    estimated_cost_labor: float = 0

    @property
    def total_cost_min(self) -> float:
        return self.estimated_cost_parts_min + self.estimated_cost_labor

    @property
    def total_cost_max(self) -> float:
        return self.estimated_cost_parts_max + self.estimated_cost_labor

    def to_spanish_report(self) -> str:
        """Genera reporte completo en espanol para mostrar al usuario."""
        lines = [
            f"DTC: {self.code} — {self.description}",
            f"Sistema: {self.system}  |  Severidad: {self.severity.upper()}",
            "",
            "SINTOMAS:",
        ]
        for s in self.symptoms:
            lines.append(f"  • {s}")
        lines.extend([
            "",
            "DIAGNOSTICO TECNICO:",
            f"  {self.technical_diagnosis}",
            "",
            "CAUSAS PROBABLES (ordenadas por probabilidad):",
        ])
        for i, cause in enumerate(self.probable_causes, 1):
            lines.append(f"  {i}. {cause}")
        lines.extend([
            "",
            "SOLUCION REAL:",
            f"  {self.real_solution}",
            "",
            "HERRAMIENTAS NECESARIAS:",
        ])
        for t in self.tools_needed:
            lines.append(f"  • {t}")
        lines.extend([
            "",
            f"TIEMPO ESTIMADO: {self.estimated_time_hours} horas",
            f"COSTO ESTIMADO: ${self.total_cost_min:.0f} - ${self.total_cost_max:.0f} USD",
            f"  (partes: ${self.estimated_cost_parts_min}-${self.estimated_cost_parts_max} + mano de obra: ${self.estimated_cost_labor})",
        ])
        return "\n".join(lines)


class DTCRepairDatabase:
    """Base de datos profesional de guias de reparacion por DTC."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or Path("data/dtc_database/professional_dtc_database.json")
        self._guides: dict[str, DTCRepairGuide] = {}
        self._load()

    def _load(self) -> None:
        """Carga la base de datos desde JSON."""
        if not self.db_path.exists():
            return
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for entry in data.get("dtcs", []):
            cost = entry.get("estimated_cost_usd", {})
            guide = DTCRepairGuide(
                code=entry["code"],
                system=entry["system"],
                severity=entry["severity"],
                description=entry["description"],
                symptoms=entry.get("symptoms", []),
                technical_diagnosis=entry.get("technical_diagnosis", ""),
                real_solution=entry.get("real_solution", ""),
                probable_causes=entry.get("probable_causes", []),
                tools_needed=entry.get("tools_needed", []),
                estimated_time_hours=entry.get("estimated_time_hours", 1.0),
                estimated_cost_parts_min=cost.get("parts_min", 0),
                estimated_cost_parts_max=cost.get("parts_max", 0),
                estimated_cost_labor=cost.get("labor", 0),
            )
            self._guides[guide.code] = guide

    def get_guide(self, code: str) -> Optional[DTCRepairGuide]:
        """Obtiene la guia de reparacion para un DTC."""
        return self._guides.get(code.upper())

    def get_all_codes(self) -> list[str]:
        """Lista todos los codigos en la base."""
        return sorted(self._guides.keys())

    def search(self, query: str) -> list[DTCRepairGuide]:
        """Busqueda por texto en descripcion o sintomas."""
        q = query.lower()
        results = []
        for guide in self._guides.values():
            text = " ".join([
                guide.description,
                " ".join(guide.symptoms),
                guide.technical_diagnosis,
                " ".join(guide.probable_causes),
            ]).lower()
            if q in text:
                results.append(guide)
        return results

    def filter_by_severity(self, severity: str) -> list[DTCRepairGuide]:
        """Filtra por nivel de severidad."""
        return [g for g in self._guides.values() if g.severity == severity]

    def get_critical_codes(self) -> list[str]:
        """Codigos que requieren atencion inmediata."""
        return [
            code for code, g in self._guides.items()
            if g.severity in ("critical", "high")
        ]


# Singleton para uso desde el orchestrator
_repair_db: Optional[DTCRepairDatabase] = None


def get_repair_database() -> DTCRepairDatabase:
    """Obtiene la instancia singleton de la base de reparaciones."""
    global _repair_db
    if _repair_db is None:
        _repair_db = DTCRepairDatabase()
    return _repair_db


__all__ = [
    "DTCRepairGuide",
    "DTCRepairDatabase",
    "get_repair_database",
]
