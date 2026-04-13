# Requirements: Jarvis

**Defined:** 2026-04-10
**Core Value:** Jarvis takes real actions for its user, by voice, and stays useful with no internet connection.

## v1 Requirements

Requirements for reaching daily-driver status. Each maps to a roadmap phase.

### Voice Loop (VOICE)

- [ ] **VOICE-01**: Jarvis activates on the wake word "Jarvis" without any key press, using a local wake-word engine (openWakeWord `hey_jarvis_v0.1`) that runs continuously on the mic.
- [ ] **VOICE-02**: After wake, recording is bounded by local voice-activity detection (silero-vad ONNX) — recording stops when the user stops speaking, not on a fixed timer.
- [ ] **VOICE-03**: Two-stage wake gating rejects false triggers — after the wake-word engine fires, a short whisper pass + regex check confirms the first word is actually "Jarvis" before the full pipeline engages.
- [ ] **VOICE-04**: Jarvis does not trigger on its own voice — wake detections are suppressed while TTS is playing, and the mic auto-mutes when another app holds an exclusive audio session.
- [ ] **VOICE-05**: Jarvis speaks in a high-quality local voice (Kokoro `bm_george`/`bm_daniel`) that runs fully offline; Piper is installed as a tested fallback and as the fast-acknowledgment voice.
- [ ] **VOICE-06**: The startup sequence verifies `espeak-ng` is on PATH and fails loudly (not silently) if Kokoro's dependency is missing.
- [ ] **VOICE-07**: Jarvis can be interrupted mid-sentence while speaking (barge-in) — starting a new wake-word activation aborts the current TTS playback cleanly.
- [ ] **VOICE-08**: System-prompt persona is "polished, calm desktop butler with dry wit" — terse by default, never impersonates a real person or character.

### Brain & Tool-Use Framework (BRAIN)

- [x] **BRAIN-01**: All LLM dispatch goes through a single `Brain.ask(messages, tools) -> BrainResponse` helper — no more provider-branched call sites. Ollama and OpenAI are two private functions behind one public API.
- [x] **BRAIN-02**: Every Ollama `/api/chat` request explicitly pins `options.num_ctx` (default 16384) so tool schemas are never silently truncated out of the prompt.
- [x] **BRAIN-03**: Token usage is counted per turn and logged; a warning fires at 80% of the active `num_ctx` budget.
- [x] **BRAIN-04**: Tools are registered with a `@tool` decorator and auto-discovered from the `jarvis.tools` package via `pkgutil.iter_modules` — adding a tool is dropping a file.
- [x] **BRAIN-05**: Tool JSON schemas are generated from Python type hints + docstrings — no hand-written JSON schema blocks.
- [x] **BRAIN-06**: A per-turn tool-call loop cap (N=8) with duplicate-call detection prevents runaway agent loops.
- [x] **BRAIN-07**: A model A/B eval harness (`jarvis_cli.py test_tools`) runs the same tool-use scenarios across gemma4, qwen3:4b, qwen3:14b so the brain model is chosen by measurement, not speculation.
- [x] **BRAIN-08**: OpenAI path is migrated from the Responses API to Chat Completions, matching the uniform message-list shape; `previous_response_id` is retired.

### Actions — PC Control (ACT-PC)

- [x] **ACT-PC-01**: Jarvis can launch applications by name ("open Spotify", "launch VS Code") via `subprocess` + Start-Menu shortcut lookup.
- [x] **ACT-PC-02**: Jarvis can focus, minimize, and close application windows using pywinauto + pywin32 (with `AttachThreadInput` workaround for focus steal).
- [x] **ACT-PC-03**: Jarvis can control system volume and media keys (play/pause/next/previous/volume up/down/mute).
- [x] **ACT-PC-04**: Jarvis can read and write the system clipboard.
- [x] **ACT-PC-05**: Jarvis can capture the current screen (full screen or focused window) as an image and feed it into a vision-as-tool call.
- [x] **ACT-PC-06**: Jarvis can run arbitrary shell commands via `subprocess.Popen` with `CREATE_NO_WINDOW`, 30-second default timeout, 4 KB output cap, and a cancellable Popen registry tied to the abort rail.

### Actions — Files & Documents (ACT-FILE)

- [ ] **ACT-FILE-01**: Jarvis can read text and markdown files from allow-listed directories (home, Desktop, Downloads, Documents, explicit project dirs).
- [ ] **ACT-FILE-02**: Jarvis can read and summarize PDFs via pymupdf4llm.
- [ ] **ACT-FILE-03**: Jarvis can write and modify files in allow-listed directories (Tier 2 — path-checked).
- [ ] **ACT-FILE-04**: `delete_file` routes through `send2trash` so deletions land in the Recycle Bin, not permanent removal.
- [ ] **ACT-FILE-05**: Jarvis can search files by filename and glob within allow-listed directories.
- [ ] **ACT-FILE-06**: File-path arguments are validated against an allow/denylist (denylist includes Windows system dirs, `.venv`, `.git`, `*.env`, credential stores).

### Actions — Web & Knowledge (ACT-WEB)

- [ ] **ACT-WEB-01**: Jarvis can perform web searches via a self-hosted SearXNG instance running in Docker (no paid API, no telemetry).
- [ ] **ACT-WEB-02**: Jarvis can fetch and extract the main content of a web page via `trafilatura`, limited to URLs returned by the current-turn search results (prompt-injection guard).
- [ ] **ACT-WEB-03**: Jarvis gracefully degrades when Docker/SearXNG is down — the tool reports unavailable and the assistant responds without hallucinating a search result.

### Actions — Personal Data (ACT-PERSONAL)

- [ ] **ACT-PERSONAL-01**: Jarvis can list recent inbox messages via Outlook COM (`pywin32.win32com.client`).
- [ ] **ACT-PERSONAL-02**: Jarvis can read a specific email by ID.
- [ ] **ACT-PERSONAL-03**: Jarvis can *draft* an email — the draft is saved to the Drafts folder, never sent directly.
- [ ] **ACT-PERSONAL-04**: Sending a drafted email is a separate tool (`send_draft(draft_id)`) requiring a separate user turn — deliberate speed bump on irreversible communication.
- [ ] **ACT-PERSONAL-05**: Jarvis can list upcoming calendar events via Outlook COM.
- [ ] **ACT-PERSONAL-06**: Jarvis can create a calendar event (parsed natural-language date via `dateparser`).
- [ ] **ACT-PERSONAL-07**: Outlook COM workers call `pythoncom.CoInitialize()` correctly per thread; component degrades cleanly if Outlook isn't installed.

### Actions — Communication (ACT-COMM)

- [ ] **ACT-COMM-01**: Jarvis can post a message to one external chat surface (Discord OR Slack — user picks during phase planning) via webhook.

### Persistent Memory (MEMORY)

- [ ] **MEMORY-01**: Conversation turns and extracted facts are stored in a local SQLite database at `%LOCALAPPDATA%\Jarvis\memory.db` with `PRAGMA journal_mode=WAL`.
- [ ] **MEMORY-02**: Embeddings are generated locally via `sentence-transformers/all-MiniLM-L6-v2` and stored in `sqlite-vec` virtual tables (`vec_turns`, `vec_facts`).
- [ ] **MEMORY-03**: Profile facts (identity, preferences) are loaded into the system prompt on every turn — Jarvis recognizes the user across sessions without needing to search.
- [ ] **MEMORY-04**: Semantic recall queries fetch the top-K=5 most relevant prior turns/facts for each user message and inject them as context; injection is hard-capped at 2 KB of tokens.
- [ ] **MEMORY-05**: Retrieved items include similarity scores; anything below 0.7 is tagged "uncertain" in the prompt so the model hedges.
- [ ] **MEMORY-06**: Facts are typed (`profile`, `preference`, `state`, `event`, `identity`) with per-type expiry (e.g. `state` facts expire after 90 days).
- [ ] **MEMORY-07**: Supersession detection — a new contradicting fact marks the old one `superseded_by`, so stale preferences don't linger.
- [ ] **MEMORY-08**: `remember`, `recall`, and `forget` are exposed as tools so Jarvis can explicitly persist and redact facts on request.
- [ ] **MEMORY-09**: PII (emails, phone numbers, credit cards) is redacted by regex *before* content is embedded.
- [ ] **MEMORY-10**: In-process `self.history` rolling window is retired; SQLite is the single source of conversation truth.

### Process & Reliability (PROC)

- [ ] **PROC-01**: Jarvis runs as a `pythonw.exe` background process (not a terminal REPL) with a `pystray` tray icon on the main thread.
- [ ] **PROC-02**: Tray menu shows listening/muted state and a Quit item; tooltip shows component health (green/yellow/red).
- [ ] **PROC-03**: The first lines of `jarvis.pyw` redirect `sys.stdout` and `sys.stderr` to `%LOCALAPPDATA%\Jarvis\logs\*.log` **before any import**, so pythonw crashes are never silent.
- [ ] **PROC-04**: `faulthandler.enable()` catches C-extension segfaults; a global `sys.excepthook` posts a Windows toast on unhandled exceptions.
- [ ] **PROC-05**: Startup runs health checks for espeak-ng, Ollama + model tag, camera, mic, Outlook COM availability, and `%LOCALAPPDATA%` writability.
- [ ] **PROC-06**: A `Component` protocol unifies lifecycle (`try_init`, `check`, `status`, `last_error`) for every subsystem; try/except lives in exactly three places (component init/check, tool dispatcher, turn-pipeline top).
- [ ] **PROC-07**: Graceful degradation matrix — when any subsystem fails, the assistant continues with reduced capability rather than crashing.
- [ ] **PROC-08**: A watchdog / pystray heartbeat restarts the async worker thread if it dies.
- [ ] **PROC-09**: `install_autostart.ps1` creates a `shell:startup` shortcut to `pythonw.exe src\jarvis.pyw`.
- [x] **PROC-10**: A second entry point `jarvis_cli.py` preserves the current terminal REPL for development/debugging and shares the same assistant class.

### Safety & Abort (SAFE)

- [x] **SAFE-01**: Tools are classified into three tiers (0 = read-only, 1 = reversible writes, 2 = destructive/irreversible) and the tier is declared as a decorator argument, not an afterthought.
- [x] **SAFE-02**: Every tool call (all tiers) is written to a `tool_calls` audit log *before* execution.
- [ ] **SAFE-03**: Tier 2 tools write a dry-run preview to `actions.log` before acting.
- [ ] **SAFE-04**: Tier 2 tools are *blocked* during any conversation turn that has pulled in external content (email body, PDF contents, web page) — prevents prompt injection from triggering destructive actions on the same turn.
- [x] **SAFE-05**: A global hotkey (registered via `pynput.keyboard.GlobalHotKeys`) aborts the current turn — cancels the asyncio task, terminates all registered child Popens, and stops any TTS playback.
- [x] **SAFE-06**: A tool result payload sent back to the LLM is wrapped in `<untrusted_content source="...">...</untrusted_content>` markers so the model treats it as data, not instructions.
- [ ] **SAFE-07**: Outbound URLs for `fetch_page` are constrained to the SearXNG result set of the current turn — no freeform URL fetching.

### Performance (PERF)

- [ ] **PERF-01**: Every pipeline stage (wake → VAD → STT → brain → TTS) logs timing into a local SQLite table every turn.
- [ ] **PERF-02**: Target end-to-end latency for short replies is ≤1.5 s wake-to-first-audio, measured and committed in a dashboard.
- [ ] **PERF-03**: Piper acknowledgment voice speaks a short "Certainly." / "Right away." within 400 ms while Kokoro synthesizes the real reply, masking perceived latency.
- [ ] **PERF-04**: Kokoro synthesizes TTS sentence-by-sentence — sentence N+1 is generated while sentence N is still playing, with a short crossfade to mask the boundary.
- [ ] **PERF-05**: All heavy models (openWakeWord, silero-vad, whisper, Kokoro, sentence-transformer, Ollama keep-alive) are preloaded at startup — the first user interaction is not delayed by lazy initialization.
- [ ] **PERF-06**: Saying "stop" or "cancel" during a running action invokes the abort rail (SAFE-05), not just the TTS interrupt.

## v2 Requirements

Deferred — acknowledged, not in the current roadmap.

### Voice

- **VOICE-V2-01**: Custom wake-word training for reduced false-positive rate in the user's specific acoustic environment
- **VOICE-V2-02**: Acoustic echo cancellation so Jarvis can hear the user while it's still speaking (full AEC, not just suppression)
- **VOICE-V2-03**: Multi-language support

### Brain

- **BRAIN-V2-01**: Cloud fallback — automatic routing of hard requests to Claude or GPT when local model confidence is low
- **BRAIN-V2-02**: Streaming tool-call parsing for lower time-to-first-action

### Actions

- **ACT-V2-01**: Gmail + Google Calendar via OAuth (for non-Outlook users)
- **ACT-V2-02**: Web-form automation via Playwright
- **ACT-V2-03**: Teams messaging via MS Graph
- **ACT-V2-04**: Proactive notifications — Jarvis initiates conversations based on time/events

### Memory

- **MEMORY-V2-01**: Visual episodic memory — remembers things the camera has seen
- **MEMORY-V2-02**: Cross-device memory sync (opt-in, end-to-end encrypted)

## Out of Scope

Explicitly excluded. Do not reintroduce without a decision log entry.

| Feature | Reason |
|---------|--------|
| Cloud-dependent default path | Core value is "useful with no internet" — every must-have must work offline. Cloud stays an opt-in override. |
| Web/Electron/browser UI | PROJECT.md constraint — Jarvis is a native desktop process, period. |
| Cross-platform parity (macOS/Linux) at launch | Windows-primary explicitly. Mac/Linux are post-milestone. Don't build cross-platform shims speculatively. |
| Microservices / DI framework / plugin marketplace | PROJECT.md anti-goal — "over-engineering" is a named failure mode. |
| Image/video generation | Jarvis consumes vision; it does not generate it. |
| Voice impersonation of a real actor or character | Persona is "polished butler archetype," not anyone specific. Encoded in system prompt already. |
| Settings GUI / config app | Configuration stays in `.env` and code. |
| Multi-user authentication | Single user, single machine. No auth layer. |
| Confirm-before-every-action dialogs | User explicitly chose "trust by default" — safety lives in tiered blast-radius + abort rail, not confirms. |
| Windows Service mode | Session 0 isolation blocks audio and webcam. Tray process is the only viable shape. |
| Auto-updater | Out of scope for a single-user personal project. |
| Cloud sync of memory/logs | Privacy requirement — all data stays local. |
| Conversation branching / multiple chat threads | One conversation at a time; history is linear. |
| Real-time cloud transcription fallback | faster-whisper local is good enough; cloud STT adds dependency without benefit. |

## Traceability

Every v1 requirement is mapped to exactly one phase. Phases defined in `.planning/ROADMAP.md`.

| Requirement | Phase | Status |
|-------------|-------|--------|
| VOICE-01 | Phase 1 | Pending |
| VOICE-02 | Phase 1 | Pending |
| VOICE-03 | Phase 1 | Pending |
| VOICE-04 | Phase 1 | Pending |
| VOICE-05 | Phase 1 | Pending |
| VOICE-06 | Phase 1 | Pending |
| VOICE-07 | Phase 6 | Pending |
| VOICE-08 | Phase 1 | Pending |
| BRAIN-01 | Phase 2 | Complete |
| BRAIN-02 | Phase 2 | Complete |
| BRAIN-03 | Phase 2 | Complete |
| BRAIN-04 | Phase 2 | Complete |
| BRAIN-05 | Phase 2 | Complete |
| BRAIN-06 | Phase 2 | Complete |
| BRAIN-07 | Phase 2 | Complete |
| BRAIN-08 | Phase 2 | Complete |
| ACT-PC-01 | Phase 3 | Complete |
| ACT-PC-02 | Phase 3 | Complete |
| ACT-PC-03 | Phase 3 | Complete |
| ACT-PC-04 | Phase 3 | Complete |
| ACT-PC-05 | Phase 3 | Complete |
| ACT-PC-06 | Phase 3 | Complete |
| ACT-FILE-01 | Phase 7 | Pending |
| ACT-FILE-02 | Phase 7 | Pending |
| ACT-FILE-03 | Phase 7 | Pending |
| ACT-FILE-04 | Phase 7 | Pending |
| ACT-FILE-05 | Phase 7 | Pending |
| ACT-FILE-06 | Phase 7 | Pending |
| ACT-WEB-01 | Phase 8 | Pending |
| ACT-WEB-02 | Phase 8 | Pending |
| ACT-WEB-03 | Phase 8 | Pending |
| ACT-PERSONAL-01 | Phase 9 | Pending |
| ACT-PERSONAL-02 | Phase 9 | Pending |
| ACT-PERSONAL-03 | Phase 9 | Pending |
| ACT-PERSONAL-04 | Phase 9 | Pending |
| ACT-PERSONAL-05 | Phase 9 | Pending |
| ACT-PERSONAL-06 | Phase 9 | Pending |
| ACT-PERSONAL-07 | Phase 9 | Pending |
| ACT-COMM-01 | Phase 10 | Pending |
| MEMORY-01 | Phase 4 | Pending |
| MEMORY-02 | Phase 4 | Pending |
| MEMORY-03 | Phase 4 | Pending |
| MEMORY-04 | Phase 4 | Pending |
| MEMORY-05 | Phase 4 | Pending |
| MEMORY-06 | Phase 4 | Pending |
| MEMORY-07 | Phase 4 | Pending |
| MEMORY-08 | Phase 4 | Pending |
| MEMORY-09 | Phase 4 | Pending |
| MEMORY-10 | Phase 4 | Pending |
| PROC-01 | Phase 5 | Pending |
| PROC-02 | Phase 5 | Pending |
| PROC-03 | Phase 5 | Pending |
| PROC-04 | Phase 5 | Pending |
| PROC-05 | Phase 5 | Pending |
| PROC-06 | Phase 5 | Pending |
| PROC-07 | Phase 5 | Pending |
| PROC-08 | Phase 5 | Pending |
| PROC-09 | Phase 5 | Pending |
| PROC-10 | Phase 2 | Complete |
| SAFE-01 | Phase 2 | Complete |
| SAFE-02 | Phase 2 | Complete |
| SAFE-03 | Phase 7 | Pending |
| SAFE-04 | Phase 7 | Pending |
| SAFE-05 | Phase 2 | Complete |
| SAFE-06 | Phase 2 | Complete |
| SAFE-07 | Phase 8 | Pending |
| PERF-01 | Phase 6 | Pending |
| PERF-02 | Phase 6 | Pending |
| PERF-03 | Phase 6 | Pending |
| PERF-04 | Phase 6 | Pending |
| PERF-05 | Phase 6 | Pending |
| PERF-06 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 72 total
- Mapped to phases: 72 ✓
- Unmapped: 0

---
*Requirements defined: 2026-04-10*
*Last updated: 2026-04-10 — traceability populated by gsd-roadmapper*
