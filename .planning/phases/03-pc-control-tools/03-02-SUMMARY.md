---
phase: 03-pc-control-tools
plan: 02
subsystem: pc-action-tools
tags: [app-launch, window-management, volume-control, media-keys]
dependency_graph:
  requires: [pycaw-dep, pywin32-dep, image-bypass]
  provides: [launch-app-tool, manage-window-tool, set-volume-tool, media-control-tool]
  affects: []
tech_stack:
  added: []
  patterns: [3-tier-app-fallback, AttachThreadInput-focus-steal, pycaw-COM-per-call, ctypes-SendInput]
key_files:
  created:
    - src/jarvis/tools/app_launch.py
    - src/jarvis/tools/window.py
    - src/jarvis/tools/volume.py
  modified: []
decisions:
  - Single manage_window tool with Literal action enum (not 3 separate tools)
  - set_volume + media_control as two separate tools (different tiers)
  - COM init/uninit per function call for thread safety (pycaw and WScript.Shell)
metrics:
  duration: 127s
  completed: 2026-04-13
---

# Phase 03 Plan 02: App Launch, Window Management, Volume + Media Control Summary

Three action tool files: app_launch.py with 3-tier fallback (start cmd, Start Menu .lnk search, app_map.json), window.py with AttachThreadInput focus-steal hack, and volume.py with pycaw COM volume control + ctypes SendInput media keys.

## Tasks Completed

| # | Task | Commit | Key Changes |
|---|------|--------|-------------|
| 1 | Create app_launch.py with 3-tier fallback | 413eeca | launch_app tool: start cmd -> .lnk search -> app_map.json |
| 2 | Create window.py with manage_window tool | fbbdc4f | manage_window(title, action) with focus/minimize/close |
| 3 | Create volume.py with set_volume and media_control | 4d6c38b | set_volume (pycaw, tier 1) + media_control (SendInput, tier 0) |

## Deviations from Plan

None - plan executed exactly as written.

## Decisions Made

1. **Single manage_window tool**: Used one tool with `action: Literal["focus", "minimize", "close"]` rather than three separate tools. Smaller schema for the LLM, enum makes valid actions explicit.
2. **Separate volume and media tools**: `set_volume` (tier 1, COM-based) and `media_control` (tier 0, pure ctypes) kept separate because they have different tier levels and different underlying mechanisms.
3. **COM lifecycle per call**: Both app_launch.py (WScript.Shell for .lnk resolution) and volume.py (pycaw) call `pythoncom.CoInitialize()` at function entry and `CoUninitialize()` in finally blocks, since tool functions run in executor threads.

## Verification Results

- All 4 tools auto-discovered via pkgutil (10 total tools registered)
- `set_volume` schema shows `level` as `integer` type
- `manage_window` schema shows `action` as `enum: ["focus", "minimize", "close"]`
- `media_control` schema shows `action` as `enum: ["play_pause", "next", "prev", "mute"]`
- `launch_app` schema shows `name` as `string` type
