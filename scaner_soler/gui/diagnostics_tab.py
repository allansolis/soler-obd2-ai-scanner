"""
Tab 1 — Diagnósticos: escaneo DTC, freeze frame, guía de reparación.
"""
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime

DARK_BG   = "#1e1e2e"
ENTRY_BG  = "#313244"
FG        = "#cdd6f4"
ACCENT    = "#89b4fa"
RED       = "#f38ba8"
YELLOW    = "#f9e2af"
GREEN     = "#a6e3a1"

SEVERITY_COLOR = {"critical": RED, "warning": YELLOW, "info": GREEN, "": FG}

_DEMO_DTCS = [
    {"code": "P0300", "description": "Random/Multiple Cylinder Misfire", "system": "Ignition System",
     "severity": "critical", "suggested_action": "Revisar bujías, bobinas e inyectores.", "source": "generic"},
    {"code": "P0171", "description": "System Too Lean Bank 1",           "system": "Fuel System",
     "severity": "critical", "suggested_action": "Revisar MAF, fugas de vacío, inyectores.", "source": "generic"},
    {"code": "P0420", "description": "Catalyst Efficiency Below Threshold","system": "Emissions",
     "severity": "warning",  "suggested_action": "Revisar catalizador y sondas O2.", "source": "generic"},
    {"code": "P1259", "description": "Sistema VTEC banco 1 — mal funcionamiento", "system": "VTEC",
     "severity": "critical", "suggested_action": "Verificar presión de aceite y solenoide VTEC.", "source": "Honda specific"},
]


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
        self.app   = app
        self._dtcs = []
        self._kb   = None
        self._build()
        # Load KB lazily in background
        threading.Thread(target=self._load_kb, daemon=True).start()

    def _load_kb(self):
        self._kb = _get_unified_kb()

    def _build(self):
        # ── Top controls ────────────────────────────────────────────────────
        ctrl = ttk.Frame(self)
        ctrl.pack(fill="x", padx=10, pady=8)

        ttk.Label(ctrl, text="Puerto:").pack(side="left")
        self.port_var = tk.StringVar(value="COM3")
        ttk.Entry(ctrl, textvariable=self.port_var, width=8).pack(side="left", padx=(4, 12))

        ttk.Button(ctrl, text="⚡ Escanear",       style="Accent.TButton",
                   command=self._scan).pack(side="left", padx=4)
        ttk.Button(ctrl, text="📋 Guía de Reparación",
                   command=self._show_repair_guide).pack(side="left", padx=4)
        ttk.Button(ctrl, text="🗑️ Limpiar DTCs",   command=self._clear_dtcs).pack(side="left", padx=4)
        ttk.Button(ctrl, text="💾 Exportar",        command=self._export).pack(side="left", padx=4)

        self.scan_label = ttk.Label(ctrl, text="")
        self.scan_label.pack(side="right", padx=10)

        # ── DTC list ─────────────────────────────────────────────────────────
        lf = ttk.LabelFrame(self, text="Códigos de Falla (DTCs)")
        lf.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        cols = ("code", "severity", "system", "description", "action")
        self.tree = ttk.Treeview(lf, columns=cols, show="headings", selectmode="browse")
        for col, width, label in [
            ("code",         80, "Código"),
            ("severity",     80, "Severidad"),
            ("system",      140, "Sistema"),
            ("description", 300, "Descripción"),
            ("action",      260, "Acción sugerida"),
        ]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, minwidth=60)

        vsb = ttk.Scrollbar(lf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # ── Detail panel ─────────────────────────────────────────────────────
        detail = ttk.LabelFrame(self, text="Detalle del código seleccionado")
        detail.pack(fill="x", padx=10, pady=(0, 8))

        self.detail_text = tk.Text(detail, height=7, bg=ENTRY_BG, fg=FG,
                                   font=("Consolas", 10), relief="flat",
                                   wrap="word", state="disabled")
        self.detail_text.pack(fill="x", padx=6, pady=4)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _scan(self):
        self.scan_label.config(text="Escaneando…", foreground=YELLOW)
        self.app.set_status("Escaneo en progreso…")

        def do_scan():
            try:
                if self.app.demo:
                    import time; time.sleep(0.8)
                    # Enrich demo DTCs with KB data
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

    def _enrich_dtc(self, code: str) -> dict:
        """Look up DTC in unified KB or DTCDatabase."""
        if self._kb is None:
            return {}
        try:
            if hasattr(self._kb, "lookup_dtc"):
                return self._kb.lookup_dtc(code)
            return self._kb.lookup(code)
        except Exception:
            return {}

    def _populate(self, dtcs):
        self._dtcs = dtcs
        for row in self.tree.get_children():
            self.tree.delete(row)
        for d in dtcs:
            sev   = d.get("severity", "info")
            color = SEVERITY_COLOR.get(sev, FG)
            tag   = f"sev_{sev}"
            self.tree.insert("", "end", values=(
                d.get("code", ""),
                sev.upper(),
                d.get("system", ""),
                d.get("description", ""),
                d.get("suggested_action", d.get("real_solution", d.get("fix_hint", ""))),
            ), tags=(tag,))
            self.tree.tag_configure(tag, foreground=color)

        count = len(dtcs)
        self.scan_label.config(text=f"✓ {count} DTC{'s' if count != 1 else ''}", foreground=GREEN)
        self.app.set_status(f"Escaneo completo — {count} código(s) encontrado(s)")

    def _scan_error(self, msg):
        self.scan_label.config(text="Error", foreground=RED)
        messagebox.showerror("Error de escaneo", msg)

    def _show_repair_guide(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Guía", "Selecciona un DTC de la lista primero.")
            return
        code = self.tree.item(sel[0])["values"][0]
        self._open_repair_guide_window(code)

    def _open_repair_guide_window(self, code: str):
        win = tk.Toplevel(self)
        win.title(f"Guía de Reparación — {code}")
        win.configure(bg=DARK_BG)
        win.geometry("680x520")

        ttk.Label(win, text=f"🔧 Guía de Reparación: {code}",
                  font=("Segoe UI", 13, "bold")).pack(padx=12, pady=(10, 4), anchor="w")

        txt = scrolledtext.ScrolledText(win, bg=ENTRY_BG, fg=FG,
                                        font=("Consolas", 10), relief="flat", wrap="word")
        txt.pack(fill="both", expand=True, padx=12, pady=(0, 10))
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
        # Try backend client first
        try:
            bc = getattr(self.app, "backend_client", None)
            if bc and bc.is_online():
                guide = bc.get_repair_guide(code)
                if guide:
                    return guide
        except Exception:
            pass

        # Try unified KB
        if self._kb and hasattr(self._kb, "get_repair_guide"):
            try:
                return self._kb.get_repair_guide(code)
            except Exception:
                pass

        # Fallback: build from lookup data
        info = self._enrich_dtc(code)
        if not info:
            return f"No se encontró información para {code} en la base de conocimiento."

        lines = [f"=== GUÍA DE REPARACIÓN: {code} ===\n"]
        if info.get("description"):
            lines.append(f"DESCRIPCIÓN:\n  {info['description']}\n")
        if info.get("system"):
            lines.append(f"SISTEMA: {info['system']}   SEVERIDAD: {info.get('severity','?').upper()}\n")
        if info.get("symptoms"):
            lines.append("SÍNTOMAS:")
            for s in (info["symptoms"] if isinstance(info["symptoms"], list) else [info["symptoms"]]):
                lines.append(f"  • {s}")
            lines.append("")
        if info.get("technical_diagnosis") or info.get("suggested_action"):
            lines.append("DIAGNÓSTICO TÉCNICO:")
            lines.append(f"  {info.get('technical_diagnosis') or info.get('suggested_action','')}\n")
        if info.get("real_solution"):
            lines.append("SOLUCIÓN:")
            lines.append(f"  {info['real_solution']}\n")
        if info.get("probable_causes"):
            lines.append("CAUSAS PROBABLES:")
            causes = info["probable_causes"] if isinstance(info["probable_causes"], list) else [info["probable_causes"]]
            for c in causes:
                lines.append(f"  • {c}")
            lines.append("")
        if info.get("tools_needed"):
            lines.append("HERRAMIENTAS NECESARIAS:")
            tools = info["tools_needed"] if isinstance(info["tools_needed"], list) else [info["tools_needed"]]
            for t in tools:
                lines.append(f"  • {t}")
            lines.append("")
        if info.get("estimated_time_hours"):
            lines.append(f"TIEMPO ESTIMADO: {info['estimated_time_hours']} hora(s)")
        cost = info.get("estimated_cost_usd") or {}
        if isinstance(cost, dict) and cost:
            lines.append(f"COSTO ESTIMADO: Piezas ${cost.get('parts_min',0)}–${cost.get('parts_max',0)} USD  |  Mano de obra: ${cost.get('labor',0)} USD")

        return "\n".join(lines)

    def _clear_dtcs(self):
        if not messagebox.askyesno("Confirmar", "¿Borrar todos los DTCs del vehículo?"):
            return
        self.app.set_status("DTCs borrados (demo).")

    def _export(self):
        if not self._dtcs:
            messagebox.showinfo("Exportar", "No hay DTCs para exportar.")
            return
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = f"diagnostico_{ts}.txt"
        lines = [
            f"{'Código':<10} {'Severidad':<10} {'Sistema':<22} {'Descripción'}",
            "-" * 90,
        ]
        for d in self._dtcs:
            lines.append(
                f"{d.get('code',''):<10} {d.get('severity',''):<10} "
                f"{d.get('system',''):<22} {d.get('description','')}"
            )
            if d.get("suggested_action") or d.get("real_solution"):
                lines.append(f"{'':>10}  Acción: {d.get('suggested_action') or d.get('real_solution','')}")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        messagebox.showinfo("Exportado", f"Guardado en {path}")

    def _on_select(self, _):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0])["values"]
        if not vals:
            return
        code, sev, system, desc, action = vals

        # Build enriched detail
        info = self._enrich_dtc(str(code)) or {}
        lines = [
            f"Código:      {code}",
            f"Sistema:     {system}",
            f"Severidad:   {sev}",
            f"Descripción: {desc}",
        ]
        if info.get("technical_diagnosis"):
            lines.append(f"\nDiagnóstico: {info['technical_diagnosis'][:200]}{'…' if len(info.get('technical_diagnosis',''))>200 else ''}")
        if info.get("real_solution"):
            lines.append(f"Solución:    {info['real_solution'][:200]}{'…' if len(info.get('real_solution',''))>200 else ''}")
        elif action:
            lines.append(f"Acción:      {action}")
        if info.get("probable_causes"):
            causes = info["probable_causes"] if isinstance(info["probable_causes"], list) else [info["probable_causes"]]
            lines.append(f"Causas:      {', '.join(str(c) for c in causes[:3])}")

        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", "\n".join(lines))
        self.detail_text.config(state="disabled")
