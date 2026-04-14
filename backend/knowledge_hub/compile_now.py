"""
SOLER OBD2 AI Scanner - Compilador del KnowledgeHub
====================================================
Script standalone para ejecutar la compilacion completa del hub.
Importa Drive inventory, PDFs locales, vehiculos, DTCs, mapas de
tuning, guias de reparacion y recursos online en data/knowledge_hub.db.

Uso:
    python -m backend.knowledge_hub.compile_now
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Permite ejecutar el script directamente sin "python -m"
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.knowledge_hub.hub import KnowledgeHub


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )

    print("=" * 70)
    print("SOLER OBD2 AI Scanner - KnowledgeHub Compiler")
    print("=" * 70)

    hub = KnowledgeHub()
    print(f"DB destino: {hub.db_path}")
    print()
    print("Compilando KnowledgeHub de SOLER...")
    print("(esto puede tardar varios segundos por la indexacion de PDFs)")
    print()

    stats = await hub.compile_all()
    hub_stats = hub.get_stats()

    print()
    print("-" * 70)
    print("COMPILACION COMPLETA")
    print("-" * 70)
    print(f"  Recursos totales       : {hub_stats.total_resources}")
    print(f"  Vehiculos              : {hub_stats.total_vehicles}")
    print(f"  DTCs catalogados       : {hub_stats.total_dtcs}")
    print(f"  PDFs locales indexados : {hub_stats.total_pdfs_local}")
    print(f"  Recursos Drive         : {hub_stats.total_drive}")
    print(f"  Recursos online        : {hub_stats.total_online}")
    print(f"  Software catalogado    : {hub_stats.total_software}")
    print(f"  Procedimientos         : {hub_stats.total_repair_procedures}")
    print(f"  Tamano DB              : {hub_stats.db_size_mb} MB")
    print()

    if stats.errors:
        print("Errores no fatales durante la compilacion:")
        for err in stats.errors:
            print(f"   - {err}")
        print()

    print("Categorias:")
    for cat, n in sorted(hub_stats.by_category.items(), key=lambda x: -x[1]):
        print(f"   {cat:20s} {n}")

    print()
    print("Marcas con perfil de vehiculo:")
    for make, n in sorted(hub_stats.by_make.items(), key=lambda x: -x[1])[:15]:
        print(f"   {make:20s} {n}")

    print()
    print("KnowledgeHub listo. El cerebro del SOLER esta cargado.")


if __name__ == "__main__":
    asyncio.run(main())
