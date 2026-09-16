"""
Demo rápido de ECUSandbox — corre sin conexión a vehículo real.
Usa los mapas demo del ECUReader.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from scaner_soler.optimizer.ecu_sandbox import ECUSandbox
from scaner_soler.ecu.ecu_reader import ECUReader


class _FakeConn:
    """Conexión falsa para demo (sin OBD real)."""
    def read_full_flash(self): return b"\x00" * 1024
    def write_full_flash(self, data): return True


def main():
    reader = ECUReader(conn=_FakeConn(), vin="DEMO_VIN")

    sandbox = ECUSandbox(safety_profile="track", seed=42)
    sandbox.clone_from_vehicle(reader, live_params={"rpm": 3000, "tps": 75})

    # 500 combinaciones para que el demo sea rápido; usa 1000–5000 en producción
    results = sandbox.simulate_combinations(n=500, workers=4)

    print(sandbox.report(goal="power"))
    print()
    print(sandbox.report(goal="efficiency"))
    print()
    print(sandbox.report(goal="speed"))

    best_power, _ = sandbox.get_best_config(goal="power")
    print("\nMejor config para POTENCIA:")
    print(best_power.summary())

    saved = sandbox.save_best_to_ssmap(goal="power")
    print(f"\nArchivo guardado: {saved}")


if __name__ == "__main__":
    main()
