"""HTTP server: serves the mobile dictation page and handles auth + text injection."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import state
import injection
from utils import make_pin, is_lan_client

# ---------------------------------------------------------------------------
# Mobile web page (PIN injected per request via .format())
# ---------------------------------------------------------------------------
_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dictate</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: sans-serif; background: #1a1a1a; color: #eee;
         display: flex; flex-direction: column; height: 100dvh; padding: 12px; gap: 10px; }}
  #pin-view {{ display: flex; flex-direction: column; align-items: center;
               justify-content: center; flex: 1; gap: 16px; }}
  #pin-view h1 {{ font-size: 3rem; letter-spacing: .3em; }}
  #pin-view p  {{ color: #aaa; font-size: 0.9rem; text-align: center; }}
  #main-view   {{ display: none; flex-direction: column; flex: 1; gap: 10px; }}
  #ended-view  {{ display: none; flex-direction: column; flex: 1; gap: 10px; }}
  textarea {{ flex: 1; width: 100%; background: #2a2a2a; color: #eee;
              border: 1px solid #444; border-radius: 8px; padding: 10px;
              font-size: 0.85rem; resize: none; }}
  textarea:read-only {{ opacity: 0.6; }}
  .btn       {{ width: 100%; padding: 18px; font-size: 1.1rem; border: none;
                border-radius: 8px; cursor: pointer; font-weight: bold; }}
  .btn-send  {{ background: #2e7d32; color: #fff; }}
  .btn-send:active {{ background: #1b5e20; }}
  .btn-clear {{ background: #333; color: #ccc; padding: 12px; font-size: 0.85rem; }}
  .ended-msg {{ color: #e57373; text-align: center; padding: 8px; }}
</style>
</head>
<body>

<div id="pin-view">
  <p>PIN eingeben im Desktop-Fenster:</p>
  <h1>{pin}</h1>
  <p>Warte auf Bestätigung&hellip;</p>
</div>

<div id="main-view">
  <textarea id="text" placeholder="Text eingeben&hellip;"></textarea>
  <button class="btn btn-send" onclick="sendText()">Senden</button>
  <button class="btn btn-clear" onclick="clearText()">Leeren</button>
</div>

<div id="ended-view">
  <p class="ended-msg">Sitzung beendet</p>
  <textarea id="saved-text" readonly></textarea>
</div>

<script>
const PIN = "{pin}";
let authorized = false;

function poll() {{
  fetch("/status?pin=" + PIN)
    .then(r => r.json())
    .then(data => {{
      if (data.status === "authorized" && !authorized) {{
        authorized = true;
        document.getElementById("pin-view").style.display = "none";
        document.getElementById("main-view").style.display = "flex";
        setTimeout(poll, 5000);
      }} else if (data.status === "ended") {{
        const text = document.getElementById("text").value;
        document.getElementById("saved-text").value = text;
        document.getElementById("pin-view").style.display  = "none";
        document.getElementById("main-view").style.display = "none";
        document.getElementById("ended-view").style.display = "flex";
      }} else if (data.status === "authorized") {{
        setTimeout(poll, 5000);
      }} else {{
        setTimeout(poll, 1000);
      }}
    }})
    .catch(() => setTimeout(poll, 2000));
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
  if (confirm("Text wirklich löschen?")) {{
    document.getElementById("text").value = "";
  }}
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
        if not is_lan_client(self.client_address[0], _Handler.server_ip):
            self.send_error(403, "LAN only")
            return False
        return True

    def do_GET(self):
        if not self._check_lan():
            return

        if self.path == "/":
            pin = make_pin()
            data = _HTML.format(pin=pin).encode("utf-8")
            self._respond(200, "text/html; charset=utf-8", data)

        elif self.path.startswith("/status?pin="):
            pin = self.path.split("=", 1)[1]
            resp = json.dumps({"status": state.check_pin(pin)}).encode()
            self._respond(200, "application/json", resp)

        else:
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
                self.send_error(400)
                return

            if state.check_pin(pin) != "authorized":
                self.send_error(403, "Not authorized")
                return

            injection.inject_text(text)
            state.gui_queue.put(("last_text", text))
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
    return server


def stop(server: HTTPServer) -> None:
    threading.Thread(target=server.shutdown, daemon=True).start()
    state.clear_auth()
