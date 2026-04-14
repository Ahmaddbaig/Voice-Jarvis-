"""search_web -- Tier 0 read-only tool. Degrades gracefully without SearXNG."""
import requests as http_requests

from jarvis.tools._registry import tool, mark_external_content

# SearXNG URL set by assistant.py at startup
_searxng_url: str = "http://localhost:8888"

# SAFE-07: Per-turn URL allow-list populated by search_web, checked by fetch_page
_current_turn_urls: set[str] = set()


def set_searxng_url(url: str) -> None:
    """Called once at startup to inject the configured SearXNG URL."""
    global _searxng_url
    _searxng_url = url


def clear_turn_urls() -> None:
    """Clear the per-turn URL allow-list. Called at turn start."""
    _current_turn_urls.clear()


def register_urls(urls: list[str]) -> None:
    """Add URLs from a search result to the per-turn allow-list."""
    _current_turn_urls.update(urls)


def is_url_allowed(url: str) -> bool:
    """Check if a URL was returned by search_web this turn."""
    return url in _current_turn_urls


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
        # SAFE-07: Register URLs in per-turn allow-list
        for r in results:
            url = r.get("url", "")
            if url:
                _current_turn_urls.add(url)
        # SAFE-04: Search results are external content — block Tier 2 for this turn
        mark_external_content()
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title', '(no title)')}")
            lines.append(f"   URL: {r.get('url', '')}")
            snippet = r.get("content", "")[:200]
            if snippet:
                lines.append(f"   {snippet}")
        return "\n".join(lines)
    except Exception:
        return "(web search unavailable -- SearXNG is not running. Answering from knowledge only.)"
