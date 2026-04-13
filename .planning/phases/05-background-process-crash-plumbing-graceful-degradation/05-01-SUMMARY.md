---
phase: 05-background-process-crash-plumbing-graceful-degradation
plan: 01
subsystem: core/component-health
tags: [component-protocol, health-checks, dependencies]
dependency_graph:
  requires: []
  provides: [component-protocol, component-registry, health-checks]
  affects: [preload, main, assistant]
tech_stack:
  added: [pystray, winotify]
  patterns: [structural-typing-protocol, registry-pattern]
key_files:
  created:
    - src/jarvis/core/component.py
  modified:
    - requirements.txt
    - src/jarvis/core/preload.py
    - src/jarvis/main.py
decisions:
  - Component uses typing.Protocol (structural typing) not ABC
  - Camera component abbreviated to "Cam" in tooltip for brevity
  - Shared _ComponentBase helper class for DRY without requiring inheritance
metrics:
  duration: 124s
  completed: "2026-04-10"
---

# Phase 5 Plan 1: Component Protocol + Health Checks Summary

Component protocol with 5 subsystem wrappers, ComponentRegistry with compact tooltip, and startup health checks wired into preload_all returning (PreloadedModels, ComponentRegistry) tuple.

## Completed Tasks

| # | Task | Commit | Key Files |
|---|------|--------|-----------|
| 1 | Add deps + create Component protocol and registry | 470c3d6 | requirements.txt, src/jarvis/core/component.py |
| 2 | Wire health checks into preload_all | aeb8c01 | src/jarvis/core/preload.py, src/jarvis/main.py |

## Deviations from Plan

None - plan executed exactly as written.

## Key Outputs

- **Component Protocol** (`typing.Protocol`, `@runtime_checkable`): `try_init() -> bool`, `check() -> str`, `status() -> str`, `last_error() -> str | None`
- **ComponentRegistry**: `health_summary()` returns tooltip under 128 chars (50 chars actual), `run_startup_checks()`, `try_recover_all()`, iterable
- **5 Wrappers**: WakeComponent (mic probe), STTComponent (whisper not-None), BrainComponent (Ollama /api/tags or OPENAI_API_KEY), TTSComponent (kokoro or piper not-None), CameraComponent (cv2.VideoCapture)
- **preload_all** returns `(PreloadedModels, ComponentRegistry)` with step [9/9] health checks
- **main.py** unpacks as `models, _registry = preload_all(cfg)` to preserve voice-first entry
- **requirements.txt** has `pystray>=0.19.5` and `winotify>=1.1.0`

## Decisions Made

1. **Protocol over ABC**: `typing.Protocol` with `@runtime_checkable` -- structural typing means existing classes can satisfy the contract without inheriting from anything.
2. **_ComponentBase helper**: Shared base class for DRY (`_succeed`, `_fail`, `set_status`), but not an ABC -- wrappers use it by inheritance of convenience, not contract.
3. **"Cam" abbreviation**: Camera component uses `name="Cam"` to keep tooltip compact (50 chars total vs 128 char limit).
