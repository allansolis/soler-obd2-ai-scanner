"""
Scaner Soler Pro — Lanzador unificado.

Inicia el backend FastAPI (si uvicorn está disponible) y luego
la GUI Tkinter. Al cerrar la GUI, el servidor se apaga automáticamente.

Uso:
    python launch_supersystem.py              # backend + GUI (demo)
    python launch_supersystem.py --no-backend # solo GUI (modo offline)
    python launch_supersystem.py --port COM3  # GUI conectada a puerto real
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

# ── Directorios ───────────────────────────────────────────────────────────────
BACKEND_DIR = Path(r"C:\Users\Usuario\AppData\Local\Temp\soler-obd2-ai-scanner")
GUI_DIR     = Path(__file__).parent

# ── Backend ───────────────────────────────────────────────────────────────────

def _start_backend_thread():
    """Arranca uvicorn en un hilo daemon."""
    try:
        sys.path.insert(0, str(BACKEND_DIR))
        import uvicorn  # type: ignore
        uvicorn.run(
            "backend.api.server:app",
            host="127.0.0.1",
            port=8000,
            log_level="warning",
        )
    except ModuleNotFoundError as exc:
        print(f"[launch] Backend no disponible: {exc}")
    except Exception as exc:
        print(f"[launch] Error al iniciar backend: {exc}")


def _wait_backend(timeout: int = 8) -> bool:
    """Espera hasta {timeout} segundos a que el backend responda en /health."""
    try:
        import requests  # type: ignore
    except ImportError:
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get("http://localhost:8000/health", timeout=1).ok:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Scaner Soler Pro — lanzador")
    parser.add_argument(
        "--no-backend",
        action="store_true",
        help="Lanza solo la GUI sin intentar iniciar el backend FastAPI.",
    )
    parser.add_argument(
        "--port",
        default=None,
        metavar="PORT",
        help="Puerto COM / socket OBD-II. Si se omite, la GUI arranca en modo demo.",
    )
    args = parser.parse_args()

    # ── Backend ────────────────────────────────────────────────────────────────
    backend_ready = False
    if not args.no_backend:
        print("[launch] Iniciando backend FastAPI…")
        t = threading.Thread(target=_start_backend_thread, daemon=True)
        t.start()
        backend_ready = _wait_backend(timeout=8)
        status = "online" if backend_ready else "offline (modo local)"
        print(f"[launch] Backend: {status}")
    else:
        print("[launch] Backend omitido (--no-backend).")

    # ── GUI ────────────────────────────────────────────────────────────────────
    sys.path.insert(0, str(GUI_DIR))
    try:
        from scaner_soler.gui.app import run_gui
    except ImportError as exc:
        print(f"[launch] No se pudo importar la GUI: {exc}")
        sys.exit(1)

    demo_mode = args.port is None
    print(f"[launch] Iniciando GUI (demo={demo_mode})…")
    run_gui(demo=demo_mode)

    # Al cerrar la GUI el proceso principal termina; el hilo daemon
    # del backend se detiene automáticamente con él.
    print("[launch] GUI cerrada. Saliendo.")


if __name__ == "__main__":
    main()
