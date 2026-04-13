---
phase: 08-web-search-page-fetch
plan: 02
subsystem: web-tools
tags: [fetch-page, trafilatura, searxng, health-check, quarantine]
dependency_graph:
  requires: [08-01]
  provides: [fetch_page tool, SearXNGComponent, turn-start URL clearing]
  affects: [assistant.py turn pipeline, preload.py health checks]
tech_stack:
  added: [trafilatura]
  patterns: [URL allow-list enforcement, bare_extraction, degraded health status]
key_files:
  created:
    - src/jarvis/tools/web.py
  modified:
    - src/jarvis/core/component.py
    - src/jarvis/core/preload.py
    - src/jarvis/assistant.py
decisions:
  - "bare_extraction with isinstance(doc, dict) fallback for trafilatura 2.x API variance"
  - "SearXNGComponent status is degraded (not failed) since web search is optional"
  - "Component name is Web for compact tray tooltip"
metrics:
  duration: 88s
  completed: 2026-04-13
  tasks_completed: 2
  tasks_total: 2
  files_changed: 4
---

# Phase 08 Plan 02: Page Fetch and SearXNG Health Summary

fetch_page tool with URL allow-list enforcement (SAFE-07), trafilatura extraction with 4KB cap, SearXNG degraded-mode health component, and per-turn URL set clearing wired into assistant.py turn pipeline.

## Tasks Completed

### Task 1: Create fetch_page tool in web.py
- **Commit:** f125f63
- **Files:** src/jarvis/tools/web.py (created, 90 lines)
- Created Tier 0 fetch_page tool using trafilatura.bare_extraction
- SAFE-07: URL allow-list check via is_url_allowed() before any HTTP request
- SAFE-04: mark_external_content() called after successful fetch
- 12-second timeout, 4KB text cap, poor/clean quality hint at 50-word threshold
- Metadata header: Title, Source, Extraction quality, Words count
- Defensive handling of trafilatura dict vs Document return type

### Task 2: Add SearXNG component and wire turn-start URL clearing
- **Commit:** db0de94
- **Files:** src/jarvis/core/component.py, src/jarvis/core/preload.py, src/jarvis/assistant.py
- SearXNGComponent with name "Web" reports degraded (not failed) when unreachable
- Registered in preload.py after CameraComponent, before run_startup_checks
- clear_turn_urls() imported and called at turn start right after quarantine reset
- Prevents cross-turn URL leakage (T-08-09 mitigation)

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

1. fetch_page('http://not-in-set.com') returns "not in current search results" -- PASS
2. SearXNGComponent('http://localhost:99999').try_init() returns False, check() returns 'degraded' -- PASS

## Threat Mitigations Applied

| Threat ID | Mitigation |
|-----------|------------|
| T-08-04 | is_url_allowed() check before HTTP request in fetch_page |
| T-08-05 | mark_external_content() triggers SAFE-04 quarantine |
| T-08-07 | 12-second timeout + 4KB text cap |
| T-08-08 | URL set populated only by search_web, checked by fetch_page |
| T-08-09 | clear_turn_urls() at turn start prevents stale URLs |
