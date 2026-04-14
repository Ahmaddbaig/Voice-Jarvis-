"""Outlook email & calendar tools -- COM bridge via pywin32.

ACT-PERSONAL-01..07: Six tools for inbox, email, drafts, calendar.
All COM calls use _get_outlook() which handles CoInitialize (D-03),
auto-launch (D-02), and clean degradation (D-14).
"""
from __future__ import annotations

import logging
import threading
import time

import pywintypes

from jarvis.tools._registry import tool, mark_external_content

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Outlook COM folder constants
# ---------------------------------------------------------------------------
OL_FOLDER_INBOX = 6
OL_FOLDER_CALENDAR = 9
OL_FOLDER_DRAFTS = 16
OL_FOLDER_SENT = 5
OL_MAIL_ITEM = 0
OL_APPOINTMENT_ITEM = 1

# ---------------------------------------------------------------------------
# Module-level COM reference (lazy init, per D-03 threading model)
# ---------------------------------------------------------------------------
_outlook_lock = threading.Lock()
_outlook_available: bool | None = None  # None = not checked yet

_DEGRADED_MSG = (
    "Outlook is not available on this machine. "
    "Email and calendar tools require Microsoft Outlook."
)


def _get_outlook():
    """Get or create the Outlook COM application. Returns None if unavailable.

    Per D-03: calls pythoncom.CoInitialize() for the current thread.
    Per D-02: Dispatch auto-launches Outlook silently if not running.
    """
    global _outlook_available
    if _outlook_available is False:
        return None
    with _outlook_lock:
        try:
            import pythoncom
            pythoncom.CoInitialize()
            import win32com.client
            app = win32com.client.Dispatch("Outlook.Application")
            _outlook_available = True
            return app
        except Exception as exc:
            _logger.warning("Outlook COM unavailable: %s", exc)
            _outlook_available = False
            return None


def _com_retry(fn, max_retries=3):
    """Execute a COM call with retry on RPC_E_CALL_REJECTED (-2147418111).

    Outlook rejects COM calls when busy (dialogs, syncing). Retries with
    exponential backoff up to max_retries times.
    """
    for attempt in range(max_retries):
        try:
            return fn()
        except pywintypes.com_error as e:
            if e.hresult == -2147418111 and attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
