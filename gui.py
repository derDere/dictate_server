"""Tkinter GUI -- small status/control window."""
import queue
import tkinter as tk
from tkinter import ttk
from http.server import HTTPServer

import qrcode
import sv_ttk
from PIL import Image, ImageTk

import config as cfg
import server as srv
import state
from gateway_client import GatewayClient
from utils import get_lan_ip
from state import _log

# Status label text and colour for each gateway state
_GW_LABELS: dict[str, tuple[str, str]] = {
    "connecting":   ("Verbinde...",                   "#888888"),
    "waiting":      ("Verbunden – Code eingeben:", "#4caf50"),
    "pairing":      ("Warte auf Best\xe4tigung...",   "#888888"),
    "active":       ("Aktive Sitzung (E2E)",          "#4caf50"),
    "pair_failed":  ("Falscher Code – nochmal:", "#ef5350"),
    "disconnected": ("Nicht verbunden",               "#555555"),
}


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Dictate Server")
        self.root.resizable(False, False)

        sv_ttk.set_theme("dark")
        self.root.configure(padx=10, pady=10)

        self._http: HTTPServer | None = None
        self._qr_image = None
        self._last_text = ""
        self._gw_enabled = False
        self._gateway = GatewayClient()

        self.lan_ip = get_lan_ip()
        self.url = f"http://{self.lan_ip}:{state.PORT}"
        _log(f"GUI    LAN IP detected: {self.lan_ip}")

        self._set_icon()
        self._build_ui()
        self._center_window()
        self._on_toggle()
        self._poll_queue()

        # Restore gateway state from last session
        if cfg.get("gateway_enabled") and cfg.get("gateway_url"):
            self._gw_enabled = True
            self._gw_toggle_btn.configure(
                bg="#14532d", fg="#86efac", activebackground="#166534", text="ON"
            )
            self._gateway.connect(cfg.get("gateway_url"))

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        p = {"padx": 8, "pady": 4}

        # QR code (bg matches dark theme)
        self._qr_label = tk.Label(self.root)
        self._qr_label.pack(**p)
        self._render_qr()

        # URL (read-only, selectable and copyable)
        url_entry = ttk.Entry(self.root, font=("Courier", 9), justify="center")
        url_entry.insert(0, self.url)
        url_entry.configure(state="readonly")
        url_entry.pack(fill="x", **p)

        # PIN row: label | entry | Connect button (centered)
        pin_row = ttk.Frame(self.root)
        pin_row.pack(**p)
        ttk.Label(pin_row, text="PIN:").pack(side="left")
        self._pin_var = tk.StringVar()
        pin_entry = ttk.Entry(pin_row, textvariable=self._pin_var,
                              width=8, font=("Courier", 11))
        pin_entry.pack(side="left", padx=4)
        pin_entry.bind("<Return>", lambda _: self._on_connect())
        ttk.Button(pin_row, text="Connect",
                   command=self._on_connect).pack(side="left")

        # Last text button
        self._last_btn = ttk.Button(self.root, text="Last Text",
                                    width=18, command=self._show_last_text)
        self._last_btn.pack(**p)

        # Start / Stop button
        self._btn_text = tk.StringVar(value="Start")
        self._toggle_btn = ttk.Button(self.root, textvariable=self._btn_text,
                                      width=18, command=self._on_toggle)
        self._toggle_btn.pack(**p)

        # ── Online Gateway section ──────────────────────────────────────
        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=8, pady=(6, 2))

        gw_outer = ttk.Frame(self.root)
        gw_outer.pack(fill="x", padx=8, pady=(2, 6))

        ttk.Label(gw_outer, text="Online Gateway",
                  font=("TkDefaultFont", 8, "bold")).pack(anchor="w")

        # Row 1: URL entry + ON/OFF toggle
        url_row = ttk.Frame(gw_outer)
        url_row.pack(fill="x", pady=(2, 0))

        self._gw_url_var = tk.StringVar(value=cfg.get("gateway_url"))
        gw_url_entry = ttk.Entry(url_row, textvariable=self._gw_url_var,
                                  font=("Courier", 8))
        gw_url_entry.pack(side="left", fill="x", expand=True)
        gw_url_entry.bind("<FocusOut>", self._on_gw_url_change)
        gw_url_entry.bind("<Return>",   self._on_gw_url_change)

        self._gw_toggle_btn = tk.Button(
            url_row, text="OFF", width=5,
            bg="#7f1d1d", fg="#fca5a5",
            activebackground="#991b1b", activeforeground="#fca5a5",
            relief="flat", font=("TkDefaultFont", 9, "bold"),
            command=self._on_gw_toggle,
        )
        self._gw_toggle_btn.pack(side="left", padx=(4, 0))

        # Row 2: status + code entry + Pair button
        code_row = ttk.Frame(gw_outer)
        code_row.pack(fill="x", pady=(3, 0))

        self._gw_status_var = tk.StringVar(value="Nicht verbunden")
        self._gw_status_lbl = ttk.Label(
            code_row, textvariable=self._gw_status_var,
            font=("TkDefaultFont", 8), foreground="#555555",
        )
        self._gw_status_lbl.pack(side="left", fill="x", expand=True)

        self._gw_pair_btn = ttk.Button(
            code_row, text="Pair", width=5,
            command=self._on_gw_pair, state="disabled",
        )
        self._gw_pair_btn.pack(side="right")

        self._gw_code_var = tk.StringVar()
        self._gw_code_entry = ttk.Entry(
            code_row, textvariable=self._gw_code_var,
            width=8, font=("Courier", 10), state="disabled",
        )
        self._gw_code_entry.bind("<Return>", lambda _: self._on_gw_pair())
        self._gw_code_entry.pack(side="right", padx=(0, 4))

    def _set_icon(self):
        try:
            img = Image.open("icon.png")
            self._icon_image = ImageTk.PhotoImage(img)
            self.root.iconphoto(True, self._icon_image)
        except Exception:
            pass

    def _render_qr(self):
        # Pick up the actual background colour from the theme
        bg = ttk.Style().lookup("TFrame", "background") or "#1c1c1c"
        qr = qrcode.QRCode(box_size=3, border=2)
        qr.add_data(self.url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="white", back_color=bg)
        self._qr_image = ImageTk.PhotoImage(img)
        self._qr_label.configure(image=self._qr_image, bg=bg)

    def _center_window(self):
        self.root.update_idletasks()
        w = self.root.winfo_reqwidth() + 70
        h = self.root.winfo_reqheight()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    # ------------------------------------------------------------------
    # LAN server event handlers (unchanged)
    # ------------------------------------------------------------------
    def _on_toggle(self):
        if self._http is None:
            _log("GUI    Start")
            self._http = srv.start(self.lan_ip)
            self._btn_text.set("Stop")
        else:
            _log("GUI    Stop")
            srv.stop(self._http)
            self._http = None
            self._btn_text.set("Start")

    def _on_connect(self):
        pin = self._pin_var.get().strip()
        if pin:
            _log(f"GUI    Connect PIN={pin!r}")
            state.authorize(pin)

    def _show_last_text(self):
        if not self._last_text:
            return
        win = tk.Toplevel(self.root)
        win.title("Last text")
        win.resizable(True, True)
        txt = tk.Text(win, wrap="word", width=55, height=18,
                      font=("TkDefaultFont", 10), padx=8, pady=8)
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        txt.insert("1.0", self._last_text)
        txt.configure(state="disabled")

    # ------------------------------------------------------------------
    # Gateway event handlers
    # ------------------------------------------------------------------
    def _on_gw_url_change(self, _event=None):
        cfg.set("gateway_url", self._gw_url_var.get().strip())

    def _on_gw_toggle(self):
        if self._gw_enabled:
            # Turn OFF
            self._gw_enabled = False
            self._gw_toggle_btn.configure(
                bg="#7f1d1d", fg="#fca5a5", activebackground="#991b1b", text="OFF"
            )
            self._gateway.disconnect()
            self._set_gw_status("disconnected")
            cfg.set("gateway_enabled", False)
        else:
            # Turn ON — require URL first
            url = self._gw_url_var.get().strip()
            if not url:
                return
            self._gw_enabled = True
            self._gw_toggle_btn.configure(
                bg="#14532d", fg="#86efac", activebackground="#166534", text="ON"
            )
            self._gateway.connect(url)
            cfg.set("gateway_url", url)
            cfg.set("gateway_enabled", True)

    def _on_gw_pair(self):
        code = self._gw_code_var.get().strip().upper()
        if code:
            self._gateway.submit_code(code)
            self._gw_code_var.set("")

    def _set_gw_status(self, status: str):
        label, color = _GW_LABELS.get(status, (status, "#888888"))
        self._gw_status_var.set(label)
        self._gw_status_lbl.configure(foreground=color)
        # Code entry enabled only when we're waiting for user to enter a code
        code_active = status in ("waiting", "pair_failed")
        new_state = "normal" if code_active else "disabled"
        self._gw_code_entry.configure(state=new_state)
        self._gw_pair_btn.configure(state=new_state)
        if code_active:
            self._gw_code_entry.focus_set()

    # ------------------------------------------------------------------
    # Background -> GUI updates
    # ------------------------------------------------------------------
    def _poll_queue(self):
        try:
            while True:
                kind, value = state.gui_queue.get_nowait()
                if kind == "last_text":
                    self._last_text = value
                elif kind == "gw_status":
                    self._set_gw_status(value)
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)
