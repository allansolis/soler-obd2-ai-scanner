"""
SOLER OBD2 AI Scanner - Knowledge Hub
======================================
Hub central de conocimiento automotriz. Compila e indexa TODOS los
recursos disponibles (Drive, PDFs locales, DTCs, vehiculos, mapas
de tuning, software profesional) en una unica base de datos SQLite
busqueable, sirviendo de cerebro al asistente de IA.
"""

from backend.knowledge_hub.hub import KnowledgeHub, CompileStats, HubStats
from backend.knowledge_hub.expert_advisor import (
    ExpertAdvisor,
    ToolRecommendation,
    Workflow,
    WorkflowStep,
    ComparisonMatrix,
    get_advisor,
)
from backend.knowledge_hub.schema import (
    Base,
    Resource,
    SoftwareTool,
    VehicleProfile,
    DTCCatalog,
    DiagramReference,
    RepairProcedure,
)

__all__ = [
    "KnowledgeHub",
    "CompileStats",
    "HubStats",
    "Base",
    "Resource",
    "SoftwareTool",
    "VehicleProfile",
    "DTCCatalog",
    "DiagramReference",
    "RepairProcedure",
    "ExpertAdvisor",
    "ToolRecommendation",
    "Workflow",
    "WorkflowStep",
    "ComparisonMatrix",
    "get_advisor",
]
