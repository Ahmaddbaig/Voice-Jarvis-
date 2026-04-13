"""Background-mode entry point for Jarvis (PROC-01).

Launched via: pythonw.exe src/jarvis.pyw
Or via the shell:startup shortcut created by install_autostart.ps1.

CRITICAL: The first executable lines redirect sys.stdout and sys.stderr
to a log file BEFORE any other import. Under pythonw.exe, stdout/stderr
are None -- any print(), logging call, or unhandled exception silently
vanishes. See cpython bugs #107792, #706263, #122633.
"""
import sys
import os
import faulthandler
from pathlib import Path

# --- CRASH PLUMBING (must be first, before ANY project import) ---
_log_dir = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "Jarvis" / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)
_log_file = open(_log_dir / "jarvis.log", "a", buffering=1, encoding="utf-8")
sys.stdout = _log_file
sys.stderr = _log_file

# faulthandler catches C-extension segfaults (ONNX, torch, pywin32) -- PROC-04
faulthandler.enable(file=_log_file)

# --- GLOBAL EXCEPTHOOK (still before project imports, after redirect) ---
import traceback


def _excepthook(exc_type, exc_value, exc_tb):
    """Global exception handler: log traceback + show Windows toast (PROC-04)."""
    traceback.print_exception(exc_type, exc_value, exc_tb, file=sys.stderr)
    sys.stderr.flush()
    try:
        from winotify import Notification

        log_dir_str = str(_log_dir)
        toast = Notification(
            app_id="Jarvis",
            title="Jarvis encountered an error",
            msg=f"See logs at {log_dir_str}",
        )
        toast.add_actions(label="Open Logs", launch=log_dir_str)
        toast.show()
    except Exception:
        pass  # toast is best-effort -- do not recurse


sys.excepthook = _excepthook

# --- NOW safe to import project modules ---
import threading
import time

import pystray
from PIL import Image, ImageDraw, ImageFont

from jarvis.core.config import load_config
from jarvis.core.preload import preload_all
from jarvis.assistant import JarvisAssistant


# ---------------------------------------------------------------------------
# Icon generation
# ---------------------------------------------------------------------------


def create_jarvis_icon(size: int = 64) -> Image.Image:
    """Generate a simple 'J' icon for the system tray (D-01)."""
    img = Image.new("RGBA", (size, size), (30, 30, 30, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", size=int(size * 0.7))
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "J", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - w) // 2
    y = (size - h) // 2 - bbox[1]
    draw.text((x, y), "J", fill=(255, 255, 255, 255), font=font)
    return img


# ---------------------------------------------------------------------------
# Main block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cfg = load_config()
    models, registry = preload_all(cfg)
    assistant = JarvisAssistant(cfg, preloaded=models)

    _listening = True

    def _toggle_listening(icon, item):
        """Toggle wake-word stream on/off (D-02)."""
        global _listening
        _listening = not _listening
        if _listening:
            assistant._wake_stream.start()
        else:
            assistant._wake_stream.stop()

    def _quit(icon, item):
        """Graceful shutdown: stop assistant then tray icon."""
        assistant.close()
        icon.stop()

    def _setup(icon):
        """Runs in a thread created by pystray. Starts voice loop + watchdog."""
        icon.visible = True
        assistant.start_voice_loop()
        # Watchdog loop (PROC-08) -- checks worker thread every ~5 seconds
        while icon.visible:
            time.sleep(5)
            if assistant._worker is not None and not assistant._worker.is_alive():
                print("[watchdog] Worker thread died, restarting...", flush=True)
                try:
                    assistant.start_voice_loop()
                except Exception as exc:
                    print(f"[watchdog] Restart failed: {exc}", flush=True)
            # Update tooltip with component health (D-03)
            icon.title = registry.health_summary()

    menu = pystray.Menu(
        pystray.MenuItem(
            "Listening",
            _toggle_listening,
            checked=lambda item: _listening,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", _quit),
    )

    icon = pystray.Icon(
        "Jarvis",
        icon=create_jarvis_icon(),
        title=registry.health_summary(),
        menu=menu,
    )
    print(f"Jarvis tray starting (provider={cfg.provider})", flush=True)
    icon.run(setup=_setup)  # blocks main thread (PROC-01)
