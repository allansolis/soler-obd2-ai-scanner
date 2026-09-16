#!/usr/bin/env python3
"""
Lanzador de la GUI de escritorio Scaner Soler Pro.

Uso:
    python launch_gui.py          # modo demo (sin hardware)
    python launch_gui.py --port COM3  # con adaptador ELM327 real
"""
import argparse
import sys
from pathlib import Path

# Asegura que el proyecto esté en el path
sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(description="Scaner Soler Pro — GUI")
    parser.add_argument("--port", default=None,
                        help="Puerto COM del adaptador ELM327 (ej: COM3). "
                             "Si se omite, arranca en modo demo.")
    args = parser.parse_args()

    demo = args.port is None
    from scaner_soler.gui.app import run_gui
    run_gui(demo=demo)


if __name__ == "__main__":
    main()
