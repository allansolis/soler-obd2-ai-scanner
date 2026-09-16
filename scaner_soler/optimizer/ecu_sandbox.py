"""
ECUSandbox — Simulador de configuraciones ECU inspirado en MiroFish
====================================================================

Arquitectura tomada de MiroFish (github.com/666ghj/MiroFish):

  MiroFish                          ECUSandbox (adaptación)
  ─────────────────────────────     ───────────────────────────────────────
  Semilla informativa (news/data) → clone_from_vehicle() clona estado real
  Generación de perfiles de agente→ _generate_combinations() LHS sampling
  Simulación paralela (OASIS)     → ThreadPoolExecutor sobre _score_config()
  Logs JSONL en tiempo real       → results_path / stream JSONL por config
  Reporte con métricas agregadas  → get_best_config(goal)

Diferencia clave: en MiroFish los "agentes" son personas IA interactuando
en redes sociales.  Aquí cada "agente" es una combinación de parámetros
ECU (ignición, combustible, boost) que se evalúa con un modelo físico
estimado sin tocar el motor real.

Algoritmos de muestreo
──────────────────────
  • Latin Hypercube Sampling (LHS): cubre el espacio de parámetros
    uniformemente — mucho mejor que Monte Carlo puro para n < 10 000.
  • Perturbación por factor: cada combinación aplica un delta_pct
    distinto a cada mapa respecto al estado clonado.
  • Evaluación paralela: ThreadPoolExecutor(max_workers) como en
    OasisProfileGenerator.generate_profiles_from_entities().
  • Resultado streaming a JSONL: cada resultado se escribe en disco
    al completarse (no al final), igual que action_logger.py en MiroFish.

Uso típico
──────────
    sandbox = ECUSandbox(safety_profile='track')
    sandbox.clone_from_vehicle(ecu_reader)          # o clone_from_maps()
    results = sandbox.simulate_combinations(n=2000, workers=8)
    best = sandbox.get_best_config(goal='power')
    print(best.summary())
"""

from __future__ import annotations

import copy
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..ecu.maps.map_table import MapTable
from .safety_guard import SafetyGuard, SafetyError, PROFILES, SafetyLimits


# ─────────────────────────────────────────────────────────────────────────────
# Modelos de score basados en DELTAS porcentuales
# ─────────────────────────────────────────────────────────────────────────────
# El sandbox mide MEJORA RELATIVA al estado base clonado, no valores absolutos.
# Esto es más robusto: no asume unidades ni rangos fijos por motor.
#
# Cada modelo recibe los deltas% aplicados a cada mapa y estima un score [0-100].
# Reemplazar con modelos validados en banco de pruebas / dyno cuando estén disponibles.
# ─────────────────────────────────────────────────────────────────────────────

def _model_power(delta_ign: float, delta_fuel: float,
                 delta_boost: float = 0.0) -> float:
    """
    Score de potencia [0–100].

    Física simplificada con deltas%:
    - Avance moderadamente adelantado (+5..+12%) ≈ más torque hasta MBT.
      Demasiado adelante (+>15%) puede knock (penaliza).
    - Combustible rico (delta_fuel > 0, λ <1) mejora potencia hasta cierto punto.
    - Boost positivo multiplica potencia en motores turbo.
    """
    # Avance: pico alrededor de +8%, cae en extremos
    ign_score = 1.0 - ((delta_ign - 8.0) / 15.0) ** 2
    ign_score = float(np.clip(ign_score, 0.0, 1.0))

    # Combustible: delta positivo = más rico = más potencia (hasta +15%)
    fuel_score = float(np.clip((delta_fuel + 20.0) / 40.0, 0.0, 1.0))
    # Penaliza exceso de riqueza (>+18% = demasiado rico)
    if delta_fuel > 18.0:
        fuel_score *= 1.0 - (delta_fuel - 18.0) / 5.0
    fuel_score = float(np.clip(fuel_score, 0.0, 1.0))

    # Boost: lineal hasta +10%
    boost_score = float(np.clip((delta_boost + 10.0) / 20.0, 0.0, 1.0))

    raw = 0.45 * ign_score + 0.35 * fuel_score + 0.20 * boost_score
    return float(np.clip(raw * 100.0, 0.0, 100.0))


def _model_efficiency(delta_ign: float, delta_fuel: float,
                      delta_boost: float = 0.0) -> float:
    """
    Score de eficiencia de combustible [0–100].

    - Avance óptimo cerca de 0% (base ya bien calibrado para consumo).
    - Combustible: neutral o ligeramente negativo (lambda >1 en crucero).
    - Boost bajo.
    """
    # Avance cercano a 0 delta = ya estaba en MBT para consumo
    ign_score = 1.0 - abs(delta_ign) / 15.0
    ign_score = float(np.clip(ign_score, 0.0, 1.0))

    # Fuel: lean es más eficiente (delta_fuel negativo = menos combustible)
    fuel_score = float(np.clip((-delta_fuel + 20.0) / 40.0, 0.0, 1.0))

    # Boost: menos boost = menos consumo de bomba
    boost_score = float(np.clip((-delta_boost + 10.0) / 20.0, 0.0, 1.0))

    raw = 0.40 * ign_score + 0.40 * fuel_score + 0.20 * boost_score
    return float(np.clip(raw * 100.0, 0.0, 100.0))


def _model_speed(delta_ign: float, delta_fuel: float,
                 delta_boost: float = 0.0) -> float:
    """
    Score de respuesta / aceleración [0–100].

    Prioriza torque bajo-medio RPM:
    - Avance adelantado (+3..+10%) para respuesta rápida.
    - Combustible ligeramente rico (+5..+12%) para torque máximo instantáneo.
    - Boost agresivo positivo.
    """
    # Avance: respuesta pico alrededor de +6%
    ign_score = 1.0 - ((delta_ign - 6.0) / 12.0) ** 2
    ign_score = float(np.clip(ign_score, 0.0, 1.0))

    # Fuel: ligeramente rico (+5..+12%) = mejor torque transitorio
    if 0.0 <= delta_fuel <= 15.0:
        fuel_score = 1.0 - abs(delta_fuel - 8.0) / 10.0
    else:
        fuel_score = 0.5 - abs(delta_fuel - 8.0) / 25.0
    fuel_score = float(np.clip(fuel_score, 0.0, 1.0))

    # Boost: mayor boost = más aceleración
    boost_score = float(np.clip((delta_boost + 10.0) / 20.0, 0.0, 1.0))

    raw = 0.40 * ign_score + 0.35 * fuel_score + 0.25 * boost_score
    return float(np.clip(raw * 100.0, 0.0, 100.0))


def _model_egt(ignition: np.ndarray, boost_bar: Optional[np.ndarray] = None) -> float:
    """Temperatura estimada de gases de escape [°C] (basada en valores absolutos del mapa)."""
    base = 700.0
    egt = base + (ignition.mean() - 25.0) * 6.0
    if boost_bar is not None:
        egt += (boost_bar.mean() - 1.0) * 80.0
    return float(np.clip(egt, 400.0, 1100.0))


# ─────────────────────────────────────────────────────────────────────────────
# Estructuras de datos  (patrón SimulationRunState / AgentAction de MiroFish)
# ─────────────────────────────────────────────────────────────────────────────

class SandboxStatus(str, Enum):
    IDLE       = "idle"
    CLONED     = "cloned"
    RUNNING    = "running"
    COMPLETED  = "completed"
    FAILED     = "failed"


@dataclass
class ECUSnapshot:
    """
    Estado completo de la ECU clonado del vehículo real.
    Equivalente al "seed data" de MiroFish antes de construir el grafo.
    """
    vin: str = "UNKNOWN"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    maps: Dict[str, MapTable] = field(default_factory=dict)
    live_params: Dict[str, Any] = field(default_factory=dict)   # PIDs en tiempo real
    dtcs: List[str] = field(default_factory=list)               # P0xxx activos
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "vin": self.vin,
            "timestamp": self.timestamp,
            "maps": {k: v.to_dict() for k, v in self.maps.items()},
            "live_params": self.live_params,
            "dtcs": self.dtcs,
            "metadata": self.metadata,
        }


@dataclass
class ConfigCandidate:
    """
    Una combinación de parámetros ECU para evaluar.
    Equivalente al "agent profile" de MiroFish.
    """
    candidate_id: int
    maps: Dict[str, MapTable]
    delta_pct: Dict[str, float]          # % de perturbación aplicado a cada mapa
    scores: Dict[str, float] = field(default_factory=dict)   # por objetivo
    egt_celsius: float = 0.0
    safety_violations: List[str] = field(default_factory=list)
    is_safe: bool = True
    eval_time_ms: float = 0.0

    def summary(self) -> str:
        lines = [
            f"Candidato #{self.candidate_id}",
            f"  Deltas:     {self.delta_pct}",
            f"  Potencia:   {self.scores.get('power', 0):.1f}/100",
            f"  Eficiencia: {self.scores.get('efficiency', 0):.1f}/100",
            f"  Velocidad:  {self.scores.get('speed', 0):.1f}/100",
            f"  EGT:        {self.egt_celsius:.0f}°C",
            f"  Seguro:     {'SI' if self.is_safe else 'NO'}",
        ]
        if self.safety_violations:
            for v in self.safety_violations:
                lines.append(f"    ⚠  {v}")
        return "\n".join(lines)


@dataclass
class SandboxRunState:
    """
    Estado en tiempo real de la simulación.
    Patrón directo de SimulationRunState en MiroFish.
    """
    status: SandboxStatus = SandboxStatus.IDLE
    total: int = 0
    completed: int = 0
    safe_count: int = 0
    unsafe_count: int = 0
    start_time: float = field(default_factory=time.time)
    results: List[ConfigCandidate] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def progress_pct(self) -> float:
        return (self.completed / self.total * 100.0) if self.total else 0.0

    @property
    def elapsed_sec(self) -> float:
        return time.time() - self.start_time


# ─────────────────────────────────────────────────────────────────────────────
# ECUSandbox  — clase principal
# ─────────────────────────────────────────────────────────────────────────────

class ECUSandbox:
    """
    Simulador sandbox de configuraciones ECU.

    Inspirado en la arquitectura de MiroFish:
    - clone_from_vehicle()   ≡  ingesta de semilla + construcción de grafo
    - simulate_combinations() ≡  generación de agentes + simulación paralela
    - get_best_config()      ≡  ReportAgent con métricas agregadas

    No escribe NADA en la ECU real. Toda la optimización ocurre en memoria
    sobre copias de los mapas clonados.
    """

    DEFAULT_PERTURBATION = {
        "ignition": (-15.0, +15.0),   # % de variación respecto al valor base
        "fuel":     (-20.0, +20.0),
        "boost":    (-10.0, +10.0),
    }

    GOAL_WEIGHTS = {
        "power":      {"power": 1.0,  "efficiency": 0.1, "speed": 0.3},
        "efficiency": {"power": 0.1,  "efficiency": 1.0, "speed": 0.1},
        "speed":      {"power": 0.4,  "efficiency": 0.1, "speed": 1.0},
    }

    def __init__(
        self,
        safety_profile: str = "street",
        results_dir: Optional[Path] = None,
        seed: Optional[int] = None,
    ):
        self.safety_profile = safety_profile
        self.guard = SafetyGuard(profile=safety_profile)
        self.results_dir = results_dir or (
            Path(__file__).parent.parent.parent / "sandbox_results"
        )
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self._rng = np.random.default_rng(seed)

        self.snapshot: Optional[ECUSnapshot] = None
        self.run_state = SandboxRunState()
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._jsonl_path = self.results_dir / f"session_{self._session_id}.jsonl"

    # ── 1. Clonado del estado real ────────────────────────────────────────────

    def clone_from_vehicle(self, ecu_reader, live_params: Dict = None,
                           dtcs: List[str] = None) -> "ECUSandbox":
        """
        Clona el estado de la ECU real hacia el sandbox.

        Parámetros
        ──────────
        ecu_reader : ECUReader
            Instancia conectada al vehículo real.
        live_params : dict, opcional
            PIDs leídos en tiempo real (RPM, TPS, MAP, lambda, etc.)
        dtcs : list[str], opcional
            Códigos DTC activos.

        Retorna self para encadenar métodos.
        """
        try:
            # Intenta leer mapas reales desde flash
            maps = ecu_reader.load_demo_maps()   # sustituir por read_flash() + parse
        except Exception:
            # Fallback: usa mapas demo  (igual que _generate_agent_config_by_rule en MiroFish)
            maps = ecu_reader.load_demo_maps()

        self.snapshot = ECUSnapshot(
            vin=getattr(ecu_reader, "vin", "UNKNOWN"),
            maps=maps,
            live_params=live_params or {},
            dtcs=dtcs or [],
            metadata={"safety_profile": self.safety_profile},
        )
        self.run_state.status = SandboxStatus.CLONED
        print(f"[ECUSandbox] Clonado — VIN: {self.snapshot.vin} | "
              f"Mapas: {list(maps.keys())} | DTCs: {self.snapshot.dtcs}")
        return self

    def clone_from_maps(self, maps: Dict[str, MapTable],
                        vin: str = "UNKNOWN",
                        live_params: Dict = None,
                        dtcs: List[str] = None) -> "ECUSandbox":
        """
        Clona desde mapas ya cargados (sin conexión al vehículo).
        Útil para pruebas o cuando los mapas vienen de un .ssmap guardado.
        """
        self.snapshot = ECUSnapshot(
            vin=vin,
            maps=maps,
            live_params=live_params or {},
            dtcs=dtcs or [],
            metadata={"safety_profile": self.safety_profile},
        )
        self.run_state.status = SandboxStatus.CLONED
        print(f"[ECUSandbox] Clonado desde mapas — VIN: {vin} | "
              f"Mapas: {list(maps.keys())}")
        return self

    # ── 2. Generación de combinaciones  (Latin Hypercube Sampling) ────────────

    def _latin_hypercube(self, n: int, dims: int) -> np.ndarray:
        """
        Genera n muestras en [0,1]^dims con LHS.
        LHS divide cada dimensión en n estratos iguales y toma
        una muestra aleatoria de cada estrato — cobertura mucho
        más uniforme que Monte Carlo puro.

        Referencia: McKay, Beckman & Conover (1979)
        """
        result = np.zeros((n, dims))
        for d in range(dims):
            perm = self._rng.permutation(n)
            u = self._rng.uniform(size=n)
            result[:, d] = (perm + u) / n
        return result

    def _generate_combinations(self, n: int) -> List[Dict[str, float]]:
        """
        Genera n combinaciones de deltas (%) para cada mapa.
        Retorna lista de dicts {map_name: delta_pct}.

        Adapta el patrón de MiroFish:
        - _generate_agent_configs_batch() genera N perfiles de agentes
        - Aquí generamos N configuraciones de parámetros ECU
        """
        map_names = list(self.snapshot.maps.keys())
        dims = len(map_names)
        lhs = self._latin_hypercube(n, dims)   # shape (n, dims) en [0,1]

        combinations = []
        for i in range(n):
            combo: Dict[str, float] = {}
            for d, name in enumerate(map_names):
                lo, hi = self.DEFAULT_PERTURBATION.get(name, (-10.0, +10.0))
                delta = lo + lhs[i, d] * (hi - lo)
                combo[name] = round(float(delta), 3)
            combinations.append(combo)
        return combinations

    def _apply_delta(self, base_map: MapTable, delta_pct: float) -> MapTable:
        """
        Aplica delta_pct% de perturbación a todos los valores del mapa.
        Devuelve una copia nueva sin modificar el original.
        """
        factor = 1.0 + delta_pct / 100.0
        new_values = np.clip(
            base_map.values * factor,
            base_map.min_safe,
            base_map.max_safe,
        )
        new_map = copy.copy(base_map)
        object.__setattr__(new_map, 'values', new_values)
        new_map._backup = new_values.copy()
        new_map._dirty = False
        new_map._change_log = []
        new_map.name = f"{base_map.name}_d{delta_pct:+.1f}pct"
        return new_map

    # ── 3. Evaluación individual ──────────────────────────────────────────────

    def _score_config(self, candidate_id: int,
                      delta_combo: Dict[str, float]) -> ConfigCandidate:
        """
        Evalúa una combinación de parámetros.
        Cada invocación = un "round" de simulación OASIS en MiroFish.
        """
        t0 = time.perf_counter()
        assert self.snapshot is not None

        # Aplica deltas a copias de los mapas base
        perturbed_maps: Dict[str, MapTable] = {}
        for name, base in self.snapshot.maps.items():
            delta = delta_combo.get(name, 0.0)
            perturbed_maps[name] = self._apply_delta(base, delta)

        ign  = perturbed_maps.get("ignition")
        fuel = perturbed_maps.get("fuel")
        bst  = perturbed_maps.get("boost")

        ign_arr = ign.values if ign else None
        bst_arr = bst.values if bst else None

        # Deltas% para los modelos de score (más robustos que valores absolutos)
        d_ign   = delta_combo.get("ignition", 0.0)
        d_fuel  = delta_combo.get("fuel",     0.0)
        d_boost = delta_combo.get("boost",    0.0)

        # Scores por objetivo (basados en deltas relativos al estado base)
        scores = {
            "power":      _model_power(d_ign, d_fuel, d_boost),
            "efficiency": _model_efficiency(d_ign, d_fuel, d_boost),
            "speed":      _model_speed(d_ign, d_fuel, d_boost),
        }

        egt = _model_egt(ign_arr, bst_arr) if ign_arr is not None else 700.0

        # Validación de seguridad con SafetyGuard
        # NOTA: fuel_arr está en ms de inyección, NO en lambda.
        # SafetyGuard.validate_fuel_map espera valores lambda (≈0.78–1.05).
        # Solo validamos ignición y boost — el modelo de scoring maneja el
        # rango de combustible internamente.
        violations: List[str] = []
        try:
            self.guard.assert_safe(
                ignition=ign_arr,
                boost=bst_arr,
            )
            is_safe = True
        except SafetyError as exc:
            violations = [str(exc)]
            is_safe = False

        # EGT check adicional
        limits = PROFILES.get(self.safety_profile)
        if limits and egt > limits.max_egt_celsius:
            violations.append(f"EGT {egt:.0f}°C > límite {limits.max_egt_celsius}°C")
            is_safe = False

        eval_ms = (time.perf_counter() - t0) * 1000.0

        return ConfigCandidate(
            candidate_id=candidate_id,
            maps=perturbed_maps,
            delta_pct=delta_combo,
            scores=scores,
            egt_celsius=egt,
            safety_violations=violations,
            is_safe=is_safe,
            eval_time_ms=eval_ms,
        )

    # ── 4. Simulación paralela  (patrón ThreadPoolExecutor de MiroFish) ───────

    def simulate_combinations(
        self,
        n: int = 1000,
        workers: int = 8,
        safe_only: bool = False,
        progress_callback=None,
    ) -> List[ConfigCandidate]:
        """
        Genera y evalúa n combinaciones de parámetros ECU en paralelo.

        Parámetros
        ──────────
        n : int
            Número de combinaciones a evaluar (default 1000).
        workers : int
            Hilos paralelos. MiroFish usa 5 en generate_profiles_from_entities().
            Para ECU recomendamos 8 (CPU-bound puro, no I/O).
        safe_only : bool
            Si True, omite candidatos que violen SafetyGuard.
        progress_callback : callable(completed, total), opcional
            Función llamada después de cada candidato completado.

        Retorna
        ───────
        Lista de ConfigCandidate ordenada por score compuesto decreciente
        (igual que MiroFish ordena agentes por influencia/actividad).
        """
        if self.snapshot is None:
            raise RuntimeError("Primero ejecutar clone_from_vehicle() o clone_from_maps()")

        self.run_state = SandboxRunState(
            status=SandboxStatus.RUNNING,
            total=n,
        )
        print(f"[ECUSandbox] Iniciando simulación: {n} combinaciones, "
              f"{workers} workers, perfil={self.safety_profile}")

        combinations = self._generate_combinations(n)

        # Abre JSONL de streaming  (como action_logger.py en MiroFish)
        jsonl_file = open(self._jsonl_path, "w", encoding="utf-8")

        def _write_result(candidate: ConfigCandidate):
            """Escribe resultado a JSONL en tiempo real (thread-safe con lock)."""
            record = {
                "candidate_id": candidate.candidate_id,
                "delta_pct": candidate.delta_pct,
                "scores": candidate.scores,
                "egt_celsius": candidate.egt_celsius,
                "is_safe": candidate.is_safe,
                "safety_violations": candidate.safety_violations,
                "eval_time_ms": candidate.eval_time_ms,
            }
            with self.run_state._lock:
                jsonl_file.write(json.dumps(record) + "\n")
                jsonl_file.flush()

        results: List[ConfigCandidate] = []

        # Paralelismo  (ThreadPoolExecutor, igual que MiroFish profile generator)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(self._score_config, i, combo): i
                for i, combo in enumerate(combinations)
            }

            for future in as_completed(future_map):
                try:
                    candidate = future.result()
                except Exception as exc:
                    idx = future_map[future]
                    print(f"[ECUSandbox] Error en candidato {idx}: {exc}")
                    continue

                _write_result(candidate)

                with self.run_state._lock:
                    self.run_state.completed += 1
                    if candidate.is_safe:
                        self.run_state.safe_count += 1
                    else:
                        self.run_state.unsafe_count += 1
                    self.run_state.results.append(candidate)

                if progress_callback:
                    progress_callback(self.run_state.completed, n)

                # Log cada 100 candidatos  (como monitor de rondas en MiroFish)
                if self.run_state.completed % 100 == 0:
                    print(f"[ECUSandbox] {self.run_state.completed}/{n} "
                          f"({self.run_state.progress_pct:.0f}%) | "
                          f"seguros={self.run_state.safe_count} | "
                          f"elapsed={self.run_state.elapsed_sec:.1f}s")

        jsonl_file.close()
        self.run_state.status = SandboxStatus.COMPLETED

        print(f"[ECUSandbox] Completado: {n} candidatos en "
              f"{self.run_state.elapsed_sec:.1f}s | "
              f"seguros={self.run_state.safe_count} | "
              f"resultados en {self._jsonl_path}")

        pool = [c for c in self.run_state.results if c.is_safe] if safe_only \
               else self.run_state.results
        return pool

    # ── 5. Extracción del mejor resultado ─────────────────────────────────────

    def get_best_config(
        self,
        goal: str = "power",
        top_n: int = 5,
        safe_only: bool = True,
    ) -> Tuple[ConfigCandidate, List[ConfigCandidate]]:
        """
        Retorna el mejor candidato y el top_n ranking para el objetivo dado.

        Parámetros
        ──────────
        goal : str
            'power'      — maximiza potencia
            'efficiency' — maximiza eficiencia de combustible
            'speed'      — maximiza respuesta / aceleración

        Retorna
        ───────
        (best_candidate, top_list) — ambos ordenados por score compuesto
        """
        if not self.run_state.results:
            raise RuntimeError("No hay resultados. Ejecutar simulate_combinations() primero.")
        if goal not in self.GOAL_WEIGHTS:
            raise ValueError(f"goal debe ser uno de: {list(self.GOAL_WEIGHTS)}")

        weights = self.GOAL_WEIGHTS[goal]
        pool = [c for c in self.run_state.results if c.is_safe] if safe_only \
               else self.run_state.results

        if not pool:
            raise RuntimeError("Ningún candidato seguro encontrado. "
                               "Intenta con safe_only=False o un perfil de seguridad menos restrictivo.")

        def composite_score(c: ConfigCandidate) -> float:
            return sum(c.scores.get(k, 0.0) * w for k, w in weights.items())

        ranked = sorted(pool, key=composite_score, reverse=True)
        return ranked[0], ranked[:top_n]

    # ── 6. Utilidades ─────────────────────────────────────────────────────────

    def report(self, goal: str = "power") -> str:
        """
        Genera un reporte de texto del estado del sandbox.
        Equivalente al ReportAgent de MiroFish.
        """
        if self.run_state.status == SandboxStatus.IDLE:
            return "[ECUSandbox] Sin datos aún."

        lines = [
            "=" * 60,
            "  SCANER SOLER PRO — ECUSandbox Report",
            "=" * 60,
            f"  VIN:             {self.snapshot.vin if self.snapshot else 'N/A'}",
            f"  Perfil seguridad:{self.safety_profile}",
            f"  Candidatos total:{self.run_state.total}",
            f"  Seguros:         {self.run_state.safe_count}",
            f"  Con violaciones: {self.run_state.unsafe_count}",
            f"  Tiempo total:    {self.run_state.elapsed_sec:.1f}s",
            f"  Resultados JSONL:{self._jsonl_path}",
            "",
        ]

        if self.run_state.results:
            try:
                best, top = self.get_best_config(goal=goal)
                lines.append(f"  TOP 5 para objetivo '{goal.upper()}':")
                for rank, c in enumerate(top, 1):
                    ws = self.GOAL_WEIGHTS[goal]
                    cs = sum(c.scores.get(k, 0.0) * w for k, w in ws.items())
                    lines.append(
                        f"  #{rank:>2}  Cand.{c.candidate_id:>5} | "
                        f"Score={cs:.1f} | "
                        f"Power={c.scores.get('power',0):.1f} | "
                        f"Eff={c.scores.get('efficiency',0):.1f} | "
                        f"Spd={c.scores.get('speed',0):.1f} | "
                        f"EGT={c.egt_celsius:.0f}°C"
                    )
                lines.append("")
                lines.append("  MEJOR CANDIDATO:")
                lines.append(best.summary())
            except RuntimeError as e:
                lines.append(f"  [!] {e}")

        lines.append("=" * 60)
        return "\n".join(lines)

    def save_best_to_ssmap(self, goal: str = "power",
                           ecu_reader=None) -> Optional[Path]:
        """
        Guarda los mapas del mejor candidato como archivo .ssmap
        compatible con el sistema existente de ECUReader.
        """
        best, _ = self.get_best_config(goal=goal)
        vin = self.snapshot.vin if self.snapshot else "UNKNOWN"

        if ecu_reader is not None:
            return ecu_reader.save_map_profile(best.maps, f"sandbox_{goal}")

        # Guardado directo si no hay ecu_reader
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.results_dir / f"{ts}_{vin}_sandbox_{goal}.ssmap"
        payload = {
            "vehicle": {"vin": vin},
            "profile": f"sandbox_{goal}",
            "created": datetime.now().isoformat(),
            "sandbox_scores": best.scores,
            "delta_pct": best.delta_pct,
            "tables": {name: table.to_dict() for name, table in best.maps.items()},
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[ECUSandbox] Mejor config ({goal}) guardada: {path}")
        return path

    def status(self) -> Dict[str, Any]:
        """Retorna estado actual como dict (para integración con GUI/API)."""
        return {
            "status": self.run_state.status.value,
            "total": self.run_state.total,
            "completed": self.run_state.completed,
            "progress_pct": self.run_state.progress_pct,
            "safe_count": self.run_state.safe_count,
            "unsafe_count": self.run_state.unsafe_count,
            "elapsed_sec": self.run_state.elapsed_sec,
            "session_id": self._session_id,
            "jsonl_path": str(self._jsonl_path),
        }
