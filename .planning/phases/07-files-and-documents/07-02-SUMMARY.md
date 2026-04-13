---
phase: 07-files-and-documents
plan: 02
subsystem: file-tools
tags: [file-io, pdf, recycle-bin, quarantine]
dependency_graph:
  requires: [file_access_module, safe_03_dry_run, safe_04_quarantine]
  provides: [read_file, read_pdf, write_file, delete_file, search_files]
  affects: [tools/_registry.py]
tech_stack:
  added: []
  patterns: [check_file_access-guard, mark_external_content-on-read]
key_files:
  created:
    - src/jarvis/tools/files.py
  modified: []
decisions:
  - UTF-8 default with latin-1 fallback for read_file encoding
  - search_files depth limited to 3 levels for non-recursive globs, max 50 results
  - mark_external_content called only by read_file and read_pdf (not write/delete/search)
metrics:
  duration: 89s
  completed: 2026-04-10
---

# Phase 07 Plan 02: File I/O Tools Summary

Five file tools (read_file, read_pdf, write_file, delete_file, search_files) with path validation via check_file_access and quarantine marking on read operations.

## Tasks Completed

| # | Task | Commit | Key Files |
|---|------|--------|-----------|
| 1 | Create all 5 file tools in files.py | da4684c | src/jarvis/tools/files.py |

## What Was Built

### src/jarvis/tools/files.py (new module, 5 tools)

- **read_file** (Tier 0): Reads text/markdown/code files. UTF-8 with latin-1 fallback. Calls `mark_external_content()` after successful read to trigger SAFE-04 quarantine.
- **read_pdf** (Tier 0): Reads PDF via `pymupdf4llm.to_markdown()` for LLM-friendly output. Validates `.pdf` extension. Calls `mark_external_content()` after successful read.
- **write_file** (Tier 2): Writes text content with UTF-8 encoding. Creates parent directories automatically. Dry-run preview and quarantine enforced by call_tool.
- **delete_file** (Tier 2): Sends files to Recycle Bin via `send2trash.send2trash()`. Verifies file exists before attempting deletion. Dry-run preview and quarantine enforced by call_tool.
- **search_files** (Tier 0): Glob-based file search within allow-listed directories. Depth limited to 3 levels for non-recursive patterns. Returns up to 50 relative paths.

All 5 tools call `check_file_access(path)` as their first operation before any I/O.

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

- All 5 tools import correctly from `jarvis.tools.files`
- All 5 tools auto-discovered by pkgutil via `discover_tools()`
- Registered tools: read_file (T0), read_pdf (T0), write_file (T2), delete_file (T2), search_files (T0)

## Self-Check: PASSED
