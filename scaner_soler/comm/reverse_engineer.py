"""
reverse_engineer.py — Módulo de Ingeniería Inversa para ECUs desconocidas.

Técnicas integradas de:
  - morluto/rea           : Agent-loop (observar → hipótesis → re-query)
  - morluto/awesome-RE    : Scapy-automotive: CANSocket, UDS, ISO-TP pattern analysis
  - zhaoxuya520/reverse-skill : FieldJournal + structured methodology routing
  - wtsxDev/RE            : Fuzzing grammar (PID/DID range scan con Peach-style grammar)

Flujo de trabajo:
  1. FieldJournal       → loguea todo (request bytes → response bytes)
  2. UnknownECUProfiler → sondea la ECU con probes básicos para clasificar protocolo
  3. PIDFuzzer          → barre rangos 0x00..0xFF (OBD) o 0x0000..0xFFFF (UDS DID)
  4. PatternAnalyzer    → histograma de bytes, entropía, clustering por arbitration ID
  5. ProtocolGuesser    → vota protocolo basándose en patrones estadísticos
  6. ReverseEngineerSession → orquesta todo en un workflow iterativo
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

# ── Constantes ─────────────────────────────────────────────────────────────────

# Probes básicos estándar para detectar qué protocolo responde
_PROBE_COMMANDS = [
    ("OBD_MODE01_00", "01 00"),           # Soportados PIDs 0x01-0x20
    ("OBD_MODE09_02", "09 02"),           # VIN
    ("UDS_DIAG_SESSION", "10 01"),        # UDS: DiagnosticSessionControl Default
    ("UDS_ECU_RESET", "11 01"),           # UDS: ECUReset SoftReset (NO enviar en producción)
    ("KWP_START_DIAG", "10 92"),          # KWP2000: startDiagnosticSession 0x92
    ("UDS_READ_DID_F190", "22 F1 90"),    # UDS: ReadDataByIdentifier VIN (DID 0xF190)
    ("UDS_READ_DID_F18C", "22 F1 8C"),    # UDS: ECU serial number
    ("ISO9141_INIT", "AT SP 3"),          # Cambiar a ISO 9141-2
    ("CAN_11BIT", "AT SP 6"),             # CAN 11-bit 500k
    ("CAN_29BIT", "AT SP 7"),             # CAN 29-bit 500k
]

# Patrones de respuesta que identifican protocolos
_PROTOCOL_SIGNATURES: dict[str, list[str]] = {
    "UDS":      ["50 01", "50 02", "50 03", "7F 10", "7F 11", "7F 22"],
    "KWP2000":  ["50 92", "50 81", "7F 10 14", "7F 10 35"],
    "OBD2_CAN": ["41 00", "41 0C", "41 0D", "49 02"],
    "ISO9141":  ["48 6B", "BF F3 96", "48 6B 10"],
    "EOBD":     ["43 00", "43 01", "47 00"],  # European OBD
}

# Rangos de DID UDS más comunes para fuzzing
_UDS_DID_RANGES: list[tuple[int, int, str]] = [
    (0xF100, 0xF1FF, "ECU Identification"),
    (0xD900, 0xD9FF, "Manufacturer Specific"),
    (0xDD00, 0xDDFF, "Diagnostic Data"),
    (0x0100, 0x01FF, "Vehicle Info"),
    (0x2000, 0x20FF, "Application Data"),
]

# ── FieldJournal ───────────────────────────────────────────────────────────────

@dataclass
class JournalEntry:
    """Una entrada del diario: request → response."""
    timestamp:    str
    session_id:   str
    cmd:          str           # hex string del comando enviado
    raw_response: str           # respuesta cruda del ELM/ECU
    parsed:       dict          # interpretación parcial si la hay
    protocol_hint: str = ""     # protocolo detectado en esta entrada
    tags:         list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ts": self.timestamp,
            "session": self.session_id,
            "cmd": self.cmd,
            "resp": self.raw_response,
            "parsed": self.parsed,
            "proto_hint": self.protocol_hint,
            "tags": self.tags,
        }


class FieldJournal:
    """
    Diario de campo: loguea todos los pares request→response.
    Patrón de zhaoxuya520/reverse-skill: field-journal evidence tracking.
    """

    def __init__(self, session_id: Optional[str] = None,
                 save_path: Optional[Path] = None):
        self.session_id = session_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.entries: list[JournalEntry] = []
        self.save_path = save_path

    def log(self, cmd: str, raw_response: str,
            parsed: Optional[dict] = None,
            protocol_hint: str = "",
            tags: Optional[list[str]] = None) -> JournalEntry:
        entry = JournalEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=self.session_id,
            cmd=cmd,
            raw_response=raw_response,
            parsed=parsed or {},
            protocol_hint=protocol_hint,
            tags=tags or [],
        )
        self.entries.append(entry)
        return entry

    def save(self, path: Optional[Path] = None) -> Path:
        out = path or self.save_path or Path(f"re_journal_{self.session_id}.json")
        out.write_text(
            json.dumps([e.to_dict() for e in self.entries], indent=2),
            encoding="utf-8"
        )
        return out

    @classmethod
    def load(cls, path: Path) -> "FieldJournal":
        data = json.loads(path.read_text(encoding="utf-8"))
        j = cls()
        for d in data:
            j.entries.append(JournalEntry(
                timestamp=d["ts"], session_id=d["session"],
                cmd=d["cmd"], raw_response=d["resp"],
                parsed=d["parsed"], protocol_hint=d["proto_hint"],
                tags=d["tags"],
            ))
        return j

    def unique_responses(self) -> set[str]:
        return {e.raw_response for e in self.entries}

    def filter_by_tag(self, tag: str) -> list[JournalEntry]:
        return [e for e in self.entries if tag in e.tags]

    def summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "total_entries": len(self.entries),
            "unique_responses": len(self.unique_responses()),
            "protocols_seen": list({e.protocol_hint for e in self.entries if e.protocol_hint}),
            "tags": list({t for e in self.entries for t in e.tags}),
        }


# ── PatternAnalyzer ───────────────────────────────────────────────────────────

@dataclass
class FrameStats:
    """Estadísticas de un frame o conjunto de bytes."""
    byte_freq:   Counter             # frecuencia de cada byte
    entropy:     float               # entropía de Shannon (bits)
    length:      int
    arb_id:      Optional[str]       # CAN arbitration ID si se conoce
    checksum_ok: Optional[bool]

    @property
    def top_bytes(self) -> list[tuple[int, int]]:
        return self.byte_freq.most_common(8)


class PatternAnalyzer:
    """
    Análisis estadístico de frames capturados.
    Basado en el patrón de Scapy-automotive (awesome-RE) + byte-frequency histograms.
    """

    @staticmethod
    def parse_hex_line(line: str) -> list[int]:
        """Convierte '41 0C 0B B8' → [0x41, 0x0C, 0x0B, 0xB8]."""
        return [int(x, 16) for x in re.findall(r"[0-9A-Fa-f]{2}", line)]

    @staticmethod
    def shannon_entropy(data: list[int]) -> float:
        if not data:
            return 0.0
        n = len(data)
        freq = Counter(data)
        return -sum((c / n) * math.log2(c / n) for c in freq.values() if c > 0)

    @classmethod
    def analyze_frame(cls, hex_line: str,
                      arb_id: Optional[str] = None) -> FrameStats:
        data = cls.parse_hex_line(hex_line)
        return FrameStats(
            byte_freq=Counter(data),
            entropy=cls.shannon_entropy(data),
            length=len(data),
            arb_id=arb_id,
            checksum_ok=cls._verify_checksum(data),
        )

    @staticmethod
    def _verify_checksum(data: list[int]) -> Optional[bool]:
        """Prueba checksum XOR y suma módulo 256 (los dos más comunes en ECU)."""
        if len(data) < 3:
            return None
        payload, chk = data[:-1], data[-1]
        xor_chk = 0
        for b in payload:
            xor_chk ^= b
        sum_chk = sum(payload) & 0xFF
        return chk in (xor_chk, sum_chk)

    @classmethod
    def cluster_by_arb_id(cls, entries: list[JournalEntry]) -> dict[str, list[str]]:
        """Agrupa respuestas por CAN arbitration ID (si está en el prefijo)."""
        clusters: dict[str, list[str]] = defaultdict(list)
        for e in entries:
            arb = e.parsed.get("arb_id", "UNKNOWN")
            clusters[arb].append(e.raw_response)
        return dict(clusters)

    @classmethod
    def byte_histogram(cls, hex_lines: list[str]) -> Counter:
        """Histograma global de todos los bytes en todas las líneas."""
        counter: Counter = Counter()
        for line in hex_lines:
            counter.update(cls.parse_hex_line(line))
        return counter

    @classmethod
    def detect_repeating_pattern(cls, data: list[int],
                                  min_period: int = 2,
                                  max_period: int = 8) -> Optional[int]:
        """Detecta si hay un patrón repetitivo en los bytes (útil para identificar padding)."""
        for period in range(min_period, max_period + 1):
            if len(data) < period * 2:
                continue
            pattern = data[:period]
            matches = all(data[i % period] == pattern[i % period]
                          for i in range(period, min(len(data), period * 4)))
            if matches:
                return period
        return None

    @classmethod
    def rank_responses(cls, hex_lines: list[str]) -> list[tuple[float, str]]:
        """Ordena respuestas por entropía descendente (mayor entropía = más datos reales)."""
        scored = [
            (cls.shannon_entropy(cls.parse_hex_line(line)), line)
            for line in hex_lines
        ]
        return sorted(scored, key=lambda x: x[0], reverse=True)


# ── ProtocolGuesser ───────────────────────────────────────────────────────────

@dataclass
class ProtocolGuess:
    protocol:    str
    confidence:  float      # 0.0 – 1.0
    evidence:    list[str]  # qué patrones matchearon
    recommended_init: list[str]  # comandos AT recomendados para este protocolo


class ProtocolGuesser:
    """
    Vota protocolo basándose en patrones estadísticos de las respuestas capturadas.
    Combina firma-matching (awesome-RE) con el routing pattern de reverse-skill.
    """

    _PROTOCOL_INIT: dict[str, list[str]] = {
        "UDS":      ["AT SP 6", "AT AL", "AT H1", "AT D1"],
        "KWP2000":  ["AT SP 5", "AT AL", "AT H1"],
        "OBD2_CAN": ["AT SP 6", "AT AL", "AT H0"],
        "ISO9141":  ["AT SP 3", "AT AL", "AT H1"],
        "EOBD":     ["AT SP 4", "AT AL"],
    }

    @classmethod
    def guess(cls, responses: list[str]) -> list[ProtocolGuess]:
        scores: dict[str, list[str]] = defaultdict(list)
        resp_upper = [r.upper().replace(" ", "") for r in responses]

        for proto, sigs in _PROTOCOL_SIGNATURES.items():
            for sig in sigs:
                sig_compact = sig.upper().replace(" ", "")
                for r in resp_upper:
                    if sig_compact in r:
                        scores[proto].append(f"found '{sig}' in response")

        if not scores:
            return [ProtocolGuess("UNKNOWN", 0.0, ["no signatures matched"],
                                  ["AT SP 0"])]

        total_hits = sum(len(v) for v in scores.values())
        results = []
        for proto, evidence in sorted(scores.items(),
                                       key=lambda x: len(x[1]), reverse=True):
            confidence = min(1.0, len(evidence) / max(total_hits, 1) * 2)
            results.append(ProtocolGuess(
                protocol=proto,
                confidence=round(confidence, 3),
                evidence=evidence,
                recommended_init=cls._PROTOCOL_INIT.get(proto, ["AT SP 0"]),
            ))
        return results

    @classmethod
    def best_guess(cls, responses: list[str]) -> ProtocolGuess:
        guesses = cls.guess(responses)
        return guesses[0] if guesses else ProtocolGuess("UNKNOWN", 0.0, [], [])


# ── PIDFuzzer ────────────────────────────────────────────────────────────────

@dataclass
class FuzzResult:
    """Resultado de un intento de fuzzing."""
    service:   int
    pid_or_did: int
    request:   str
    response:  str
    responded: bool          # ¿ECU contestó con datos reales (no NO DATA)?
    positive:  bool          # ¿Respuesta positiva (no 7F)?
    raw_bytes: list[int] = field(default_factory=list)


class PIDFuzzer:
    """
    Fuzzer de rangos PID/DID.
    Grammar: OBD service 01-0A con PID 0x00-0xFF, o UDS 0x22 con DID 0x0000-0xFFFF.
    Patrón de wtsxDev/reverse-engineering: Peach Fuzzer grammar model.
    """

    _NEGATIVE_RESPONSES = {"NO DATA", "ERROR", "STOPPED", "?", "BUS INIT",
                           "UNABLE TO CONNECT", "CAN ERROR"}

    def __init__(self, send_fn: Callable[[str], str],
                 delay_s: float = 0.15,
                 journal: Optional[FieldJournal] = None):
        """
        send_fn: función que toma una cadena de comando y retorna la respuesta cruda.
        delay_s: pausa entre comandos (evitar flooding la ECU).
        """
        self.send = send_fn
        self.delay = delay_s
        self.journal = journal or FieldJournal()
        self.results: list[FuzzResult] = []

    def _is_negative(self, response: str) -> bool:
        up = response.upper()
        return any(neg in up for neg in self._NEGATIVE_RESPONSES)

    def _is_7f(self, response: str) -> bool:
        return response.upper().replace(" ", "").startswith("7F")

    def _send_and_log(self, cmd: str, tag: str,
                      extra_tags: Optional[list[str]] = None) -> str:
        raw = self.send(cmd)
        self.journal.log(cmd, raw, tags=[tag] + (extra_tags or []))
        time.sleep(self.delay)
        return raw

    def fuzz_obd_service(self, service: int = 0x01,
                          pid_start: int = 0x00,
                          pid_end: int = 0xFF,
                          callback: Optional[Callable[[FuzzResult], None]] = None
                          ) -> list[FuzzResult]:
        """Barre PIDs de un servicio OBD (Mode 01..0A) en el rango dado."""
        results = []
        for pid in range(pid_start, pid_end + 1):
            cmd = f"{service:02X} {pid:02X}"
            raw = self._send_and_log(cmd, "OBD_FUZZ",
                                     [f"svc_{service:02X}", f"pid_{pid:02X}"])
            responded = not self._is_negative(raw)
            positive  = responded and not self._is_7f(raw)
            raw_bytes  = PatternAnalyzer.parse_hex_line(raw) if responded else []
            r = FuzzResult(
                service=service,
                pid_or_did=pid,
                request=cmd,
                response=raw,
                responded=responded,
                positive=positive,
                raw_bytes=raw_bytes,
            )
            results.append(r)
            self.results.append(r)
            if callback:
                callback(r)
        return results

    def fuzz_uds_read_did(self, did_start: int = 0xF100,
                           did_end: int = 0xF1FF,
                           callback: Optional[Callable[[FuzzResult], None]] = None
                           ) -> list[FuzzResult]:
        """Barre DIDs UDS (service 0x22 ReadDataByIdentifier)."""
        results = []
        for did in range(did_start, did_end + 1):
            hi = (did >> 8) & 0xFF
            lo = did & 0xFF
            cmd = f"22 {hi:02X} {lo:02X}"
            raw = self._send_and_log(cmd, "UDS_FUZZ",
                                     [f"did_{did:04X}"])
            responded = not self._is_negative(raw)
            positive  = responded and not self._is_7f(raw)
            raw_bytes  = PatternAnalyzer.parse_hex_line(raw) if responded else []
            r = FuzzResult(
                service=0x22,
                pid_or_did=did,
                request=cmd,
                response=raw,
                responded=responded,
                positive=positive,
                raw_bytes=raw_bytes,
            )
            results.append(r)
            self.results.append(r)
            if callback:
                callback(r)
        return results

    def fuzz_uds_standard_dids(self,
                                callback: Optional[Callable[[FuzzResult], None]] = None
                                ) -> list[FuzzResult]:
        """Barre los rangos DID UDS más frecuentes."""
        all_results = []
        for start, end, _label in _UDS_DID_RANGES:
            all_results.extend(
                self.fuzz_uds_read_did(start, end, callback=callback)
            )
        return all_results

    def positive_hits(self) -> list[FuzzResult]:
        return [r for r in self.results if r.positive]

    def export_catalog(self) -> list[dict]:
        """Exporta PIDs/DIDs que respondieron positivamente."""
        return [
            {
                "service": f"0x{r.service:02X}",
                "pid_did": f"0x{r.pid_or_did:04X}" if r.service == 0x22
                           else f"0x{r.pid_or_did:02X}",
                "request": r.request,
                "response": r.response,
                "bytes": r.raw_bytes,
                "entropy": PatternAnalyzer.shannon_entropy(r.raw_bytes),
            }
            for r in self.positive_hits()
        ]


# ── UnknownECUProfiler ────────────────────────────────────────────────────────

@dataclass
class ECUProfile:
    """Perfil de una ECU desconocida tras el sondeo."""
    session_id:        str
    probed_at:         str
    protocol_guesses:  list[ProtocolGuess]
    best_protocol:     str
    vin:               Optional[str]
    ecu_addresses:     list[str]
    supported_services: list[int]
    raw_probe_data:    dict[str, str]   # cmd → respuesta
    journal_path:      Optional[str]
    notes:             list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "probed_at": self.probed_at,
            "best_protocol": self.best_protocol,
            "vin": self.vin,
            "ecu_addresses": self.ecu_addresses,
            "supported_services": [f"0x{s:02X}" for s in self.supported_services],
            "protocol_guesses": [
                {"protocol": g.protocol, "confidence": g.confidence,
                 "evidence": g.evidence}
                for g in self.protocol_guesses
            ],
            "raw_probe_data": self.raw_probe_data,
            "journal_path": self.journal_path,
            "notes": self.notes,
        }


class UnknownECUProfiler:
    """
    Sondea una ECU desconocida usando el agent-loop de morluto/rea:
    observe → form hypothesis → re-query → refine.
    """

    # Patrones de VIN en respuestas ELM327
    _VIN_RE = re.compile(
        r"(?:[0-9A-HJ-NPR-Z]{17}|"          # VIN estándar
        r"(?:[0-9A-F]{2} ){16}[0-9A-F]{2})"  # o 17 bytes hex
    )

    def __init__(self, send_fn: Callable[[str], str],
                 delay_s: float = 0.2):
        self.send    = send_fn
        self.delay   = delay_s
        self.journal = FieldJournal()
        self._probe_data: dict[str, str] = {}

    def _send(self, cmd: str, tag: str = "PROBE") -> str:
        raw = self.send(cmd)
        self._probe_data[cmd] = raw
        self.journal.log(cmd, raw, tags=[tag])
        time.sleep(self.delay)
        return raw

    # ── Agent-loop step 1: observe ─────────────────────────────────────────
    def _observe(self) -> dict[str, str]:
        """Envía probes de bajo riesgo y recoge todas las respuestas."""
        results = {}
        for name, cmd in _PROBE_COMMANDS:
            if "RESET" in name:        # Skip reset en producción
                continue
            if name.startswith("ISO") or name.startswith("CAN"):
                # Comandos AT: enviar directamente
                raw = self._send(cmd, tag="AT_PROBE")
            else:
                raw = self._send(cmd, tag="OBD_PROBE")
            results[name] = raw
        return results

    # ── Agent-loop step 2: form hypothesis ───────────────────────────────
    def _hypothesize(self, observations: dict[str, str]) -> list[ProtocolGuess]:
        all_responses = list(observations.values())
        return ProtocolGuesser.guess(all_responses)

    # ── Agent-loop step 3: re-query (refine with targeted probes) ────────
    def _refine(self, best_proto: str) -> dict[str, str]:
        refined = {}
        if best_proto == "UDS":
            for did_hex in ["F190", "F18C", "F187", "F1A0"]:
                hi = int(did_hex[:2], 16)
                lo = int(did_hex[2:], 16)
                cmd = f"22 {hi:02X} {lo:02X}"
                refined[f"UDS_DID_{did_hex}"] = self._send(cmd, "REFINE_UDS")
        elif best_proto == "OBD2_CAN":
            for pid_hex in ["04", "05", "0C", "0D", "10"]:
                cmd = f"01 {pid_hex}"
                refined[f"OBD_PID_0x{pid_hex}"] = self._send(cmd, "REFINE_OBD")
        elif best_proto == "KWP2000":
            refined["KWP_ECU_ID"] = self._send("1A 86", "REFINE_KWP")
        return refined

    def _extract_vin(self, observations: dict[str, str]) -> Optional[str]:
        for raw in observations.values():
            clean = re.sub(r"\s+", "", raw.upper())
            # Intenta decodificar bytes a ASCII
            try:
                hexbytes = [int(clean[i:i+2], 16)
                            for i in range(0, len(clean), 2)]
                ascii_str = "".join(
                    chr(b) for b in hexbytes
                    if 0x20 <= b <= 0x7E
                )
                m = self._VIN_RE.search(ascii_str)
                if m:
                    return m.group(0)
            except ValueError:
                pass
            m = self._VIN_RE.search(raw.upper())
            if m:
                return m.group(0)
        return None

    def _detect_ecu_addresses(self, observations: dict[str, str]) -> list[str]:
        known = {
            "7E8": "Engine", "7E9": "Transmission", "7EA": "EVAP",
            "7EB": "A/C", "7EC": "ABS", "7ED": "BCM",
        }
        found = []
        for raw in observations.values():
            for addr in known:
                if addr in raw.upper():
                    found.append(addr)
        return list(set(found))

    def _detect_supported_services(self, observations: dict[str, str]) -> list[int]:
        services = set()
        for name in observations:
            if "OBD_MODE01" in name:
                services.add(0x01)
            elif "UDS_DIAG" in name or "UDS_READ" in name:
                services.add(0x10)
                services.add(0x22)
            elif "KWP" in name:
                services.add(0x10)
        return sorted(services)

    def profile(self,
                save_journal: Optional[Path] = None) -> ECUProfile:
        """
        Ejecuta el agent-loop completo y retorna un ECUProfile.
        """
        # Step 1: Observe
        observations = self._observe()

        # Step 2: Hypothesize
        guesses = self._hypothesize(observations)
        best = guesses[0].protocol if guesses else "UNKNOWN"

        # Step 3: Refine
        refined = self._refine(best)
        observations.update(refined)

        vin = self._extract_vin(observations)
        ecu_addrs = self._detect_ecu_addresses(observations)
        services = self._detect_supported_services(observations)

        journal_path = None
        if save_journal:
            journal_path = str(self.journal.save(save_journal))

        return ECUProfile(
            session_id=self.journal.session_id,
            probed_at=datetime.now(timezone.utc).isoformat(),
            protocol_guesses=guesses,
            best_protocol=best,
            vin=vin,
            ecu_addresses=ecu_addrs,
            supported_services=services,
            raw_probe_data=dict(self._probe_data),
            journal_path=journal_path,
            notes=[
                f"Total probes sent: {len(self._probe_data)}",
                f"Journal entries: {len(self.journal.entries)}",
            ],
        )


# ── ReverseEngineerSession ────────────────────────────────────────────────────

@dataclass
class RESessionResult:
    """Resultado completo de una sesión de ingeniería inversa."""
    profile:          ECUProfile
    fuzz_catalog:     list[dict]   # PIDs/DIDs respondidos positivamente
    pattern_stats:    dict         # histograma, entropía promedio
    journal_summary:  dict
    duration_s:       float


class ReverseEngineerSession:
    """
    Orquestador de ingeniería inversa completo.

    Secuencia:
      1. Profile: sonda la ECU para identificar protocolo
      2. Fuzz: barre rangos de PIDs/DIDs según el protocolo detectado
      3. Analyze: aplica PatternAnalyzer a todas las respuestas
      4. Report: devuelve RESessionResult con todo

    Uso:
      from scaner_soler.comm.elm327 import ELM327Protocol
      from scaner_soler.comm.reverse_engineer import ReverseEngineerSession

      proto = ELM327Protocol(port="COM3", baudrate=38400)
      session = ReverseEngineerSession(send_fn=proto.send_command)
      result = session.run(fuzz=True, fuzz_mode="obd")
      print(result.profile.best_protocol)
      print(len(result.fuzz_catalog), "PIDs respondidos")
    """

    def __init__(self,
                 send_fn: Callable[[str], str],
                 probe_delay_s: float = 0.2,
                 fuzz_delay_s:  float = 0.15,
                 on_progress: Optional[Callable[[str, float], None]] = None):
        """
        send_fn:     función que envía un comando y retorna la respuesta raw.
        on_progress: callback(mensaje, porcentaje) para reportar progreso.
        """
        self.send        = send_fn
        self.probe_delay = probe_delay_s
        self.fuzz_delay  = fuzz_delay_s
        self.progress    = on_progress or (lambda m, p: None)
        self._journal    = FieldJournal()

    def run(self,
            fuzz: bool = True,
            fuzz_mode: str = "obd",    # "obd" | "uds" | "both" | "smart"
            save_journal: Optional[Path] = None,
            save_catalog: Optional[Path] = None
            ) -> RESessionResult:
        t0 = time.time()

        # 1. Profile
        self.progress("Sondeando ECU...", 0.05)
        profiler = UnknownECUProfiler(self.send, delay_s=self.probe_delay)
        profiler.journal = self._journal
        profile = profiler.profile(save_journal=save_journal)
        self.progress(f"Protocolo detectado: {profile.best_protocol}", 0.25)

        # 2. Fuzz
        fuzz_catalog: list[dict] = []
        if fuzz:
            fuzzer = PIDFuzzer(self.send, delay_s=self.fuzz_delay,
                               journal=self._journal)

            # "smart": elige el modo según el protocolo detectado
            if fuzz_mode == "smart":
                fuzz_mode = "uds" if profile.best_protocol == "UDS" else "obd"

            if fuzz_mode in ("obd", "both"):
                self.progress("Fuzzing OBD services 01/02/09...", 0.35)
                for svc in [0x01, 0x02, 0x09]:
                    fuzzer.fuzz_obd_service(
                        service=svc, pid_start=0x00, pid_end=0xFF,
                        callback=lambda r: (
                            self.progress(
                                f"OBD {r.request} -> {'OK' if r.positive else 'NACK'}",
                                0.4
                            ) if r.positive else None
                        )
                    )

            if fuzz_mode in ("uds", "both"):
                self.progress("Fuzzing UDS DIDs estandar...", 0.55)
                fuzzer.fuzz_uds_standard_dids(
                    callback=lambda r: (
                        self.progress(
                            f"DID {r.pid_or_did:04X} -> {'OK' if r.positive else 'NACK'}",
                            0.65
                        ) if r.positive else None
                    )
                )

            fuzz_catalog = fuzzer.export_catalog()
            if save_catalog:
                save_catalog.write_text(
                    json.dumps(fuzz_catalog, indent=2),
                    encoding="utf-8"
                )

        # 3. Analyze
        self.progress("Analizando patrones...", 0.85)
        all_responses = [e.raw_response for e in self._journal.entries
                         if e.raw_response]
        histogram = PatternAnalyzer.byte_histogram(all_responses)
        ranked    = PatternAnalyzer.rank_responses(all_responses)
        avg_entropy = (
            sum(h for h, _ in ranked) / len(ranked) if ranked else 0.0
        )
        pattern_stats = {
            "total_frames":  len(all_responses),
            "unique_frames": len(set(all_responses)),
            "avg_entropy":   round(avg_entropy, 3),
            "top_bytes":     dict(histogram.most_common(16)),
            "highest_entropy_frames": [line for _, line in ranked[:5]],
        }

        self.progress("Sesión completada.", 1.0)

        return RESessionResult(
            profile=profile,
            fuzz_catalog=fuzz_catalog,
            pattern_stats=pattern_stats,
            journal_summary=self._journal.summary(),
            duration_s=round(time.time() - t0, 2),
        )

    def quick_profile(self) -> ECUProfile:
        """Sólo perfila sin fuzzing (más rápido)."""
        result = self.run(fuzz=False)
        return result.profile


# ── Modo demo (sin hardware) ─────────────────────────────────────────────────

def _demo_send_fn(cmd: str) -> str:
    """Simulador de respuestas para pruebas sin ELM327 físico."""
    cmd_upper = cmd.upper().strip()

    # Respuestas UDS
    if cmd_upper.startswith("10"):
        return "50 01 00 19 01 F4"
    if cmd_upper.startswith("22 F1 90"):
        return "62 F1 90 31 47 31 4A 43 35 34 34 34 52 37 32 35 32 36 38 35 36"
    if cmd_upper.startswith("22 F1 8C"):
        return "62 F1 8C 41 42 43 31 32 33 34 35"
    if cmd_upper.startswith("22"):
        # Respuesta negativa aleatoria para la mayoría
        return random.choice(["7F 22 31", "NO DATA", "NO DATA", "7F 22 11"])
    # Respuestas OBD2
    if cmd_upper.startswith("01 00"):
        return "41 00 BE 3F A8 13"
    if cmd_upper.startswith("01 0C"):
        return "41 0C 0B B8"   # RPM=750
    if cmd_upper.startswith("01 0D"):
        return "41 0D 00"      # Speed=0
    if cmd_upper.startswith("01 05"):
        return "41 05 6E"      # Coolant=70°C
    if cmd_upper.startswith("09 02"):
        return "49 02 01 31 47 31 4A 43 35 34 34 34 52 37 32 35 32 36 38 35 36"
    if cmd_upper.startswith("01"):
        return random.choice(["NO DATA", "7F 01 31", "NO DATA"])
    if cmd_upper.startswith("AT"):
        return "OK"
    return "NO DATA"


def run_demo(fuzz_mode: str = "obd") -> RESessionResult:
    """Ejecuta una sesión de demostración completa sin hardware."""
    session = ReverseEngineerSession(
        send_fn=_demo_send_fn,
        on_progress=lambda m, p: print(f"  [{p*100:5.1f}%] {m}", flush=True)
    )
    return session.run(fuzz=True, fuzz_mode=fuzz_mode)


if __name__ == "__main__":
    print("=== Scaner Soler -- Modulo Ingenieria Inversa (DEMO) ===\n")
    result = run_demo(fuzz_mode="obd")
    print(f"\nProtocolo detectado : {result.profile.best_protocol}")
    print(f"VIN                 : {result.profile.vin or 'no detectado'}")
    print(f"ECUs encontradas    : {result.profile.ecu_addresses}")
    print(f"PIDs respondidos    : {len(result.fuzz_catalog)}")
    print(f"Entropía promedio   : {result.pattern_stats['avg_entropy']} bits")
    print(f"Duración            : {result.duration_s}s")
    print(f"\nResumen del diario:\n{json.dumps(result.journal_summary, indent=2)}")
