"""Memory tools -- remember, recall, forget (MEMORY-08 / D-11)."""
from __future__ import annotations

from jarvis.tools._registry import tool

_memory_store = None


def set_memory_store(store) -> None:
    """Called by JarvisAssistant.__init__ to inject the MemoryStore instance."""
    global _memory_store
    _memory_store = store


@tool(tier=0)
def remember(fact: str) -> str:
    """Explicitly store a fact about the user in long-term memory.

    Args:
        fact: The fact to remember, e.g. "My name is Alex" or "I prefer metric units"
    """
    if _memory_store is None:
        return "[error] Memory system not available."
    _memory_store.upsert_fact(
        type="profile", key=fact[:50], value=fact, source="user"
    )
    return f"Noted. I'll remember: {fact}"


@tool(tier=0)
def recall(query: str) -> str:
    """Search long-term memory for facts and past conversations matching a query.

    Args:
        query: What to search for, e.g. "Paris trip" or "user preferences"
    """
    if _memory_store is None:
        return "[error] Memory system not available."
    results = _memory_store.recall_similar(query, k=5)
    if not results:
        return "I don't have any memories matching that query."
    lines = []
    for r in results:
        sim = r.get("similarity", 0)
        confidence = "uncertain" if sim < 0.7 else ""
        ts = r.get("ts", "")[:10]
        content = r.get("content") or r.get("value", "")
        prefix = f"[{ts}]" if ts else ""
        tag = f" ({confidence})" if confidence else ""
        lines.append(f"- {prefix}{tag} {content} (similarity: {sim:.2f})")
    return "Memory search results:\n" + "\n".join(lines)


@tool(tier=1)
def forget(fact: str) -> str:
    """Remove a fact from long-term memory. Marks matching facts as forgotten.

    Args:
        fact: Description of what to forget, e.g. "my preference for short replies"
    """
    if _memory_store is None:
        return "[error] Memory system not available."
    count = _memory_store.forget_fact(fact)
    if count == 0:
        return f"I couldn't find any stored facts matching: {fact}"
    return f"Done. Forgot {count} fact(s) related to: {fact}"
