---
phase: 06-latency-pass-barge-in-voice-abort
plan: 02
subsystem: assistant, audio-input
tags: [barge-in, voice-abort, fast-ack, latency]
dependency_graph:
  requires: [play_cancellable, fast-ack-pool, barge_in_threshold, tts_cancel]
  provides: [barge-in-discrimination, voice-abort-rail, fast-ack-concurrent-brain]
  affects: [assistant._on_wake_detected, assistant._turn_pipeline]
tech_stack:
  added: []
  patterns: [abort-on-barge-in, keyword-abort-rail, concurrent-ack-brain]
key_files:
  created: []
  modified:
    - src/jarvis/assistant.py
decisions:
  - Barge-in calls abort_controller.abort() to cancel current turn task and kill Popens
  - ABORT_KEYWORDS is a frozenset for O(1) lookup
  - Voice abort when idle falls through to brain with "I said stop but nothing is running" text
  - Fast-ack only on first brain call iteration, skipped for tool-call loop iterations
  - Fast-ack sets tts_playing during playback so barge-in works even during ack
metrics:
  duration: 113s
  completed: "2026-04-13"
---

# Phase 06 Plan 02: Barge-In + Voice Abort + Fast-Ack Concurrent Summary

Barge-in discrimination allowing user interrupts during TTS, voice abort keyword rail before brain, and Piper fast-ack playing concurrently with brain call on local path.

## What Was Built

### Barge-In Discrimination (D-01, D-02, VOICE-07)
- `_on_wake_detected` updated: high-confidence wake detections during TTS (score >= barge_in_threshold) fire `_tts_cancel.set()` + `abort_controller.abort()` then enqueue new turn
- Low-confidence detections during TTS logged as `suppressed_self_trigger` and dropped
- Abort call cancels asyncio task, terminates Popens, stops audio -- full abort rail

### Voice Abort Keywords (D-05, D-06, D-07, PERF-06)
- `ABORT_KEYWORDS = frozenset({"stop", "cancel", "abort", "nevermind", "never mind"})` at module level
- Check inserted after STT transcription, before brain call
- When busy: fires full abort rail (tts_cancel + abort_controller.abort)
- When idle: rewrites user_text to "I said stop but nothing is running" and falls through to brain

### Fast-Ack Concurrent with Brain (D-09, D-11, PERF-03)
- New `_run_brain_with_fast_ack()` method on JarvisAssistant
- Uses `asyncio.create_task` for ack playback + `await run_brain()` pattern
- Brain sets cancel_ack event when it returns; ack task awaited before real TTS starts
- Only activates when: provider != "openai", piper_ack exists, fast_ack_pool non-empty
- First iteration of tool-call loop uses fast-ack; subsequent iterations use plain brain call
- Ack sets tts_playing so barge-in works even during the ack phrase

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Log event name mismatch from Plan 01**
- **Found during:** Task 1
- **Issue:** Plan 01 used `suppressed_tts` as the wake log event name but Plan 02 specifies `suppressed_self_trigger` for clarity
- **Fix:** Renamed the event to `suppressed_self_trigger` to match the barge-in discrimination semantics
- **Commit:** b08e69b

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | b08e69b | Barge-in discrimination + voice abort keywords |
| 2 | 97aac48 | Fast-ack concurrent with brain call |

## Self-Check: PASSED
