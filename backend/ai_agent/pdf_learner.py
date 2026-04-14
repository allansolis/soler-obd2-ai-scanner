"""
SOLER OBD2 AI Scanner - Motor de Aprendizaje desde PDFs
========================================================
Lee, indexa y aprende de los 1,400+ archivos PDF en el directorio data/
para construir la base de conocimiento del agente IA.

Estructura de datos esperada:
    data/obd-diesel/OBD DIESEL/{make}/*.pdf
    data/datos-tecnicos/DADOS TÉCNICOS E TORQUES/{category}/{make}/*.pdf
    data/abs-esp/ABS ASR ESP/*.pdf
    data/airbag/AIR BAG/{make}/*.pdf
    data/aire-acondicionado/AR CONDICIONADO/{category}/{make}/*.pdf
    data/transmision/CAMBIO/{make}/*.pdf
    data/localizacion-componentes/LOCALIZAÇÃO DE COMPONENTES/{make}/*.pdf

Dependencias:
    pip install PyMuPDF
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ruta base del proyecto
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DATA_PATH = _PROJECT_ROOT / "data"
_DEFAULT_INDEX_PATH = _PROJECT_ROOT / "data" / "knowledge_base" / "pdf_index.db"

# ---------------------------------------------------------------------------
# Categorias de conocimiento
# ---------------------------------------------------------------------------

CATEGORY_OBD_CODES = "obd_codes"
CATEGORY_TECHNICAL_DATA = "technical_data"
CATEGORY_ABS_ESP = "abs_esp"
CATEGORY_AIRBAG = "airbag"
CATEGORY_AC = "ac"
CATEGORY_TRANSMISSION = "transmission"
CATEGORY_COMPONENTS = "components"
CATEGORY_UNKNOWN = "unknown"

# Mapeo de directorios a categorias
_DIR_CATEGORY_MAP: dict[str, str] = {
    "obd-diesel": CATEGORY_OBD_CODES,
    "datos-tecnicos": CATEGORY_TECHNICAL_DATA,
    "abs-esp": CATEGORY_ABS_ESP,
    "airbag": CATEGORY_AIRBAG,
    "aire-acondicionado": CATEGORY_AC,
    "transmision": CATEGORY_TRANSMISSION,
    "localizacion-componentes": CATEGORY_COMPONENTS,
}


# ---------------------------------------------------------------------------
# Modelos de datos
# ---------------------------------------------------------------------------

@dataclass
class DTCEntry:
    """Codigo de diagnostico (DTC) extraido de un PDF."""
    code: str
    description: str
    system: str
    severity: str
    source_pdf: str
    vehicle_make: str = ""
    vehicle_model: str = ""

    @property
    def system_prefix(self) -> str:
        """Retorna el prefijo del sistema: P=Powertrain, C=Chassis, B=Body, U=Network."""
        prefix_map = {"P": "Powertrain", "C": "Chasis", "B": "Carroceria", "U": "Red"}
        return prefix_map.get(self.code[0].upper(), "Desconocido") if self.code else "Desconocido"


@dataclass
class TorqueSpec:
    """Especificacion de torque extraida de un PDF."""
    component: str
    torque_value: float
    unit: str  # "N.m", "kgf.m", "ft.lbs"
    notes: str = ""
    source_pdf: str = ""
    vehicle_make: str = ""
    vehicle_model: str = ""


@dataclass
class SensorSpec:
    """Especificacion de sensor extraida de un PDF."""
    sensor_name: str
    parameter: str  # "voltage", "resistance", "frequency", etc.
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    unit: str = ""
    condition: str = ""  # "ralenti", "plena carga", etc.
    source_pdf: str = ""
    vehicle_make: str = ""


@dataclass
class WiringInfo:
    """Informacion de cableado extraida de un PDF."""
    connector_name: str
    pin_number: str
    wire_color: str
    signal_description: str
    ecu_name: str = ""
    source_pdf: str = ""
    vehicle_make: str = ""


@dataclass
class VehicleCategory:
    """Categoria de vehiculo determinada desde la ruta del PDF."""
    make: str
    model: str
    category: str
    subcategory: str = ""
    source_path: str = ""


@dataclass
class DataInventory:
    """Inventario de todos los PDFs encontrados en el directorio de datos."""
    by_make: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    total_files: int = 0
    categories_found: list[str] = field(default_factory=list)
    makes_found: list[str] = field(default_factory=list)

    def add(self, make: str, category: str, pdf_path: str) -> None:
        if make not in self.by_make:
            self.by_make[make] = {}
        if category not in self.by_make[make]:
            self.by_make[make][category] = []
        self.by_make[make][category].append(pdf_path)
        self.total_files += 1
        if category not in self.categories_found:
            self.categories_found.append(category)
        if make not in self.makes_found:
            self.makes_found.append(make)


@dataclass
class IndexStats:
    """Estadisticas del proceso de indexado."""
    files_processed: int = 0
    files_failed: int = 0
    dtcs_found: int = 0
    torque_specs_found: int = 0
    sensor_specs_found: int = 0
    wiring_entries_found: int = 0
    vehicles_indexed: int = 0
    processing_time_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    """Resultado de busqueda en el indice."""
    source_pdf: str
    category: str
    vehicle_make: str
    snippet: str
    relevance_score: float
    data_type: str = ""  # "dtc", "torque", "sensor", "wiring", "text"


@dataclass
class RepairProcedure:
    """Procedimiento de reparacion basado en conocimiento aprendido."""
    dtc_code: str
    vehicle_make: str
    description: str
    possible_causes: list[str] = field(default_factory=list)
    diagnostic_steps: list[str] = field(default_factory=list)
    related_dtcs: list[str] = field(default_factory=list)
    torque_specs: list[TorqueSpec] = field(default_factory=list)
    wiring_info: list[WiringInfo] = field(default_factory=list)


@dataclass
class LearningReport:
    """Reporte del proceso de aprendizaje."""
    timestamp: str = ""
    data_path: str = ""
    index_stats: Optional[IndexStats] = None
    vehicle_makes_learned: list[str] = field(default_factory=list)
    categories_covered: list[str] = field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# PDFKnowledgeExtractor
# ---------------------------------------------------------------------------

class PDFKnowledgeExtractor:
    """Lee PDFs y extrae conocimiento estructurado para el agente IA.

    Usa PyMuPDF (fitz) para leer el contenido de los PDFs.
    Maneja texto en portugues y espanol correctamente.
    """

    # Patrones regex para extraccion
    _DTC_PATTERN = re.compile(
        r'\b([PCBU]\d{4,5})\b[\s\-:]*([^\n\r]{5,120})',
        re.IGNORECASE,
    )
    _TORQUE_NM_PATTERN = re.compile(
        r'(\d+(?:[.,]\d+)?)\s*(?:N[\.\s]?m|Nm)',
        re.IGNORECASE,
    )
    _TORQUE_KGF_PATTERN = re.compile(
        r'(\d+(?:[.,]\d+)?)\s*(?:kgf[\.\s]?m|kgf\.cm)',
        re.IGNORECASE,
    )
    _TORQUE_FTLBS_PATTERN = re.compile(
        r'(\d+(?:[.,]\d+)?)\s*(?:ft[\.\s]?lbs?|lb[\.\s]?ft)',
        re.IGNORECASE,
    )
    _VOLTAGE_PATTERN = re.compile(
        r'(\d+(?:[.,]\d+)?)\s*(?:a|~|-|hasta)\s*(\d+(?:[.,]\d+)?)\s*[Vv](?:olts?)?',
        re.IGNORECASE,
    )
    _RESISTANCE_PATTERN = re.compile(
        r'(\d+(?:[.,]\d+)?)\s*(?:a|~|-|hasta)\s*(\d+(?:[.,]\d+)?)\s*(?:[kK]?[Ωo]|ohm)',
        re.IGNORECASE,
    )
    _WIRE_COLOR_PATTERN = re.compile(
        r'(?:pin|pino?|terminal)\s*(\d+)\s*[-:]\s*'
        r'((?:(?:amarillo|azul|blanco|gris|marron|naranja|negro|rojo|rosa|verde|violeta|'
        r'amarelo|branco|cinza|marrom|laranja|preto|vermelho|roxo|'
        r'AM|AZ|BR|CZ|MR|LR|PR|VM|RS|VD|VT|NR)'
        r'(?:\s*/\s*(?:amarillo|azul|blanco|gris|marron|naranja|negro|rojo|rosa|verde|violeta|'
        r'amarelo|branco|cinza|marrom|laranja|preto|vermelho|roxo|'
        r'AM|AZ|BR|CZ|MR|LR|PR|VM|RS|VD|VT|NR))?'
        r'))\s*[-:]\s*(.+)',
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        if fitz is None:
            raise ImportError(
                "PyMuPDF no esta instalado. Ejecutar: pip install PyMuPDF"
            )

    # ------------------------------------------------------------------
    # scan_data_directory
    # ------------------------------------------------------------------

    def scan_data_directory(self, base_path: Optional[str | Path] = None) -> DataInventory:
        """Recorre el arbol de directorios data/ y cataloga todos los PDFs.

        Args:
            base_path: Ruta al directorio data/. Si es None, usa la ruta por defecto.

        Returns:
            DataInventory con {make: {category: [pdf_paths]}}.
        """
        data_dir = Path(base_path) if base_path else _DEFAULT_DATA_PATH
        if not data_dir.exists():
            raise FileNotFoundError(f"Directorio de datos no encontrado: {data_dir}")

        inventory = DataInventory()
        logger.info("Escaneando directorio de datos: %s", data_dir)

        # Recorrer cada subdirectorio de primer nivel
        for top_dir in sorted(data_dir.iterdir()):
            if not top_dir.is_dir():
                continue

            dir_name = top_dir.name.lower().replace(" ", "-")
            category = self._resolve_category(dir_name, top_dir.name)

            # Buscar PDFs recursivamente
            for pdf_path in top_dir.rglob("*.pdf"):
                make = self._extract_make_from_path(pdf_path, top_dir, category)
                inventory.add(make, category, str(pdf_path))

        logger.info(
            "Inventario completo: %d archivos, %d marcas, %d categorias",
            inventory.total_files,
            len(inventory.makes_found),
            len(inventory.categories_found),
        )
        return inventory

    def _resolve_category(self, dir_name_lower: str, original_name: str) -> str:
        """Resuelve la categoria basandose en el nombre del directorio."""
        for key, cat in _DIR_CATEGORY_MAP.items():
            if key in dir_name_lower:
                return cat
        # Intentar por nombre original
        name_lower = original_name.lower()
        if "dtc" in name_lower or "obd" in name_lower:
            return CATEGORY_OBD_CODES
        if "torque" in name_lower or "técnico" in name_lower or "tecnico" in name_lower:
            return CATEGORY_TECHNICAL_DATA
        if "tuning" in name_lower:
            return CATEGORY_TECHNICAL_DATA
        return CATEGORY_UNKNOWN

    def _extract_make_from_path(
        self, pdf_path: Path, top_dir: Path, category: str
    ) -> str:
        """Extrae la marca del vehiculo desde la ruta del archivo.

        Analiza la estructura de directorios para determinar la marca.
        Por ejemplo: data/obd-diesel/OBD DIESEL/Toyota Diesel/archivo.pdf -> Toyota
        """
        # Obtener las partes relativas al directorio principal
        try:
            rel = pdf_path.relative_to(top_dir)
        except ValueError:
            return "Desconocido"

        parts = list(rel.parts)

        # Si el PDF esta directamente en el directorio (abs-esp/ABS ASR ESP/Fiat.pdf)
        if len(parts) == 1:
            # El nombre del archivo puede ser la marca
            name = pdf_path.stem
            return self._clean_make_name(name)

        # Buscar la marca en las partes del path
        # Saltar subdirectorios intermedios en mayusculas (e.g. "OBD DIESEL", "AIR BAG")
        for part in parts[:-1]:  # Excluir el nombre del archivo
            if part.isupper() or part == part.title():
                # Podria ser un directorio de categoria o de marca
                cleaned = self._clean_make_name(part)
                if self._looks_like_make(cleaned):
                    return cleaned
            else:
                cleaned = self._clean_make_name(part)
                if self._looks_like_make(cleaned):
                    return cleaned

        # Ultimo recurso: usar la primera carpeta que no sea un encabezado
        for part in parts[:-1]:
            if not part.isupper() or len(part.split()) == 1:
                cleaned = self._clean_make_name(part)
                if cleaned and cleaned != "Desconocido":
                    return cleaned

        # Si todo falla, usar el nombre del directorio padre del PDF
        if len(parts) >= 2:
            return self._clean_make_name(parts[-2])

        return "Desconocido"

    @staticmethod
    def _clean_make_name(name: str) -> str:
        """Limpia el nombre de marca removiendo sufijos comunes."""
        # Remover sufijos de tipo de motor
        cleaned = re.sub(
            r'\s*(?:Diesel|Gasolina|Flex|Turbo|diesel|gasolina)\s*$',
            '', name.strip()
        )
        # Remover caracteres especiales del final
        cleaned = cleaned.strip(" -_.")
        # Remover sufijos de archivo
        for suffix in (" k", " h", " l"):
            if cleaned.lower().endswith(suffix):
                cleaned = cleaned[:-2].strip()
        return cleaned if cleaned else "Desconocido"

    @staticmethod
    def _looks_like_make(name: str) -> bool:
        """Determina si un nombre parece una marca de vehiculo."""
        if not name or name == "Desconocido":
            return False
        # No es marca si es un encabezado de categoria conocido
        category_headers = {
            "obd diesel", "dados técnicos e torques", "abs asr esp",
            "air bag", "ar condicionado", "cambio",
            "localização de componentes", "motores leves",
            "motores pesados", "pesados", "esquemas elétricos",
            "tabela de gás", "compressor", "diagnose",
            "dicas de falhas",
        }
        if name.lower() in category_headers:
            return False
        # Marcas tienen tipicamente 2-15 caracteres y no son solo numeros
        if len(name) < 2 or len(name) > 30:
            return False
        if name.isdigit():
            return False
        return True

    # ------------------------------------------------------------------
    # extract_text_from_pdf
    # ------------------------------------------------------------------

    def extract_text_from_pdf(self, pdf_path: str | Path) -> str:
        """Lee todo el texto de un PDF usando PyMuPDF.

        Args:
            pdf_path: Ruta al archivo PDF.

        Returns:
            Texto completo extraido del PDF.

        Raises:
            FileNotFoundError: Si el archivo no existe.
            RuntimeError: Si hay un error al leer el PDF.
        """
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF no encontrado: {path}")

        try:
            doc = fitz.open(str(path))
            text_parts: list[str] = []

            for page_num in range(len(doc)):
                page = doc[page_num]
                page_text = page.get_text("text")
                if page_text:
                    text_parts.append(page_text)

            doc.close()

            full_text = "\n\n".join(text_parts)

            # Normalizar caracteres de encoding comunes en PDFs en portugues/espanol
            full_text = full_text.replace("\x00", "")
            full_text = re.sub(r'\s+\n', '\n', full_text)
            full_text = re.sub(r'\n{3,}', '\n\n', full_text)

            return full_text

        except Exception as exc:
            raise RuntimeError(
                f"Error leyendo PDF {path.name}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # extract_dtc_codes
    # ------------------------------------------------------------------

    def extract_dtc_codes(self, text: str, source_pdf: str = "") -> list[DTCEntry]:
        """Extrae codigos DTC del texto.

        Busca patrones como P0xxx, C0xxx, B0xxx, U0xxx.

        Args:
            text: Texto extraido del PDF.
            source_pdf: Ruta del PDF fuente para referencia.

        Returns:
            Lista de DTCEntry encontrados.
        """
        entries: list[DTCEntry] = []
        seen_codes: set[str] = set()

        for match in self._DTC_PATTERN.finditer(text):
            code = match.group(1).upper()
            raw_desc = match.group(2).strip()

            if code in seen_codes:
                continue
            seen_codes.add(code)

            # Limpiar la descripcion
            description = self._clean_description(raw_desc)
            if not description or len(description) < 3:
                continue

            # Determinar sistema y severidad
            system = self._classify_dtc_system(code)
            severity = self._classify_dtc_severity(code, description)

            entries.append(DTCEntry(
                code=code,
                description=description,
                system=system,
                severity=severity,
                source_pdf=source_pdf,
            ))

        logger.debug("Extraidos %d DTCs de %s", len(entries), source_pdf or "texto")
        return entries

    @staticmethod
    def _clean_description(raw: str) -> str:
        """Limpia una descripcion de DTC extraida del texto."""
        # Cortar en el primer salto de linea o patron de nuevo DTC
        desc = re.split(r'[\n\r]|(?=[PCBU]\d{4})', raw)[0]
        # Remover caracteres no deseados
        desc = desc.strip(" -:;.,")
        # Limitar longitud
        if len(desc) > 120:
            desc = desc[:117] + "..."
        return desc

    @staticmethod
    def _classify_dtc_system(code: str) -> str:
        """Clasifica el sistema del DTC basandose en el codigo."""
        if not code:
            return "Desconocido"
        prefix = code[0].upper()
        if prefix == "P":
            # Subclasificar Powertrain
            try:
                num = int(code[1:3])
            except ValueError:
                return "Motor/Transmision"
            if num <= 9:
                return "Control de combustible/aire"
            elif num <= 19:
                return "Control de combustible/aire"
            elif num <= 29:
                return "Control de combustible/aire"
            elif num <= 39:
                return "Encendido"
            elif num <= 49:
                return "Control de emisiones"
            elif num <= 59:
                return "Velocidad/ralenti"
            elif num <= 69:
                return "ECU/Computadora"
            elif num <= 79:
                return "Transmision"
            else:
                return "Motor/Transmision"
        elif prefix == "C":
            return "Chasis (ABS/ESP/Frenos)"
        elif prefix == "B":
            return "Carroceria (Airbag/Confort)"
        elif prefix == "U":
            return "Red de comunicacion"
        return "Desconocido"

    @staticmethod
    def _classify_dtc_severity(code: str, description: str) -> str:
        """Clasifica la severidad del DTC."""
        desc_lower = description.lower()
        # Severidad critica
        critical_keywords = [
            "airbag", "air bag", "srs", "freno", "brake", "freio",
            "abs", "esp", "direccion", "direção", "steering",
            "transmiss", "cambio",
        ]
        for kw in critical_keywords:
            if kw in desc_lower:
                return "CRITICO"

        # Severidad alta
        high_keywords = [
            "motor", "engine", "inyect", "inject", "injeç",
            "turbo", "combusti", "fuel", "coolant", "refriger",
            "overtemp", "sobretemp",
        ]
        for kw in high_keywords:
            if kw in desc_lower:
                return "ALTO"

        # Severidad media
        medium_keywords = [
            "sensor", "circuito", "circuit", "señal", "sinal",
            "signal", "voltag", "tensão",
        ]
        for kw in medium_keywords:
            if kw in desc_lower:
                return "MEDIO"

        return "BAJO"

    # ------------------------------------------------------------------
    # extract_torque_specs
    # ------------------------------------------------------------------

    def extract_torque_specs(
        self, text: str, source_pdf: str = ""
    ) -> list[TorqueSpec]:
        """Extrae especificaciones de torque del texto.

        Busca patrones como: Componente ... 45 N.m, 4.5 kgf.m, 33 ft.lbs

        Args:
            text: Texto extraido del PDF.
            source_pdf: Ruta del PDF fuente.

        Returns:
            Lista de TorqueSpec encontrados.
        """
        specs: list[TorqueSpec] = []

        # Procesar linea por linea para mantener contexto del componente
        lines = text.split("\n")
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if not line_stripped:
                continue

            # Buscar valores de torque en la linea
            found_torque = False

            for pattern, unit in [
                (self._TORQUE_NM_PATTERN, "N.m"),
                (self._TORQUE_KGF_PATTERN, "kgf.m"),
                (self._TORQUE_FTLBS_PATTERN, "ft.lbs"),
            ]:
                for match in pattern.finditer(line_stripped):
                    raw_val = match.group(1).replace(",", ".")
                    try:
                        value = float(raw_val)
                    except ValueError:
                        continue

                    if value <= 0 or value > 2000:
                        continue

                    component = self._extract_component_context(
                        lines, i, match.start()
                    )

                    specs.append(TorqueSpec(
                        component=component,
                        torque_value=value,
                        unit=unit,
                        notes=line_stripped[:150],
                        source_pdf=source_pdf,
                    ))
                    found_torque = True

        logger.debug(
            "Extraidas %d especificaciones de torque de %s",
            len(specs), source_pdf or "texto",
        )
        return specs

    @staticmethod
    def _extract_component_context(
        lines: list[str], line_idx: int, char_pos: int
    ) -> str:
        """Extrae el nombre del componente del contexto de la linea."""
        line = lines[line_idx].strip()

        # Intentar obtener el texto antes del valor numerico
        prefix = line[:char_pos].strip()
        if prefix:
            # Limpiar separadores
            prefix = re.sub(r'[\.\-_:;,]+$', '', prefix).strip()
            if len(prefix) > 3:
                return prefix[:100]

        # Intentar con la linea anterior
        if line_idx > 0:
            prev_line = lines[line_idx - 1].strip()
            if prev_line and len(prev_line) > 3 and not prev_line[0].isdigit():
                return prev_line[:100]

        return line[:80] if line else "Componente no identificado"

    # ------------------------------------------------------------------
    # extract_sensor_specs
    # ------------------------------------------------------------------

    def extract_sensor_specs(
        self, text: str, source_pdf: str = ""
    ) -> list[SensorSpec]:
        """Extrae especificaciones de sensores del texto.

        Busca rangos de voltaje, resistencia y frecuencia.

        Args:
            text: Texto extraido del PDF.
            source_pdf: Ruta del PDF fuente.

        Returns:
            Lista de SensorSpec encontrados.
        """
        specs: list[SensorSpec] = []
        lines = text.split("\n")

        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if not line_stripped:
                continue

            # Voltaje
            for match in self._VOLTAGE_PATTERN.finditer(line_stripped):
                try:
                    min_v = float(match.group(1).replace(",", "."))
                    max_v = float(match.group(2).replace(",", "."))
                except ValueError:
                    continue

                sensor_name = self._extract_sensor_name(lines, i)
                specs.append(SensorSpec(
                    sensor_name=sensor_name,
                    parameter="voltage",
                    min_value=min_v,
                    max_value=max_v,
                    unit="V",
                    source_pdf=source_pdf,
                ))

            # Resistencia
            for match in self._RESISTANCE_PATTERN.finditer(line_stripped):
                try:
                    min_r = float(match.group(1).replace(",", "."))
                    max_r = float(match.group(2).replace(",", "."))
                except ValueError:
                    continue

                sensor_name = self._extract_sensor_name(lines, i)
                unit = "kΩ" if "k" in match.group(0).lower() else "Ω"
                specs.append(SensorSpec(
                    sensor_name=sensor_name,
                    parameter="resistance",
                    min_value=min_r,
                    max_value=max_r,
                    unit=unit,
                    source_pdf=source_pdf,
                ))

        logger.debug(
            "Extraidas %d especificaciones de sensores de %s",
            len(specs), source_pdf or "texto",
        )
        return specs

    @staticmethod
    def _extract_sensor_name(lines: list[str], line_idx: int) -> str:
        """Intenta extraer el nombre del sensor del contexto."""
        # Buscar palabras clave de sensor en la linea actual y anteriores
        sensor_keywords = [
            "sensor", "sonda", "map", "maf", "tps", "ect", "iat",
            "ckp", "cmp", "o2", "lambda", "egr", "evap",
            "temperatura", "presion", "pressão", "posicion", "posição",
        ]

        for offset in range(0, min(3, line_idx + 1)):
            idx = line_idx - offset
            if idx < 0:
                break
            line = lines[idx].strip().lower()
            for kw in sensor_keywords:
                if kw in line:
                    # Devolver la linea como nombre del sensor
                    clean = lines[idx].strip()
                    clean = re.sub(r'[\d.,]+\s*(?:a|~|-|hasta)\s*[\d.,]+\s*[VvΩo].*', '', clean)
                    clean = clean.strip(" -:;,.")
                    if clean and len(clean) > 2:
                        return clean[:100]

        return lines[line_idx].strip()[:80] if lines[line_idx].strip() else "Sensor no identificado"

    # ------------------------------------------------------------------
    # extract_wiring_info
    # ------------------------------------------------------------------

    def extract_wiring_info(
        self, text: str, source_pdf: str = ""
    ) -> list[WiringInfo]:
        """Extrae informacion de cableado del texto.

        Busca asignaciones de pines, colores de cable y ubicaciones de conectores.

        Args:
            text: Texto extraido del PDF.
            source_pdf: Ruta del PDF fuente.

        Returns:
            Lista de WiringInfo encontrados.
        """
        entries: list[WiringInfo] = []

        for match in self._WIRE_COLOR_PATTERN.finditer(text):
            pin = match.group(1)
            color = match.group(2).strip()
            description = match.group(3).strip()[:120]

            entries.append(WiringInfo(
                connector_name="",
                pin_number=pin,
                wire_color=color,
                signal_description=description,
                source_pdf=source_pdf,
            ))

        # Busqueda adicional para tablas de pines con formato mas simple
        # Formato: "Pin X - Descripcion - Color"
        simple_pin_pattern = re.compile(
            r'(?:pin|pino?)\s*(\d+)\s*[-–:]\s*(.{5,80})',
            re.IGNORECASE,
        )
        for match in simple_pin_pattern.finditer(text):
            pin = match.group(1)
            desc = match.group(2).strip()

            # Evitar duplicados
            if any(e.pin_number == pin and e.signal_description == desc for e in entries):
                continue

            entries.append(WiringInfo(
                connector_name="",
                pin_number=pin,
                wire_color="",
                signal_description=desc[:120],
                source_pdf=source_pdf,
            ))

        logger.debug(
            "Extraidas %d entradas de cableado de %s",
            len(entries), source_pdf or "texto",
        )
        return entries

    # ------------------------------------------------------------------
    # categorize_vehicle
    # ------------------------------------------------------------------

    def categorize_vehicle(self, pdf_path: str | Path) -> VehicleCategory:
        """Determina marca/modelo/categoria desde la ruta y contenido del PDF.

        Args:
            pdf_path: Ruta al archivo PDF.

        Returns:
            VehicleCategory con la informacion deducida.
        """
        path = Path(pdf_path)
        parts = path.parts

        make = "Desconocido"
        model = ""
        category = CATEGORY_UNKNOWN
        subcategory = ""

        # Determinar categoria por el directorio de primer nivel
        for i, part in enumerate(parts):
            part_lower = part.lower().replace(" ", "-")
            for key, cat in _DIR_CATEGORY_MAP.items():
                if key in part_lower:
                    category = cat
                    break
            if category != CATEGORY_UNKNOWN:
                break

        # Buscar la marca en los subdirectorios
        # Tipicamente la marca es el penultimo o antepenultimo directorio
        for part in reversed(parts[:-1]):
            cleaned = self._clean_make_name(part)
            if self._looks_like_make(cleaned):
                make = cleaned
                break

        # Intentar extraer modelo del nombre del archivo
        file_stem = path.stem
        file_stem_clean = re.sub(
            r'\s*(?:Diesel|Gasolina|Flex|k|h|l)\s*$',
            '', file_stem, flags=re.IGNORECASE
        ).strip()

        # Si el nombre del archivo es diferente de la marca, puede ser el modelo
        if file_stem_clean.lower() != make.lower() and len(file_stem_clean) > 1:
            model = file_stem_clean

        return VehicleCategory(
            make=make,
            model=model,
            category=category,
            subcategory=subcategory,
            source_path=str(path),
        )


# ---------------------------------------------------------------------------
# KnowledgeIndexer
# ---------------------------------------------------------------------------

class KnowledgeIndexer:
    """Construye un indice buscable a partir del conocimiento extraido de PDFs.

    Almacena en SQLite para consultas rapidas.
    """

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_INDEX_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._extractor = PDFKnowledgeExtractor()
        self._init_database()

    def close(self) -> None:
        """Cierra la conexion a la base de datos."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _init_database(self) -> None:
        """Inicializa la base de datos SQLite con las tablas necesarias."""
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._conn.executescript("""
            -- Archivos PDF procesados
            CREATE TABLE IF NOT EXISTS pdf_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                file_name TEXT NOT NULL,
                category TEXT NOT NULL,
                vehicle_make TEXT,
                vehicle_model TEXT,
                file_size INTEGER,
                page_count INTEGER,
                text_length INTEGER,
                processed_at TEXT NOT NULL,
                processing_error TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_pdf_make ON pdf_files(vehicle_make);
            CREATE INDEX IF NOT EXISTS idx_pdf_category ON pdf_files(category);

            -- Codigos DTC
            CREATE TABLE IF NOT EXISTS dtc_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                description TEXT NOT NULL,
                system TEXT,
                severity TEXT,
                vehicle_make TEXT,
                vehicle_model TEXT,
                source_pdf_id INTEGER,
                FOREIGN KEY (source_pdf_id) REFERENCES pdf_files(id)
            );

            CREATE INDEX IF NOT EXISTS idx_dtc_code ON dtc_codes(code);
            CREATE INDEX IF NOT EXISTS idx_dtc_make ON dtc_codes(vehicle_make);

            -- Especificaciones de torque
            CREATE TABLE IF NOT EXISTS torque_specs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                component TEXT NOT NULL,
                torque_value REAL NOT NULL,
                unit TEXT NOT NULL,
                notes TEXT,
                vehicle_make TEXT,
                vehicle_model TEXT,
                source_pdf_id INTEGER,
                FOREIGN KEY (source_pdf_id) REFERENCES pdf_files(id)
            );

            CREATE INDEX IF NOT EXISTS idx_torque_make ON torque_specs(vehicle_make);

            -- Especificaciones de sensores
            CREATE TABLE IF NOT EXISTS sensor_specs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sensor_name TEXT NOT NULL,
                parameter TEXT NOT NULL,
                min_value REAL,
                max_value REAL,
                unit TEXT,
                condition TEXT,
                vehicle_make TEXT,
                source_pdf_id INTEGER,
                FOREIGN KEY (source_pdf_id) REFERENCES pdf_files(id)
            );

            CREATE INDEX IF NOT EXISTS idx_sensor_make ON sensor_specs(vehicle_make);

            -- Informacion de cableado
            CREATE TABLE IF NOT EXISTS wiring_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                connector_name TEXT,
                pin_number TEXT,
                wire_color TEXT,
                signal_description TEXT,
                ecu_name TEXT,
                vehicle_make TEXT,
                source_pdf_id INTEGER,
                FOREIGN KEY (source_pdf_id) REFERENCES pdf_files(id)
            );

            CREATE INDEX IF NOT EXISTS idx_wiring_make ON wiring_info(vehicle_make);

            -- Cobertura de vehiculos (resumen)
            CREATE TABLE IF NOT EXISTS vehicle_coverage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_make TEXT NOT NULL,
                vehicle_model TEXT,
                category TEXT NOT NULL,
                pdf_count INTEGER DEFAULT 0,
                dtc_count INTEGER DEFAULT 0,
                torque_count INTEGER DEFAULT 0,
                sensor_count INTEGER DEFAULT 0,
                wiring_count INTEGER DEFAULT 0,
                UNIQUE(vehicle_make, vehicle_model, category)
            );

            CREATE INDEX IF NOT EXISTS idx_coverage_make ON vehicle_coverage(vehicle_make);

            -- Indice de texto completo (FTS5)
            CREATE VIRTUAL TABLE IF NOT EXISTS full_text_index USING fts5(
                content,
                source_pdf,
                vehicle_make,
                category,
                tokenize='unicode61 remove_diacritics 2'
            );

            -- Metadatos del indice
            CREATE TABLE IF NOT EXISTS index_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # build_index
    # ------------------------------------------------------------------

    def build_index(self, data_path: Optional[str | Path] = None) -> IndexStats:
        """Escanea todos los PDFs, extrae conocimiento y lo almacena en SQLite.

        Args:
            data_path: Ruta al directorio data/. Si es None, usa la ruta por defecto.

        Returns:
            IndexStats con estadisticas del proceso.
        """
        if not self._conn:
            raise RuntimeError("Base de datos no inicializada")

        stats = IndexStats()
        start_time = time.time()

        logger.info("Iniciando construccion del indice...")

        # 1. Escanear directorio
        inventory = self._extractor.scan_data_directory(data_path)
        logger.info(
            "Encontrados %d archivos PDF de %d marcas",
            inventory.total_files,
            len(inventory.makes_found),
        )

        # 2. Procesar cada PDF
        for make, categories in inventory.by_make.items():
            for category, pdf_paths in categories.items():
                for pdf_path in pdf_paths:
                    try:
                        self._process_single_pdf(
                            pdf_path, make, category, stats
                        )
                    except Exception as exc:
                        stats.files_failed += 1
                        error_msg = f"Error procesando {Path(pdf_path).name}: {exc}"
                        stats.errors.append(error_msg)
                        logger.warning(error_msg)

        # 3. Construir resumen de cobertura
        self._build_coverage_summary()

        # 4. Guardar metadatos
        stats.processing_time_seconds = round(time.time() - start_time, 2)
        stats.vehicles_indexed = len(inventory.makes_found)

        self._save_metadata(stats)
        self._conn.commit()

        logger.info(
            "Indice construido: %d archivos, %d DTCs, %d torques, %.1f seg",
            stats.files_processed,
            stats.dtcs_found,
            stats.torque_specs_found,
            stats.processing_time_seconds,
        )
        return stats

    def _process_single_pdf(
        self,
        pdf_path: str,
        make: str,
        category: str,
        stats: IndexStats,
    ) -> None:
        """Procesa un unico PDF y almacena los resultados."""
        assert self._conn is not None

        path = Path(pdf_path)
        logger.debug("Procesando: %s", path.name)

        # Verificar si ya fue procesado
        existing = self._conn.execute(
            "SELECT id FROM pdf_files WHERE file_path = ?",
            (str(path),),
        ).fetchone()
        if existing:
            logger.debug("Ya procesado: %s", path.name)
            stats.files_processed += 1
            return

        # Extraer texto
        try:
            text = self._extractor.extract_text_from_pdf(path)
        except Exception as exc:
            # Registrar el archivo con error
            self._conn.execute(
                """INSERT INTO pdf_files
                   (file_path, file_name, category, vehicle_make, processed_at, processing_error)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(path), path.name, category, make,
                 datetime.now().isoformat(), str(exc)),
            )
            raise

        # Categorizar vehiculo
        vehicle_cat = self._extractor.categorize_vehicle(path)
        vehicle_model = vehicle_cat.model

        # Obtener info del archivo
        try:
            doc = fitz.open(str(path))
            page_count = len(doc)
            doc.close()
        except Exception:
            page_count = 0

        # Insertar registro del archivo
        cursor = self._conn.execute(
            """INSERT INTO pdf_files
               (file_path, file_name, category, vehicle_make, vehicle_model,
                file_size, page_count, text_length, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(path), path.name, category, make, vehicle_model,
             path.stat().st_size, page_count, len(text),
             datetime.now().isoformat()),
        )
        pdf_id = cursor.lastrowid

        # Extraer DTCs
        dtcs = self._extractor.extract_dtc_codes(text, str(path))
        for dtc in dtcs:
            dtc.vehicle_make = make
            dtc.vehicle_model = vehicle_model
            self._conn.execute(
                """INSERT INTO dtc_codes
                   (code, description, system, severity, vehicle_make,
                    vehicle_model, source_pdf_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (dtc.code, dtc.description, dtc.system, dtc.severity,
                 make, vehicle_model, pdf_id),
            )
        stats.dtcs_found += len(dtcs)

        # Extraer torques
        torques = self._extractor.extract_torque_specs(text, str(path))
        for spec in torques:
            spec.vehicle_make = make
            spec.vehicle_model = vehicle_model
            self._conn.execute(
                """INSERT INTO torque_specs
                   (component, torque_value, unit, notes, vehicle_make,
                    vehicle_model, source_pdf_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (spec.component, spec.torque_value, spec.unit, spec.notes,
                 make, vehicle_model, pdf_id),
            )
        stats.torque_specs_found += len(torques)

        # Extraer sensores
        sensors = self._extractor.extract_sensor_specs(text, str(path))
        for sensor in sensors:
            sensor.vehicle_make = make
            self._conn.execute(
                """INSERT INTO sensor_specs
                   (sensor_name, parameter, min_value, max_value, unit,
                    condition, vehicle_make, source_pdf_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (sensor.sensor_name, sensor.parameter, sensor.min_value,
                 sensor.max_value, sensor.unit, sensor.condition,
                 make, pdf_id),
            )
        stats.sensor_specs_found += len(sensors)

        # Extraer cableado
        wiring = self._extractor.extract_wiring_info(text, str(path))
        for wire in wiring:
            wire.vehicle_make = make
            self._conn.execute(
                """INSERT INTO wiring_info
                   (connector_name, pin_number, wire_color, signal_description,
                    ecu_name, vehicle_make, source_pdf_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (wire.connector_name, wire.pin_number, wire.wire_color,
                 wire.signal_description, wire.ecu_name, make, pdf_id),
            )
        stats.wiring_entries_found += len(wiring)

        # Indexar texto completo (dividir en fragmentos de ~500 caracteres)
        if text:
            chunks = self._chunk_text(text, chunk_size=500)
            for chunk in chunks:
                self._conn.execute(
                    """INSERT INTO full_text_index
                       (content, source_pdf, vehicle_make, category)
                       VALUES (?, ?, ?, ?)""",
                    (chunk, str(path), make, category),
                )

        stats.files_processed += 1

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 500) -> list[str]:
        """Divide el texto en fragmentos para indexacion FTS."""
        chunks: list[str] = []
        # Dividir por parrafos primero
        paragraphs = text.split("\n\n")
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) < chunk_size:
                current_chunk += " " + para if current_chunk else para
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                # Si el parrafo es mas grande que chunk_size, dividirlo
                if len(para) > chunk_size:
                    words = para.split()
                    current_chunk = ""
                    for word in words:
                        if len(current_chunk) + len(word) + 1 < chunk_size:
                            current_chunk += " " + word if current_chunk else word
                        else:
                            if current_chunk:
                                chunks.append(current_chunk)
                            current_chunk = word
                else:
                    current_chunk = para

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _build_coverage_summary(self) -> None:
        """Construye el resumen de cobertura de vehiculos."""
        if not self._conn:
            return

        # Limpiar tabla existente
        self._conn.execute("DELETE FROM vehicle_coverage")

        # Construir desde los datos indexados
        rows = self._conn.execute("""
            SELECT vehicle_make, vehicle_model, category,
                   COUNT(*) as pdf_count
            FROM pdf_files
            WHERE vehicle_make IS NOT NULL
            GROUP BY vehicle_make, vehicle_model, category
        """).fetchall()

        for row in rows:
            make = row["vehicle_make"]
            model = row["vehicle_model"] or ""
            cat = row["category"]

            # Contar DTCs para este vehiculo/categoria
            dtc_count = self._conn.execute(
                """SELECT COUNT(*) as cnt FROM dtc_codes
                   WHERE vehicle_make = ? AND (vehicle_model = ? OR ? = '')""",
                (make, model, model),
            ).fetchone()["cnt"]

            # Contar torques
            torque_count = self._conn.execute(
                """SELECT COUNT(*) as cnt FROM torque_specs
                   WHERE vehicle_make = ? AND (vehicle_model = ? OR ? = '')""",
                (make, model, model),
            ).fetchone()["cnt"]

            # Contar sensores
            sensor_count = self._conn.execute(
                """SELECT COUNT(*) as cnt FROM sensor_specs
                   WHERE vehicle_make = ?""",
                (make,),
            ).fetchone()["cnt"]

            # Contar cableado
            wiring_count = self._conn.execute(
                """SELECT COUNT(*) as cnt FROM wiring_info
                   WHERE vehicle_make = ?""",
                (make,),
            ).fetchone()["cnt"]

            self._conn.execute(
                """INSERT OR REPLACE INTO vehicle_coverage
                   (vehicle_make, vehicle_model, category, pdf_count,
                    dtc_count, torque_count, sensor_count, wiring_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (make, model, cat, row["pdf_count"],
                 dtc_count, torque_count, sensor_count, wiring_count),
            )

    def _save_metadata(self, stats: IndexStats) -> None:
        """Guarda metadatos del indice."""
        if not self._conn:
            return

        metadata = {
            "last_build": datetime.now().isoformat(),
            "files_processed": str(stats.files_processed),
            "files_failed": str(stats.files_failed),
            "dtcs_found": str(stats.dtcs_found),
            "torque_specs_found": str(stats.torque_specs_found),
            "sensor_specs_found": str(stats.sensor_specs_found),
            "wiring_entries_found": str(stats.wiring_entries_found),
            "processing_time": str(stats.processing_time_seconds),
        }

        for key, value in metadata.items():
            self._conn.execute(
                """INSERT OR REPLACE INTO index_metadata (key, value)
                   VALUES (?, ?)""",
                (key, value),
            )

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        make: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """Busqueda de texto completo en todo el conocimiento extraido.

        Args:
            query: Texto a buscar.
            make: Filtrar por marca de vehiculo.
            category: Filtrar por categoria de conocimiento.
            limit: Maximo de resultados.

        Returns:
            Lista de SearchResult ordenados por relevancia.
        """
        if not self._conn:
            return []

        results: list[SearchResult] = []

        # Busqueda FTS5
        fts_query = self._prepare_fts_query(query)

        try:
            if make and category:
                rows = self._conn.execute(
                    """SELECT content, source_pdf, vehicle_make, category,
                              rank
                       FROM full_text_index
                       WHERE full_text_index MATCH ?
                         AND vehicle_make = ?
                         AND category = ?
                       ORDER BY rank
                       LIMIT ?""",
                    (fts_query, make, category, limit),
                ).fetchall()
            elif make:
                rows = self._conn.execute(
                    """SELECT content, source_pdf, vehicle_make, category,
                              rank
                       FROM full_text_index
                       WHERE full_text_index MATCH ?
                         AND vehicle_make = ?
                       ORDER BY rank
                       LIMIT ?""",
                    (fts_query, make, limit),
                ).fetchall()
            elif category:
                rows = self._conn.execute(
                    """SELECT content, source_pdf, vehicle_make, category,
                              rank
                       FROM full_text_index
                       WHERE full_text_index MATCH ?
                         AND category = ?
                       ORDER BY rank
                       LIMIT ?""",
                    (fts_query, category, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """SELECT content, source_pdf, vehicle_make, category,
                              rank
                       FROM full_text_index
                       WHERE full_text_index MATCH ?
                       ORDER BY rank
                       LIMIT ?""",
                    (fts_query, limit),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            logger.warning("Error en busqueda FTS: %s", exc)
            rows = []

        for row in rows:
            # Calcular snippet relevante
            content = row["content"]
            snippet = self._extract_snippet(content, query)

            results.append(SearchResult(
                source_pdf=row["source_pdf"],
                category=row["category"],
                vehicle_make=row["vehicle_make"],
                snippet=snippet,
                relevance_score=abs(row["rank"]) if row["rank"] else 0.0,
                data_type="text",
            ))

        # Complementar con busqueda en tablas estructuradas
        results.extend(self._search_dtcs(query, make, limit=5))
        results.extend(self._search_torques(query, make, limit=5))

        # Ordenar por relevancia
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:limit]

    @staticmethod
    def _prepare_fts_query(query: str) -> str:
        """Prepara la consulta para FTS5."""
        # Escapar caracteres especiales de FTS5
        cleaned = re.sub(r'[^\w\s]', ' ', query)
        terms = cleaned.split()
        if not terms:
            return query
        # Unir con OR para busqueda flexible
        return " OR ".join(f'"{term}"' for term in terms if term)

    @staticmethod
    def _extract_snippet(content: str, query: str, max_len: int = 200) -> str:
        """Extrae un snippet relevante del contenido."""
        query_lower = query.lower()
        content_lower = content.lower()

        # Buscar la primera ocurrencia del termino
        pos = content_lower.find(query_lower)
        if pos == -1:
            # Intentar con terminos individuales
            for term in query_lower.split():
                pos = content_lower.find(term)
                if pos != -1:
                    break

        if pos == -1:
            return content[:max_len] + ("..." if len(content) > max_len else "")

        # Centrar el snippet alrededor de la coincidencia
        start = max(0, pos - max_len // 3)
        end = min(len(content), start + max_len)

        snippet = content[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."

        return snippet

    def _search_dtcs(
        self, query: str, make: Optional[str], limit: int = 5
    ) -> list[SearchResult]:
        """Busca en la tabla de DTCs."""
        if not self._conn:
            return []

        results: list[SearchResult] = []
        query_upper = query.upper()

        # Buscar por codigo DTC
        if re.match(r'^[PCBU]\d{3,5}$', query_upper):
            if make:
                rows = self._conn.execute(
                    """SELECT code, description, system, severity, vehicle_make
                       FROM dtc_codes
                       WHERE code = ? AND vehicle_make = ?
                       LIMIT ?""",
                    (query_upper, make, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """SELECT code, description, system, severity, vehicle_make
                       FROM dtc_codes
                       WHERE code = ?
                       LIMIT ?""",
                    (query_upper, limit),
                ).fetchall()

            for row in rows:
                results.append(SearchResult(
                    source_pdf="",
                    category=CATEGORY_OBD_CODES,
                    vehicle_make=row["vehicle_make"] or "",
                    snippet=f"{row['code']}: {row['description']} [{row['system']}] - {row['severity']}",
                    relevance_score=10.0,
                    data_type="dtc",
                ))

        return results

    def _search_torques(
        self, query: str, make: Optional[str], limit: int = 5
    ) -> list[SearchResult]:
        """Busca en la tabla de torques."""
        if not self._conn:
            return []

        results: list[SearchResult] = []

        if make:
            rows = self._conn.execute(
                """SELECT component, torque_value, unit, vehicle_make
                   FROM torque_specs
                   WHERE vehicle_make = ?
                     AND component LIKE ?
                   LIMIT ?""",
                (make, f"%{query}%", limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT component, torque_value, unit, vehicle_make
                   FROM torque_specs
                   WHERE component LIKE ?
                   LIMIT ?""",
                (f"%{query}%", limit),
            ).fetchall()

        for row in rows:
            results.append(SearchResult(
                source_pdf="",
                category=CATEGORY_TECHNICAL_DATA,
                vehicle_make=row["vehicle_make"] or "",
                snippet=f"{row['component']}: {row['torque_value']} {row['unit']}",
                relevance_score=8.0,
                data_type="torque",
            ))

        return results

    # ------------------------------------------------------------------
    # get_dtcs_for_vehicle
    # ------------------------------------------------------------------

    def get_dtcs_for_vehicle(
        self,
        make: str,
        model: Optional[str] = None,
    ) -> list[DTCEntry]:
        """Retorna todos los DTCs conocidos para un vehiculo especifico.

        Args:
            make: Marca del vehiculo.
            model: Modelo del vehiculo (opcional).

        Returns:
            Lista de DTCEntry para el vehiculo.
        """
        if not self._conn:
            return []

        if model:
            rows = self._conn.execute(
                """SELECT code, description, system, severity,
                          vehicle_make, vehicle_model
                   FROM dtc_codes
                   WHERE vehicle_make = ?
                     AND (vehicle_model = ? OR vehicle_model LIKE ?)
                   ORDER BY code""",
                (make, model, f"%{model}%"),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT code, description, system, severity,
                          vehicle_make, vehicle_model
                   FROM dtc_codes
                   WHERE vehicle_make = ?
                   ORDER BY code""",
                (make,),
            ).fetchall()

        return [
            DTCEntry(
                code=row["code"],
                description=row["description"],
                system=row["system"] or "",
                severity=row["severity"] or "",
                source_pdf="",
                vehicle_make=row["vehicle_make"] or "",
                vehicle_model=row["vehicle_model"] or "",
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # get_torque_specs
    # ------------------------------------------------------------------

    def get_torque_specs(
        self,
        make: str,
        model: Optional[str] = None,
    ) -> list[TorqueSpec]:
        """Retorna especificaciones de torque para un vehiculo.

        Args:
            make: Marca del vehiculo.
            model: Modelo del vehiculo (opcional).

        Returns:
            Lista de TorqueSpec.
        """
        if not self._conn:
            return []

        if model:
            rows = self._conn.execute(
                """SELECT component, torque_value, unit, notes,
                          vehicle_make, vehicle_model
                   FROM torque_specs
                   WHERE vehicle_make = ?
                     AND (vehicle_model = ? OR vehicle_model LIKE ?)
                   ORDER BY component""",
                (make, model, f"%{model}%"),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT component, torque_value, unit, notes,
                          vehicle_make, vehicle_model
                   FROM torque_specs
                   WHERE vehicle_make = ?
                   ORDER BY component""",
                (make,),
            ).fetchall()

        return [
            TorqueSpec(
                component=row["component"],
                torque_value=row["torque_value"],
                unit=row["unit"],
                notes=row["notes"] or "",
                source_pdf="",
                vehicle_make=row["vehicle_make"] or "",
                vehicle_model=row["vehicle_model"] or "",
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # get_vehicle_coverage
    # ------------------------------------------------------------------

    def get_vehicle_coverage(self) -> dict[str, list[str]]:
        """Retorna las marcas y modelos/sistemas cubiertos.

        Returns:
            Diccionario {make: [modelos o sistemas cubiertos]}.
        """
        if not self._conn:
            return {}

        rows = self._conn.execute("""
            SELECT vehicle_make, vehicle_model, category
            FROM vehicle_coverage
            WHERE vehicle_make IS NOT NULL
            ORDER BY vehicle_make, vehicle_model
        """).fetchall()

        coverage: dict[str, list[str]] = {}
        for row in rows:
            make = row["vehicle_make"]
            if make not in coverage:
                coverage[make] = []
            entry = row["vehicle_model"] or row["category"]
            if entry and entry not in coverage[make]:
                coverage[make].append(entry)

        return coverage

    # ------------------------------------------------------------------
    # get_stats
    # ------------------------------------------------------------------

    def get_stats(self) -> IndexStats:
        """Retorna estadisticas del indice actual.

        Returns:
            IndexStats con informacion del indice.
        """
        if not self._conn:
            return IndexStats()

        stats = IndexStats()

        stats.files_processed = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM pdf_files WHERE processing_error IS NULL"
        ).fetchone()["cnt"]

        stats.files_failed = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM pdf_files WHERE processing_error IS NOT NULL"
        ).fetchone()["cnt"]

        stats.dtcs_found = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM dtc_codes"
        ).fetchone()["cnt"]

        stats.torque_specs_found = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM torque_specs"
        ).fetchone()["cnt"]

        stats.sensor_specs_found = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM sensor_specs"
        ).fetchone()["cnt"]

        stats.wiring_entries_found = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM wiring_info"
        ).fetchone()["cnt"]

        stats.vehicles_indexed = self._conn.execute(
            "SELECT COUNT(DISTINCT vehicle_make) as cnt FROM pdf_files"
        ).fetchone()["cnt"]

        # Leer tiempo de procesamiento de metadatos
        row = self._conn.execute(
            "SELECT value FROM index_metadata WHERE key = 'processing_time'"
        ).fetchone()
        if row:
            try:
                stats.processing_time_seconds = float(row["value"])
            except (ValueError, TypeError):
                pass

        return stats


# ---------------------------------------------------------------------------
# LearningEngine
# ---------------------------------------------------------------------------

class LearningEngine:
    """Motor de aprendizaje del agente IA.

    Usa el extractor y el indexador para aprender de los PDFs
    y proveer conocimiento al agente de diagnostico.
    """

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        self._indexer = KnowledgeIndexer(db_path=db_path)
        self._extractor = PDFKnowledgeExtractor()

    def close(self) -> None:
        """Cierra recursos."""
        self._indexer.close()

    # ------------------------------------------------------------------
    # learn_from_pdfs
    # ------------------------------------------------------------------

    def learn_from_pdfs(
        self, data_path: Optional[str | Path] = None
    ) -> LearningReport:
        """Pipeline completo de aprendizaje desde PDFs.

        1. Escanea el directorio de datos
        2. Extrae texto de cada PDF
        3. Parsea DTCs, torques, especificaciones de sensores
        4. Construye referencias cruzadas
        5. Crea perfiles de vehiculos
        6. Almacena todo en la base de conocimiento

        Args:
            data_path: Ruta al directorio data/. Si es None, usa la ruta por defecto.

        Returns:
            LearningReport con el resumen de lo aprendido.
        """
        report = LearningReport(
            timestamp=datetime.now().isoformat(),
            data_path=str(data_path or _DEFAULT_DATA_PATH),
        )

        logger.info("Iniciando proceso de aprendizaje desde PDFs...")

        # 1-6. El indexador maneja todo el pipeline
        try:
            stats = self._indexer.build_index(data_path)
            report.index_stats = stats
        except Exception as exc:
            logger.error("Error durante el aprendizaje: %s", exc)
            report.summary = f"Error durante el aprendizaje: {exc}"
            return report

        # Obtener resumen de cobertura
        coverage = self._indexer.get_vehicle_coverage()
        report.vehicle_makes_learned = sorted(coverage.keys())
        report.categories_covered = list(set(
            cat
            for cats in coverage.values()
            for cat in cats
        ))

        # Generar resumen en espanol
        report.summary = self._generate_learning_summary(stats, coverage)

        logger.info("Aprendizaje completado: %s", report.summary[:200])
        return report

    @staticmethod
    def _generate_learning_summary(
        stats: IndexStats, coverage: dict[str, list[str]]
    ) -> str:
        """Genera un resumen legible del aprendizaje en espanol."""
        lines = [
            "=== Resumen de Aprendizaje ===",
            f"Archivos procesados: {stats.files_processed}",
            f"Archivos con errores: {stats.files_failed}",
            f"Codigos DTC encontrados: {stats.dtcs_found}",
            f"Especificaciones de torque: {stats.torque_specs_found}",
            f"Especificaciones de sensores: {stats.sensor_specs_found}",
            f"Entradas de cableado: {stats.wiring_entries_found}",
            f"Marcas indexadas: {stats.vehicles_indexed}",
            f"Tiempo de procesamiento: {stats.processing_time_seconds:.1f} segundos",
            "",
            "Marcas cubiertas:",
        ]

        for make in sorted(coverage.keys()):
            models = coverage[make]
            lines.append(f"  - {make}: {', '.join(models[:5])}")
            if len(models) > 5:
                lines.append(f"    ... y {len(models) - 5} mas")

        if stats.errors:
            lines.append("")
            lines.append(f"Errores ({len(stats.errors)}):")
            for err in stats.errors[:10]:
                lines.append(f"  - {err}")
            if len(stats.errors) > 10:
                lines.append(f"  ... y {len(stats.errors) - 10} errores mas")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # get_professional_advice
    # ------------------------------------------------------------------

    def get_professional_advice(
        self,
        vehicle_make: str,
        vehicle_model: str,
        question: str,
    ) -> str:
        """Responde preguntas tecnicas usando el conocimiento indexado.

        Todas las respuestas son en espanol.

        Args:
            vehicle_make: Marca del vehiculo (ej: "Toyota").
            vehicle_model: Modelo del vehiculo (ej: "Hilux").
            question: Pregunta en texto libre.

        Returns:
            Respuesta profesional basada en los datos indexados.

        Ejemplo:
            >>> engine.get_professional_advice(
            ...     "Toyota", "Hilux",
            ...     "Cual es el torque de la tapa de cilindros?"
            ... )
        """
        response_parts: list[str] = []
        question_lower = question.lower()

        response_parts.append(
            f"=== Consulta Tecnica: {vehicle_make} {vehicle_model} ==="
        )
        response_parts.append(f"Pregunta: {question}")
        response_parts.append("")

        # Detectar tipo de pregunta
        is_torque_question = any(
            kw in question_lower
            for kw in ["torque", "apriete", "ajuste", "nm", "kgf"]
        )
        is_dtc_question = any(
            kw in question_lower
            for kw in ["dtc", "codigo", "código", "falla", "error", "p0", "c0", "b0", "u0"]
        )
        is_sensor_question = any(
            kw in question_lower
            for kw in ["sensor", "voltaje", "resistencia", "señal", "sonda"]
        )
        is_wiring_question = any(
            kw in question_lower
            for kw in ["cable", "pin", "conector", "cableado", "color"]
        )

        found_data = False

        # Buscar torques
        if is_torque_question:
            torques = self._indexer.get_torque_specs(vehicle_make, vehicle_model)
            if torques:
                found_data = True
                response_parts.append("--- Especificaciones de Torque ---")
                # Filtrar por contexto de la pregunta
                relevant = self._filter_relevant_torques(torques, question)
                for spec in relevant[:15]:
                    response_parts.append(
                        f"  * {spec.component}: {spec.torque_value} {spec.unit}"
                    )
                    if spec.notes:
                        response_parts.append(f"    Nota: {spec.notes[:100]}")
                response_parts.append("")

        # Buscar DTCs
        if is_dtc_question:
            # Extraer codigo DTC de la pregunta si existe
            dtc_match = re.search(r'[PCBU]\d{4,5}', question.upper())
            if dtc_match:
                dtc_code = dtc_match.group(0)
                results = self._indexer.search(dtc_code, make=vehicle_make)
                if results:
                    found_data = True
                    response_parts.append(f"--- Informacion DTC {dtc_code} ---")
                    for result in results[:5]:
                        response_parts.append(f"  * {result.snippet}")
                    response_parts.append("")
            else:
                dtcs = self._indexer.get_dtcs_for_vehicle(
                    vehicle_make, vehicle_model
                )
                if dtcs:
                    found_data = True
                    response_parts.append("--- Codigos DTC Conocidos ---")
                    for dtc in dtcs[:20]:
                        response_parts.append(
                            f"  * {dtc.code}: {dtc.description} "
                            f"[{dtc.system}] - Severidad: {dtc.severity}"
                        )
                    response_parts.append("")

        # Buscar sensores
        if is_sensor_question:
            results = self._indexer.search(
                question, make=vehicle_make, category=CATEGORY_OBD_CODES
            )
            if results:
                found_data = True
                response_parts.append("--- Especificaciones de Sensores ---")
                for result in results[:10]:
                    response_parts.append(f"  * {result.snippet}")
                response_parts.append("")

        # Buscar cableado
        if is_wiring_question:
            results = self._indexer.search(
                question, make=vehicle_make, category=CATEGORY_COMPONENTS
            )
            if results:
                found_data = True
                response_parts.append("--- Informacion de Cableado ---")
                for result in results[:10]:
                    response_parts.append(f"  * {result.snippet}")
                response_parts.append("")

        # Busqueda general si no se encontro nada especifico
        if not found_data:
            results = self._indexer.search(question, make=vehicle_make)
            if results:
                found_data = True
                response_parts.append("--- Informacion Encontrada ---")
                for result in results[:10]:
                    response_parts.append(
                        f"  * [{result.category}] {result.snippet}"
                    )
                response_parts.append("")

        if not found_data:
            response_parts.append(
                "No se encontro informacion especifica para esta consulta "
                f"sobre {vehicle_make} {vehicle_model} en la base de conocimiento."
            )
            response_parts.append(
                "Recomendacion: Verificar que los PDFs del vehiculo estan "
                "incluidos en el directorio data/ y re-ejecutar el indexado."
            )

        return "\n".join(response_parts)

    @staticmethod
    def _filter_relevant_torques(
        torques: list[TorqueSpec], question: str
    ) -> list[TorqueSpec]:
        """Filtra torques relevantes basandose en la pregunta."""
        question_lower = question.lower()
        terms = [
            t for t in question_lower.split()
            if len(t) > 2 and t not in {
                "cual", "cuál", "del", "los", "las", "que", "qué",
                "para", "por", "con", "sin", "una", "uno", "the",
                "torque", "apriete", "ajuste", "es",
            }
        ]

        if not terms:
            return torques

        scored: list[tuple[float, TorqueSpec]] = []
        for spec in torques:
            comp_lower = spec.component.lower()
            score = sum(
                1.0 for term in terms if term in comp_lower
            )
            if score > 0:
                scored.append((score, spec))

        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            return [s[1] for s in scored]

        return torques

    # ------------------------------------------------------------------
    # get_repair_procedure
    # ------------------------------------------------------------------

    def get_repair_procedure(
        self,
        dtc_code: str,
        vehicle_make: str,
    ) -> RepairProcedure:
        """Genera un procedimiento de reparacion basado en conocimiento aprendido.

        Args:
            dtc_code: Codigo DTC (ej: "P0420").
            vehicle_make: Marca del vehiculo.

        Returns:
            RepairProcedure con pasos de diagnostico.
        """
        dtc_code = dtc_code.upper()

        # Buscar el DTC en la base de conocimiento
        dtcs = self._indexer.get_dtcs_for_vehicle(vehicle_make)
        matching_dtcs = [d for d in dtcs if d.code == dtc_code]

        description = ""
        system = ""
        severity = ""

        if matching_dtcs:
            dtc_info = matching_dtcs[0]
            description = dtc_info.description
            system = dtc_info.system
            severity = dtc_info.severity

        # Buscar DTCs relacionados
        related_codes: list[str] = []
        if dtc_code.startswith("P"):
            # Buscar DTCs del mismo rango
            try:
                base_num = int(dtc_code[1:])
                range_start = (base_num // 10) * 10
                range_end = range_start + 10
                for d in dtcs:
                    try:
                        d_num = int(d.code[1:])
                        if range_start <= d_num < range_end and d.code != dtc_code:
                            related_codes.append(d.code)
                    except ValueError:
                        continue
            except ValueError:
                pass

        # Buscar informacion adicional por texto
        search_results = self._indexer.search(dtc_code, make=vehicle_make)

        # Generar posibles causas basadas en el sistema
        possible_causes = self._generate_possible_causes(
            dtc_code, system, description
        )

        # Generar pasos de diagnostico
        diagnostic_steps = self._generate_diagnostic_steps(
            dtc_code, system, description, search_results
        )

        # Buscar torques relevantes
        torque_specs: list[TorqueSpec] = []
        if system:
            all_torques = self._indexer.get_torque_specs(vehicle_make)
            system_lower = system.lower()
            torque_specs = [
                t for t in all_torques
                if any(kw in t.component.lower() for kw in system_lower.split("/"))
            ][:10]

        procedure = RepairProcedure(
            dtc_code=dtc_code,
            vehicle_make=vehicle_make,
            description=description or f"Codigo de falla {dtc_code}",
            possible_causes=possible_causes,
            diagnostic_steps=diagnostic_steps,
            related_dtcs=related_codes[:5],
            torque_specs=torque_specs,
        )

        return procedure

    @staticmethod
    def _generate_possible_causes(
        dtc_code: str, system: str, description: str
    ) -> list[str]:
        """Genera posibles causas basadas en el codigo y sistema."""
        causes: list[str] = []
        prefix = dtc_code[0].upper() if dtc_code else ""
        desc_lower = description.lower()

        if prefix == "P":
            if "sensor" in desc_lower:
                causes.extend([
                    "Sensor defectuoso o fuera de rango",
                    "Cableado del sensor danado o con corto circuito",
                    "Conector del sensor corroido o suelto",
                    "Problema en la alimentacion del sensor",
                ])
            elif "inyect" in desc_lower or "inject" in desc_lower or "injeç" in desc_lower:
                causes.extend([
                    "Inyector obstruido o con fugas",
                    "Problema en el circuito electrico del inyector",
                    "Presion de combustible fuera de rango",
                    "Filtro de combustible obstruido",
                ])
            elif "turbo" in desc_lower:
                causes.extend([
                    "Actuador de la valvula wastegate defectuoso",
                    "Fuga en el sistema de admision",
                    "Turbocompresor danado",
                    "Sensor de presion del turbo defectuoso",
                ])
            else:
                causes.extend([
                    "Componente del tren motriz defectuoso",
                    "Problema electrico en el circuito",
                    "ECU requiere actualizacion o reprogramacion",
                ])
        elif prefix == "C":
            causes.extend([
                "Sensor de velocidad de rueda defectuoso",
                "Problema en el modulo ABS/ESP",
                "Cableado del sistema de frenos danado",
                "Bomba hidraulica del ABS defectuosa",
            ])
        elif prefix == "B":
            causes.extend([
                "Sensor de impacto defectuoso",
                "Problema en el modulo de airbag (SRS)",
                "Conector del pretensor de cinturon danado",
                "Cableado del sistema de airbag con resistencia anormal",
            ])
        elif prefix == "U":
            causes.extend([
                "Problema de comunicacion CAN bus",
                "Modulo de control no responde",
                "Cableado de red de datos danado",
                "Resistencias de terminacion CAN bus incorrectas",
            ])

        return causes

    @staticmethod
    def _generate_diagnostic_steps(
        dtc_code: str,
        system: str,
        description: str,
        search_results: list[SearchResult],
    ) -> list[str]:
        """Genera pasos de diagnostico basados en el conocimiento."""
        steps: list[str] = [
            f"1. Conectar escaner OBD2 y verificar DTC {dtc_code} activo",
            "2. Verificar datos en vivo (freeze frame) asociados al codigo",
            "3. Borrar el codigo y realizar prueba de manejo para confirmar reincidencia",
        ]

        prefix = dtc_code[0].upper() if dtc_code else ""

        if prefix == "P":
            steps.extend([
                "4. Inspeccionar visualmente el componente y cableado asociado",
                "5. Medir voltaje/resistencia en el conector del componente",
                "6. Verificar continuidad del cableado hacia la ECU",
                "7. Si los valores electricos son correctos, considerar reemplazo del componente",
                "8. Borrar codigo y verificar reparacion con prueba de manejo",
            ])
        elif prefix == "C":
            steps.extend([
                "4. Inspeccionar sensores de velocidad de rueda",
                "5. Verificar resistencia de cada sensor (tipico: 1000-2000 ohms)",
                "6. Inspeccionar anillo dentado (reluctor) de cada rueda",
                "7. Verificar voltaje de alimentacion del modulo ABS",
                "8. Comprobar comunicacion con el modulo ABS por CAN bus",
            ])
        elif prefix == "B":
            steps.extend([
                "4. PRECAUCION: Desconectar bateria y esperar 10 minutos antes de trabajar en el sistema SRS",
                "5. Inspeccionar conectores del modulo de airbag",
                "6. Medir resistencia de los squibs (tipico: 2-4 ohms)",
                "7. Verificar sensor de impacto y cableado",
                "8. Reconectar bateria y borrar codigo",
            ])
        elif prefix == "U":
            steps.extend([
                "4. Verificar voltajes del bus CAN: CAN-H ~2.5-3.5V, CAN-L ~1.5-2.5V",
                "5. Comprobar resistencias de terminacion (60 ohms en cada extremo)",
                "6. Inspeccionar cableado de red por cortocircuitos",
                "7. Verificar alimentacion del modulo que no responde",
                "8. Intentar comunicacion directa con el modulo afectado",
            ])

        # Agregar informacion de los resultados de busqueda
        if search_results:
            steps.append("")
            steps.append(
                "NOTA: Se encontro informacion adicional en la base de conocimiento. "
                "Consultar los datos del fabricante para procedimientos especificos."
            )

        return steps

    # ------------------------------------------------------------------
    # get_vehicle_knowledge_summary
    # ------------------------------------------------------------------

    def get_vehicle_knowledge_summary(
        self,
        make: str,
        model: Optional[str] = None,
    ) -> str:
        """Genera un resumen de todo lo conocido sobre un vehiculo.

        Todas las respuestas son en espanol.

        Args:
            make: Marca del vehiculo.
            model: Modelo del vehiculo (opcional).

        Returns:
            Resumen completo en espanol.
        """
        parts: list[str] = []
        vehicle_name = f"{make} {model}" if model else make

        parts.append(f"=== Base de Conocimiento: {vehicle_name} ===")
        parts.append("")

        # DTCs conocidos
        dtcs = self._indexer.get_dtcs_for_vehicle(make, model)
        if dtcs:
            parts.append(f"--- Codigos DTC ({len(dtcs)} encontrados) ---")
            # Agrupar por sistema
            by_system: dict[str, list[DTCEntry]] = {}
            for dtc in dtcs:
                sys_name = dtc.system or "Otro"
                if sys_name not in by_system:
                    by_system[sys_name] = []
                by_system[sys_name].append(dtc)

            for sys_name, sys_dtcs in sorted(by_system.items()):
                parts.append(f"  [{sys_name}]")
                for dtc in sys_dtcs[:10]:
                    parts.append(
                        f"    {dtc.code}: {dtc.description} "
                        f"(Severidad: {dtc.severity})"
                    )
                if len(sys_dtcs) > 10:
                    parts.append(f"    ... y {len(sys_dtcs) - 10} codigos mas")
            parts.append("")

        # Torques
        torques = self._indexer.get_torque_specs(make, model)
        if torques:
            parts.append(f"--- Especificaciones de Torque ({len(torques)} encontradas) ---")
            for spec in torques[:20]:
                parts.append(
                    f"  * {spec.component}: {spec.torque_value} {spec.unit}"
                )
            if len(torques) > 20:
                parts.append(f"  ... y {len(torques) - 20} especificaciones mas")
            parts.append("")

        # Cobertura general
        coverage = self._indexer.get_vehicle_coverage()
        if make in coverage:
            parts.append("--- Sistemas Cubiertos ---")
            for item in coverage[make]:
                parts.append(f"  * {item}")
            parts.append("")

        # Estadisticas
        stats = self._indexer.get_stats()
        parts.append("--- Estadisticas Generales del Indice ---")
        parts.append(f"  Total de archivos procesados: {stats.files_processed}")
        parts.append(f"  Total de DTCs en el indice: {stats.dtcs_found}")
        parts.append(f"  Total de torques en el indice: {stats.torque_specs_found}")
        parts.append(f"  Total de marcas indexadas: {stats.vehicles_indexed}")

        if not dtcs and not torques:
            parts.append("")
            parts.append(
                f"NOTA: No se encontro informacion especifica para {vehicle_name}. "
                "Verificar que los PDFs correspondientes estan en el directorio data/ "
                "y ejecutar el proceso de aprendizaje con learn_from_pdfs()."
            )

        return "\n".join(parts)
