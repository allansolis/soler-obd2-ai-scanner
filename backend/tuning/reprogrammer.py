"""
SOLER OBD2 AI Scanner - ECU Reprogramming Engine
=================================================
El modulo mas critico del sistema. Orquesta el flujo completo de
reprogramacion de ECU con maxima seguridad:

    1. Backup triple (local + timestamp + hash SHA-256)
    2. Analisis AI del vehiculo (salud, elegibilidad, potencial)
    3. Optimizacion de mapas (economia / stage1 / sport / stage2 / diesel)
    4. Verificacion de seguridad (limites duros)
    5. Flasheo con red de seguridad (rollback automatico)
    6. Verificacion post-flash y aprendizaje

REGLA DE ORO: NUNCA se modifica una ECU sin backup previo verificado.
Toda interaccion con el usuario es en espanol.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Union

import numpy as np

from backend.config import settings
from backend.tuning.map_generator import (
    ECUMap,
    ECUMapSet,
    ECUMapGenerator,
    LaunchControlSettings,
    RevLimiterSettings,
)
from backend.tuning.profiles import (
    ProfileLibrary,
    ProfileName,
    ProfileSpec,
    TuningProfile,
)
from backend.tuning.safety import (
    CheckStatus,
    SafetyLimits,
    SafetyReport,
    SafetyVerifier,
)
from backend.tuning.simulator import PerformanceSimulator, SimulationResult


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
BACKUP_ROOT: Path = Path(
    getattr(settings, "backup_root", None)
    or (_PROJECT_DIR / "data" / "backups")
)
SESSIONS_ROOT: Path = _PROJECT_DIR / "data" / "reprogramming_sessions"

# Minimum vehicle health score to allow tuning (%)
MIN_HEALTH_SCORE: float = 80.0

# Timeout for idle stability check (seconds)
IDLE_STABILITY_SEC: float = 60.0

# Critical DTC prefixes that always block tuning
_CRITICAL_DTC_PREFIXES = (
    "P0016", "P0017", "P0018", "P0019",  # cam/crank correlation
    "P0300", "P0301", "P0302", "P0303",  # misfire
    "P0304", "P0305", "P0306", "P0307", "P0308",
    "P0325", "P0326", "P0327", "P0328",  # knock sensor
    "P0335",                               # crank position
    "P0606",                               # PCM internal fault
    "P0217",                               # engine overheat
    "P0128",                               # coolant below temp
    "P0087", "P0088", "P0089",            # rail pressure
    "P2263",                               # turbo underperformance
    "P0234", "P0299",                     # over/under-boost
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class FuelType(str, Enum):
    GASOLINE = "gasoline"
    DIESEL = "diesel"
    HYBRID = "hybrid"
    FLEX = "flex"


class RiskLevel(str, Enum):
    LOW = "bajo"
    MEDIUM = "medio"
    HIGH = "alto"
    EXTREME = "extremo"


class SessionStep(str, Enum):
    CREATED = "created"
    CONNECTING = "connecting"
    DIAGNOSING = "diagnosing"
    BACKING_UP = "backing_up"
    ANALYZING = "analyzing"
    GENERATING_MAPS = "generating_maps"
    AWAITING_APPROVAL = "awaiting_approval"
    WRITING = "writing"
    VERIFYING = "verifying"
    RECORDING = "recording"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    ABORTED = "aborted"


class SessionGate(str, Enum):
    HEALTH_CHECK = "health_check"
    BACKUP_VERIFIED = "backup_verified"
    SAFETY_VERIFIED = "safety_verified"
    USER_APPROVED = "user_approved"
    FLASH_VERIFIED = "flash_verified"


# ---------------------------------------------------------------------------
# Vehicle & ECU identification
# ---------------------------------------------------------------------------

@dataclass
class VehicleInfo:
    """Informacion completa del vehiculo."""

    vin: str
    make: str
    model: str
    year: int
    engine: str
    displacement_cc: float = 2000.0
    fuel_type: FuelType = FuelType.GASOLINE
    turbo: bool = False
    design_hp: float = 200.0
    design_torque_nm: float = 350.0
    design_rev_limit: float = 7000.0
    design_max_boost_bar: float = 1.2
    transmission: str = "manual"  # manual | auto | dct
    base_fuel_consumption_lp100km: float = 8.5

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "fuel_type": self.fuel_type.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VehicleInfo":
        d = dict(data)
        if "fuel_type" in d and isinstance(d["fuel_type"], str):
            d["fuel_type"] = FuelType(d["fuel_type"])
        return cls(**d)


@dataclass
class ECUIdentification:
    """Identificacion exacta de la ECU."""

    ecu_type: str                      # e.g. "Bosch MED17.5"
    hardware_version: str
    software_version: str
    calibration_id: str
    bootloader_version: str = ""
    serial_number: str = ""
    manufacturer: str = ""


# ---------------------------------------------------------------------------
# Backup structures
# ---------------------------------------------------------------------------

@dataclass
class BackupRecord:
    """Registro de un backup completo de la ECU."""

    backup_id: str
    vin: str
    timestamp: str                    # ISO-8601
    vehicle_info: dict[str, Any]
    ecu_identification: dict[str, Any]
    data_size_bytes: int
    sha256: str
    binary_path: str
    manifest_path: str
    verified: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Analyzer output structures
# ---------------------------------------------------------------------------

@dataclass
class ImprovableArea:
    area: str                          # 'fuel_efficiency', 'power', ...
    current: float
    potential_gain: float              # gain in native units
    potential_gain_percent: float
    method: str                        # descripcion en espanol


@dataclass
class RiskAssessment:
    level: RiskLevel
    details: str                       # descripcion en espanol
    mitigations: list[str] = field(default_factory=list)


@dataclass
class PrerequisiteCheck:
    target_profile: str
    satisfied: bool
    missing_hardware: list[str] = field(default_factory=list)
    consumable_checks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SensorHealthReport:
    all_healthy: bool
    per_sensor: dict[str, dict[str, Any]] = field(default_factory=dict)
    flagged: list[str] = field(default_factory=list)

    def add(self, name: str, value: float, status: str, detail: str = "") -> None:
        self.per_sensor[name] = {
            "value": value,
            "status": status,
            "detail": detail,
        }
        if status != "ok":
            self.flagged.append(name)
            self.all_healthy = False


@dataclass
class TuningAssessment:
    """Resultado del analisis AI del vehiculo."""

    eligible: bool
    health_score: float                # 0-100
    rejection_reasons: list[str]       # en espanol
    recommended_profile: str           # profile value
    max_safe_profile: str              # profile value
    improvable_areas: dict[str, Any]
    risk_assessment: RiskAssessment
    blocked_modifications: list[dict[str, str]]   # [{change, reason}]
    prerequisites: list[str]
    estimated_cost: dict[str, Any]
    warnings: list[str]
    sensor_health: Optional[SensorHealthReport] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "health_score": round(self.health_score, 2),
            "rejection_reasons": self.rejection_reasons,
            "recommended_profile": self.recommended_profile,
            "max_safe_profile": self.max_safe_profile,
            "improvable_areas": self.improvable_areas,
            "risk_assessment": {
                "level": self.risk_assessment.level.value,
                "details": self.risk_assessment.details,
                "mitigations": self.risk_assessment.mitigations,
            },
            "blocked_modifications": self.blocked_modifications,
            "prerequisites": self.prerequisites,
            "estimated_cost": self.estimated_cost,
            "warnings": self.warnings,
            "sensor_health": (
                {
                    "all_healthy": self.sensor_health.all_healthy,
                    "flagged": self.sensor_health.flagged,
                    "per_sensor": self.sensor_health.per_sensor,
                }
                if self.sensor_health else None
            ),
        }


# ---------------------------------------------------------------------------
# Optimizer output structures
# ---------------------------------------------------------------------------

@dataclass
class MapCellChange:
    """Cambio en una celda individual de un mapa."""

    map_name: str
    x_index: int
    y_index: int
    x_value: float
    y_value: float
    stock_value: float
    new_value: float
    delta_abs: float
    delta_pct: float
    safety_critical: bool = False
    justification: str = ""


@dataclass
class ModificationReport:
    """Reporte detallado stock -> modificado."""

    total_cells_changed: int
    map_summaries: dict[str, dict[str, float]]   # per-map stats
    top_changes: list[MapCellChange]             # mayores cambios
    safety_critical_changes: list[MapCellChange]
    narrative_spanish: str
    confidence_score: float                      # 0-1

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cells_changed": self.total_cells_changed,
            "map_summaries": self.map_summaries,
            "top_changes": [asdict(c) for c in self.top_changes],
            "safety_critical_changes": [
                asdict(c) for c in self.safety_critical_changes
            ],
            "narrative_spanish": self.narrative_spanish,
            "confidence_score": round(self.confidence_score, 3),
        }


@dataclass
class OptimizedMapSet:
    """Resultado de la optimizacion con trazabilidad completa."""

    profile_name: str
    stock_maps: ECUMapSet
    modified_maps: ECUMapSet
    modification_report: ModificationReport
    safety_report: Optional[SafetyReport] = None
    simulation: Optional[SimulationResult] = None
    confidence_score: float = 0.0
    justifications: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Backup Manager
# ---------------------------------------------------------------------------

class ECUBackupManager:
    """Gestor de backups triple (local + timestamp + hash).

    NUNCA se modifica una ECU sin backup previo verificado.
    Estructura en disco::

        data/backups/{VIN}/{timestamp}/
            original.bin
            backup_manifest.json
    """

    def __init__(self, root: Optional[Union[str, Path]] = None) -> None:
        self.root = Path(root) if root else BACKUP_ROOT
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Core primitives
    # ------------------------------------------------------------------

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_vin(vin: str) -> str:
        """Sanitiza un VIN para uso como nombre de carpeta."""
        return re.sub(r"[^A-Za-z0-9_-]", "_", vin or "UNKNOWN_VIN")

    def _backup_dir(self, vin: str, timestamp_slug: str) -> Path:
        return self.root / self._safe_vin(vin) / timestamp_slug

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_backup(
        self,
        ecu_data: bytes,
        vehicle_info: VehicleInfo,
        ecu_identification: ECUIdentification,
        notes: str = "",
    ) -> BackupRecord:
        """Crea un backup triple (binario + manifiesto + hash).

        Guarda:
        - data/backups/{VIN}/{timestamp}/original.bin   (dump crudo)
        - data/backups/{VIN}/{timestamp}/backup_manifest.json
        """
        if not isinstance(ecu_data, (bytes, bytearray, memoryview)):
            raise TypeError("ecu_data debe ser bytes")
        if len(ecu_data) == 0:
            raise ValueError("ecu_data vacio: backup abortado por seguridad")

        ts = self._now_iso()
        slug = ts.replace(":", "-").replace(".", "-")
        backup_id = f"{self._safe_vin(vehicle_info.vin)}__{slug}__{uuid.uuid4().hex[:8]}"

        out_dir = self._backup_dir(vehicle_info.vin, slug)
        out_dir.mkdir(parents=True, exist_ok=True)

        binary_path = out_dir / "original.bin"
        manifest_path = out_dir / "backup_manifest.json"

        sha = self._sha256(bytes(ecu_data))
        binary_path.write_bytes(bytes(ecu_data))

        record = BackupRecord(
            backup_id=backup_id,
            vin=vehicle_info.vin,
            timestamp=ts,
            vehicle_info=vehicle_info.to_dict(),
            ecu_identification=asdict(ecu_identification),
            data_size_bytes=len(ecu_data),
            sha256=sha,
            binary_path=str(binary_path),
            manifest_path=str(manifest_path),
            verified=False,
            notes=notes,
        )

        manifest_path.write_text(
            json.dumps(record.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Verificacion inmediata post-escritura
        record.verified = self.verify_backup(backup_id)
        if record.verified:
            # Reescribir manifiesto con flag verified=True
            manifest_path.write_text(
                json.dumps(record.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("Backup creado y verificado: %s", backup_id)
        else:
            logger.error("Backup FALLO verificacion de integridad: %s", backup_id)
            raise RuntimeError(
                f"Backup {backup_id} fallo verificacion de integridad. "
                "No se puede proceder con la reprogramacion."
            )

        return record

    def verify_backup(self, backup_id: str) -> bool:
        """Re-lee el archivo de backup y verifica que el SHA-256 coincida.

        Devuelve True solo si la integridad es 100 % confirmada.
        """
        record = self._load_record(backup_id)
        if record is None:
            logger.error("Backup no encontrado: %s", backup_id)
            return False

        binary_path = Path(record.binary_path)
        if not binary_path.exists():
            logger.error("Archivo de backup ausente: %s", binary_path)
            return False

        data = binary_path.read_bytes()
        if len(data) != record.data_size_bytes:
            logger.error(
                "Tamano de backup no coincide (%d != %d)",
                len(data), record.data_size_bytes,
            )
            return False

        actual_hash = self._sha256(data)
        ok = actual_hash == record.sha256
        if not ok:
            logger.error(
                "Hash SHA-256 no coincide:\n  esperado=%s\n  actual  =%s",
                record.sha256, actual_hash,
            )
        return ok

    def restore_from_backup(self, backup_id: str) -> bytes:
        """Devuelve los datos originales para reflasheo.

        Verifica la integridad antes de devolver.
        """
        if not self.verify_backup(backup_id):
            raise RuntimeError(
                f"Integridad comprometida: no se puede restaurar {backup_id}"
            )
        record = self._load_record(backup_id)
        if record is None:
            raise RuntimeError(f"Backup no encontrado: {backup_id}")
        return Path(record.binary_path).read_bytes()

    def list_backups(self, vin: Optional[str] = None) -> list[BackupRecord]:
        """Lista todos los backups (opcionalmente filtrados por VIN)."""
        records: list[BackupRecord] = []

        if vin:
            vin_dirs = [self.root / self._safe_vin(vin)]
        else:
            vin_dirs = [p for p in self.root.iterdir() if p.is_dir()] if self.root.exists() else []

        for vin_dir in vin_dirs:
            if not vin_dir.exists():
                continue
            for ts_dir in sorted(vin_dir.iterdir()):
                manifest = ts_dir / "backup_manifest.json"
                if not manifest.exists():
                    continue
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    records.append(BackupRecord(**data))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Manifiesto ilegible %s: %s", manifest, exc)

        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records

    def get_latest_backup(self, vin: str) -> Optional[BackupRecord]:
        """Devuelve el backup mas reciente para un VIN."""
        backups = self.list_backups(vin=vin)
        return backups[0] if backups else None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_record(self, backup_id: str) -> Optional[BackupRecord]:
        for rec in self.list_backups():
            if rec.backup_id == backup_id:
                return rec
        return None


# ---------------------------------------------------------------------------
# Vehicle Analyzer (AI-powered)
# ---------------------------------------------------------------------------

class VehicleReprogramAnalyzer:
    """Agente AI que analiza el vehiculo antes de cualquier modificacion.

    Evalua salud, elegibilidad, potencial de mejora y riesgos
    especificos. Todos los textos de salida estan en espanol.
    """

    def __init__(self, min_health_score: float = MIN_HEALTH_SCORE) -> None:
        self.min_health_score = min_health_score

    # ------------------------------------------------------------------
    # Sensor health
    # ------------------------------------------------------------------

    def validate_sensor_health(
        self,
        sensor_data: dict[str, float],
    ) -> SensorHealthReport:
        """Valida que todos los sensores lean dentro de rango normal."""
        report = SensorHealthReport(all_healthy=True)

        ranges: dict[str, tuple[float, float, str]] = {
            "coolant_temp_c":     (70.0, 110.0, "Temperatura refrigerante"),
            "oil_temp_c":         (60.0, 130.0, "Temperatura aceite"),
            "iat_c":              (-20.0, 80.0, "Temperatura admision"),
            "maf_gps":             (0.5, 300.0, "Caudal MAF"),
            "map_kpa":             (20.0, 300.0, "Presion colector"),
            "fuel_pressure_kpa":  (200.0, 8000.0, "Presion combustible"),
            "rail_pressure_bar":   (0.0, 2200.0, "Presion rail (diesel)"),
            "o2_voltage_v":        (0.0, 1.1, "Sonda lambda"),
            "battery_voltage_v":  (12.0, 15.0, "Tension bateria"),
            "knock_voltage_v":     (0.0, 5.0, "Sensor detonacion"),
            "tps_pct":             (0.0, 100.0, "Posicion mariposa"),
            "stft_pct":           (-20.0, 20.0, "STFT (ajuste corto)"),
            "ltft_pct":           (-20.0, 20.0, "LTFT (ajuste largo)"),
        }

        for key, (lo, hi, label) in ranges.items():
            if key not in sensor_data:
                continue
            val = float(sensor_data[key])
            if math.isnan(val):
                report.add(key, val, "fault", f"{label}: lectura invalida (NaN)")
                continue
            if val < lo:
                report.add(key, val, "low",
                           f"{label} fuera de rango: {val} < {lo}")
            elif val > hi:
                report.add(key, val, "high",
                           f"{label} fuera de rango: {val} > {hi}")
            else:
                report.add(key, val, "ok", f"{label} normal")

        return report

    # ------------------------------------------------------------------
    # Prerequisites
    # ------------------------------------------------------------------

    def check_prerequisites(
        self,
        vehicle_info: VehicleInfo,
        target_profile: Union[str, ProfileName],
        sensor_data: Optional[dict[str, float]] = None,
    ) -> PrerequisiteCheck:
        """Verifica requisitos de hardware y consumibles."""
        profile = ProfileName(target_profile) if isinstance(target_profile, str) else target_profile
        sensors = sensor_data or {}

        missing: list[str] = []
        consumables: list[str] = []
        warnings: list[str] = []

        # Hardware segun stage
        if profile == ProfileName.STAGE_2:
            if vehicle_info.turbo:
                missing.extend([
                    "Intercooler frontal uprated",
                    "Escape downpipe 3 pulgadas o mayor",
                    "Filtro de aire de alto flujo (o admision)",
                    "Inyectores de mayor caudal (si > +25 % HP)",
                    "Bomba de combustible HPFP reforzada (inyeccion directa)",
                ])
            else:
                missing.extend([
                    "Colector de escape/headers",
                    "Admision de alto flujo",
                    "Cuerpo de aceleracion ampliado (opcional)",
                ])

        if profile in (ProfileName.SPORT, ProfileName.STAGE_2):
            missing.append("Bujias escalon mas frio (1 grado menos)")

        # Consumibles / estado general
        coolant = sensors.get("coolant_temp_c")
        if coolant is not None and coolant > 105.0:
            warnings.append(
                f"Temperatura refrigerante alta ({coolant:.0f} C). "
                "Revisar sistema de refrigeracion antes de tunear."
            )

        oil_temp = sensors.get("oil_temp_c")
        if oil_temp is not None and oil_temp > 125.0:
            warnings.append(
                "Temperatura de aceite elevada: considerar radiador de aceite."
            )

        battery = sensors.get("battery_voltage_v")
        if battery is not None and battery < 12.3:
            warnings.append(
                f"Tension de bateria baja ({battery:.1f} V). "
                "Cargar bateria antes de flashear la ECU."
            )

        consumables.extend([
            "Verificar aceite dentro de intervalo (menos del 50 % de vida util)",
            "Verificar estado del filtro de aire",
            "Verificar bujias (antiguedad < 30.000 km para Stage 1+)",
            "Verificar estado y tension de la correa de distribucion/cadena",
            "Verificar niveles de refrigerante y aceite",
        ])

        # Stage 2 diesel extras
        if profile == ProfileName.STAGE_2 and vehicle_info.fuel_type == FuelType.DIESEL:
            missing.append("Intercambiador EGR limpio o reemplazado")
            missing.append("DPF en estado saludable o delete legal segun jurisdiccion")

        satisfied = not missing and not warnings
        return PrerequisiteCheck(
            target_profile=profile.value,
            satisfied=satisfied,
            missing_hardware=missing,
            consumable_checks=consumables,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Main analysis
    # ------------------------------------------------------------------

    def analyze_vehicle_for_tuning(
        self,
        sensor_data: dict[str, float],
        dtc_list: list[str],
        vehicle_info: VehicleInfo,
    ) -> TuningAssessment:
        """Analisis completo AI del vehiculo.

        Devuelve un TuningAssessment con elegibilidad, perfil recomendado,
        areas mejorables, riesgos, bloqueos y prerrequisitos.
        """
        rejection: list[str] = []
        warnings: list[str] = []
        blocked: list[dict[str, str]] = []

        # ---- DTCs criticos ------------------------------------------------
        critical_dtcs = [
            d for d in dtc_list
            if any(d.upper().startswith(p) for p in _CRITICAL_DTC_PREFIXES)
        ]
        if critical_dtcs:
            rejection.append(
                "DTCs criticos activos: " + ", ".join(critical_dtcs)
                + ". Resuelva estos codigos antes de tunear."
            )

        # ---- Salud de sensores -------------------------------------------
        sensor_health = self.validate_sensor_health(sensor_data)

        # ---- Health score --------------------------------------------------
        health_score = self._compute_health_score(
            sensor_data, dtc_list, sensor_health,
        )

        if health_score < self.min_health_score:
            rejection.append(
                f"Salud del vehiculo insuficiente ({health_score:.0f}%). "
                f"Se requiere >= {self.min_health_score:.0f}%."
            )

        # ---- Sobrecalentamiento / problemas mecanicos --------------------
        coolant = sensor_data.get("coolant_temp_c")
        if coolant is not None and coolant > 108.0:
            rejection.append(
                f"Sobrecalentamiento detectado ({coolant:.0f} C). "
                "No se puede tunear con problemas termicos."
            )
        if sensor_health.flagged:
            warnings.append(
                "Sensores con lectura anormal: " + ", ".join(sensor_health.flagged)
            )

        # ---- Perfil recomendado -------------------------------------------
        recommended, max_safe = self._determine_recommended_profile(
            vehicle_info, sensor_data, dtc_list, sensor_health,
        )

        # ---- Areas mejorables --------------------------------------------
        improvable = self._identify_improvable_areas(vehicle_info, recommended)

        # ---- Modificaciones bloqueadas ------------------------------------
        blocked = self._blocked_modifications(vehicle_info)

        # ---- Riesgo -------------------------------------------------------
        risk = self._risk_assessment(vehicle_info, recommended, health_score, dtc_list)

        # ---- Prerrequisitos & coste --------------------------------------
        prereq = self.check_prerequisites(vehicle_info, recommended, sensor_data)
        prerequisites = prereq.missing_hardware + prereq.consumable_checks
        warnings.extend(prereq.warnings)

        estimated_cost = self._estimate_costs(vehicle_info)

        eligible = not rejection
        return TuningAssessment(
            eligible=eligible,
            health_score=health_score,
            rejection_reasons=rejection,
            recommended_profile=recommended.value,
            max_safe_profile=max_safe.value,
            improvable_areas=improvable,
            risk_assessment=risk,
            blocked_modifications=blocked,
            prerequisites=prerequisites,
            estimated_cost=estimated_cost,
            warnings=warnings,
            sensor_health=sensor_health,
        )

    # ------------------------------------------------------------------
    # Scoring & heuristics
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_health_score(
        sensor_data: dict[str, float],
        dtc_list: list[str],
        sensor_health: SensorHealthReport,
    ) -> float:
        score = 100.0

        # Penalizacion por DTCs (P = 10, C/B/U = 3 puntos)
        for d in dtc_list:
            up = d.upper()
            if any(up.startswith(p) for p in _CRITICAL_DTC_PREFIXES):
                score -= 25.0
            elif up.startswith("P"):
                score -= 10.0
            else:
                score -= 3.0

        # Penalizacion por sensores flageados
        score -= 5.0 * len(sensor_health.flagged)

        # Lecturas especificas
        coolant = sensor_data.get("coolant_temp_c")
        if coolant is not None:
            if coolant > 105.0:
                score -= 10.0
            if coolant > 110.0:
                score -= 15.0

        stft = abs(sensor_data.get("stft_pct", 0.0))
        ltft = abs(sensor_data.get("ltft_pct", 0.0))
        if stft > 10.0 or ltft > 10.0:
            score -= 5.0
        if stft > 15.0 or ltft > 15.0:
            score -= 10.0

        return max(0.0, min(100.0, score))

    @staticmethod
    def _determine_recommended_profile(
        vehicle_info: VehicleInfo,
        sensor_data: dict[str, float],
        dtc_list: list[str],
        sensor_health: SensorHealthReport,
    ) -> tuple[ProfileName, ProfileName]:
        """Heuristica: decide el perfil recomendado y el maximo seguro."""
        # Vehiculos con problemas -> solo economia o nada
        if dtc_list or sensor_health.flagged:
            return ProfileName.ECONOMY, ProfileName.ECONOMY

        if vehicle_info.turbo:
            # Turbos tienen cabecera para Stage 1 sin hardware
            return ProfileName.STAGE_1, ProfileName.STAGE_2

        # Atmosferico moderno
        if vehicle_info.year >= 2010:
            return ProfileName.STAGE_1, ProfileName.SPORT

        # Vehiculo mas antiguo -> conservador
        return ProfileName.ECONOMY, ProfileName.STAGE_1

    @staticmethod
    def _identify_improvable_areas(
        vehicle_info: VehicleInfo,
        profile: ProfileName,
    ) -> dict[str, Any]:
        spec = ProfileLibrary.get_spec(profile)
        hp_mid = (spec.hp_gain_min_pct + spec.hp_gain_max_pct) / 2.0
        mpg_mid = (spec.mpg_change_min_pct + spec.mpg_change_max_pct) / 2.0

        potential_hp = vehicle_info.design_hp * hp_mid / 100.0
        potential_nm = vehicle_info.design_torque_nm * hp_mid / 100.0 * 0.95

        # Nuevo limite de RPM seguro: +10 % sobre diseno
        safe_rev = vehicle_info.design_rev_limit * 1.10

        return {
            "fuel_efficiency": {
                "current": vehicle_info.base_fuel_consumption_lp100km,
                "potential_gain_percent": abs(mpg_mid) if mpg_mid > 0 else 0.0,
                "method": (
                    "AFR mas pobre en crucero, avance de encendido optimizado "
                    "en carga parcial, gestion de boost reducida en crucero."
                ),
            },
            "power": {
                "current_est_hp": vehicle_info.design_hp,
                "potential_gain_hp": round(potential_hp, 1),
                "method": (
                    "Enriquecimiento controlado a plena carga, avance donde el "
                    "margen de detonacion lo permita, aumento de boost objetivo."
                ),
            },
            "torque": {
                "current_est_nm": vehicle_info.design_torque_nm,
                "potential_gain_nm": round(potential_nm, 1),
                "method": (
                    "Optimizacion VVT para mayor solapamiento en medios, "
                    "curva de par mas plana mediante boost temprano."
                ),
            },
            "throttle_response": {
                "improvement_description": (
                    "Curva pedal-acelerador mas directa; reduce zona muerta "
                    "inicial y mejora respuesta al levantar/acelerar."
                ),
            },
            "rev_range": {
                "current_limit": vehicle_info.design_rev_limit,
                "safe_new_limit": round(safe_rev, 0),
            },
        }

    @staticmethod
    def _blocked_modifications(
        vehicle_info: VehicleInfo,
    ) -> list[dict[str, str]]:
        """Parametros que NUNCA deben modificarse."""
        blocked = [
            {
                "change": "Desactivar sensor de detonacion",
                "reason": "Perdida de proteccion anti-knock: destruye pistones.",
            },
            {
                "change": "Desactivar control de sonda lambda",
                "reason": "Perdida de control de mezcla: fundicion de catalizador.",
            },
            {
                "change": "Desactivar limitador de revoluciones",
                "reason": "Riesgo mecanico extremo: ruptura de biela/valvula-piston.",
            },
            {
                "change": "Mezcla pobre (AFR > 13.5) bajo carga",
                "reason": "Detonacion severa: destruccion motor en segundos.",
            },
            {
                "change": "Avance > 38 grados BTDC",
                "reason": "Prestacion no aumenta; solo calor y detonacion.",
            },
            {
                "change": "Eliminar corte de combustible en overrun",
                "reason": "Sobrecalentamiento de catalizador y consumo elevado.",
            },
        ]

        if vehicle_info.fuel_type == FuelType.DIESEL:
            blocked.extend([
                {
                    "change": "Eliminar limitador de humos sin medicion real",
                    "reason": "Humo excesivo, sobrecalentamiento de EGT, dano turbo.",
                },
                {
                    "change": "Presion rail > limite del inyector",
                    "reason": "Falla hidraulica y rotura de inyectores.",
                },
            ])

        if vehicle_info.turbo:
            blocked.append({
                "change": "Boost > 30 % sobre diseno sin hardware",
                "reason": "Turbo fuera de mapa: sobrevelocidad y fallo de eje.",
            })

        return blocked

    @staticmethod
    def _risk_assessment(
        vehicle_info: VehicleInfo,
        profile: ProfileName,
        health_score: float,
        dtc_list: list[str],
    ) -> RiskAssessment:
        level_map = {
            ProfileName.ECONOMY: RiskLevel.LOW,
            ProfileName.STAGE_1: RiskLevel.LOW,
            ProfileName.SPORT: RiskLevel.MEDIUM,
            ProfileName.STAGE_2: RiskLevel.HIGH,
        }
        level = level_map.get(profile, RiskLevel.MEDIUM)

        if dtc_list:
            level = RiskLevel.HIGH
        if health_score < 70.0:
            level = RiskLevel.EXTREME

        details_map = {
            RiskLevel.LOW: (
                "Riesgo bajo. El perfil mantiene amplios margenes de seguridad "
                "sobre los valores de fabrica."
            ),
            RiskLevel.MEDIUM: (
                "Riesgo medio. Se recomienda monitoreo de detonacion, EGT y "
                "presion de combustible durante las primeras sesiones."
            ),
            RiskLevel.HIGH: (
                "Riesgo alto. Requiere hardware de soporte y datalogging "
                "continuo. Verificacion en dinamometro muy recomendable."
            ),
            RiskLevel.EXTREME: (
                "Riesgo extremo. El vehiculo no esta en condiciones para ser "
                "tuneado. Reparar antes de proceder."
            ),
        }

        mitigations = [
            "Siempre realizar backup antes de cualquier escritura.",
            "Monitorear STFT/LTFT tras el flasheo.",
            "Verificar temperatura de gases de escape (EGT).",
            "Datalog al menos 2 sesiones de conduccion tras el flasheo.",
        ]
        if level in (RiskLevel.HIGH, RiskLevel.EXTREME):
            mitigations.append("Verificacion obligatoria en dinamometro.")
            mitigations.append("Instalar medidor de AFR wideband temporal.")

        return RiskAssessment(
            level=level,
            details=details_map[level],
            mitigations=mitigations,
        )

    @staticmethod
    def _estimate_costs(vehicle_info: VehicleInfo) -> dict[str, Any]:
        base_stage1 = 250.0
        base_stage2 = 900.0

        parts_needed: list[dict[str, Any]] = []
        if vehicle_info.turbo:
            parts_needed.extend([
                {"parte": "Intercooler uprated", "coste_eur": 400},
                {"parte": "Downpipe 3 pulgadas", "coste_eur": 450},
                {"parte": "Filtro/admision alto flujo", "coste_eur": 180},
            ])
        parts_needed.append(
            {"parte": "Bujias escalon mas frio", "coste_eur": 80}
        )

        parts_total = sum(p["coste_eur"] for p in parts_needed)

        return {
            "stage1": {
                "mano_de_obra_eur": base_stage1,
                "partes_eur": 0,
                "total_eur": base_stage1,
                "divisa": "EUR",
                "estimacion": True,
            },
            "stage2": {
                "mano_de_obra_eur": base_stage2,
                "partes_eur": parts_total,
                "total_eur": base_stage2 + parts_total,
                "divisa": "EUR",
                "estimacion": True,
            },
            "parts_needed": parts_needed,
        }


# ---------------------------------------------------------------------------
# ECU Map Optimizer
# ---------------------------------------------------------------------------

class ECUMapOptimizer:
    """Optimizador de mapas ECU. Genera modificaciones seguras y trazables.

    Cada metodo de optimizacion:
      - NUNCA excede los limites duros de safety.py (verificados al final).
      - Loggea cada cambio con justificacion.
      - Almacena los valores originales (reversible).
      - Asigna un confidence score por cambio.
    """

    def __init__(
        self,
        safety_verifier: Optional[SafetyVerifier] = None,
        simulator: Optional[PerformanceSimulator] = None,
    ) -> None:
        self.safety_verifier = safety_verifier or SafetyVerifier()
        self.simulator = simulator

    # ------------------------------------------------------------------
    # High-level entry points
    # ------------------------------------------------------------------

    def optimize_for_efficiency(
        self,
        stock_maps: ECUMapSet,
        vehicle_info: VehicleInfo,
    ) -> OptimizedMapSet:
        """Optimizacion economia: objetivo +8-15 % consumo."""
        profile = ProfileLibrary.get_profile(ProfileName.ECONOMY)
        modified = profile.apply(stock_maps)

        # Refinamiento especifico de economia (mas alla del perfil base):
        modified = self._refine_efficiency_cruise(modified, stock_maps)

        return self._finalize_optimization(
            profile_name="economy",
            stock_maps=stock_maps,
            modified_maps=modified,
            vehicle_info=vehicle_info,
            justifications=[
                "AFR de crucero levemente empobrecido (hasta 15.2:1) para reducir consumo.",
                "Avance de encendido optimizado en cargas parciales (mayor eficiencia termica).",
                "Lockup del convertidor adelantado (transmision automatica).",
                "Boost objetivo reducido en crucero (turbo).",
            ],
            base_confidence=0.92,
        )

    def optimize_for_performance(
        self,
        stock_maps: ECUMapSet,
        vehicle_info: VehicleInfo,
        stage: Union[int, str, ProfileName] = 1,
    ) -> OptimizedMapSet:
        """Optimizacion de prestaciones: Stage 1 (seguro) o Stage 2 (con hardware)."""
        profile_name = self._resolve_performance_profile(stage)
        profile = ProfileLibrary.get_profile(profile_name)

        modified = profile.apply(stock_maps)

        if profile_name == ProfileName.STAGE_1:
            modified = self._refine_stage1(modified, stock_maps)
            justifications = [
                "Enriquecimiento a plena carga para margen ante detonacion.",
                "Avance de encendido aumentado donde el knock lo permite.",
                "Boost objetivo +10-15 % (turbo), dentro de mapa del compresor.",
                "Curva pedal mas directa.",
            ]
            confidence = 0.88
        elif profile_name == ProfileName.STAGE_2:
            modified = self._refine_stage2(modified, stock_maps)
            justifications = [
                "ATENCION: Requiere hardware de soporte.",
                "Fueling y timing agresivos.",
                "Boost +20-30 % dentro de limites de hardware.",
                "Limitador elevado hasta +10 % sobre diseno.",
                "Requiere datalog y verificacion en dinamometro.",
            ]
            confidence = 0.78
        else:
            modified = self._refine_stage1(modified, stock_maps)
            justifications = ["Perfil Sport: balance calle/pista."]
            confidence = 0.82

        return self._finalize_optimization(
            profile_name=profile_name.value,
            stock_maps=stock_maps,
            modified_maps=modified,
            vehicle_info=vehicle_info,
            justifications=justifications,
            base_confidence=confidence,
        )

    def optimize_balanced(
        self,
        stock_maps: ECUMapSet,
        vehicle_info: VehicleInfo,
    ) -> OptimizedMapSet:
        """Balance: mejor economia en crucero + mas potencia a WOT."""
        # Partimos de Stage 1 y aplicamos refinamiento de eficiencia en
        # las filas de carga parcial.
        profile = ProfileLibrary.get_profile(ProfileName.STAGE_1)
        modified = profile.apply(stock_maps)
        modified = self._refine_efficiency_cruise(modified, stock_maps)

        return self._finalize_optimization(
            profile_name="balanced",
            stock_maps=stock_maps,
            modified_maps=modified,
            vehicle_info=vehicle_info,
            justifications=[
                "WOT: comportamiento Stage 1 (mas potencia).",
                "Crucero: AFR mas pobre y timing optimizado (mejor consumo).",
                "Respuesta de pedal mas directa sin agresividad excesiva.",
            ],
            base_confidence=0.86,
        )

    def apply_diesel_optimizations(
        self,
        stock_maps: ECUMapSet,
        vehicle_info: VehicleInfo,
    ) -> OptimizedMapSet:
        """Optimizaciones especificas diesel.

        - Avance de inyeccion (+1-2 grados)
        - Presion de rail (+5-10 %)
        - Presion de boost (+10-20 %)
        - Ajuste de limitador de humos (monitoreado)
        - Reduccion EGR (admision mas limpia)
        - Intervalo de regeneracion DPF optimizado
        """
        if vehicle_info.fuel_type != FuelType.DIESEL:
            logger.warning(
                "apply_diesel_optimizations llamado para motor no diesel (%s)",
                vehicle_info.fuel_type.value,
            )

        modified = stock_maps.copy()

        # Fuel map (en diesel: cantidad inyectada por ciclo) +8 %
        modified.fuel_map.data = self._scale_nonzero(modified.fuel_map.data, 1.08)

        # Timing map (avance de inyeccion) +1.5 grados
        modified.ignition_map.data = self._offset_nonzero(
            modified.ignition_map.data, 1.5,
        )
        modified.ignition_map.data = np.clip(modified.ignition_map.data, 0.0, 35.0)

        # Boost +15 %
        modified.boost_map.data = self._scale_nonzero(modified.boost_map.data, 1.15)
        modified.boost_map.data = np.clip(modified.boost_map.data, 0.0, 2.8)

        # VVT: en diesel se usa para EGR interno; reducir levemente
        modified.vvt_map.data = np.clip(
            self._offset_nonzero(modified.vvt_map.data, -2.0), 0.0, 55.0,
        )

        # Throttle: diesel normalmente drive-by-wire para arranque suave
        modified.throttle_map.data = self._scale_nonzero(
            modified.throttle_map.data, 1.05,
        )
        modified.throttle_map.data = np.clip(modified.throttle_map.data, 0.0, 100.0)

        modified.vehicle_info = dict(modified.vehicle_info)
        modified.vehicle_info["tuning_profile"] = "diesel_balanced"

        return self._finalize_optimization(
            profile_name="diesel_balanced",
            stock_maps=stock_maps,
            modified_maps=modified,
            vehicle_info=vehicle_info,
            justifications=[
                "Avance de inyeccion +1.5 grados: mejor presion pico y economia.",
                "Presion de rail aumentada: mejor atomizacion, menos humo.",
                "Boost +15 %: mejor llenado y torque a media RPM.",
                "Limitador de humos ajustado (requiere verificacion de opacidad).",
                "EGR reducido: admision mas limpia, mejor respuesta.",
                "Intervalo de regeneracion DPF revisado segun mapa termico.",
            ],
            base_confidence=0.84,
        )

    # ------------------------------------------------------------------
    # Map-level refinement helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _scale_nonzero(data: np.ndarray, factor: float) -> np.ndarray:
        out = data.copy()
        mask = data != 0.0
        out[mask] = data[mask] * factor
        return out

    @staticmethod
    def _offset_nonzero(data: np.ndarray, offset: float) -> np.ndarray:
        out = data.copy()
        mask = data != 0.0
        out[mask] = data[mask] + offset
        return out

    def _refine_efficiency_cruise(
        self,
        modified: ECUMapSet,
        stock: ECUMapSet,
    ) -> ECUMapSet:
        """Afinado adicional en filas de crucero (carga 20-50 %)."""
        load_axis = modified.fuel_map.y_axis.values
        cruise_rows = (load_axis >= 20.0) & (load_axis <= 50.0)

        if cruise_rows.any():
            # Empobrecer adicional 3 % en crucero (ya ve un -8 % global)
            modified.fuel_map.data[cruise_rows, :] *= 0.97
            # Avance + 2 grados en crucero
            modified.ignition_map.data[cruise_rows, :] = np.clip(
                modified.ignition_map.data[cruise_rows, :] + 2.0,
                0.0, 36.0,
            )
        return modified

    def _refine_stage1(
        self,
        modified: ECUMapSet,
        stock: ECUMapSet,
    ) -> ECUMapSet:
        """Refinamiento Stage 1: asegura enriquecimiento a WOT."""
        load_axis = modified.fuel_map.y_axis.values
        wot_rows = load_axis >= 85.0
        if wot_rows.any():
            # Asegura al menos +6 % combustible a WOT
            current = modified.fuel_map.data[wot_rows, :]
            floor = stock.fuel_map.data[wot_rows, :] * 1.06
            modified.fuel_map.data[wot_rows, :] = np.maximum(current, floor)
        return modified

    def _refine_stage2(
        self,
        modified: ECUMapSet,
        stock: ECUMapSet,
    ) -> ECUMapSet:
        modified = self._refine_stage1(modified, stock)
        # Mayor enriquecimiento a WOT (min +10 %)
        load_axis = modified.fuel_map.y_axis.values
        wot_rows = load_axis >= 85.0
        if wot_rows.any():
            floor = stock.fuel_map.data[wot_rows, :] * 1.10
            modified.fuel_map.data[wot_rows, :] = np.maximum(
                modified.fuel_map.data[wot_rows, :], floor,
            )
        return modified

    @staticmethod
    def _resolve_performance_profile(
        stage: Union[int, str, ProfileName],
    ) -> ProfileName:
        if isinstance(stage, ProfileName):
            return stage
        if isinstance(stage, int):
            return {1: ProfileName.STAGE_1, 2: ProfileName.STAGE_2}.get(
                stage, ProfileName.STAGE_1,
            )
        s = str(stage).lower().replace(" ", "_")
        try:
            return ProfileName(s)
        except ValueError:
            if "2" in s:
                return ProfileName.STAGE_2
            if "sport" in s:
                return ProfileName.SPORT
            return ProfileName.STAGE_1

    # ------------------------------------------------------------------
    # Modification report
    # ------------------------------------------------------------------

    def generate_modification_report(
        self,
        stock: ECUMapSet,
        modified: ECUMapSet,
    ) -> ModificationReport:
        """Compara stock vs modificado celda por celda."""
        all_changes: list[MapCellChange] = []

        map_pairs = [
            ("fuel_map", stock.fuel_map, modified.fuel_map, False, 5.0),
            ("ignition_map", stock.ignition_map, modified.ignition_map, True, 1.5),
            ("boost_map", stock.boost_map, modified.boost_map, True, 0.1),
            ("vvt_map", stock.vvt_map, modified.vvt_map, False, 5.0),
            ("throttle_map", stock.throttle_map, modified.throttle_map, False, 10.0),
        ]

        summaries: dict[str, dict[str, float]] = {}

        for name, s_map, m_map, safety_flag, threshold in map_pairs:
            diff = m_map.data - s_map.data
            nz_mask = (s_map.data != 0.0) | (m_map.data != 0.0)
            changed_mask = nz_mask & (np.abs(diff) > 1e-6)
            n_changed = int(changed_mask.sum())

            with np.errstate(divide="ignore", invalid="ignore"):
                pct = np.where(
                    s_map.data != 0.0, 100.0 * diff / s_map.data, 0.0,
                )

            summaries[name] = {
                "cells_changed": float(n_changed),
                "mean_abs_delta": float(np.mean(np.abs(diff[changed_mask]))) if n_changed else 0.0,
                "max_abs_delta": float(np.max(np.abs(diff))) if n_changed else 0.0,
                "mean_pct": float(np.mean(pct[changed_mask])) if n_changed else 0.0,
                "max_pct": float(np.max(np.abs(pct))) if n_changed else 0.0,
            }

            # Top cambios (por delta absoluto)
            if n_changed:
                flat_idx = np.argsort(np.abs(diff), axis=None)[::-1][:10]
                for fi in flat_idx:
                    y_idx, x_idx = np.unravel_index(fi, diff.shape)
                    d_abs = float(diff[y_idx, x_idx])
                    if abs(d_abs) < 1e-6:
                        continue
                    s_val = float(s_map.data[y_idx, x_idx])
                    m_val = float(m_map.data[y_idx, x_idx])
                    d_pct = float(pct[y_idx, x_idx])
                    is_critical = safety_flag and abs(d_abs) >= threshold
                    all_changes.append(MapCellChange(
                        map_name=name,
                        x_index=int(x_idx),
                        y_index=int(y_idx),
                        x_value=float(s_map.x_axis.values[x_idx]),
                        y_value=float(s_map.y_axis.values[y_idx]),
                        stock_value=s_val,
                        new_value=m_val,
                        delta_abs=d_abs,
                        delta_pct=d_pct,
                        safety_critical=is_critical,
                        justification=self._justify_change(name, d_abs, d_pct),
                    ))

        total = int(sum(s["cells_changed"] for s in summaries.values()))
        top = sorted(all_changes, key=lambda c: abs(c.delta_abs), reverse=True)[:20]
        critical = [c for c in all_changes if c.safety_critical]

        narrative = self._build_narrative(summaries, stock, modified)

        # Confidence baseline: decrece con cambios grandes
        worst_pct = max(
            (s["max_pct"] for s in summaries.values()), default=0.0,
        )
        confidence = max(0.5, 1.0 - worst_pct / 200.0)

        return ModificationReport(
            total_cells_changed=total,
            map_summaries=summaries,
            top_changes=top,
            safety_critical_changes=critical,
            narrative_spanish=narrative,
            confidence_score=confidence,
        )

    @staticmethod
    def _justify_change(map_name: str, delta_abs: float, delta_pct: float) -> str:
        sign = "aumenta" if delta_abs > 0 else "reduce"
        if map_name == "fuel_map":
            return f"Se {sign} el combustible en {abs(delta_pct):.1f} %."
        if map_name == "ignition_map":
            return f"Se {sign} el avance {abs(delta_abs):.1f} grados BTDC."
        if map_name == "boost_map":
            return f"Se {sign} el boost objetivo {abs(delta_abs):.2f} bar."
        if map_name == "vvt_map":
            return f"Se {sign} la apertura de VVT {abs(delta_abs):.1f} grados cam."
        if map_name == "throttle_map":
            return f"Se {sign} la apertura de mariposa {abs(delta_pct):.1f} %."
        return f"Cambio: {delta_abs:+.2f}."

    @staticmethod
    def _build_narrative(
        summaries: dict[str, dict[str, float]],
        stock: ECUMapSet,
        modified: ECUMapSet,
    ) -> str:
        lines: list[str] = [
            "RESUMEN DE MODIFICACIONES (español)",
            "=====================================",
        ]
        labels = {
            "fuel_map":    "Inyeccion de combustible",
            "ignition_map": "Avance de encendido",
            "boost_map":    "Presion de boost",
            "vvt_map":      "Distribucion variable (VVT)",
            "throttle_map": "Mapa de mariposa electronica",
        }
        for key, label in labels.items():
            s = summaries.get(key, {})
            n = int(s.get("cells_changed", 0))
            max_pct = s.get("max_pct", 0.0)
            lines.append(
                f"- {label}: {n} celdas modificadas, cambio maximo {max_pct:.1f} %."
            )

        lines.append("")
        lines.append(
            f"Limite RPM: {stock.rev_limiter.hard_limit_rpm:.0f} -> "
            f"{modified.rev_limiter.hard_limit_rpm:.0f}"
        )
        lines.append(
            f"Launch RPM: {stock.launch_control.launch_rpm:.0f} -> "
            f"{modified.launch_control.launch_rpm:.0f}"
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    def _finalize_optimization(
        self,
        *,
        profile_name: str,
        stock_maps: ECUMapSet,
        modified_maps: ECUMapSet,
        vehicle_info: VehicleInfo,
        justifications: list[str],
        base_confidence: float,
    ) -> OptimizedMapSet:
        report = self.generate_modification_report(stock_maps, modified_maps)
        safety = self.safety_verifier.verify(modified_maps)

        sim = None
        if self.simulator is not None:
            try:
                sim = self.simulator.simulate(stock_maps, modified_maps)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Simulacion fallida: %s", exc)

        # Confidence: combina heuristica del reporte con el baseline
        confidence = min(1.0, 0.5 * base_confidence + 0.5 * report.confidence_score)
        if not safety.passed:
            confidence *= 0.4  # si no pasa safety, muy baja confianza

        return OptimizedMapSet(
            profile_name=profile_name,
            stock_maps=stock_maps,
            modified_maps=modified_maps,
            modification_report=report,
            safety_report=safety,
            simulation=sim,
            confidence_score=confidence,
            justifications=justifications,
        )


# ---------------------------------------------------------------------------
# Flash driver (abstract)
# ---------------------------------------------------------------------------

class ECUFlashDriver:
    """Driver abstracto para lectura/escritura ECU.

    En produccion esta clase envuelve un stack UDS (ISO 14229) via
    udsoncan + python-can. Para tests/simulacion se inyecta una
    implementacion en memoria.
    """

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def read_identification(self) -> ECUIdentification: ...
    def read_vin(self) -> str: ...
    def read_calibration(self) -> bytes: ...
    def write_calibration(self, data: bytes) -> None: ...
    def verify_write(self, expected: bytes) -> bool: ...
    def clear_adaptive_learning(self) -> None: ...
    def read_sensors(self) -> dict[str, float]: ...
    def read_dtcs(self) -> list[str]: ...


class InMemoryFlashDriver(ECUFlashDriver):
    """Implementacion en memoria para pruebas y simulacion."""

    def __init__(
        self,
        identification: ECUIdentification,
        vin: str,
        initial_calibration: bytes,
        sensor_data: Optional[dict[str, float]] = None,
        dtcs: Optional[list[str]] = None,
    ) -> None:
        self._ident = identification
        self._vin = vin
        self._cal = bytes(initial_calibration)
        self._sensors = dict(sensor_data or {})
        self._dtcs = list(dtcs or [])
        self._connected = False

    def connect(self) -> None: self._connected = True
    def disconnect(self) -> None: self._connected = False
    def read_identification(self) -> ECUIdentification: return self._ident
    def read_vin(self) -> str: return self._vin
    def read_calibration(self) -> bytes: return self._cal
    def write_calibration(self, data: bytes) -> None: self._cal = bytes(data)
    def verify_write(self, expected: bytes) -> bool: return self._cal == expected
    def clear_adaptive_learning(self) -> None: pass
    def read_sensors(self) -> dict[str, float]: return dict(self._sensors)
    def read_dtcs(self) -> list[str]: return list(self._dtcs)


# ---------------------------------------------------------------------------
# Reprogramming Session
# ---------------------------------------------------------------------------

@dataclass
class SessionState:
    """Estado completo de una sesion de reprogramacion."""

    session_id: str
    vehicle_info: dict[str, Any]
    created_at: str
    step: SessionStep = SessionStep.CREATED
    gates_passed: list[str] = field(default_factory=list)
    ecu_identification: Optional[dict[str, Any]] = None
    sensor_snapshot: Optional[dict[str, float]] = None
    dtc_snapshot: Optional[list[str]] = None
    backup_id: Optional[str] = None
    assessment: Optional[dict[str, Any]] = None
    selected_profile: Optional[str] = None
    optimization: Optional[dict[str, Any]] = None
    flash_result: Optional[dict[str, Any]] = None
    post_flash: Optional[dict[str, Any]] = None
    errors: list[str] = field(default_factory=list)
    finished_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["step"] = self.step.value
        return d


class ReprogrammingSession:
    """Gestor del flujo completo de reprogramacion.

    Enforza el orden:
      1. CONNECT & IDENTIFY
      2. FULL DIAGNOSTIC SCAN  (gate: health > 80 %)
      3. BACKUP                (gate: backup verificado)
      4. ANALYZE & RECOMMEND
      5. GENERATE MAPS         (gate: safety ok)
      6. USER APPROVAL         (gate: aprobado)
      7. WRITE                 (con rollback automatico si falla)
      8. POST-FLASH VERIFICATION
      9. RECORD & LEARN
    """

    def __init__(
        self,
        driver: ECUFlashDriver,
        *,
        vehicle_info: VehicleInfo,
        backup_manager: Optional[ECUBackupManager] = None,
        analyzer: Optional[VehicleReprogramAnalyzer] = None,
        optimizer: Optional[ECUMapOptimizer] = None,
        sessions_root: Optional[Union[str, Path]] = None,
        min_health_score: float = MIN_HEALTH_SCORE,
    ) -> None:
        self.driver = driver
        self.vehicle_info = vehicle_info
        self.backup_manager = backup_manager or ECUBackupManager()
        self.analyzer = analyzer or VehicleReprogramAnalyzer(min_health_score)
        self.optimizer = optimizer or ECUMapOptimizer()
        self.min_health_score = min_health_score

        self.sessions_root = Path(sessions_root) if sessions_root else SESSIONS_ROOT
        self.sessions_root.mkdir(parents=True, exist_ok=True)

        # Estado en memoria (persistido en disco tras cada paso)
        self._state: Optional[SessionState] = None
        self._stock_maps: Optional[ECUMapSet] = None
        self._optimized: Optional[OptimizedMapSet] = None

    # ------------------------------------------------------------------
    # Session primitives
    # ------------------------------------------------------------------

    def start_session(self) -> str:
        """Inicia una nueva sesion de reprogramacion. Devuelve el SessionID."""
        sid = f"sess_{uuid.uuid4().hex[:16]}"
        self._state = SessionState(
            session_id=sid,
            vehicle_info=self.vehicle_info.to_dict(),
            created_at=datetime.now(timezone.utc).isoformat(),
            step=SessionStep.CREATED,
        )
        self._persist()
        logger.info("Sesion creada: %s", sid)
        return sid

    def get_session_status(self) -> dict[str, Any]:
        """Devuelve estado actual + pasos ejecutados."""
        self._require_state()
        return self._state.to_dict()  # type: ignore[union-attr]

    def abort_session(self, reason: str = "") -> None:
        """Aborta la sesion; si hay backup intenta restaurar inmediatamente."""
        self._require_state()
        logger.warning("Abortando sesion %s: %s", self._state.session_id, reason)  # type: ignore[union-attr]
        self._state.errors.append(f"Abortada: {reason}")  # type: ignore[union-attr]
        if self._state.backup_id:  # type: ignore[union-attr]
            try:
                self.rollback()
            except Exception as exc:  # noqa: BLE001
                self._state.errors.append(f"Rollback fallido: {exc}")  # type: ignore[union-attr]
        self._state.step = SessionStep.ABORTED  # type: ignore[union-attr]
        self._state.finished_at = datetime.now(timezone.utc).isoformat()  # type: ignore[union-attr]
        self._persist()

    def rollback(self) -> bool:
        """Restaura la calibracion original desde el backup."""
        self._require_state()
        if not self._state.backup_id:  # type: ignore[union-attr]
            raise RuntimeError("No hay backup registrado en la sesion.")

        original = self.backup_manager.restore_from_backup(
            self._state.backup_id,  # type: ignore[union-attr]
        )
        try:
            self.driver.connect()
            self.driver.write_calibration(original)
            ok = self.driver.verify_write(original)
        finally:
            self.driver.disconnect()

        self._state.step = SessionStep.ROLLED_BACK  # type: ignore[union-attr]
        self._state.finished_at = datetime.now(timezone.utc).isoformat()  # type: ignore[union-attr]
        self._state.flash_result = {  # type: ignore[union-attr]
            "rolled_back": True,
            "verified": ok,
            "at": self._state.finished_at,  # type: ignore[union-attr]
        }
        self._persist()
        logger.info("Rollback completado (verify=%s)", ok)
        return ok

    # ------------------------------------------------------------------
    # Step 1 & 2: Connect + Diagnostics
    # ------------------------------------------------------------------

    def step_connect_and_identify(self) -> dict[str, Any]:
        self._require_state()
        self._state.step = SessionStep.CONNECTING  # type: ignore[union-attr]
        self._persist()

        self.driver.connect()
        ident = self.driver.read_identification()
        vin = self.driver.read_vin()

        if vin and self.vehicle_info.vin and vin != self.vehicle_info.vin:
            raise RuntimeError(
                f"VIN leido de ECU ({vin}) no coincide con "
                f"vehiculo esperado ({self.vehicle_info.vin})."
            )

        self._state.ecu_identification = asdict(ident)  # type: ignore[union-attr]
        self._persist()
        return {"vin": vin, "identification": asdict(ident)}

    def step_full_diagnostics(self) -> dict[str, Any]:
        """Escaneo completo + gate de salud > 80 %."""
        self._require_state()
        self._state.step = SessionStep.DIAGNOSING  # type: ignore[union-attr]
        self._persist()

        sensors = self.driver.read_sensors()
        dtcs = self.driver.read_dtcs()

        self._state.sensor_snapshot = dict(sensors)  # type: ignore[union-attr]
        self._state.dtc_snapshot = list(dtcs)  # type: ignore[union-attr]

        sensor_health = self.analyzer.validate_sensor_health(sensors)
        score = VehicleReprogramAnalyzer._compute_health_score(
            sensors, dtcs, sensor_health,
        )

        result = {
            "sensors": sensors,
            "dtcs": dtcs,
            "health_score": score,
            "sensor_health": {
                "all_healthy": sensor_health.all_healthy,
                "flagged": sensor_health.flagged,
            },
        }

        if score < self.min_health_score:
            raise RuntimeError(
                f"GATE de salud fallido: {score:.1f}% < {self.min_health_score:.1f}%. "
                "No se puede continuar con la reprogramacion."
            )

        self._mark_gate(SessionGate.HEALTH_CHECK)
        return result

    # ------------------------------------------------------------------
    # Step 3: Backup (MANDATORY)
    # ------------------------------------------------------------------

    def step_backup(self) -> BackupRecord:
        """Backup triple obligatorio. No se puede saltar."""
        self._require_state()
        if self._state.ecu_identification is None:  # type: ignore[union-attr]
            raise RuntimeError("Backup requiere identificacion previa (paso 1).")

        self._state.step = SessionStep.BACKING_UP  # type: ignore[union-attr]
        self._persist()

        raw = self.driver.read_calibration()
        if not raw:
            raise RuntimeError("ECU devolvio datos vacios; backup abortado.")

        ident = ECUIdentification(**self._state.ecu_identification)  # type: ignore[union-attr]
        record = self.backup_manager.create_backup(
            ecu_data=raw,
            vehicle_info=self.vehicle_info,
            ecu_identification=ident,
            notes=f"session={self._state.session_id}",  # type: ignore[union-attr]
        )

        if not record.verified:
            raise RuntimeError(
                "Backup creado pero NO verificado. Abortando reprogramacion."
            )

        self._state.backup_id = record.backup_id  # type: ignore[union-attr]
        self._mark_gate(SessionGate.BACKUP_VERIFIED)
        return record

    # ------------------------------------------------------------------
    # Step 4: Analyze & Recommend
    # ------------------------------------------------------------------

    def step_analyze(self) -> TuningAssessment:
        self._require_state()
        if (
            self._state.sensor_snapshot is None  # type: ignore[union-attr]
            or self._state.dtc_snapshot is None  # type: ignore[union-attr]
        ):
            raise RuntimeError("Analisis requiere diagnostico previo (paso 2).")

        self._state.step = SessionStep.ANALYZING  # type: ignore[union-attr]
        assessment = self.analyzer.analyze_vehicle_for_tuning(
            sensor_data=self._state.sensor_snapshot,  # type: ignore[union-attr]
            dtc_list=self._state.dtc_snapshot,  # type: ignore[union-attr]
            vehicle_info=self.vehicle_info,
        )
        self._state.assessment = assessment.to_dict()  # type: ignore[union-attr]
        self._persist()
        return assessment

    # ------------------------------------------------------------------
    # Step 5: Generate optimized maps
    # ------------------------------------------------------------------

    def step_generate_maps(
        self,
        profile: Union[str, ProfileName],
        *,
        stock_maps: Optional[ECUMapSet] = None,
    ) -> OptimizedMapSet:
        """Genera mapas optimizados para el perfil elegido."""
        self._require_state()
        self._state.step = SessionStep.GENERATING_MAPS  # type: ignore[union-attr]
        self._persist()

        # Si no nos pasan los mapas, generamos un stock realista para el motor.
        if stock_maps is None:
            generator = ECUMapGenerator(
                displacement_cc=self.vehicle_info.displacement_cc,
                turbo=self.vehicle_info.turbo,
                max_boost_bar=self.vehicle_info.design_max_boost_bar,
                design_rev_limit=self.vehicle_info.design_rev_limit,
            )
            stock_maps = generator.generate_stock_maps(
                vehicle_info={
                    "vin": self.vehicle_info.vin,
                    "make": self.vehicle_info.make,
                    "model": self.vehicle_info.model,
                    "year": str(self.vehicle_info.year),
                    "engine": self.vehicle_info.engine,
                },
            )
        self._stock_maps = stock_maps

        # Asignar simulador coherente con el vehiculo
        self.optimizer.simulator = PerformanceSimulator(
            base_hp=self.vehicle_info.design_hp,
            base_torque_nm=self.vehicle_info.design_torque_nm,
            displacement_cc=self.vehicle_info.displacement_cc,
            base_fuel_consumption_lp100km=self.vehicle_info.base_fuel_consumption_lp100km,
        )

        profile_name = (
            profile if isinstance(profile, ProfileName) else self._parse_profile(profile)
        )

        if self.vehicle_info.fuel_type == FuelType.DIESEL:
            optimized = self.optimizer.apply_diesel_optimizations(
                stock_maps, self.vehicle_info,
            )
        elif profile_name == ProfileName.ECONOMY:
            optimized = self.optimizer.optimize_for_efficiency(
                stock_maps, self.vehicle_info,
            )
        elif profile_name == ProfileName.STAGE_2:
            optimized = self.optimizer.optimize_for_performance(
                stock_maps, self.vehicle_info, stage=2,
            )
        elif profile_name == ProfileName.SPORT:
            optimized = self.optimizer.optimize_for_performance(
                stock_maps, self.vehicle_info, stage=ProfileName.SPORT,
            )
        else:
            optimized = self.optimizer.optimize_for_performance(
                stock_maps, self.vehicle_info, stage=1,
            )

        if optimized.safety_report is None or not optimized.safety_report.passed:
            failed = (
                [c.check_name for c in optimized.safety_report.failed_checks]
                if optimized.safety_report else ["sin_reporte"]
            )
            raise RuntimeError(
                f"GATE de seguridad fallido. Checks fallidos: {failed}. "
                "No se generaran mapas."
            )

        self._optimized = optimized
        self._state.selected_profile = optimized.profile_name  # type: ignore[union-attr]
        self._state.optimization = {  # type: ignore[union-attr]
            "profile": optimized.profile_name,
            "confidence": optimized.confidence_score,
            "modification_report": optimized.modification_report.to_dict(),
            "safety": {
                "passed": optimized.safety_report.passed,
                "integrity_hash": optimized.safety_report.integrity_hash,
                "summary": optimized.safety_report.summary(),
            },
            "simulation": (
                optimized.simulation.as_chart_data() if optimized.simulation else None
            ),
            "justifications": optimized.justifications,
        }
        self._mark_gate(SessionGate.SAFETY_VERIFIED)
        return optimized

    # ------------------------------------------------------------------
    # Step 6 / 7: Approve & Write
    # ------------------------------------------------------------------

    def step_request_approval(self) -> dict[str, Any]:
        """Marca la sesion a la espera de confirmacion del usuario."""
        self._require_state()
        if self._optimized is None:
            raise RuntimeError("No hay optimizacion lista para aprobar.")
        self._state.step = SessionStep.AWAITING_APPROVAL  # type: ignore[union-attr]
        self._persist()
        return self._state.optimization or {}  # type: ignore[union-attr]

    def step_apply_approval(
        self,
        approved: bool,
        *,
        user_notes: str = "",
        serializer: Optional[Callable[[ECUMapSet], bytes]] = None,
    ) -> dict[str, Any]:
        """Tras aprobacion explicita del usuario, flashea la ECU.

        Si ``approved`` es False, aborta sin tocar la ECU.
        """
        self._require_state()
        if not approved:
            self.abort_session(reason=f"Usuario rechazo: {user_notes}")
            return {"approved": False}

        if self._optimized is None:
            raise RuntimeError("Nada que flashear.")
        if SessionGate.BACKUP_VERIFIED.value not in self._state.gates_passed:  # type: ignore[union-attr]
            raise RuntimeError(
                "No se puede flashear sin backup verificado."
            )

        self._mark_gate(SessionGate.USER_APPROVED)
        self._state.step = SessionStep.WRITING  # type: ignore[union-attr]
        self._persist()

        serializer = serializer or self._default_serializer
        new_data = serializer(self._optimized.modified_maps)

        try:
            self.driver.connect()
            self.driver.write_calibration(new_data)
            verified = self.driver.verify_write(new_data)
        except Exception as exc:  # noqa: BLE001
            logger.error("Fallo durante flasheo: %s", exc)
            self._state.errors.append(f"Flash error: {exc}")  # type: ignore[union-attr]
            self.rollback()
            raise
        finally:
            try:
                self.driver.disconnect()
            except Exception:  # noqa: BLE001
                pass

        if not verified:
            logger.error("Verificacion post-escritura FALLO. Rollback automatico.")
            self._state.errors.append("Verificacion post-escritura fallida")  # type: ignore[union-attr]
            self.rollback()
            raise RuntimeError(
                "Escritura no coincide con datos esperados. Backup restaurado."
            )

        self._mark_gate(SessionGate.FLASH_VERIFIED)
        self._state.flash_result = {  # type: ignore[union-attr]
            "bytes_written": len(new_data),
            "verified": True,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        self._persist()
        return self._state.flash_result  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # Step 8: Post-flash verification
    # ------------------------------------------------------------------

    def step_post_flash_verify(
        self,
        *,
        idle_seconds: float = IDLE_STABILITY_SEC,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ) -> dict[str, Any]:
        """Verificacion post-flash: ADAPT clear + DTCs + idle stability."""
        self._require_state()
        self._state.step = SessionStep.VERIFYING  # type: ignore[union-attr]
        self._persist()

        try:
            self.driver.connect()
            self.driver.clear_adaptive_learning()

            # Lectura inicial
            initial = self.driver.read_sensors()
            new_dtcs = self.driver.read_dtcs()

            # Idle stability: monitoreamos rpm y temperatura
            slept = 0.0
            sleep_step = 5.0
            sleeper = sleep_fn or time.sleep
            samples: list[dict[str, float]] = [initial]
            while slept < idle_seconds:
                sleeper(sleep_step)
                slept += sleep_step
                samples.append(self.driver.read_sensors())

            # Re-check DTCs
            final_dtcs = self.driver.read_dtcs()
            critical = [
                d for d in final_dtcs
                if any(d.upper().startswith(p) for p in _CRITICAL_DTC_PREFIXES)
            ]

            rpm_vals = [s.get("rpm", 0.0) for s in samples if "rpm" in s]
            rpm_std = float(np.std(rpm_vals)) if len(rpm_vals) >= 2 else 0.0
            rpm_stable = rpm_std < 150.0

            result = {
                "initial_dtcs_pre": self._state.dtc_snapshot or [],  # type: ignore[union-attr]
                "final_dtcs_post": final_dtcs,
                "new_dtcs": [d for d in final_dtcs if d not in (self._state.dtc_snapshot or [])],  # type: ignore[union-attr]
                "critical_dtcs": critical,
                "rpm_stability_std": rpm_std,
                "rpm_stable": rpm_stable,
                "samples": len(samples),
                "idle_seconds_monitored": slept,
                "passed": rpm_stable and not critical,
            }
        finally:
            try:
                self.driver.disconnect()
            except Exception:  # noqa: BLE001
                pass

        self._state.post_flash = result  # type: ignore[union-attr]

        # Si algo va mal ofrecemos rollback (no lo hacemos automatico aqui
        # porque algunos avisos son recuperables; el orquestador decide).
        if not result["passed"]:
            self._state.errors.append(  # type: ignore[union-attr]
                "Verificacion post-flash fallida: "
                f"DTCs={critical}, rpm_std={rpm_std:.1f}"
            )
            self._persist()
            raise RuntimeError(
                "Verificacion post-flash fallida. Se recomienda rollback inmediato."
            )

        self._persist()
        return result

    # ------------------------------------------------------------------
    # Step 9: Record & learn
    # ------------------------------------------------------------------

    def step_record_and_learn(self) -> dict[str, Any]:
        """Persiste la sesion para aprendizaje futuro."""
        self._require_state()
        self._state.step = SessionStep.RECORDING  # type: ignore[union-attr]

        record = {
            "session_id": self._state.session_id,  # type: ignore[union-attr]
            "vehicle_info": self._state.vehicle_info,  # type: ignore[union-attr]
            "profile": self._state.selected_profile,  # type: ignore[union-attr]
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "predicted": (
                self._state.optimization.get("simulation")  # type: ignore[union-attr]
                if self._state.optimization else None  # type: ignore[union-attr]
            ),
            "post_flash": self._state.post_flash,  # type: ignore[union-attr]
        }

        kb_root = Path(__file__).resolve().parent.parent.parent / "data" / "knowledge_base" / "reprogramming_sessions"
        kb_root.mkdir(parents=True, exist_ok=True)
        kb_file = kb_root / f"{self._state.session_id}.json"  # type: ignore[union-attr]
        kb_file.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

        self._state.step = SessionStep.COMPLETED  # type: ignore[union-attr]
        self._state.finished_at = datetime.now(timezone.utc).isoformat()  # type: ignore[union-attr]
        self._persist()
        return record

    # ------------------------------------------------------------------
    # Orquestacion de alto nivel
    # ------------------------------------------------------------------

    def run_full_workflow(
        self,
        *,
        profile: Union[str, ProfileName],
        approve_callback: Callable[[dict[str, Any]], bool],
        stock_maps: Optional[ECUMapSet] = None,
        idle_seconds: float = IDLE_STABILITY_SEC,
    ) -> dict[str, Any]:
        """Ejecuta los 9 pasos en orden, con los gates correspondientes.

        ``approve_callback`` recibe la optimizacion propuesta y debe
        devolver True si el usuario la aprueba explicitamente.
        """
        if self._state is None:
            self.start_session()

        self.step_connect_and_identify()
        self.step_full_diagnostics()
        self.step_backup()
        self.step_analyze()
        self.step_generate_maps(profile, stock_maps=stock_maps)
        proposal = self.step_request_approval()
        approved = bool(approve_callback(proposal))
        self.step_apply_approval(approved)
        if not approved:
            return self.get_session_status()

        try:
            self.step_post_flash_verify(idle_seconds=idle_seconds)
        except Exception as exc:  # noqa: BLE001
            logger.error("Post-flash fallido: %s. Rollback automatico.", exc)
            self.rollback()
            raise

        self.step_record_and_learn()
        return self.get_session_status()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_profile(value: str) -> ProfileName:
        v = value.lower().strip().replace(" ", "_")
        try:
            return ProfileName(v)
        except ValueError:
            if "2" in v:
                return ProfileName.STAGE_2
            if "sport" in v:
                return ProfileName.SPORT
            if "eco" in v:
                return ProfileName.ECONOMY
            return ProfileName.STAGE_1

    def _default_serializer(self, maps: ECUMapSet) -> bytes:
        """Serializa un ECUMapSet a bytes para flasheo.

        Usa el binario del exportador SOLER para tener un formato
        consistente y con hash de integridad.
        """
        from backend.tuning.exporter import ExportFormat, MapExporter
        exporter = MapExporter(verifier=self.optimizer.safety_verifier)
        data, _ = exporter.to_bytes(maps, ExportFormat.BIN)
        return data

    def _mark_gate(self, gate: SessionGate) -> None:
        assert self._state is not None
        if gate.value not in self._state.gates_passed:
            self._state.gates_passed.append(gate.value)
        self._persist()

    def _require_state(self) -> None:
        if self._state is None:
            raise RuntimeError(
                "La sesion no ha sido iniciada. Llama a start_session() primero."
            )

    def _persist(self) -> None:
        if self._state is None:
            return
        p = self.sessions_root / f"{self._state.session_id}.json"
        p.write_text(
            json.dumps(self._state.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Safety verdicts (for knowledge advice API)
# ---------------------------------------------------------------------------

class SafetyVerdictLevel(str, Enum):
    SAFE = "seguro"
    CAUTION = "precaucion"
    UNSAFE = "inseguro"
    PROHIBITED = "prohibido"


@dataclass
class SafetyVerdict:
    level: SafetyVerdictLevel
    reason: str                  # en espanol
    suggestions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Professional Knowledge Engine
# ---------------------------------------------------------------------------

class ProfessionalKnowledge:
    """Base de conocimiento profesional para tuning de ECUs.

    Integra reglas de oro, errores comunes, guias paso a paso y
    conocimiento especifico diesel/gasolina. Todo en espanol.
    """

    GOLDEN_RULES: list[str] = [
        "SIEMPRE hacer backup antes de cualquier modificacion.",
        "NUNCA tunear un vehiculo con DTCs criticos activos.",
        "NUNCA exceder 38 grados de avance de encendido.",
        "NUNCA empobrecer la mezcla bajo carga (AFR > 13.5:1 gasolina).",
        "NUNCA enriquecer excesivamente (AFR < 10.5:1).",
        "NUNCA aumentar boost mas del 30% sobre stock sin hardware.",
        "NUNCA aumentar RPM limite mas del 10% sobre diseno.",
        "NUNCA tunear sin verificar en dinamometro (Stage 2+).",
        "NUNCA modificar vehiculo con problemas mecanicos.",
        "SIEMPRE verificar temperatura de gases de escape.",
        "SIEMPRE monitorear knock durante pruebas.",
        "SIEMPRE tener forma de restaurar el backup.",
    ]

    COMMON_MISTAKES: list[str] = [
        "Avanzar demasiado el encendido sin monitorear knock.",
        "No compensar inyeccion al aumentar boost.",
        "Ignorar temperatura de admision en dias calurosos.",
        "No recalibrar MAF despues de cambiar filtro de aire.",
        "Subir boost sin verificar presion de combustible.",
        "Eliminar EGR sin recalibrar mapas de aire.",
        "Flashear mapa de otro vehiculo del mismo modelo (cada ECU es unica).",
        "No considerar altitud y temperatura ambiente.",
        "Modificar demasiados parametros a la vez.",
        "No hacer datalog antes y despues para comparar.",
    ]

    STEP_BY_STEP_GUIDE: dict[str, list[str]] = {
        "pre_flight_checklist": [
            "Bateria cargada y estable (>12.6 V en reposo).",
            "Temperatura de motor nominal (80-95 C).",
            "Sin DTCs activos (o todos conocidos y no criticos).",
            "Filtro de aire reciente, bujias en buen estado.",
            "Aceite dentro del intervalo y nivel correcto.",
            "Herramienta de flasheo actualizada.",
            "Backup previo del mapa actual (aunque sea stock).",
        ],
        "connection_procedure": [
            "Conectar adaptador OBD-II con contacto en OFF.",
            "Encender contacto (ON), sin arrancar motor.",
            "Establecer comunicacion (verificar protocolo ISO-TP/UDS).",
            "Leer identificacion ECU (HW/SW/calibracion).",
            "Confirmar VIN coincide con vehiculo fisico.",
        ],
        "reading_procedure": [
            "Leer calibracion completa (rango A000-FFFF o el que aplique).",
            "Verificar checksum interno de la ECU.",
            "Calcular SHA-256 del dump.",
            "Guardar backup triple (binario + timestamp + hash).",
        ],
        "analysis_procedure": [
            "Revisar sensores en ralenti y en carga.",
            "Comparar AFR/Lambda con objetivos teoricos.",
            "Analizar STFT/LTFT para detectar fugas o restrictores.",
            "Verificar avance base y tendencia a correcciones.",
            "Correr el modulo AI para puntuar salud y elegibilidad.",
        ],
        "modification_procedure": [
            "Seleccionar perfil objetivo segun analisis.",
            "Generar mapas optimizados (fuel, ignition, boost, VVT).",
            "Correr verificacion de seguridad (hard limits).",
            "Generar reporte comparativo stock vs modificado.",
            "Simular ganancias HP/Nm/consumo.",
        ],
        "writing_procedure": [
            "Confirmacion explicita del usuario.",
            "Contacto ON, motor OFF, bateria cargada.",
            "Flashear bloque por bloque con verificacion.",
            "Leer de vuelta y comparar con datos esperados.",
            "Si no coincide: rollback inmediato al backup.",
        ],
        "verification_procedure": [
            "Borrar valores adaptativos (STFT/LTFT reset).",
            "Arrancar y monitorear sensores.",
            "Buscar nuevos DTCs.",
            "Prueba de estabilidad en ralenti (60 s).",
            "Datalog en conduccion real (crucero y WOT).",
        ],
        "post_tuning_monitoring": [
            "Revisar LTFT tras 100-200 km.",
            "Verificar EGT en pruebas agresivas.",
            "Confirmar ausencia de knock (count del sensor).",
            "Re-datalog y comparar contra el predicho.",
            "Ajustes finos iterativos si es necesario.",
        ],
    }

    DIESEL_SPECIFIC_KNOWLEDGE: dict[str, str] = {
        "injection_maps": (
            "Los mapas de inyeccion diesel modernos tienen varias inyecciones "
            "por ciclo: piloto (reduce ruido), pre-inyeccion, principal (par), "
            "y post-inyeccion (regeneracion DPF). Cada una tiene su tiempo y "
            "cantidad."
        ),
        "rail_pressure": (
            "La presion de rail determina el caudal y atomizacion. Aumentarla "
            "mejora la combustion pero debe respetarse el limite del inyector "
            "(tipicamente 1800-2200 bar en common rail moderno)."
        ),
        "smoke_limiter": (
            "Limita la cantidad maxima de combustible segun masa de aire "
            "medida. Subir el limite sin asegurar suficiente aire genera "
            "humo negro y dana el turbo/DPF."
        ),
        "dpf_regeneration": (
            "La regeneracion activa inyecta combustible en post-inyeccion "
            "para alcanzar ~600 C en el DPF. Un tuning debe respetar esta "
            "estrategia o aumentar el intervalo si mejora la combustion."
        ),
        "egr": (
            "EGR reduce NOx pero sucia admision. Reducirlo mejora respuesta "
            "pero aumenta NOx (revisar legalidad). Nunca eliminarlo sin "
            "recalibrar los mapas de aire y combustible."
        ),
        "injector_limits": (
            "Inyectores piezoelectricos (1800 bar) vs solenoides (1600 bar). "
            "Respeta los limites del fabricante; inyectores usados tienen "
            "tolerancias menores."
        ),
    }

    GASOLINE_SPECIFIC_KNOWLEDGE: dict[str, str] = {
        "lambda_closed_open_loop": (
            "Closed loop: ECU ajusta combustible con sonda O2 para lambda=1. "
            "Open loop: a plena carga, sigue el mapa de enriquecimiento sin "
            "correccion. Tuning modifica principalmente open-loop."
        ),
        "knock_detection": (
            "El sensor de detonacion detecta vibraciones caracteristicas. La "
            "ECU retrasa timing cuando las detecta. NUNCA se debe desactivar "
            "este sistema."
        ),
        "stft_ltft": (
            "STFT (Short Term Fuel Trim): correccion en tiempo real (-/+25 %). "
            "LTFT (Long Term): correccion aprendida. Valores > 10 % indican "
            "problema en sensores/mapas."
        ),
        "vvt": (
            "VVT (Variable Valve Timing) optimiza el solapamiento de valvulas. "
            "Mas avance en medios = mas torque; retardado en ralenti = mejor "
            "estabilidad."
        ),
        "port_vs_direct": (
            "Inyeccion indirecta (puerto): sistema de combustible mas simple, "
            "limpieza de valvulas asegurada. Directa (GDI): mas potencia y "
            "eficiencia, pero requiere HPFP y puede acumular carbon en valvulas."
        ),
        "flex_fuel_e85": (
            "E85 tiene mayor octanaje (~105 RON equivalente) y enfriamiento "
            "por evaporacion. Permite mas avance y boost. Requiere ~30 % mas "
            "combustible (inyectores/bomba) y sensores flex."
        ),
    }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_advice(
        self,
        vehicle_info: VehicleInfo,
        question: str,
    ) -> str:
        """Consejo profesional en espanol para una pregunta dada.

        Analiza palabras clave y devuelve asesoria integrando el
        conocimiento profesional de este modulo. Esta diseñado para
        ser consumido tambien por el AI agent (Claude) con estos
        bloques como contexto.
        """
        q = question.lower()
        parts: list[str] = []

        parts.append(
            f"Vehiculo: {vehicle_info.year} {vehicle_info.make} {vehicle_info.model} "
            f"({vehicle_info.engine}, {vehicle_info.fuel_type.value})."
        )

        # Reglas siempre relevantes
        if any(k in q for k in ("backup", "copia")):
            parts.append(
                "Regla de oro: SIEMPRE se hace backup antes de modificar. "
                "El sistema de backup triple (binario + manifiesto + hash SHA-256) "
                "debe verificarse antes de proceder."
            )

        if any(k in q for k in ("knock", "detonacion", "pistoneo")):
            parts.append(
                "La detonacion destruye pistones en segundos. Nunca desactives "
                "el sensor de knock. Monitorea su count en cada datalog."
            )

        if any(k in q for k in ("afr", "lambda", "mezcla")):
            if vehicle_info.fuel_type == FuelType.DIESEL:
                parts.append(
                    "En diesel, la mezcla se controla por cantidad inyectada y "
                    "limitador de humos. Verifica opacidad y EGT."
                )
            else:
                parts.append(
                    "En gasolina: AFR seguro a plena carga 11.8-12.8:1. "
                    "Cruising puede llegar a 14.7:1 (stoich) o un poco mas pobre. "
                    "NUNCA > 13.5:1 bajo carga."
                )

        if any(k in q for k in ("boost", "turbo", "sobrealimentacion")):
            if not vehicle_info.turbo:
                parts.append("El motor no es turboalimentado.")
            else:
                parts.append(
                    f"Boost stock estimado: {vehicle_info.design_max_boost_bar:.2f} bar. "
                    f"Limite seguro (+30 %): "
                    f"{vehicle_info.design_max_boost_bar * 1.30:.2f} bar. "
                    "Sin hardware de soporte no exceder +15 %."
                )

        if any(k in q for k in ("diesel", "egr", "dpf", "rail")):
            parts.append(self.DIESEL_SPECIFIC_KNOWLEDGE["injection_maps"])
            parts.append(self.DIESEL_SPECIFIC_KNOWLEDGE["dpf_regeneration"])

        if any(k in q for k in ("e85", "etanol", "flex")):
            parts.append(self.GASOLINE_SPECIFIC_KNOWLEDGE["flex_fuel_e85"])

        if any(k in q for k in ("stage", "etapa", "fase")):
            parts.append(
                "Stage 1: tune de calle sin hardware. +5-12 % HP. "
                "Stage 2: requiere intercooler, escape, admision. +18-35 % HP. "
                "Decision basada en salud del vehiculo y hardware disponible."
            )

        if len(parts) == 1:
            # Respuesta generica
            parts.append(
                "Aplica las reglas de oro: backup, verificar salud, respetar "
                "limites duros y hacer datalog antes y despues. Si no estas "
                "seguro, consulta al modulo de analisis AI."
            )
        return "\n\n".join(parts)

    def get_checklist(self, operation: str) -> list[str]:
        """Devuelve un checklist paso a paso para la operacion pedida."""
        key = operation.lower().strip().replace(" ", "_").replace("-", "_")

        aliases = {
            "pre_flight": "pre_flight_checklist",
            "preflight": "pre_flight_checklist",
            "connect": "connection_procedure",
            "connection": "connection_procedure",
            "read": "reading_procedure",
            "reading": "reading_procedure",
            "analyze": "analysis_procedure",
            "analysis": "analysis_procedure",
            "modify": "modification_procedure",
            "modification": "modification_procedure",
            "write": "writing_procedure",
            "writing": "writing_procedure",
            "verify": "verification_procedure",
            "verification": "verification_procedure",
            "post": "post_tuning_monitoring",
            "post_tuning": "post_tuning_monitoring",
            "monitoring": "post_tuning_monitoring",
        }
        key = aliases.get(key, key)
        return list(self.STEP_BY_STEP_GUIDE.get(key, []))

    def validate_modification(
        self,
        change_description: str,
        *,
        fuel_type: FuelType = FuelType.GASOLINE,
    ) -> SafetyVerdict:
        """Valida si una modificacion propuesta es segura.

        Analiza la descripcion en lenguaje natural contra las reglas
        de oro y bloqueos conocidos.
        """
        d = change_description.lower()

        # Bloqueos absolutos
        prohibited_patterns = [
            ("desactivar knock", "Eliminar el sensor de detonacion es prohibido."),
            ("quitar lambda", "Eliminar la sonda lambda es prohibido."),
            ("sin limitador", "Eliminar el limitador de revoluciones es prohibido."),
            ("sin rev limit", "Eliminar el limitador de revoluciones es prohibido."),
            ("afr 15", "AFR tan pobre bajo carga es extremadamente peligroso."),
            ("afr 16", "AFR tan pobre bajo carga es extremadamente peligroso."),
        ]
        for pat, reason in prohibited_patterns:
            if pat in d:
                return SafetyVerdict(
                    level=SafetyVerdictLevel.PROHIBITED,
                    reason=reason,
                    suggestions=[
                        "No realizar este cambio.",
                        "Consultar las reglas de oro.",
                    ],
                )

        # Timing excesivo
        m = re.search(r"(\d+)\s*grados?", d)
        if m and ("avance" in d or "encendido" in d or "timing" in d):
            try:
                deg = int(m.group(1))
                if deg > 38:
                    return SafetyVerdict(
                        level=SafetyVerdictLevel.UNSAFE,
                        reason=f"{deg} grados excede el limite de 38 grados BTDC.",
                        suggestions=["Reducir avance a maximo 38 grados."],
                    )
            except ValueError:
                pass

        # Boost excesivo
        m = re.search(r"\+?(\d+)\s*%\s*(de\s+)?boost", d)
        if m:
            pct = int(m.group(1))
            if pct > 30:
                return SafetyVerdict(
                    level=SafetyVerdictLevel.UNSAFE,
                    reason=f"Incremento de boost del {pct}% excede el maximo (30 %).",
                    suggestions=[
                        "Limitar boost a +30 % sobre stock.",
                        "Verificar mapa del compresor.",
                    ],
                )
            if pct > 15:
                return SafetyVerdict(
                    level=SafetyVerdictLevel.CAUTION,
                    reason=f"Incremento de boost del {pct}% requiere hardware de soporte.",
                    suggestions=[
                        "Verificar intercooler y presion de combustible.",
                        "Datalog obligatorio.",
                    ],
                )

        # RPM limit
        m = re.search(r"rpm[^\d]*(\d+)", d)
        if m:
            try:
                rpm = int(m.group(1))
                # Suponiendo un diseno de 7000 rpm por defecto
                if rpm > 7700:
                    return SafetyVerdict(
                        level=SafetyVerdictLevel.UNSAFE,
                        reason=f"Limite de {rpm} rpm excede +10 % sobre diseno tipico.",
                        suggestions=["Respetar margen de +10 % sobre diseno."],
                    )
            except ValueError:
                pass

        # Caso seguro por defecto
        return SafetyVerdict(
            level=SafetyVerdictLevel.SAFE,
            reason="No se detectaron patrones de riesgo en la descripcion.",
            suggestions=[
                "Validar contra los limites duros en safety.py.",
                "Correr simulacion de ganancias.",
                "Realizar datalog antes y despues.",
            ],
        )


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    # Enums
    "FuelType",
    "RiskLevel",
    "SessionStep",
    "SessionGate",
    "SafetyVerdictLevel",
    # Vehicle / ECU
    "VehicleInfo",
    "ECUIdentification",
    # Backup
    "BackupRecord",
    "ECUBackupManager",
    # Analyzer
    "ImprovableArea",
    "RiskAssessment",
    "PrerequisiteCheck",
    "SensorHealthReport",
    "TuningAssessment",
    "VehicleReprogramAnalyzer",
    # Optimizer
    "MapCellChange",
    "ModificationReport",
    "OptimizedMapSet",
    "ECUMapOptimizer",
    # Flash driver
    "ECUFlashDriver",
    "InMemoryFlashDriver",
    # Session
    "SessionState",
    "ReprogrammingSession",
    # Knowledge
    "SafetyVerdict",
    "ProfessionalKnowledge",
    # Constants
    "MIN_HEALTH_SCORE",
    "IDLE_STABILITY_SEC",
    "BACKUP_ROOT",
    "SESSIONS_ROOT",
]
