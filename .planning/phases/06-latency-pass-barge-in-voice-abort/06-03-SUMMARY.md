---
phase: 06-latency-pass-barge-in-voice-abort
plan: 03
subsystem: audio-output, assistant
tags: [kokoro, sentence-streaming, crossfade, tts, latency]
dependency_graph:
  requires:
    - plan: 06-01
      provides: play_cancellable, OutputStream migration, TimingLog
    - plan: 06-02
      provides: barge-in, voice-abort, fast-ack concurrent brain
  provides:
    - split_sentences() for abbreviation-aware sentence boundary detection
    - crossfade() for linear overlap-add between audio arrays
    - FallbackTTS.speak_streaming() for sentence-level Kokoro TTS with crossfade
    - tts_first_audio timing stage for wake-to-first-audio measurement
    - Preload verification print at startup
  affects: [assistant._turn_pipeline, audio.output.FallbackTTS]
tech_stack:
  added: []
  patterns: [sentence-streaming-tts, linear-crossfade, split-then-synth]
key_files:
  created: []
  modified:
    - src/jarvis/audio/output.py
    - src/jarvis/assistant.py
key_decisions:
  - "Variable-width lookbehind avoided by using split-then-merge approach for sentence splitting"
  - "Decimal numbers at sentence end (3.14.) treated as real boundaries since the period is the sentence terminator"
  - "Crossfade uses tail-save pattern: each sentence saves its last overlap_samples for next iteration"
patterns_established:
  - "Sentence streaming: pre-split text outside KPipeline, pass each sentence with split_pattern=None"
  - "Crossfade tail pattern: save last N samples of each sentence, crossfade with start of next"
requirements-completed: [PERF-02, PERF-04]
metrics:
  duration: 170s
  completed: "2026-04-13"
---

# Phase 06 Plan 03: Kokoro Sentence Streaming with Crossfade Summary

**Sentence-by-sentence Kokoro TTS with 30ms linear crossfade, abbreviation-aware splitting, and tts_first_audio timing stage for latency measurement**

## Performance

- **Duration:** 2m 50s
- **Started:** 2026-04-13T05:10:08Z
- **Completed:** 2026-04-13T05:12:58Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Sentence splitter that respects abbreviations (Mr., Dr., etc.) and correctly handles decimals at sentence boundaries
- Linear crossfade utility producing smooth overlap-add between 1D float32 audio arrays
- FallbackTTS.speak_streaming() synthesizes per-sentence with Kokoro (split_pattern=None), plays with crossfade, checks cancel between 50ms chunks
- tts_first_audio timing stage logged before TTS playback for PERF-02 wake-to-first-audio measurement
- Preload verification message confirms all models resident at startup (PERF-05)

## Task Commits

1. **Task 1: Sentence splitter + crossfade + speak_streaming** - `8242cb0` (feat)
2. **Task 2: Wire speak_streaming + timing + preload verification** - `af48884` (feat)

## Files Created/Modified
- `src/jarvis/audio/output.py` - Added split_sentences(), crossfade(), FallbackTTS.speak_streaming()
- `src/jarvis/assistant.py` - Wired speak_streaming into _turn_pipeline, added tts_first_audio timing, preload verification print

## Decisions Made
- Used split-then-merge approach for sentence splitting instead of variable-width lookbehind (Python re module limitation)
- Decimal numbers at sentence end ("3.14.") are correctly treated as sentence boundaries since the period terminates the sentence
- Crossfade uses tail-save pattern from Research Pattern 3: save last overlap_samples of each sentence, crossfade with start of next

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed variable-width lookbehind regex error**
- **Found during:** Task 1
- **Issue:** Plan's regex used `(?<!\b(?:Mr|Mrs|...)\.)` which Python re rejects as variable-width lookbehind
- **Fix:** Replaced with split-then-merge approach: split on all `[.!?]\s+`, then re-merge false positives using abbreviation pattern check
- **Files modified:** src/jarvis/audio/output.py
- **Verification:** split_sentences tests pass for abbreviations, decimals, and normal sentences
- **Committed in:** 8242cb0

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Regex limitation required alternative approach. Same behavior, different implementation. No scope creep.

## Issues Encountered
None beyond the regex fix above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 06 plans 01-03 complete: OutputStream migration, timing, cancel support, barge-in, voice abort, fast-ack, sentence streaming
- Ready for Phase 06 Plan 04+ (if any) or phase gate verification

---
*Phase: 06-latency-pass-barge-in-voice-abort*
*Completed: 2026-04-13*
