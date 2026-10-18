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


# ── CANBusScanner ─────────────────────────────────────────────────────────────

@dataclass
class CANScanResult:
    """Resultado del escaneo de un ID CAN específico."""
    can_id: int           # Arbitration ID
    frame_count: int      # Frames capturados
    dlc_common: int       # DLC más frecuente
    byte_pattern: str     # "static" | "dynamic" | "counter" | "mixed"
    entropy: float
    sample_frames: list   # Hasta 5 frames hex de muestra
    first_seen: float
    last_seen: float


class CANBusScanner:
    """
    Escanea CAN bus para encontrar IDs activos, patrones de tráfico y señales candidatas.
    En hardware real usa python-can. En demo usa tráfico simulado.
    """

    def __init__(self, send_fn: Callable[[str], str],
                 journal: Optional[FieldJournal] = None):
        self._send = send_fn
        self.journal = journal or FieldJournal()
        self._results: list[CANScanResult] = []

    def scan_traffic(self, duration_s: float = 10.0,
                     callback: Optional[Callable[[str], None]] = None
                     ) -> list[CANScanResult]:
        """
        Escucha tráfico CAN durante duration_s segundos.
        Demo: simula 20-40 IDs activos con patrones realistas.
          - 0x7E8/0x7E9: respuestas ECU OBD, patrón dynamic
          - 0x100-0x120: chassis (velocidad, RPM, temp), patrón counter/dynamic
          - 0x200-0x210: carrocería (puertas, luces), patrón static
          - 0x300-0x310: ABS/ESP, patrón dynamic
          - 0x400-0x405: otros módulos, patrón mixed
        """
        rng = random.Random(42)
        t0 = time.time()

        # (id_start, id_end, count, dlc, pattern)
        id_groups = [
            (0x7E8, 0x7E9, 2, 8, "dynamic"),
            (0x100, 0x120, 8, 8, "counter"),
            (0x200, 0x210, 6, 3, "static"),
            (0x300, 0x310, 6, 8, "dynamic"),
            (0x400, 0x405, 3, 4, "mixed"),
        ]

        raw_ids: dict[int, list[str]] = {}
        raw_ts: dict[int, list[float]] = {}

        for id_start, id_end, count, dlc, pattern in id_groups:
            pool = list(range(id_start, id_end + 1))
            selected = rng.sample(pool, min(count, len(pool)))
            for can_id in selected:
                frames: list[str] = []
                timestamps: list[float] = []
                n_frames = rng.randint(30, 80)
                counter_byte = rng.randint(0, 15)
                base_bytes = [rng.randint(0, 255) for _ in range(dlc)]
                for _ in range(n_frames):
                    if pattern == "static":
                        fb = base_bytes[:]
                    elif pattern == "counter":
                        fb = [rng.randint(0, 255) for _ in range(dlc)]
                        fb[0] = counter_byte & 0xFF
                        counter_byte += 1
                    elif pattern == "dynamic":
                        fb = [rng.randint(0, 255) for _ in range(dlc)]
                    else:  # mixed
                        fb = [rng.randint(0, 255) for _ in range(dlc)]
                        fb[-1] = counter_byte & 0xFF
                        counter_byte += 1
                    frames.append(" ".join(f"{b:02X}" for b in fb))
                    timestamps.append(t0 + rng.uniform(0, duration_s))
                raw_ids[can_id] = frames
                raw_ts[can_id] = sorted(timestamps)

        results: list[CANScanResult] = []
        for can_id, frames in raw_ids.items():
            # Calcular entropía sobre los primeros 10 frames concatenados
            sample_hex = " ".join(f[:8] for f in frames[:10])
            entropy = PatternAnalyzer.shannon_entropy(
                PatternAnalyzer.parse_hex_line(sample_hex)
            )
            classified = self.classify_pattern(frames)
            ts_list = raw_ts[can_id]
            r = CANScanResult(
                can_id=can_id,
                frame_count=len(frames),
                dlc_common=len(PatternAnalyzer.parse_hex_line(frames[0])),
                byte_pattern=classified,
                entropy=round(entropy, 3),
                sample_frames=frames[:5],
                first_seen=ts_list[0],
                last_seen=ts_list[-1],
            )
            results.append(r)
            if callback:
                callback(f"CAN 0x{can_id:03X}: {classified}, {len(frames)} frames, "
                         f"entropy={entropy:.2f}")
            self.journal.log(
                f"CAN_SCAN 0x{can_id:03X}",
                frames[0] if frames else "",
                parsed={"can_id": f"0x{can_id:03X}", "pattern": classified},
                tags=["CAN_SCAN"],
            )

        self._results = sorted(results, key=lambda x: x.can_id)
        return self._results

    def probe_id(self, can_id: int) -> Optional[CANScanResult]:
        """Envía un frame de diagnóstico al ID y espera respuesta."""
        cmd = f"TX {can_id:03X} 8 02 01 00 00 00 00 00 00"
        raw = self._send(cmd)
        raw_up = raw.upper()
        if "NO DATA" in raw_up or "ERROR" in raw_up:
            return None
        bytes_ = PatternAnalyzer.parse_hex_line(raw)
        entropy = PatternAnalyzer.shannon_entropy(bytes_)
        return CANScanResult(
            can_id=can_id,
            frame_count=1,
            dlc_common=len(bytes_),
            byte_pattern=self.classify_pattern([raw]),
            entropy=round(entropy, 3),
            sample_frames=[raw],
            first_seen=time.time(),
            last_seen=time.time(),
        )

    @staticmethod
    def classify_pattern(frames: list[str]) -> str:
        """
        Clasifica el patrón de bytes de una lista de frames hex:
        - "static":  todos los bytes son iguales entre frames
        - "counter": un byte incrementa linealmente (+1 por frame)
        - "dynamic": alta entropía (datos reales cambiantes)
        - "mixed":   combinación
        """
        if len(frames) < 2:
            return "dynamic"
        parsed = [PatternAnalyzer.parse_hex_line(f) for f in frames]
        parsed = [p for p in parsed if p]
        if not parsed:
            return "dynamic"
        first = parsed[0]
        n_bytes = len(first)

        # static: todos idénticos
        if all(f == first for f in parsed):
            return "static"

        # counter: algún byte incrementa +1 consistentemente
        for byte_idx in range(min(n_bytes, 4)):
            vals = [f[byte_idx] for f in parsed if len(f) > byte_idx]
            if len(vals) < 3:
                continue
            diffs = [(vals[i + 1] - vals[i]) & 0xFF for i in range(len(vals) - 1)]
            if len(set(diffs)) == 1 and diffs[0] == 1:
                return "counter"

        # dynamic vs mixed por entropía
        all_bytes = [b for f in parsed for b in f]
        entropy = PatternAnalyzer.shannon_entropy(all_bytes)
        return "dynamic" if entropy > 5.0 else "mixed"


# ── UDSServiceMap ─────────────────────────────────────────────────────────────

_UDS_SERVICES: dict[int, str] = {
    0x10: "DiagnosticSessionControl",
    0x11: "ECUReset",
    0x14: "ClearDiagnosticInformation",
    0x19: "ReadDTCInformation",
    0x22: "ReadDataByIdentifier",
    0x23: "ReadMemoryByAddress",
    0x24: "ReadScalingDataByIdentifier",
    0x27: "SecurityAccess",
    0x28: "CommunicationControl",
    0x29: "Authentication",
    0x2A: "ReadDataByPeriodicIdentifier",
    0x2C: "DynamicallyDefineDataIdentifier",
    0x2E: "WriteDataByIdentifier",
    0x2F: "InputOutputControlByIdentifier",
    0x31: "RoutineControl",
    0x34: "RequestDownload",
    0x35: "RequestUpload",
    0x36: "TransferData",
    0x37: "RequestTransferExit",
    0x3D: "WriteMemoryByAddress",
    0x3E: "TesterPresent",
    0x83: "AccessTimingParameters",
    0x84: "SecuredDataTransmission",
    0x85: "ControlDTCSetting",
    0x86: "ResponseOnEvent",
    0x87: "LinkControl",
}

_NRC_NAMES: dict[int, str] = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLength",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x26: "failurePreventsExecution",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceededNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x70: "uploadDownloadNotAccepted",
    0x71: "transferDataSuspended",
    0x72: "generalProgrammingFailure",
    0x78: "requestCorrectlyReceivedResponsePending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}


@dataclass
class UDSServiceResult:
    """Resultado del sondeo de un servicio UDS."""
    service_id: int
    service_name: str
    supported: bool
    response_code: Optional[str]   # Hex del primer byte de respuesta positiva
    nrc: Optional[str]             # Negative Response Code si aplica
    sub_functions: list            # Sub-funciones que respondieron OK
    risk_level: str                # "safe" | "caution" | "danger"


class UDSServiceMap:
    """
    Escanea sistemáticamente todos los servicios UDS para construir el mapa
    de capacidades de la ECU (ISO 14229-1).
    """

    _RISK: dict[int, str] = {
        0x10: "safe",    0x11: "caution",  0x14: "caution",  0x19: "safe",
        0x22: "safe",    0x23: "safe",     0x24: "safe",     0x27: "caution",
        0x28: "caution", 0x29: "caution",  0x2A: "safe",     0x2C: "caution",
        0x2E: "caution", 0x2F: "danger",   0x31: "caution",  0x34: "danger",
        0x35: "danger",  0x36: "danger",   0x37: "danger",   0x3D: "danger",
        0x3E: "safe",    0x83: "safe",     0x84: "caution",  0x85: "caution",
        0x86: "caution", 0x87: "caution",
    }
    _DANGER_SERVICES: set = {0x34, 0x35, 0x36, 0x2F, 0x3D}

    # Demo: servicios que "soporta" la ECU simulada
    _DEMO_SUPPORTED = {0x10, 0x19, 0x22, 0x3E}
    # Demo: servicios que responden con NRC específico (no 0x11)
    _DEMO_NRC_MAP = {0x27: 0x37}  # SecurityAccess → requiredTimeDelayNotExpired

    def __init__(self, send_fn: Callable[[str], str],
                 journal: Optional[FieldJournal] = None):
        self._send = send_fn
        self.journal = journal or FieldJournal()
        self._results: list[UDSServiceResult] = []

    def scan_service(self, service_id: int) -> UDSServiceResult:
        """Prueba un servicio UDS con sub-función 0x01 básico y registra la respuesta."""
        name = _UDS_SERVICES.get(service_id, f"Unknown_0x{service_id:02X}")
        risk = self._RISK.get(service_id, "caution")
        cmd = f"{service_id:02X} 01"
        raw = self._send(cmd)
        self.journal.log(cmd, raw,
                         tags=["UDS_MAP", f"svc_{service_id:02X}"],
                         protocol_hint="UDS")

        raw_up = raw.upper().replace(" ", "")
        supported = False
        response_code: Optional[str] = None
        nrc: Optional[str] = None
        sub_functions: list[int] = []

        if any(x in raw_up for x in ("NODATA", "ERROR", "STOPPED", "?")):
            pass  # no responde
        elif raw_up.startswith("7F"):
            try:
                bytes_ = PatternAnalyzer.parse_hex_line(raw)
                nrc_byte = bytes_[2] if len(bytes_) >= 3 else 0x11
                nrc_name = _NRC_NAMES.get(nrc_byte, "unknown")
                nrc = f"0x{nrc_byte:02X} ({nrc_name})"
                response_code = "7F"
                # NRC != serviceNotSupported → ECU conoce el servicio
                if nrc_byte != 0x11:
                    supported = True
            except (ValueError, IndexError):
                pass
        else:
            positive_sid = service_id + 0x40
            if raw_up.startswith(f"{positive_sid:02X}"):
                supported = True
                response_code = f"{positive_sid:02X}"
                try:
                    bytes_ = PatternAnalyzer.parse_hex_line(raw)
                    if len(bytes_) > 1:
                        sub_functions.append(bytes_[1])
                except ValueError:
                    pass

        return UDSServiceResult(
            service_id=service_id,
            service_name=name,
            supported=supported,
            response_code=response_code,
            nrc=nrc,
            sub_functions=sub_functions,
            risk_level=risk,
        )

    def scan_all(self, skip_danger: bool = True,
                 callback: Optional[Callable[[str], None]] = None
                 ) -> list[UDSServiceResult]:
        """
        Escanea todos los servicios UDS definidos en _UDS_SERVICES.
        skip_danger=True omite 0x34/0x35/0x36/0x2F/0x3D para seguridad.
        Demo: 0x10/0x19/0x22/0x3E responden positivo; 0x27 NRC 0x37;
              el resto NRC 0x11 (serviceNotSupported).
        """
        results: list[UDSServiceResult] = []
        for svc_id in sorted(_UDS_SERVICES.keys()):
            if skip_danger and svc_id in self._DANGER_SERVICES:
                if callback:
                    callback(f"SKIP 0x{svc_id:02X} {_UDS_SERVICES[svc_id]} [danger]")
                continue
            r = self.scan_service(svc_id)
            results.append(r)
            self._results.append(r)
            if callback:
                status = ("OK" if r.supported
                          else f"NACK {r.nrc}" if r.nrc
                          else "NO_RESP")
                callback(f"UDS 0x{svc_id:02X} {r.service_name}: {status} [{r.risk_level}]")
        return results

    def scan_rdbi_range(self, did_start: int = 0xF100, did_end: int = 0xF1FF,
                        callback: Optional[Callable[[str], None]] = None
                        ) -> dict[int, str]:
        """
        Escanea un rango de DIDs con ReadDataByIdentifier (0x22).
        Retorna dict[did] -> response_hex para los que respondieron positivamente.
        """
        found: dict[int, str] = {}
        for did in range(did_start, did_end + 1):
            hi = (did >> 8) & 0xFF
            lo = did & 0xFF
            cmd = f"22 {hi:02X} {lo:02X}"
            raw = self._send(cmd)
            self.journal.log(cmd, raw,
                             tags=["RDBI_SCAN", f"did_{did:04X}"],
                             protocol_hint="UDS")
            raw_up = raw.upper().replace(" ", "")
            # Respuesta positiva: 62 <hi_hex><lo_hex><data...>
            expected_prefix = f"62{hi:02X}{lo:02X}"
            if raw_up.startswith(expected_prefix):
                found[did] = raw
                if callback:
                    callback(f"DID 0x{did:04X}: {raw}")
        return found

    def to_summary(self) -> str:
        """Resumen legible de los servicios encontrados."""
        supported = [r for r in self._results if r.supported]
        lines = [
            f"=== UDS Service Map "
            f"({len(self._results)} escaneados, {len(supported)} soportados) ===",
        ]
        for r in sorted(self._results, key=lambda x: x.service_id):
            check = "✓" if r.supported else "✗"
            nrc_info = f" NRC={r.nrc}" if r.nrc else ""
            lines.append(
                f"  [{check}] 0x{r.service_id:02X} {r.service_name:<42} "
                f"risk={r.risk_level}{nrc_info}"
            )
        return "\n".join(lines)


# ── SignalChangeMonitor ───────────────────────────────────────────────────────

@dataclass
class SignalDelta:
    """Cambio detectado en una señal asociado a una acción."""
    pid_or_id: str       # "PID:0x0C" o "CAN:0x120:byte3"
    action_label: str    # Qué acción se hizo cuando cambió
    before_value: str
    after_value: str
    change_magnitude: float   # 0.0-1.0


class SignalChangeMonitor:
    """
    Monitorea señales mientras el técnico realiza acciones físicas (acelerar,
    encender AC, etc.) para correlacionar señales con funciones de la ECU.
    """

    _PID_NAMES: dict[str, str] = {
        "0x0C": "RPM",         "0x0D": "Speed_kmh",   "0x04": "Load_pct",
        "0x05": "Coolant_C",   "0x0F": "IntakeAir_C",  "0x11": "Throttle_pct",
        "0x0B": "MAP_kPa",     "0x10": "MAF_gs",       "0x13": "O2_sensors",
    }

    def __init__(self, send_fn: Callable[[str], str],
                 pids_to_watch: Optional[list] = None):
        self._send = send_fn
        self._pids = pids_to_watch or [
            "0x0C", "0x0D", "0x04", "0x05", "0x0F", "0x11"
        ]
        self._baseline: dict[str, str] = {}
        self._snapshots: list[tuple[str, dict[str, str]]] = []  # (label, values)
        self._running = False

    def _read_pid(self, pid_hex: str) -> str:
        pid_int = int(pid_hex, 16)
        cmd = f"01 {pid_int:02X}"
        return self._send(cmd)

    def capture_baseline(self) -> dict[str, str]:
        """Captura valores actuales como línea base."""
        self._baseline = {}
        for pid in self._pids:
            self._baseline[pid] = self._read_pid(pid)
        return dict(self._baseline)

    def mark_action(self, label: str) -> dict[str, str]:
        """Captura un snapshot de todos los PIDs y lo asocia a la acción label."""
        snapshot: dict[str, str] = {}
        for pid in self._pids:
            snapshot[pid] = self._read_pid(pid)
        self._snapshots.append((label, snapshot))
        return dict(snapshot)

    def _parse_numeric(self, raw: str) -> Optional[float]:
        """Extrae un valor numérico del byte_A de la respuesta OBD."""
        try:
            bytes_ = PatternAnalyzer.parse_hex_line(raw)
            if len(bytes_) >= 3:
                return float(bytes_[2])
            if len(bytes_) == 2:
                return float(bytes_[1])
        except (ValueError, IndexError):
            pass
        return None

    def analyze_deltas(self) -> list[SignalDelta]:
        """Compara snapshots contra baseline y devuelve señales que cambiaron."""
        if not self._baseline or not self._snapshots:
            return []
        deltas: list[SignalDelta] = []
        for label, snapshot in self._snapshots:
            for pid in self._pids:
                before_raw = self._baseline.get(pid, "NO DATA")
                after_raw = snapshot.get(pid, "NO DATA")
                if before_raw == after_raw:
                    continue
                b_val = self._parse_numeric(before_raw)
                a_val = self._parse_numeric(after_raw)
                if b_val is not None and a_val is not None:
                    magnitude = min(1.0, abs(a_val - b_val) / max(abs(b_val), 1.0))
                else:
                    magnitude = 1.0  # cambio binario completo
                deltas.append(SignalDelta(
                    pid_or_id=f"PID:{pid}",
                    action_label=label,
                    before_value=before_raw,
                    after_value=after_raw,
                    change_magnitude=round(magnitude, 3),
                ))
        return sorted(deltas, key=lambda d: d.change_magnitude, reverse=True)

    def generate_correlation_report(self) -> str:
        """Texto legible: qué señales cambiaron con qué acciones."""
        deltas = self.analyze_deltas()
        if not deltas:
            return "No se detectaron cambios de señal en las acciones registradas."
        lines = ["=== Reporte de Correlación Señal-Acción ===\n"]
        by_action: dict[str, list[SignalDelta]] = defaultdict(list)
        for d in deltas:
            by_action[d.action_label].append(d)
        for action, ds in by_action.items():
            lines.append(f"Acción: {action}")
            for d in ds:
                pid_key = d.pid_or_id.split(":")[-1]
                pid_name = self._PID_NAMES.get(pid_key, d.pid_or_id)
                lines.append(
                    f"  {pid_name}: {d.before_value} -> {d.after_value} "
                    f"(magnitud={d.change_magnitude:.2f})"
                )
            lines.append("")
        return "\n".join(lines)


# ── ECUControlMap ─────────────────────────────────────────────────────────────

_WRITABLE_DID_HINTS: dict[str, str] = {
    "F1A0": "ECU_Calibration", "F190": "VIN",        "F18C": "SerialNumber",
    "F187": "PartNumber",      "F1A1": "SWVersion",   "F1A2": "HWVersion",
    "F1A3": "BootSWVersion",   "F1A4": "HWConfig",    "F19D": "ECU_ProgramDate",
    "F18A": "SystemSupplier",  "F18B": "ManufacDate",
}

_ACTUATOR_KEYWORDS = [
    "output", "control", "actuator", "valve", "relay",
    "pump", "motor", "injector", "solenoid", "enable",
]


@dataclass
class ECUControlMap:
    """
    Mapa completo de control de una ECU desconocida.
    Resultado final del pipeline de ingeniería inversa:
    UnknownECUProfiler → CANBusScanner → UDSServiceMap → ECUControlMap.
    """
    vin: Optional[str]
    protocol: str
    scan_date: str

    # De UnknownECUProfiler
    supported_pids: list        # [{cmd, response}]

    # De CANBusScanner
    active_can_ids: list        # list[CANScanResult]

    # De UDSServiceMap
    uds_services: list          # list[UDSServiceResult]
    readable_dids: dict         # {int → str hex}

    # De SignalChangeMonitor
    signal_correlations: list   # list[SignalDelta]

    # Análisis generado
    write_candidates: list      # [{did, hint, current_value, writable}]
    actuator_candidates: list   # [{id, type, description, confidence, source}]

    @classmethod
    def build(cls,
              profile: ECUProfile,
              can_results: Optional[list] = None,
              service_map: Optional[list] = None,
              rdbi_results: Optional[dict] = None,
              signal_deltas: Optional[list] = None) -> "ECUControlMap":
        """Construye el mapa completo a partir de todos los resultados."""
        supported_pids = [
            {"cmd": cmd, "response": resp}
            for cmd, resp in profile.raw_probe_data.items()
            if resp and "NO DATA" not in resp.upper()
            and "ERROR" not in resp.upper()
        ]
        service_list = service_map or []
        rdbi_map = rdbi_results or {}
        deltas = signal_deltas or []
        can_list = can_results or []

        # Inferir write_candidates
        write_candidates: list[dict] = []
        write_supported = any(
            r.service_id == 0x2E and r.supported for r in service_list
        )
        if write_supported:
            for did, resp in rdbi_map.items():
                hint = _WRITABLE_DID_HINTS.get(f"{did:04X}", "")
                write_candidates.append({
                    "did": f"0x{did:04X}",
                    "hint": hint or "unknown",
                    "current_value": resp,
                    "writable": True,
                })

        instance = cls(
            vin=profile.vin,
            protocol=profile.best_protocol,
            scan_date=datetime.now(timezone.utc).isoformat(),
            supported_pids=supported_pids,
            active_can_ids=can_list,
            uds_services=service_list,
            readable_dids=rdbi_map,
            signal_correlations=deltas,
            write_candidates=write_candidates,
            actuator_candidates=[],
        )
        instance.actuator_candidates = instance._infer_actuators()
        return instance

    def to_json(self, path: Any) -> Path:
        """Exporta el mapa completo a JSON."""
        out = Path(path)
        data: dict[str, Any] = {
            "vin": self.vin,
            "protocol": self.protocol,
            "scan_date": self.scan_date,
            "supported_pids_count": len(self.supported_pids),
            "supported_pids": self.supported_pids,
            "active_can_ids": [
                {
                    "can_id": f"0x{r.can_id:03X}",
                    "frame_count": r.frame_count,
                    "pattern": r.byte_pattern,
                    "entropy": r.entropy,
                    "dlc": r.dlc_common,
                    "sample": r.sample_frames[:2],
                }
                for r in self.active_can_ids
            ],
            "uds_services": [
                {
                    "id": f"0x{r.service_id:02X}",
                    "name": r.service_name,
                    "supported": r.supported,
                    "risk": r.risk_level,
                    "nrc": r.nrc,
                    "sub_functions": r.sub_functions,
                }
                for r in self.uds_services
            ],
            "readable_dids": {f"0x{k:04X}": v for k, v in self.readable_dids.items()},
            "signal_correlations": [
                {
                    "pid": d.pid_or_id,
                    "action": d.action_label,
                    "before": d.before_value,
                    "after": d.after_value,
                    "magnitude": d.change_magnitude,
                }
                for d in self.signal_correlations
            ],
            "write_candidates": self.write_candidates,
            "actuator_candidates": self.actuator_candidates,
        }
        out.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return out

    def to_markdown(self) -> str:
        """Genera informe Markdown legible con todas las secciones."""
        lines = [
            "# ECU Control Map",
            "",
            "| Campo | Valor |",
            "|-------|-------|",
            f"| VIN | {self.vin or 'no detectado'} |",
            f"| Protocolo | {self.protocol} |",
            f"| Fecha escaneo | {self.scan_date} |",
            "",
            f"## PIDs/Comandos Soportados ({len(self.supported_pids)})",
            "",
        ]
        for p in self.supported_pids[:20]:
            lines.append(f"- `{p.get('cmd', '')}` -> `{p.get('response', '')}`")
        if len(self.supported_pids) > 20:
            lines.append(f"- _(y {len(self.supported_pids) - 20} más)_")

        lines += [
            "",
            f"## IDs CAN Activos ({len(self.active_can_ids)})",
            "",
            "| CAN ID | Frames | Patrón | Entropía | DLC |",
            "|--------|--------|--------|----------|-----|",
        ]
        for r in sorted(self.active_can_ids, key=lambda x: x.can_id):
            lines.append(
                f"| 0x{r.can_id:03X} | {r.frame_count} | {r.byte_pattern} "
                f"| {r.entropy:.2f} | {r.dlc_common} |"
            )

        lines += [
            "",
            f"## Servicios UDS ({len(self.uds_services)})",
            "",
            "| ID | Nombre | Soportado | Riesgo | NRC |",
            "|----|--------|-----------|--------|-----|",
        ]
        for r in self.uds_services:
            check = "✓" if r.supported else "✗"
            lines.append(
                f"| 0x{r.service_id:02X} | {r.service_name} | {check} "
                f"| {r.risk_level} | {r.nrc or '-'} |"
            )

        lines += [
            "",
            f"## DIDs Legibles ({len(self.readable_dids)})",
            "",
        ]
        for did, resp in list(self.readable_dids.items())[:20]:
            hint = _WRITABLE_DID_HINTS.get(f"{did:04X}", "")
            hint_str = f" _{hint}_" if hint else ""
            lines.append(f"- `0x{did:04X}`{hint_str}: `{resp}`")
        if len(self.readable_dids) > 20:
            lines.append(f"- _(y {len(self.readable_dids) - 20} más)_")

        lines += [
            "",
            f"## Candidatos a Escritura ({len(self.write_candidates)})",
            "",
        ]
        for w in self.write_candidates:
            lines.append(
                f"- DID {w['did']} ({w.get('hint', 'unknown')}): "
                f"`{w.get('current_value', '')}`"
            )

        lines += [
            "",
            f"## Actuadores Inferidos ({len(self.actuator_candidates)})",
            "",
        ]
        for a in self.actuator_candidates:
            lines.append(
                f"- `{a.get('id', '')}` [{a.get('type', '')}] — "
                f"{a.get('description', '')} (confianza: {a.get('confidence', '')})"
            )

        lines += [
            "",
            f"## Correlaciones de Señal ({len(self.signal_correlations)})",
            "",
        ]
        for d in self.signal_correlations[:10]:
            lines.append(
                f"- **{d.action_label}** -> {d.pid_or_id}: "
                f"`{d.before_value}` -> `{d.after_value}` "
                f"(mag={d.change_magnitude:.2f})"
            )

        return "\n".join(lines)

    def generate_python_snippet(self) -> str:
        """
        Genera un snippet Python de ejemplo que muestra cómo enviar comandos
        a los PIDs/DIDs descubiertos usando el protocolo detectado.
        """
        lines = [
            '"""',
            f'Snippet autogenerado por ECUControlMap — protocolo: {self.protocol}',
            f'VIN: {self.vin or "desconocido"} | Fecha: {self.scan_date}',
            '"""',
            "from scaner_soler.comm.elm327 import ELM327Protocol",
            "",
            "# Conectar al adaptador ELM327",
            'proto = ELM327Protocol(port="COM3", baudrate=38400)',
            "proto.connect()",
            "",
        ]
        if self.protocol == "UDS":
            lines += [
                "# UDS: Leer DIDs descubiertos con ReadDataByIdentifier (0x22)",
                "def read_did(did_hi: int, did_lo: int) -> str:",
                '    return proto.send_command(f"22 {did_hi:02X} {did_lo:02X}")',
                "",
            ]
            for did in list(self.readable_dids.keys())[:5]:
                hi = (did >> 8) & 0xFF
                lo = did & 0xFF
                hint = _WRITABLE_DID_HINTS.get(f"{did:04X}", "data")
                var_name = hint.lower().replace(" ", "_").replace("-", "_")
                lines.append(
                    f'result_{var_name} = '
                    f'read_did(0x{hi:02X}, 0x{lo:02X})  # DID 0x{did:04X}'
                )
        else:
            lines += [
                "# OBD2: Leer PIDs descubiertos",
                "def read_pid(pid: int) -> str:",
                '    return proto.send_command(f"01 {pid:02X}")',
                "",
                "rpm    = read_pid(0x0C)  # RPM del motor",
                "speed  = read_pid(0x0D)  # Velocidad km/h",
                "load   = read_pid(0x04)  # Carga motor %",
                "temp   = read_pid(0x05)  # Temperatura refrigerante °C",
            ]
        if self.write_candidates:
            lines += [
                "",
                "# Escritura de DIDs — USAR CON PRECAUCIÓN",
                "def write_did(did_hi: int, did_lo: int, data_bytes: str) -> str:",
                '    return proto.send_command(f"2E {did_hi:02X} {did_lo:02X} {data_bytes}")',
            ]
        return "\n".join(lines)

    def _infer_actuators(self) -> list:
        """
        Infiere qué parámetros son actuadores vs sensores basándose en:
        - DIDs escribibles (0x2E soportado)
        - Cambios correlacionados con acciones (SignalChangeMonitor)
        - IDs CAN con tráfico dinámico
        """
        actuators: list[dict] = []
        seen: set[str] = set()

        # 1. DIDs escribibles
        for wc in self.write_candidates:
            did_key = wc["did"]
            if did_key in seen:
                continue
            hint = wc.get("hint", "").lower()
            is_known_actuator = any(kw in hint for kw in _ACTUATOR_KEYWORDS)
            actuators.append({
                "id": did_key,
                "type": "DID_writable",
                "description": wc.get("hint", "unknown writable DID"),
                "confidence": "medium" if is_known_actuator else "low",
                "source": "UDS_WriteDataByIdentifier",
            })
            seen.add(did_key)

        # 2. Señales con alta magnitud de cambio
        for d in self.signal_correlations:
            if d.change_magnitude > 0.5 and d.pid_or_id not in seen:
                actuators.append({
                    "id": d.pid_or_id,
                    "type": "signal_correlated",
                    "description": (
                        f"Cambió {d.change_magnitude:.0%} con acción '{d.action_label}'"
                    ),
                    "confidence": "high" if d.change_magnitude > 0.8 else "medium",
                    "source": "SignalChangeMonitor",
                })
                seen.add(d.pid_or_id)

        # 3. IDs CAN dinámicos de alta entropía
        for r in self.active_can_ids:
            can_key = f"CAN:0x{r.can_id:03X}"
            if r.byte_pattern in ("dynamic", "mixed") and r.entropy > 4.0:
                if can_key not in seen:
                    actuators.append({
                        "id": can_key,
                        "type": "CAN_dynamic",
                        "description": (
                            f"ID CAN con tráfico dinámico (entropía={r.entropy:.2f})"
                        ),
                        "confidence": "low",
                        "source": "CANBusScanner",
                    })
                    seen.add(can_key)

        return actuators


# ── full_scan para ReverseEngineerSession (añadido sin modificar la clase) ────

def _full_scan_impl(
        self: ReverseEngineerSession,
        skip_can: bool = False,
        skip_uds_map: bool = False,
        callback: Optional[Callable[[str], None]] = None,
) -> ECUControlMap:
    """
    Pipeline completo:
    1. quick_profile() → protocolo + PIDs básicos
    2. CANBusScanner.scan_traffic(10s) → IDs activos
    3. UDSServiceMap.scan_all() → servicios soportados + DID scan F100-F1FF
    4. ECUControlMap.build() → mapa final

    Retorna ECUControlMap listo para exportar con to_json() / to_markdown().
    """
    _cb = callback or (lambda m: None)

    # 1. Profile
    _cb("[1/4] Perfilando ECU (quick_profile)...")
    profile = self.quick_profile()
    _cb(f"      Protocolo: {profile.best_protocol} | VIN: {profile.vin or 'N/A'} "
        f"| ECUs: {profile.ecu_addresses}")

    # 2. CAN bus scan
    can_results: list[CANScanResult] = []
    if not skip_can:
        _cb("[2/4] Escaneando bus CAN (10 s demo)...")
        scanner = CANBusScanner(self.send, journal=self._journal)
        can_results = scanner.scan_traffic(
            duration_s=10.0,
            callback=lambda m: _cb(f"      {m}"),
        )
        _cb(f"      IDs CAN activos: {len(can_results)}")
    else:
        _cb("[2/4] CAN scan omitido (skip_can=True).")

    # 3. UDS service map + RDBI range scan
    service_results: list[UDSServiceResult] = []
    rdbi_results: dict[int, str] = {}
    if not skip_uds_map:
        _cb("[3/4] Mapeando servicios UDS...")
        uds_map = UDSServiceMap(self.send, journal=self._journal)
        service_results = uds_map.scan_all(
            skip_danger=True,
            callback=lambda m: _cb(f"      {m}"),
        )
        _cb("      Escaneando DIDs F100-F1FF con RDBI...")
        rdbi_results = uds_map.scan_rdbi_range(
            0xF100, 0xF1FF,
            callback=lambda m: _cb(f"      {m}"),
        )
        n_ok = sum(1 for r in service_results if r.supported)
        _cb(f"      Servicios UDS soportados: {n_ok} | DIDs legibles: {len(rdbi_results)}")
    else:
        _cb("[3/4] UDS map omitido (skip_uds_map=True).")

    # 4. Construir mapa final
    _cb("[4/4] Construyendo ECUControlMap...")
    control_map = ECUControlMap.build(
        profile=profile,
        can_results=can_results,
        service_map=service_results,
        rdbi_results=rdbi_results,
        signal_deltas=[],
    )
    _cb(
        f"      Mapa completo: {len(control_map.active_can_ids)} CAN IDs | "
        f"{len(control_map.uds_services)} servicios UDS | "
        f"{len(control_map.readable_dids)} DIDs | "
        f"{len(control_map.actuator_candidates)} actuadores inferidos."
    )
    return control_map


# Inyectar full_scan en ReverseEngineerSession sin tocar la definición original
ReverseEngineerSession.full_scan = _full_scan_impl  # type: ignore[attr-defined]


# ── run_full_demo ─────────────────────────────────────────────────────────────

def run_full_demo(export_path: Optional[str] = None) -> ECUControlMap:
    """
    Pipeline completo de demostración sin hardware físico.
    Usa _demo_send_fn que simula respuestas de una ECU OBD2/UDS.

    export_path: ruta JSON opcional para guardar el mapa (None = no exportar).
    """
    print("=== Scaner Soler — Full Reverse-Engineer Pipeline (DEMO) ===\n")
    session = ReverseEngineerSession(
        send_fn=_demo_send_fn,
        on_progress=lambda m, p: print(f"  [{p * 100:5.1f}%] {m}", flush=True),
    )
    control_map = session.full_scan(
        skip_can=False,
        skip_uds_map=False,
        callback=lambda m: print(f"  {m}", flush=True),
    )

    print(f"\n{'=' * 60}")
    print(f"VIN              : {control_map.vin or 'no detectado'}")
    print(f"Protocolo        : {control_map.protocol}")
    print(f"IDs CAN activos  : {len(control_map.active_can_ids)}")
    n_uds_ok = sum(1 for r in control_map.uds_services if r.supported)
    print(f"Servicios UDS    : {len(control_map.uds_services)} total, {n_uds_ok} soportados")
    print(f"DIDs legibles    : {len(control_map.readable_dids)}")
    print(f"Write candidates : {len(control_map.write_candidates)}")
    print(f"Actuadores inf.  : {len(control_map.actuator_candidates)}")

    if export_path:
        out = control_map.to_json(export_path)
        print(f"\nMapa exportado   : {out}")

    print("\n--- Markdown Report (primeras 40 líneas) ---")
    for line in control_map.to_markdown().split("\n")[:40]:
        print(line)

    print("\n--- Python Snippet ---")
    print(control_map.generate_python_snippet())

    return control_map


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

    print("\n\n=== Full Pipeline Demo ===\n")
    run_full_demo()
