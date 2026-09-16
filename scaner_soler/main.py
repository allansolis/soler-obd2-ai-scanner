"""
Scaner Soler Pro — CLI entry point.
Usage:
  python -m scaner_soler.main scan --port COM3
  python -m scaner_soler.main demo
  python -m scaner_soler.main optimize --profile track --fuel 98
"""
import argparse
import sys


def cmd_scan(args):
    from .comm.vehicle_conn import VehicleConnection
    from .diagnostic.diagnostic_engine import DiagnosticEngine

    print(f"[ScanerSolerPro] Conectando en {args.port}...")
    with VehicleConnection() as conn:
        ok = conn.connect(port=args.port)
        if not ok:
            print("ERROR: no se pudo conectar al vehiculo.")
            sys.exit(1)
        engine = DiagnosticEngine(conn)
        report = engine.full_scan()
        print(report.summary())


def cmd_demo(args):
    from .ecu.ecu_reader import ECUReader
    from .ecu.maps.map_editor import MapEditor
    from .optimizer.map_optimizer import MapOptimizer

    reader = ECUReader(conn=None, vin="DEMO123")  # type: ignore
    maps = reader.load_demo_maps()

    print("[DEMO] Mapas cargados:")
    for name, table in maps.items():
        print(f"  {name}: {table.values.shape}  {table.unit}  "
              f"[{table.min_safe}, {table.max_safe}]  checksum={table.checksum()}")

    opt = MapOptimizer(profile="track", fuel_grade=98)
    optimized_ign = opt.optimize_ignition(maps["ignition"])
    print(f"\n[DEMO] Optimizacion completada:")
    print(opt.summary(maps["ignition"], optimized_ign))

    profile_path = reader.save_map_profile(
        {"ignition": optimized_ign, "fuel": maps["fuel"], "boost": maps["boost"]},
        profile_name="track_98oct",
    )
    print(f"\n[DEMO] Perfil guardado: {profile_path}")

    try:
        from .ecu.maps.map_visualizer import plot_heatmap
        plot_heatmap(optimized_ign, title="Mapa de avance — Pista 98oct")
        plot_heatmap(optimized_ign, show_diff=True, title="Diferencia vs base")
    except ImportError:
        print("[DEMO] matplotlib no disponible — omitiendo visualizacion.")


def cmd_optimize(args):
    from .optimizer.map_optimizer import MapOptimizer
    from .ecu.ecu_reader import ECUReader

    reader = ECUReader(conn=None, vin="DEMO")  # type: ignore
    maps = reader.load_demo_maps()
    opt = MapOptimizer(profile=args.profile, fuel_grade=args.fuel)
    optimized = opt.optimize_ignition(maps["ignition"])
    print(opt.summary(maps["ignition"], optimized))


def main():
    parser = argparse.ArgumentParser(prog="scaner_soler", description="Scaner Soler Pro")
    sub = parser.add_subparsers(dest="cmd")

    p_scan = sub.add_parser("scan", help="Escaneo completo del vehiculo")
    p_scan.add_argument("--port", default="COM3", help="Puerto COM del adaptador (default: COM3)")

    sub.add_parser("demo", help="Demo sin hardware: mapas de muestra + optimizacion")

    p_opt = sub.add_parser("optimize", help="Optimizar mapa de ignicion")
    p_opt.add_argument("--profile", default="track", choices=["street", "track", "race"])
    p_opt.add_argument("--fuel", type=int, default=95, help="Octanaje del combustible")

    args = parser.parse_args()

    if args.cmd == "scan":
        cmd_scan(args)
    elif args.cmd == "demo":
        cmd_demo(args)
    elif args.cmd == "optimize":
        cmd_optimize(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
