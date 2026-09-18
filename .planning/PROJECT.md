# Jarvis

## What This Is

A local, action-capable desktop AI assistant for Windows 11 and macOS. Jarvis listens on a wake word, sees through the webcam, remembers its user across sessions, and *does things* — controlling the PC, searching the web, reading personal files, and communicating on the user's behalf — with a polished, genuinely pleasant voice. It is not a chatbot. It is a daily driver.

## Core Value

**Jarvis takes real actions for its user, by voice, and stays useful with no internet connection.** Every trade-off resolves in favor of "can it actually *do* the thing you asked, right now, offline, without nagging you" over any other consideration.

## Requirements

### Validated

<!-- Shipped and confirmed valuable in v1.0. -->

- ✓ Text chat with a local LLM (gemma4 → OpenAI) — v1.0
- ✓ Always-on webcam vision — v1.0
- ✓ Spoken replies via Kokoro TTS (Piper fast-ack fallback) — v1.0
- ✓ Wake-word activation ("Jarvis") + VAD-bounded recording — v1.0
- ✓ Provider abstraction: Ollama / OpenAI via Brain.ask() — v1.0
- ✓ Cross-session memory: SQLite + sqlite-vec semantic recall — v1.0
- ✓ Tool framework: @tool decorator, 25+ tools, 3-tier safety, abort rail — v1.0
- ✓ PC control: apps, windows, volume, clipboard, screenshot, shell — v1.0
- ✓ Files: read/write/search/PDF with allow-list + quarantine — v1.0
- ✓ Web search: SearXNG + trafilatura with URL allow-list — v1.0
- ✓ Outlook: inbox, email, drafts, send (Tier 2), calendar — v1.0
- ✓ Discord webhook: post_to_chat (Tier 2) — v1.0
- ✓ Multi-step agent composition with 8-call loop cap — v1.0
- ✓ Background tray process with graceful degradation matrix — v1.0
- ✓ Barge-in, voice abort, sentence-streaming TTS — v1.0

### Active

<!-- v2.0 scope: Cross-Platform Personal Assistant — Hybrid Brain + Computer Use -->

**Cross-platform core**
- [ ] Jarvis boots and runs on macOS (fix hard `LOCALAPPDATA` dependency in load_config)
- [ ] Shared core with OS-specific tool layers (pywin32/pycaw/winotify/Outlook COM on Windows; AppleScript/osascript/EventKit equivalents on macOS)
- [ ] Feature parity for PC-control tools on both platforms (apps, windows, volume, clipboard, screenshot, notifications)

**Hybrid brain**
- [ ] Anthropic Claude provider via official `anthropic` Python SDK (claude-opus-4-8, adaptive thinking, native tool use) — replaces OpenAI
- [ ] Local Ollama handles quick conversational turns; Claude handles hard multi-step tool-use turns
- [ ] Per-turn routing logic decides local vs Claude

**Computer-use agent**
- [ ] Structured control preferred first — media keys, AppleScript, app APIs
- [ ] Screenshot-based GUI understanding — see screen, identify elements (Claude vision)
- [ ] Vision-driven click/type/scroll fallback — navigate any app without hardcoded automation
- [ ] Self-correcting interaction loop — detect failures, adapt and retry

**Human-like presence**
- [ ] Natural voice with cadence, pauses, emotional modulation
- [ ] Personality-rich responses — humor, warmth, contextual wit
- [ ] Conversational memory flow — natural callbacks to prior topics

**Proactive assistant**
- [ ] Reminders and scheduled briefings
- [ ] Calendar awareness — surfaces upcoming events unprompted

**Daily driver**
- [ ] Autostart on login on both platforms
- [ ] Always listening with low friction — no babysitting

## Current Milestone: v2.0 Cross-Platform Personal Assistant — Hybrid Brain + Computer Use

**Goal:** Turn Jarvis into a daily-driver personal assistant that runs on both Windows 11 and macOS, thinks with a hybrid local (Ollama) + Claude brain, and can operate any app — structured control first, vision-based computer use as fallback.

### Out of Scope

<!-- Explicit boundaries. Reasons included so they don't sneak back in. -->

- **Becoming cloud-dependent** — Cloud LLM/TTS/STT is allowed as an *optional override* for users who want it, but the default build must remain fully usable with zero internet. Cloud lock-in is an explicit failure mode.
- **Shipping as a web app / Electron / browser UI** — Jarvis is a native desktop process, period. Any work that turns it into a web app is a wrong turn.
- **Linux support** — v2.0 targets Windows 11 + macOS. Linux remains a nice-to-have; don't build shims for it speculatively. (Superseded in v2.0: the old "no cross-platform" exclusion — the user now runs macOS daily, so macOS parity is in scope.)
- **Microservices / DI frameworks / premature abstractions** — The project is a single-file prototype today. Architectural complexity must earn its keep feature-by-feature. "Over-engineering" is an explicitly named failure mode.
- **Voice impersonation of a specific actor** — The assistant is "polished butler," not "Paul Bettany's JARVIS." The current system prompt already encodes this constraint. We train/tune voice models and personas toward the *archetype*, not a specific real person.
- **Image/video generation** — Jarvis consumes vision; it does not create images or video.
- **GUI / settings panel** — Configuration stays in `.env` and code. No settings app.

## Context

- **Current state**: v1.0 shipped. 6,235 lines of Python across `src/jarvis/` package (10 modules). 25+ tools across 7 domains. Background tray process with component health monitoring.
- **Environment**: Windows 11, Python 3.12, OpenAI (primary), Ollama (local fallback). Kokoro TTS + Piper fast-ack. SearXNG in Docker for web search. Outlook COM for email/calendar.
- **User profile**: The user built the prototype and is the sole operator. Comfortable with Python, .env config, Docker, Ollama models.
- **v1.0 delivered**: The action layer is complete — Jarvis does things, not just chats. Voice loop, tool framework, PC control, memory, files, web, email, calendar, Discord, multi-step composition.
- **Reference point**: Movie-JARVIS in vibe only. Not in look, voice, or branding.

## Constraints

- **Offline-capable**: Every must-have feature has to work with the network cable unplugged. Cloud is an opt-in speed/quality boost, never a dependency.
- **Single-user**: Built for one person on one machine. No multi-user model, no auth, no server.
- **Local storage only**: Memory, logs, cached models, recordings — all live on disk in the project directory or a local user folder. No cloud sync.
- **Python + local models**: Stay on Python and the current Ollama / faster-whisper ecosystem. Rewrites in another language are not on the table.
- **Minimal dependencies philosophy**: The project is a prototype; every new pip package needs a reason. Prefer stdlib and the few established libraries already in `requirements.txt`.
- **Platform**: Windows 11 and macOS are both first-class targets in v2.0. Shared core, OS-specific tool layers behind a platform abstraction. No Linux.
- **Trust model**: The user has opted into "trust by default" — actions run without confirmation. The only hard floor is that the system must expose *some* way to abort a running destructive action (Ctrl-C, hotkey, or voice interrupt). Everything else proceeds.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| **Action layer first, better brain later** | User's top pain is "doesn't do anything." Model quality is the wrong thing to optimize before tool use works at all. | ✓ Good — 25+ tools shipped in v1.0 |
| **Local high-quality TTS over cloud TTS** | "Voice is the whole point" + "no cloud lock-in" are both explicit user requirements. Kokoro + Piper is the answer. | ✓ Good — Kokoro primary, Piper fast-ack |
| **Wake word over push-to-talk** | User explicitly wants always-listening, not `m`-key recording. | ✓ Good — openWakeWord + silero-vad shipped |
| **Persistent memory is a first-class feature** | User flagged memory as "matters a lot" for daily-driver status. | ✓ Good — SQLite + sqlite-vec semantic recall |
| **Trust-by-default with hard abort rail** | Speed over confirm dialogs. Abort is the minimum safety guarantee. | ✓ Good — hotkey + voice + barge-in abort |
| **Package split at Phase 2** | Single-file through Phase 1, `jarvis/` package when tool registry needed it. | ✓ Good — clean split at the right time |
| **Windows-primary** | User is on Windows 11. Cross-platform is not a goal. | ✓ Good — COM, pywin32, SAPI all used |
| **Ollama / faster-whisper stack stays** | Already working, already local, already cached. | ✓ Good — stack preserved through v1.0 |
| **3-tier tool safety with quarantine** | Tier 0/1/2 + SAFE-04 quarantine blocks Tier 2 after external content. | ✓ Good — caught real bug in Phase 8 UAT |
| **Discord over Slack for v1.0 chat** | Simpler webhook, no OAuth needed. | ✓ Good — single requests.post() |
| **Claude replaces OpenAI as cloud brain (v2.0)** | Stronger multi-step tool use for an agentic assistant; official `anthropic` SDK, claude-opus-4-8, adaptive thinking. Local Ollama stays the offline default. | Pending — v2.0 |
| **Hybrid per-turn brain routing (v2.0)** | Quick turns stay local (fast, free, private); hard multi-step tool work goes to Claude. | Pending — v2.0 |
| **macOS becomes first-class (v2.0)** | User now develops and lives on a Mac; Windows-primary assumption no longer matches reality. | Pending — v2.0 |
| **Structured control before computer use (v2.0)** | AppleScript/media keys/APIs are faster, cheaper, and more reliable than screenshot+click; vision-based control is the fallback, not the default. | Pending — v2.0 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-05 after v2.0 scope expansion (cross-platform + hybrid Claude brain)*
