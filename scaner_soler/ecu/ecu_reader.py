import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np

from ..comm.vehicle_conn import VehicleConnection
from .maps.map_table import MapTable
from ..optimizer.safety_guard import SafetyGuard
from scaner_soler.exceptions import SafetyError

BACKUPS_DIR = Path(__file__).parent.parent.parent / "backups"
MAPS_DIR    = Path(__file__).parent.parent.parent / "maps"

# Default map definitions for a generic 4-cylinder engine
DEFAULT_MAP_DEFS = {
    "ignition": {
        "unit": "deg BTDC",
        "min_safe": -10.0,
        "max_safe": 45.0,
        "description": "Ignition timing advance table",
        "rpm_axis": [600,800,1000,1500,2000,2500,3000,3500,4000,4500,5000,5500,6000,6500,7000,7500],
        "load_axis": [10,15,20,25,30,35,40,50,60,70,80,90,100],
    },
    "fuel": {
        "unit": "ms",
        "min_safe": 0.5,
        "max_safe": 25.0,
        "description": "Base fuel injection pulse width",
        "rpm_axis": [600,800,1000,1500,2000,2500,3000,3500,4000,4500,5000,5500,6000,6500,7000,7500],
        "load_axis": [10,15,20,25,30,35,40,50,60,70,80,90,100],
    },
    "boost": {
        "unit": "bar abs",
        "min_safe": 0.8,
        "max_safe": 2.5,
        "description": "Boost / wastegate target pressure",
        "rpm_axis": [1000,1500,2000,2500,3000,3500,4000,4500,5000,5500,6000,6500,7000],
        "load_axis": [20,30,40,50,60,70,80,90,100],
    },
}

# ── Mapas de rendimiento por marca ─────────────────────────────────────────────
#   lambda_target : AFR objetivo (lambda 0.75-1.05, 1.0 = estequiométrico)
#   vvt_intake    : avance VVT árbol admisión (grados de cigüeñal)
#   vvt_exhaust   : avance VVT árbol escape
#   knock_retard  : retardo máximo por detonación (deg)
#   rev_limit     : limitador de RPM por temperatura refrigerante
PERFORMANCE_MAP_DEFS: dict[str, dict] = {
    "VW_Bosch_ME17": {
        "lambda_target": {
            "unit": "lambda",
            "min_safe": 0.75, "max_safe": 1.05,
            "description": "AFR objetivo (1.0 = 14.7:1 gasolina)",
            "rpm_axis": [800,1200,1600,2000,2500,3000,3500,4000,5000,6200],
            "load_axis": [20,30,40,50,60,70,80,90,100],
            "base": 1.00,
            "wot_enrich": 0.87,    # enriquecimiento a plena carga
        },
        "vvt_intake": {
            "unit": "deg CAM",
            "min_safe": 0.0, "max_safe": 40.0,
            "description": "Avance árbol admisión (VVT/VANOS)",
            "rpm_axis": [800,1200,1600,2000,2500,3000,3500,4000,5000,6200],
            "load_axis": [20,40,60,80,100],
            "base": 20.0,
        },
        "knock_retard": {
            "unit": "deg",
            "min_safe": 0.0, "max_safe": 8.0,
            "description": "Retardo máximo por detonación por cilindro",
            "rpm_axis": [2000,2500,3000,3500,4000,5000,6000],
            "load_axis": [60,70,80,90,100],
            "base": 0.0,
        },
    },
    "Toyota_Denso": {
        "lambda_target": {
            "unit": "lambda",
            "min_safe": 0.78, "max_safe": 1.02,
            "description": "AFR objetivo Toyota D-4S",
            "rpm_axis": [700,1000,1500,2000,2500,3000,4000,5000,6000,7000],
            "load_axis": [15,25,40,60,80,100],
            "base": 1.00, "wot_enrich": 0.88,
        },
        "vvt_intake": {
            "unit": "deg CAM",
            "min_safe": 0.0, "max_safe": 50.0,
            "description": "Avance VVT-i admisión",
            "rpm_axis": [700,1000,1500,2000,2500,3000,4000,5000,6000,7000],
            "load_axis": [15,30,50,80,100],
            "base": 25.0,
        },
        "vvt_exhaust": {
            "unit": "deg CAM",
            "min_safe": 0.0, "max_safe": 30.0,
            "description": "Avance VVT-iE escape",
            "rpm_axis": [700,1000,1500,2000,2500,3000,4000,5000,6000,7000],
            "load_axis": [15,30,50,80,100],
            "base": 10.0,
        },
    },
    "BMW_Bosch_MSD80": {
        "lambda_target": {
            "unit": "lambda",
            "min_safe": 0.75, "max_safe": 1.02,
            "description": "AFR objetivo BMW N54/N55",
            "rpm_axis": [600,1000,1500,2000,3000,4000,5000,6000,7000,8000],
            "load_axis": [10,20,30,40,50,60,70,80,90,100],
            "base": 1.00, "wot_enrich": 0.85,
        },
        "vvt_intake": {
            "unit": "deg CAM",
            "min_safe": 0.0, "max_safe": 60.0,
            "description": "VANOS admisión",
            "rpm_axis": [600,1000,1500,2000,3000,4000,5000,6000,7000,8000],
            "load_axis": [20,40,60,80,100],
            "base": 30.0,
        },
        "vvt_exhaust": {
            "unit": "deg CAM",
            "min_safe": 0.0, "max_safe": 40.0,
            "description": "VANOS escape",
            "rpm_axis": [600,1000,1500,2000,3000,4000,5000,6000,7000,8000],
            "load_axis": [20,40,60,80,100],
            "base": 15.0,
        },
        "knock_retard": {
            "unit": "deg",
            "min_safe": 0.0, "max_safe": 10.0,
            "description": "Retardo knock cil. 1-6 (MSD80)",
            "rpm_axis": [2000,2500,3000,3500,4000,5000,6000,7000],
            "load_axis": [60,70,80,90,100],
            "base": 0.0,
        },
    },
    "Ford_PCM": {
        "lambda_target": {
            "unit": "lambda",
            "min_safe": 0.80, "max_safe": 1.03,
            "description": "AFR objetivo Ford EcoBoost",
            "rpm_axis": [700,1000,1500,2000,2500,3000,4000,5000,6000],
            "load_axis": [20,35,50,65,80,100],
            "base": 1.00, "wot_enrich": 0.88,
        },
        "rev_limit": {
            "unit": "RPM",
            "min_safe": 3000.0, "max_safe": 7000.0,
            "description": "Limitador RPM por temperatura refrigerante (°C axis)",
            "rpm_axis": [50,60,70,80,90,100,105,110],   # temperatura eje X
            "load_axis": [1.0],                           # dummy axis
            "base": 6500.0,
        },
    },
    "Chevrolet_Delphi_E38": {
        "lambda_target": {
            "unit": "lambda",
            "min_safe": 0.78, "max_safe": 1.03,
            "description": "AFR objetivo Delphi E38 LS3",
            "rpm_axis": [600,900,1200,1800,2400,3000,4000,5500,7000],
            "load_axis": [20,40,60,80,100],
            "base": 1.00, "wot_enrich": 0.86,
        },
        "knock_retard": {
            "unit": "deg",
            "min_safe": 0.0, "max_safe": 12.0,
            "description": "Retardo knock LS3 (por cil.)",
            "rpm_axis": [2000,3000,4000,5000,6000,7000],
            "load_axis": [60,80,100],
            "base": 0.0,
        },
    },
    "Honda_Keihin": {
        "lambda_target": {
            "unit": "lambda",
            "min_safe": 0.80, "max_safe": 1.02,
            "description": "AFR objetivo Honda K-series",
            "rpm_axis": [750,1000,1500,2000,3000,4000,5500,7000],
            "load_axis": [20,40,60,80,100],
            "base": 1.00, "wot_enrich": 0.89,
        },
        "vvt_intake": {
            "unit": "deg CAM",
            "min_safe": 0.0, "max_safe": 50.0,
            "description": "i-VTEC admisión (continuo)",
            "rpm_axis": [750,1000,1500,2000,3000,4000,5500,7000],
            "load_axis": [20,40,60,80,100],
            "base": 20.0,
        },
    },
    "Nissan_Hitachi": {
        "lambda_target": {
            "unit": "lambda",
            "min_safe": 0.78, "max_safe": 1.02,
            "description": "AFR objetivo Hitachi MEC90310",
            "rpm_axis": [650,1000,1600,2200,3000,4000,5500,7000],
            "load_axis": [20,40,60,80,100],
            "base": 1.00, "wot_enrich": 0.87,
        },
        "vvt_intake": {
            "unit": "deg CAM",
            "min_safe": 0.0, "max_safe": 50.0,
            "description": "CVTC admisión Nissan",
            "rpm_axis": [650,1000,1600,2200,3000,4000,5500,7000],
            "load_axis": [20,40,60,80,100],
            "base": 22.0,
        },
    },
    "Renault_Siemens": {
        "lambda_target": {
            "unit": "lambda",
            "min_safe": 0.80, "max_safe": 1.03,
            "description": "AFR objetivo Siemens SID305",
            "rpm_axis": [700,1100,1600,2200,3000,4000,5000,6000],
            "load_axis": [20,40,60,80,100],
            "base": 1.00, "wot_enrich": 0.89,
        },
    },
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ECUReader:

    def __init__(self, conn: VehicleConnection, vin: str = "UNKNOWN"):
        self.conn = conn
        self.vin = vin
        self.guard = SafetyGuard()
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        MAPS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Flash read ─────────────────────────────────────────────────────────

    def read_flash(self) -> bytes:
        """Read full ECU flash. Always saves a backup before returning."""
        data = self.conn.read_full_flash()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUPS_DIR / f"{ts}_{self.vin}.bin"
        backup_path.write_bytes(data)
        print(f"[ECUReader] Backup guardado: {backup_path}  SHA256: {_sha256(data)[:16]}")
        return data

    # ── Flash write (with full safety protocol) ────────────────────────────

    def write_flash(self, data: bytes, require_backup: bool = True) -> bool:
        """
        Write flash to ECU.
        1. Verify a backup exists for this VIN.
        2. Verify readback after write.
        """
        if require_backup:
            existing_backups = list(BACKUPS_DIR.glob(f"*{self.vin}*.bin"))
            if not existing_backups:
                raise SafetyError(
                    f"No se encontro backup para VIN {self.vin}. "
                    f"Ejecutar read_flash() primero."
                )

        hash_before = _sha256(data)
        ok = self.conn.write_full_flash(data)
        if not ok:
            raise IOError("ECU reporto error durante la escritura del flash.")

        # Verify readback
        readback = self.conn.read_full_flash()
        hash_after = _sha256(readback)
        if hash_before != hash_after:
            raise IOError(
                f"Verificacion post-escritura FALLO. "
                f"Hash original: {hash_before[:16]} | Readback: {hash_after[:16]}"
            )

        print(f"[ECUReader] Flash escrito y verificado OK. SHA256: {hash_after[:16]}")
        return True

    # ── Performance maps ───────────────────────────────────────────────────

    def load_performance_maps(self, brand_key: str,
                               auto_backup: bool = True) -> dict[str, MapTable]:
        """
        Carga los mapas de rendimiento para una marca/ECU específica.

        brand_key: clave de PERFORMANCE_MAP_DEFS (ej. 'VW_Bosch_ME17').
        auto_backup=True: activa backup automático en BACKUPS_DIR antes del
                          primer cambio en cada tabla.

        Mapas incluidos según marca:
          lambda_target  — objetivo AFR/lambda
          vvt_intake     — avance VVT/VANOS admisión
          vvt_exhaust    — avance VVT/VANOS escape
          knock_retard   — retardo máximo por detonación
          rev_limit      — limitador RPM por temperatura

        Retorna dict[nombre, MapTable] listo para editar con MapEditor.
        """
        brand_defs = PERFORMANCE_MAP_DEFS.get(brand_key)
        if brand_defs is None:
            available = ", ".join(PERFORMANCE_MAP_DEFS.keys())
            raise ValueError(
                f"Marca '{brand_key}' no encontrada. "
                f"Disponibles: {available}"
            )
        rng = np.random.default_rng(0)
        maps: dict[str, MapTable] = {}
        for map_name, defn in brand_defs.items():
            rpm_axis  = np.array(defn["rpm_axis"], dtype=float)
            load_axis = np.array(defn["load_axis"], dtype=float)
            rows, cols = len(rpm_axis), len(load_axis)
            base      = float(defn["base"])
            wot       = float(defn.get("wot_enrich", base))

            if map_name == "lambda_target":
                # Estequiométrico en parcial, enriquecido en WOT
                vals = np.full((rows, cols), base)
                vals[:, -2:] = wot          # últimas 2 columnas = WOT
                vals[:, -1]  = wot
                vals = vals + rng.normal(0, 0.002, (rows, cols))
            elif map_name in ("vvt_intake", "vvt_exhaust"):
                # Curva típica VVT: máximo en media carga/RPM
                rpm_factor  = np.sin(np.linspace(0, np.pi, rows))
                load_factor = np.linspace(0.5, 1.0, cols)
                vals = base * rpm_factor[:, None] * load_factor[None, :]
                vals = np.clip(vals, defn["min_safe"], defn["max_safe"])
            elif map_name == "knock_retard":
                vals = np.zeros((rows, cols))  # sin retardo en condiciones normales
            elif map_name == "rev_limit":
                # Límite de RPM decrece con temperatura excesiva
                vals = np.full((rows, cols), base)
                for i, temp in enumerate(rpm_axis):
                    if temp >= 105:
                        vals[i, :] = base * 0.80
                    elif temp >= 100:
                        vals[i, :] = base * 0.90
            else:
                vals = np.full((rows, cols), base)

            tabla = MapTable(
                name=f"{brand_key}_{map_name}",
                rpm_axis=rpm_axis,
                load_axis=load_axis,
                values=vals.astype(np.float64),
                unit=defn["unit"],
                min_safe=defn["min_safe"],
                max_safe=defn["max_safe"],
                description=defn["description"],
            )
            if auto_backup:
                tabla.enable_auto_backup(BACKUPS_DIR, vin=self.vin)

            maps[map_name] = tabla
        return maps

    # ── Map loading (from raw binary or demo) ──────────────────────────────

    def load_demo_maps(self, auto_backup: bool = True) -> dict[str, MapTable]:
        """Return a set of plausible demo maps for testing without real ECU."""
        maps = {}
        rng = np.random.default_rng(42)
        for name, defn in DEFAULT_MAP_DEFS.items():
            rpm_axis = np.array(defn["rpm_axis"])
            load_axis = np.array(defn["load_axis"])
            rows, cols = len(rpm_axis), len(load_axis)
            if name == "ignition":
                # Typical timing: higher at low load/high RPM, lower at WOT
                base = np.linspace(8, 35, rows)[:, None] * np.linspace(0.5, 1.0, cols)[None, :]
                values = base + rng.normal(0, 0.5, (rows, cols))
                values = np.clip(values, 5, 40)
            elif name == "fuel":
                base = np.linspace(1.5, 12.0, rows)[:, None] * np.linspace(0.4, 1.2, cols)[None, :]
                values = base + rng.normal(0, 0.1, (rows, cols))
                values = np.clip(values, 0.5, 20)
            else:  # boost
                values = np.ones((rows, cols)) * 1.0
                values[:, cols//2:] = 1.5
                values = np.clip(values, 0.8, 2.2)
            tabla = MapTable(
                name=name,
                rpm_axis=rpm_axis,
                load_axis=load_axis,
                values=values.astype(np.float64),
                unit=defn["unit"],
                min_safe=defn["min_safe"],
                max_safe=defn["max_safe"],
                description=defn["description"],
            )
            if auto_backup:
                tabla.enable_auto_backup(BACKUPS_DIR, vin=self.vin)
            maps[name] = tabla
        return maps

    # ── Save / load map profiles ───────────────────────────────────────────

    def save_map_profile(self, maps: dict[str, MapTable], profile_name: str,
                         dyno_results: dict | None = None) -> Path:
        payload = {
            "vehicle": {"vin": self.vin},
            "profile": profile_name,
            "created": datetime.now().isoformat(),
            "dyno_results": dyno_results or {},
            "tables": {name: table.to_dict() for name, table in maps.items()},
        }
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = MAPS_DIR / f"{ts}_{self.vin}_{profile_name}.ssmap"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[ECUReader] Perfil guardado: {path}")
        return path

    def load_map_profile(self, path: str | Path) -> dict[str, MapTable]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return {name: MapTable.from_dict(tbl) for name, tbl in payload["tables"].items()}
