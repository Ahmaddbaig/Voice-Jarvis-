"""get_clipboard -- Tier 0 read-only tool."""
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
