"""Tkinter GUI -- small status/control window."""
import queue
import tkinter as tk
from http.server import HTTPServer

import qrcode
from PIL import ImageTk

import server as srv
import state
from utils import get_lan_ip
from state import _log


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Dictate Server")
        self.root.resizable(False, False)

        self._http: HTTPServer | None = None
        self._qr_image = None      # hold reference to prevent GC
        self._last_text = ""

        self.lan_ip = get_lan_ip()
        self.url = f"http://{self.lan_ip}:{state.PORT}"
        _log(f"GUI    LAN IP detected: {self.lan_ip}")

        self._build_ui()
        self._center_window()
        self._on_toggle()      # auto-start server
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

        # URL (read-only, selectable and copyable)
        url_entry = tk.Entry(self.root, font=("Courier", 9), fg="#555",
                             relief="flat", justify="center",
                             readonlybackground=self.root.cget("bg"))
        url_entry.insert(0, self.url)
        url_entry.configure(state="readonly")
        url_entry.pack(fill="x", **p)

        # PIN row: label | entry | Connect button (centered)
        pin_row = tk.Frame(self.root)
        pin_row.pack(**p)
        tk.Label(pin_row, text="PIN:").pack(side="left")
        self._pin_var = tk.StringVar()
        pin_entry = tk.Entry(pin_row, textvariable=self._pin_var,
                             width=8, font=("Courier", 11))
        pin_entry.pack(side="left", padx=4)
        pin_entry.bind("<Return>", lambda _: self._on_connect())
        tk.Button(pin_row, text="Connect",
                  command=self._on_connect).pack(side="left")

        # Last text button
        self._last_btn = tk.Button(self.root, text="Last Text",
                                   width=18, command=self._show_last_text)
        self._last_btn.pack(**p)

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

    def _center_window(self):
        self.root.update_idletasks()
        w = self.root.winfo_reqwidth() + 70
        h = self.root.winfo_reqheight()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def _on_toggle(self):
        if self._http is None:
            _log("GUI    Start")
            self._http = srv.start(self.lan_ip)
            self._btn_text.set("Stop")
            self._toggle_btn.configure(fg="red")
        else:
            _log("GUI    Stop")
            srv.stop(self._http)
            self._http = None
            self._btn_text.set("Start")
            self._toggle_btn.configure(fg="black")

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
    # Background -> GUI updates
    # ------------------------------------------------------------------
    def _poll_queue(self):
        try:
            while True:
                kind, value = state.gui_queue.get_nowait()
                if kind == "last_text":
                    self._last_text = value
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)
