"""
Tab 1 — Diagnósticos: escaneo DTC, freeze frame, guía de reparación.
Diseño 2026: tarjetas KPI + treeview con badges de severidad.
"""
import math
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime

# ── Paleta ─────────────────────────────────────────────────────────────────────
BG      = "#080812"
SURFACE = "#0e0e1c"
CARD    = "#141428"
BORDER  = "#1e1e38"
ACCENT  = "#7c3aed"
ACCENT2 = "#a855f7"
CYAN    = "#06b6d4"
GREEN   = "#10b981"
RED     = "#f43f5e"
YELLOW  = "#f59e0b"
TEXT    = "#e2e8f0"
SUBTEXT = "#64748b"
ENTRY_BG = "#1a1a32"

SEVERITY_COLOR = {
    "critical": RED,
    "warning":  YELLOW,
    "info":     CYAN,
    "":         TEXT,
}
SEVERITY_BG = {
    "critical": "#1f0a0f",
    "warning":  "#1f150a",
    "info":     "#0a1820",
    "":         CARD,
}

_DEMO_DTCS = [
    {"code": "P0300", "description": "Random/Multiple Cylinder Misfire",
     "system": "Ignition", "severity": "critical",
     "suggested_action": "Revisar bujías, bobinas e inyectores."},
    {"code": "P0171", "description": "System Too Lean Bank 1",
     "system": "Fuel System", "severity": "critical",
     "suggested_action": "Revisar MAF, fugas de vacío, inyectores."},
    {"code": "P0420", "description": "Catalyst Efficiency Below Threshold",
     "system": "Emissions", "severity": "warning",
     "suggested_action": "Revisar catalizador y sondas O2."},
    {"code": "P1259", "description": "VTEC Bank 1 Malfunction",
     "system": "VTEC", "severity": "critical",
     "suggested_action": "Verificar presión de aceite y solenoide VTEC."},
]


# ── Stat Card (Canvas) ─────────────────────────────────────────────────────────

class StatCard(tk.Canvas):
    """Tarjeta KPI con borde superior de color, número grande y etiqueta."""

    def __init__(self, parent, label="", value="—", color=ACCENT,
                 sub="", width=190, height=80, **kw):
        super().__init__(parent, width=width, height=height,
                         bg=CARD, highlightthickness=0, **kw)
        self._label = label
        self._color = color
        self._sub   = sub
        self._cw    = width
        self._ch    = height
        self._val   = value
        self._draw()

    def update_value(self, value, color=None, sub=None):
        self._val   = str(value)
        if color: self._color = color
        if sub is not None: self._sub = sub
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self._cw, self._ch

        # Fondo
        self.create_rectangle(0, 0, w, h, fill=CARD, outline=BORDER, width=1)
        # Barra de color superior (4px)
        self.create_rectangle(0, 0, w, 4, fill=self._color, outline="")

        # Etiqueta superior
        self.create_text(14, 18, text=self._label.upper(), anchor="w",
                         fill=SUBTEXT, font=("Consolas", 7, "bold"))

        # Valor principal
        self.create_text(14, 52, text=self._val, anchor="w",
                         fill=self._color, font=("Consolas", 22, "bold"))

        # Sub-etiqueta
        if self._sub:
            self.create_text(w - 10, h - 10, text=self._sub, anchor="se",
                             fill=SUBTEXT, font=("Consolas", 7))


# ── Botón de acción ─────────────────────────────────────────────────────────────

class ActionBtn(tk.Canvas):
    """Botón moderno con hover effect."""

    def __init__(self, parent, text="", command=None,
                 color=ACCENT, width=150, height=32, **kw):
        super().__init__(parent, width=width, height=height,
                         bg=BG, highlightthickness=0, cursor="hand2", **kw)
        self._text    = text
        self._command = command
        self._color   = color
        self._bw      = width
        self._bh      = height
        self._hover   = False
        self._draw()
        self.bind("<Enter>",    lambda e: self._set_hover(True))
        self.bind("<Leave>",    lambda e: self._set_hover(False))
        self.bind("<Button-1>", lambda e: self._click())

    def _set_hover(self, val):
        self._hover = val
        self._draw()

    def _click(self):
        self._draw()
        if self._command:
            self.after(60, self._command)

    def _draw(self):
        self.delete("all")
        w, h = self._bw, self._bh
        r = 4
        fill = ACCENT2 if self._hover else self._color
        # Rounded rect via overlapping shapes
        self.create_arc(0, 0, r*2, r*2, start=90, extent=90, fill=fill, outline="")
        self.create_arc(w-r*2, 0, w, r*2, start=0, extent=90, fill=fill, outline="")
        self.create_arc(0, h-r*2, r*2, h, start=180, extent=90, fill=fill, outline="")
        self.create_arc(w-r*2, h-r*2, w, h, start=270, extent=90, fill=fill, outline="")
        self.create_rectangle(r, 0, w-r, h, fill=fill, outline="")
        self.create_rectangle(0, r, w, h-r, fill=fill, outline="")
        self.create_text(w//2, h//2, text=self._text,
                         fill="#ffffff", font=("Consolas", 8, "bold"))


# ── Progress bar animada ───────────────────────────────────────────────────────

class ScanProgress(tk.Canvas):
    """Barra de progreso de escaneo con shimmer."""

    def __init__(self, parent, **kw):
        super().__init__(parent, height=3, bg=BG, highlightthickness=0, **kw)
        self._active  = False
        self._pos     = 0
        self.bind("<Configure>", lambda e: self._redraw())

    def start(self):
        self._active = True
        self._loop()

    def stop(self):
        self._active = False
        self._redraw()

    def _loop(self):
        if not self._active:
            return
        self._pos = (self._pos + 4) % (self.winfo_width() + 80)
        self._redraw()
        self.after(16, self._loop)

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width() or 400
        self.create_rectangle(0, 0, w, 3, fill=BORDER, outline="")
        if self._active:
            x = self._pos - 80
            self.create_rectangle(x, 0, x + 80, 3, fill=ACCENT2, outline="")


# ── Tab principal ──────────────────────────────────────────────────────────────

def _get_unified_kb():
    try:
        from ..knowledge.unified_kb import UnifiedKnowledgeBase
        return UnifiedKnowledgeBase()
    except Exception:
        try:
            from ..diagnostic.dtc_database import DTCDatabase
            return DTCDatabase()
        except Exception:
            return None


class DiagnosticsTab(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.configure(style="TFrame")
        self.app   = app
        self._dtcs = []
        self._kb   = None
        self._build()
        threading.Thread(target=self._load_kb, daemon=True).start()

    def _load_kb(self):
        self._kb = _get_unified_kb()

    def _build(self):
        root_bg = tk.Frame(self, bg=BG)
        root_bg.pack(fill="both", expand=True)

        # ── Barra de controles ─────────────────────────────────────────────────
        ctrl = tk.Frame(root_bg, bg=SURFACE, pady=0)
        ctrl.pack(fill="x")
        tk.Frame(ctrl, bg=BORDER, height=1).pack(fill="x")

        inner_ctrl = tk.Frame(ctrl, bg=SURFACE)
        inner_ctrl.pack(fill="x", padx=16, pady=10)

        # Puerto
        tk.Label(inner_ctrl, text="PUERTO", bg=SURFACE, fg=SUBTEXT,
                 font=("Consolas", 7, "bold")).pack(side="left")
        self.port_var = tk.StringVar(value="COM3")
        port_entry = tk.Entry(inner_ctrl, textvariable=self.port_var, width=7,
                              bg=ENTRY_BG, fg=TEXT, insertbackground=ACCENT2,
                              relief="flat", font=("Consolas", 9),
                              bd=0, highlightthickness=1,
                              highlightcolor=ACCENT, highlightbackground=BORDER)
        port_entry.pack(side="left", padx=(6, 20), ipady=4)

        # Botones de acción
        self._scan_btn = ActionBtn(inner_ctrl, "⚡  ESCANEAR", self._scan,
                                   color=ACCENT, width=130, height=30)
        self._scan_btn.pack(side="left", padx=(0, 8))

        ActionBtn(inner_ctrl, "🔧  REPARACIÓN", self._show_repair_guide,
                  color="#1e3a5f", width=140, height=30).pack(side="left", padx=(0, 8))

        ActionBtn(inner_ctrl, "🗑  LIMPIAR", self._clear_dtcs,
                  color="#3f1010", width=110, height=30).pack(side="left", padx=(0, 8))

        ActionBtn(inner_ctrl, "💾  EXPORTAR", self._export,
                  color="#0f2f1f", width=110, height=30).pack(side="left", padx=(0, 8))

        # Status del scan
        self._status_var = tk.StringVar(value="")
        self._status_lbl = tk.Label(inner_ctrl, textvariable=self._status_var,
                                    bg=SURFACE, fg=SUBTEXT,
                                    font=("Consolas", 8))
        self._status_lbl.pack(side="right")

        # Barra de progreso shimmer
        self._progress = ScanProgress(root_bg)
        self._progress.pack(fill="x")

        # ── Tarjetas KPI ───────────────────────────────────────────────────────
        kpi_frame = tk.Frame(root_bg, bg=BG)
        kpi_frame.pack(fill="x", padx=16, pady=(14, 0))

        self._card_total    = StatCard(kpi_frame, "Total DTCs",    "0",  ACCENT2,  "modo demo",    190, 80)
        self._card_critical = StatCard(kpi_frame, "Críticos",      "0",  RED,      "falla grave",  175, 80)
        self._card_warning  = StatCard(kpi_frame, "Advertencias",  "0",  YELLOW,   "atención",     175, 80)
        self._card_health   = StatCard(kpi_frame, "Health Score",  "—",  GREEN,    "/ 100",        175, 80)
        self._card_proto    = StatCard(kpi_frame, "Protocolo",     "OBD-II", CYAN, "CAN / ISO",    175, 80)

        for card in [self._card_total, self._card_critical,
                     self._card_warning, self._card_health, self._card_proto]:
            card.pack(side="left", padx=(0, 8))

        # ── Separador ──────────────────────────────────────────────────────────
        tk.Frame(root_bg, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(14, 0))

        # ── Treeview de DTCs ───────────────────────────────────────────────────
        tree_frame = tk.Frame(root_bg, bg=BG)
        tree_frame.pack(fill="both", expand=True, padx=16, pady=(8, 0))

        # Header del treeview
        th = tk.Frame(tree_frame, bg=SURFACE)
        th.pack(fill="x")
        tk.Label(th, text="CÓDIGOS DE FALLA", bg=SURFACE, fg=SUBTEXT,
                 font=("Consolas", 8, "bold"),
                 padx=12, pady=6).pack(side="left")
        self._count_lbl = tk.Label(th, text="", bg=SURFACE, fg=SUBTEXT,
                                   font=("Consolas", 8))
        self._count_lbl.pack(side="right", padx=12)

        cols = ("sev_icon", "code", "system", "description", "action")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                 selectmode="browse", style="Treeview")
        for col, width, label, anchor in [
            ("sev_icon",    24,  "",              "center"),
            ("code",        80,  "Código",        "center"),
            ("system",     120,  "Sistema",       "w"),
            ("description",380,  "Descripción",   "w"),
            ("action",     280,  "Acción sugerida","w"),
        ]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, minwidth=width, anchor=anchor)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Tags de severidad — fila completa coloreada
        self.tree.tag_configure("critical", background="#1a0810", foreground=RED)
        self.tree.tag_configure("warning",  background="#1a1208", foreground=YELLOW)
        self.tree.tag_configure("info",     background="#081418", foreground=CYAN)

        # ── Panel de detalle ───────────────────────────────────────────────────
        det_outer = tk.Frame(root_bg, bg=BG)
        det_outer.pack(fill="x", padx=16, pady=(8, 12))

        # Borde izquierdo de color dinámico
        self._det_border = tk.Frame(det_outer, bg=SUBTEXT, width=3)
        self._det_border.pack(side="left", fill="y")

        det_inner = tk.Frame(det_outer, bg=CARD)
        det_inner.pack(side="left", fill="both", expand=True)

        det_hdr = tk.Frame(det_inner, bg=CARD)
        det_hdr.pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(det_hdr, text="DETALLE DEL CÓDIGO", bg=CARD,
                 fg=SUBTEXT, font=("Consolas", 7, "bold")).pack(side="left")

        self.detail_text = tk.Text(det_inner, height=5,
                                   bg=CARD, fg=TEXT,
                                   font=("Consolas", 9), relief="flat",
                                   wrap="word", state="disabled",
                                   padx=10, pady=6,
                                   insertbackground=ACCENT2,
                                   selectbackground=ACCENT,
                                   cursor="arrow")
        self.detail_text.pack(fill="x")

        # Paleta de colores semánticos dentro del Text
        self.detail_text.tag_configure("key",      foreground=SUBTEXT)
        self.detail_text.tag_configure("critical", foreground=RED)
        self.detail_text.tag_configure("warning",  foreground=YELLOW)
        self.detail_text.tag_configure("info",     foreground=CYAN)
        self.detail_text.tag_configure("value",    foreground=TEXT)
        self.detail_text.tag_configure("accent",   foreground=ACCENT2)

    # ── KB ──────────────────────────────────────────────────────────────────────

    def _enrich_dtc(self, code: str) -> dict:
        if self._kb is None:
            return {}
        try:
            if hasattr(self._kb, "lookup_dtc"):
                return self._kb.lookup_dtc(code) or {}
            return self._kb.lookup(code) or {}
        except Exception:
            return {}

    # ── Scan ────────────────────────────────────────────────────────────────────

    def _scan(self):
        self._status_var.set("Escaneando…")
        self._status_lbl.config(fg=YELLOW)
        self._progress.start()
        self._scan_btn.configure_state = lambda s: None  # disable visual

        def do_scan():
            try:
                if getattr(self.app, "demo", True):
                    time.sleep(0.9)
                    enriched = []
                    for d in _DEMO_DTCS:
                        info = self._enrich_dtc(d["code"]) or {}
                        enriched.append({**d, **{k: v for k, v in info.items() if v}})
                    dtcs = enriched
                else:
                    from ..comm.vehicle_conn import VehicleConnection
                    from ..diagnostic.diagnostic_engine import DiagnosticEngine
                    conn = VehicleConnection()
                    conn.connect(port=self.port_var.get())
                    engine = DiagnosticEngine(conn)
                    report = engine.full_scan()
                    dtcs = []
                    for d in report.dtcs:
                        info = self._enrich_dtc(d.code) or {}
                        dtcs.append({"code": d.code, **info})
                self.after(0, lambda: self._populate(dtcs))
            except Exception as e:
                self.after(0, lambda: self._scan_error(str(e)))

        threading.Thread(target=do_scan, daemon=True).start()

    def _populate(self, dtcs):
        self._dtcs = dtcs
        self._progress.stop()

        for row in self.tree.get_children():
            self.tree.delete(row)

        critical = sum(1 for d in dtcs if d.get("severity") == "critical")
        warnings = sum(1 for d in dtcs if d.get("severity") == "warning")

        for d in dtcs:
            sev  = d.get("severity", "info")
            icon = {"critical": "●", "warning": "◆", "info": "○"}.get(sev, "·")
            self.tree.insert("", "end", values=(
                icon,
                d.get("code", ""),
                d.get("system", ""),
                d.get("description", ""),
                d.get("suggested_action") or d.get("real_solution") or "",
            ), tags=(sev,))

        count = len(dtcs)
        self._card_total.update_value(str(count), ACCENT2)
        self._card_critical.update_value(str(critical),
                                         RED if critical else GREEN)
        self._card_warning.update_value(str(warnings),
                                        YELLOW if warnings else GREEN)

        # Health score básico
        health = max(0, 100 - critical * 25 - warnings * 10)
        hcolor = GREEN if health >= 70 else (YELLOW if health >= 40 else RED)
        self._card_health.update_value(str(health), hcolor)

        self._count_lbl.config(
            text=f"{count} código{'s' if count != 1 else ''} encontrado{'s' if count != 1 else ''}")
        self._status_var.set(f"Escaneo completo — {count} DTC(s)")
        self._status_lbl.config(fg=GREEN if count == 0 else RED)
        self.app.set_status(f"Escaneo completo — {count} código(s) encontrado(s)")

    def _scan_error(self, msg):
        self._progress.stop()
        self._status_var.set("Error de escaneo")
        self._status_lbl.config(fg=RED)
        messagebox.showerror("Error de escaneo", msg)

    # ── Detalle ─────────────────────────────────────────────────────────────────

    def _on_select(self, _):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0])["values"]
        if not vals:
            return
        _, code, system, desc, action = vals
        code = str(code)

        # Color del borde según severidad del item seleccionado
        tags = self.tree.item(sel[0], "tags")
        sev  = tags[0] if tags else ""
        self._det_border.config(bg=SEVERITY_COLOR.get(sev, SUBTEXT))

        info = self._enrich_dtc(code) or {}

        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", "end")

        def w(label, value, tag="value"):
            self.detail_text.insert("end", f"  {label:<14}", "key")
            self.detail_text.insert("end", f"{value}\n", tag)

        sev_tag = sev if sev in ("critical", "warning", "info") else "value"
        w("Código",       code,   "accent")
        w("Sistema",      system)
        w("Severidad",    sev.upper() if sev else "—", sev_tag)
        w("Descripción",  desc)

        if info.get("technical_diagnosis"):
            td = info["technical_diagnosis"]
            w("Diagnóstico",  td[:200] + ("…" if len(td) > 200 else ""))
        if info.get("real_solution"):
            rs = info["real_solution"]
            w("Solución",     rs[:200] + ("…" if len(rs) > 200 else ""))
        elif action:
            w("Acción",       str(action))
        if info.get("probable_causes"):
            causes = info["probable_causes"]
            if isinstance(causes, list):
                causes = ", ".join(str(c) for c in causes[:3])
            w("Causas",       str(causes)[:200])

        self.detail_text.config(state="disabled")

    # ── Reparación ──────────────────────────────────────────────────────────────

    def _show_repair_guide(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Guía", "Selecciona un DTC de la lista primero.")
            return
        code = str(self.tree.item(sel[0])["values"][1])
        self._open_repair_guide_window(code)

    def _open_repair_guide_window(self, code: str):
        win = tk.Toplevel(self)
        win.title(f"Guía de Reparación — {code}")
        win.configure(bg=BG)
        win.geometry("720x560")

        # Header
        hdr = tk.Frame(win, bg=SURFACE)
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=ACCENT, height=3).pack(fill="x")
        tk.Label(hdr, text=f"  GUÍA DE REPARACIÓN  ·  {code}",
                 bg=SURFACE, fg=TEXT,
                 font=("Consolas", 11, "bold"),
                 pady=10).pack(side="left")

        txt = scrolledtext.ScrolledText(
            win, bg=CARD, fg=TEXT,
            font=("Consolas", 9), relief="flat", wrap="word",
            padx=16, pady=12)
        txt.pack(fill="both", expand=True, padx=12, pady=12)
        txt.insert("end", "Cargando guía…")
        txt.config(state="disabled")

        def load():
            guide = self._get_repair_guide(code)
            def update():
                txt.config(state="normal")
                txt.delete("1.0", "end")
                txt.insert("end", guide)
                txt.config(state="disabled")
            win.after(0, update)

        threading.Thread(target=load, daemon=True).start()

    def _get_repair_guide(self, code: str) -> str:
        try:
            bc = getattr(self.app, "backend_client", None)
            if bc and bc.is_online():
                guide = bc.get_repair_guide(code)
                if guide:
                    return guide
        except Exception:
            pass

        if self._kb and hasattr(self._kb, "get_repair_guide"):
            try:
                return self._kb.get_repair_guide(code)
            except Exception:
                pass

        info = self._enrich_dtc(code)
        if not info:
            return f"No se encontró información para {code} en la base de conocimiento."

        lines = [f"═══ GUÍA DE REPARACIÓN: {code} ═══\n"]
        if info.get("description"):
            lines.append(f"DESCRIPCIÓN\n  {info['description']}\n")
        if info.get("system"):
            lines.append(f"SISTEMA: {info['system']}   SEVERIDAD: {info.get('severity','?').upper()}\n")
        if info.get("symptoms"):
            lines.append("SÍNTOMAS")
            for s in (info["symptoms"] if isinstance(info["symptoms"], list) else [info["symptoms"]]):
                lines.append(f"  • {s}")
            lines.append("")
        if info.get("technical_diagnosis") or info.get("suggested_action"):
            lines.append("DIAGNÓSTICO TÉCNICO")
            lines.append(f"  {info.get('technical_diagnosis') or info.get('suggested_action','')}\n")
        if info.get("real_solution"):
            lines.append("SOLUCIÓN")
            lines.append(f"  {info['real_solution']}\n")
        if info.get("probable_causes"):
            lines.append("CAUSAS PROBABLES")
            causes = info["probable_causes"] if isinstance(info["probable_causes"], list) else [info["probable_causes"]]
            for c in causes:
                lines.append(f"  • {c}")
            lines.append("")
        if info.get("tools_needed"):
            lines.append("HERRAMIENTAS")
            tools = info["tools_needed"] if isinstance(info["tools_needed"], list) else [info["tools_needed"]]
            for t in tools:
                lines.append(f"  • {t}")
            lines.append("")
        if info.get("estimated_time_hours"):
            lines.append(f"TIEMPO ESTIMADO: {info['estimated_time_hours']} hora(s)")
        cost = info.get("estimated_cost_usd") or {}
        if isinstance(cost, dict) and cost:
            lines.append(f"COSTO ESTIMADO: ${cost.get('parts_min',0)}–${cost.get('parts_max',0)} USD partes  |  Mano de obra: ${cost.get('labor',0)} USD")

        return "\n".join(lines)

    # ── Limpiar / Exportar ──────────────────────────────────────────────────────

    def _clear_dtcs(self):
        if not messagebox.askyesno("Confirmar", "¿Borrar todos los DTCs del vehículo?"):
            return
        for row in self.tree.get_children():
            self.tree.delete(row)
        self._dtcs = []
        for card in [self._card_total, self._card_critical,
                     self._card_warning, self._card_health]:
            card.update_value("0", GREEN)
        self._count_lbl.config(text="0 códigos")
        self._status_var.set("DTCs borrados")
        self._status_lbl.config(fg=GREEN)
        self.app.set_status("DTCs borrados (demo).")

    def _export(self):
        if not self._dtcs:
            messagebox.showinfo("Exportar", "No hay DTCs para exportar.")
            return
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = f"diagnostico_{ts}.txt"
        lines = [
            f"SCANER SOLER PRO — Reporte de Diagnóstico",
            f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 90,
            f"{'Código':<10} {'Severidad':<10} {'Sistema':<22} Descripción",
            "-" * 90,
        ]
        for d in self._dtcs:
            lines.append(
                f"{d.get('code',''):<10} {d.get('severity',''):<10} "
                f"{d.get('system',''):<22} {d.get('description','')}")
            if d.get("suggested_action") or d.get("real_solution"):
                lines.append(f"{'':>10}  Acción: {d.get('suggested_action') or d.get('real_solution','')}")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        messagebox.showinfo("Exportado", f"Guardado en {path}")
