---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Cross-Platform Personal Assistant — Hybrid Brain + Computer Use
status: planning
last_updated: "2026-07-05T05:12:33.819Z"
last_activity: 2026-07-05
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-05)

**Core value:** Jarvis takes real actions for its user, by voice, and stays useful with no internet connection.
**Current focus:** Phase 11 — Cross-Platform Foundation

## Current Position

Phase: 11 of 14 (Cross-Platform Foundation)
Plan: — (roadmap created, not yet planned)
Status: Ready to plan
Last activity: 2026-07-05 — ROADMAP.md created for v2.0, all 25 requirements mapped across Phases 11-14

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**

- Total plans completed: 7
- Average duration: — (no data yet)
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| — | — | — | — |
| 08 | 2 | - | - |
| 09 | 3 | - | - |
| 10 | 2 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: — (no data yet)

*Updated after each plan completion*
| Phase 02 P01 | 340s | 2 tasks | 14 files |
| Phase 02 P02 | 153s | 2 tasks | 6 files |
| Phase 02 P03 | 208 | 2 tasks | 8 files |
| Phase 02 P04 | 89s | 1 tasks | 1 files |
| Phase 03 P01 | 117 | 3 tasks | 3 files |
| Phase 03 P03 | 110s | 2 tasks | 3 files |
| Phase 03 P02 | 127s | 3 tasks | 3 files |
| Phase 04 P01 | 230s | 2 tasks | 4 files |
| Phase 04 P02 | 163 | 1 tasks | 1 files |
| Phase 04 P03 | 95s | 1 tasks | 2 files |
| Phase 05 P01 | 124s | 2 tasks | 4 files |
| Phase 05 P02 | 71s | 2 tasks | 3 files |
| Phase 05 P03 | 98s | 2 tasks | 3 files |
| Phase 06 P01 | 207s | 2 tasks | 4 files |
| Phase 06 P02 | 113s | 2 tasks | 1 files |
| Phase 06 P03 | 170s | 2 tasks | 2 files |
| Phase 07 P01 | 127 | 2 tasks | 5 files |
| Phase 07 P02 | 89s | 1 tasks | 1 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Roadmap (v2.0): Build order is strict-dependency-chained — Phase 11 (cross-platform foundation) unblocks macOS testability for everything else; Phase 12 (hybrid brain) is a hard prerequisite for Phase 13 (computer-use needs Claude vision routing); Phase 14 (proactive scheduler) depends on both the router and whichever calendar tool Phase 11 produced
- Roadmap (v2.0): DRIVER-01/02/03 (autostart, menu-bar/tray status, crash auto-restart) folded into Phase 11 rather than a separate phase — they're mechanical, cross-platform, and validate the "runs unattended on macOS" story early
- Roadmap (v2.0): PRES-01/02/03 (personality, memory callbacks, natural TTS cadence) folded into Phase 12 rather than a standalone phase — persona/system-prompt work and canonical provider-agnostic history both live in the brain layer; research recommends iterating persona continuously across Phases 12-14, not as a discrete deliverable
- Roadmap: Voice loop before tool use — independently valuable, isolates audio-stack risk from tool-calling risk
- Roadmap: Single-file through Phase 1; `jarvis/` package split happens in Phase 2 with the tool registry
- Roadmap: Brain model is NOT committed — Phase 2 ships the `jarvis_cli.py test_tools` A/B harness across gemma4 / qwen3:4b / qwen3:14b; winner picked by measurement
- Roadmap: Abort rail ships working in Phase 2 (same day as first Tier 1 tool), not as Phase 5 polish
- Roadmap: Tier 2 destructive tools first appear in Phase 7 (Files) — that's where SAFE-03/04 dry-run + post-read quarantine land
- [Phase 02]: Used git mv for file moves to preserve blame; ContinuousVision verbatim in assistant.py; thin launchers use sys.path.insert for package resolution
- [Phase 02]: Brain._ask_openai uses Chat Completions API (migrated from Responses API); dynamic num_ctx 16384/4096 for tools/no-tools; tool schemas unified for OpenAI+Ollama
- [Phase 02]: Audit log uses write-ahead pattern: insert before execution, update after
- [Phase 02]: Tool results wrapped in untrusted_content markers before LLM consumption (SAFE-06)
- [Phase 02]: Fresh Brain per scenario, graceful model skip, 7 scenarios for eval harness
- [Phase 03]: Image results (data:image/) bypass 4KB truncation in call_tool; OpenAI uses image_url content blocks, Ollama uses follow-up user message with images field
- [Phase 03]: Pillow added as explicit dep for screenshot JPEG encoding; take_screenshot returns data:image/jpeg;base64 URL triggering Plan 01 vision pipeline
- [Phase 03]: Single manage_window tool with Literal action enum (focus/minimize/close) over 3 separate tools
- [Phase 03]: set_volume (tier 1, pycaw COM) and media_control (tier 0, ctypes SendInput) as separate tools
- [Phase 04]: MemoryStore embeds facts as 'key: value' for better semantic matching; superseded_by=-1 is manual-forget sentinel
- [Phase 04]: Memory wiring: _build_messages scopes recent turns to session_id; async extraction via run_in_executor; CLI ask_ollama also uses DB
- [Phase 04]: Memory tools use module-level injection (set_memory_store) matching shell.py pattern; remember stores as profile/user source
- [Phase 05]: Component uses typing.Protocol (structural typing) not ABC; _ComponentBase for DRY
- [Phase 05]: Plain open() for stdout/stderr redirect in jarvis.pyw (not RotatingFileHandler)
- [Phase 05]: Stage-level try/except in _turn_pipeline for degradation; registry iterator for component lookup by name
- [Phase 06]: TimingLog shares jarvis.db with AuditLog; single turn_id for both timing and audit
- [Phase 06]: Barge-in fires abort_controller.abort() for full turn cancellation; ABORT_KEYWORDS frozenset for O(1) lookup; fast-ack only on first brain iteration
- [Phase 06]: Sentence splitting uses split-then-merge approach to avoid Python re variable-width lookbehind limitation
- [Phase 07]: JSON config at %LOCALAPPDATA%\Jarvis\file_access.json re-read on every call for hot-reload (D-03); quarantine flag is module-level bool reset per turn (D-11)
- [Phase 07]: UTF-8 default with latin-1 fallback for read_file; search_files depth-limited to 3 levels, max 50 results

### Pending Todos

None yet.

### Blockers/Concerns

- **macOS TCC permission behavior is empirically unverified** — no MCP doc provider was available during v2.0 research; permission-dialog behavior for headless/LaunchAgent-started processes should be verified early in Phase 11 via `tccutil reset` testing, not assumed from web sources. Screen Recording also requires monthly re-authorization on modern macOS.
- **Scheduler library choice is contested** — STACK.md recommends APScheduler, ARCHITECTURE.md recommends a plain stdlib `threading.Event().wait()` polling loop matching the existing `ContinuousVision` pattern. Resolve explicitly during Phase 14 planning; architecture doc's reasoning is more consistent with the project's minimal-dependencies philosophy.
- **`pyautogui` vs `pynput`+`mss` for computer-use is unresolved** — STACK.md rejects `pyautogui` outright (brittle, coordinate-based); ARCHITECTURE.md suggests spiking it first since it's already cross-platform and might remove the need for platform branching in `tools/computer_use.py`. Spike in Phase 13 before committing to an implementation.
- **Message-shape normalization for Claude tool_use/tool_result is the largest single plumbing task in Phase 12** — Ollama's tool_calls array, OpenAI's shape, and Claude's content-block shape are structurally incompatible; budget a dedicated plan for `messages_for_provider()`, not a subtask of adding `_ask_claude`.
- **Hybrid routing must not silently default to "always Claude"** — cost blowup risk, especially since `JARVIS_ALWAYS_SEE` auto-attaches a webcam frame to every text prompt. Phase 12 needs an explicit conservative routing rule plus a visible cost counter as an acceptance criterion, not later hardening.
- **Outlook presence on target machine** — carried from v1.0 Phase 9; user now primarily runs macOS, so Phase 11's EventKit/AppleScript calendar path is likely the higher-traffic path going forward.
- **Small-model tool-calling reliability is empirical** — don't bake a specific brain model into plans; measure and pick.

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Computer Use | CUSE-06: Full generalized "operate any app" vision coverage | Deferred to v2 requirements | v2.0 requirements definition |
| Proactive Assistant | PROA-06: Personalized/adaptive notification cadence | Deferred to v2 requirements | v2.0 requirements definition |
| Proactive Assistant | PROA-07: Multi-signal busy detection (meetings, focus modes) | Deferred to v2 requirements | v2.0 requirements definition |

## Session Continuity

Last session: 2026-07-05T05:12:33.819Z
Stopped at: ROADMAP.md created for v2.0 (Phases 11-14), REQUIREMENTS.md traceability updated, STATE.md position advanced to Phase 11
Resume file: None
