"""
security_tab.py — Pestaña GUI para Monitor de Seguridad Automotriz.
Estilo 2026: paleta abismal + tarjetas KPI + treeview con severidad coloreada.
Funciona con o sin comm/security.py (graceful fallback).
"""
from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime
from typing import Optional, List, Dict, Any

# ── Importación opcional del módulo de seguridad ──────────────────────────────
try:
    from ..comm.security import (
        SecurityAuditLog,
        CANAnomalyDetector,
        CommandSanitizer,
        UDSRiskGuard,
    )
    _SEC_AVAILABLE = True
    _SEC_IMPORT_ERROR = ""
except ImportError as e:
    _SEC_AVAILABLE = False
    _SEC_IMPORT_ERROR = str(e)
    SecurityAuditLog    = None  # type: ignore
    CANAnomalyDetector  = None  # type: ignore
    CommandSanitizer    = None  # type: ignore
    UDSRiskGuard        = None  # type: ignore

# ── Paleta (igual que app.py y reverse_engineer_tab.py) ───────────────────────
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

# ── Constantes de severidad ───────────────────────────────────────────────────
SEV_COLOR = {
    "critical": RED,
    "warning":  YELLOW,
    "info":     CYAN,
    "ok":       GREEN,
}


def _ts() -> str:
    """Timestamp corto para el log."""
    return datetime.now().strftime("%H:%M:%S")


# ── Widget auxiliar: tarjeta KPI ─────────────────────────────────────────────
class _KPICard(tk.Frame):
    """Tarjeta compacta: título + valor grande."""

    def __init__(self, parent: tk.Widget, title: str, value: str = "0",
                 color: str = CYAN, **kwargs):
        super().__init__(parent, bg=CARD, padx=14, pady=10, **kwargs)
        self._color = color

        tk.Label(self, text=title.upper(), bg=CARD, fg=SUBTEXT,
                 font=("Consolas", 7, "bold")).pack(anchor="w")
        self._val_lbl = tk.Label(self, text=value, bg=CARD, fg=color,
                                  font=("Consolas", 22, "bold"))
        self._val_lbl.pack(anchor="w")

    def set(self, value: str, color: Optional[str] = None):
        self._val_lbl.config(text=value)
        if color:
            self._val_lbl.config(fg=color)


# ── Pestaña principal ─────────────────────────────────────────────────────────
class SecurityTab(tk.Frame):
    """
    Pestaña de Seguridad Automotriz.

    - Panel izquierdo : treeview de alertas + validador de comandos OBD/UDS/AT.
    - Panel derecho   : 4 KPI cards + log de auditoría con exportación JSON.
    - Modo seguro     : toggle que bloquea comandos peligrosos si el módulo
                        comm/security está disponible.
    """

    def __init__(self, parent: tk.Widget, app=None):
        super().__init__(parent, bg=DARK_BG)
        self._app   = app

        # Módulos opcionales
        self._audit_log         : Optional[Any] = None
        self._anomaly_detector  : Optional[Any] = None
        self._sanitizer         : Optional[Any] = None
        self._risk_guard        : Optional[Any] = None

        # Estado interno
        self._security_mode  = tk.BooleanVar(value=False)
        self._alert_count    = 0
        self._cmd_count      = 0
        self._blocked_count  = 0
        self._unique_ids     : set = set()
        self._audit_entries  : List[str] = []

        self._build_ui()
        self._try_init_security()

    # ── Inicialización del módulo de seguridad ────────────────────────────────
    def _try_init_security(self):
        if not _SEC_AVAILABLE:
            self._update_status(
                f"Módulo comm/security no disponible: {_SEC_IMPORT_ERROR}", SUBTEXT
            )
            return
        try:
            self._audit_log        = SecurityAuditLog()
            self._anomaly_detector = CANAnomalyDetector()
            self._sanitizer        = CommandSanitizer()
            self._risk_guard       = UDSRiskGuard()
            self._update_status("✓ Módulo de seguridad cargado correctamente.", GREEN)
            self._append_audit(f"[{_ts()}] [INFO] Módulo de seguridad inicializado.")
        except Exception as exc:
            self._update_status(f"Error al inicializar seguridad: {exc}", YELLOW)

    # ── Construcción de la UI ─────────────────────────────────────────────────
    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=SURFACE)
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=ACCENT, height=2).pack(fill="x")

        hdr_inner = tk.Frame(hdr, bg=SURFACE, pady=8)
        hdr_inner.pack(fill="x", padx=16)

        tk.Label(
            hdr_inner,
            text="🛡️  Seguridad",
            bg=SURFACE, fg=FG,
            font=("Consolas", 13, "bold"),
        ).pack(side="left")
        tk.Label(
            hdr_inner,
            text=" — Monitor de Seguridad Automotriz",
            bg=SURFACE, fg=SUBTEXT,
            font=("Consolas", 9),
        ).pack(side="left")

        # Badge de estado del módulo
        self._status_badge = tk.Label(
            hdr_inner,
            text="● cargando…",
            bg=SURFACE, fg=SUBTEXT,
            font=("Consolas", 8, "bold"),
        )
        self._status_badge.pack(side="right", padx=(0, 8))

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # ── Cuerpo: PanedWindow horizontal ───────────────────────────────────
        paned = tk.PanedWindow(
            self, orient=tk.HORIZONTAL,
            bg=DARK_BG, sashwidth=4, sashrelief="flat",
            sashpad=2,
        )
        paned.pack(fill="both", expand=True, padx=6, pady=6)

        left  = tk.Frame(paned, bg=DARK_BG)
        right = tk.Frame(paned, bg=DARK_BG)
        paned.add(left,  minsize=380, stretch="always")
        paned.add(right, minsize=380, stretch="always")

        self._build_left(left)
        self._build_right(right)

    # ── Panel izquierdo ───────────────────────────────────────────────────────
    def _build_left(self, parent: tk.Frame):
        # -- Alertas de Seguridad --------------------------------------------
        alert_lf = tk.LabelFrame(
            parent, text=" Alertas de Seguridad ",
            bg=DARK_BG, fg=SUBTEXT,
            font=("Consolas", 8, "bold"),
            relief="flat", bd=1, highlightbackground=BORDER,
            highlightthickness=1,
        )
        alert_lf.pack(fill="both", expand=True, pady=(0, 6))

        cols = ("severity", "tipo", "descripcion", "timestamp")
        self._alert_tree = ttk.Treeview(
            alert_lf, columns=cols, show="headings",
            selectmode="browse", height=10,
        )
        for col, label, width in (
            ("severity",    "Severity",     80),
            ("tipo",        "Tipo",        120),
            ("descripcion", "Descripción", 260),
            ("timestamp",   "Hora",         70),
        ):
            self._alert_tree.heading(col, text=label)
            self._alert_tree.column(col, width=width, anchor="w")

        # Tags de color para filas
        self._alert_tree.tag_configure("critical", foreground=RED)
        self._alert_tree.tag_configure("warning",  foreground=YELLOW)
        self._alert_tree.tag_configure("info",     foreground=CYAN)
        self._alert_tree.tag_configure("ok",       foreground=GREEN)

        sb_alert = ttk.Scrollbar(alert_lf, orient="vertical",
                                  command=self._alert_tree.yview)
        self._alert_tree.configure(yscrollcommand=sb_alert.set)
        sb_alert.pack(side="right", fill="y")
        self._alert_tree.pack(fill="both", expand=True, padx=4, pady=4)

        # -- Validador de Comandos -------------------------------------------
        val_lf = tk.LabelFrame(
            parent, text=" Validador de Comandos ",
            bg=DARK_BG, fg=SUBTEXT,
            font=("Consolas", 8, "bold"),
            relief="flat", bd=1, highlightbackground=BORDER,
            highlightthickness=1,
        )
        val_lf.pack(fill="x", pady=(0, 6))

        row1 = tk.Frame(val_lf, bg=DARK_BG)
        row1.pack(fill="x", padx=8, pady=(8, 4))

        tk.Label(row1, text="Comando OBD/UDS/AT:",
                 bg=DARK_BG, fg=FG,
                 font=("Consolas", 9)).pack(side="left")

        self._cmd_entry = tk.Entry(
            row1, bg=ENTRY_BG, fg=FG,
            insertbackground=ACCENT_LT,
            relief="flat", font=("Consolas", 10),
            width=28,
        )
        self._cmd_entry.pack(side="left", padx=8, fill="x", expand=True)
        self._cmd_entry.bind("<Return>", lambda _e: self.validate_command())

        tk.Button(
            row1, text="Validar",
            bg=ACCENT, fg="#ffffff",
            activebackground=ACCENT_LT,
            relief="flat", font=("Consolas", 9, "bold"),
            cursor="hand2",
            command=self.validate_command,
        ).pack(side="left")

        self._val_result = tk.Label(
            val_lf, text="",
            bg=DARK_BG, fg=SUBTEXT,
            font=("Consolas", 9, "bold"),
        )
        self._val_result.pack(anchor="w", padx=8, pady=(0, 8))

        # -- Controles -------------------------------------------------------
        ctrl_lf = tk.LabelFrame(
            parent, text=" Controles ",
            bg=DARK_BG, fg=SUBTEXT,
            font=("Consolas", 8, "bold"),
            relief="flat", bd=1, highlightbackground=BORDER,
            highlightthickness=1,
        )
        ctrl_lf.pack(fill="x")

        ctrl_row = tk.Frame(ctrl_lf, bg=DARK_BG)
        ctrl_row.pack(fill="x", padx=8, pady=8)

        self._mode_btn = tk.Button(
            ctrl_row,
            text="🔒  Modo Seguro OFF",
            bg=BORDER, fg=FG,
            activebackground=CARD,
            relief="flat", font=("Consolas", 9, "bold"),
            cursor="hand2",
            command=self.toggle_security_mode,
        )
        self._mode_btn.pack(side="left", padx=(0, 8))

        tk.Button(
            ctrl_row,
            text="Ver Alertas",
            bg=BORDER, fg=FG,
            activebackground=CARD,
            relief="flat", font=("Consolas", 9, "bold"),
            cursor="hand2",
            command=self._focus_alerts,
        ).pack(side="left")

    # ── Panel derecho ─────────────────────────────────────────────────────────
    def _build_right(self, parent: tk.Frame):
        # -- KPI cards -------------------------------------------------------
        kpi_lf = tk.LabelFrame(
            parent, text=" Estadísticas de Tráfico ",
            bg=DARK_BG, fg=SUBTEXT,
            font=("Consolas", 8, "bold"),
            relief="flat", bd=1, highlightbackground=BORDER,
            highlightthickness=1,
        )
        kpi_lf.pack(fill="x", pady=(0, 6))

        kpi_row = tk.Frame(kpi_lf, bg=DARK_BG)
        kpi_row.pack(fill="x", padx=6, pady=6)

        self._kpi_sent    = _KPICard(kpi_row, "Comandos enviados",  "0", CYAN)
        self._kpi_alerts  = _KPICard(kpi_row, "Alertas detectadas", "0", YELLOW)
        self._kpi_blocked = _KPICard(kpi_row, "Cmd. bloqueados",    "0", RED)
        self._kpi_ids     = _KPICard(kpi_row, "IDs CAN únicos",     "0", GREEN)

        for card in (self._kpi_sent, self._kpi_alerts,
                     self._kpi_blocked, self._kpi_ids):
            card.pack(side="left", expand=True, fill="both", padx=3)

        # -- Log de Auditoría ------------------------------------------------
        log_lf = tk.LabelFrame(
            parent, text=" Log de Auditoría ",
            bg=DARK_BG, fg=SUBTEXT,
            font=("Consolas", 8, "bold"),
            relief="flat", bd=1, highlightbackground=BORDER,
            highlightthickness=1,
        )
        log_lf.pack(fill="both", expand=True, pady=(0, 6))

        self._log_text = tk.Text(
            log_lf,
            bg=CARD, fg=FG,
            insertbackground=ACCENT_LT,
            relief="flat", font=("Consolas", 9),
            state="disabled",
            wrap="none",
        )
        sb_log_y = ttk.Scrollbar(log_lf, orient="vertical",
                                   command=self._log_text.yview)
        sb_log_x = ttk.Scrollbar(log_lf, orient="horizontal",
                                   command=self._log_text.xview)
        self._log_text.configure(yscrollcommand=sb_log_y.set,
                                  xscrollcommand=sb_log_x.set)
        sb_log_y.pack(side="right", fill="y")
        sb_log_x.pack(side="bottom", fill="x")
        self._log_text.pack(fill="both", expand=True, padx=4, pady=4)

        # Tags de color en el log
        self._log_text.tag_configure("critical", foreground=RED)
        self._log_text.tag_configure("warning",  foreground=YELLOW)
        self._log_text.tag_configure("info",     foreground=CYAN)
        self._log_text.tag_configure("ok",       foreground=GREEN)
        self._log_text.tag_configure("blocked",  foreground=ORANGE)
        self._log_text.tag_configure("default",  foreground=FG)

        # -- Botones de log --------------------------------------------------
        btn_row = tk.Frame(parent, bg=DARK_BG)
        btn_row.pack(fill="x")

        tk.Button(
            btn_row,
            text="Exportar Log JSON",
            bg=ACCENT, fg="#ffffff",
            activebackground=ACCENT_LT,
            relief="flat", font=("Consolas", 9, "bold"),
            cursor="hand2",
            command=self.export_log,
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            btn_row,
            text="Limpiar",
            bg=BORDER, fg=FG,
            activebackground=CARD,
            relief="flat", font=("Consolas", 9, "bold"),
            cursor="hand2",
            command=self._clear_log,
        ).pack(side="left")

    # ── Métodos públicos ──────────────────────────────────────────────────────

    def validate_command(self):
        """
        Lee el Entry, valida con CommandSanitizer / UDSRiskGuard si están
        disponibles, y muestra el resultado en colores semáforo.
        """
        cmd = self._cmd_entry.get().strip()
        if not cmd:
            self._val_result.config(text="⚠  Escribe un comando primero.", fg=YELLOW)
            return

        self._cmd_count += 1
        self._kpi_sent.set(str(self._cmd_count))
        ts = _ts()

        # ── Caso 1: módulo disponible ────────────────────────────────────────
        if self._sanitizer is not None:
            try:
                result = self._sanitizer.validate(cmd)
                # Intentar detección de riesgo UDS si disponible
                risk_label = None
                if self._risk_guard is not None:
                    try:
                        risk_label = self._risk_guard.assess(cmd)
                    except Exception:
                        pass

                if risk_label and risk_label.lower() in ("danger", "high", "critical"):
                    self._blocked_count += 1
                    self._kpi_blocked.set(str(self._blocked_count))
                    msg = f"⚠  DANGER: {risk_label} — {cmd}"
                    self._val_result.config(text=msg, fg=YELLOW)
                    self._append_audit(f"[{ts}] [DANGER] {cmd} → {risk_label}",
                                       tag="warning")
                    self.add_alert({
                        "severity": "warning",
                        "tipo": "UDS Risk",
                        "descripcion": f"Servicio peligroso: {cmd}",
                        "timestamp": ts,
                    })
                elif result and getattr(result, "blocked", False):
                    self._blocked_count += 1
                    self._kpi_blocked.set(str(self._blocked_count))
                    reason = getattr(result, "reason", "razón desconocida")
                    msg = f"✗  BLOQUEADO: {reason}"
                    self._val_result.config(text=msg, fg=RED)
                    self._append_audit(f"[{ts}] [BLOQUEADO] {cmd} — {reason}",
                                       tag="blocked")
                    self.add_alert({
                        "severity": "critical",
                        "tipo": "Comando bloqueado",
                        "descripcion": f"{cmd}: {reason}",
                        "timestamp": ts,
                    })
                else:
                    msg = f"✓  VÁLIDO — {cmd}"
                    self._val_result.config(text=msg, fg=GREEN)
                    self._append_audit(f"[{ts}] [OK] {cmd}", tag="ok")
            except Exception as exc:
                self._val_result.config(
                    text=f"Error en sanitizer: {exc}", fg=YELLOW
                )
                self._append_audit(f"[{ts}] [ERR] {exc}", tag="warning")
            return

        # ── Caso 2: fallback heurístico (sin módulo) ──────────────────────────
        cmd_upper = cmd.upper().strip()

        # Comandos AT siempre válidos
        if cmd_upper.startswith("AT"):
            self._val_result.config(
                text=f"✓  VÁLIDO (AT command) — {cmd}", fg=GREEN
            )
            self._append_audit(f"[{ts}] [OK] {cmd}", tag="ok")
            return

        # Servicios UDS peligrosos conocidos
        dangerous = {
            "2E": "Escritura de datos en ECU",
            "34": "Solicitud de descarga",
            "35": "Solicitud de carga",
            "36": "Transferencia de datos",
            "37": "Salida de transferencia",
            "31": "Control de rutina",
            "27": "Acceso de seguridad (seed/key)",
            "85": "Control de comunicación",
            "3E": "Tester Present (sesión extendida)",
        }
        # Extraer posible byte de servicio (primeros 2 hex)
        hex_part = cmd_upper.replace(" ", "")[:2]
        if hex_part in dangerous:
            self._blocked_count += 1
            self._kpi_blocked.set(str(self._blocked_count))
            reason = dangerous[hex_part]
            self._val_result.config(
                text=f"⚠  DANGER: {reason} (servicio {hex_part})", fg=YELLOW
            )
            self._append_audit(
                f"[{ts}] [DANGER] {cmd} → {reason}", tag="warning"
            )
            self.add_alert({
                "severity": "warning",
                "tipo": "Servicio peligroso",
                "descripcion": f"{reason}: {cmd}",
                "timestamp": ts,
            })
            return

        # OBD Mode 01 / 09 — lectura segura
        if hex_part in ("01", "09", "03", "04", "07", "0A"):
            self._val_result.config(
                text=f"✓  VÁLIDO (OBD-II modo {hex_part}) — {cmd}", fg=GREEN
            )
            self._append_audit(f"[{ts}] [OK] {cmd}", tag="ok")
            return

        # Default: advertencia por comando desconocido
        self._val_result.config(
            text=f"⚠  DESCONOCIDO: revisa el comando — {cmd}", fg=YELLOW
        )
        self._append_audit(f"[{ts}] [UNKNOWN] {cmd}", tag="warning")

    def toggle_security_mode(self):
        """Activa / desactiva el modo seguro."""
        current = self._security_mode.get()
        new_val = not current
        self._security_mode.set(new_val)

        if new_val:
            self._mode_btn.config(
                text="🔒  Modo Seguro ON",
                bg=GREEN, fg="#000000",
            )
            self._append_audit(f"[{_ts()}] [MODO] Modo seguro ACTIVADO.", tag="ok")
            # Intentar propagar al vehicle_conn si existe
            if self._app is not None:
                conn = getattr(self._app, "vehicle_conn", None)
                if conn is not None:
                    try:
                        conn.set_safe_mode(True)
                    except Exception:
                        pass
        else:
            self._mode_btn.config(
                text="🔒  Modo Seguro OFF",
                bg=BORDER, fg=FG,
            )
            self._append_audit(
                f"[{_ts()}] [MODO] Modo seguro DESACTIVADO.", tag="warning"
            )
            if self._app is not None:
                conn = getattr(self._app, "vehicle_conn", None)
                if conn is not None:
                    try:
                        conn.set_safe_mode(False)
                    except Exception:
                        pass

    def add_alert(self, alert: Dict[str, Any]):
        """
        Añade una alerta al treeview.

        alert = {
            "severity": "critical" | "warning" | "info" | "ok",
            "tipo": str,
            "descripcion": str,
            "timestamp": str,   # opcional
        }
        """
        severity    = alert.get("severity", "info").lower()
        tipo        = alert.get("tipo",        "—")
        descripcion = alert.get("descripcion", "—")
        ts          = alert.get("timestamp",   _ts())

        self._alert_count += 1
        self._kpi_alerts.set(
            str(self._alert_count),
            color=RED if severity == "critical" else YELLOW,
        )

        tag = severity if severity in SEV_COLOR else "info"
        self._alert_tree.insert(
            "", "end",
            values=(severity.upper(), tipo, descripcion, ts),
            tags=(tag,),
        )
        # Scroll al último elemento
        children = self._alert_tree.get_children()
        if children:
            self._alert_tree.see(children[-1])

    def refresh_log(self):
        """Recarga el text widget con las últimas 50 entradas del audit_log."""
        if self._audit_log is None:
            return
        try:
            entries = self._audit_log.get_entries(limit=50)
            self._log_text.config(state="normal")
            self._log_text.delete("1.0", "end")
            for entry in entries:
                line = str(entry) + "\n"
                self._log_text.insert("end", line)
            self._log_text.config(state="disabled")
            self._log_text.see("end")
        except Exception as exc:
            self._append_audit(f"[{_ts()}] [ERR] refresh_log: {exc}", tag="warning")

    def export_log(self):
        """Exporta el log de auditoría a un archivo JSON elegido por el usuario."""
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Todos", "*.*")],
            title="Exportar Log de Auditoría",
            initialfile=f"security_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
        if not path:
            return

        # Exportar desde módulo si disponible
        if self._audit_log is not None:
            try:
                data = self._audit_log.export_json()
                with open(path, "w", encoding="utf-8") as f:
                    f.write(data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False))
                messagebox.showinfo("Exportar Log", f"Log exportado a:\n{path}")
                return
            except Exception as exc:
                messagebox.showerror("Error", f"Error al exportar desde módulo:\n{exc}")
                return

        # Fallback: exportar entradas internas
        payload = {
            "exported_at": datetime.now().isoformat(),
            "total_entries": len(self._audit_entries),
            "entries": self._audit_entries[-200:],
            "stats": {
                "commands_sent":   self._cmd_count,
                "alerts_detected": self._alert_count,
                "commands_blocked": self._blocked_count,
                "unique_can_ids":  len(self._unique_ids),
            },
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            messagebox.showinfo("Exportar Log", f"Log exportado a:\n{path}")
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo escribir el archivo:\n{exc}")

    def register_can_id(self, can_id: str):
        """Registra un ID CAN único y actualiza el KPI."""
        self._unique_ids.add(can_id)
        self._kpi_ids.set(str(len(self._unique_ids)))

    def on_close(self):
        """Llamado por app.py al cerrar la ventana."""
        pass  # sin recursos activos que liberar

    # ── Métodos internos ──────────────────────────────────────────────────────

    def _update_status(self, text: str, color: str = FG):
        """Actualiza el badge de estado en el header."""
        try:
            self._status_badge.config(text=f"● {text}", fg=color)
        except tk.TclError:
            pass

    def _append_audit(self, line: str, tag: str = "default"):
        """Añade una línea al text widget del log y a la lista interna."""
        self._audit_entries.append(line)
        # Mantener máximo 500 entradas en memoria
        if len(self._audit_entries) > 500:
            self._audit_entries = self._audit_entries[-500:]
        try:
            self._log_text.config(state="normal")
            self._log_text.insert("end", line + "\n", tag)
            # Mantener solo las últimas 50 líneas visibles
            lines = int(self._log_text.index("end-1c").split(".")[0])
            if lines > 52:
                self._log_text.delete("1.0", f"{lines - 50}.0")
            self._log_text.see("end")
            self._log_text.config(state="disabled")
        except tk.TclError:
            pass

    def _clear_log(self):
        """Limpia el text widget del log."""
        try:
            self._log_text.config(state="normal")
            self._log_text.delete("1.0", "end")
            self._log_text.config(state="disabled")
        except tk.TclError:
            pass
        self._append_audit(f"[{_ts()}] [INFO] Log limpiado por el usuario.", tag="info")

    def _focus_alerts(self):
        """Desplaza la vista para mostrar el treeview de alertas."""
        try:
            self._alert_tree.focus_set()
            children = self._alert_tree.get_children()
            if children:
                self._alert_tree.see(children[-1])
                self._alert_tree.selection_set(children[-1])
        except tk.TclError:
            pass
