"""
SOLER OBD2 AI Scanner - Modulo de Agente IA
=============================================
Sistema de diagnostico vehicular inteligente con motor de reglas,
correlacion multi-sensor, base de conocimiento auto-mejorable
y prediccion de fallas.

Uso basico:
    from backend.ai_agent import AIAgent

    agent = AIAgent()
    report = await agent.diagnose(sensor_data, dtcs)
"""

from __future__ import annotations

from typing import Any, Optional

from .analyzer import DiagnosticReport, VehicleAnalyzer
from .knowledge_base import KnowledgeBase, ScanRecord
from .predictor import FailurePredictor, PredictionReport
from .rules_engine import (
    DiagnosticRule,
    RuleResult,
    RulesEngine,
    Severity,
    VehicleSystem,
)

__all__ = [
    # Clases principales
    "AIAgent",
    "VehicleAnalyzer",
    "RulesEngine",
    "KnowledgeBase",
    "FailurePredictor",
    # Modelos de datos
    "DiagnosticReport",
    "PredictionReport",
    "DiagnosticRule",
    "RuleResult",
    "ScanRecord",
    # Enums
    "Severity",
    "VehicleSystem",
]


class AIAgent:
    """Agente de IA principal que coordina todos los subsistemas.

    Provee una interfaz unificada para diagnostico vehicular completo,
    incluyendo analisis, prediccion y aprendizaje continuo.

    Ejemplo:
        agent = AIAgent()
        report = await agent.diagnose(
            sensors={"coolant_temp": 115, "rpm": 800},
            dtcs=["P0217", "P0420"],
            vehicle_info={"make": "Toyota", "model": "Corolla", "year": 2019},
        )
        print(report.diagnosis_text)
    """

    def __init__(
        self,
        knowledge_base: Optional[KnowledgeBase] = None,
    ) -> None:
        self._rules_engine = RulesEngine()
        self._analyzer = VehicleAnalyzer(rules_engine=self._rules_engine)
        self._knowledge_base = knowledge_base or KnowledgeBase()
        self._predictor = FailurePredictor()

    @property
    def rules_engine(self) -> RulesEngine:
        """Motor de reglas de diagnostico."""
        return self._rules_engine

    @property
    def analyzer(self) -> VehicleAnalyzer:
        """Analizador multi-sensor."""
        return self._analyzer

    @property
    def knowledge_base(self) -> KnowledgeBase:
        """Base de conocimiento."""
        return self._knowledge_base

    @property
    def predictor(self) -> FailurePredictor:
        """Predictor de fallas."""
        return self._predictor

    async def diagnose(
        self,
        sensors: dict[str, Any],
        dtcs: Optional[list[str]] = None,
        vehicle_info: Optional[dict[str, str]] = None,
        mileage: Optional[int] = None,
    ) -> DiagnosticReport:
        """Realiza un diagnostico completo del vehiculo.

        Args:
            sensors: Diccionario de lecturas de sensores.
            dtcs: Lista de codigos DTC activos.
            vehicle_info: Informacion del vehiculo (make, model, year, engine).
            mileage: Kilometraje actual.

        Returns:
            DiagnosticReport con el diagnostico completo.
        """
        data: dict[str, Any] = {
            "sensors": sensors,
            "dtcs": dtcs or [],
        }

        # Cargar rangos personalizados del perfil del vehiculo si existe
        if vehicle_info:
            make = vehicle_info.get("make", "")
            model = vehicle_info.get("model", "")
            engine = vehicle_info.get("engine", "")

            if make and model:
                profile = await self._knowledge_base.get_vehicle_profile(
                    make, model, engine
                )
                if profile and profile.normal_ranges:
                    self._analyzer.update_normal_ranges(profile.normal_ranges)

        # Ejecutar analisis
        report = await self._analyzer.analyze(data, vehicle_info=vehicle_info)

        return report

    async def diagnose_and_learn(
        self,
        scan_id: str,
        sensors: dict[str, Any],
        dtcs: Optional[list[str]] = None,
        vehicle_info: Optional[dict[str, str]] = None,
        vehicle_vin: str = "",
        mileage: Optional[int] = None,
    ) -> DiagnosticReport:
        """Diagnostica y registra el escaneo para aprendizaje continuo.

        Args:
            scan_id: Identificador unico del escaneo.
            sensors: Diccionario de lecturas de sensores.
            dtcs: Lista de codigos DTC activos.
            vehicle_info: Informacion del vehiculo.
            vehicle_vin: VIN del vehiculo.
            mileage: Kilometraje actual.

        Returns:
            DiagnosticReport con el diagnostico completo.
        """
        report = await self.diagnose(sensors, dtcs, vehicle_info, mileage)

        # Registrar en la base de conocimiento
        info = vehicle_info or {}
        scan = ScanRecord(
            scan_id=scan_id,
            timestamp=report.timestamp.isoformat(),
            vehicle_vin=vehicle_vin,
            vehicle_make=info.get("make", ""),
            vehicle_model=info.get("model", ""),
            vehicle_year=int(info.get("year", 0)),
            vehicle_engine=info.get("engine", ""),
            sensors=sensors,
            dtcs=dtcs or [],
            diagnosis=report.diagnosis_text[:500],
            health_score=report.vehicle_health_score,
            triggered_rules=[r.rule_id for r in report.triggered_rules],
            root_causes=[rc.root_cause for rc in report.root_causes],
            mileage=mileage,
        )

        try:
            await self._knowledge_base.record_scan(scan)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Error registrando escaneo en knowledge base: %s", exc
            )

        return report

    async def predict_failures(
        self,
        sensor_history: list[dict[str, Any]],
        current_sensors: dict[str, Any],
        current_dtcs: Optional[list[str]] = None,
        vehicle_info: Optional[dict[str, Any]] = None,
        mileage: Optional[int] = None,
        last_service_km: Optional[int] = None,
    ) -> PredictionReport:
        """Predice fallas futuras basado en tendencias.

        Args:
            sensor_history: Historial de lecturas de sensores.
            current_sensors: Lecturas actuales de sensores.
            current_dtcs: DTCs actuales.
            vehicle_info: Informacion del vehiculo.
            mileage: Kilometraje actual.
            last_service_km: Kilometraje del ultimo servicio.

        Returns:
            PredictionReport con predicciones de fallas.
        """
        current_data = {
            "sensors": current_sensors,
            "dtcs": current_dtcs or [],
        }

        return await self._predictor.predict(
            sensor_history=sensor_history,
            current_data=current_data,
            vehicle_info=vehicle_info,
            mileage=mileage,
            last_service_km=last_service_km,
        )

    def close(self) -> None:
        """Cierra recursos (base de datos, etc.)."""
        self._knowledge_base.close()
