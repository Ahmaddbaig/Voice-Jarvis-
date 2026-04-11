"""Phase 1 wake-event JSONL log writer."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


class WakeLog:
    def __init__(self, log_path: Path) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("jarvis.wake")
        self._logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(str(log_path), maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        if not any(isinstance(h, RotatingFileHandler) for h in self._logger.handlers):
            self._logger.addHandler(handler)
        self._logger.propagate = False

    def log_wake(self, decision: str, confidence: float, transcript: str = "") -> None:
        capped = " ".join((transcript or "").split()[:6])
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "decision": decision,
            "confidence": round(confidence, 4),
            "transcript": capped,
        }
        self._logger.info(json.dumps(row, ensure_ascii=False))
