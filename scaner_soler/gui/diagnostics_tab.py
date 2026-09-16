"""
Tab 1 — Diagnósticos: escaneo DTC, freeze frame, acciones.
"""
import threading
import tkinter as tk
from tkinter import ttk, messagebox
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
]


class DiagnosticsTab(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app  = app
        self._dtcs = []
        self._build()

    def _build(self):
        # ── Top controls ────────────────────────────────────────────────────
        ctrl = ttk.Frame(self)
        ctrl.pack(fill="x", padx=10, pady=8)

        ttk.Label(ctrl, text="Puerto:").pack(side="left")
        self.port_var = tk.StringVar(value="COM3")
        ttk.Entry(ctrl, textvariable=self.port_var, width=8).pack(side="left", padx=(4, 12))

        ttk.Button(ctrl, text="⚡ Escanear",  style="Accent.TButton",
                   command=self._scan).pack(side="left", padx=4)
        ttk.Button(ctrl, text="🗑️ Limpiar DTCs", command=self._clear_dtcs).pack(side="left", padx=4)
        ttk.Button(ctrl, text="💾 Exportar",  command=self._export).pack(side="left", padx=4)

        self.scan_label = ttk.Label(ctrl, text="")
        self.scan_label.pack(side="right", padx=10)

        # ── DTC list ─────────────────────────────────────────────────────────
        lf = ttk.LabelFrame(self, text="Códigos de Falla (DTCs)")
        lf.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        cols = ("code", "severity", "system", "description", "action")
        self.tree = ttk.Treeview(lf, columns=cols, show="headings", selectmode="browse")
        for col, width, label in [
            ("code",        80,  "Código"),
            ("severity",    80,  "Severidad"),
            ("system",     140,  "Sistema"),
            ("description",280,  "Descripción"),
            ("action",     260,  "Acción sugerida"),
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

        self.detail_text = tk.Text(detail, height=5, bg=ENTRY_BG, fg=FG,
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
                    dtcs = _DEMO_DTCS
                else:
                    from ..comm.vehicle_conn import VehicleConnection
                    from ..diagnostic.diagnostic_engine import DiagnosticEngine
                    from ..diagnostic.dtc_database import DTCDatabase
                    db = DTCDatabase()
                    conn = VehicleConnection()
                    conn.connect(port=self.port_var.get())
                    engine = DiagnosticEngine(conn)
                    report = engine.full_scan()
                    dtcs = [db.lookup(d.code) | {"code": d.code} for d in report.dtcs]

                self.after(0, lambda: self._populate(dtcs))
            except Exception as e:
                self.after(0, lambda: self._scan_error(str(e)))

        threading.Thread(target=do_scan, daemon=True).start()

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
                d.get("suggested_action", d.get("fix_hint", "")),
            ), tags=(tag,))
            self.tree.tag_configure(tag, foreground=color)

        count = len(dtcs)
        self.scan_label.config(text=f"✓ {count} DTC{'s' if count != 1 else ''}", foreground=GREEN)
        self.app.set_status(f"Escaneo completo — {count} código(s) encontrado(s)")

    def _scan_error(self, msg):
        self.scan_label.config(text="Error", foreground=RED)
        messagebox.showerror("Error de escaneo", msg)

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
        lines = [f"{'Código':<10} {'Severidad':<10} {'Sistema':<22} {'Descripción'}\n" + "-" * 80]
        for d in self._dtcs:
            lines.append(f"{d.get('code',''):<10} {d.get('severity',''):<10} {d.get('system',''):<22} {d.get('description','')}")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        messagebox.showinfo("Exportado", f"Guardado en {path}")

    def _on_select(self, _):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0])["values"]
        code, sev, system, desc, action = vals
        text = (f"Código:   {code}\n"
                f"Sistema:  {system}\n"
                f"Severidad:{sev}\n"
                f"Descripción: {desc}\n"
                f"Acción:   {action}")
        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)
        self.detail_text.config(state="disabled")
