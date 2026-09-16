import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np

from ..comm.vehicle_conn import VehicleConnection
from .maps.map_table import MapTable, SafetyError
from ..optimizer.safety_guard import SafetyGuard

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

    # ── Map loading (from raw binary or demo) ──────────────────────────────

    def load_demo_maps(self) -> dict[str, MapTable]:
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
            maps[name] = MapTable(
                name=name,
                rpm_axis=rpm_axis,
                load_axis=load_axis,
                values=values.astype(np.float64),
                unit=defn["unit"],
                min_safe=defn["min_safe"],
                max_safe=defn["max_safe"],
                description=defn["description"],
            )
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
