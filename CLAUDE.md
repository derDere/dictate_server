# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`dictate_server` is a Windows-only desktop application that runs a local LAN web server, receives text from any device (e.g. iPhone via browser), and injects that text into the currently active Windows application via clipboard simulation.

## Tech Stack

- **Python 3.13**, Windows only
- **GUI**: `tkinter` (built-in)
- **Web server**: `http.server` from stdlib (intentionally lightweight, no Flask)
- **Text injection**: `pyautogui` (Ctrl+V simulation) + `pywin32` (`win32clipboard`)
- **QR code**: `qrcode[pil]` rendered into the tkinter window via `pillow`

## Setup & Run

```
pip install -r requirements.txt
pythonw main.py
```

(`pythonw` = no console window; `python main.py` also works for development)

## File Structure

```
main.py         Entry point — creates tkinter root, starts App
gui.py          App class — tkinter window, QR code, PIN entry, Start/Stop
server.py       _Handler (BaseHTTPRequestHandler), HTML template, start()/stop()
injection.py    inject_text() — clipboard save/restore + Ctrl+V via pyautogui
state.py        Shared mutable state + Lock: authorize(), check_pin(), clear_auth(), gui_queue
utils.py        Pure helpers: get_lan_ip(), make_pin(), is_lan_client()
requirements.txt
```

## Architecture

### 1. Tkinter GUI (main thread) — `gui.py`

Small, compact window meant to sit unobtrusively in a corner:
- QR code of the server URL
- URL label (`http://192.168.x.x:8765`)
- PIN entry field + "Connect" button (always visible; user sees PIN on phone, types it in)
- Last injected text label
- Start/Stop button

LAN IP detected via UDP socket trick in `utils.get_lan_ip()`: connect to `8.8.8.8:80`, read `getsockname()[0]`.

### 2. HTTP Server (background thread) — `server.py`

Listens on `0.0.0.0:8765`. Every request first checks that the client IP is on the same `/24` subnet as the server.

| Endpoint | Description |
|----------|-------------|
| `GET /` | Generates a fresh 6-digit PIN, returns the full HTML page with PIN embedded |
| `GET /status?pin=<pin>` | Returns `{"status": "authorized"\|"pending"\|"ended"}` |
| `POST /send` | Body: `{"pin": "...", "text": "..."}` — injects text if PIN is authorized |

### 3. Auth State — `state.py`

Two variables protected by a `threading.Lock`:
- `authorized_pin` — the currently approved PIN (may send text)
- `previous_pin` — the PIN that was authorized just before the current one

`check_pin()` logic: `authorized` → `pending` → `ended` (previous).
When the user clicks Connect in tkinter: `previous = authorized`, `authorized = entered_pin`.
The old client's next poll returns `"ended"` → browser shows "Sitzung beendet", textarea becomes readonly (text preserved).

Browser polls `/status` every 1 s while pending, every 5 s while authorized.

### 4. Text Injection — `injection.py`

1. Save clipboard via `win32clipboard`
2. Write received text to clipboard
3. `pyautogui.hotkey("ctrl", "v")` — works even when tkinter window is minimized
4. `time.sleep(0.3)`
5. Restore original clipboard
6. Put `("last_text", text)` on `state.gui_queue`; GUI picks it up via `root.after` polling

### 5. Thread Safety

- All auth state mutations go through `state.py` functions (Lock-protected).
- GUI updates from the server thread are dispatched via `gui_queue` + `root.after(200, poll)` — tkinter is never called directly from a background thread.
- Server thread is a daemon thread; `server.shutdown()` is called in its own thread to avoid blocking the GUI.
