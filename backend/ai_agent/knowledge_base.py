"""
SOLER OBD2 AI Scanner - Base de Conocimiento Auto-Mejorable
=============================================================
Base de conocimiento que almacena cada escaneo, aprende patrones
de co-ocurrencia de DTCs, mantiene perfiles de vehiculos con rangos
normales ajustados y genera predicciones basadas en datos acumulados.

Almacenamiento: JSON + SQLite (hibrido).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Ruta por defecto de la base de datos
DEFAULT_DB_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "knowledge"


# ---------------------------------------------------------------------------
# Modelos de datos
# ---------------------------------------------------------------------------

@dataclass
class ScanRecord:
    """Registro de un escaneo completo."""
    scan_id: str
    timestamp: str
    vehicle_vin: str
    vehicle_make: str
    vehicle_model: str
    vehicle_year: int
    vehicle_engine: str
    sensors: dict[str, Any]
    dtcs: list[str]
    diagnosis: str
    health_score: float
    triggered_rules: list[str]
    root_causes: list[str]
    mileage: Optional[int] = None


@dataclass
class VehicleProfile:
    """Perfil de un vehiculo por marca/modelo/motor."""
    make: str
    model: str
    engine: str
    year_range: tuple[int, int]
    normal_ranges: dict[str, dict[str, float]]
    common_dtcs: dict[str, int]  # DTC -> frecuencia
    common_issues: list[str]
    scan_count: int = 0
    last_updated: str = ""


@dataclass
class DTCCorrelation:
    """Correlacion entre dos DTCs."""
    dtc_a: str
    dtc_b: str
    co_occurrence_count: int
    total_scans_a: int
    total_scans_b: int
    correlation_strength: float  # 0-1
    common_root_causes: list[str]
    common_fixes: list[str]


@dataclass
class KnowledgeBaseStats:
    """Estadisticas de la base de conocimiento."""
    version: int
    total_scans: int
    unique_vehicles: int
    unique_dtcs: int
    dtc_correlations: int
    vehicle_profiles: int
    last_updated: str
    db_size_bytes: int


# ---------------------------------------------------------------------------
# Base de conocimiento
# ---------------------------------------------------------------------------

class KnowledgeBase:
    """Base de conocimiento auto-mejorable para diagnostico vehicular."""

    SCHEMA_VERSION = 3

    def __init__(self, db_dir: Optional[Path] = None) -> None:
        self._db_dir = db_dir or DEFAULT_DB_DIR
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._db_dir / "knowledge.db"
        self._profiles_path = self._db_dir / "vehicle_profiles.json"
        self._version_path = self._db_dir / "version.json"

        self._conn: Optional[sqlite3.Connection] = None
        self._version: int = 0

        self._init_database()
        self._load_version()

    def close(self) -> None:
        """Cierra la conexion a la base de datos."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Inicializacion
    # ------------------------------------------------------------------

    def _init_database(self) -> None:
        """Inicializa la base de datos SQLite."""
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS scans (
                scan_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                vehicle_vin TEXT,
                vehicle_make TEXT,
                vehicle_model TEXT,
                vehicle_year INTEGER,
                vehicle_engine TEXT,
                sensors_json TEXT NOT NULL,
                dtcs_json TEXT NOT NULL,
                diagnosis TEXT,
                health_score REAL,
                triggered_rules_json TEXT,
                root_causes_json TEXT,
                mileage INTEGER,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            );

            CREATE INDEX IF NOT EXISTS idx_scans_vehicle
                ON scans(vehicle_make, vehicle_model, vehicle_year);
            CREATE INDEX IF NOT EXISTS idx_scans_timestamp
                ON scans(timestamp);
            CREATE INDEX IF NOT EXISTS idx_scans_vin
                ON scans(vehicle_vin);

            CREATE TABLE IF NOT EXISTS dtc_occurrences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id TEXT NOT NULL,
                dtc_code TEXT NOT NULL,
                vehicle_make TEXT,
                vehicle_model TEXT,
                vehicle_year INTEGER,
                FOREIGN KEY (scan_id) REFERENCES scans(scan_id)
            );

            CREATE INDEX IF NOT EXISTS idx_dtc_code
                ON dtc_occurrences(dtc_code);
            CREATE INDEX IF NOT EXISTS idx_dtc_vehicle
                ON dtc_occurrences(vehicle_make, vehicle_model);

            CREATE TABLE IF NOT EXISTS dtc_correlations (
                dtc_a TEXT NOT NULL,
                dtc_b TEXT NOT NULL,
                co_occurrence_count INTEGER DEFAULT 1,
                common_root_causes_json TEXT DEFAULT '[]',
                common_fixes_json TEXT DEFAULT '[]',
                last_updated REAL DEFAULT (strftime('%s', 'now')),
                PRIMARY KEY (dtc_a, dtc_b)
            );

            CREATE TABLE IF NOT EXISTS sensor_baselines (
                vehicle_key TEXT NOT NULL,
                sensor_name TEXT NOT NULL,
                min_value REAL,
                max_value REAL,
                avg_value REAL,
                sample_count INTEGER DEFAULT 1,
                last_updated REAL DEFAULT (strftime('%s', 'now')),
                PRIMARY KEY (vehicle_key, sensor_name)
            );

            CREATE TABLE IF NOT EXISTS learned_patterns (
                pattern_id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT NOT NULL,
                description TEXT,
                dtc_pattern_json TEXT,
                sensor_pattern_json TEXT,
                root_cause TEXT,
                confidence REAL DEFAULT 0.5,
                occurrence_count INTEGER DEFAULT 1,
                last_seen REAL DEFAULT (strftime('%s', 'now')),
                created_at REAL DEFAULT (strftime('%s', 'now'))
            );

            CREATE TABLE IF NOT EXISTS sensor_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_vin TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                sensor_name TEXT NOT NULL,
                sensor_value REAL NOT NULL,
                mileage INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_sensor_history_vin
                ON sensor_history(vehicle_vin, sensor_name, timestamp);
        """)
        self._conn.commit()

    def _load_version(self) -> None:
        """Carga la version actual de la base de conocimiento."""
        if self._version_path.exists():
            try:
                data = json.loads(self._version_path.read_text(encoding="utf-8"))
                self._version = data.get("version", 0)
            except (json.JSONDecodeError, OSError):
                self._version = 0
        else:
            self._version = 0

    def _increment_version(self) -> None:
        """Incrementa la version y la guarda."""
        self._version += 1
        self._version_path.write_text(
            json.dumps({
                "version": self._version,
                "schema_version": self.SCHEMA_VERSION,
                "updated_at": datetime.now().isoformat(),
            }, indent=2),
            encoding="utf-8",
        )

    @property
    def version(self) -> int:
        return self._version

    # ------------------------------------------------------------------
    # record_scan - Registrar un escaneo
    # ------------------------------------------------------------------

    async def record_scan(self, scan: ScanRecord) -> None:
        """Registra un escaneo completo en la base de conocimiento.

        Actualiza correlaciones, perfiles de vehiculo y patrones.
        """
        if not self._conn:
            raise RuntimeError("La base de datos no esta inicializada")

        conn = self._conn

        # Insertar escaneo
        conn.execute(
            """INSERT OR REPLACE INTO scans
               (scan_id, timestamp, vehicle_vin, vehicle_make, vehicle_model,
                vehicle_year, vehicle_engine, sensors_json, dtcs_json,
                diagnosis, health_score, triggered_rules_json, root_causes_json, mileage)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                scan.scan_id,
                scan.timestamp,
                scan.vehicle_vin,
                scan.vehicle_make,
                scan.vehicle_model,
                scan.vehicle_year,
                scan.vehicle_engine,
                json.dumps(scan.sensors),
                json.dumps(scan.dtcs),
                scan.diagnosis,
                scan.health_score,
                json.dumps(scan.triggered_rules),
                json.dumps(scan.root_causes),
                scan.mileage,
            ),
        )

        # Registrar ocurrencias de DTCs
        for dtc in scan.dtcs:
            conn.execute(
                """INSERT INTO dtc_occurrences
                   (scan_id, dtc_code, vehicle_make, vehicle_model, vehicle_year)
                   VALUES (?, ?, ?, ?, ?)""",
                (scan.scan_id, dtc, scan.vehicle_make, scan.vehicle_model, scan.vehicle_year),
            )

        # Actualizar correlaciones de DTCs
        self._update_dtc_correlations(scan.dtcs)

        # Actualizar baselines de sensores
        vehicle_key = f"{scan.vehicle_make}_{scan.vehicle_model}_{scan.vehicle_engine}".lower()
        self._update_sensor_baselines(vehicle_key, scan.sensors)

        # Registrar historial de sensores
        if scan.vehicle_vin:
            self._record_sensor_history(
                scan.vehicle_vin, scan.timestamp, scan.sensors, scan.mileage
            )

        # Detectar y almacenar patrones nuevos
        self._detect_new_patterns(scan)

        conn.commit()
        self._increment_version()

        logger.info(
            "Escaneo %s registrado. VIN=%s DTCs=%d",
            scan.scan_id, scan.vehicle_vin, len(scan.dtcs),
        )

    def _update_dtc_correlations(self, dtcs: list[str]) -> None:
        """Actualiza la tabla de co-ocurrencias de DTCs."""
        if len(dtcs) < 2 or not self._conn:
            return

        # Generar todos los pares
        sorted_dtcs = sorted(set(dtcs))
        for i in range(len(sorted_dtcs)):
            for j in range(i + 1, len(sorted_dtcs)):
                dtc_a, dtc_b = sorted_dtcs[i], sorted_dtcs[j]
                self._conn.execute(
                    """INSERT INTO dtc_correlations (dtc_a, dtc_b, co_occurrence_count)
                       VALUES (?, ?, 1)
                       ON CONFLICT(dtc_a, dtc_b) DO UPDATE SET
                           co_occurrence_count = co_occurrence_count + 1,
                           last_updated = strftime('%s', 'now')""",
                    (dtc_a, dtc_b),
                )

    def _update_sensor_baselines(
        self, vehicle_key: str, sensors: dict[str, Any]
    ) -> None:
        """Actualiza los baselines de sensores para un tipo de vehiculo."""
        if not self._conn:
            return

        for name, value in sensors.items():
            if value is None or not isinstance(value, (int, float)):
                continue

            row = self._conn.execute(
                """SELECT min_value, max_value, avg_value, sample_count
                   FROM sensor_baselines
                   WHERE vehicle_key = ? AND sensor_name = ?""",
                (vehicle_key, name),
            ).fetchone()

            if row:
                new_min = min(row["min_value"], value)
                new_max = max(row["max_value"], value)
                count = row["sample_count"] + 1
                new_avg = (row["avg_value"] * row["sample_count"] + value) / count

                self._conn.execute(
                    """UPDATE sensor_baselines
                       SET min_value = ?, max_value = ?, avg_value = ?,
                           sample_count = ?, last_updated = strftime('%s', 'now')
                       WHERE vehicle_key = ? AND sensor_name = ?""",
                    (new_min, new_max, new_avg, count, vehicle_key, name),
                )
            else:
                self._conn.execute(
                    """INSERT INTO sensor_baselines
                       (vehicle_key, sensor_name, min_value, max_value, avg_value, sample_count)
                       VALUES (?, ?, ?, ?, ?, 1)""",
                    (vehicle_key, name, value, value, value),
                )

    def _record_sensor_history(
        self,
        vin: str,
        timestamp: str,
        sensors: dict[str, Any],
        mileage: Optional[int],
    ) -> None:
        """Registra historial de sensores para analisis de tendencia."""
        if not self._conn:
            return

        for name, value in sensors.items():
            if value is None or not isinstance(value, (int, float)):
                continue
            self._conn.execute(
                """INSERT INTO sensor_history
                   (vehicle_vin, timestamp, sensor_name, sensor_value, mileage)
                   VALUES (?, ?, ?, ?, ?)""",
                (vin, timestamp, name, float(value), mileage),
            )

    def _detect_new_patterns(self, scan: ScanRecord) -> None:
        """Detecta patrones nuevos a partir de un escaneo."""
        if not self._conn or len(scan.dtcs) < 2:
            return

        dtc_pattern = json.dumps(sorted(scan.dtcs))

        # Buscar patron existente
        row = self._conn.execute(
            """SELECT pattern_id, occurrence_count, confidence
               FROM learned_patterns
               WHERE pattern_type = 'dtc_group' AND dtc_pattern_json = ?""",
            (dtc_pattern,),
        ).fetchone()

        if row:
            new_count = row["occurrence_count"] + 1
            # Aumentar confianza con mas ocurrencias (max 0.95)
            new_confidence = min(0.95, 0.3 + 0.1 * new_count)

            self._conn.execute(
                """UPDATE learned_patterns
                   SET occurrence_count = ?, confidence = ?,
                       last_seen = strftime('%s', 'now')
                   WHERE pattern_id = ?""",
                (new_count, new_confidence, row["pattern_id"]),
            )
        else:
            root_cause = scan.root_causes[0] if scan.root_causes else None
            self._conn.execute(
                """INSERT INTO learned_patterns
                   (pattern_type, description, dtc_pattern_json, root_cause, confidence)
                   VALUES ('dtc_group', ?, ?, ?, 0.3)""",
                (
                    f"Patron: {', '.join(scan.dtcs[:5])}",
                    dtc_pattern,
                    root_cause,
                ),
            )

    # ------------------------------------------------------------------
    # get_vehicle_profile - Obtener perfil de vehiculo
    # ------------------------------------------------------------------

    async def get_vehicle_profile(
        self,
        make: str,
        model: str,
        engine: str = "",
        year: Optional[int] = None,
    ) -> Optional[VehicleProfile]:
        """Obtiene el perfil de un vehiculo basado en datos historicos."""
        if not self._conn:
            return None

        vehicle_key = f"{make}_{model}_{engine}".lower()

        # Obtener baselines de sensores
        rows = self._conn.execute(
            """SELECT sensor_name, min_value, max_value, avg_value, sample_count
               FROM sensor_baselines
               WHERE vehicle_key = ?""",
            (vehicle_key,),
        ).fetchall()

        if not rows:
            return None

        normal_ranges: dict[str, dict[str, float]] = {}
        total_samples = 0

        for row in rows:
            avg = row["avg_value"]
            spread = (row["max_value"] - row["min_value"]) * 0.1
            normal_ranges[row["sensor_name"]] = {
                "min": row["min_value"],
                "max": row["max_value"],
                "ideal_min": avg - spread,
                "ideal_max": avg + spread,
                "avg": avg,
            }
            total_samples = max(total_samples, row["sample_count"])

        # DTCs comunes para este vehiculo
        common_dtcs: dict[str, int] = {}
        dtc_rows = self._conn.execute(
            """SELECT dtc_code, COUNT(*) as count
               FROM dtc_occurrences
               WHERE vehicle_make = ? AND vehicle_model = ?
               GROUP BY dtc_code
               ORDER BY count DESC
               LIMIT 20""",
            (make, model),
        ).fetchall()

        for row in dtc_rows:
            common_dtcs[row["dtc_code"]] = row["count"]

        # Scan count
        scan_count_row = self._conn.execute(
            """SELECT COUNT(*) as cnt FROM scans
               WHERE vehicle_make = ? AND vehicle_model = ?""",
            (make, model),
        ).fetchone()

        # Year range
        year_row = self._conn.execute(
            """SELECT MIN(vehicle_year) as min_y, MAX(vehicle_year) as max_y
               FROM scans
               WHERE vehicle_make = ? AND vehicle_model = ?
                 AND vehicle_year IS NOT NULL""",
            (make, model),
        ).fetchone()

        year_range = (
            year_row["min_y"] or (year or 2000),
            year_row["max_y"] or (year or 2025),
        )

        # Problemas comunes
        common_issues: list[str] = []
        issue_rows = self._conn.execute(
            """SELECT diagnosis, COUNT(*) as cnt FROM scans
               WHERE vehicle_make = ? AND vehicle_model = ?
                 AND diagnosis IS NOT NULL AND diagnosis != ''
               GROUP BY diagnosis
               ORDER BY cnt DESC
               LIMIT 5""",
            (make, model),
        ).fetchall()

        for row in issue_rows:
            common_issues.append(row["diagnosis"][:200])

        return VehicleProfile(
            make=make,
            model=model,
            engine=engine,
            year_range=year_range,
            normal_ranges=normal_ranges,
            common_dtcs=common_dtcs,
            common_issues=common_issues,
            scan_count=scan_count_row["cnt"] if scan_count_row else 0,
            last_updated=datetime.now().isoformat(),
        )

    # ------------------------------------------------------------------
    # update_thresholds - Actualizar umbrales
    # ------------------------------------------------------------------

    async def update_thresholds(
        self,
        vehicle_key: str,
        thresholds: dict[str, dict[str, float]],
    ) -> None:
        """Actualiza los umbrales de sensores para un tipo de vehiculo.

        Args:
            vehicle_key: Clave del vehiculo (make_model_engine en minusculas).
            thresholds: Diccionario de sensor -> {min, max, ideal_min, ideal_max}.
        """
        if not self._conn:
            return

        for sensor_name, values in thresholds.items():
            self._conn.execute(
                """INSERT INTO sensor_baselines
                   (vehicle_key, sensor_name, min_value, max_value, avg_value, sample_count)
                   VALUES (?, ?, ?, ?, ?, 0)
                   ON CONFLICT(vehicle_key, sensor_name) DO UPDATE SET
                       min_value = ?,
                       max_value = ?,
                       avg_value = ?,
                       last_updated = strftime('%s', 'now')""",
                (
                    vehicle_key,
                    sensor_name,
                    values.get("min", 0),
                    values.get("max", 100),
                    values.get("avg", (values.get("min", 0) + values.get("max", 100)) / 2),
                    values.get("min", 0),
                    values.get("max", 100),
                    values.get("avg", (values.get("min", 0) + values.get("max", 100)) / 2),
                ),
            )

        self._conn.commit()
        self._increment_version()

    # ------------------------------------------------------------------
    # get_correlations - Obtener correlaciones de DTCs
    # ------------------------------------------------------------------

    async def get_correlations(
        self,
        dtc_code: str,
        min_count: int = 2,
        limit: int = 20,
    ) -> list[DTCCorrelation]:
        """Obtiene DTCs que frecuentemente ocurren junto con el DTC dado.

        Args:
            dtc_code: Codigo DTC a buscar.
            min_count: Minimo de co-ocurrencias para incluir.
            limit: Maximo de resultados.

        Returns:
            Lista de correlaciones ordenadas por fuerza de correlacion.
        """
        if not self._conn:
            return []

        rows = self._conn.execute(
            """SELECT dtc_a, dtc_b, co_occurrence_count,
                      common_root_causes_json, common_fixes_json
               FROM dtc_correlations
               WHERE (dtc_a = ? OR dtc_b = ?)
                 AND co_occurrence_count >= ?
               ORDER BY co_occurrence_count DESC
               LIMIT ?""",
            (dtc_code, dtc_code, min_count, limit),
        ).fetchall()

        correlations: list[DTCCorrelation] = []

        for row in rows:
            other_dtc = row["dtc_b"] if row["dtc_a"] == dtc_code else row["dtc_a"]

            # Calcular fuerza de correlacion
            total_a = self._count_dtc_occurrences(dtc_code)
            total_b = self._count_dtc_occurrences(other_dtc)

            strength = 0.0
            if total_a > 0 and total_b > 0:
                # Jaccard-like similarity
                strength = row["co_occurrence_count"] / (total_a + total_b - row["co_occurrence_count"])

            try:
                root_causes = json.loads(row["common_root_causes_json"] or "[]")
            except json.JSONDecodeError:
                root_causes = []

            try:
                fixes = json.loads(row["common_fixes_json"] or "[]")
            except json.JSONDecodeError:
                fixes = []

            correlations.append(DTCCorrelation(
                dtc_a=dtc_code,
                dtc_b=other_dtc,
                co_occurrence_count=row["co_occurrence_count"],
                total_scans_a=total_a,
                total_scans_b=total_b,
                correlation_strength=round(strength, 3),
                common_root_causes=root_causes,
                common_fixes=fixes,
            ))

        correlations.sort(key=lambda c: c.correlation_strength, reverse=True)
        return correlations

    def _count_dtc_occurrences(self, dtc_code: str) -> int:
        """Cuenta el total de ocurrencias de un DTC."""
        if not self._conn:
            return 0
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM dtc_occurrences WHERE dtc_code = ?",
            (dtc_code,),
        ).fetchone()
        return row["cnt"] if row else 0

    # ------------------------------------------------------------------
    # get_predictions - Obtener predicciones basadas en datos historicos
    # ------------------------------------------------------------------

    async def get_predictions(
        self,
        vehicle_vin: str,
        current_dtcs: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Genera predicciones basadas en el historial del vehiculo.

        Args:
            vehicle_vin: VIN del vehiculo.
            current_dtcs: DTCs actuales para buscar patrones conocidos.

        Returns:
            Lista de predicciones con probabilidad y descripcion.
        """
        if not self._conn:
            return []

        predictions: list[dict[str, Any]] = []

        # 1. Buscar patrones de DTCs aprendidos
        if current_dtcs and len(current_dtcs) >= 1:
            for dtc in current_dtcs:
                # Buscar que otros DTCs suelen aparecer despues
                rows = self._conn.execute(
                    """SELECT dtc_b, co_occurrence_count
                       FROM dtc_correlations
                       WHERE dtc_a = ? AND co_occurrence_count >= 3
                       ORDER BY co_occurrence_count DESC
                       LIMIT 5""",
                    (dtc,),
                ).fetchall()

                for row in rows:
                    if row["dtc_b"] not in current_dtcs:
                        predictions.append({
                            "type": "dtc_prediction",
                            "description": (
                                f"Basado en {row['co_occurrence_count']} casos previos, "
                                f"el DTC {row['dtc_b']} frecuentemente aparece junto con "
                                f"{dtc}. Monitorear este sistema."
                            ),
                            "probability": min(0.9, 0.3 + row["co_occurrence_count"] * 0.05),
                            "related_dtc": row["dtc_b"],
                        })

        # 2. Buscar tendencias de sensores
        sensor_trends = await self._get_sensor_trends(vehicle_vin)
        for trend in sensor_trends:
            if trend["trend"] == "degrading":
                predictions.append({
                    "type": "sensor_degradation",
                    "description": (
                        f"El sensor '{trend['sensor']}' muestra una tendencia de "
                        f"degradacion: {trend['description']}. "
                        f"Considerar inspeccion preventiva."
                    ),
                    "probability": trend.get("confidence", 0.5),
                    "sensor": trend["sensor"],
                })

        # 3. Buscar patrones aprendidos
        if current_dtcs:
            dtc_pattern = json.dumps(sorted(current_dtcs))
            learned = self._conn.execute(
                """SELECT description, root_cause, confidence, occurrence_count
                   FROM learned_patterns
                   WHERE pattern_type = 'dtc_group'
                     AND dtc_pattern_json = ?
                     AND confidence >= 0.5""",
                (dtc_pattern,),
            ).fetchone()

            if learned:
                predictions.append({
                    "type": "learned_pattern",
                    "description": (
                        f"Patron conocido ({learned['occurrence_count']} ocurrencias previas): "
                        f"{learned['description']}. "
                        f"Causa raiz probable: {learned['root_cause'] or 'pendiente de determinar'}."
                    ),
                    "probability": learned["confidence"],
                    "root_cause": learned["root_cause"],
                })

        # Ordenar por probabilidad
        predictions.sort(key=lambda p: p["probability"], reverse=True)
        return predictions

    async def _get_sensor_trends(
        self,
        vehicle_vin: str,
        min_samples: int = 5,
    ) -> list[dict[str, Any]]:
        """Analiza tendencias de sensores para un vehiculo."""
        if not self._conn:
            return []

        trends: list[dict[str, Any]] = []

        # Obtener sensores con historial suficiente
        sensors = self._conn.execute(
            """SELECT sensor_name, COUNT(*) as cnt
               FROM sensor_history
               WHERE vehicle_vin = ?
               GROUP BY sensor_name
               HAVING cnt >= ?""",
            (vehicle_vin, min_samples),
        ).fetchall()

        for sensor_row in sensors:
            sensor_name = sensor_row["sensor_name"]

            # Obtener ultimos valores ordenados por tiempo
            values = self._conn.execute(
                """SELECT sensor_value, timestamp
                   FROM sensor_history
                   WHERE vehicle_vin = ? AND sensor_name = ?
                   ORDER BY timestamp DESC
                   LIMIT 20""",
                (vehicle_vin, sensor_name),
            ).fetchall()

            if len(values) < min_samples:
                continue

            vals = [v["sensor_value"] for v in values]

            # Analisis simple de tendencia
            first_half = vals[len(vals) // 2:]
            second_half = vals[:len(vals) // 2]

            avg_first = sum(first_half) / len(first_half) if first_half else 0
            avg_second = sum(second_half) / len(second_half) if second_half else 0

            if avg_first == 0:
                continue

            change_pct = (avg_second - avg_first) / abs(avg_first) * 100

            # Detectar tendencias significativas
            if abs(change_pct) > 10:
                direction = "aumento" if change_pct > 0 else "disminucion"
                trends.append({
                    "sensor": sensor_name,
                    "trend": "degrading",
                    "direction": direction,
                    "change_percent": round(change_pct, 1),
                    "description": (
                        f"Tendencia de {direction} del {abs(change_pct):.1f}% "
                        f"en las ultimas {len(values)} lecturas"
                    ),
                    "confidence": min(0.85, 0.4 + abs(change_pct) / 100),
                })

        return trends

    # ------------------------------------------------------------------
    # get_scan_history - Historial de escaneos
    # ------------------------------------------------------------------

    async def get_scan_history(
        self,
        vehicle_vin: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Obtiene el historial de escaneos."""
        if not self._conn:
            return []

        if vehicle_vin:
            rows = self._conn.execute(
                """SELECT scan_id, timestamp, vehicle_make, vehicle_model,
                          vehicle_year, health_score, dtcs_json, diagnosis
                   FROM scans
                   WHERE vehicle_vin = ?
                   ORDER BY timestamp DESC
                   LIMIT ? OFFSET ?""",
                (vehicle_vin, limit, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT scan_id, timestamp, vehicle_vin, vehicle_make,
                          vehicle_model, vehicle_year, health_score, dtcs_json, diagnosis
                   FROM scans
                   ORDER BY timestamp DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()

        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Estadisticas
    # ------------------------------------------------------------------

    async def get_stats(self) -> KnowledgeBaseStats:
        """Obtiene estadisticas de la base de conocimiento."""
        if not self._conn:
            return KnowledgeBaseStats(
                version=self._version,
                total_scans=0,
                unique_vehicles=0,
                unique_dtcs=0,
                dtc_correlations=0,
                vehicle_profiles=0,
                last_updated="",
                db_size_bytes=0,
            )

        total_scans = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM scans"
        ).fetchone()["cnt"]

        unique_vehicles = self._conn.execute(
            "SELECT COUNT(DISTINCT vehicle_vin) as cnt FROM scans WHERE vehicle_vin IS NOT NULL"
        ).fetchone()["cnt"]

        unique_dtcs = self._conn.execute(
            "SELECT COUNT(DISTINCT dtc_code) as cnt FROM dtc_occurrences"
        ).fetchone()["cnt"]

        dtc_correlations = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM dtc_correlations"
        ).fetchone()["cnt"]

        vehicle_profiles = self._conn.execute(
            "SELECT COUNT(DISTINCT vehicle_key) as cnt FROM sensor_baselines"
        ).fetchone()["cnt"]

        db_size = self._db_path.stat().st_size if self._db_path.exists() else 0

        return KnowledgeBaseStats(
            version=self._version,
            total_scans=total_scans,
            unique_vehicles=unique_vehicles,
            unique_dtcs=unique_dtcs,
            dtc_correlations=dtc_correlations,
            vehicle_profiles=vehicle_profiles,
            last_updated=datetime.now().isoformat(),
            db_size_bytes=db_size,
        )
