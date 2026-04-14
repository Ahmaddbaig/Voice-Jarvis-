---
phase: 09-outlook-email-calendar
plan: 03
subsystem: outlook-calendar
tags: [calendar, outlook, com, dateparser, tool-use]
dependency_graph:
  requires: [09-01]
  provides: [list_events, create_event]
  affects: [tool-registry, brain-tool-dispatch]
tech_stack:
  added: [dateparser]
  patterns: [outlook-com-restrict-filter, natural-language-date-parsing]
key_files:
  modified:
    - src/jarvis/tools/outlook.py
decisions:
  - "dateparser with PREFER_DATES_FROM=future for natural-language date parsing"
  - "list_events caps at 25 events and 30 days_ahead max for DoS mitigation"
  - "create_event defaults to 60-minute duration and 15-minute reminder"
  - "IncludeRecurrences=True set after Sort per Outlook COM requirement"
metrics:
  duration_seconds: 62
  completed: "2026-04-14T04:53:39Z"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 1
---

# Phase 09 Plan 03: Calendar Tools (list_events + create_event) Summary

Two calendar tools appended to outlook.py: list_events (tier 0, Restrict filter with IncludeRecurrences for efficient date-range queries) and create_event (tier 1, dateparser with PREFER_DATES_FROM=future for natural-language scheduling, local timezone via naive datetime passthrough to Outlook COM).

## Task Results

### Task 1: Add list_events and create_event tools

**Commit:** `93bc23c`
**Files modified:** `src/jarvis/tools/outlook.py`

Added two @tool functions to outlook.py after the email tools:

- **list_events** (tier=0): Uses Outlook Restrict filter with `strftime('%m/%d/%Y %I:%M %p')` format for server-side date filtering. Sets IncludeRecurrences=True after Sort("[Start]") per COM requirement. Caps at 25 events and 30 days_ahead max (T-09-05 DoS mitigation). Returns subject, start, end, location, and EntryID for each event.

- **create_event** (tier=1): Lazy-imports dateparser. Parses natural-language date with `PREFER_DATES_FROM='future'` (D-07). Returns friendly error when dateparser returns None (T-09-04 mitigation). Creates appointment via OL_APPOINTMENT_ITEM with 60-minute default duration, optional location, and 15-minute reminder. Single events only (D-08). Naive datetime passed to Outlook COM which applies local system timezone (D-09).

Added `from datetime import datetime, timedelta` to module imports.

## Verification Results

- `from jarvis.tools.outlook import list_events, create_event` -- PASS
- Tool registry discovers both tools with correct tiers (list_events=0, create_event=1) -- PASS
- dateparser.parse works for explicit dates and relative phrases like "tomorrow 3pm" -- PASS
- dateparser returns None for some complex phrases ("next Thursday at noon") confirming our error handling is necessary -- PASS

## Deviations from Plan

None -- plan executed exactly as written.

## Self-Check: PASSED

- [x] src/jarvis/tools/outlook.py exists and contains list_events and create_event
- [x] Commit 93bc23c verified
