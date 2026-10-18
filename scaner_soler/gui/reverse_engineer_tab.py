"""
reverse_engineer_tab.py — Pestaña GUI para Ingeniería Inversa de ECU.
Estilo 2026: paleta abismal + tarjetas KPI + barra de progreso animada.
"""
from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from typing import Optional

try:
    from ..comm.reverse_engineer import (
        ReverseEngineerSession, RESessionResult,
        PatternAnalyzer, run_demo,
    )
    _RE_AVAILABLE = True
except ImportError:
    _RE_AVAILABLE = False

# ── Paleta (igual que app.py) ──────────────────────────────────────────────────
DARK_BG   = "#080812"
SURFACE   = "#0e0e1c"
CARD      = "#141428"
BORDER    = "#1e1e38"
ACCENT    = "#7c3aed"
ACCENT_LT = "#a855f7"
CYAN      = "#06b6d4"
GREEN     = "#10b981"
RED       = "#f43f5e"
YELLOW    = "#f59e0b"
FG        = "#e2e8f0"
SUBTEXT   = "#64748b"
ENTRY_BG  = "#1a1a32"
ORANGE    = "#f97316"

# ── Mini widgets ──────────────────────────────────────────────────────────────

class _StatCard(tk.Canvas):
    """Tarjeta KPI reutilizable."""
    W, H = 140, 80

    def __init__(self, parent, label: str, value: str = "—",
                 color: str = CYAN, **kw):
        super().__init__(parent, width=self.W, height=self.H,
                         bg=CARD, highlightthickness=0, **kw)
        self._color = color
        self._label = label
        self._value = value
        self._draw()

    def _draw(self):
        self.delete("all")
        # barra superior
        self.create_rectangle(0, 0, self.W, 3, fill=self._color, outline="")
        # fondo card
        self.create_rectangle(0, 3, self.W, self.H, fill=CARD, outline="")
        # label
        self.create_text(12, 20, text=self._label.upper(), anchor="w",
                         fill=SUBTEXT, font=("Consolas", 7, "bold"))
        # valor
        self.create_text(12, 52, text=self._value, anchor="w",
                         fill=self._color, font=("Consolas", 20, "bold"))

    def update_value(self, value: str, color: Optional[str] = None):
        self._value = value
        if color:
            self._color = color
        self._draw()


class _ActionBtn(tk.Canvas):
    """Botón redondeado con hover."""
    def __init__(self, parent, text: str, command=None,
                 color: str = ACCENT, w: int = 160, h: int = 36, **kw):
        super().__init__(parent, width=w, height=h,
                         bg=SURFACE, highlightthickness=0, cursor="hand2", **kw)
        self._bw, self._bh = w, h
        self._color = color
        self._hover_color = ACCENT_LT if color == ACCENT else color
        self._text = text
        self._cmd  = command
        self._draw(color)
        self.bind("<Enter>",  lambda e: self._draw(self._hover_color))
        self.bind("<Leave>",  lambda e: self._draw(self._color))
        self.bind("<Button-1>", lambda e: self._cmd() if self._cmd else None)

    def _draw(self, bg: str):
        self.delete("all")
        r = 6
        x0, y0, x1, y1 = 1, 1, self._bw - 1, self._bh - 1
        self.create_arc(x0, y0, x0 + 2*r, y0 + 2*r, start=90,  extent=90,  fill=bg, outline="")
        self.create_arc(x1 - 2*r, y0, x1, y0 + 2*r, start=0,   extent=90,  fill=bg, outline="")
        self.create_arc(x0, y1 - 2*r, x0 + 2*r, y1, start=180, extent=90,  fill=bg, outline="")
        self.create_arc(x1 - 2*r, y1 - 2*r, x1, y1, start=270, extent=90,  fill=bg, outline="")
        self.create_rectangle(x0 + r, y0, x1 - r, y1, fill=bg, outline="")
        self.create_rectangle(x0, y0 + r, x1, y1 - r, fill=bg, outline="")
        self.create_text(self._bw // 2, self._bh // 2,
                         text=self._text, fill="#ffffff",
                         font=("Consolas", 9, "bold"))

    def configure_state(self, enabled: bool):
        self._cmd = self._cmd if enabled else None
        self.configure(cursor="hand2" if enabled else "arrow")


class _ProgressBar(tk.Canvas):
    """Barra de progreso animada con shimmer."""
    def __init__(self, parent, **kw):
        super().__init__(parent, height=6, bg=SURFACE,
                         highlightthickness=0, **kw)
        self._running   = False
        self._progress  = 0.0
        self._shimmer_x = 0

    def set_progress(self, pct: float):
        self._progress = max(0.0, min(1.0, pct))
        self._redraw()

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width() or 400
        self.create_rectangle(0, 0, w, 6, fill=ENTRY_BG, outline="")
        if self._progress > 0:
            fill_w = int(w * self._progress)
            self.create_rectangle(0, 0, fill_w, 6, fill=ACCENT, outline="")
            # shimmer
            sx = self._shimmer_x % (fill_w + 40) - 20
            self.create_rectangle(sx, 0, sx + 20, 6,
                                   fill=ACCENT_LT, outline="")

    def start(self):
        self._running = True
        self._animate()

    def stop(self):
        self._running = False

    def _animate(self):
        if not self._running:
            return
        self._shimmer_x += 8
        self._redraw()
        self.after(30, self._animate)


# ── ReverseEngineerTab ────────────────────────────────────────────────────────

class ReverseEngineerTab(tk.Frame):
    """Pestaña completa de Ingeniería Inversa de ECU."""

    def __init__(self, parent, app=None, **kw):
        super().__init__(parent, bg=DARK_BG, **kw)
        self._app    = app
        self._result: Optional[RESessionResult] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        # Header strip
        hdr = tk.Frame(self, bg=SURFACE)
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=ACCENT, height=3).pack(fill="x")
        inner = tk.Frame(hdr, bg=SURFACE)
        inner.pack(fill="x", padx=16, pady=6)
        tk.Label(inner, text="INGENIERÍA INVERSA  ",
                 bg=SURFACE, fg=FG, font=("Consolas", 12, "bold")).pack(side="left")
        tk.Label(inner, text="ECU",
                 bg=SURFACE, fg=ACCENT_LT, font=("Consolas", 12, "bold")).pack(side="left")
        tk.Label(inner, text=" · Detección automática de protocolo + fuzzing de PIDs/DIDs",
                 bg=SURFACE, fg=SUBTEXT, font=("Consolas", 8)).pack(side="left")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Controls
        ctrl = tk.Frame(self, bg=SURFACE, pady=8)
        ctrl.pack(fill="x", padx=12)

        tk.Label(ctrl, text="MODO FUZZ:", bg=SURFACE, fg=SUBTEXT,
                 font=("Consolas", 8, "bold")).pack(side="left", padx=(0, 6))
        self._fuzz_mode = tk.StringVar(value="smart")
        for val, lbl in [("smart", "Auto"), ("obd", "OBD Only"),
                          ("uds", "UDS Only"), ("both", "OBD + UDS")]:
            tk.Radiobutton(
                ctrl, text=lbl, variable=self._fuzz_mode, value=val,
                bg=SURFACE, fg=FG, selectcolor=ACCENT,
                activebackground=SURFACE, activeforeground=FG,
                font=("Consolas", 9), cursor="hand2"
            ).pack(side="left", padx=4)

        tk.Frame(ctrl, bg=BORDER, width=1, height=24).pack(side="left", padx=12)

        self._only_profile = tk.BooleanVar(value=False)
        tk.Checkbutton(
            ctrl, text="Solo perfilar (sin fuzzing)", variable=self._only_profile,
            bg=SURFACE, fg=FG, selectcolor=ACCENT,
            activebackground=SURFACE, font=("Consolas", 9)
        ).pack(side="left", padx=4)

        tk.Frame(ctrl, bg=BORDER, width=1, height=24).pack(side="left", padx=12)

        self._demo_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            ctrl, text="Modo DEMO (sin hardware)", variable=self._demo_var,
            bg=SURFACE, fg=YELLOW, selectcolor=ACCENT,
            activebackground=SURFACE, font=("Consolas", 9)
        ).pack(side="left", padx=4)

        # Buttons
        btn_row = tk.Frame(self, bg=DARK_BG, pady=6)
        btn_row.pack(fill="x", padx=12)

        self._btn_run = _ActionBtn(btn_row, "▶  INICIAR SESIÓN RE",
                                   command=self._start_session,
                                   color=ACCENT, w=200)
        self._btn_run.pack(side="left", padx=(0, 8))

        self._btn_stop = _ActionBtn(btn_row, "■  DETENER",
                                    command=self._stop_session,
                                    color=RED, w=120)
        self._btn_stop.pack(side="left", padx=(0, 8))

        self._btn_export = _ActionBtn(btn_row, "⬇  EXPORTAR JSON",
                                      command=self._export,
                                      color=CYAN, w=160)
        self._btn_export.pack(side="left", padx=(0, 8))

        # Progress
        prog_row = tk.Frame(self, bg=DARK_BG, pady=2)
        prog_row.pack(fill="x", padx=12)
        self._prog_bar = _ProgressBar(prog_row)
        self._prog_bar.pack(fill="x")
        self._prog_label = tk.Label(prog_row, text="Esperando inicio…",
                                    bg=DARK_BG, fg=SUBTEXT,
                                    font=("Consolas", 8))
        self._prog_label.pack(anchor="w", pady=2)

        # KPI cards
        kpi_row = tk.Frame(self, bg=DARK_BG, pady=6)
        kpi_row.pack(fill="x", padx=12)
        self._card_proto    = _StatCard(kpi_row, "Protocolo",   "—",  ACCENT_LT)
        self._card_vin      = _StatCard(kpi_row, "VIN",         "—",  CYAN)
        self._card_pids     = _StatCard(kpi_row, "PIDs/DIDs OK","0",  GREEN)
        self._card_ecus     = _StatCard(kpi_row, "ECUs",        "0",  YELLOW)
        self._card_entropy  = _StatCard(kpi_row, "Entropía avg","— b", ORANGE)
        self._card_duration = _StatCard(kpi_row, "Duración",    "—s", SUBTEXT)
        for card in (self._card_proto, self._card_vin, self._card_pids,
                     self._card_ecus, self._card_entropy, self._card_duration):
            card.pack(side="left", padx=4)

        # Main content split
        split = tk.Frame(self, bg=DARK_BG)
        split.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # Left: fuzz catalog treeview
        left = tk.Frame(split, bg=DARK_BG)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="CATÁLOGO DE PIDs/DIDs RESPONDIDOS",
                 bg=DARK_BG, fg=SUBTEXT, font=("Consolas", 8, "bold")).pack(anchor="w")

        tree_frame = tk.Frame(left, bg=CARD)
        tree_frame.pack(fill="both", expand=True)
        cols = ("pid_did", "service", "response", "bytes", "entropy")
        self.tree = ttk.Treeview(tree_frame, columns=cols,
                                  show="headings", selectmode="browse")
        for col, lbl, w in [
            ("pid_did",  "PID/DID",    80),
            ("service",  "Servicio",   70),
            ("response", "Respuesta", 200),
            ("bytes",    "Bytes",      60),
            ("entropy",  "Entropía",   70),
        ]:
            self.tree.heading(col, text=lbl)
            self.tree.column(col, width=w, anchor="w")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                             command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Right: detail panel
        right = tk.Frame(split, bg=DARK_BG, width=320)
        right.pack(side="right", fill="y", padx=(8, 0))
        right.pack_propagate(False)
        tk.Label(right, text="DETALLE / ANÁLISIS",
                 bg=DARK_BG, fg=SUBTEXT, font=("Consolas", 8, "bold")).pack(anchor="w")

        self._det_border = tk.Frame(right, bg=BORDER, padx=3, pady=3)
        self._det_border.pack(fill="both", expand=True)
        self._detail = tk.Text(self._det_border, bg=CARD, fg=FG,
                                font=("Consolas", 9), wrap="word",
                                relief="flat", state="disabled")
        sb2 = ttk.Scrollbar(self._det_border, orient="vertical",
                              command=self._detail.yview)
        self._detail.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y")
        self._detail.pack(fill="both", expand=True)
        self._detail.tag_configure("heading",  foreground=ACCENT_LT,
                                    font=("Consolas", 9, "bold"))
        self._detail.tag_configure("key",      foreground=CYAN)
        self._detail.tag_configure("value",    foreground=FG)
        self._detail.tag_configure("positive", foreground=GREEN)
        self._detail.tag_configure("negative", foreground=RED)
        self._detail.tag_configure("warn",     foreground=YELLOW)
        self._detail.tag_configure("subtext",  foreground=SUBTEXT,
                                    font=("Consolas", 8))

        self._show_detail_idle()

    # ── Session control ──────────────────────────────────────────────────────

    def _start_session(self):
        if self._running:
            return
        self._running = True
        self._clear_results()
        self._prog_bar.set_progress(0.0)
        self._prog_bar.start()

        if self._demo_var.get():
            send_fn = self._get_demo_fn()
        else:
            send_fn = self._get_live_fn()
            if send_fn is None:
                self._running = False
                return

        fuzz   = not self._only_profile.get()
        mode   = self._fuzz_mode.get()
        session = ReverseEngineerSession(
            send_fn=send_fn,
            on_progress=self._on_progress,
        )

        def _run():
            try:
                result = session.run(fuzz=fuzz, fuzz_mode=mode)
                self.after(0, lambda: self._on_done(result))
            except Exception as exc:
                self.after(0, lambda: self._on_error(str(exc)))

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def _stop_session(self):
        self._running = False
        self._prog_bar.stop()
        self._set_progress("Sesión detenida por el usuario.", 0.0)

    def _get_demo_fn(self):
        from ..comm.reverse_engineer import _demo_send_fn
        return _demo_send_fn

    def _get_live_fn(self):
        # Intenta obtener el protocolo del backend de la app principal
        try:
            backend = getattr(self._app, "backend", None)
            if backend and hasattr(backend, "send_command"):
                return backend.send_command
            proto = getattr(self._app, "_protocol", None)
            if proto and hasattr(proto, "send_command"):
                return proto.send_command
        except Exception:
            pass
        messagebox.showwarning(
            "Sin conexión",
            "No hay backend ELM327 conectado.\n"
            "Activa el modo DEMO o conecta el adaptador primero."
        )
        return None

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_progress(self, msg: str, pct: float):
        self.after(0, lambda: self._set_progress(msg, pct))

    def _set_progress(self, msg: str, pct: float):
        self._prog_bar.set_progress(pct)
        self._prog_label.configure(text=msg)

    def _on_done(self, result: RESessionResult):
        self._running = False
        self._result  = result
        self._prog_bar.stop()
        self._prog_bar.set_progress(1.0)
        self._set_progress(
            f"Completado en {result.duration_s}s — "
            f"{len(result.fuzz_catalog)} PIDs/DIDs encontrados.", 1.0
        )
        self._update_kpis(result)
        self._populate_tree(result)
        self._show_profile_detail(result)

    def _on_error(self, msg: str):
        self._running = False
        self._prog_bar.stop()
        self._set_progress(f"Error: {msg}", 0.0)
        messagebox.showerror("Error RE", msg)

    # ── UI updates ────────────────────────────────────────────────────────────

    def _update_kpis(self, result: RESessionResult):
        p = result.profile
        ps = result.pattern_stats
        self._card_proto.update_value(p.best_protocol, ACCENT_LT)
        vin_short = (p.vin[:11] + "…") if (p.vin and len(p.vin) > 11) else (p.vin or "—")
        self._card_vin.update_value(vin_short, CYAN)
        self._card_pids.update_value(str(len(result.fuzz_catalog)),
                                      GREEN if result.fuzz_catalog else SUBTEXT)
        self._card_ecus.update_value(str(len(p.ecu_addresses)),
                                      YELLOW if p.ecu_addresses else SUBTEXT)
        self._card_entropy.update_value(f"{ps['avg_entropy']}b", ORANGE)
        self._card_duration.update_value(f"{result.duration_s}s", SUBTEXT)

    def _populate_tree(self, result: RESessionResult):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for entry in result.fuzz_catalog:
            pid  = entry.get("pid_did", "—")
            svc  = entry.get("service", "—")
            resp = entry.get("response", "")[:40]
            nb   = str(len(entry.get("bytes", [])))
            ent  = str(entry.get("entropy", 0.0))
            iid  = self.tree.insert("", "end",
                                     values=(pid, svc, resp, nb, ent))
            # Color por entropía
            e_val = float(entry.get("entropy", 0.0))
            if e_val > 3.5:
                self.tree.item(iid, tags=("high_entropy",))
            elif e_val > 1.5:
                self.tree.item(iid, tags=("mid_entropy",))

        self.tree.tag_configure("high_entropy",
                                 background="#0a1a0a", foreground=GREEN)
        self.tree.tag_configure("mid_entropy",
                                 background="#0e0e1c", foreground=CYAN)

    def _on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel or not self._result:
            return
        vals = self.tree.item(sel[0], "values")
        pid, svc, resp, nb, ent = vals

        # Encuentra entry completo
        entry = next(
            (e for e in self._result.fuzz_catalog
             if e.get("pid_did") == pid),
            None
        )
        if not entry:
            return

        d = self._detail
        d.configure(state="normal")
        d.delete("1.0", "end")
        d.insert("end", "PID / DID SELECCIONADO\n", "heading")
        d.insert("end", f"  Identificador : ", "key")
        d.insert("end", f"{pid}\n", "value")
        d.insert("end", f"  Servicio      : ", "key")
        d.insert("end", f"{svc}\n", "value")
        d.insert("end", f"  Entropía      : ", "key")
        e_val = float(ent)
        color = "positive" if e_val > 3.5 else "warn" if e_val > 1.5 else "negative"
        d.insert("end", f"{ent} bits\n", color)

        d.insert("end", "\nRESPUESTA CRUDA\n", "heading")
        d.insert("end", f"  {entry.get('response', '')}\n", "value")

        d.insert("end", "\nBYTES DECODIFICADOS\n", "heading")
        raw_bytes = entry.get("bytes", [])
        hex_str = " ".join(f"{b:02X}" for b in raw_bytes)
        d.insert("end", f"  HEX : {hex_str}\n", "value")
        ascii_str = "".join(chr(b) if 0x20 <= b <= 0x7E else "." for b in raw_bytes)
        d.insert("end", f"  ASCII: {ascii_str}\n", "value")

        d.insert("end", "\nANÁLISIS DE PATRÓN\n", "heading")
        stats = PatternAnalyzer.analyze_frame(entry.get("response", ""))
        d.insert("end", f"  Bytes totales  : {stats.length}\n", "value")
        d.insert("end", f"  Checksum OK    : ", "key")
        ck = stats.checksum_ok
        d.insert("end", f"{'Sí' if ck else 'No' if ck is False else '—'}\n",
                 "positive" if ck else "negative")
        d.insert("end", f"  Bytes más comunes:\n", "key")
        for byte_val, cnt in stats.top_bytes[:4]:
            d.insert("end", f"    0x{byte_val:02X} = {cnt}×\n", "subtext")

        d.configure(state="disabled")

    def _show_profile_detail(self, result: RESessionResult):
        p  = result.profile
        ps = result.pattern_stats
        d  = self._detail
        d.configure(state="normal")
        d.delete("1.0", "end")
        d.insert("end", "PERFIL DE ECU DETECTADO\n", "heading")
        d.insert("end", f"  Protocolo     : ", "key")
        d.insert("end", f"{p.best_protocol}\n", "positive")
        d.insert("end", f"  VIN           : ", "key")
        d.insert("end", f"{p.vin or '—'}\n", "value")
        d.insert("end", f"  ECUs en red   : ", "key")
        d.insert("end", f"{', '.join(p.ecu_addresses) or '—'}\n", "value")
        d.insert("end", f"  Servicios OK  : ", "key")
        d.insert("end", f"{', '.join(hex(s) for s in p.supported_services) or '—'}\n",
                 "value")

        d.insert("end", "\nCONFIANZA POR PROTOCOLO\n", "heading")
        for g in p.protocol_guesses[:4]:
            bar = "█" * int(g.confidence * 10) + "░" * (10 - int(g.confidence * 10))
            color = "positive" if g.confidence > 0.6 else "warn" if g.confidence > 0.3 else "subtext"
            d.insert("end", f"  {g.protocol:12s} {bar} {g.confidence*100:.0f}%\n", color)

        d.insert("end", "\nESTADÍSTICAS DE SESIÓN\n", "heading")
        d.insert("end", f"  Frames totales : {ps['total_frames']}\n", "value")
        d.insert("end", f"  Frames únicos  : {ps['unique_frames']}\n", "value")
        d.insert("end", f"  Entropía media : {ps['avg_entropy']} bits\n", "value")
        d.insert("end", f"  Duración       : {result.duration_s}s\n", "value")

        if p.protocol_guesses:
            best = p.protocol_guesses[0]
            d.insert("end", "\nCOMENDOS AT RECOMENDADOS\n", "heading")
            for cmd in best.recommended_init:
                d.insert("end", f"  {cmd}\n", "key")

        d.configure(state="disabled")

    def _show_detail_idle(self):
        d = self._detail
        d.configure(state="normal")
        d.delete("1.0", "end")
        d.insert("end", "MÓDULO DE INGENIERÍA INVERSA\n\n", "heading")
        d.insert("end", "Técnicas implementadas:\n", "key")
        for line in [
            "• Agent-loop (observar → hipótesis → refinar)",
            "• Firma de protocolos (UDS/KWP2000/OBD2/ISO9141)",
            "• Fuzzing de PIDs OBD (Mode 01–0A)",
            "• Fuzzing de DIDs UDS 0x22 (0xF100–0xF1FF)",
            "• Análisis de entropía de Shannon",
            "• Histograma de bytes",
            "• Verificación de checksums (XOR / suma)",
            "• Field Journal (log completo request→response)",
        ]:
            d.insert("end", f"  {line}\n", "subtext")
        d.insert("end", "\nInicia una sesión con ▶ INICIAR SESIÓN RE\n", "warn")
        d.configure(state="disabled")

    def _clear_results(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for card in (self._card_proto, self._card_vin, self._card_pids,
                     self._card_ecus, self._card_entropy, self._card_duration):
            card.update_value("—")
        self._show_detail_idle()

    # ── Export ────────────────────────────────────────────────────────────────

    def _export(self):
        if not self._result:
            messagebox.showinfo("Sin datos", "Primero ejecuta una sesión RE.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Todos", "*.*")],
            title="Guardar catálogo RE",
        )
        if not path:
            return
        data = {
            "profile": self._result.profile.to_dict(),
            "fuzz_catalog": self._result.fuzz_catalog,
            "pattern_stats": self._result.pattern_stats,
            "journal_summary": self._result.journal_summary,
            "duration_s": self._result.duration_s,
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        messagebox.showinfo("Exportado", f"Datos guardados en:\n{path}")
