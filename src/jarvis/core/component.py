"""Component protocol, registry, and concrete subsystem wrappers (PROC-05, PROC-06).

Defines a structural-typing contract for subsystem health monitoring and a
registry that aggregates health into a compact tooltip string. Five concrete
wrappers cover: wake-word engine, STT, brain, TTS, and camera.

Statuses:
  - "ok"       -- subsystem initialised and working
  - "degraded" -- primary threw but a fallback is active (set externally)
  - "failed"   -- even the fallback is down
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Component Protocol (D-08, PROC-06)
# ---------------------------------------------------------------------------


@runtime_checkable
class Component(Protocol):
    """Structural-typing contract for subsystem lifecycle monitoring."""

    @property
    def name(self) -> str: ...

    def try_init(self) -> bool:
        """Attempt initialisation. Return True on success, False on failure."""
        ...

    def check(self) -> str:
        """Return current status: 'ok', 'degraded', or 'failed'."""
        ...

    def status(self) -> str:
        """Human-readable status string, e.g. 'Wake: ok'."""
        ...

    def last_error(self) -> str | None:
        """Last error message, or None if healthy."""
        ...


# ---------------------------------------------------------------------------
# Component Registry (D-03, D-11)
# ---------------------------------------------------------------------------


class ComponentRegistry:
    """Holds all monitored components and provides aggregate health."""

    def __init__(self) -> None:
        self._components: list[Component] = []

    def register(self, comp: Component) -> None:
        """Add a component to the registry."""
        self._components.append(comp)

    def health_summary(self) -> str:
        """One-line tooltip: 'Wake: ok | STT: ok | Brain: ok | TTS: ok | Cam: ok'.

        Kept under 128 chars to respect the Win32 tooltip limit (Pitfall 7).
        """
        parts = [f"{c.name}: {c.check()}" for c in self._components]
        return " | ".join(parts)

    def run_startup_checks(self) -> None:
        """Call try_init on each component and print pass/fail."""
        for c in self._components:
            ok = c.try_init()
            tag = "pass" if ok else "FAIL"
            print(f"    {c.name}: {tag}", flush=True)
            if not ok and c.last_error():
                print(f"      error: {c.last_error()}", flush=True)

    def try_recover_all(self) -> None:
        """Auto-recovery (D-11): retry degraded/failed components."""
        for c in self._components:
            if c.check() in ("degraded", "failed"):
                c.try_init()

    def __iter__(self):
        return iter(self._components)

    def __len__(self) -> int:
        return len(self._components)


# ---------------------------------------------------------------------------
# Helper mixin-style base for concrete wrappers
# ---------------------------------------------------------------------------


class _ComponentBase:
    """Shared state and helpers for concrete component wrappers.

    NOT an ABC -- the Component Protocol uses structural typing. This is
    just DRY convenience for the five wrappers below.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._status: str = "ok"
        self._error: str | None = None

    @property
    def name(self) -> str:
        return self._name

    def check(self) -> str:
        return self._status

    def status(self) -> str:
        return f"{self._name}: {self._status}"

    def last_error(self) -> str | None:
        return self._error

    def set_status(self, status: str, error: str | None = None) -> None:
        """Allow external code (turn pipeline) to mark degraded/failed."""
        self._status = status
        self._error = error

    def _succeed(self) -> bool:
        self._status = "ok"
        self._error = None
        return True

    def _fail(self, exc: Exception) -> bool:
        self._status = "failed"
        self._error = str(exc)
        return False


# ---------------------------------------------------------------------------
# Concrete wrappers (D-09) -- 5 monitored subsystems
# ---------------------------------------------------------------------------


class WakeComponent(_ComponentBase):
    """Probes microphone access via sounddevice."""

    def __init__(self) -> None:
        super().__init__("Wake")

    def try_init(self) -> bool:
        try:
            import sounddevice as sd
            sd.query_devices(kind="input")
            return self._succeed()
        except Exception as exc:
            return self._fail(exc)


class STTComponent(_ComponentBase):
    """Verifies faster-whisper model object is available."""

    def __init__(self, whisper_model: object = None) -> None:
        super().__init__("STT")
        self._whisper = whisper_model

    def try_init(self) -> bool:
        try:
            if self._whisper is None:
                raise RuntimeError("whisper model not loaded")
            return self._succeed()
        except Exception as exc:
            return self._fail(exc)


class BrainComponent(_ComponentBase):
    """Checks brain provider connectivity (Ollama or OpenAI)."""

    def __init__(
        self,
        provider: str = "ollama",
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "gemma4:latest",
    ) -> None:
        super().__init__("Brain")
        self._provider = provider
        self._ollama_url = ollama_url
        self._ollama_model = ollama_model

    def try_init(self) -> bool:
        try:
            if self._provider == "ollama":
                import requests
                resp = requests.get(
                    f"{self._ollama_url}/api/tags",
                    timeout=5,
                )
                resp.raise_for_status()
            elif self._provider == "openai":
                key = os.environ.get("OPENAI_API_KEY")
                if not key:
                    raise RuntimeError("OPENAI_API_KEY not set")
            return self._succeed()
        except Exception as exc:
            return self._fail(exc)


class TTSComponent(_ComponentBase):
    """Checks that at least one TTS engine (Kokoro or Piper) is available."""

    def __init__(
        self,
        kokoro: object = None,
        piper_voice: object = None,
    ) -> None:
        super().__init__("TTS")
        self._kokoro = kokoro
        self._piper_voice = piper_voice

    def try_init(self) -> bool:
        try:
            if self._kokoro is None and self._piper_voice is None:
                raise RuntimeError("no TTS engine available (kokoro and piper both None)")
            return self._succeed()
        except Exception as exc:
            return self._fail(exc)


class CameraComponent(_ComponentBase):
    """Probes camera access via OpenCV VideoCapture."""

    def __init__(self, camera_index: int = 0) -> None:
        super().__init__("Cam")
        self._camera_index = camera_index

    def try_init(self) -> bool:
        try:
            import cv2
            cap = cv2.VideoCapture(self._camera_index)
            opened = cap.isOpened()
            cap.release()
            if not opened:
                raise RuntimeError(f"camera {self._camera_index} not available")
            return self._succeed()
        except Exception as exc:
            return self._fail(exc)


class SearXNGComponent(_ComponentBase):
    """Pings SearXNG at startup. Yellow if unreachable, green if reachable."""

    def __init__(self, url: str = "http://localhost:8888") -> None:
        super().__init__("Web")
        self._url = url

    def try_init(self) -> bool:
        try:
            import requests as http_requests
            resp = http_requests.get(
                f"{self._url}/search",
                params={"q": "test", "format": "json"},
                timeout=3,
            )
            resp.raise_for_status()
            return self._succeed()
        except Exception as exc:
            # Degraded, not failed -- SearXNG is optional (D-13)
            self._status = "degraded"
            self._error = str(exc)
            return False


class OutlookComponent(_ComponentBase):
    """Probes Outlook COM availability at startup. Degraded if absent (D-13)."""

    def __init__(self) -> None:
        super().__init__("Mail")

    def try_init(self) -> bool:
        try:
            import pythoncom
            pythoncom.CoInitialize()
            import win32com.client
            app = win32com.client.Dispatch("Outlook.Application")
            _ = app.GetNamespace("MAPI")
            return self._succeed()
        except Exception as exc:
            self._status = "degraded"
            self._error = str(exc)
            return False
