"""window -- Tier 1 reversible tool. Focus, minimize, or close windows by title."""
import ctypes
import logging
from typing import Literal

import win32con
import win32gui
import win32process

from jarvis.tools._registry import tool

_logger = logging.getLogger(__name__)


def _find_window(title: str) -> tuple[int, str] | None:
    """Find the first visible window whose title contains the search string (case-insensitive).

    Returns (hwnd, full_title) or None.
    """
    title_lower = title.lower()
    result = None

    def _callback(hwnd, _extra):
        nonlocal result
        if result is not None:
            return True
        if win32gui.IsWindowVisible(hwnd):
            window_title = win32gui.GetWindowText(hwnd)
            if window_title and title_lower in window_title.lower():
                result = (hwnd, window_title)
        return True

    try:
        win32gui.EnumWindows(_callback, None)
    except Exception:
        pass
    return result


def _focus_window(hwnd: int) -> None:
    """Bring a window to the foreground using the AttachThreadInput dance."""
    current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
    target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
    attached = False

    if current_thread != target_thread:
        ctypes.windll.user32.AttachThreadInput(current_thread, target_thread, True)
        attached = True
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    finally:
        if attached:
            ctypes.windll.user32.AttachThreadInput(current_thread, target_thread, False)


@tool(tier=1, description="Manage a window by title: focus, minimize, or close it.")
def manage_window(title: str, action: Literal["focus", "minimize", "close"]) -> str:
    """Manage a window by title: focus, minimize, or close it.

    Args:
        title: Substring to match against window titles (case-insensitive).
        action: The action to perform: 'focus', 'minimize', or 'close'.
    """
    match = _find_window(title)
    if match is None:
        return f"No window found matching '{title}'"

    hwnd, full_title = match

    try:
        if action == "focus":
            _focus_window(hwnd)
            return f"Focused window: {full_title}"
        elif action == "minimize":
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
            return f"Minimized window: {full_title}"
        elif action == "close":
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            return f"Closed window: {full_title}"
        else:
            return f"Unknown action: {action}. Use 'focus', 'minimize', or 'close'."
    except Exception as exc:
        return f"Failed to {action} window '{full_title}': {exc}"
