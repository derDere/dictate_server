"""Pure helper functions — no side effects, no shared state."""
import random
import socket


def get_lan_ip() -> str:
    """Detect the real LAN IP via UDP socket trick (never returns 127.0.0.1)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def make_pin() -> str:
    return f"{random.randint(0, 999999):06d}"


def is_lan_client(client_ip: str, server_ip: str) -> bool:
    """Allow only clients on the same /24 subnet as the server."""
    return client_ip.rsplit(".", 1)[0] == server_ip.rsplit(".", 1)[0]
