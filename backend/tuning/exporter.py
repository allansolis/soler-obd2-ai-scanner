"""
SOLER OBD2 AI Scanner - Map Exporter
=====================================
Exports :class:`ECUMapSet` instances to CSV, JSON, and binary (.bin)
formats compatible with common ECU flash tools.  Every exported file
embeds metadata (vehicle, date, profile, safety-check hash).
"""

from __future__ import annotations

import csv
import io
import json
import struct
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Union

import numpy as np

from backend.tuning.map_generator import ECUMap, ECUMapSet
from backend.tuning.safety import SafetyReport, SafetyVerifier


# ---------------------------------------------------------------------------
# Export format enumeration
# ---------------------------------------------------------------------------

class ExportFormat(str, Enum):
    CSV = "csv"
    JSON = "json"
    BIN = "bin"


# ---------------------------------------------------------------------------
# Binary format constants
# ---------------------------------------------------------------------------

# File signature for the SOLER .bin format
_BIN_MAGIC = b"SOLER_ECU"
_BIN_VERSION: int = 1

# Map ID bytes (used in binary header to identify each map)
_MAP_IDS: dict[str, int] = {
    "fuel_injection": 0x01,
    "ignition_timing": 0x02,
    "boost_pressure": 0x03,
    "vvt_intake": 0x04,
    "throttle_response": 0x05,
}


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------

def _build_metadata(
    maps: ECUMapSet,
    safety_report: Optional[SafetyReport] = None,
) -> dict:
    """Build a metadata dict for the export file header."""
    meta: dict = {
        "exporter": "SOLER OBD2 AI Scanner",
        "format_version": _BIN_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "vehicle_info": maps.vehicle_info,
        "rev_limiter": {
            "soft_limit_rpm": maps.rev_limiter.soft_limit_rpm,
            "hard_limit_rpm": maps.rev_limiter.hard_limit_rpm,
            "fuel_cut_percent": maps.rev_limiter.fuel_cut_percent,
            "ignition_retard_deg": maps.rev_limiter.ignition_retard_deg,
        },
        "launch_control": {
            "enabled": maps.launch_control.enabled,
            "launch_rpm": maps.launch_control.launch_rpm,
            "max_rpm": maps.launch_control.max_rpm,
            "ignition_retard_deg": maps.launch_control.ignition_retard_deg,
            "boost_limit_bar": maps.launch_control.boost_limit_bar,
            "time_limit_sec": maps.launch_control.time_limit_sec,
        },
    }

    if safety_report is not None:
        meta["safety"] = {
            "passed": safety_report.passed,
            "integrity_hash": safety_report.integrity_hash,
            "checks_total": len(safety_report.checks),
            "checks_failed": len(safety_report.failed_checks),
        }

    return meta


# ---------------------------------------------------------------------------
# Per-format serialisers
# ---------------------------------------------------------------------------

def _map_to_csv_string(ecu_map: ECUMap) -> str:
    """Serialise a single :class:`ECUMap` to a CSV string.

    Layout::

        <map_name>
        ,<x0>,<x1>,...
        <y0>,<d00>,<d01>,...
        <y1>,<d10>,<d11>,...
        ...
    """
    buf = io.StringIO()
    writer = csv.writer(buf)

    # Header row: map name, then x-axis values
    writer.writerow(
        [f"{ecu_map.name} ({ecu_map.unit})"]
        + [f"{v}" for v in ecu_map.x_axis.values]
    )

    # Axis label row
    writer.writerow(
        [f"{ecu_map.y_axis.name} \\ {ecu_map.x_axis.name}"]
        + [f"{v}" for v in ecu_map.x_axis.values]
    )

    # Data rows: y-axis value followed by map cells
    for i, y_val in enumerate(ecu_map.y_axis.values):
        writer.writerow(
            [f"{y_val}"]
            + [f"{ecu_map.data[i, j]}" for j in range(ecu_map.data.shape[1])]
        )

    return buf.getvalue()


def _mapset_to_csv(
    maps: ECUMapSet,
    metadata: dict,
) -> str:
    """Serialise a full :class:`ECUMapSet` to a combined CSV string."""
    sections: list[str] = []

    # Metadata as comment lines
    sections.append("# SOLER OBD2 AI Scanner - ECU Map Export")
    for key, val in metadata.items():
        if isinstance(val, dict):
            sections.append(f"# {key}: {json.dumps(val)}")
        else:
            sections.append(f"# {key}: {val}")
    sections.append("")

    for ecu_map in (
        maps.fuel_map,
        maps.ignition_map,
        maps.boost_map,
        maps.vvt_map,
        maps.throttle_map,
    ):
        sections.append(_map_to_csv_string(ecu_map))

    return "\n".join(sections)


def _mapset_to_json(
    maps: ECUMapSet,
    metadata: dict,
) -> str:
    """Serialise a full :class:`ECUMapSet` to a JSON string."""

    def _map_dict(ecu_map: ECUMap) -> dict:
        return {
            "name": ecu_map.name,
            "description": ecu_map.description,
            "unit": ecu_map.unit,
            "x_axis": {
                "name": ecu_map.x_axis.name,
                "unit": ecu_map.x_axis.unit,
                "values": ecu_map.x_axis.values.tolist(),
            },
            "y_axis": {
                "name": ecu_map.y_axis.name,
                "unit": ecu_map.y_axis.unit,
                "values": ecu_map.y_axis.values.tolist(),
            },
            "data": ecu_map.data.tolist(),
        }

    payload = {
        "metadata": metadata,
        "maps": {
            "fuel_injection": _map_dict(maps.fuel_map),
            "ignition_timing": _map_dict(maps.ignition_map),
            "boost_pressure": _map_dict(maps.boost_map),
            "vvt_intake": _map_dict(maps.vvt_map),
            "throttle_response": _map_dict(maps.throttle_map),
        },
    }

    return json.dumps(payload, indent=2)


def _mapset_to_bin(
    maps: ECUMapSet,
    metadata: dict,
) -> bytes:
    """Serialise a full :class:`ECUMapSet` to a binary blob.

    Binary layout (little-endian)::

        [9 bytes]  Magic "SOLER_ECU"
        [2 bytes]  Version (uint16)
        [4 bytes]  Metadata JSON length N (uint32)
        [N bytes]  Metadata JSON (UTF-8)
        -- per map (5 maps) --
        [1 byte ]  Map ID
        [2 bytes]  Rows (uint16)
        [2 bytes]  Cols (uint16)
        [R bytes]  X-axis values (float64 array, Cols elements)
        [R bytes]  Y-axis values (float64 array, Rows elements)
        [R bytes]  Data values   (float64 array, Rows*Cols elements)
        -- end per map --
        [32 bytes] SHA-256 integrity hash (from metadata if present)
    """
    buf = io.BytesIO()

    # Magic + version
    buf.write(_BIN_MAGIC)
    buf.write(struct.pack("<H", _BIN_VERSION))

    # Metadata JSON
    meta_bytes = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
    buf.write(struct.pack("<I", len(meta_bytes)))
    buf.write(meta_bytes)

    # Maps
    for ecu_map in (
        maps.fuel_map,
        maps.ignition_map,
        maps.boost_map,
        maps.vvt_map,
        maps.throttle_map,
    ):
        map_id = _MAP_IDS.get(ecu_map.name, 0xFF)
        rows, cols = ecu_map.data.shape

        buf.write(struct.pack("<B", map_id))
        buf.write(struct.pack("<HH", rows, cols))

        # Axis values as float64 arrays
        buf.write(ecu_map.x_axis.values.astype(np.float64).tobytes())
        buf.write(ecu_map.y_axis.values.astype(np.float64).tobytes())

        # Map data as float64 row-major
        buf.write(ecu_map.data.astype(np.float64).tobytes())

    # Integrity hash trailer (32 hex chars = 32 bytes ASCII)
    integrity = metadata.get("safety", {}).get("integrity_hash", "0" * 64)
    buf.write(integrity[:64].encode("ascii"))

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Public exporter class
# ---------------------------------------------------------------------------

class MapExporter:
    """Exports :class:`ECUMapSet` to various file formats.

    The exporter automatically runs safety verification before
    writing.  If verification fails the export is blocked unless
    ``force=True`` is passed (useful for diagnostics only).

    Parameters
    ----------
    verifier:
        A :class:`SafetyVerifier` instance.  If ``None`` a default
        one is created.
    """

    def __init__(self, verifier: Optional[SafetyVerifier] = None) -> None:
        self.verifier = verifier or SafetyVerifier()

    # ------------------------------------------------------------------
    # Core export
    # ------------------------------------------------------------------

    def export(
        self,
        maps: ECUMapSet,
        fmt: ExportFormat,
        output_path: Union[str, Path],
        *,
        force: bool = False,
    ) -> SafetyReport:
        """Export *maps* to *output_path* in the requested format.

        Parameters
        ----------
        maps:
            The map set to export.
        fmt:
            Target file format (csv, json, or bin).
        output_path:
            Destination file path.
        force:
            If ``True``, write the file even when safety verification
            fails.  A warning is embedded in the metadata.

        Returns
        -------
        SafetyReport
            The result of the safety check.

        Raises
        ------
        ValueError
            If safety verification fails and *force* is ``False``.
        """
        report = self.verifier.verify(maps)

        if not report.passed and not force:
            raise ValueError(
                f"Safety verification failed.  Export blocked.  "
                f"Failed checks: {[c.check_name for c in report.failed_checks]}"
            )

        metadata = _build_metadata(maps, report)
        if not report.passed:
            metadata["WARNING"] = "SAFETY_VERIFICATION_FAILED_FORCE_EXPORT"

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if fmt == ExportFormat.CSV:
            content = _mapset_to_csv(maps, metadata)
            path.write_text(content, encoding="utf-8")
        elif fmt == ExportFormat.JSON:
            content = _mapset_to_json(maps, metadata)
            path.write_text(content, encoding="utf-8")
        elif fmt == ExportFormat.BIN:
            blob = _mapset_to_bin(maps, metadata)
            path.write_bytes(blob)
        else:
            raise ValueError(f"Unsupported export format: {fmt}")

        return report

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------

    def export_csv(
        self,
        maps: ECUMapSet,
        output_path: Union[str, Path],
        **kwargs,
    ) -> SafetyReport:
        """Shortcut for :meth:`export` with ``ExportFormat.CSV``."""
        return self.export(maps, ExportFormat.CSV, output_path, **kwargs)

    def export_json(
        self,
        maps: ECUMapSet,
        output_path: Union[str, Path],
        **kwargs,
    ) -> SafetyReport:
        """Shortcut for :meth:`export` with ``ExportFormat.JSON``."""
        return self.export(maps, ExportFormat.JSON, output_path, **kwargs)

    def export_bin(
        self,
        maps: ECUMapSet,
        output_path: Union[str, Path],
        **kwargs,
    ) -> SafetyReport:
        """Shortcut for :meth:`export` with ``ExportFormat.BIN``."""
        return self.export(maps, ExportFormat.BIN, output_path, **kwargs)

    # ------------------------------------------------------------------
    # In-memory serialisation (for API responses)
    # ------------------------------------------------------------------

    def to_bytes(
        self,
        maps: ECUMapSet,
        fmt: ExportFormat,
        *,
        force: bool = False,
    ) -> tuple[bytes, SafetyReport]:
        """Serialise *maps* to bytes without writing to disk.

        Returns a ``(data_bytes, safety_report)`` tuple.
        """
        report = self.verifier.verify(maps)
        if not report.passed and not force:
            raise ValueError(
                f"Safety verification failed.  "
                f"Failed checks: {[c.check_name for c in report.failed_checks]}"
            )

        metadata = _build_metadata(maps, report)
        if not report.passed:
            metadata["WARNING"] = "SAFETY_VERIFICATION_FAILED_FORCE_EXPORT"

        if fmt == ExportFormat.CSV:
            data = _mapset_to_csv(maps, metadata).encode("utf-8")
        elif fmt == ExportFormat.JSON:
            data = _mapset_to_json(maps, metadata).encode("utf-8")
        elif fmt == ExportFormat.BIN:
            data = _mapset_to_bin(maps, metadata)
        else:
            raise ValueError(f"Unsupported export format: {fmt}")

        return data, report
