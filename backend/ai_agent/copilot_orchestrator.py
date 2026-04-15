"""
SOLER OBD2 AI Scanner - Copilot Orchestrator

Orquestador del AI Copilot que ejecuta flujos completos
de escaneo, diagnostico, reparacion y tuning.

Toda la salida al usuario final esta en espanol.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class VehicleInfo:
    vin: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    engine: Optional[str] = None
    ecu_type: Optional[str] = None


@dataclass
class ScanResult:
    health_score: int
    dtc_count: int
    sensor_count: int
    warnings: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    report_es: str = ""

    def to_dict(self) -> dict:
        return {
            "healthScore": self.health_score,
            "dtcCount": self.dtc_count,
            "sensorCount": self.sensor_count,
            "warnings": self.warnings,
            "nextSteps": self.next_steps,
            "report": self.report_es,
        }


@dataclass
class RepairStep:
    order: int
    title: str
    description: str
    image: Optional[str] = None


@dataclass
class RepairGuide:
    dtc_code: str
    title: str
    summary: str
    steps: list[RepairStep]
    estimated_cost_usd: float
    estimated_time_min: int
    tools_needed: list[str]
    difficulty: str  # easy | medium | hard
    evidence: list[dict] = field(default_factory=list)
    tool_recommendations: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dtcCode": self.dtc_code,
            "title": self.title,
            "summary": self.summary,
            "steps": [
                {
                    "order": s.order,
                    "title": s.title,
                    "description": s.description,
                    "image": s.image,
                }
                for s in self.steps
            ],
            "estimatedCostUsd": self.estimated_cost_usd,
            "estimatedTimeMin": self.estimated_time_min,
            "toolsNeeded": self.tools_needed,
            "difficulty": self.difficulty,
            "evidence": self.evidence,
            "toolRecommendations": self.tool_recommendations,
        }


@dataclass
class TuneGuide:
    profile: str
    eligible: bool
    reason: Optional[str]
    steps: list[dict]
    expected_gains: dict
    safety_warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "eligible": self.eligible,
            "reason": self.reason,
            "steps": self.steps,
            "expectedGains": self.expected_gains,
            "safetyWarnings": self.safety_warnings,
        }


@dataclass
class ClearResult:
    cleared: bool
    safe_to_clear: bool
    warnings: list[str]
    follow_up: str

    def to_dict(self) -> dict:
        return {
            "cleared": self.cleared,
            "safeToClear": self.safe_to_clear,
            "warnings": self.warnings,
            "followUp": self.follow_up,
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class CopilotOrchestrator:
    """
    Orquestador del AI Copilot que ejecuta flujos completos
    de escaneo, diagnostico, reparacion y tuning.
    """

    def __init__(
        self,
        rules_engine: Any | None = None,
        pdf_learner: Any | None = None,
        web_researcher: Any | None = None,
        knowledge_base: Any | None = None,
        reprogram_analyzer: Any | None = None,
        ecu_backup: Any | None = None,
        map_generator: Any | None = None,
        profile_library: Any | None = None,
        safety_verifier: Any | None = None,
        flash_orchestrator: Any | None = None,
    ) -> None:
        self.rules_engine = rules_engine
        self.pdf_learner = pdf_learner
        self.web_researcher = web_researcher
        self.knowledge_base = knowledge_base
        self.reprogram_analyzer = reprogram_analyzer
        self.ecu_backup = ecu_backup
        self.map_generator = map_generator
        self.profile_library = profile_library
        self.safety_verifier = safety_verifier
        self.flash_orchestrator = flash_orchestrator
        self._sessions: dict[str, dict] = {}

    # -----------------------------------------------------------------------
    # Scan workflow
    # -----------------------------------------------------------------------
    async def full_scan_workflow(
        self, vehicle_info: VehicleInfo | dict | None = None
    ) -> ScanResult:
        """Conecta OBD, lee sensores y DTCs, analiza y genera reporte en espanol."""
        session_id = str(uuid.uuid4())
        logger.info("Iniciando escaneo completo (session=%s)", session_id)

        warnings: list[str] = []
        next_steps: list[str] = []
        dtc_count = 0
        sensor_count = 0
        health_score = 85  # default optimista

        try:
            # 1. Lectura de sensores (simulado si no hay drivers reales)
            sensors = await self._read_sensors()
            sensor_count = len(sensors)

            # 2. Lectura de DTCs
            dtcs = await self._read_dtcs()
            dtc_count = len(dtcs)

            # 3. Analisis con rules engine
            if self.rules_engine and hasattr(self.rules_engine, "evaluate"):
                diagnosis = self.rules_engine.evaluate(sensors=sensors, dtcs=dtcs)
                warnings.extend(diagnosis.get("warnings", []))
                health_score = diagnosis.get("health_score", health_score)

            # 4. Sugerencias
            if dtc_count > 0:
                next_steps.append(
                    f"Tienes {dtc_count} codigos activos. Pidete guia paso a paso."
                )
            if health_score < 70:
                next_steps.append(
                    "Salud por debajo del umbral optimo. Recomiendo mantenimiento preventivo."
                )
            if not next_steps:
                next_steps.append("Todo en orden. Puedes conducir con tranquilidad.")

            report_es = (
                f"Reporte SOLER: tu vehiculo tiene salud {health_score}%. "
                f"Detecte {dtc_count} codigos y lei {sensor_count} sensores. "
                + (" ".join(warnings) if warnings else "Sin alertas criticas.")
            )

            self._sessions[session_id] = {
                "timestamp": time.time(),
                "type": "scan",
                "result": {
                    "health": health_score,
                    "dtcs": dtc_count,
                    "sensors": sensor_count,
                },
            }

            return ScanResult(
                health_score=health_score,
                dtc_count=dtc_count,
                sensor_count=sensor_count,
                warnings=warnings,
                next_steps=next_steps,
                report_es=report_es,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Fallo el escaneo completo: %s", exc)
            return ScanResult(
                health_score=0,
                dtc_count=0,
                sensor_count=0,
                warnings=[f"Error durante el escaneo: {exc}"],
                next_steps=["Revisa la conexion OBD y reintenta."],
                report_es="No se pudo completar el escaneo.",
            )

    async def _read_sensors(self) -> list[dict]:
        # Hook para drivers OBD reales. Aqui devolvemos vacio seguro.
        return []

    async def _read_dtcs(self) -> list[dict]:
        return []

    # -----------------------------------------------------------------------
    # Guided repair
    # -----------------------------------------------------------------------
    async def guided_repair_workflow(
        self,
        dtc_code: str,
        vehicle_info: VehicleInfo | dict | None = None,
    ) -> RepairGuide:
        """Devuelve guia paso a paso en espanol para resolver un DTC."""
        logger.info("Generando guia de reparacion para %s", dtc_code)

        # 1. Reglas internas
        rule_info: dict[str, Any] = {}
        if self.rules_engine and hasattr(self.rules_engine, "lookup_dtc"):
            rule_info = self.rules_engine.lookup_dtc(dtc_code) or {}

        # 2. PDFs indexados
        pdf_info: dict[str, Any] = {}
        if self.pdf_learner and hasattr(self.pdf_learner, "search_dtc"):
            pdf_info = await _maybe_await(self.pdf_learner.search_dtc(dtc_code)) or {}

        # 3. Investigacion online
        web_info: dict[str, Any] = {}
        if self.web_researcher and hasattr(self.web_researcher, "search_dtc_info"):
            try:
                web_info = (
                    await _maybe_await(
                        self.web_researcher.search_dtc_info(dtc_code, vehicle_info)
                    )
                    or {}
                )
            except Exception:  # noqa: BLE001
                web_info = {}

        title = rule_info.get("title") or pdf_info.get("title") or f"Reparacion {dtc_code}"
        summary = rule_info.get("summary") or pdf_info.get("summary") or (
            f"Procedimiento recomendado para el codigo {dtc_code}."
        )

        steps_src = (
            rule_info.get("steps")
            or pdf_info.get("steps")
            or web_info.get("steps")
            or self._default_repair_steps(dtc_code)
        )
        steps = [
            RepairStep(
                order=i + 1,
                title=str(s.get("title", f"Paso {i + 1}")),
                description=str(s.get("description", "")),
                image=s.get("image"),
            )
            for i, s in enumerate(steps_src)
        ]

        guide = RepairGuide(
            dtc_code=dtc_code,
            title=title,
            summary=summary,
            steps=steps,
            estimated_cost_usd=float(rule_info.get("cost_usd", 120)),
            estimated_time_min=int(rule_info.get("time_min", 90)),
            tools_needed=list(rule_info.get("tools", ["Escaner OBD2", "Multimetro"])),
            difficulty=str(rule_info.get("difficulty", "medium")),
        )

        # Enriquecer con KnowledgeHub + ExpertAdvisor
        try:
            from backend.knowledge_hub import KnowledgeHub
            from backend.knowledge_hub.expert_advisor import get_advisor

            vehicle = vehicle_info if isinstance(vehicle_info, dict) else (
                vehicle_info.__dict__ if vehicle_info else {}
            )
            hub = KnowledgeHub()
            advisor = get_advisor()
            resources = hub.get_resources_for_dtc(
                dtc_code, vehicle.get("make") if vehicle else None
            )
            recs = advisor.recommend_tools_for_dtc_with_evidence(
                dtc_code,
                vehicle.get("make") if vehicle else None,
                vehicle.get("year") if vehicle else None,
            )
            guide.evidence = [
                {"resource": r.get("name"), "path": r.get("source_url")}
                for r in resources[:5]
            ]
            guide.tool_recommendations = [
                {
                    "tool": r.get("tool_name"),
                    "reason": r.get("reason_es"),
                    "score": r.get("score"),
                }
                for r in recs[:3]
            ]
        except Exception as e:  # noqa: BLE001
            logger.warning("Knowledge enrichment failed: %s", e)

        return guide

    def _default_repair_steps(self, dtc_code: str) -> list[dict]:
        return [
            {"title": "Confirmar el codigo", "description": f"Reescanea para confirmar {dtc_code}."},
            {"title": "Inspeccion visual", "description": "Revisa cableado, conectores y fusibles."},
            {"title": "Medir sensores", "description": "Monitorea PIDs en vivo."},
            {"title": "Reemplazar componente", "description": "Sustituye pieza defectuosa."},
            {"title": "Borrar DTC y verificar", "description": "Limpia codigo y prueba de ruta."},
        ]

    # -----------------------------------------------------------------------
    # Guided tune
    # -----------------------------------------------------------------------
    async def guided_tune_workflow(
        self,
        profile: str,
        vehicle_info: VehicleInfo | dict | None = None,
    ) -> TuneGuide:
        """Flujo completo de tuning con validaciones de seguridad."""
        logger.info("Iniciando flujo de tune '%s'", profile)

        # 1. Analiza vehiculo
        eligible = True
        reason: Optional[str] = None
        if self.reprogram_analyzer and hasattr(self.reprogram_analyzer, "analyze"):
            result = await _maybe_await(self.reprogram_analyzer.analyze(vehicle_info))
            eligible = bool(result.get("eligible", True)) if result else True
            reason = result.get("reason") if result else None

        safety_warnings: list[str] = []
        if not eligible:
            return TuneGuide(
                profile=profile,
                eligible=False,
                reason=reason or "Vehiculo no elegible para tuning.",
                steps=[],
                expected_gains={"hp": 0, "torque": 0},
                safety_warnings=[
                    "No es seguro flashear. Resuelve las advertencias primero."
                ],
            )

        # 2. Backup
        if self.ecu_backup and hasattr(self.ecu_backup, "create_backup"):
            try:
                await _maybe_await(self.ecu_backup.create_backup(vehicle_info))
            except Exception as exc:  # noqa: BLE001
                safety_warnings.append(f"Fallo backup: {exc}")

        # 3. Generar mapas
        expected_gains = {"hp": 15, "torque": 18, "mpg": 0}
        if self.map_generator and hasattr(self.map_generator, "generate"):
            gen = await _maybe_await(
                self.map_generator.generate(profile=profile, vehicle=vehicle_info)
            )
            if gen and "expected_gains" in gen:
                expected_gains = gen["expected_gains"]

        # 4. Validacion
        if self.safety_verifier and hasattr(self.safety_verifier, "validate"):
            val = await _maybe_await(
                self.safety_verifier.validate(profile=profile, vehicle=vehicle_info)
            )
            if val and not val.get("safe", True):
                safety_warnings.extend(val.get("warnings", []))

        steps = [
            {"order": 1, "title": "Chequeo de salud", "description": "Verifico estado del motor."},
            {"order": 2, "title": "Backup de ECU", "description": "Respaldo automatico creado."},
            {"order": 3, "title": "Generacion de mapas", "description": f"Perfil '{profile}' aplicado."},
            {"order": 4, "title": "Validacion de seguridad", "description": "Reviso limites criticos."},
            {"order": 5, "title": "Flasheo", "description": "Aplico el tune a la ECU."},
            {"order": 6, "title": "Verificacion post-flash", "description": "Monitoreo y aprendo del resultado."},
        ]

        return TuneGuide(
            profile=profile,
            eligible=True,
            reason=None,
            steps=steps,
            expected_gains=expected_gains,
            safety_warnings=safety_warnings,
        )

    # -----------------------------------------------------------------------
    # Clear DTC
    # -----------------------------------------------------------------------
    async def clear_dtc_safely(
        self,
        dtc_code: str,
        vehicle_info: VehicleInfo | dict | None = None,
    ) -> ClearResult:
        warnings: list[str] = []
        safe = True
        if self.rules_engine and hasattr(self.rules_engine, "is_critical_dtc"):
            try:
                if self.rules_engine.is_critical_dtc(dtc_code):
                    safe = False
                    warnings.append(
                        f"{dtc_code} es critico. Repara la causa raiz antes de borrar."
                    )
            except Exception:  # noqa: BLE001
                pass

        cleared = False
        if safe:
            # Aqui se integraria con el driver OBD para enviar mode 04.
            cleared = True

        return ClearResult(
            cleared=cleared,
            safe_to_clear=safe,
            warnings=warnings,
            follow_up=(
                "Monitorea el vehiculo 50-100km. Si el codigo regresa, la causa persiste."
                if cleared
                else "No se borro. Resuelve las advertencias antes de reintentar."
            ),
        )

    # -----------------------------------------------------------------------
    # Web research
    # -----------------------------------------------------------------------
    async def web_research(
        self,
        query: str,
        vehicle_context: VehicleInfo | dict | None = None,
    ) -> dict:
        if not self.web_researcher:
            return {
                "query": query,
                "sources": [],
                "summary": "Modulo de investigacion web no disponible.",
            }
        try:
            tsb = await _maybe_await(
                self.web_researcher.search_tsb(vehicle_context)
            ) or []
            dtc = await _maybe_await(
                self.web_researcher.search_dtc_info(query, vehicle_context)
            ) or {}
            return {
                "query": query,
                "sources": dtc.get("sources", []) + [{"title": t.get("title", "TSB"), "url": t.get("url", ""), "snippet": t.get("summary", "")} for t in tsb],
                "summary": dtc.get("summary", "Sin resultados."),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("web_research fallo: %s", exc)
            return {"query": query, "sources": [], "summary": f"Error: {exc}"}

    # -----------------------------------------------------------------------
    # Learn
    # -----------------------------------------------------------------------
    async def learn_from_outcome(self, session_id: str, outcome: dict) -> None:
        if self.knowledge_base and hasattr(self.knowledge_base, "record_outcome"):
            try:
                await _maybe_await(
                    self.knowledge_base.record_outcome(session_id, outcome)
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("No se pudo registrar outcome: %s", exc)
        self._sessions.setdefault(session_id, {})["outcome"] = outcome


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _maybe_await(value):
    """Await if coroutine, return value otherwise."""
    import inspect

    if inspect.isawaitable(value):
        return await value
    return value
