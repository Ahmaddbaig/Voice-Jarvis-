---
phase: 06-latency-pass-barge-in-voice-abort
plan: 01
subsystem: audio-output, core-timing, config
tags: [tts, cancellation, timing, barge-in,OutputStream]
dependency_graph:
  requires: []
  provides: [TimingLog, play_cancellable, cancellable-TTS, fast-ack-pool, barge_in_threshold]
  affects: [assistant._turn_pipeline, audio.output.FallbackTTS, audio.output.CloudTTS, audio.output.PiperAck]
tech_stack:
  added: []
  patterns: [sd.OutputStream-cancel-event, play_cancellable-helper, timing-to-SQLite]
key_files:
  created:
    - src/jarvis/core/timing.py
  modified:
    - src/jarvis/core/config.py
    - src/jarvis/audio/output.py
    - src/jarvis/assistant.py
decisions:
  - TimingLog shares jarvis.db with AuditLog (same db_path)
  - turn_id generated once at pipeline start, reused for both timing and audit
  - Barge-in wake detection uses cfg.barge_in_threshold for self-trigger vs user discrimination
  - play_cancellable uses 50ms chunks for ~50ms cancellation latency
metrics:
  duration: 207s
  completed: "2026-04-13"
---

# Phase 06 Plan 01: OutputStream Migration + Timing Infrastructure Summary

OutputStream cancel-event pattern for all TTS playback, SQLite timing table, barge_in_threshold config, and fast-ack phrase pool pre-synthesized at startup.

## What Was Built

### TimingLog (PERF-01, D-16)
- New `src/jarvis/core/timing.py` with `TimingLog` class following AuditLog pattern
- Schema: `timing(id, ts, turn_id, stage, elapsed_ms)` in shared jarvis.db
- Wired into `_turn_pipeline` via `log_t` closure -- every stage writes to both stdout and SQLite via `run_in_executor`

### Cancellable TTS Playback (D-03)
- New `play_cancellable()` module-level helper in output.py using `sd.OutputStream` with 50ms chunk writes
- `FallbackTTS.speak()` -- all `sd.play(blocking=True)` replaced with `play_cancellable` for Kokoro (Tier 1) and Piper (Tier 2); SAPI (Tier 3) left as-is
- `PiperAck.play_ack()` -- migrated from `sd.play` to `play_cancellable`
- `CloudTTS.speak()` -- cancel event check added between chunk writes, `stream.abort()` on cancel
- Zero `sd.play()` calls remain in output.py

### TTS Cancel Event Wiring
- `_tts_cancel = threading.Event()` created in `JarvisAssistant.__init__`
- Cleared before TTS playback, passed to all speak() calls
- Set on hotkey abort (`_on_hotkey_triggered`)
- Set on barge-in wake detection (`_on_wake_detected` when score >= threshold)

### Barge-In Threshold (D-01, D-02)
- `barge_in_threshold: float = 0.90` added to Config dataclass
- Populated from `JARVIS_BARGE_IN_THRESHOLD` env var in `load_config()`
- `_on_wake_detected` updated: low-confidence during TTS suppressed as self-trigger, high-confidence allowed through as barge-in

### Fast-Ack Phrase Pool (D-10, PERF-05)
- `FAST_ACK_PHRASES` constant with 5 phrases exported from output.py
- `PiperAck._cache_fast_ack_pool()` pre-synthesizes all phrases at startup
- `PiperAck.fast_ack_pool` property exposes the cached (audio, sr) tuples

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Duplicate turn_id declaration**
- **Found during:** Task 2
- **Issue:** Plan instructed adding `turn_id` at pipeline start, but existing code already had `turn_id = str(uuid.uuid4())` later for audit log
- **Fix:** Removed the later declaration; single turn_id at pipeline start serves both timing and audit
- **Commit:** b2fb14b

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 8a28033 | TimingLog + config barge_in_threshold + fast-ack phrase pool |
| 2 | b2fb14b | OutputStream migration + cancel support + timing wiring |

## Self-Check: PASSED
