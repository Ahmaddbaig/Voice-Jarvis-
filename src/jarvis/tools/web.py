"""fetch_page -- Tier 0 read-only tool. Extracts page content via trafilatura.

SAFE-07: Only fetches URLs returned by search_web in the current turn.
SAFE-04: Marks the turn as having external content (quarantine).
"""
import requests as http_requests
import trafilatura

from jarvis.tools._registry import tool, mark_external_content
from jarvis.tools.search import is_url_allowed

_FETCH_TIMEOUT = 12  # seconds (D-04 recommendation: 10-15s)
_TEXT_CAP = 4096     # 4 KB cap matching read_file/read_pdf (D-04)
_POOR_THRESHOLD = 50 # words below this = "poor" extraction quality


@tool(tier=0)
def fetch_page(url: str) -> str:
    """Fetch and extract the main text content of a web page. Only accepts URLs returned by search_web in this turn.

    Args:
        url: The URL to fetch (must be from current search results).
    """
    # SAFE-07: URL allow-list check (D-01, D-02)
    if not is_url_allowed(url):
        return (
            "URL not in current search results. fetch_page only accepts URLs "
            "returned by search_web in this turn. Ask me to search first, "
            "then I can fetch a specific result."
        )

    # Fetch with requests (not trafilatura.fetch_url) for URL control (D-03)
    try:
        resp = http_requests.get(
            url,
            timeout=_FETCH_TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Jarvis/1.0)"},
        )
        resp.raise_for_status()
    except Exception as exc:
        return f"[error] Failed to fetch {url}: {exc}"

    final_url = resp.url
    html = resp.text

    # Extract content via trafilatura (bare_extraction for metadata access)
    doc = trafilatura.bare_extraction(
        html,
        url=final_url,
        favor_precision=True,
        include_tables=True,
        include_comments=False,
    )

    title = "(no title)"
    text = ""
    if doc is not None:
        if isinstance(doc, dict):
            title = doc.get("title", "") or "(no title)"
            text = doc.get("text", "") or ""
        else:
            title = getattr(doc, "title", "") or "(no title)"
            text = getattr(doc, "text", "") or ""

    word_count = len(text.split()) if text else 0
    quality = "clean" if word_count >= _POOR_THRESHOLD else "poor"

    # 4 KB text cap (D-04)
    total_len = len(text)
    truncation = ""
    if total_len > _TEXT_CAP:
        text = text[:_TEXT_CAP]
        truncation = f"[...truncated at 4KB -- {total_len // 1024}KB total]"

    # SAFE-04: Mark external content -- blocks Tier 2 tools for rest of turn (D-06)
    mark_external_content()

    # Build response with metadata (D-05)
    parts = [
        f"Title: {title}",
        f"Source: {final_url}",
        f"Extraction: {quality}",
        f"Words: {word_count}",
    ]
    if truncation:
        parts.append(truncation)
    parts.append("")
    parts.append(text)
    return "\n".join(parts)
