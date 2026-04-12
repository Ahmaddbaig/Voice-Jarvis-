"""Abort rail -- PopenRegistry + AbortController.

D-05: Context-dependent Ctrl+Alt+J (idle=start, busy=cancel).
D-06: Silent abort with log entry.
D-07: Popen registry as dict of {tool_call_id: Popen}.
SAFE-05: Hotkey cancels asyncio task + kills Popens + stops TTS.
"""
from __future__ import annotations

import asyncio
import subprocess
import threading
from typing import Callable


class PopenRegistry:
    """Thread-safe registry of active child processes."""

    def __init__(self):
        self._lock = threading.Lock()
        self._procs: dict[str, subprocess.Popen] = {}

    def register(self, call_id: str, proc: subprocess.Popen) -> None:
        with self._lock:
            self._procs[call_id] = proc

    def unregister(self, call_id: str) -> None:
        with self._lock:
            self._procs.pop(call_id, None)

    def terminate_all(self) -> None:
        """Kill all registered child processes. Called by abort handler."""
        with self._lock:
            for call_id, proc in list(self._procs.items()):
                try:
                    proc.terminate()
                except OSError:
                    pass
            self._procs.clear()


class AbortController:
    """Coordinates turn cancellation across asyncio task + Popens + TTS.

    The abort handler needs BOTH task.cancel() AND popen_registry.terminate_all()
    because task.cancel() does NOT kill threads in run_in_executor.
    """

    def __init__(self, popen_registry: PopenRegistry):
        self.popen_registry = popen_registry
        self._current_turn: asyncio.Task | None = None

    @property
    def is_busy(self) -> bool:
        return self._current_turn is not None and not self._current_turn.done()

    def set_current_turn(self, task: asyncio.Task) -> None:
        self._current_turn = task

    def clear_current_turn(self) -> None:
        self._current_turn = None

    def abort(self, tts_playing: asyncio.Event | None, sd_stop_fn: Callable) -> None:
        """Cancel everything. Called from hotkey via call_soon_threadsafe."""
        # 1. Cancel asyncio task
        if self._current_turn and not self._current_turn.done():
            self._current_turn.cancel()

        # 2. Kill child processes
        self.popen_registry.terminate_all()

        # 3. Stop audio playback
        sd_stop_fn()
        if tts_playing is not None:
            tts_playing.clear()
