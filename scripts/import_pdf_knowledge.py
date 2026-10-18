"""
Importador de conocimiento desde PDFs de Remofer / Guia Completo de Reparo de ECUs.

Requiere: pdftotext (incluido en Git para Windows en mingw64/bin)

Uso:
  python scripts/import_pdf_knowledge.py

Qué hace:
  1. Extrae texto de los 3 PDFs con pdftotext
  2. Guarda .txt en knowledge/pdf_texts/
  3. Parsea secciones de "Defeitos mais comuns" → dtc_extended en SQLite
  4. Importa modelos ECU adicionales detectados en el texto → ecu_models
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "scaner_soler" / "database" / "dtc_codes.db"
PDF_DIR = ROOT  # los PDFs están en la raíz del proyecto
TXT_DIR = ROOT / "scaner_soler" / "knowledge" / "pdf_texts"

PDFS = [
    "Guia Completo de Reparo de ECUs (2025).pdf",
    "INSTRUÇÕES DE INSTALAÇÃO.pdf",
    "INSTRUÇÕES DE INSTALAÇÃO (1).pdf",
    "PACK DE SOFTWARE - VIDEO AULAS DAS INSTALAÇOES E PASSO A PASSO DOS PROGRAMAS.pdf",
]

PDFTOTEXT = r"C:\Program Files\Git\mingw64\bin\pdftotext.exe"


def extract_pdf(pdf_path: Path, txt_path: Path) -> str:
    """Extrae texto de un PDF usando pdftotext. Devuelve el texto."""
    if txt_path.exists():
        print(f"  [cache] {txt_path.name}")
        return txt_path.read_text(encoding="utf-8", errors="replace")

    result = subprocess.run(
        [PDFTOTEXT, "-enc", "UTF-8", str(pdf_path), "-"],
        capture_output=True, timeout=60
    )
    if result.returncode != 0:
        print(f"  [ERROR] pdftotext falló: {result.stderr.decode(errors='replace')[:200]}")
        return ""

    text = result.stdout.decode("utf-8", errors="replace")
    txt_path.write_text(text, encoding="utf-8")
    print(f"  [OK] {len(text):,} chars → {txt_path.name}")
    return text


# ── Parser de "Defeitos mais comuns" ─────────────────────────────────────────

# Ejemplo de sección en el PDF:
#   Módulo 5NF
#   Defeitos mais comuns
#   4
#   Defeito: No acelerador eletrônico.
#   Solução: Trocar todos os itens marcados...

_MODULE_RE = re.compile(
    r"[Mm]ódulo\s+([\w\s\-\.]+?)(?:\n|\r\n?)",
    re.MULTILINE,
)
_DEFECT_RE = re.compile(
    r"[Dd]efeito[:\s]+(.+?)(?:\n|\r\n?)",
    re.MULTILINE,
)
_SOLUTION_RE = re.compile(
    r"[Ss]olu[çc][ãa]o[:\s]+(.+?)(?:\n|\r\n?)",
    re.MULTILINE,
)

# Mapeo de marcas del PDF a marcas en nuestra DB
_BRAND_MAP = {
    "fiat":     "FIAT",
    "peugeot":  "PEUGEOT",
    "citroen":  "CITROEN",
    "ford":     "FORD",
    "chevrolet":"CHEVROLET",
    "gm":       "GM",
    "renault":  "RENAULT",
    "volkswagen":"VW",
    "vw":       "VW",
    "hyundai":  "HYUNDAI",
    "nissan":   "NISSAN",
    "honda":    "HONDA",
    "audi":     "AUDI",
    "mercedes": "MERCEDES",
    "jeep":     "JEEP",
    "chrysler": "CHRYSLER",
}


def parse_ecu_guide(text: str) -> list[dict]:
    """
    Parsea el texto del PDF de la guía de ECUs.
    Extrae pares (módulo, marca, defecto, solución).
    """
    entries = []
    current_brand = "GENERIC"
    current_module = ""

    # Dividir por secciones de marca (líneas que son solo un nombre de marca en mayúsculas)
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Detectar marca por encabezado de sección
        line_lower = line.lower()
        for brand_key, brand_val in _BRAND_MAP.items():
            if line_lower == brand_key:
                current_brand = brand_val
                break

        # Detectar nombre de módulo
        if re.match(r'^[A-Z][A-Za-z0-9\s\.\-]{3,30}$', line) and "módulo" not in line_lower:
            # Posible nombre de módulo (ej: "5NF", "Bosch ME 7.9.9")
            if any(x in line for x in ["Bosch", "Marelli", "Siemens", "Delphi", "Sagem", "Multec", "Motronic", "Valeo", "Hitachi", "HSFI", "Digifant", "EEC", "EMS"]):
                current_module = line

        # Defeito / Solução
        if line.lower().startswith("defeito") and i + 1 < len(lines):
            defect = re.sub(r'^[Dd]efeito\s*:?\s*', '', line).strip()
            solution = ""
            # Buscar solución en las siguientes líneas
            for j in range(i + 1, min(i + 5, len(lines))):
                sl = lines[j].strip()
                if sl.lower().startswith("solu"):
                    solution = re.sub(r'^[Ss]olu[çc][ãa]o\s*:?\s*', '', sl).strip()
                    i = j
                    break

            if defect and current_module:
                entries.append({
                    "brand":   current_brand,
                    "module":  current_module,
                    "defect":  defect,
                    "solution": solution,
                })

        i += 1

    return entries


def import_to_db(entries: list[dict], conn: sqlite3.Connection):
    """Importa entradas parseadas a la tabla ecu_faults."""
    c = conn.cursor()

    # Asegurarse de que las tablas existen
    c.execute("""
        CREATE TABLE IF NOT EXISTS ecu_models (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            ecu_code TEXT UNIQUE,
            make     TEXT,
            family   TEXT,
            page_ref TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS ecu_faults (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            ecu_id  INTEGER REFERENCES ecu_models(id),
            symptom TEXT,
            solution TEXT,
            page_ref TEXT
        )
    """)

    inserted_models = 0
    inserted_faults = 0

    for e in entries:
        module_code = e["module"][:60]  # truncar por seguridad
        make        = e["brand"]

        # Insertar o recuperar el modelo ECU
        c.execute("INSERT OR IGNORE INTO ecu_models (ecu_code, make) VALUES (?,?)",
                  (module_code, make))
        if c.rowcount > 0:
            inserted_models += 1

        c.execute("SELECT id FROM ecu_models WHERE ecu_code=?", (module_code,))
        row = c.fetchone()
        if not row:
            continue
        ecu_id = row[0]

        # Insertar la falla
        c.execute("""
            INSERT INTO ecu_faults (ecu_id, symptom, solution)
            VALUES (?,?,?)
        """, (ecu_id, e["defect"][:500], e["solution"][:1000]))
        inserted_faults += 1

    conn.commit()
    return inserted_models, inserted_faults


def main():
    TXT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n{'='*60}")
    print("  Importador de PDFs — Scaner Soler Pro")
    print(f"{'='*60}\n")

    if not Path(PDFTOTEXT).exists():
        print(f"ERROR: pdftotext no encontrado en {PDFTOTEXT}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    total_models = 0
    total_faults = 0

    for pdf_name in PDFS:
        pdf_path = PDF_DIR / pdf_name
        if not pdf_path.exists():
            print(f"[SKIP] No encontrado: {pdf_name}")
            continue

        txt_name = re.sub(r'[^\w\s\-]', '_', pdf_path.stem) + ".txt"
        txt_path = TXT_DIR / txt_name
        print(f"\nProcesando: {pdf_name}")

        text = extract_pdf(pdf_path, txt_path)
        if not text:
            continue

        if "reparo" in pdf_name.lower() or "reparo" in text[:200].lower() or "defeito" in text[:5000].lower():
            entries = parse_ecu_guide(text)
            if entries:
                m, f = import_to_db(entries, conn)
                total_models += m
                total_faults += f
                print(f"  → {len(entries)} pares defecto/solución parseados ({m} modelos nuevos, {f} fallas)")
            else:
                print(f"  → No se encontraron secciones de fallas en este PDF")
        else:
            print(f"  → PDF de instalación — texto guardado en {txt_path.name}")

    conn.close()

    print(f"\n{'='*60}")
    print(f"  Modelos ECU nuevos: {total_models}")
    print(f"  Fallas ECU nuevas:  {total_faults}")
    print(f"  Textos guardados en: {TXT_DIR}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
