---
phase: 09-outlook-email-calendar
plan: 01
subsystem: outlook-com-infrastructure
tags: [outlook, com, pywin32, health-check, email]
dependency_graph:
  requires: []
  provides: [outlook-com-helpers, outlook-health-component, dateparser-dep]
  affects: [09-02, 09-03]
tech_stack:
  added: [dateparser]
  patterns: [com-lazy-init, com-retry, degraded-component]
key_files:
  created:
    - src/jarvis/tools/outlook.py
  modified:
    - requirements.txt
    - src/jarvis/core/component.py
    - src/jarvis/core/preload.py
decisions:
  - OutlookComponent uses degraded (not failed) status when Outlook absent, matching SearXNGComponent pattern
  - COM lazy init with thread lock and global availability flag for fast-exit after first failure
metrics:
  duration: 77s
  completed: 2026-04-13
  tasks: 1
  files: 4
---

# Phase 09 Plan 01: Outlook COM Infrastructure Summary

Outlook COM bridge foundation with lazy init, retry helper, folder constants, and health monitoring component -- no tool functions yet (Plans 02/03 add those).

## Task Results

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add dateparser dep + OutlookComponent + outlook.py COM infrastructure | fc54628 | requirements.txt, component.py, preload.py, outlook.py |

## What Was Built

1. **requirements.txt** -- Added `dateparser>=1.4.0` under Phase 9 section
2. **src/jarvis/tools/outlook.py** -- COM infrastructure module:
   - `_get_outlook()` -- lazy COM init with `pythoncom.CoInitialize()`, thread lock, availability caching
   - `_com_retry(fn, max_retries=3)` -- retry on `RPC_E_CALL_REJECTED` with exponential backoff
   - `_DEGRADED_MSG` -- standard message when Outlook unavailable
   - Folder constants: `OL_FOLDER_INBOX`, `OL_FOLDER_CALENDAR`, `OL_FOLDER_DRAFTS`, `OL_FOLDER_SENT`, `OL_MAIL_ITEM`, `OL_APPOINTMENT_ITEM`
3. **src/jarvis/core/component.py** -- `OutlookComponent(_ComponentBase)` with name "Mail", degraded-on-missing pattern
4. **src/jarvis/core/preload.py** -- Imported and registered `OutlookComponent()` after SearXNGComponent

## Decisions Made

- OutlookComponent sets status to "degraded" (not "failed") when Outlook is absent, consistent with SearXNGComponent pattern for optional services
- COM lazy init uses module-level `_outlook_available` flag with `threading.Lock` for thread safety and fast-exit after first failure detection

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

- `from jarvis.tools.outlook import _get_outlook, _com_retry, _DEGRADED_MSG, OL_FOLDER_INBOX` -- PASS
- `OutlookComponent().name == "Mail"` -- PASS
- `import dateparser` -- PASS (version 1.4.0)

## Self-Check: PASSED
