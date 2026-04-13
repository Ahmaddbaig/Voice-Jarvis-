"""clipboard -- Tier 0 read + Tier 1 write tools for system clipboard."""
from jarvis.tools._registry import tool


@tool(tier=0)
def get_clipboard() -> str:
    """Return the current text contents of the system clipboard."""
    import win32clipboard
    import win32con

    try:
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                return str(data)[:4000]
            return "(clipboard is empty or contains non-text data)"
        finally:
            win32clipboard.CloseClipboard()
    except Exception as exc:
        return f"(clipboard unavailable: {exc})"


@tool(tier=1, description="Set the system clipboard to the given text.")
def set_clipboard(text: str) -> str:
    """Set the system clipboard to the given text.

    Args:
        text: The text to place on the clipboard.
    """
    import time
    import win32clipboard
    import win32con

    for attempt in range(2):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
                return f"Clipboard set ({len(text)} chars)."
            finally:
                win32clipboard.CloseClipboard()
        except Exception as exc:
            if attempt == 0:
                time.sleep(0.1)  # Retry once after 100ms per D-11
                continue
            return f"(clipboard unavailable: {exc})"
    return "(clipboard unavailable: unknown error)"
