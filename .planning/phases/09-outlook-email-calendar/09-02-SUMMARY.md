---
phase: "09"
plan: "02"
subsystem: outlook-email
tags: [email, outlook, com, tools, quarantine, safety]
dependency_graph:
  requires: ["09-01"]
  provides: ["list_inbox", "read_email", "draft_email", "send_draft"]
  affects: ["_registry.py (quarantine via mark_external_content)"]
tech_stack:
  added: []
  patterns: ["COM retry with _com_retry", "SAFE-04 quarantine on read_email", "two-turn speed bump via draft_id"]
key_files:
  created: []
  modified: ["src/jarvis/tools/outlook.py"]
decisions:
  - "list_inbox tier 0 with no quarantine -- metadata only, not untrusted content"
  - "read_email tier 0 with quarantine -- email bodies are untrusted external content"
  - "draft_email tier 1 -- reversible (user can delete from Drafts)"
  - "send_draft tier 2 -- irreversible, gets automatic dry-run + quarantine check from call_tool"
metrics:
  duration: "80s"
  completed: "2026-04-13"
  tasks_completed: 2
  tasks_total: 2
---

# Phase 09 Plan 02: Email Tools (list, read, draft, send) Summary

Four Outlook email tools with tiered safety: inbox listing (tier 0, no quarantine), email reading (tier 0, triggers SAFE-04 quarantine), drafting (tier 1, saves to Drafts only), and sending drafts (tier 2, requires draft_id from prior turn for two-turn speed bump).

## Tasks Completed

### Task 1: Add list_inbox and read_email tools
- **Commit:** b6527a2
- **Files:** src/jarvis/tools/outlook.py
- Added `list_inbox` (tier 0) -- lists recent inbox emails with subject, sender, date, read status, and EntryID. Does NOT trigger quarantine per D-12 (metadata only).
- Added `read_email` (tier 0) -- reads full email body with 4KB truncation cap. Calls `mark_external_content()` to trigger SAFE-04 quarantine per D-11.
- Both use `_get_outlook()` with degraded message fallback and `_com_retry` for COM resilience.

### Task 2: Add draft_email and send_draft tools
- **Commit:** 20fae4b
- **Files:** src/jarvis/tools/outlook.py
- Added `draft_email` (tier 1) -- creates email and saves to Drafts folder via `.Save()`. Returns `draft_id` (EntryID) enabling the two-turn speed bump (D-06).
- Added `send_draft` (tier 2) -- sends a previously drafted email by `draft_id`. Tier 2 classification means `call_tool` automatically writes dry-run preview to actions.log and checks SAFE-04 quarantine before execution.
- Both use `_get_outlook()` with degraded message fallback and `_com_retry` for COM resilience.

## Verification Results

- All four tools importable: `list_inbox`, `read_email`, `draft_email`, `send_draft`
- Tier verification: list_inbox=0, read_email=0, draft_email=1, send_draft=2
- `read_email` contains `mark_external_content()` call
- `list_inbox` does NOT contain `mark_external_content`
- `draft_email` uses `.Save()` only, never `.Send()`
- `send_draft` uses `.Send()` with subject/to captured before send

## Deviations from Plan

None -- plan executed exactly as written.

## Known Stubs

None -- all four tools are fully implemented with real COM calls.

## Decisions Made

1. **list_inbox no quarantine** -- Listing inbox metadata (subject, sender, date) is not untrusted content injection risk, so no quarantine trigger.
2. **read_email quarantine** -- Email bodies are untrusted external content that could contain prompt injection; quarantine blocks Tier 2 tools for the rest of the turn.
3. **draft_email tier 1** -- Saving to Drafts is reversible (user can delete), so tier 1 is appropriate.
4. **send_draft tier 2 with draft_id** -- Sending is irreversible. Requiring `draft_id` from a prior `draft_email` call enforces the two-turn speed bump (D-06).
