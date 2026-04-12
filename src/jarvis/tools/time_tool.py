"""get_time -- Tier 0 read-only tool."""
from jarvis.tools._registry import tool


@tool(tier=0)
def get_time() -> str:
    """Return the current date and time in the user's local timezone."""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S %Z").strip()
