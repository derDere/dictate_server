"""PC-side client for the online gateway server.

Runs a persistent WebSocket connection in a background thread.
Handles pairing (ECDH P-256) and decrypts incoming AES-256-GCM messages.
The gateway server never sees the pairing code or the plaintext.
"""
import asyncio
import base64
import hashlib
import json
import threading

import websockets
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDH,
    SECP256R1,
    EllipticCurvePublicNumbers,
    generate_private_key,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import injection
import state
from state import _log

# ---------------------------------------------------------------------------
# Crypto helpers
# ---------------------------------------------------------------------------

def _derive_identifier(code: str) -> str:
    """One-way hash of the pairing code — safe to send to the server."""
    return hashlib.sha256(f"dictate_pairing_v1:{code}".encode()).hexdigest()


def _make_keypair() -> tuple:
    """Generate ephemeral ECDH P-256 keypair; return (private_key, pubkey_b64)."""
    priv = generate_private_key(SECP256R1(), default_backend())
    raw = priv.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return priv, base64.b64encode(raw).decode()


def _derive_session_key(priv_key, peer_b64: str, code: str) -> bytes:
    """ECDH exchange + HKDF to produce 256-bit AES-GCM key."""
    raw = base64.b64decode(peer_b64)
    if len(raw) != 65 or raw[0] != 0x04:
        raise ValueError("invalid P-256 uncompressed point")
    x = int.from_bytes(raw[1:33], "big")
    y = int.from_bytes(raw[33:65], "big")
    peer_pub = EllipticCurvePublicNumbers(x, y, SECP256R1()).public_key(default_backend())
    shared = priv_key.exchange(ECDH(), peer_pub)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=code.encode(),
        info=b"dictate_session_v1",
        backend=default_backend(),
    ).derive(shared)


def _decrypt(session_key: bytes, payload_b64: str) -> dict:
    data = base64.b64decode(payload_b64)
    plain = AESGCM(session_key).decrypt(data[:12], data[12:], None)
    return json.loads(plain)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class GatewayClient:
    """Thread-safe gateway WebSocket client.

    Call connect() / disconnect() from the GUI thread.
    Status is reported back via state.gui_queue as ("gw_status", <str>).
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False
        self._ws_url = ""
        self._pending_code: str | None = None
        self._code_event: asyncio.Event | None = None
        self._priv_key = None
        self._session_key: bytes | None = None

    # --- Public API (GUI / main thread) ------------------------------------

    def connect(self, url: str) -> None:
        if self._running:
            return
        self._ws_url = _normalise_url(url)
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def disconnect(self) -> None:
        self._running = False
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)

    def submit_code(self, code: str) -> None:
        """Called from GUI thread when the user enters the phone's pairing code."""
        self._pending_code = code.upper().strip()
        if self._loop and self._code_event and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._code_event.set)

    # --- Async loop (background thread) ------------------------------------

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._code_event = asyncio.Event()
        try:
            self._loop.run_until_complete(self._main())
        except Exception as e:
            _log(f"GATEWAY thread error: {e}")
        finally:
            self._running = False
            self._loop.close()
            state.gui_queue.put(("gw_status", "disconnected"))

    async def _main(self) -> None:
        while self._running:
            state.gui_queue.put(("gw_status", "connecting"))
            try:
                await self._connect_once()
            except Exception as e:
                _log(f"GATEWAY connect error: {e}")
            if not self._running:
                break
            state.gui_queue.put(("gw_status", "disconnected"))
            # Wait before reconnecting, but wake immediately if stopped
            try:
                await asyncio.wait_for(asyncio.sleep(5), timeout=5)
            except Exception:
                pass

    async def _connect_once(self) -> None:
        async with websockets.connect(self._ws_url, ping_interval=20) as ws:
            _log(f"GATEWAY connected {self._ws_url}")
            await ws.send(json.dumps({"type": "pc_register"}))
            state.gui_queue.put(("gw_status", "waiting"))
            self._session_key = None
            self._priv_key = None
            self._pending_code = None
            self._code_event.clear()

            recv_task = asyncio.create_task(self._recv_loop(ws))
            code_task = asyncio.create_task(self._code_loop(ws))
            done, pending = await asyncio.wait(
                [recv_task, code_task], return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    async def _code_loop(self, ws) -> None:
        """Wait for the user to enter a pairing code, then send it to the gateway."""
        while True:
            await self._code_event.wait()
            self._code_event.clear()
            code = self._pending_code
            if not code:
                continue
            self._priv_key, pub_b64 = _make_keypair()
            await ws.send(json.dumps({
                "type": "pc_pair",
                "identifier": _derive_identifier(code),
                "pc_pubkey": pub_b64,
            }))
            state.gui_queue.put(("gw_status", "pairing"))

    async def _recv_loop(self, ws) -> None:
        async for raw in ws:
            msg = json.loads(raw)
            await self._handle(msg)

    async def _handle(self, msg: dict) -> None:
        kind = msg.get("type")

        if kind == "paired":
            code = self._pending_code
            if not code or not self._priv_key:
                return
            try:
                self._session_key = _derive_session_key(
                    self._priv_key, msg["phone_pubkey"], code
                )
                _log("GATEWAY paired — E2E session active")
                state.gui_queue.put(("gw_status", "active"))
            except Exception as e:
                _log(f"GATEWAY key derivation error: {e}")

        elif kind == "data":
            if not self._session_key:
                return
            try:
                payload = _decrypt(self._session_key, msg["payload"])
                action = payload.get("action")
                if action == "send":
                    text = payload.get("text", "")
                    _log(f"GATEWAY inject {len(text)} chars")
                    injection.inject_text(text)
                    state.gui_queue.put(("last_text", text))
                elif action == "enter":
                    injection.press_enter()
            except Exception as e:
                _log(f"GATEWAY decrypt error: {e}")

        elif kind == "pair_failed":
            _log(f"GATEWAY pair failed: {msg.get('reason')}")
            state.gui_queue.put(("gw_status", "pair_failed"))
            self._priv_key = None
            self._pending_code = None

        elif kind == "session_ended":
            _log("GATEWAY session ended by peer")
            state.gui_queue.put(("gw_status", "waiting"))
            self._session_key = None
            self._priv_key = None
            self._pending_code = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_url(url: str) -> str:
    """Convert any URL form to a wss:// or ws:// WebSocket URL ending in /ws."""
    url = url.strip().rstrip("/")
    if url.startswith("https://"):
        url = "wss://" + url[8:]
    elif url.startswith("http://"):
        url = "ws://" + url[7:]
    elif not url.startswith(("ws://", "wss://")):
        url = "wss://" + url  # assume secure by default for public servers
    return url + "/ws"
