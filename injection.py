"""Text injection into the active Windows application via clipboard + Ctrl+V."""
import time

import pyautogui
import win32clipboard


def inject_text(text: str) -> None:
    try:
        # Save current clipboard content
        win32clipboard.OpenClipboard()
        try:
            old = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        except Exception:
            old = None
        win32clipboard.CloseClipboard()

        # Place new text into clipboard
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
        win32clipboard.CloseClipboard()

        # Paste into the active application (works even if tkinter is minimised)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.3)

        # Restore original clipboard content
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        if old is not None:
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, old)
        win32clipboard.CloseClipboard()
    except Exception:
        pass
