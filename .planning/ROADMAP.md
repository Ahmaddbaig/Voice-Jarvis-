# Roadmap: Jarvis

## Overview

Jarvis evolves from a ~400-line single-file Python prototype that "just chats" into a daily-driver Windows desktop agent that listens on a wake word, takes real actions by voice, remembers its user across sessions, and runs quietly in the background — all fully offline on the default path. Ten phases walk through the critical path the four researchers converged on: first the voice loop becomes hands-free and pleasant to hear, then the brain gets a tool-use framework with the abort rail built in on day one, then real actions start landing one category at a time (PC control, files, web, Outlook, chat), with persistent memory, background-process plumbing, and a dedicated latency pass threaded between them at the moments each becomes load-bearing. Every phase ends in a behavior the user can observe from the microphone — not a code milestone.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Voice Loop Upgrade** - Wake word, VAD-bounded recording, Kokoro TTS, async refactor — hands-free chatbot with a pleasant voice
- [ ] **Phase 2: Brain Refactor + Tool Framework + Abort Rail** - Unified `Brain.ask()`, `@tool` decorator, model A/B eval, audit log, abort hotkey shipping working
- [x] **Phase 3: PC Control Tools** - Launch apps, window management, media keys, clipboard, screenshot, shell execution with cancellable Popens (completed 2026-04-13)
- [ ] **Phase 4: Persistent Memory** - SQLite + sqlite-vec cross-session memory; profile facts in system prompt, semantic recall per turn
- [ ] **Phase 5: Background Process + Crash Plumbing + Graceful Degradation** - pythonw + pystray tray + autostart; stdout/stderr plumbing so crashes are never silent
- [ ] **Phase 6: Latency Pass + Barge-In + Voice Abort** - Per-stage timing, Piper fast-ack, sentence-streaming TTS, barge-in, "stop"/"cancel" as abort
- [ ] **Phase 7: Files & Documents** - Read/write/search files and PDFs with path allow-list, send2trash deletes, Tier 2 guards
- [ ] **Phase 8: Web Search & Page Fetch** - SearXNG in Docker + trafilatura with URL allow-list constrained to current-turn results
- [ ] **Phase 9: Outlook Email & Calendar** - Inbox read, draft-only send, calendar read/create via Outlook COM
- [ ] **Phase 10: Multi-Step Agent Loop + External Chat** - Compose prior tools into multi-step chains; post to one external chat webhook

## Phase Details

### Phase 1: Voice Loop Upgrade
**Goal**: Jarvis becomes a hands-free, pleasant-sounding chatbot — activates on the spoken word "Jarvis", stops recording when the user stops talking, and speaks replies in a high-quality local voice. Brain stays on the existing `gemma4:latest` — no tool-use refactor in this phase.
**Depends on**: Nothing (first phase)
**Requirements**: VOICE-01, VOICE-02, VOICE-03, VOICE-04, VOICE-05, VOICE-06, VOICE-08
**Success Criteria** (what must be TRUE):
  1. User says "Jarvis, what time is it" from across the room without touching the keyboard and hears a spoken answer in a natural British-butler voice — no `m` key, no terminal focus.
  2. User speaks a question that naturally trails off with "um…" and Jarvis waits for the real sentence to finish before transcribing, instead of cutting off on a five-second timer.
  3. Playing a Marvel podcast that says "Jarvis" in the background does not trigger a false recording session — the two-stage gate rejects it silently.
  4. Jarvis speaking its own name in a TTS reply does not re-trigger its own wake word.
  5. With no `espeak-ng` installed, startup fails with a loud, specific error message pointing at the missing dependency — not a silent crash, not a vague traceback.
**Plans**: 5 plans
- [ ] 01-PLAN-environment-and-assets-01.md — Wave 0: install Phase 1 pip deps, download model assets, verify espeak-ng, create %LOCALAPPDATA%\Jarvis\logs\, extend .env.example
- [ ] 01-PLAN-config-and-preloader-02.md — Wave 1: src/config.py (frozen Config dataclass) + src/preload.py (espeak-ng probe for VOICE-06 + preload_all)
- [ ] 01-PLAN-audio-input-pipeline-03.md — Wave 2: src/audio_in.py (WakeWordStream + VadRecorder + TwoStageGate) + src/wake_log.py — VOICE-01, VOICE-02, VOICE-03
- [ ] 01-PLAN-audio-output-pipeline-04.md — Wave 2: src/audio_out.py (PiperAck + Kokoro/Piper/SAPI FallbackTTS chain) — VOICE-05
- [ ] 01-PLAN-orchestration-and-entry-points-05.md — Wave 3: rewrite src/jarvis.py (asyncio + tts_playing flag for VOICE-04 + pynput hotkey + SYSTEM_PROMPT for VOICE-08), extract src/jarvis_cli.py (preserved REPL)

### Phase 2: Brain Refactor + Tool Framework + Abort Rail
**Goal**: The provider-branched call sites collapse into a single `Brain.ask(messages, tools) -> BrainResponse` helper with tool-calling support. A decorator-based tool registry, an A/B eval harness across candidate brain models, the prompt-injection quarantine, the audit log, and a working global-hotkey abort rail all ship together — because the abort rail is infrastructure, not polish, and the first tool cannot ship without it. The `jarvis/` package split happens here, and nowhere earlier.
**Depends on**: Phase 1
**Requirements**: BRAIN-01, BRAIN-02, BRAIN-03, BRAIN-04, BRAIN-05, BRAIN-06, BRAIN-07, BRAIN-08, SAFE-01, SAFE-02, SAFE-05, SAFE-06, PROC-10
**Success Criteria** (what must be TRUE):
  1. User runs `jarvis_cli.py test_tools` and sees a comparison table with tool-call success rates for gemma4, qwen3:4b, and qwen3:14b against the same scenario set — the brain model is chosen by that table, not by the roadmap.
  2. User asks Jarvis a hypothetical "what would happen if" question that the model tries to answer with a tool call; the per-turn call cap stops it at 8 and Jarvis gives a plain text reply instead of looping forever.
  3. During any tool call, user presses the configured global hotkey and the running turn stops — the asyncio task is cancelled, any child process is terminated, and TTS is silent within a second — whether Jarvis is listening, thinking, or speaking.
  4. Every tool invocation (including a trivial `get_time` read) leaves a row in `%LOCALAPPDATA%\Jarvis\tool_calls` audit before the tool body runs, even when the turn later aborts.
  5. Both `jarvis.pyw` (not yet present) and `jarvis_cli.py` REPL entry points share the same `JarvisAssistant` class — switching between them requires no code change.
**Plans**: 4 plans
- [x] 02-01-package-split-PLAN.md — Wave 1: restructure src/ into src/jarvis/ package (core/audio/tools), thin launchers, zero new features
- [x] 02-02-brain-tool-registry-PLAN.md — Wave 2: Brain.ask() + BrainResponse + @tool decorator + pkgutil discovery + CloudTTS streaming
- [x] 02-03-tools-audit-abort-PLAN.md — Wave 3: 4 starter tools + audit log + tool-call loop cap + untrusted markers + abort rail
- [x] 02-04-eval-harness-PLAN.md — Wave 4: A/B eval harness (jarvis_cli.py test_tools) across OpenAI + Ollama models

### Phase 3: PC Control Tools
**Goal**: Jarvis can actually do something on the user's machine — launch and focus apps, control volume and media keys, read/write the clipboard, take a screenshot and reason about it, and run a shell command it can cancel. This is the first phase where Jarvis is materially more useful than the prototype, and it lands on top of the Phase 2 registry with no new framework code.
**Depends on**: Phase 2
**Requirements**: ACT-PC-01, ACT-PC-02, ACT-PC-03, ACT-PC-04, ACT-PC-05, ACT-PC-06
**Success Criteria** (what must be TRUE):
  1. User says "Jarvis, open Spotify and turn the volume down to thirty" and Spotify launches, focuses, and system volume lands at 30% — in one spoken turn.
  2. User says "Jarvis, what's on my screen right now" and Jarvis takes a screenshot, passes it through the vision-as-tool path, and describes the visible window in natural language.
  3. User says "Jarvis, run `git status` in the current repo" and Jarvis returns the (capped) output spoken as a summary; the command inherits the 30-second timeout and runs without flashing a terminal window.
  4. User starts a long-running command by voice, then says "stop" (or presses the abort hotkey) and the child process terminates immediately — the Popen registry handles the kill.
  5. User says "Jarvis, copy this to the clipboard: <phrase>" and the clipboard contents on the next Ctrl-V are exactly that phrase.
**Plans**: 3 plans
Plans:
- [x] 03-01-PLAN.md — Wave 1: pip deps (pycaw, mss, pywin32) + image-result handling in _turn_pipeline + call_tool 4KB bypass
- [x] 03-02-PLAN.md — Wave 2: app_launch.py + window.py + volume.py (ACT-PC-01, 02, 03)
- [x] 03-03-PLAN.md — Wave 2: screenshot.py + set_clipboard (ACT-PC-04, 05)

### Phase 4: Persistent Memory
**Goal**: Jarvis recognizes the user across restarts. Profile facts (name, preferences, identity) are injected into every system prompt. Conversation turns and extracted facts live in a local SQLite + sqlite-vec store at `%LOCALAPPDATA%\Jarvis\memory.db`, and semantic recall brings back the top-K most relevant prior turns for each new user message. The in-process rolling history is retired; SQLite becomes the single source of conversation truth. Both providers go stateless — `previous_response_id` is retired.
**Depends on**: Phase 3
**Requirements**: MEMORY-01, MEMORY-02, MEMORY-03, MEMORY-04, MEMORY-05, MEMORY-06, MEMORY-07, MEMORY-08, MEMORY-09, MEMORY-10
**Success Criteria** (what must be TRUE):
  1. User introduces themselves to Jarvis once ("my name is Alex, I prefer short replies"), quits the process, relaunches the next day, says "Jarvis, who am I" and hears "You're Alex" — without asking Jarvis to recall anything explicitly.
  2. User references a topic from a conversation two weeks ago ("what did we decide about the weekend trip"); Jarvis semantically recalls the relevant prior turn and answers in context, not from scratch.
  3. User says "Jarvis, forget that I prefer short replies"; the forget tool marks the fact superseded and subsequent turns no longer inject that preference.
  4. When the user tells Jarvis a contradicting preference ("actually, give me long explanations"), the old preference is automatically marked `superseded_by` and stops appearing in retrieval.
  5. A message the user speaks containing a credit-card number is stored with the PII redacted before embedding — the raw number is not searchable in `vec_turns`.
**Plans**: 3 plans
Plans:
- [x] 03-01-PLAN.md — Wave 1: pip deps (pycaw, mss, pywin32) + image-result handling in _turn_pipeline + call_tool 4KB bypass
- [x] 03-02-PLAN.md — Wave 2: app_launch.py + window.py + volume.py (ACT-PC-01, 02, 03)
- [x] 03-03-PLAN.md — Wave 2: screenshot.py + set_clipboard (ACT-PC-04, 05)

### Phase 5: Background Process + Crash Plumbing + Graceful Degradation
**Goal**: Jarvis stops being a terminal program and becomes a tray-icon background process launched via `pythonw.exe` at login. Crash plumbing (stdout/stderr redirect, faulthandler, excepthook + toast, watchdog) lands the same day `jarvis.pyw` ships so silent pythonw crashes never happen. A `Component` protocol unifies subsystem lifecycles, the startup health check runs, and the graceful-degradation matrix lets Jarvis keep running with any single subsystem down.
**Depends on**: Phase 4
**Requirements**: PROC-01, PROC-02, PROC-03, PROC-04, PROC-05, PROC-06, PROC-07, PROC-08, PROC-09
**Success Criteria** (what must be TRUE):
  1. User runs `install_autostart.ps1`, reboots, and Jarvis is already listening from a tray icon without opening a terminal — the tray tooltip shows a green/yellow/red component-health dot.
  2. User unplugs the webcam mid-conversation; Jarvis reports the camera as degraded in the tray tooltip but continues answering non-vision questions instead of crashing the loop.
  3. User deliberately stops the Ollama service; Jarvis detects it on the next turn, speaks a graceful "brain unavailable" message, and recovers automatically when Ollama comes back — no restart required.
  4. A forced C-extension segfault (e.g. bad ONNX input) results in a Windows toast notification and a readable traceback in `%LOCALAPPDATA%\Jarvis\logs\jarvis.log` — not a vanished process.
  5. From the tray menu, user clicks Quit and the process exits cleanly, releasing the mic and closing the DB.
**Plans**: 3 plans
Plans:
- [x] 03-01-PLAN.md — Wave 1: pip deps (pycaw, mss, pywin32) + image-result handling in _turn_pipeline + call_tool 4KB bypass
- [ ] 03-02-PLAN.md — Wave 2: app_launch.py + window.py + volume.py (ACT-PC-01, 02, 03)
- [ ] 03-03-PLAN.md — Wave 2: screenshot.py + set_clipboard (ACT-PC-04, 05)

### Phase 6: Latency Pass + Barge-In + Voice Abort
**Goal**: The pipeline is now functionally complete end-to-end, so this phase is a dedicated tuning + UX wave. Every stage (wake → VAD → STT → brain → TTS) logs timing to SQLite every turn. Piper speaks a sub-400ms "Certainly" fast-ack while Kokoro is still synthesizing the real reply. Kokoro synthesizes sentence-by-sentence with a crossfade so the second sentence starts while the first is still playing. Barge-in works mid-speech. Saying "stop" or "cancel" during a tool call invokes the full abort rail, not just TTS.
**Depends on**: Phase 5
**Requirements**: VOICE-07, PERF-01, PERF-02, PERF-03, PERF-04, PERF-05, PERF-06
**Success Criteria** (what must be TRUE):
  1. For short replies ("what time is it", "set volume to 50"), the measured wake-to-first-audio latency is ≤1.5 seconds, committed as a row in the timing table the user can query.
  2. User interrupts Jarvis mid-sentence by starting a new wake-word activation; the current TTS playback stops cleanly within ~200 ms and the new turn begins — no audio garbage, no dropped frames.
  3. During a multi-second tool call (e.g. a shell command), user says "stop" by voice; the running action is cancelled through the same abort path as the hotkey, not just silenced.
  4. On first interaction after startup, there is no perceptible "warming up" pause — all heavy models (openWakeWord, silero-vad, whisper, Kokoro, sentence-transformer, Ollama keep-alive) are already resident.
  5. For any reply longer than one sentence, sentence N+1 starts playing immediately after sentence N without an audible gap at the boundary.
**Plans**: 3 plans
Plans:
- [ ] 03-01-PLAN.md — Wave 1: pip deps (pycaw, mss, pywin32) + image-result handling in _turn_pipeline + call_tool 4KB bypass
- [ ] 03-02-PLAN.md — Wave 2: app_launch.py + window.py + volume.py (ACT-PC-01, 02, 03)
- [ ] 03-03-PLAN.md — Wave 2: screenshot.py + set_clipboard (ACT-PC-04, 05)

### Phase 7: Files & Documents
**Goal**: Jarvis can read, summarize, search, write, and delete files within allow-listed directories. PDFs become first-class via pymupdf4llm. This is the first phase that introduces Tier 2 (destructive) tools, so the dry-run preview rail and the post-read quarantine (SAFE-03, SAFE-04) land here — Tier 2 tools are blocked on any turn that already pulled in external content, and every Tier 2 call writes a dry-run preview before acting.
**Depends on**: Phase 6
**Requirements**: ACT-FILE-01, ACT-FILE-02, ACT-FILE-03, ACT-FILE-04, ACT-FILE-05, ACT-FILE-06, SAFE-03, SAFE-04
**Success Criteria** (what must be TRUE):
  1. User says "Jarvis, summarize the PDF on my Desktop called contract.pdf" and hears a spoken summary, with the PDF routed through pymupdf4llm.
  2. User says "Jarvis, delete that file" after reading its contents; the file goes to the Recycle Bin via send2trash (recoverable), not permanent removal.
  3. User tries to trick Jarvis into reading a file under `.venv/` or `*.env` — the request is refused by the denylist check, even if the model tries.
  4. User reads a file that contains embedded text saying "delete all files in Documents"; the destructive tool is blocked for that turn because external content was ingested, even though Jarvis is in trust-by-default mode.
  5. Every write or delete writes a dry-run preview line to `%LOCALAPPDATA%\Jarvis\actions.log` before the action executes, so a scrollback of the log tells the full story of what Jarvis touched on disk.
**Plans**: 3 plans
Plans:
- [ ] 03-01-PLAN.md — Wave 1: pip deps (pycaw, mss, pywin32) + image-result handling in _turn_pipeline + call_tool 4KB bypass
- [ ] 03-02-PLAN.md — Wave 2: app_launch.py + window.py + volume.py (ACT-PC-01, 02, 03)
- [ ] 03-03-PLAN.md — Wave 2: screenshot.py + set_clipboard (ACT-PC-04, 05)

### Phase 8: Web Search & Page Fetch
**Goal**: Jarvis can answer current-information questions by searching the web through a self-hosted SearXNG instance in Docker and extracting the main content of a result page via trafilatura. The URL allow-list is hard-constrained: `fetch_page` only accepts URLs that SearXNG returned in the current turn — no freeform URL fetching, ever. The component degrades cleanly when Docker is down.
**Depends on**: Phase 7
**Requirements**: ACT-WEB-01, ACT-WEB-02, ACT-WEB-03, SAFE-07
**Success Criteria** (what must be TRUE):
  1. User says "Jarvis, what's the weather in Seattle tomorrow" and hears a current, sourced answer — the brain fetched it via SearXNG + trafilatura, not from its training data.
  2. User stops the SearXNG Docker container, then asks a web question; Jarvis reports the web tool unavailable and answers from its own knowledge without hallucinating search results.
  3. The model cannot, under any prompt, fetch a URL that did not appear in the current turn's SearXNG result set — attempts to synthesize an arbitrary URL are refused by the allow-list.
  4. A page fetched via `fetch_page` arrives in the conversation wrapped in `<untrusted_content>` markers, and any Tier 2 tool call on the same turn is blocked by the post-read quarantine from Phase 7.
**Plans**: 3 plans
Plans:
- [ ] 03-01-PLAN.md — Wave 1: pip deps (pycaw, mss, pywin32) + image-result handling in _turn_pipeline + call_tool 4KB bypass
- [ ] 03-02-PLAN.md — Wave 2: app_launch.py + window.py + volume.py (ACT-PC-01, 02, 03)
- [ ] 03-03-PLAN.md — Wave 2: screenshot.py + set_clipboard (ACT-PC-04, 05)

### Phase 9: Outlook Email & Calendar
**Goal**: Jarvis talks to the user's Outlook inbox and calendar via COM. It can list the inbox, read a specific email, draft an email (saved to Drafts, never sent directly), send a drafted email as a separate tool requiring a separate user turn (the speed bump), list upcoming calendar events, and create a new event from natural-language date phrases. If Outlook isn't installed, the component degrades cleanly instead of crashing.
**Depends on**: Phase 8
**Requirements**: ACT-PERSONAL-01, ACT-PERSONAL-02, ACT-PERSONAL-03, ACT-PERSONAL-04, ACT-PERSONAL-05, ACT-PERSONAL-06, ACT-PERSONAL-07
**Success Criteria** (what must be TRUE):
  1. User says "Jarvis, read me my last three emails" and hears a summary of the three most recent inbox items — fetched live via Outlook COM.
  2. User says "Jarvis, draft an email to Sam saying I'll be late"; the email appears in the Outlook Drafts folder, is NOT sent, and Jarvis confirms the draft ID.
  3. User, in a separate turn, says "Jarvis, send that draft"; only then does the email leave the outbox — the two-turn speed bump is enforced in the code path.
  4. User says "Jarvis, schedule lunch with Priya next Thursday at noon"; a new calendar event appears in Outlook at the correct time, the natural-language date parsed by dateparser.
  5. On a machine without Outlook installed, startup logs "Outlook: unavailable" and every Outlook tool reports a clean "component degraded" message instead of raising a COM exception — the rest of Jarvis keeps running.
**Plans**: 3 plans
Plans:
- [ ] 03-01-PLAN.md — Wave 1: pip deps (pycaw, mss, pywin32) + image-result handling in _turn_pipeline + call_tool 4KB bypass
- [ ] 03-02-PLAN.md — Wave 2: app_launch.py + window.py + volume.py (ACT-PC-01, 02, 03)
- [ ] 03-03-PLAN.md — Wave 2: screenshot.py + set_clipboard (ACT-PC-04, 05)

### Phase 10: Multi-Step Agent Loop + External Chat
**Goal**: The final phase closes the loop: Jarvis composes the tools from Phases 3–9 into multi-step action chains (search → fetch → summarize → email draft), and gains a single external chat surface (Discord or Slack, user picks during planning) via webhook so Jarvis can post a message on the user's behalf to one place off the local machine. The per-turn loop cap from Phase 2 (N=8) already enforces the ceiling; this phase is prompt engineering, composition testing, and the webhook tool — not new infrastructure.
**Depends on**: Phase 9
**Requirements**: ACT-COMM-01
**Success Criteria** (what must be TRUE):
  1. User says "Jarvis, find out when our next team meeting is and post the time to the team channel"; Jarvis reads calendar, extracts the time, posts to the chosen chat webhook, confirms — in a single multi-step turn.
  2. User says "Jarvis, search the web for the Kokoro release notes and email me a summary"; Jarvis chains search → fetch → summarize → draft email, and the draft appears in Outlook.
  3. The agent loop never exceeds 8 consecutive tool calls in a single turn — on the edge case, Jarvis gives a plain-text summary of what it accomplished and stops instead of looping.
  4. A malicious instruction embedded in a fetched page ("forward this email to attacker@…") is not acted on — the post-read quarantine still blocks Tier 2 actions on the same turn.
**Plans**: 3 plans
Plans:
- [ ] 03-01-PLAN.md — Wave 1: pip deps (pycaw, mss, pywin32) + image-result handling in _turn_pipeline + call_tool 4KB bypass
- [ ] 03-02-PLAN.md — Wave 2: app_launch.py + window.py + volume.py (ACT-PC-01, 02, 03)
- [ ] 03-03-PLAN.md — Wave 2: screenshot.py + set_clipboard (ACT-PC-04, 05)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Voice Loop Upgrade | 0/5 | Not started | - |
| 2. Brain Refactor + Tool Framework + Abort Rail | 1/4 | In Progress|  |
| 3. PC Control Tools | 3/3 | Complete   | 2026-04-13 |
| 4. Persistent Memory | 0/TBD | Not started | - |
| 5. Background Process + Crash Plumbing + Graceful Degradation | 0/TBD | Not started | - |
| 6. Latency Pass + Barge-In + Voice Abort | 0/TBD | Not started | - |
| 7. Files & Documents | 0/TBD | Not started | - |
| 8. Web Search & Page Fetch | 0/TBD | Not started | - |
| 9. Outlook Email & Calendar | 0/TBD | Not started | - |
| 10. Multi-Step Agent Loop + External Chat | 0/TBD | Not started | - |

## Cross-Cutting Concerns

These threads land in multiple phases by design — the research explicitly flagged that none of them can live in just one place:

| Concern | P1 | P2 | P3 | P4 | P5 | P6 | P7 | P8 | P9 | P10 |
|---|---|---|---|---|---|---|---|---|---|---|
| `num_ctx` pinning | — | **Pinned in payload builder** | Schemas grow | Memory stays in budget | Startup verify | Timing log | Schemas-last | +web schemas | +outlook schemas | Final schema budget check |
| Abort rail | `sd.OutputStream` skeleton | **Landed working** (hotkey + Popen registry) | Tools honor cancellation | Memory writes honor it | Tray shows abort state | **Voice-interrupt = abort** | Tier 2 dry-run before Popen | Web fetches cancellable | COM calls cancellable | Multi-step loop cancellable |
| `pythonw` crash plumbing | — | — | — | — | **Landed** (redirects + faulthandler + excepthook + watchdog) | — | — | — | — | — |
| `%LOCALAPPDATA%\Jarvis` path discipline | Logs go here | Audit log DB here | — | **memory.db here** | Startup verification | Timing DB here | actions.log here | — | — | — |
| Model A/B eval harness | — | **Landed** (`test_tools`) | Re-run after PC tools | Re-run after memory | — | Timing joins it | Re-run per category | Re-run per category | Re-run per category | Final composition run |
| Preload all models at startup | Phase 1 models | +Qwen 3 candidates | — | +sentence-transformer | Health check validates | **Preload finalized (PERF-05)** | — | — | — | — |
| Component health / graceful degradation | Audio / Kokoro / camera | +Ollama | +PC subsystems | +Memory | **Full matrix** | Latency-degraded as a state | +Files | +SearXNG down | +Outlook absent | — |
| Persona + system prompt hardening | **Landed** | +tool-use format | — | +memory injection | — | +observe-reason format | — | — | — | +multi-step agent format |

## Key Architectural Rules (Inherited from Research)

- **Single-file through Phase 1.** The `jarvis/` package split happens in Phase 2 when the tool registry lands — not earlier.
- **Brain model is chosen by measurement, not the roadmap.** Phase 2 ships `jarvis_cli.py test_tools` across gemma4, qwen3:4b, qwen3:14b. The winner is picked by that harness output during planning, not here.
- **No `providers/` subpackage, no DI framework, no plugin system.** Two LLM providers collapse into `Brain.ask()` with two private functions.
- **Try/except lives in exactly three places:** `Component.try_init/check`, `call_tool`, top of `turn_pipeline`.
- **Abort rail is infrastructure, not polish.** It ships working the same day as the first Tier 1 tool (Phase 2), not at the end.
- **`%LOCALAPPDATA%\Jarvis`, never `%USERPROFILE%`.** OneDrive redirect hazard is real.

## Traceability Summary

All 72 v1 requirements are mapped to exactly one phase. Full per-requirement traceability lives in REQUIREMENTS.md.

| Phase | Requirement Count | Requirement IDs |
|-------|-------------------|-----------------|
| 1 | 7 | VOICE-01, VOICE-02, VOICE-03, VOICE-04, VOICE-05, VOICE-06, VOICE-08 |
| 2 | 13 | BRAIN-01..08, SAFE-01, SAFE-02, SAFE-05, SAFE-06, PROC-10 |
| 3 | 6 | ACT-PC-01..06 |
| 4 | 10 | MEMORY-01..10 |
| 5 | 9 | PROC-01..09 |
| 6 | 7 | VOICE-07, PERF-01..06 |
| 7 | 8 | ACT-FILE-01..06, SAFE-03, SAFE-04 |
| 8 | 4 | ACT-WEB-01, ACT-WEB-02, ACT-WEB-03, SAFE-07 |
| 9 | 7 | ACT-PERSONAL-01..07 |
| 10 | 1 | ACT-COMM-01 |
| **Total** | **72** | |

---
*Roadmap created: 2026-04-10 by gsd-roadmapper*
*Granularity: fine (10 phases)*
*Coverage: 72/72 v1 requirements mapped, no orphans*
