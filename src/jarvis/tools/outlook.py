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


# ---------------------------------------------------------------------------
# Email read tools (Tier 0)
# ---------------------------------------------------------------------------


@tool(tier=0)
def list_inbox(count: int = 10) -> str:
    """List recent inbox emails with subject, sender, date, and read status.

    Args:
        count: Number of recent emails to list (default 10, max 25).
    """
    app = _get_outlook()
    if app is None:
        return _DEGRADED_MSG
    count = min(count, 25)

    def _fetch():
        ns = app.GetNamespace("MAPI")
        inbox = ns.GetDefaultFolder(OL_FOLDER_INBOX)
        items = inbox.Items
        items.Sort("[ReceivedTime]", True)  # descending
        lines = []
        for i, item in enumerate(items):
            if i >= count:
                break
            try:
                status = "unread" if item.UnRead else "read"
                lines.append(
                    f"{i+1}. [{status}] {item.Subject}\n"
                    f"   From: {item.SenderName}\n"
                    f"   Date: {item.ReceivedTime.strftime('%Y-%m-%d %H:%M')}\n"
                    f"   ID: {item.EntryID}"
                )
            except Exception:
                continue
        return "\n".join(lines) if lines else "Inbox is empty."

    return _com_retry(_fetch)


@tool(tier=0)
def read_email(entry_id: str) -> str:
    """Read the full content of an email by its ID.

    Args:
        entry_id: The EntryID of the email to read (from list_inbox results).
    """
    app = _get_outlook()
    if app is None:
        return _DEGRADED_MSG

    def _fetch():
        ns = app.GetNamespace("MAPI")
        try:
            item = ns.GetItemFromID(entry_id)
        except Exception:
            return "[error] Email not found. It may have been moved or deleted."
        body = item.Body or ""
        total_len = len(body)
        if total_len > 4096:
            body = body[:4096] + f"\n[...truncated at 4KB -- {total_len // 1024}KB total]"
        mark_external_content()  # D-11: SAFE-04 quarantine
        return (
            f"Subject: {item.Subject}\n"
            f"From: {item.SenderName}\n"
            f"Date: {item.ReceivedTime.strftime('%Y-%m-%d %H:%M')}\n"
            f"To: {item.To}\n\n"
            f"{body}"
        )

    return _com_retry(_fetch)


# ---------------------------------------------------------------------------
# Email write tools (Tier 1 draft, Tier 2 send)
# ---------------------------------------------------------------------------


@tool(tier=1)
def draft_email(to: str, subject: str, body: str) -> str:
    """Draft an email and save it to the Drafts folder. Does NOT send.

    Args:
        to: Recipient email address(es), comma-separated for multiple.
        subject: Email subject line.
        body: Email body text.
    """
    app = _get_outlook()
    if app is None:
        return _DEGRADED_MSG

    def _create():
        mail = app.CreateItem(OL_MAIL_ITEM)
        mail.To = to
        mail.Subject = subject
        mail.Body = body
        mail.Save()  # Saves to Drafts -- does NOT send (D-05)
        return f"Draft saved. draft_id: {mail.EntryID}  Subject: '{subject}'  To: {to}"

    return _com_retry(_create)


@tool(tier=2)
def send_draft(draft_id: str) -> str:
    """Send a previously drafted email. Requires draft_id from draft_email.

    Args:
        draft_id: The EntryID of the draft to send (from draft_email result).
    """
    app = _get_outlook()
    if app is None:
        return _DEGRADED_MSG

    def _send():
        ns = app.GetNamespace("MAPI")
        try:
            draft = ns.GetItemFromID(draft_id)
        except Exception:
            return "[error] Draft not found. It may have been deleted or moved from Drafts."
        subj = draft.Subject
        to = draft.To
        draft.Send()
        return f"Email sent. Subject: '{subj}' To: {to}"

    return _com_retry(_send)
