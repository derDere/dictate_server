#!/usr/bin/env python3
"""
Online Gateway Server for dictate_server.

Relays E2E-encrypted messages between the desktop dictate app (PC client)
and a phone browser.  The server never sees the pairing code or plaintext —
it only routes opaque encrypted blobs matched by a one-way SHA-256 identifier.

Usage:
    pip install aiohttp
    python online_server.py [--host 0.0.0.0] [--port 8766]

Deploy behind nginx / Caddy with WebSocket proxy support.  Example Caddy block:

    reverse_proxy /ws  localhost:8766
    reverse_proxy      localhost:8766
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from aiohttp import WSMsgType, web

# ---------------------------------------------------------------------------
# In-memory state (single asyncio event loop — no threading locks required)
# ---------------------------------------------------------------------------
active_pcs: set = set()      # WebSocket objects of registered PC clients
pending_phones: dict = {}    # identifier -> {ws, pubkey, expires_at}
sessions: dict = {}          # ws -> partner_ws  (stored for both directions)
pc_attempts: dict = {}       # ws -> int  (brute-force counter)

MAX_PAIR_ATTEMPTS = 10
PAIR_TTL = 120          # seconds a phone's code stays valid
CLEANUP_INTERVAL = 15   # seconds between expiry sweeps

# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------

async def index_handler(request: web.Request) -> web.Response:
    return web.Response(
        text=_PHONE_HTML,
        content_type="text/html",
        charset="utf-8",
        headers={"Cache-Control": "no-store"},
    )


async def has_pc_handler(request: web.Request) -> web.Response:
    return web.json_response({"available": len(active_pcs) > 0})


# ---------------------------------------------------------------------------
# WebSocket handler (shared by PC app and phone browser)
# ---------------------------------------------------------------------------

async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)

    is_pc = False

    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except (json.JSONDecodeError, ValueError):
                continue
            kind = data.get("type")

            # ── PC registers itself as available ──────────────────────────
            if kind == "pc_register":
                active_pcs.add(ws)
                pc_attempts[ws] = 0
                is_pc = True
                await ws.send_json({"type": "pc_registered"})

            # ── Phone announces a code (sends its public key + identifier) ─
            elif kind == "phone_pair":
                identifier = data.get("identifier", "")
                pubkey = data.get("phone_pubkey", "")
                if not identifier or not pubkey or len(identifier) != 64:
                    continue
                # Replace any stale entry for the same identifier
                pending_phones[identifier] = {
                    "ws": ws,
                    "pubkey": pubkey,
                    "expires_at": time.monotonic() + PAIR_TTL,
                }

            # ── PC submits the code the user typed in ─────────────────────
            elif kind == "pc_pair":
                if not is_pc:
                    continue
                fails = pc_attempts.get(ws, 0)
                if fails >= MAX_PAIR_ATTEMPTS:
                    await ws.send_json({"type": "pair_failed", "reason": "too_many_attempts"})
                    await ws.close()
                    break

                identifier = data.get("identifier", "")
                pc_pubkey = data.get("pc_pubkey", "")
                entry = pending_phones.pop(identifier, None)

                if not entry or time.monotonic() > entry["expires_at"]:
                    pc_attempts[ws] = fails + 1
                    await ws.send_json({"type": "pair_failed", "reason": "code_invalid"})
                    continue

                phone_ws = entry["ws"]
                if phone_ws.closed:
                    pc_attempts[ws] = fails + 1
                    await ws.send_json({"type": "pair_failed", "reason": "phone_gone"})
                    continue

                # Success — create bidirectional session
                sessions[ws] = phone_ws
                sessions[phone_ws] = ws
                pc_attempts[ws] = 0
                await ws.send_json({"type": "paired", "phone_pubkey": entry["pubkey"]})
                await phone_ws.send_json({"type": "paired", "pc_pubkey": pc_pubkey})

            # ── Relay encrypted payload to partner ────────────────────────
            elif kind == "data":
                partner = sessions.get(ws)
                if partner and not partner.closed:
                    await partner.send_json({
                        "type": "data",
                        "payload": data.get("payload", ""),
                    })

    finally:
        active_pcs.discard(ws)
        pc_attempts.pop(ws, None)
        partner = sessions.pop(ws, None)
        if partner:
            sessions.pop(partner, None)
            if not partner.closed:
                try:
                    await partner.send_json({"type": "session_ended"})
                except Exception:
                    pass
        # Remove stale pending-phone entries for this ws
        stale = [k for k, v in list(pending_phones.items()) if v["ws"] is ws]
        for k in stale:
            pending_phones.pop(k, None)

    return ws


# ---------------------------------------------------------------------------
# Background task: expire stale pending-phone entries
# ---------------------------------------------------------------------------

async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL)
        now = time.monotonic()
        expired = [k for k, v in list(pending_phones.items()) if now > v["expires_at"]]
        for k in expired:
            entry = pending_phones.pop(k, None)
            if entry and not entry["ws"].closed:
                try:
                    await entry["ws"].send_json({"type": "pair_expired"})
                except Exception:
                    pass


async def _on_startup(app: web.Application) -> None:
    asyncio.create_task(_cleanup_loop())


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/has_pc", has_pc_handler)
    app.router.add_get("/ws", ws_handler)
    app.on_startup.append(_on_startup)
    return app


# ---------------------------------------------------------------------------
# Phone browser UI (served at GET /)
# ---------------------------------------------------------------------------

_PHONE_HTML = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<meta name="theme-color" content="#1a1a1a">
<title>Dictate</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; touch-action: manipulation; }
html { -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }
html, body { width: 100%; overflow: hidden; background: #1a1a1a; color: #eee; font-family: sans-serif; }
body { display: flex; flex-direction: column; }

.view { display: none; flex-direction: column; align-items: center; justify-content: center;
        flex: 1; gap: 18px; padding: 24px; width: 100%; }
.view.on { display: flex; }

#main-view { align-items: stretch; justify-content: flex-start; padding: 0; gap: 0; }

.spinner { width: 52px; height: 52px; border: 5px solid #333; border-top-color: #eee;
           border-radius: 50%; animation: spin 0.9s linear infinite; flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg); } }

.sub  { color: #aaa; font-size: 0.9rem; text-align: center; }
.code { font-size: 3rem; letter-spacing: .3em; font-weight: bold; font-family: monospace; }
.err  { color: #e57373; text-align: center; }

.btn-row { display: flex; gap: 6px; padding: 8px; flex-shrink: 0; }
.btn { flex: 1; padding: 16px 0; font-size: 1rem; border: none; border-radius: 8px;
       cursor: pointer; font-weight: bold; }
.btn-send  { background: #2e7d32; color: #fff; }
.btn-send:active  { background: #1b5e20; }
.btn-clear { background: #444; color: #ccc; }
.btn-enter { background: #1565c0; color: #fff; }
.btn-reload { background: #555; color: #fff; }

textarea { flex: 1; min-height: 0; width: 100%; background: #1a1a1a; color: #eee;
           border: none; outline: none; padding: 8px; font-size: 0.9rem; resize: none; display: block; }
textarea:read-only { opacity: 0.6; }

#reload-row { display: none; }
</style>
</head>
<body>

<!-- Loading: no PC connected yet -->
<div id="loading-view" class="view on">
  <div class="spinner"></div>
  <p class="sub">Waiting for PC to connect&hellip;</p>
</div>

<!-- Pairing: show code, wait for PC to enter it -->
<div id="pair-view" class="view">
  <p class="sub">Enter this code in the PC app:</p>
  <div id="pair-code" class="code">&mdash;</div>
  <p class="sub" id="pair-hint">Waiting for confirmation&hellip;</p>
</div>

<!-- Active dictation session -->
<div id="main-view" class="view">
  <div class="btn-row" id="btn-row">
    <button class="btn btn-send"  onclick="sendText()">Send</button>
    <button class="btn btn-clear" onclick="clearText()">Clear</button>
    <button class="btn btn-enter" onclick="pressEnter()">Enter</button>
  </div>
  <div class="btn-row" id="reload-row">
    <button class="btn btn-reload" onclick="location.reload()">Connection lost &mdash; Reload</button>
  </div>
  <textarea id="text" placeholder="Use your phone&#x2019;s dictate function to enter text&hellip;"></textarea>
</div>

<!-- Session ended -->
<div id="ended-view" class="view">
  <p class="err">Session ended</p>
  <textarea id="saved-text" readonly style="width:100%;flex:1;min-height:0;"></textarea>
</div>

<script>
// ── Constants ────────────────────────────────────────────────────────────
const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ23456789'; // no 0 1 (equated to O I on PC side)
const SESSION_INFO = new TextEncoder().encode('dictate_session_v1');
const CODE_LEN = 6;

// ── State ────────────────────────────────────────────────────────────────
let ws = null;
let sessionKey = null;

// ── View helper ──────────────────────────────────────────────────────────
function show(id) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('on'));
  document.getElementById(id).classList.add('on');
}

// ── Viewport fit (keyboard-aware on iOS) ─────────────────────────────────
function fitViewport() {
  const h = window.visualViewport ? window.visualViewport.height : window.innerHeight;
  document.body.style.height = h + 'px';
}
fitViewport();
if (window.visualViewport) {
  window.visualViewport.addEventListener('resize', fitViewport);
  window.visualViewport.addEventListener('scroll', fitViewport);
}

// ── Crypto helpers ───────────────────────────────────────────────────────
function toB64(ab) {
  return btoa(String.fromCharCode(...new Uint8Array(ab)));
}
function fromB64(s) {
  return Uint8Array.from(atob(s), c => c.charCodeAt(0));
}

function genCode() {
  const b = new Uint8Array(CODE_LEN);
  crypto.getRandomValues(b);
  return Array.from(b).map(x => ALPHABET[x % ALPHABET.length]).join('');
}

async function deriveIdentifier(code) {
  const raw = new TextEncoder().encode('dictate_pairing_v1:' + code);
  const hash = await crypto.subtle.digest('SHA-256', raw);
  return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2,'0')).join('');
}

async function deriveSessionKey(myPrivKey, peerPubB64, code) {
  const peerPub = await crypto.subtle.importKey(
    'raw', fromB64(peerPubB64), {name: 'ECDH', namedCurve: 'P-256'}, false, []
  );
  const sharedBits = await crypto.subtle.deriveBits(
    {name: 'ECDH', public: peerPub}, myPrivKey, 256
  );
  const baseKey = await crypto.subtle.importKey('raw', sharedBits, 'HKDF', false, ['deriveKey']);
  return crypto.subtle.deriveKey(
    {name: 'HKDF', hash: 'SHA-256', salt: new TextEncoder().encode(code), info: SESSION_INFO},
    baseKey, {name: 'AES-GCM', length: 256}, false, ['encrypt', 'decrypt']
  );
}

async function encryptMsg(key, obj) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt(
    {name: 'AES-GCM', iv}, key, new TextEncoder().encode(JSON.stringify(obj))
  );
  const out = new Uint8Array(12 + ct.byteLength);
  out.set(iv);
  out.set(new Uint8Array(ct), 12);
  return toB64(out.buffer);
}

// ── Main flow ────────────────────────────────────────────────────────────
async function checkForPC() {
  try {
    const {available} = await (await fetch('/has_pc')).json();
    if (available) { await startPairing(); return; }
  } catch(_) {}
  setTimeout(checkForPC, 2000);
}

async function startPairing() {
  const code = genCode();
  document.getElementById('pair-code').textContent = code;
  document.getElementById('pair-hint').textContent = 'Waiting for confirmation…';
  show('pair-view');

  const kp = await crypto.subtle.generateKey(
    {name: 'ECDH', namedCurve: 'P-256'}, true, ['deriveBits']
  );
  const pubRaw = await crypto.subtle.exportKey('raw', kp.publicKey);
  const identifier = await deriveIdentifier(code);

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(proto + '//' + location.host + '/ws');

  ws.onopen = () => ws.send(JSON.stringify({
    type: 'phone_pair',
    identifier,
    phone_pubkey: toB64(pubRaw),
  }));

  ws.onmessage = async (evt) => {
    const msg = JSON.parse(evt.data);
    if (msg.type === 'paired') {
      sessionKey = await deriveSessionKey(kp.privateKey, msg.pc_pubkey, code);
      show('main-view');
    } else if (msg.type === 'pair_failed' || msg.type === 'pair_expired') {
      ws.close();
      // Give browser a tick before reopening new WS
      setTimeout(startPairing, 300);
    } else if (msg.type === 'session_ended') {
      document.getElementById('saved-text').value =
        document.getElementById('text')?.value || '';
      show('ended-view');
    }
  };

  ws.onclose = () => {
    const inMain  = document.getElementById('main-view').classList.contains('on');
    const inEnded = document.getElementById('ended-view').classList.contains('on');
    if (inMain)  { showOffline(); }
    else if (!inEnded) { setTimeout(checkForPC, 2000); }
  };
}

// ── Actions ──────────────────────────────────────────────────────────────
async function sendText() {
  const text = document.getElementById('text').value.trim();
  if (!text || !sessionKey || !ws || ws.readyState !== 1) return;
  ws.send(JSON.stringify({type: 'data', payload: await encryptMsg(sessionKey, {action:'send', text})}));
  document.getElementById('text').value = '';
}

function clearText() {
  if (confirm('Clear all text?')) document.getElementById('text').value = '';
}

async function pressEnter() {
  if (!sessionKey || !ws || ws.readyState !== 1) return;
  ws.send(JSON.stringify({type: 'data', payload: await encryptMsg(sessionKey, {action:'enter'})}));
}

function showOffline() {
  document.getElementById('btn-row').style.display = 'none';
  document.getElementById('reload-row').style.display = 'flex';
}

checkForPC();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dictate Gateway Server")
    parser.add_argument("--host", default="0.0.0.0", help="bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8766, help="port (default: 8766)")
    args = parser.parse_args()

    print(f"Dictate Gateway Server — listening on {args.host}:{args.port}")
    print("Put this behind a reverse proxy (nginx/Caddy) with TLS for production use.")
    web.run_app(make_app(), host=args.host, port=args.port, print=None)
