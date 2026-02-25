"""Shared mutable state between the GUI thread and the HTTP server thread."""
import queue
import threading

PORT = 8765

_lock = threading.Lock()
_authorized_pin: str | None = None
_previous_pin: str | None = None

# Server thread puts ("last_text", str) messages here; GUI polls it.
gui_queue: queue.Queue = queue.Queue()


def authorize(pin: str) -> None:
    global _authorized_pin, _previous_pin
    with _lock:
        _previous_pin = _authorized_pin
        _authorized_pin = pin


def clear_auth() -> None:
    global _authorized_pin, _previous_pin
    with _lock:
        _authorized_pin = None
        _previous_pin = None


def check_pin(pin: str) -> str:
    """Returns 'authorized', 'ended', or 'pending'."""
    with _lock:
        if pin == _authorized_pin:
            return "authorized"
        if pin == _previous_pin:
            return "ended"
        return "pending"
