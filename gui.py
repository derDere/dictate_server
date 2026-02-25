"""Tkinter GUI — small status/control window."""
import queue
import tkinter as tk
from http.server import HTTPServer

import qrcode
from PIL import ImageTk

import server as srv
import state
from utils import get_lan_ip


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Dictate Server")
        self.root.resizable(False, False)

        self._http: HTTPServer | None = None
        self._qr_image = None          # hold reference to prevent GC

        self.lan_ip = get_lan_ip()
        self.url = f"http://{self.lan_ip}:{state.PORT}"

        self._build_ui()
        self._poll_queue()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        p = {"padx": 8, "pady": 4}

        # QR code
        self._qr_label = tk.Label(self.root, bg="white")
        self._qr_label.pack(**p)
        self._render_qr()

        # URL
        tk.Label(self.root, text=self.url, fg="#555",
                 font=("Courier", 9)).pack(**p)

        # PIN row: label | entry | Connect button
        pin_row = tk.Frame(self.root)
        pin_row.pack(fill="x", **p)
        tk.Label(pin_row, text="PIN:").pack(side="left")
        self._pin_var = tk.StringVar()
        pin_entry = tk.Entry(pin_row, textvariable=self._pin_var,
                             width=8, font=("Courier", 11))
        pin_entry.pack(side="left", padx=4)
        pin_entry.bind("<Return>", lambda _: self._on_connect())
        tk.Button(pin_row, text="Connect",
                  command=self._on_connect).pack(side="left")

        # Last injected text
        self._last_var = tk.StringVar(value="—")
        tk.Label(self.root, textvariable=self._last_var, fg="#333",
                 font=("TkDefaultFont", 9), wraplength=220,
                 justify="left").pack(fill="x", **p)

        # Start / Stop button
        self._btn_text = tk.StringVar(value="Start")
        self._toggle_btn = tk.Button(self.root, textvariable=self._btn_text,
                                     width=18, command=self._on_toggle)
        self._toggle_btn.pack(**p)

    def _render_qr(self):
        qr = qrcode.QRCode(box_size=3, border=2)
        qr.add_data(self.url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        self._qr_image = ImageTk.PhotoImage(img)
        self._qr_label.configure(image=self._qr_image)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def _on_toggle(self):
        if self._http is None:
            self._http = srv.start(self.lan_ip)
            self._btn_text.set("Stop")
            self._toggle_btn.configure(fg="red")
        else:
            srv.stop(self._http)
            self._http = None
            self._btn_text.set("Start")
            self._toggle_btn.configure(fg="black")

    def _on_connect(self):
        pin = self._pin_var.get().strip()
        if pin:
            state.authorize(pin)

    # ------------------------------------------------------------------
    # Background → GUI updates
    # ------------------------------------------------------------------
    def _poll_queue(self):
        try:
            while True:
                kind, value = state.gui_queue.get_nowait()
                if kind == "last_text":
                    short = value[:60] + ("…" if len(value) > 60 else "")
                    self._last_var.set(short)
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)
