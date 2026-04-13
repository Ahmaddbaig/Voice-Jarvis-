"""app_launch -- Tier 1 reversible tool. Launch applications by name with 3-tier fallback."""
import glob
import json
import logging
import os
import subprocess
import time

from jarvis.tools._registry import tool

_logger = logging.getLogger(__name__)


def _find_window_by_name(name: str) -> bool:
    """Check if a visible window with title matching name exists."""
    import win32gui

    name_lower = name.lower()
    found = False

    def _callback(hwnd, _extra):
        nonlocal found
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title and name_lower in title.lower():
                found = True
        return True

    try:
        win32gui.EnumWindows(_callback, None)
    except Exception:
        pass
    return found


def _try_start_command(name: str) -> bool:
    """Tier 1: Launch via Windows 'start' command."""
    try:
        subprocess.Popen(
            f'start "" "{name}"',
            shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        time.sleep(1.5)
        return _find_window_by_name(name)
    except Exception as exc:
        _logger.debug("start command failed for %r: %s", name, exc)
        return False


def _try_start_menu_search(name: str) -> str | None:
    """Tier 2: Search Start Menu .lnk files for a matching shortcut."""
    import pythoncom
    import win32com.client

    search_dirs = [
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
    ]

    pythoncom.CoInitialize()
    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        name_lower = name.lower()

        for search_dir in search_dirs:
            if not os.path.isdir(search_dir):
                continue
            for lnk_path in glob.glob(
                os.path.join(search_dir, "**", "*.lnk"), recursive=True
            ):
                filename = os.path.splitext(os.path.basename(lnk_path))[0].lower()
                if name_lower in filename:
                    try:
                        shortcut = shell.CreateShortcut(lnk_path)
                        target = shortcut.TargetPath
                        if target and os.path.isfile(target):
                            return target
                    except Exception as exc:
                        _logger.debug("Failed to resolve %s: %s", lnk_path, exc)
                        continue
        return None
    finally:
        pythoncom.CoUninitialize()


def _try_app_map(name: str) -> str | None:
    """Tier 3: Look up in user's app_map.json."""
    app_map_path = os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Jarvis", "app_map.json"
    )
    if not os.path.isfile(app_map_path):
        return None

    try:
        with open(app_map_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Case-insensitive lookup
        name_lower = name.lower()
        for key, value in data.items():
            if key.lower() == name_lower:
                if os.path.isfile(value):
                    return value
    except Exception as exc:
        _logger.debug("app_map.json error: %s", exc)
    return None


@tool(tier=1, description="Launch an application by name (3-tier fallback: start cmd, Start Menu search, app map).")
def launch_app(name: str) -> str:
    """Launch an application by name (3-tier fallback: start cmd, Start Menu search, app map).

    Args:
        name: The application name to launch (e.g. 'Spotify', 'Chrome', 'Notepad').
    """
    # Tier 1: Windows start command
    if _try_start_command(name):
        return f"Launched {name} via start command."

    # Tier 2: Start Menu shortcut search
    target = _try_start_menu_search(name)
    if target:
        try:
            subprocess.Popen(
                [target],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return f"Launched {name} from Start Menu shortcut ({os.path.basename(target)})."
        except Exception as exc:
            _logger.debug("Failed to launch shortcut target %s: %s", target, exc)

    # Tier 3: App map JSON
    target = _try_app_map(name)
    if target:
        try:
            subprocess.Popen(
                [target],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return f"Launched {name} from app map ({os.path.basename(target)})."
        except Exception as exc:
            _logger.debug("Failed to launch app map target %s: %s", target, exc)

    return f"Could not find application: {name}"
