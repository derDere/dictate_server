"""Text injection into the active Windows application via clipboard + Ctrl+V."""
import time

import pyautogui
import win32clipboard

from state import _log


def inject_text(text: str) -> None:
    try:
        _log("INJECT saving clipboard")
        win32clipboard.OpenClipboard()
        try:
            old = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        except Exception:
            old = None
        win32clipboard.CloseClipboard()

        _log(f"INJECT writing {len(text)} chars to clipboard")
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
        win32clipboard.CloseClipboard()

        _log("INJECT Ctrl+V")
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.3)

        _log("INJECT restoring clipboard")
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        if old is not None:
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, old)
        win32clipboard.CloseClipboard()
        _log("INJECT done")
    except Exception as e:
        _log(f"INJECT ERROR: {e}")


def press_enter() -> None:
    try:
        _log("INJECT Enter")
        pyautogui.press("enter")
    except Exception as e:
        _log(f"INJECT enter ERROR: {e}")
