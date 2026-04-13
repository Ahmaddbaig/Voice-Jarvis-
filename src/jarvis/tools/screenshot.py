"""screenshot -- Tier 0 screen capture for vision-as-tool."""
import base64
import io

from jarvis.tools._registry import tool


@tool(tier=0, description="Capture the current screen (or a specific window) as an image for visual analysis.")
def take_screenshot(window_title: str | None = None) -> str:
    """Capture the current screen as an image for visual analysis.

    Args:
        window_title: If provided, capture only the window matching this title. Otherwise captures the full screen.
    """
    import mss
    from PIL import Image

    with mss.mss() as sct:
        if window_title:
            # Find window by title and capture its bounds
            hwnd = _find_window(window_title)
            if not hwnd:
                return f"No window found matching '{window_title}'"
            import win32gui
            rect = win32gui.GetWindowRect(hwnd)
            monitor = {
                "left": rect[0], "top": rect[1],
                "width": rect[2] - rect[0], "height": rect[3] - rect[1],
            }
        else:
            monitor = sct.monitors[0]  # Full virtual screen (all monitors combined)

        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

    # Resize if wider than 1920px to keep base64 payload manageable
    if img.width > 1920:
        ratio = 1920 / img.width
        img = img.resize((1920, int(img.height * ratio)), Image.LANCZOS)

    # Encode as JPEG quality 65 (good balance of size vs readability)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=65)
    b64 = base64.b64encode(buffer.getvalue()).decode("ascii")

    return f"data:image/jpeg;base64,{b64}"


def _find_window(title: str) -> int | None:
    """Find first visible window whose title contains the search string (case-insensitive)."""
    import win32gui

    result = []

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            wt = win32gui.GetWindowText(hwnd)
            if title.lower() in wt.lower():
                result.append(hwnd)
        return True  # Continue enumeration

    win32gui.EnumWindows(callback, None)
    return result[0] if result else None
