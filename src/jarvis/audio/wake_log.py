"""Phase 1 wake-event JSONL log writer (VOICE-01 diagnostic spine).

Append-only JSONL log of every wake-word detection outcome, written via a
:class:`logging.handlers.RotatingFileHandler` so the file is bounded at
1 MB with 5 rotated backups (5 MB total ceiling). Used by the two-stage
gate in :mod:`audio_in` to record what happened on every wake event:
accepts, gate rejections, and TTS-suppressed fires alike.

The log path is ``cfg.wake_log_path`` (resolved by :mod:`config` to
``%LOCALAPPDATA%\\Jarvis\\logs\\wake.log`` — explicitly machine-local, NOT
under ``%USERPROFILE%``, to dodge OneDrive sync per PITFALLS.md §G5).

Decision values (informal enum — accepted strings for ``log_wake``):

  - ``"accept_gate"``        — wake fired, two-stage gate confirmed,
                                fresh Piper-acked recording follows.
  - ``"accept_gate_inline"`` — wake fired, gate confirmed, transcript
                                already contained the command (>=4 words
                                after the wake word). No second recording.
  - ``"accept_hotkey"``      — global hotkey pressed; no wake involved.
  - ``"reject_gate"``        — wake fired, gate transcript did not start
                                with "jarvis"; turn aborted silently.
  - ``"suppressed_tts"``     — wake fired but ``tts_playing`` was set, so
                                the wake was dropped (Plan 05 owns the
                                check; this writer just records it).

PII handling (PITFALLS.md §C1, §Pitfall 6): the ``transcript`` field is
capped to the first **6 words** of whatever was passed in. Six words is
enough to disambiguate "marvel podcast episode 12" from "jarvis set a
timer" but too short to leak structured PII (passwords, card numbers).
There is intentionally no read API — the future calibration CLI will
stream-parse the JSONL directly.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


class WakeLog:
    """Rotating-file JSONL writer for wake-word events."""

    def __init__(self, log_path: Path) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("jarvis.wake")
        self._logger.setLevel(logging.INFO)
        # Rotate at 1 MB, keep 5 backups (5 MB ceiling).
        handler = RotatingFileHandler(
            str(log_path),
            maxBytes=1_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        # Avoid duplicate handlers if WakeLog is constructed twice in one process
        # (e.g. tests, or a hot-reload during development).
        if not any(
            isinstance(h, RotatingFileHandler) for h in self._logger.handlers
        ):
            self._logger.addHandler(handler)
        self._logger.propagate = False

    def log_wake(
        self,
        decision: str,
        confidence: float,
        transcript: str = "",
    ) -> None:
        """Append one JSONL row for a wake event.

        :param decision: One of the informal enum values documented at the
            top of this module (``accept_gate``, ``accept_gate_inline``,
            ``accept_hotkey``, ``reject_gate``, ``suppressed_tts``).
        :param confidence: openWakeWord score that triggered the event,
            0.0..1.0. Rounded to 4 decimal places in the log.
        :param transcript: Whisper transcript from the gate capture (or
            empty string for ``suppressed_tts`` / ``accept_hotkey``).
            **Capped to the first 6 words** for PII safety.
        """
        # PII cap: keep at most the first 6 words to limit overheard speech leakage.
        capped = " ".join((transcript or "").split()[:6])
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "decision": decision,
            "confidence": round(confidence, 4),
            "transcript": capped,
        }
        self._logger.info(json.dumps(row, ensure_ascii=False))
