---
phase: 05-background-process-crash-plumbing-graceful-degradation
plan: 03
subsystem: assistant/degradation
tags: [graceful-degradation, component-registry, auto-recovery, reliability]
dependency_graph:
  requires: [component-protocol, component-registry, health-checks, background-entry-point]
  provides: [degradation-matrix, auto-recovery, registry-wiring]
  affects: [assistant, main, jarvis-pyw]
tech_stack:
  added: []
  patterns: [per-turn-auto-recovery, stage-level-try-except, component-status-update]
key_files:
  created: []
  modified:
    - src/jarvis/assistant.py
    - src/jarvis.pyw
    - src/jarvis/main.py
decisions:
  - Stage-level try/except inside _turn_pipeline for brain, TTS, STT, and camera (not outer wrapper)
  - Registry iterator pattern to find components by name for set_status calls
  - STT degradation speaks message via TTS before returning early
metrics:
  duration: 98s
  completed: "2026-04-13"
---

# Phase 5 Plan 3: Wire ComponentRegistry + Graceful Degradation Matrix Summary

ComponentRegistry wired into JarvisAssistant with per-turn auto-recovery and stage-level degradation for brain, TTS, STT, and camera -- any single subsystem failure degrades capability instead of crashing.

## Completed Tasks

| # | Task | Commit | Key Files |
|---|------|--------|-----------|
| 1 | Wire ComponentRegistry into JarvisAssistant with degradation matrix | 6e9b87a | src/jarvis/assistant.py |
| 2 | Pass registry to assistant from jarvis.pyw and main.py | 019401d | src/jarvis.pyw, src/jarvis/main.py |

## Deviations from Plan

None - plan executed exactly as written.

## Key Outputs

- **assistant.py constructor**: Accepts optional `registry: ComponentRegistry` parameter, stored as `self._registry`
- **Auto-recovery (D-11)**: `registry.try_recover_all()` called at top of every `_turn_pipeline` turn, retrying degraded/failed components
- **Brain degradation (D-13)**: Exception from `_brain.ask()` speaks "I'm sorry sir, my brain is unavailable at the moment" and returns early; sets Brain component to "failed"
- **TTS degradation (D-13)**: Exception from any TTS path prints reply text to log (`[degraded] TTS failed, reply was: ...`); sets TTS component to "failed"
- **STT degradation (D-13)**: Exception from whisper transcription speaks "Speech recognition is unavailable, sir" and returns early; sets STT component to "failed"
- **Camera degradation (D-13)**: Exception from vision skips image attachment and proceeds text-only; sets Cam component to "failed"
- **Registry wiring**: Both `jarvis.pyw` and `main.py` pass `registry=registry` to JarvisAssistant
- **D-16 compliance**: `jarvis.py` and `jarvis_cli.py` remain untouched

## Decisions Made

1. **Stage-level try/except**: Degradation wrapping goes inside `_turn_pipeline` around specific stage calls (brain, TTS, STT, camera), not as an outer wrapper. This follows the architecture rule of exactly three try/except locations.
2. **Registry iterator for component lookup**: Uses `for c in self._registry` with name matching to find the right component for `set_status` calls, avoiding tight coupling to specific component classes.
3. **STT degradation speaks before returning**: When STT fails, attempts to speak the degradation message via TTS before returning early, with a fallback to log if TTS is also down.

## Self-Check: PASSED
