"""HTTP server: serves the mobile dictation page and handles auth + text injection."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

_MANIFEST = json.dumps({
    "name": "Dictate",
    "short_name": "Dictate",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#1a1a1a",
    "theme_color": "#1a1a1a",
    "orientation": "portrait"
})

import state
import injection
from utils import make_pin, is_lan_client
from state import _log

# ---------------------------------------------------------------------------
# Mobile web page (PIN injected per request via .format())
# ---------------------------------------------------------------------------
_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<meta name="apple-mobile-web-app-title" content="Dictate">
<meta name="theme-color" content="#1a1a1a">
<link rel="manifest" href="/manifest.json">
<title>Dictate</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; touch-action: manipulation; }}
  html {{ -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }}
  html, body {{ width: 100%; overflow: hidden; background: #1a1a1a; color: #eee; font-family: sans-serif; }}
  body {{ display: flex; flex-direction: column; }}

  #pin-view {{
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    flex: 1; gap: 16px; padding: 20px;
  }}
  #pin-view h1 {{ font-size: 3rem; letter-spacing: .3em; }}
  #pin-view p  {{ color: #aaa; font-size: 0.9rem; text-align: center; }}

  #main-view {{ display: none; flex-direction: column; flex: 1; min-height: 0; }}
  #ended-view {{ display: none; flex-direction: column; flex: 1; min-height: 0; gap: 8px; padding: 8px; }}

  .btn-row {{ display: flex; gap: 6px; padding: 8px; flex-shrink: 0; }}
  .btn {{
    flex: 1; padding: 16px 0; font-size: 1rem;
    border: none; border-radius: 8px; cursor: pointer; font-weight: bold;
  }}
  .btn-send  {{ background: #2e7d32; color: #fff; }}
  .btn-send:active {{ background: #1b5e20; }}
  .btn-clear {{ background: #444; color: #ccc; }}
  .btn-enter {{ background: #1565c0; color: #fff; }}

  textarea {{
    flex: 1; min-height: 0; width: 100%;
    background: #1a1a1a; color: #eee;
    border: none; outline: none;
    padding: 8px; font-size: 0.9rem; resize: none;
    display: block;
  }}
  textarea:read-only {{ opacity: 0.6; }}
  .ended-msg {{ color: #e57373; text-align: center; padding: 8px; flex-shrink: 0; }}
  #reload-row {{ display: none; }}
  .btn-reload {{ background: #555; color: #fff; }}
</style>
</head>
<body>

<div id="pin-view">
  <p>Enter this PIN in the desktop window:</p>
  <h1>{pin}</h1>
  <p>Waiting for confirmation...</p>
</div>

<div id="main-view">
  <div class="btn-row" id="btn-row">
    <button class="btn btn-send"  onclick="sendText()">Send</button>
    <button class="btn btn-clear" onclick="clearText()">Clear</button>
    <button class="btn btn-enter" onclick="pressEnter()">Enter</button>
  </div>
  <div class="btn-row" id="reload-row">
    <button class="btn btn-reload" onclick="window.location.reload()">Connection lost &mdash; Reload</button>
  </div>
  <textarea id="text" placeholder="Use your phone's dictate function to enter text..."></textarea>
</div>

<div id="ended-view">
  <p class="ended-msg">Session ended</p>
  <textarea id="saved-text" readonly></textarea>
</div>

<script>
const PIN = "{pin}";
let authorized = false;
let failCount = 0;

function showOffline() {{
  document.getElementById("btn-row").style.display    = "none";
  document.getElementById("reload-row").style.display = "flex";
}}

function fitViewport() {{
  const h = window.visualViewport ? window.visualViewport.height : window.innerHeight;
  document.body.style.height = h + "px";
}}
fitViewport();
if (window.visualViewport) {{
  window.visualViewport.addEventListener("resize", fitViewport);
  window.visualViewport.addEventListener("scroll", fitViewport);
}}

function poll() {{
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 1500);
  fetch("/status?pin=" + PIN, {{ signal: ctrl.signal }})
    .then(r => {{ clearTimeout(timer); return r.json(); }})
    .then(data => {{
      failCount = 0;
      if (data.status === "authorized" && !authorized) {{
        authorized = true;
        document.getElementById("pin-view").style.display = "none";
        document.getElementById("main-view").style.display = "flex";
        setTimeout(poll, 2000);
      }} else if (data.status === "ended") {{
        const text = document.getElementById("text").value;
        document.getElementById("saved-text").value = text;
        document.getElementById("pin-view").style.display  = "none";
        document.getElementById("main-view").style.display = "none";
        document.getElementById("ended-view").style.display = "flex";
      }} else if (data.status === "authorized") {{
        setTimeout(poll, 2000);
      }} else {{
        setTimeout(poll, 1000);
      }}
    }})
    .catch(() => {{ clearTimeout(timer); showOffline(); }});
}}

function sendText() {{
  const text = document.getElementById("text").value.trim();
  if (!text) return;
  fetch("/send", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{pin: PIN, text: text}})
  }}).then(r => {{
    if (r.ok) document.getElementById("text").value = "";
  }});
}}

function clearText() {{
  if (confirm("Clear all text?")) {{
    document.getElementById("text").value = "";
  }}
}}

function pressEnter() {{
  fetch("/enter", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{pin: PIN}})
  }});
}}

poll();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    server_ip: str = "127.0.0.1"

    def log_message(self, *args):
        pass  # suppress default stderr output

    def _check_lan(self) -> bool:
        client = self.client_address[0]
        if not is_lan_client(client, _Handler.server_ip):
            _log(f"SERVER blocked non-LAN client {client} (server={_Handler.server_ip})")
            self.send_error(403, "LAN only")
            return False
        return True

    def do_GET(self):
        if not self._check_lan():
            return

        if self.path == "/":
            pin = make_pin()
            _log(f"SERVER GET /  new PIN {pin} for {self.client_address[0]}")
            data = _HTML.format(pin=pin).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return

        elif self.path.startswith("/status?pin="):
            pin = self.path.split("=", 1)[1]
            status = state.check_pin(pin)
            if status != "pending":
                _log(f"SERVER GET /status pin={pin} = {status}")
            resp = json.dumps({"status": status}).encode()
            self._respond(200, "application/json", resp)

        elif self.path == "/manifest.json":
            self._respond(200, "application/manifest+json", _MANIFEST.encode())

        else:
            _log(f"SERVER GET {self.path} 404")
            self.send_error(404)

    def do_POST(self):
        if not self._check_lan():
            return

        if self.path == "/send":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length))
                pin  = payload.get("pin", "")
                text = payload.get("text", "")
            except Exception:
                _log("SERVER POST /send 400 bad JSON")
                self.send_error(400)
                return

            if state.check_pin(pin) != "authorized":
                _log(f"SERVER POST /send 403 pin={pin} not authorized")
                self.send_error(403, "Not authorized")
                return

            _log(f"SERVER POST /send injecting {len(text)} chars")
            injection.inject_text(text)
            state.gui_queue.put(("last_text", text))
            self._respond(200, "application/json", b"{}")

        elif self.path == "/enter":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length))
                pin = payload.get("pin", "")
            except Exception:
                self.send_error(400)
                return

            if state.check_pin(pin) != "authorized":
                self.send_error(403, "Not authorized")
                return

            _log("SERVER POST /enter")
            injection.press_enter()
            self._respond(200, "application/json", b"{}")

        else:
            self.send_error(404)

    def _respond(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def start(lan_ip: str) -> HTTPServer:
    _Handler.server_ip = lan_ip
    server = HTTPServer(("0.0.0.0", state.PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _log(f"SERVER started on {lan_ip}:{state.PORT}")
    return server


def stop(server: HTTPServer) -> None:
    _log("SERVER stopping")
    threading.Thread(target=server.shutdown, daemon=True).start()
    state.clear_auth()
