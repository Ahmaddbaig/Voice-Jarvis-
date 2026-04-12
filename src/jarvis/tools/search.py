"""search_web -- Tier 0 read-only tool. Degrades gracefully without SearXNG."""
import requests as http_requests

from jarvis.tools._registry import tool

# SearXNG URL set by assistant.py at startup
_searxng_url: str = "http://localhost:8888"


def set_searxng_url(url: str) -> None:
    """Called once at startup to inject the configured SearXNG URL."""
    global _searxng_url
    _searxng_url = url


@tool(tier=0)
def search_web(query: str) -> str:
    """Search the web for a query via SearXNG. Returns top results or a graceful unavailable message.

    Args:
        query: The search query string.
    """
    try:
        resp = http_requests.get(
            f"{_searxng_url}/search",
            params={"q": query, "format": "json", "categories": "general"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])[:5]
        if not results:
            return f"No results found for: {query}"
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title', '(no title)')}")
            lines.append(f"   {r.get('url', '')}")
            snippet = r.get("content", "")[:200]
            if snippet:
                lines.append(f"   {snippet}")
        return "\n".join(lines)
    except Exception:
        return "(web search unavailable -- SearXNG is not running. Answering from knowledge only.)"
