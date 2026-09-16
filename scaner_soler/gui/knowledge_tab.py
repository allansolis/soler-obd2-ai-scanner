"""
Tab 6 — Base de Conocimiento ECU: búsqueda de fallas, pinouts, DTCs, herramientas.
"""
import threading
import tkinter as tk
from tkinter import ttk

DARK_BG  = "#1e1e2e"
ENTRY_BG = "#313244"
FG       = "#cdd6f4"
ACCENT   = "#89b4fa"
GREEN    = "#a6e3a1"
RED      = "#f38ba8"
YELLOW   = "#f9e2af"

MAKES = [
    "(todas)", "fiat", "peugeot_citroen", "ford", "renault",
    "volkswagen", "hyundai", "generic",
    "VAG specific", "BMW specific", "Toyota specific", "Honda specific",
    "Renault specific", "Fiat specific",
]


class KnowledgeTab(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app  = app
        self._db  = None
        self._ukb = None
        self._build()
        threading.Thread(target=self._load_all, daemon=True).start()

    def _get_db(self):
        if self._db is None:
            from ..diagnostic.dtc_database import DTCDatabase
            self._db = DTCDatabase()
        return self._db

    def _get_ukb(self):
        if self._ukb is None:
            try:
                from ..knowledge.unified_kb import UnifiedKnowledgeBase
                self._ukb = UnifiedKnowledgeBase()
            except Exception:
                self._ukb = self._get_db()
        return self._ukb

    def _load_all(self):
        self.after(200, self._load_stats)

    def _build(self):
        # ── Search controls ──────────────────────────────────────────────────
        search_lf = ttk.LabelFrame(self, text="Buscar en base de conocimiento ECU")
        search_lf.pack(fill="x", padx=10, pady=8)

        row = ttk.Frame(search_lf)
        row.pack(fill="x", padx=8, pady=6)
        ttk.Label(row, text="Marca:").pack(side="left")
        self.make_var = tk.StringVar(value="(todas)")
        ttk.Combobox(row, textvariable=self.make_var, values=MAKES,
                     state="readonly", width=18).pack(side="left", padx=(4, 14))
        ttk.Label(row, text="Síntoma / clave:").pack(side="left")
        self.kw_var = tk.StringVar()
        kw_entry = ttk.Entry(row, textvariable=self.kw_var, width=28)
        kw_entry.pack(side="left", padx=(4, 10))
        kw_entry.bind("<Return>", lambda _: self._search())
        ttk.Button(row, text="🔍 Buscar ECU", style="Accent.TButton",
                   command=self._search).pack(side="left", padx=4)
        ttk.Button(row, text="Mostrar todo",
                   command=self._show_all).pack(side="left", padx=4)

        # DTC + herramientas quick-lookup
        dtc_row = ttk.Frame(search_lf)
        dtc_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(dtc_row, text="Código DTC:").pack(side="left")
        self.dtc_var = tk.StringVar()
        ttk.Entry(dtc_row, textvariable=self.dtc_var, width=10).pack(side="left", padx=(4, 6))
        ttk.Button(dtc_row, text="Consultar", command=self._lookup_dtc).pack(side="left")
        ttk.Label(dtc_row, text="  Herramienta:").pack(side="left", padx=(14, 0))
        self.tool_var = tk.StringVar()
        ttk.Entry(dtc_row, textvariable=self.tool_var, width=16).pack(side="left", padx=(4, 6))
        ttk.Button(dtc_row, text="Buscar herramientas", command=self._search_tools).pack(side="left")
        self.dtc_result = ttk.Label(dtc_row, text="", foreground=ACCENT, font=("Consolas", 9))
        self.dtc_result.pack(side="left", padx=8)

        # ── Results notebook ─────────────────────────────────────────────────
        self.result_nb = ttk.Notebook(self)
        self.result_nb.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        # — Faults —
        fault_frame = ttk.Frame(self.result_nb)
        self.result_nb.add(fault_frame, text="Fallas & Reparaciones")
        cols_f = ("make", "ecu", "symptom", "solution", "page")
        self.fault_tree = ttk.Treeview(fault_frame, columns=cols_f,
                                       show="headings", selectmode="browse")
        for col, w, label in [
            ("make",    100, "Marca"), ("ecu", 130, "Módulo ECU"),
            ("symptom", 270, "Síntoma"), ("solution", 270, "Solución"), ("page", 50, "Pág"),
        ]:
            self.fault_tree.heading(col, text=label)
            self.fault_tree.column(col, width=w, minwidth=40)
        vsb_f = ttk.Scrollbar(fault_frame, orient="vertical", command=self.fault_tree.yview)
        self.fault_tree.configure(yscrollcommand=vsb_f.set)
        self.fault_tree.pack(side="left", fill="both", expand=True)
        vsb_f.pack(side="right", fill="y")
        self.fault_tree.bind("<<TreeviewSelect>>", self._on_fault_select)

        # — Pinout —
        comp_frame = ttk.Frame(self.result_nb)
        self.result_nb.add(comp_frame, text="Pinout / Componentes")
        comp_top = ttk.Frame(comp_frame)
        comp_top.pack(fill="x", padx=8, pady=6)
        ttk.Label(comp_top, text="Módulo ECU:").pack(side="left")
        self.comp_ecu_var = tk.StringVar()
        ttk.Entry(comp_top, textvariable=self.comp_ecu_var, width=20).pack(side="left", padx=4)
        ttk.Button(comp_top, text="Buscar pinout", command=self._search_components).pack(side="left", padx=4)
        cols_c = ("pin", "description")
        self.comp_tree = ttk.Treeview(comp_frame, columns=cols_c, show="headings", selectmode="browse")
        self.comp_tree.heading("pin",         text="Pin / Nº")
        self.comp_tree.heading("description", text="Descripción del componente")
        self.comp_tree.column("pin",         width=70,  minwidth=40)
        self.comp_tree.column("description", width=600, minwidth=200)
        vsb_c = ttk.Scrollbar(comp_frame, orient="vertical", command=self.comp_tree.yview)
        self.comp_tree.configure(yscrollcommand=vsb_c.set)
        self.comp_tree.pack(side="left", fill="both", expand=True)
        vsb_c.pack(side="right", fill="y")

        # — Herramientas profesionales —
        tools_frame = ttk.Frame(self.result_nb)
        self.result_nb.add(tools_frame, text="Herramientas Pro")
        cols_t = ("name", "category", "brands", "price", "publisher")
        self.tools_tree = ttk.Treeview(tools_frame, columns=cols_t,
                                       show="headings", selectmode="browse")
        for col, w, label in [
            ("name",      180, "Herramienta"), ("category", 120, "Categoría"),
            ("brands",    160, "Marcas"),       ("price",    100, "Precio"),
            ("publisher", 160, "Fabricante"),
        ]:
            self.tools_tree.heading(col, text=label)
            self.tools_tree.column(col, width=w, minwidth=60)
        vsb_t = ttk.Scrollbar(tools_frame, orient="vertical", command=self.tools_tree.yview)
        self.tools_tree.configure(yscrollcommand=vsb_t.set)
        self.tools_tree.pack(side="left", fill="both", expand=True)
        vsb_t.pack(side="right", fill="y")
        self.tools_tree.bind("<<TreeviewSelect>>", self._on_tool_select)

        # — Estadísticas —
        stats_frame = ttk.Frame(self.result_nb)
        self.result_nb.add(stats_frame, text="Estadísticas KB")
        self.stats_text = tk.Text(stats_frame, bg=ENTRY_BG, fg=FG,
                                  font=("Consolas", 10), relief="flat", state="disabled")
        self.stats_text.pack(fill="both", expand=True, padx=6, pady=6)

        # ── Detail panel ─────────────────────────────────────────────────────
        detail_frame = ttk.Frame(self)
        detail_frame.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Label(detail_frame, text="Detalle:").pack(anchor="w")
        self.detail_text = tk.Text(detail_frame, height=4, bg=ENTRY_BG, fg=FG,
                                   font=("Consolas", 9), relief="flat",
                                   wrap="word", state="disabled")
        self.detail_text.pack(fill="x")

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_stats(self):
        try:
            db    = self._get_db()
            stats = db.ecu_stats()
            ukb   = self._get_ukb()
            dtc_total = 0
            tool_count = 0
            try:
                import sqlite3
                from pathlib import Path
                dbp = Path(__file__).parent.parent / "database" / "dtc_codes.db"
                con = sqlite3.connect(str(dbp))
                dtc_total = con.execute("SELECT COUNT(*) FROM dtc_codes").fetchone()[0]
                try:
                    tool_count = con.execute("SELECT COUNT(*) FROM expert_tools").fetchone()[0]
                except Exception:
                    pass
                con.close()
            except Exception:
                pass

            lines = [
                "=== BASE DE CONOCIMIENTO UNIFICADA — SCANER SOLER PRO ===\n",
                f"  Módulos ECU indexados  : {stats.get('models', 0)}",
                f"  Fallas con solución    : {stats.get('faults', 0)}",
                f"  Registros de pinout    : {stats.get('components', 0)}",
                f"  Códigos DTC totales    : {dtc_total}  (SAE J2012 + OEM específicos)",
                f"  Herramientas pro       : {tool_count}  (HP Tuners, WinOLS, ETKA, etc.)",
                f"\n  Fuentes:",
                f"    • Guia Completo de Reparo de ECUs 2025 (617 págs.)",
                f"    • SAE J2012 — OBD-II genérico (P0xxx/B/C/U)",
                f"    • Códigos OEM: VAG, BMW, Toyota, Honda, Renault, Fiat",
                f"    • Perfiles expertos: 28 herramientas profesionales",
                f"\n  Distribución ECU por marca:",
            ]
            for make, n in stats.get("by_make", {}).items():
                bar = "█" * min(n // 2, 25)
                lines.append(f"    {make:<22} {bar} {n}")

            self._write_stats("\n".join(lines))
            # Also load tools
            self.after(0, self._load_all_tools)
        except Exception as e:
            self._write_stats(f"Error cargando stats: {e}")

    def _load_all_tools(self):
        try:
            import sqlite3, json
            from pathlib import Path
            dbp = Path(__file__).parent.parent / "database" / "dtc_codes.db"
            con = sqlite3.connect(str(dbp))
            rows = con.execute(
                "SELECT name, category, brands, price_range, publisher FROM expert_tools ORDER BY category, name"
            ).fetchall()
            con.close()
            for row in self.tools_tree.get_children():
                self.tools_tree.delete(row)
            for r in rows:
                brands_raw = r[2] or "[]"
                try:
                    brands_list = json.loads(brands_raw)
                    brands_str = ", ".join(str(b) for b in brands_list[:3])
                    if len(brands_list) > 3:
                        brands_str += f"… +{len(brands_list)-3}"
                except Exception:
                    brands_str = str(brands_raw)[:40]
                self.tools_tree.insert("", "end", values=(
                    r[0], r[1] or "", brands_str, r[3] or "", r[4] or ""
                ))
        except Exception:
            pass

    def _write_stats(self, text: str):
        self.stats_text.config(state="normal")
        self.stats_text.delete("1.0", "end")
        self.stats_text.insert("1.0", text)
        self.stats_text.config(state="disabled")

    def _write_detail(self, text: str):
        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)
        self.detail_text.config(state="disabled")

    # ── Search actions ────────────────────────────────────────────────────────

    def _search(self):
        make = self.make_var.get()
        kw   = self.kw_var.get().strip()
        if make == "(todas)":
            make = ""
        db      = self._get_db()
        results = db.search_ecu_faults(make=make, keyword=kw)
        self._populate_faults(results)
        self.app.set_status(f"{len(results)} resultado(s) en fallas ECU")
        self.result_nb.select(0)

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
        self._write_detail(
            f"Marca: {make}  |  Módulo: {ecu}  |  Página: {page}\n"
            f"Falla:    {symptom}\n"
            f"Solución: {solution}"
        )

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
        self.result_nb.select(1)

    def _lookup_dtc(self):
        code = self.dtc_var.get().strip().upper()
        if not code:
            return
        ukb = self._get_ukb()
        try:
            if hasattr(ukb, "lookup_dtc"):
                res = ukb.lookup_dtc(code)
            else:
                res = ukb.lookup(code)
        except Exception as e:
            res = {"code": code, "description": f"Error: {e}", "severity": "info"}
        desc = res.get("description", "")
        sev  = res.get("severity", "?").upper()
        sol  = res.get("real_solution") or res.get("suggested_action") or res.get("fix_hint", "")
        self.dtc_result.config(text=f"{desc[:80]} [{sev}]")
        if sol:
            self._write_detail(
                f"Código: {code}  |  {sev}\n"
                f"Descripción: {desc}\n"
                f"Acción: {sol[:200]}"
            )

    def _search_tools(self):
        query = self.tool_var.get().strip().lower()
        self.result_nb.select(2)
        try:
            import sqlite3, json
            from pathlib import Path
            dbp = Path(__file__).parent.parent / "database" / "dtc_codes.db"
            con = sqlite3.connect(str(dbp))
            rows = con.execute(
                "SELECT name, category, brands, price_range, publisher, description, use_cases "
                "FROM expert_tools WHERE LOWER(name) LIKE ? OR LOWER(brands) LIKE ? "
                "OR LOWER(category) LIKE ? OR LOWER(description) LIKE ?",
                (f"%{query}%",) * 4
            ).fetchall()
            con.close()
            for row in self.tools_tree.get_children():
                self.tools_tree.delete(row)
            for r in rows:
                try:
                    brands_list = json.loads(r[2] or "[]")
                    brands_str = ", ".join(str(b) for b in brands_list[:3])
                    if len(brands_list) > 3:
                        brands_str += f"…+{len(brands_list)-3}"
                except Exception:
                    brands_str = str(r[2] or "")[:40]
                self.tools_tree.insert("", "end", values=(r[0], r[1] or "", brands_str, r[3] or "", r[4] or ""))
            self.app.set_status(f"{len(rows)} herramienta(s) encontrada(s)")
        except Exception as e:
            self.app.set_status(f"Error buscando herramientas: {e}")

    def _on_tool_select(self, _):
        sel = self.tools_tree.selection()
        if not sel:
            return
        name = self.tools_tree.item(sel[0])["values"][0]
        try:
            import sqlite3, json
            from pathlib import Path
            dbp = Path(__file__).parent.parent / "database" / "dtc_codes.db"
            con = sqlite3.connect(str(dbp))
            row = con.execute(
                "SELECT description, use_cases, strengths, limitations, official_url "
                "FROM expert_tools WHERE name=?", (name,)
            ).fetchone()
            con.close()
            if row:
                use_cases = json.loads(row[1] or "[]") if row[1] else []
                strengths = json.loads(row[2] or "[]") if row[2] else []
                lines = [
                    f"Herramienta: {name}",
                    f"Descripción: {row[0] or ''}",
                ]
                if use_cases:
                    lines.append(f"Casos de uso: {', '.join(str(u) for u in use_cases[:4])}")
                if strengths:
                    lines.append(f"Ventajas: {', '.join(str(s) for s in strengths[:3])}")
                if row[4]:
                    lines.append(f"URL: {row[4]}")
                self._write_detail("\n".join(lines))
        except Exception:
            pass
