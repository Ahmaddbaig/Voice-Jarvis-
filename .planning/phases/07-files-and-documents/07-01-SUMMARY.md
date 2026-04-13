---
phase: 07-files-and-documents
plan: 01
subsystem: file-access-safety
tags: [safety, file-access, dry-run, quarantine]
dependency_graph:
  requires: []
  provides: [file_access_module, safe_03_dry_run, safe_04_quarantine]
  affects: [tools/_registry.py, assistant.py]
tech_stack:
  added: [pymupdf4llm, send2trash]
  patterns: [RotatingFileHandler, module-level-flag]
key_files:
  created:
    - src/jarvis/core/file_access.py
  modified:
    - requirements.txt
    - src/jarvis/tools/_registry.py
    - src/jarvis/tools/__init__.py
    - src/jarvis/assistant.py
decisions:
  - JSON config at %LOCALAPPDATA%\Jarvis\file_access.json re-read on every call (D-03)
  - Deny rules checked first with substring/glob matching (D-01)
  - Quarantine flag is module-level bool, reset per turn (D-11)
  - actions.log uses same RotatingFileHandler pattern as wake_log.py
metrics:
  duration: 127s
  completed: 2026-04-13
---

# Phase 07 Plan 01: File Access Infrastructure + Safety Rails Summary

Path allow/denylist module with JSON config, Tier 2 dry-run preview to actions.log, and per-turn quarantine guard blocking destructive tools after external content ingestion.

## Tasks Completed

| # | Task | Commit | Key Files |
|---|------|--------|-----------|
| 1 | Add pip deps + create file_access.py | ac2df78 | requirements.txt, src/jarvis/core/file_access.py |
| 2 | Wire SAFE-03 dry-run + SAFE-04 quarantine | 3438a36 | src/jarvis/tools/_registry.py, src/jarvis/tools/__init__.py, src/jarvis/assistant.py |

## What Was Built

### file_access.py (new module)
- `check_file_access(path)` validates paths against JSON allow/denylist before any file I/O
- `load_file_access_config()` reads config from `%LOCALAPPDATA%\Jarvis\file_access.json`, creates defaults on first run
- Deny rules: substring match (case-insensitive) or glob patterns (`*.env`, `*.pem`, `*.key`)
- Allow rules: path must be under at least one allowed directory
- Config re-read on every call for hot-reload without restart

### SAFE-03: Dry-run preview
- Before any Tier 2 tool execution, a `DRY-RUN` line is written to `%LOCALAPPDATA%\Jarvis\actions.log`
- Format: `[timestamp] DRY-RUN tool_name arg1=val1 arg2=val2`
- RotatingFileHandler at 1MB with 5 backups (follows wake_log.py pattern)

### SAFE-04: Post-read quarantine
- Module-level `_turn_has_external_content` flag in `_registry.py`
- `mark_external_content()` sets the flag (called by read tools in future Plan 02)
- `call_tool` checks the flag before Tier 2 execution; returns `[blocked]` message if set
- `_turn_pipeline` resets the flag at the start of each new turn via `set_turn_has_external_content(False)`

### requirements.txt
- Added `pymupdf4llm>=0.0.17` and `send2trash>=1.8.3` for Phase 7 file tools

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

- Allowed paths (Desktop) pass check_file_access
- Denied paths (C:\Windows) raise PermissionError
- file_access.json created at %LOCALAPPDATA%\Jarvis\ on first call
- Quarantine blocks Tier 2 when flag is set
- DRY-RUN line written to actions.log before Tier 2 execution
- All imports resolve correctly

## Self-Check: PASSED
