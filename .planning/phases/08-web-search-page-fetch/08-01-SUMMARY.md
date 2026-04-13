---
phase: "08-web-search-page-fetch"
plan: "01"
subsystem: "tools/search"
tags: [web-search, searxng, docker, safe-07, trafilatura]
dependency_graph:
  requires: []
  provides: [search-url-allowlist, searxng-docker, trafilatura-dep]
  affects: [08-02-fetch-page]
tech_stack:
  added: [trafilatura, searxng-docker]
  patterns: [per-turn-url-allowlist]
key_files:
  created:
    - docker/docker-compose.yml
    - docker/settings.yml
  modified:
    - src/jarvis/tools/search.py
    - requirements.txt
    - .env.example
decisions:
  - "Per-turn URL set is module-level private; only search_web populates, is_url_allowed checks"
  - "SearXNG mapped to port 8888 to avoid conflicts with common services on 8080"
metrics:
  duration_seconds: 78
  completed: "2026-04-13"
  tasks_completed: 2
  tasks_total: 2
---

# Phase 08 Plan 01: Web Search URL Registration & SearXNG Docker Summary

Per-turn URL allow-list in search.py (SAFE-07 foundation) with SearXNG Docker config and trafilatura dependency.

## Tasks Completed

| # | Task | Commit | Key Changes |
|---|------|--------|-------------|
| 1 | Enhance search.py with URL registration + trafilatura dep | a83fb9e | Added _current_turn_urls set, clear/register/is_allowed exports, URL: prefix formatting, trafilatura in requirements.txt, SEARXNG_URL in .env.example |
| 2 | Create SearXNG Docker configuration files | 15b55cd | docker-compose.yml (port 8888, auto-restart), settings.yml (JSON API, 4 categories, no telemetry) |

## Decisions Made

1. **Per-turn URL set as module-level private** -- `_current_turn_urls` is populated only by `search_web` and checked by `is_url_allowed`. This enforces the SAFE-07 trust boundary: fetch_page can only access URLs that appeared in search results for the current turn.
2. **Port 8888 for SearXNG** -- Avoids conflicts with common services running on 8080.

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

- URL registration round-trip: register -> check -> clear -> check returns False: PASS
- Docker config file content assertions (port mapping, JSON format, container name, secret_key): PASS
- All acceptance criteria met for both tasks

## Self-Check: PASSED

All created/modified files exist and both commits verified.
