---
phase: 04-persistent-memory
plan: 02
subsystem: memory-wiring
tags: [memory-injection, fact-extraction, history-retirement, async, system-prompt]
dependency_graph:
  requires: [MemoryStore, PreloadedModels.embedder, Config.memory_fields]
  provides: [_build_messages, _extract_and_store_facts, memory-augmented-turns]
  affects: [assistant.py]
tech_stack:
  added: []
  patterns: [memory-augmented system prompt, async fire-and-forget extraction, DB-backed conversation history]
key_files:
  created: []
  modified:
    - src/jarvis/assistant.py
decisions:
  - Recent turns in _build_messages scoped to current session_id for short-term context
  - Extraction uses run_in_executor wrapping Brain.ask for non-blocking async
  - CLI ask_ollama path also wired to DB turns for consistency
metrics:
  duration: 163s
  completed: 2026-04-10
---

# Phase 04 Plan 02: Memory Wiring Summary

Memory-augmented system prompt with profile facts + semantic recall, self.history retired to SQLite, async LLM fact extraction after TTS via ensure_future.

## Task Results

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Wire MemoryStore into JarvisAssistant | c90fb81 | src/jarvis/assistant.py |

## What Was Built

### Task 1: Full Memory Wiring

**Change 1 - Init MemoryStore:** Added MemoryStore initialization in `__init__` after Brain construction. Voice-first mode uses preloaded embedder; CLI mode falls back to lazy SentenceTransformer load. Session ID generated via uuid4.

**Change 2 - Retire self.history:** Removed `self.history: list[dict] = []` from `__init__`. Replaced `self.history[-8:]` usage in `ask_ollama` with `self._memory.get_recent_turns()`. Replaced `self.history.append()` calls with `self._memory.store_turn()`.

**Change 3 - _build_messages helper:** Constructs memory-augmented messages list:
- Block 1: Profile facts (identity/preference/profile) capped at 500 tokens
- Block 2: Semantic recall top-K=5 with remaining budget up to 1500 tokens, total hard cap 2000
- Uncertain results (similarity < 0.7) tagged in recall block
- Recent turns loaded from DB scoped to current session
- Used in `_turn_pipeline` replacing hardcoded `[system, user]` messages

**Change 4 - Async fact extraction:** Added `EXTRACTION_SYSTEM_PROMPT` constant with 5 fact types. Added `_extract_and_store_facts` async method using `run_in_executor` for Brain.ask. Fires via `asyncio.ensure_future` in the `finally` block after `tts_playing.clear()`. Only fires on substantive replies (D-02). Handles markdown-wrapped JSON. Best-effort with exception logging.

**Change 5 - Turn storage:** User turn stored to DB after print, before Brain.ask. Assistant turn stored after reply finalized, before TTS.

**Change 6 - Memory close:** `self._memory.close()` called in `close()` before audit log close.

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

- EXTRACTION_SYSTEM_PROMPT contains all 5 fact types (identity, preference, profile, state, event) -- PASS
- self.history not actively assigned in __init__ -- PASS
- _build_messages method exists on JarvisAssistant -- PASS
- _extract_and_store_facts method exists on JarvisAssistant -- PASS
- _estimate_tokens static method exists -- PASS
- Clean import of JarvisAssistant succeeds -- PASS
