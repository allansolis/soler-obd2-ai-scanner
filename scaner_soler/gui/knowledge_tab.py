"""
Tab 6 — Base de Conocimiento ECU: búsqueda de fallas, pinouts, DTCs.
"""
import tkinter as tk
from tkinter import ttk

DARK_BG  = "#1e1e2e"
ENTRY_BG = "#313244"
FG       = "#cdd6f4"
ACCENT   = "#89b4fa"
GREEN    = "#a6e3a1"
RED      = "#f38ba8"
YELLOW   = "#f9e2af"

MAKES = ["(todas)", "fiat", "peugeot_citroen", "ford", "renault", "volkswagen", "hyundai", "generic"]


class KnowledgeTab(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._db = None
        self._build()
        self._load_stats()

    def _get_db(self):
        if self._db is None:
            from ..diagnostic.dtc_database import DTCDatabase
            self._db = DTCDatabase()
        return self._db

    def _build(self):
        # Top: search controls
        search_lf = ttk.LabelFrame(self, text="Buscar en base de conocimiento ECU")
        search_lf.pack(fill="x", padx=10, pady=8)

        row = ttk.Frame(search_lf)
        row.pack(fill="x", padx=8, pady=6)

        ttk.Label(row, text="Marca:").pack(side="left")
        self.make_var = tk.StringVar(value="(todas)")
        ttk.Combobox(row, textvariable=self.make_var, values=MAKES,
                     state="readonly", width=18).pack(side="left", padx=(4, 14))

        ttk.Label(row, text="Síntoma / palabra clave:").pack(side="left")
        self.kw_var = tk.StringVar()
        kw_entry = ttk.Entry(row, textvariable=self.kw_var, width=30)
        kw_entry.pack(side="left", padx=(4, 10))
        kw_entry.bind("<Return>", lambda _: self._search())

        ttk.Button(row, text="🔍 Buscar",  style="Accent.TButton",
                   command=self._search).pack(side="left", padx=4)
        ttk.Button(row, text="Mostrar todo",
                   command=self._show_all).pack(side="left", padx=4)

        # DTC quick-lookup row
        dtc_row = ttk.Frame(search_lf)
        dtc_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(dtc_row, text="Lookup DTC:").pack(side="left")
        self.dtc_var = tk.StringVar()
        ttk.Entry(dtc_row, textvariable=self.dtc_var, width=10).pack(side="left", padx=(4, 6))
        ttk.Button(dtc_row, text="Consultar", command=self._lookup_dtc).pack(side="left")
        self.dtc_result = ttk.Label(dtc_row, text="", foreground=ACCENT,
                                    font=("Consolas", 9))
        self.dtc_result.pack(side="left", padx=10)

        # Results notebook (faults vs components)
        self.result_nb = ttk.Notebook(self)
        self.result_nb.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        # — Faults tab —
        fault_frame = ttk.Frame(self.result_nb)
        self.result_nb.add(fault_frame, text="Fallas & Reparaciones")

        cols_f = ("make", "ecu", "symptom", "solution", "page")
        self.fault_tree = ttk.Treeview(fault_frame, columns=cols_f,
                                       show="headings", selectmode="browse")
        for col, w, label in [
            ("make",    110, "Marca"),
            ("ecu",     130, "Módulo ECU"),
            ("symptom", 280, "Síntoma"),
            ("solution",280, "Solución"),
            ("page",     50, "Pág"),
        ]:
            self.fault_tree.heading(col, text=label)
            self.fault_tree.column(col, width=w, minwidth=40)

        vsb_f = ttk.Scrollbar(fault_frame, orient="vertical",
                               command=self.fault_tree.yview)
        self.fault_tree.configure(yscrollcommand=vsb_f.set)
        self.fault_tree.pack(side="left", fill="both", expand=True)
        vsb_f.pack(side="right", fill="y")
        self.fault_tree.bind("<<TreeviewSelect>>", self._on_fault_select)

        # Detail text under fault tree
        self.fault_detail = tk.Text(fault_frame, height=4, bg=ENTRY_BG, fg=FG,
                                    font=("Consolas", 9), relief="flat",
                                    wrap="word", state="disabled")
        # (packed after tree in same frame via separate sub-frame)
        detail_frame = ttk.Frame(self)
        detail_frame.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Label(detail_frame, text="Detalle:").pack(anchor="w")
        self.fault_detail2 = tk.Text(detail_frame, height=4, bg=ENTRY_BG, fg=FG,
                                     font=("Consolas", 9), relief="flat",
                                     wrap="word", state="disabled")
        self.fault_detail2.pack(fill="x")

        # — Components tab —
        comp_frame = ttk.Frame(self.result_nb)
        self.result_nb.add(comp_frame, text="Componentes / Pinout")

        comp_top = ttk.Frame(comp_frame)
        comp_top.pack(fill="x", padx=8, pady=6)
        ttk.Label(comp_top, text="Módulo ECU:").pack(side="left")
        self.comp_ecu_var = tk.StringVar()
        ttk.Entry(comp_top, textvariable=self.comp_ecu_var, width=20).pack(side="left", padx=4)
        ttk.Button(comp_top, text="Buscar pinout",
                   command=self._search_components).pack(side="left", padx=4)

        cols_c = ("pin", "description")
        self.comp_tree = ttk.Treeview(comp_frame, columns=cols_c,
                                      show="headings", selectmode="browse")
        self.comp_tree.heading("pin",         text="Pin / Nº")
        self.comp_tree.heading("description", text="Descripción del componente")
        self.comp_tree.column("pin",         width=70,  minwidth=40)
        self.comp_tree.column("description", width=600, minwidth=200)

        vsb_c = ttk.Scrollbar(comp_frame, orient="vertical",
                               command=self.comp_tree.yview)
        self.comp_tree.configure(yscrollcommand=vsb_c.set)
        self.comp_tree.pack(side="left", fill="both", expand=True)
        vsb_c.pack(side="right", fill="y")

        # — Stats tab —
        stats_frame = ttk.Frame(self.result_nb)
        self.result_nb.add(stats_frame, text="Estadísticas KB")
        self.stats_text = tk.Text(stats_frame, bg=ENTRY_BG, fg=FG,
                                  font=("Consolas", 10), relief="flat",
                                  state="disabled")
        self.stats_text.pack(fill="both", expand=True, padx=6, pady=6)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _load_stats(self):
        try:
            db    = self._get_db()
            stats = db.ecu_stats()
            lines = [
                "=== BASE DE CONOCIMIENTO SCANER SOLER PRO ===\n",
                f"  Módulos ECU indexados : {stats.get('models', 0)}",
                f"  Fallas con solución   : {stats.get('faults', 0)}",
                f"  Registros de pinout   : {stats.get('components', 0)}",
                f"  Fuente: Guia Completo de Reparo de ECUs 2025 (617 págs.)\n",
                "  Distribución por marca:",
            ]
            for make, n in stats.get("by_make", {}).items():
                bar = "█" * (n // 2) + " " * (20 - n // 2)
                lines.append(f"    {make:<20} {bar} {n}")

            dtcs = len(db.search(""))
            lines += ["", f"  DTCs OBD-II genéricos  : {dtcs}",
                      "  Extensión OEM          : VAG, BMW, Toyota, Honda, Ford"]
            self._write_stats("\n".join(lines))
        except Exception as e:
            self._write_stats(f"Error cargando stats: {e}")

    def _write_stats(self, text: str):
        self.stats_text.config(state="normal")
        self.stats_text.delete("1.0", "end")
        self.stats_text.insert("1.0", text)
        self.stats_text.config(state="disabled")

    def _search(self):
        make = self.make_var.get()
        kw   = self.kw_var.get().strip()
        if make == "(todas)":
            make = ""
        db      = self._get_db()
        results = db.search_ecu_faults(make=make, keyword=kw)
        self._populate_faults(results)
        self.app.set_status(f"{len(results)} resultado(s) encontrado(s)")

    def _show_all(self):
        db = self._get_db()
        self._populate_faults(db.search_ecu_faults())

    def _populate_faults(self, results: list):
        for row in self.fault_tree.get_children():
            self.fault_tree.delete(row)
        for r in results:
            self.fault_tree.insert("", "end", values=(
                r.get("make", ""),
                r.get("ecu",  ""),
                r.get("symptom",  "")[:120],
                r.get("solution", "")[:120],
                r.get("page", ""),
            ))

    def _on_fault_select(self, _):
        sel = self.fault_tree.selection()
        if not sel:
            return
        vals = self.fault_tree.item(sel[0])["values"]
        make, ecu, symptom, solution, page = vals
        text = (f"Marca:   {make}\nMódulo:  {ecu}\n"
                f"Falla:   {symptom}\nSolución:{solution}\nPágina: {page}")
        self.fault_detail2.config(state="normal")
        self.fault_detail2.delete("1.0", "end")
        self.fault_detail2.insert("1.0", text)
        self.fault_detail2.config(state="disabled")

    def _search_components(self):
        ecu = self.comp_ecu_var.get().strip()
        if not ecu:
            return
        db      = self._get_db()
        results = db.get_ecu_components(ecu)
        for row in self.comp_tree.get_children():
            self.comp_tree.delete(row)
        for r in results:
            self.comp_tree.insert("", "end", values=(r["pin"], r["description"]))
        self.app.set_status(f"{len(results)} componente(s) para '{ecu}'")

    def _lookup_dtc(self):
        code = self.dtc_var.get().strip().upper()
        if not code:
            return
        db  = self._get_db()
        res = db.lookup(code)
        txt = (f"{res['description']}  [{res.get('severity','?').upper()}]  "
               f"— {res.get('suggested_action', res.get('fix_hint',''))}")
        self.dtc_result.config(text=txt[:130])
