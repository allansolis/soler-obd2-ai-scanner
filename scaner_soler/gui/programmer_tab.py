"""
Tab "Programación ECU" — Scaner Soler Pro.

Capacidades:
  • Borrar DTCs (modo 04) con confirmación
  • Análisis profundo del vehículo
  • Resets de servicio (aceite, batería, mariposa, DPF, TPMS…)
  • Leer / escribir flash de la ECU
  • Información de la ECU (part number, versión SW)
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from typing import Optional

DARK_BG  = "#1e1e2e"
SURFACE  = "#313244"
ACCENT   = "#89b4fa"
TEXT     = "#cdd6f4"
SUBTEXT  = "#a6adc8"
GREEN    = "#a6e3a1"
YELLOW   = "#f9e2af"
RED      = "#f38ba8"
ORANGE   = "#fab387"


class ProgrammerTab(ttk.Frame):
    """Tab completa de programación y diagnóstico avanzado de ECU."""

    def __init__(self, parent, app=None, **kw):
        super().__init__(parent, **kw)
        self.app = app
        self._q: queue.Queue = queue.Queue()
        self._build_ui()
        self.after(300, self._poll)

    # ── Construcción UI ──────────────────────────────────────────────────────

    def _build_ui(self):
        # Notebook interno con sub-secciones
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=4, pady=4)

        self._build_dtc_tab(nb)
        self._build_analysis_tab(nb)
        self._build_resets_tab(nb)
        self._build_flash_tab(nb)

    # ── Sub-tab 1: Borrar DTCs ───────────────────────────────────────────────

    def _build_dtc_tab(self, nb):
        frame = ttk.Frame(nb, padding=10)
        nb.add(frame, text="🗑  Borrar DTCs")

        # Panel superior: estado actual
        info = ttk.LabelFrame(frame, text=" Estado Actual de DTCs ", padding=8)
        info.pack(fill="x", pady=(0, 8))

        ttk.Label(info, text="DTCs activos:").grid(row=0, column=0, sticky="w")
        self._dtc_count_var = tk.StringVar(value="—")
        ttk.Label(info, textvariable=self._dtc_count_var,
                  foreground=ACCENT, font=("Consolas", 12, "bold")).grid(
            row=0, column=1, padx=12, sticky="w")

        ttk.Button(info, text="🔍 Leer DTCs",
                   command=self._scan_dtcs).grid(row=0, column=2, padx=8)

        # Lista de DTCs
        cols = ("code", "status", "description", "severity")
        self._dtc_tree = ttk.Treeview(frame, columns=cols,
                                       show="headings", height=10)
        for c, w, t in [("code", 80, "Código"), ("status", 90, "Estado"),
                         ("description", 320, "Descripción"), ("severity", 80, "Gravedad")]:
            self._dtc_tree.heading(c, text=t)
            self._dtc_tree.column(c, width=w)
        self._dtc_tree.tag_configure("critical", foreground=RED)
        self._dtc_tree.tag_configure("warning",  foreground=YELLOW)
        self._dtc_tree.tag_configure("info",     foreground=SUBTEXT)
        vsb = ttk.Scrollbar(frame, orient="v", command=self._dtc_tree.yview)
        self._dtc_tree.configure(yscrollcommand=vsb.set)

        dtree_frame = ttk.Frame(frame)
        dtree_frame.pack(fill="both", expand=True)
        self._dtc_tree.pack(in_=dtree_frame, side="left", fill="both", expand=True)
        vsb.pack(in_=dtree_frame, side="right", fill="y")

        # Botones de acción
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", pady=8)

        self._clear_all_btn = ttk.Button(
            btn_frame, text="🗑 Borrar TODOS los DTCs (Modo 04)",
            command=self._clear_all_dtcs, style="Accent.TButton")
        self._clear_all_btn.pack(side="left", padx=(0, 8))

        self._clear_sel_btn = ttk.Button(
            btn_frame, text="Borrar seleccionado",
            command=self._clear_selected_dtc)
        self._clear_sel_btn.pack(side="left", padx=(0, 8))

        ttk.Button(btn_frame, text="📋 Exportar reporte",
                   command=self._export_dtc_report).pack(side="left")

        self._dtc_status_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self._dtc_status_var,
                  foreground=SUBTEXT).pack(anchor="w")

    # ── Sub-tab 2: Análisis Profundo ─────────────────────────────────────────

    def _build_analysis_tab(self, nb):
        frame = ttk.Frame(nb, padding=10)
        nb.add(frame, text="🧠  Análisis Profundo")

        top = ttk.Frame(frame)
        top.pack(fill="x", pady=(0, 8))

        ttk.Button(top, text="▶ Ejecutar Análisis Completo",
                   command=self._run_deep_analysis,
                   style="Accent.TButton").pack(side="left", padx=(0, 12))

        ttk.Label(top, text="Incluye: correlación de DTCs, sensores, causa raíz, plan de reparación",
                  foreground=SUBTEXT).pack(side="left")

        # Área de reporte
        self._analysis_text = tk.Text(
            frame, wrap="word", font=("Consolas", 9),
            bg=DARK_BG, fg=TEXT, relief="flat", state="disabled")
        vsb2 = ttk.Scrollbar(frame, orient="v",
                              command=self._analysis_text.yview)
        self._analysis_text.configure(yscrollcommand=vsb2.set)

        text_frame = ttk.Frame(frame)
        text_frame.pack(fill="both", expand=True)
        self._analysis_text.pack(in_=text_frame, side="left",
                                  fill="both", expand=True)
        vsb2.pack(in_=text_frame, side="right", fill="y")

        # Tags de color para el reporte
        self._analysis_text.tag_configure("header",   foreground=ACCENT,
                                           font=("Consolas", 10, "bold"))
        self._analysis_text.tag_configure("critical", foreground=RED)
        self._analysis_text.tag_configure("warning",  foreground=YELLOW)
        self._analysis_text.tag_configure("ok",       foreground=GREEN)
        self._analysis_text.tag_configure("code",     foreground=ORANGE)

        ttk.Button(frame, text="💾 Guardar análisis",
                   command=self._save_analysis).pack(anchor="e", pady=(4, 0))

    # ── Sub-tab 3: Resets de Servicio ────────────────────────────────────────

    def _build_resets_tab(self, nb):
        frame = ttk.Frame(nb, padding=10)
        nb.add(frame, text="🔧  Resets de Servicio")

        # Definición de resets disponibles
        RESETS = [
            ("🛢  Reset aceite / servicio",          "oil",      "Borra el contador de km desde el último cambio de aceite"),
            ("🔋  Registro de batería",               "battery",  "Registra nueva batería en el BMS del vehículo"),
            ("🌀  Adaptación mariposa",               "throttle", "Reajusta la posición del cuerpo de mariposa"),
            ("🌫  Reset DPF / FAP",                   "dpf",      "Borra contador de regeneración del filtro de partículas"),
            ("🅿  Calibración frenos de estacionamiento", "epb",  "Calibra el freno electrónico de estacionamiento"),
            ("⚙  Reset inyectores",                   "injectors","Borra correcciones adaptativas de los inyectores"),
            ("📐  Calibración ángulo dirección",       "steering", "Calibra el sensor de ángulo de dirección"),
            ("🔘  Reset TPMS",                         "tpms",     "Resetea el sistema de monitoreo de presión de neumáticos"),
            ("💨  Purga embrague",                    "clutch",   "Purga de aire en sistema hidráulico de embrague"),
            ("❄  Reset sistema A/C",                  "ac",       "Reinicia adaptaciones del compresor de A/C"),
            ("🔩  Activar bomba de combustible",      "fuel_pump","Activa la bomba 2 segundos para cebar el sistema"),
            ("💡  Test luces / actuadores",            "actuators","Prueba todos los actuadores disponibles"),
        ]

        canvas = tk.Canvas(frame, bg=DARK_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical",
                                  command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        inner = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        for i, (label, key, desc) in enumerate(RESETS):
            row = ttk.Frame(inner, padding=(4, 6))
            row.grid(row=i, column=0, sticky="ew", pady=2)
            inner.columnconfigure(0, weight=1)

            ttk.Label(row, text=label,
                      font=("Consolas", 10, "bold"),
                      width=35, anchor="w").pack(side="left")
            ttk.Label(row, text=desc,
                      foreground=SUBTEXT,
                      font=("Consolas", 9)).pack(side="left", padx=8)
            ttk.Button(row, text="Ejecutar",
                       command=lambda k=key, l=label: self._run_reset(k, l)
                       ).pack(side="right", padx=4)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._reset_log = tk.Text(frame, height=6, wrap="word",
                                   font=("Consolas", 9),
                                   bg=SURFACE, fg=TEXT, relief="flat",
                                   state="disabled")
        self._reset_log.pack(fill="x", pady=(8, 0))

    # ── Sub-tab 4: Flash ECU ─────────────────────────────────────────────────

    def _build_flash_tab(self, nb):
        frame = ttk.Frame(nb, padding=10)
        nb.add(frame, text="⚡  Flash ECU")

        # Advertencia
        warn = tk.Label(frame,
                        text="⚠  ADVERTENCIA: La reprogramación incorrecta puede inutilizar la ECU. "
                             "Siempre hacer backup antes. Asegurar alimentación estable (mínimo 12.5V).",
                        bg="#45475a", fg=YELLOW, wraplength=700,
                        font=("Consolas", 9, "bold"), pady=6, padx=10)
        warn.pack(fill="x", pady=(0, 12))

        # Información de la ECU
        ecu_info = ttk.LabelFrame(frame, text=" 📋 Información de la ECU ", padding=8)
        ecu_info.pack(fill="x", pady=(0, 8))

        self._ecu_info_vars = {}
        fields = [("Part Number", "part_number"), ("SW Version", "sw_version"),
                  ("HW Version", "hw_version"), ("VIN", "vin"),
                  ("Fabricante", "manufacturer"), ("Protocolo Flash", "flash_protocol")]
        for i, (label, key) in enumerate(fields):
            r, c = i // 3, (i % 3) * 2
            ttk.Label(ecu_info, text=f"{label}:").grid(row=r, column=c, sticky="w", padx=4)
            v = tk.StringVar(value="—")
            self._ecu_info_vars[key] = v
            ttk.Label(ecu_info, textvariable=v,
                      foreground=ACCENT).grid(row=r, column=c+1, sticky="w", padx=8)

        ttk.Button(ecu_info, text="Leer info ECU",
                   command=self._read_ecu_info).grid(row=0, column=6, padx=12, rowspan=2)

        # Operaciones de flash
        ops = ttk.LabelFrame(frame, text=" ⚡ Operaciones de Flash ", padding=8)
        ops.pack(fill="x", pady=(0, 8))

        # Backup
        bf = ttk.LabelFrame(ops, text="Backup (Leer Flash)", padding=6)
        bf.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ttk.Label(bf, text="Dirección inicio:").grid(row=0, column=0, sticky="w")
        self._backup_start_var = tk.StringVar(value="0x000000")
        ttk.Entry(bf, textvariable=self._backup_start_var, width=12).grid(
            row=0, column=1, padx=4)
        ttk.Label(bf, text="Tamaño:").grid(row=1, column=0, sticky="w")
        self._backup_size_var = tk.StringVar(value="0x40000")
        ttk.Entry(bf, textvariable=self._backup_size_var, width=12).grid(
            row=1, column=1, padx=4)
        ttk.Button(bf, text="📂 Hacer Backup",
                   command=self._do_backup,
                   style="Accent.TButton").grid(row=2, column=0, columnspan=2,
                                                 pady=6, sticky="ew")

        # Write
        wf = ttk.LabelFrame(ops, text="Escribir Flash", padding=6)
        wf.pack(side="left", fill="both", expand=True)
        self._flash_file_var = tk.StringVar(value="Ningún archivo seleccionado")
        ttk.Label(wf, textvariable=self._flash_file_var,
                  foreground=SUBTEXT, wraplength=200).grid(row=0, column=0,
                                                             columnspan=2, sticky="w")
        ttk.Button(wf, text="📂 Seleccionar .bin",
                   command=self._browse_flash).grid(row=1, column=0, pady=4, sticky="w")
        self._verify_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(wf, text="Verificar después de escribir",
                        variable=self._verify_var).grid(row=2, column=0, sticky="w")
        self._write_btn = ttk.Button(wf, text="⚡ Escribir Flash",
                                      command=self._do_write_flash)
        self._write_btn.grid(row=3, column=0, pady=6, sticky="w")

        # Barra de progreso de flash
        prog_frame = ttk.Frame(frame)
        prog_frame.pack(fill="x", pady=(0, 4))
        self._flash_progress = ttk.Progressbar(prog_frame, mode="determinate",
                                                maximum=100, value=0)
        self._flash_progress.pack(fill="x", side="left", expand=True, padx=(0, 8))
        self._flash_pct_var = tk.StringVar(value="")
        ttk.Label(prog_frame, textvariable=self._flash_pct_var,
                  width=8).pack(side="left")

        # Log de flash
        self._flash_log = tk.Text(frame, height=8, wrap="word",
                                   font=("Consolas", 9),
                                   bg=SURFACE, fg=TEXT, relief="flat",
                                   state="disabled")
        self._flash_log.pack(fill="both", expand=True)

    # ── Acciones DTCs ────────────────────────────────────────────────────────

    def _scan_dtcs(self):
        self._dtc_tree.delete(*self._dtc_tree.get_children())
        self._dtc_status_var.set("Leyendo DTCs...")
        threading.Thread(target=self._scan_dtcs_bg, daemon=True).start()

    def _scan_dtcs_bg(self):
        try:
            from ..diagnostic.deep_analyzer import DeepAnalyzer
            from ..knowledge.unified_kb import UnifiedKnowledgeBase
            kb = UnifiedKnowledgeBase()
            analyzer = DeepAnalyzer(kb=kb)

            # Demo: obtiene DTCs del backend si está disponible
            dtcs = []
            backend = getattr(self.app, "backend", None)
            if backend and backend.is_online():
                data = backend.get_dtc_info("active")
                if isinstance(data, list):
                    dtcs = data

            # Fallback: DTCs de demo
            if not dtcs:
                dtcs = [
                    {"code": "P0300", "status": "confirmed", "description": "Fallo de encendido aleatorio"},
                    {"code": "P0171", "status": "confirmed", "description": "Sistema demasiado pobre banco 1"},
                    {"code": "P0420", "status": "pending",   "description": "Eficiencia catalizador banco 1 baja"},
                ]

            self._q.put(("dtcs_loaded", dtcs))
        except Exception as exc:
            self._q.put(("dtcs_error", str(exc)))

    def _clear_all_dtcs(self):
        answer = messagebox.askyesno(
            "Confirmar borrado",
            "¿Borrar TODOS los códigos de falla almacenados?\n\n"
            "Esto borrará también los datos de freeze frame.\n"
            "Esta acción no se puede deshacer.",
            icon="warning")
        if not answer:
            return
        self._dtc_status_var.set("Borrando DTCs (Modo 04)...")
        threading.Thread(target=self._clear_all_bg, daemon=True).start()

    def _clear_all_bg(self):
        try:
            # Intenta via backend
            backend = getattr(self.app, "backend", None)
            ok = False
            if backend and backend.is_online():
                result = backend._post("/api/dtc/clear", {})
                ok = bool(result)

            # Fallback: ELM327 directo
            if not ok:
                elm = getattr(self.app, "elm", None)
                if elm and elm.is_connected:
                    ok = elm.clear_dtc()

            self._q.put(("dtcs_cleared", ok))
        except Exception as exc:
            self._q.put(("dtcs_error", str(exc)))

    def _clear_selected_dtc(self):
        sel = self._dtc_tree.selection()
        if not sel:
            messagebox.showinfo("Info", "Selecciona un DTC de la lista primero.")
            return
        code = self._dtc_tree.item(sel[0])["values"][0]
        if messagebox.askyesno("Confirmar", f"¿Borrar el código {code}?\n\nNota: el modo 04 borra TODOS los DTCs, no uno solo."):
            self._clear_all_dtcs()

    def _export_dtc_report(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Texto", "*.txt"), ("CSV", "*.csv"), ("Todos", "*.*")],
            initialfile="dtc_report.txt")
        if path:
            try:
                lines = ["REPORTE DTCs — Scaner Soler Pro\n"]
                for item in self._dtc_tree.get_children():
                    vals = self._dtc_tree.item(item)["values"]
                    lines.append(f"{vals[0]}\t{vals[1]}\t{vals[2]}\t{vals[3]}\n")
                Path(path).write_text("".join(lines), encoding="utf-8")
                messagebox.showinfo("Guardado", f"Reporte guardado en:\n{path}")
            except Exception as exc:
                messagebox.showerror("Error", str(exc))

    # ── Acciones Análisis ────────────────────────────────────────────────────

    def _run_deep_analysis(self):
        self._set_analysis_text("⏳ Ejecutando análisis profundo...\n", clear=True)
        threading.Thread(target=self._analysis_bg, daemon=True).start()

    def _analysis_bg(self):
        try:
            from ..diagnostic.deep_analyzer import DeepAnalyzer
            from ..knowledge.unified_kb import UnifiedKnowledgeBase
            kb = UnifiedKnowledgeBase()
            analyzer = DeepAnalyzer(kb=kb)

            dtcs = ["P0300", "P0171", "P0420"]
            live_data = {"rpm": 850, "coolant_temp": 92, "maf": 2.1,
                         "fuel_trim_st_b1": 18.0, "fuel_trim_lt_b1": 12.5,
                         "o2_b1s1_v": 0.15, "throttle": 5.2, "speed": 0}
            vehicle_info = {"vin": "DEMO_VIN", "make": "Generic"}

            backend = getattr(self.app, "backend", None)
            if backend and backend.is_online():
                sensors = backend.get_live_sensors()
                if isinstance(sensors, dict) and "error" not in sensors:
                    live_data.update(sensors)

            report = analyzer.run_full_diagnosis(dtcs, live_data, vehicle_info)
            self._q.put(("analysis_done", report))
        except Exception as exc:
            self._q.put(("analysis_error", str(exc)))

    def _set_analysis_text(self, text: str, clear: bool = False, tag: str = ""):
        self._analysis_text.configure(state="normal")
        if clear:
            self._analysis_text.delete("1.0", "end")
        self._analysis_text.insert("end", text, tag)
        self._analysis_text.see("end")
        self._analysis_text.configure(state="disabled")

    def _save_analysis(self):
        content = self._analysis_text.get("1.0", "end")
        if not content.strip():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Texto", "*.txt"), ("Todos", "*.*")],
            initialfile="analisis_profundo.txt")
        if path:
            Path(path).write_text(content, encoding="utf-8")

    # ── Acciones Resets ──────────────────────────────────────────────────────

    def _run_reset(self, key: str, label: str):
        confirm = messagebox.askyesno(
            "Confirmar Reset",
            f"¿Ejecutar: {label}?\n\n"
            "Asegúrate de que el contacto está en posición ON\n"
            "y el motor puede estar apagado (según el reset).")
        if not confirm:
            return
        threading.Thread(target=self._reset_bg, args=(key, label),
                         daemon=True).start()

    def _reset_bg(self, key: str, label: str):
        try:
            from ..ecu.service_resets import ServiceResetManager
            backend = getattr(self.app, "backend", None)
            elm = getattr(self.app, "elm", None)

            srm = ServiceResetManager(elm=elm, backend=backend)
            method = getattr(srm, f"reset_{key}", None) or \
                     getattr(srm, f"calibrate_{key}", None) or \
                     getattr(srm, f"activate_{key}", None)

            if method:
                result = method()
            else:
                result = {"status": "not_implemented",
                          "message": f"Reset '{key}' pendiente de implementación para este vehículo"}

            self._q.put(("reset_done", label, result))
        except Exception as exc:
            self._q.put(("reset_error", label, str(exc)))

    def _log_reset(self, msg: str, color: str = TEXT):
        self._reset_log.configure(state="normal")
        self._reset_log.insert("end", msg + "\n")
        self._reset_log.see("end")
        self._reset_log.configure(state="disabled")

    # ── Acciones Flash ───────────────────────────────────────────────────────

    def _read_ecu_info(self):
        threading.Thread(target=self._ecu_info_bg, daemon=True).start()

    def _ecu_info_bg(self):
        try:
            backend = getattr(self.app, "backend", None)
            info = {}
            if backend and backend.is_online():
                data = backend._get("/api/ecu/info")
                if isinstance(data, dict):
                    info = data

            if not info:
                info = {
                    "part_number": "0261S21892",
                    "sw_version":  "SW8.30.6",
                    "hw_version":  "HW23",
                    "vin":         "DEMO_VIN",
                    "manufacturer":"Bosch (demo)",
                    "flash_protocol": "UDS/CAN 500kbps",
                }
            self._q.put(("ecu_info", info))
        except Exception as exc:
            self._q.put(("flash_log", f"Error leyendo info: {exc}"))

    def _browse_flash(self):
        path = filedialog.askopenfilename(
            filetypes=[("Binario", "*.bin"), ("ECU dump", "*.ecu *.ori *.mod"),
                       ("Todos", "*.*")])
        if path:
            self._flash_file_var.set(path)
            sz = Path(path).stat().st_size
            self._log_flash(f"Archivo seleccionado: {path}  ({sz:,} bytes)")

    def _do_backup(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".bin",
            filetypes=[("Binario", "*.bin"), ("Todos", "*.*")],
            initialfile="ecu_backup.bin")
        if not path:
            return
        try:
            start = int(self._backup_start_var.get(), 16)
            size  = int(self._backup_size_var.get(), 16)
        except ValueError:
            messagebox.showerror("Error", "Dirección o tamaño inválido (usa hex: 0x40000)")
            return
        self._flash_progress["value"] = 0
        self._log_flash(f"Iniciando backup: addr={hex(start)} size={hex(size)}...")
        threading.Thread(target=self._backup_bg,
                         args=(path, start, size), daemon=True).start()

    def _backup_bg(self, path: str, start: int, size: int):
        try:
            from ..ecu.programmer import ECUProgrammer
            elm = getattr(self.app, "elm", None)
            prog = ECUProgrammer(comm_layer=elm)

            def _prog_cb(done, total):
                pct = done * 100 / total if total else 0
                self._q.put(("flash_progress", pct))

            data = prog.read_flash(start_addr=start, length=size,
                                   progress_cb=_prog_cb)
            Path(path).write_bytes(data)
            self._q.put(("flash_log", f"✓ Backup guardado: {path}  ({len(data):,} bytes)"))
            self._q.put(("flash_progress", 100))
        except Exception as exc:
            self._q.put(("flash_log", f"✗ Error: {exc}"))

    def _do_write_flash(self):
        path = self._flash_file_var.get()
        if path == "Ningún archivo seleccionado" or not Path(path).exists():
            messagebox.showerror("Error", "Selecciona un archivo .bin primero.")
            return
        answer = messagebox.askyesno(
            "⚠ CONFIRMACIÓN FINAL",
            f"Escribir flash desde:\n{path}\n\n"
            "¿Ya tiene un backup de la ECU original?\n"
            "¡Una escritura incorrecta puede inutilizar el motor!",
            icon="warning")
        if not answer:
            return
        self._flash_progress["value"] = 0
        data = Path(path).read_bytes()
        self._log_flash(f"Escribiendo {len(data):,} bytes desde {path}...")
        verify = self._verify_var.get()
        threading.Thread(target=self._write_flash_bg,
                         args=(data, verify), daemon=True).start()

    def _write_flash_bg(self, data: bytes, verify: bool):
        try:
            from ..ecu.programmer import ECUProgrammer
            elm = getattr(self.app, "elm", None)
            prog = ECUProgrammer(comm_layer=elm)

            def _prog_cb(done, total):
                pct = done * 100 / total if total else 0
                self._q.put(("flash_progress", pct))

            result = prog.write_flash(data, verify=verify, progress_cb=_prog_cb)
            if result.success:
                self._q.put(("flash_log",
                              f"✓ Flash escrito correctamente  ({result.bytes_written:,} bytes, "
                              f"{result.elapsed_sec:.1f}s)"))
            else:
                self._q.put(("flash_log",
                              f"✗ Error al escribir: {result.verify_errors}"))
            self._q.put(("flash_progress", 100))
        except Exception as exc:
            self._q.put(("flash_log", f"✗ {exc}"))

    def _log_flash(self, msg: str):
        self._flash_log.configure(state="normal")
        self._flash_log.insert("end", msg + "\n")
        self._flash_log.see("end")
        self._flash_log.configure(state="disabled")

    # ── Polling de cola ──────────────────────────────────────────────────────

    def _poll(self):
        while not self._q.empty():
            msg = self._q.get_nowait()
            match msg[0]:
                case "dtcs_loaded":
                    dtcs = msg[1]
                    self._dtc_count_var.set(str(len(dtcs)))
                    self._dtc_tree.delete(*self._dtc_tree.get_children())
                    for d in dtcs:
                        code = d.get("code", "?")
                        status = d.get("status", "?")
                        desc = d.get("description", "")
                        sev = d.get("severity", "warning")
                        self._dtc_tree.insert("", "end", tags=(sev,),
                                              values=(code, status, desc, sev))
                    self._dtc_status_var.set(f"✓ {len(dtcs)} DTC(s) encontrados.")
                case "dtcs_cleared":
                    ok = msg[1]
                    if ok:
                        self._dtc_tree.delete(*self._dtc_tree.get_children())
                        self._dtc_count_var.set("0")
                        self._dtc_status_var.set("✓ DTCs borrados correctamente.")
                    else:
                        self._dtc_status_var.set("✗ No se pudo borrar (sin conexión o error).")
                case "dtcs_error":
                    self._dtc_status_var.set(f"✗ Error: {msg[1]}")
                case "analysis_done":
                    self._render_analysis(msg[1])
                case "analysis_error":
                    self._set_analysis_text(f"Error: {msg[1]}\n", clear=True)
                case "reset_done":
                    _, label, result = msg
                    ok = result is True or (isinstance(result, dict) and
                                             result.get("status") != "error")
                    icon = "✓" if ok else "⚠"
                    detail = ""
                    if isinstance(result, dict):
                        detail = f" — {result.get('message', result.get('status', ''))}"
                    self._log_reset(f"{icon} {label}{detail}")
                case "reset_error":
                    _, label, err = msg
                    self._log_reset(f"✗ {label}: {err}")
                case "ecu_info":
                    info = msg[1]
                    for key, var in self._ecu_info_vars.items():
                        var.set(info.get(key, "—"))
                case "flash_progress":
                    pct = msg[1]
                    self._flash_progress["value"] = pct
                    self._flash_pct_var.set(f"{pct:.0f}%")
                case "flash_log":
                    self._log_flash(msg[1])
        self.after(250, self._poll)

    def _render_analysis(self, report):
        self._analysis_text.configure(state="normal")
        self._analysis_text.delete("1.0", "end")

        def _ins(text, tag=""):
            self._analysis_text.insert("end", text, tag)

        _ins("═" * 60 + "\n", "header")
        _ins("  ANÁLISIS PROFUNDO — SCANER SOLER PRO\n", "header")
        _ins("═" * 60 + "\n\n", "header")

        _ins(f"  Score de salud: ", "")
        score = getattr(report, "health_score", 0)
        score_tag = "ok" if score >= 70 else ("warning" if score >= 40 else "critical")
        _ins(f"{score}/100\n\n", score_tag)

        sev = getattr(report, "severity", "info")
        _ins(f"  Severidad: {sev.upper()}\n\n",
             "critical" if sev == "critical" else ("warning" if sev == "warning" else "ok"))

        dtcs = getattr(report, "dtcs", [])
        _ins(f"  DTCs ({len(dtcs)}):\n", "header")
        for d in dtcs:
            if isinstance(d, dict):
                _ins(f"    [{d.get('code','?')}] {d.get('description','')}\n", "code")
            else:
                _ins(f"    {d}\n", "code")

        alerts = getattr(report, "sensor_alerts", [])
        if alerts:
            _ins(f"\n  Alertas de sensores ({len(alerts)}):\n", "header")
            for a in alerts:
                tag = "critical" if getattr(a, "severity", "") == "critical" else "warning"
                _ins(f"    ⚠ {getattr(a,'sensor_name','?')}: "
                     f"{getattr(a,'value','?')} {getattr(a,'unit','')} "
                     f"(rango esperado: {getattr(a,'expected_range','')})\n", tag)

        rc = getattr(report, "root_cause", None)
        if rc:
            _ins("\n  Causas raíz probables:\n", "header")
            causes = getattr(rc, "probable_causes", [])
            for c in causes:
                _ins(f"    → {c}\n", "warning")
            conf = getattr(rc, "confidence", 0)
            _ins(f"    Confianza: {conf*100:.0f}%\n")

        plan = getattr(report, "repair_plan", "")
        if plan:
            _ins("\n  Plan de reparación:\n", "header")
            _ins(plan + "\n")

        self._analysis_text.see("1.0")
        self._analysis_text.configure(state="disabled")
