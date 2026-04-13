"""volume -- Tier 0/1 tools for system volume control and media key simulation."""
import ctypes
import logging
from ctypes import POINTER, cast, wintypes
from typing import Literal

from jarvis.tools._registry import tool

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Media key constants and SendInput structs
# ---------------------------------------------------------------------------

VK_MEDIA_PLAY_PAUSE = 0xB3
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_VOLUME_MUTE = 0xAD

KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    _fields_ = [("type", wintypes.DWORD), ("_input", _INPUT)]


def _press_key(vk_code: int) -> None:
    """Send a virtual key press (down + up) via SendInput."""
    inputs = (INPUT * 2)()
    # Key down
    inputs[0].type = INPUT_KEYBOARD
    inputs[0]._input.ki.wVk = vk_code
    # Key up
    inputs[1].type = INPUT_KEYBOARD
    inputs[1]._input.ki.wVk = vk_code
    inputs[1]._input.ki.dwFlags = KEYEVENTF_KEYUP
    ctypes.windll.user32.SendInput(2, inputs, ctypes.sizeof(INPUT))


# ---------------------------------------------------------------------------
# Volume control via pycaw (COM-based, needs CoInitialize per call)
# ---------------------------------------------------------------------------


def _get_volume_interface():
    """Activate and return the IAudioEndpointVolume COM interface."""
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


@tool(tier=1, description="Set system master volume to an absolute level (0-100).")
def set_volume(level: int) -> str:
    """Set system master volume to an absolute level (0-100).

    Args:
        level: Volume percentage, 0 (muted) to 100 (max).
    """
    import pythoncom

    level = max(0, min(100, level))

    pythoncom.CoInitialize()
    try:
        volume = _get_volume_interface()
        volume.SetMasterVolumeLevelScalar(level / 100.0, None)
        if level == 0:
            volume.SetMute(1, None)
        else:
            volume.SetMute(0, None)
        return f"Volume set to {level}%"
    except Exception as exc:
        _logger.warning("set_volume failed: %s", exc)
        return f"Failed to set volume: {exc}"
    finally:
        pythoncom.CoUninitialize()


# ---------------------------------------------------------------------------
# Media key control via ctypes SendInput (no COM needed)
# ---------------------------------------------------------------------------

_MEDIA_KEYS = {
    "play_pause": VK_MEDIA_PLAY_PAUSE,
    "next": VK_MEDIA_NEXT_TRACK,
    "prev": VK_MEDIA_PREV_TRACK,
    "mute": VK_VOLUME_MUTE,
}


@tool(tier=0, description="Send a media control key (play/pause, next track, previous track, mute toggle).")
def media_control(action: Literal["play_pause", "next", "prev", "mute"]) -> str:
    """Send a media control key (play/pause, next track, previous track, mute toggle).

    Args:
        action: The media action: 'play_pause', 'next', 'prev', or 'mute'.
    """
    vk_code = _MEDIA_KEYS.get(action)
    if vk_code is None:
        return f"Unknown media action: {action}. Use 'play_pause', 'next', 'prev', or 'mute'."

    try:
        _press_key(vk_code)
        return f"Media: {action}"
    except Exception as exc:
        _logger.warning("media_control failed: %s", exc)
        return f"Failed to send media key: {exc}"
