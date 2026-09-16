"""
Scaner Soler Pro — Pestaña AI Copilot (7ª pestaña).

Proporciona un chat con Soler AI, botones de acción rápida
y un indicador de estado del backend.
"""
from __future__ import annotations

import queue
import re
import threading
import time
import tkinter as tk
from tkinter import simpledialog, ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..integration.backend_client import BackendClient

# ── Paleta ────────────────────────────────────────────────────────────────────
DARK_BG  = "#1e1e2e"
ACCENT   = "#89b4fa"
TAB_BG   = "#181825"
FG       = "#cdd6f4"
ENTRY_BG = "#313244"
GREEN    = "#a6e3a1"
RED      = "#f38ba8"
YELLOW   = "#f9e2af"
SUBTEXT  = "#585b70"


def _flatten_markdown(text: str) -> str:
    """Convierte markdown básico a texto plano (Tkinter no renderiza markdown)."""
    # Elimina encabezados #
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Negrita / cursiva
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}(.+?)_{1,3}", r"\1", text)
    # Código inline
    text = re.sub(r"`(.+?)`", r"\1", text)
    # Bloques de código
    text = re.sub(r"```.*?```", lambda m: m.group(0).replace("```", ""), text, flags=re.DOTALL)
    return text.strip()


# ── Respuestas locales (modo offline) ─────────────────────────────────────────
_LOCAL_RESPONSES: list[tuple[str, str]] = [
    ("dtc|código|fault|code",
     "Sin conexión al backend. Para consultar un DTC usa la pestaña Diagnósticos "
     "o activa el servidor con `launch_supersystem.py`."),
    ("sensor|rpm|temperatura|temp|presión",
     "Modo offline: los sensores en vivo requieren el backend FastAPI. "
     "Puedes ver datos simulados en la pestaña Datos en Vivo."),
    ("reparar|reparación|repair|guía|guide",
     "Modo offline: las guías de reparación detalladas están en la pestaña Conocimiento."),
    ("salud|health|score",
     "Modo offline: el health score requiere el backend. Revisa la pestaña Diagnósticos."),
]

_LOCAL_DEFAULT = (
    "Soler AI está en modo offline (backend no disponible). "
    "Las pestañas Diagnósticos y Conocimiento funcionan sin conexión. "
    "Para respuestas AI completas, inicia el backend con `launch_supersystem.py`."
)


def _local_response(message: str) -> str:
    msg_low = message.lower()
    for pattern, reply in _LOCAL_RESPONSES:
        if re.search(pattern, msg_low):
            return reply
    return _LOCAL_DEFAULT


# ── Clase principal ───────────────────────────────────────────────────────────
class AICopilotTab(ttk.Frame):
    """Séptima pestaña: chat con Soler AI + acciones rápidas."""

    def __init__(self, parent: tk.Widget, backend_client: "BackendClient | None" = None, **kw):
        super().__init__(parent, **kw)
        self.client = backend_client
        self._msg_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._last_dtcs: list[str] = []

        self._build_ui()
        self._schedule_status_check()
        self._poll_queue()

    # ── Construcción de la UI ─────────────────────────────────────────────────

    def _build_ui(self):
        self.configure(style="TFrame")

        # ── Barra superior: título + estado backend ──────────────────────────
        top_bar = tk.Frame(self, bg=TAB_BG, pady=4)
        top_bar.pack(fill="x")

        tk.Label(
            top_bar, text="🤖  SOLER AI COPILOT",
            bg=TAB_BG, fg=ACCENT,
            font=("Consolas", 12, "bold"),
        ).pack(side="left", padx=12)

        self._status_dot = tk.Label(
            top_bar, text="●  Verificando…",
            bg=TAB_BG, fg=YELLOW,
            font=("Consolas", 9),
        )
        self._status_dot.pack(side="right", padx=12)

        # ── Contenido principal: chat izquierda, panel derecha ───────────────
        content = tk.Frame(self, bg=DARK_BG)
        content.pack(fill="both", expand=True, padx=6, pady=6)

        # Panel lateral derecho
        side = tk.Frame(content, bg=TAB_BG, width=190, padx=8, pady=8)
        side.pack(side="right", fill="y", padx=(6, 0))
        side.pack_propagate(False)
        self._build_side_panel(side)

        # Área de chat
        chat_frame = tk.Frame(content, bg=DARK_BG)
        chat_frame.pack(side="left", fill="both", expand=True)
        self._build_chat_area(chat_frame)

    def _build_chat_area(self, parent: tk.Frame):
        # Texto de conversación
        txt_frame = tk.Frame(parent, bg=DARK_BG)
        txt_frame.pack(fill="both", expand=True)

        sb = ttk.Scrollbar(txt_frame, orient="vertical")
        sb.pack(side="right", fill="y")

        self._chat_text = tk.Text(
            txt_frame,
            bg=ENTRY_BG, fg=FG,
            font=("Consolas", 10),
            wrap="word",
            state="disabled",
            relief="flat",
            yscrollcommand=sb.set,
            padx=10, pady=8,
            cursor="arrow",
            insertbackground=FG,
        )
        self._chat_text.pack(fill="both", expand=True)
        sb.config(command=self._chat_text.yview)

        # Tags de color
        self._chat_text.tag_configure("user_tag",  foreground=ACCENT, font=("Consolas", 10, "bold"))
        self._chat_text.tag_configure("ai_tag",    foreground=GREEN,  font=("Consolas", 10, "bold"))
        self._chat_text.tag_configure("sys_tag",   foreground=YELLOW, font=("Consolas", 9, "italic"))
        self._chat_text.tag_configure("body_tag",  foreground=FG,     font=("Consolas", 10))

        # Barra de entrada
        entry_frame = tk.Frame(parent, bg=TAB_BG, pady=6, padx=6)
        entry_frame.pack(fill="x")

        self._entry_var = tk.StringVar()
        entry = ttk.Entry(entry_frame, textvariable=self._entry_var, font=("Consolas", 10))
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        entry.bind("<Return>", lambda _: self._send_user_message())

        ttk.Button(
            entry_frame, text="Enviar",
            style="Accent.TButton",
            command=self._send_user_message,
        ).pack(side="right")

        # Mensaje de bienvenida
        self._append_system(
            "Bienvenido a Soler AI Copilot. Escribe tu pregunta o usa los botones "
            "de acción rápida para diagnósticos, guías y análisis."
        )

    def _build_side_panel(self, parent: tk.Frame):
        tk.Label(
            parent, text="Acciones Rápidas",
            bg=TAB_BG, fg=ACCENT,
            font=("Consolas", 10, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        buttons = [
            ("🔍  Diagnosticar DTCs",      self._action_diagnose_dtcs),
            ("📋  Guía de reparación",     self._action_repair_guide),
            ("🔧  Recomendar herramientas", self._action_recommend_tools),
            ("❤️  Estado del motor",       self._action_engine_health),
        ]
        for label, cmd in buttons:
            ttk.Button(parent, text=label, command=cmd).pack(
                fill="x", pady=3, ipady=4
            )

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=10)

        tk.Label(
            parent, text="Contexto del vehículo",
            bg=TAB_BG, fg=SUBTEXT,
            font=("Consolas", 9),
        ).pack(anchor="w")

        tk.Label(parent, text="Marca:", bg=TAB_BG, fg=FG,
                 font=("Consolas", 9)).pack(anchor="w", pady=(4, 0))
        self._make_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self._make_var,
                  font=("Consolas", 9)).pack(fill="x", pady=2)

        tk.Label(parent, text="Modelo:", bg=TAB_BG, fg=FG,
                 font=("Consolas", 9)).pack(anchor="w")
        self._model_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self._model_var,
                  font=("Consolas", 9)).pack(fill="x", pady=2)

    # ── Escritura en el chat ──────────────────────────────────────────────────

    def _append(self, speaker: str, text: str, tag: str, body_tag: str = "body_tag"):
        self._chat_text.configure(state="normal")
        self._chat_text.insert("end", f"\n{speaker}\n", tag)
        self._chat_text.insert("end", text + "\n", body_tag)
        self._chat_text.configure(state="disabled")
        self._chat_text.see("end")

    def _append_user(self, text: str):
        self._append("Tú:", text, "user_tag")

    def _append_ai(self, text: str):
        self._append("Soler AI:", _flatten_markdown(text), "ai_tag")

    def _append_system(self, text: str):
        self._chat_text.configure(state="normal")
        self._chat_text.insert("end", f"\n[Sistema] {text}\n", "sys_tag")
        self._chat_text.configure(state="disabled")
        self._chat_text.see("end")

    # ── Envío de mensajes ─────────────────────────────────────────────────────

    def _send_user_message(self):
        msg = self._entry_var.get().strip()
        if not msg:
            return
        self._entry_var.set("")
        self._append_user(msg)
        self._dispatch_chat(msg)

    def _dispatch_chat(self, message: str, context: dict | None = None):
        """Lanza el chat en un hilo de fondo."""
        def _worker():
            if self.client and self.client.is_online():
                result = self.client.chat(message, context)
                reply = result if result else "Sin respuesta del servidor."
            else:
                reply = _local_response(message)
            self._msg_queue.put(("ai", reply))

        threading.Thread(target=_worker, daemon=True).start()

    # ── Poll de la cola (UI thread) ───────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                kind, data = self._msg_queue.get_nowait()
                if kind == "ai":
                    self._append_ai(data)
                elif kind == "sys":
                    self._append_system(data)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    # ── Acciones rápidas ──────────────────────────────────────────────────────

    def _action_diagnose_dtcs(self):
        dtcs = self._last_dtcs
        make = self._make_var.get().strip()

        if not dtcs:
            self._append_system("No hay DTCs registrados del último scan. "
                                 "Ejecuta un diagnóstico en la pestaña Diagnósticos primero.")
            return

        msg = f"Tengo los siguientes DTCs: {', '.join(dtcs)}. ¿Qué significan y cuál es el diagnóstico?"
        self._append_user(msg)

        def _worker():
            if self.client and self.client.is_online():
                advice = self.client.get_expert_advice(
                    scenario=f"DTCs presentes: {', '.join(dtcs)}",
                    dtc_codes=dtcs,
                    make=make,
                )
                if isinstance(advice, dict) and "error" not in advice:
                    reply = advice.get("advice") or advice.get("response") or str(advice)
                else:
                    # Fallback: chat normal
                    reply = self.client.chat(msg) or _local_response(msg)
            else:
                reply = _local_response(msg)
            self._msg_queue.put(("ai", reply))

        threading.Thread(target=_worker, daemon=True).start()

    def _action_repair_guide(self):
        code = simpledialog.askstring(
            "Código DTC",
            "Ingresa el código DTC para obtener la guía de reparación:",
            parent=self,
        )
        if not code:
            return
        code = code.strip().upper()
        make = self._make_var.get().strip()
        msg = f"Necesito la guía de reparación para {code}" + (f" en {make}" if make else "")
        self._append_user(msg)

        def _worker():
            if self.client and self.client.is_online():
                guide = self.client.get_repair_guide(code, make)
                reply = guide if guide else _local_response(msg)
            else:
                reply = _local_response(msg)
            self._msg_queue.put(("ai", reply))

        threading.Thread(target=_worker, daemon=True).start()

    def _action_recommend_tools(self):
        make = self._make_var.get().strip()
        model = self._model_var.get().strip()
        vehicle = f"{make} {model}".strip() or "vehículo desconocido"
        msg = f"¿Qué herramientas y equipos recomiendas para diagnosticar un {vehicle}?"
        self._append_user(msg)

        def _worker():
            if self.client and self.client.is_online():
                advice = self.client.get_expert_advice(
                    scenario=f"Selección de herramientas para {vehicle}",
                    make=make,
                )
                if isinstance(advice, dict) and "error" not in advice:
                    reply = advice.get("advice") or advice.get("response") or str(advice)
                else:
                    reply = self.client.chat(msg) or _local_response(msg)
            else:
                reply = _local_response(msg)
            self._msg_queue.put(("ai", reply))

        threading.Thread(target=_worker, daemon=True).start()

    def _action_engine_health(self):
        msg = "Dame un resumen del estado de salud del motor con los sensores actuales."
        self._append_user(msg)

        def _worker():
            if self.client and self.client.is_online():
                health = self.client.get_health_score()
                sensors = self.client.get_live_sensors()

                parts: list[str] = []
                if isinstance(health, dict) and "error" not in health:
                    score = health.get("score") or health.get("health_score")
                    if score is not None:
                        parts.append(f"Health Score: {score}/100")
                    detail = health.get("details") or health.get("summary") or ""
                    if detail:
                        parts.append(str(detail))

                if isinstance(sensors, dict) and "error" not in sensors:
                    sensor_lines = [
                        f"  {k}: {v}"
                        for k, v in sensors.items()
                        if k not in ("error",)
                    ]
                    if sensor_lines:
                        parts.append("Sensores en vivo:\n" + "\n".join(sensor_lines[:12]))

                if parts:
                    reply = "\n".join(parts)
                else:
                    reply = self.client.chat(msg) or _local_response(msg)
            else:
                reply = _local_response(msg)
            self._msg_queue.put(("ai", reply))

        threading.Thread(target=_worker, daemon=True).start()

    # ── Estado del backend ────────────────────────────────────────────────────

    def _schedule_status_check(self):
        self._check_backend_status()
        self.after(5000, self._schedule_status_check)

    def _check_backend_status(self):
        def _worker():
            online = bool(self.client and self.client.is_online())
            self._msg_queue.put(("_status", "online" if online else "offline"))

        threading.Thread(target=_worker, daemon=True).start()
        # Procesar el resultado directamente en el poll
        # (el poll ya consume la cola; añadimos un handler especial)

    def _poll_queue(self):  # type: ignore[override]  # redefinición con status
        try:
            while True:
                kind, data = self._msg_queue.get_nowait()
                if kind == "ai":
                    self._append_ai(data)
                elif kind == "sys":
                    self._append_system(data)
                elif kind == "_status":
                    self._update_status_dot(data == "online")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _update_status_dot(self, online: bool):
        if online:
            self._status_dot.configure(text="●  Backend online", fg=GREEN)
        else:
            self._status_dot.configure(text="●  Backend offline", fg=RED)

    # ── API pública ───────────────────────────────────────────────────────────

    def set_dtcs(self, dtc_list: list[str]):
        """Llamado desde otras pestañas para informar DTCs activos."""
        self._last_dtcs = list(dtc_list)
