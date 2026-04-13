---
phase: 04-persistent-memory
plan: 01
subsystem: memory
tags: [sqlite, sqlite-vec, sentence-transformers, embeddings, pii-redaction]
dependency_graph:
  requires: []
  provides: [MemoryStore, redact_pii, Config.memory_fields, PreloadedModels.embedder]
  affects: [assistant.py, memory_tools.py]
tech_stack:
  added: [sqlite-vec>=0.1.9, sentence-transformers>=5.0.0]
  patterns: [WAL-mode SQLite, vec0 cosine KNN, PII regex redaction, typed fact expiry, supersession]
key_files:
  created:
    - src/jarvis/core/memory.py
  modified:
    - requirements.txt
    - src/jarvis/core/config.py
    - src/jarvis/core/preload.py
decisions:
  - Embed fact as "key: value" concatenation for better semantic matching
  - Use superseded_by=-1 as manual-forget sentinel value
  - Merge turn and fact KNN results in recall_similar, sort by similarity, take top-k
metrics:
  duration: 230s
  completed: 2026-04-10
---

# Phase 04 Plan 01: MemoryStore Foundation Summary

MemoryStore class with SQLite+sqlite-vec backend, 384-dim cosine embeddings via all-MiniLM-L6-v2, PII redaction, typed fact expiry (state/event=90d), automatic supersession, and semantic KNN retrieval.

## Task Results

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add dependencies + Config fields + preload embedder | b3ba51c | requirements.txt, config.py, preload.py |
| 2 | Create MemoryStore module | f83fe3e | memory.py (280+ lines) |

## What Was Built

### Task 1: Dependencies, Config, Preload
- Added `sqlite-vec>=0.1.9` and `sentence-transformers>=5.0.0` to requirements.txt
- Added 8 memory fields to Config dataclass: memory_db_path, memory_top_k, memory_profile_max_tokens, memory_recall_max_tokens, memory_total_max_tokens, memory_similarity_threshold, memory_recent_turns, memory_embedding_model
- Set memory_db_path to `%LOCALAPPDATA%/Jarvis/memory.db` in load_config()
- Added `embedder` field to PreloadedModels
- Added step [7/8] in preload_all() to load SentenceTransformer with warmup encode
- Renumbered all preload steps from N/6,N/7 to N/8

### Task 2: MemoryStore Module
- `MemoryStore.__init__`: WAL mode, sqlite-vec extension loading, schema init, stale expiry on startup
- Schema: turns (id, ts, role, content, session_id), facts (id, ts, type, key, value, source, expired, superseded_by, expires_at), vec_turns (384-dim cosine), vec_facts (384-dim cosine)
- `redact_pii()`: regex patterns for CC, SSN, US phone; emails preserved (D-10)
- `embed()`: PII-redacted text encoded via SentenceTransformer to float32
- `store_turn()`: insert turn + embedding into vec_turns
- `upsert_fact()`: typed expiry (state/event=90d), automatic supersession on same type+key with different value
- `recall_similar()`: KNN on both vec_turns and vec_facts, merged, sorted by similarity, uncertain tagging below 0.7
- `get_profile_facts()`: non-expired, non-superseded identity/preference/profile facts
- `get_recent_turns()`: last N turns as chronological message dicts
- `search_facts()`: semantic search returning formatted strings for tool output
- `forget_fact()`: marks top-3 matching facts with superseded_by=-1 sentinel

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

- `from jarvis.core.memory import MemoryStore, redact_pii` -- PASS
- `from jarvis.core.config import load_config; c.memory_top_k == 5` -- PASS
- PII redaction: CC, SSN, phone all redacted; email preserved -- PASS
- requirements.txt contains sqlite-vec and sentence-transformers -- PASS
