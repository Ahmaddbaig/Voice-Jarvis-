"""External chat tools -- Discord webhook posting.

ACT-COMM-01: post_to_chat sends messages to Discord via webhook.
Tier 2 classification: destructive/external (same pattern as send_draft).
"""
from __future__ import annotations

import logging
import os

import requests as http_requests

from jarvis.tools._registry import tool

_logger = logging.getLogger(__name__)

_DEGRADED_MSG = (
    "I don't have chat access configured right now, sir. "
    "Set JARVIS_DISCORD_WEBHOOK in .env to enable Discord messaging."
)

_VALID_PREFIXES = (
    "https://discord.com/api/webhooks/",
    "https://discordapp.com/api/webhooks/",
)

_DISCORD_MAX_LEN = 2000


@tool(tier=2)
def post_to_chat(message: str) -> str:
    """Post a message to the configured Discord channel via webhook.

    Args:
        message: The message text to post (max 2000 characters).
    """
    webhook_url = os.environ.get("JARVIS_DISCORD_WEBHOOK", "").strip()
    if not webhook_url:
        return _DEGRADED_MSG

    # T-10-03: Validate webhook URL prefix
    if not webhook_url.startswith(_VALID_PREFIXES):
        return "[error] JARVIS_DISCORD_WEBHOOK does not look like a valid Discord webhook URL."

    # Truncate to Discord's 2000-char limit
    if len(message) > _DISCORD_MAX_LEN:
        message = message[:_DISCORD_MAX_LEN - 3] + "..."

    try:
        resp = http_requests.post(
            webhook_url,
            json={"content": message, "username": "Jarvis"},
            timeout=10,
        )
        resp.raise_for_status()
        return f"Message posted to Discord ({len(message)} chars)."
    except http_requests.exceptions.RequestException as exc:
        return f"[error] Discord webhook failed: {exc}"
