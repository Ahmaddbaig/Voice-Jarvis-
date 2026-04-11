# Jarvis

## What This Is

A local, action-capable desktop AI assistant for Windows. Jarvis listens on a wake word, sees through the webcam, remembers its user across sessions, and *does things* — controlling the PC, searching the web, reading personal files, and communicating on the user's behalf — with a polished, genuinely pleasant voice. It is not a chatbot. It is a daily driver.

## Core Value

**Jarvis takes real actions for its user, by voice, and stays useful with no internet connection.** Every trade-off resolves in favor of "can it actually *do* the thing you asked, right now, offline, without nagging you" over any other consideration.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

- ✓ Text chat with a local LLM (gemma4:latest via Ollama) — existing (`src/jarvis.py`)
- ✓ Always-on webcam vision, latest frame auto-attached to every request — existing (`ContinuousVision` class)
- ✓ Spoken replies via local TTS (pyttsx3 / SAPI5) — existing
- ✓ Push-to-talk mic capture with local transcription (faster-whisper) — existing, fully offline
- ✓ Provider abstraction: swappable Ollama / OpenAI backends — existing
- ✓ Ephemeral conversation history inside a single process run — existing

### Active

<!-- Current scope. Building toward daily-driver status. -->

**Brain & persona**
- [ ] Persona refinement: terse, calm, polished "butler" with dry wit — tuned system prompt + conversation style
- [ ] Iterable brain strategy — stay on gemma4 initially, evaluate larger local models (Llama 3.3, Qwen 2.5, tool-use-tuned variants) once tool calling is wired up

**Action layer (the biggest gap)**
- [ ] Tool-use / function-calling framework so the LLM can invoke actions, not just describe them
- [ ] **Control the PC**: launch/focus/close apps, basic window management, run shell commands, file read/write/search, volume + media control
- [ ] **Web + knowledge**: live web search, fetch and summarize pages, current-info answers (weather, news, lookups)
- [ ] **Personal data**: read PDFs / text files / notes on disk, email inbox access, calendar access
- [ ] **Communication**: draft and send email, post to chat services on the user's behalf
- [ ] A minimal safety rail so a destructive, irreversible action can still be aborted mid-flight (user has opted into "trust by default" but this is the one non-negotiable guard)

**Persistent memory (first-class)**
- [ ] Cross-session memory: who the user is, their preferences, recent conversations, ongoing projects
- [ ] Memory is loaded into context on startup and updated as the conversation evolves — it is not a bolt-on afterthought
- [ ] Storage stays local (SQLite / flat files / local vector store), no cloud sync

**Voice loop upgrade**
- [ ] Wake-word activation (say "Jarvis") replacing the terminal-bound `m` key
- [ ] Always-listening pipeline: wake-word engine → VAD-bounded recording → local STT → brain → TTS
- [ ] Natural turn-taking: stop recording when the user stops talking, not on a fixed 5-second timer
- [ ] High-quality **local** TTS (XTTS-v2, Piper, or similar) replacing robotic SAPI5 — voice quality is a headline feature, not a detail

**Vision**
- [ ] Keep always-on webcam vision working end-to-end through the new action layer
- [ ] "What am I looking at" / "read this screen" / "describe what's on my desk" as first-class commands

**Reliability**
- [ ] Runs as a background process with a stable hotkey/wake-word interface, not just a terminal REPL
- [ ] Survives provider errors (Ollama down, whisper model missing, camera unplugged) without crashing the loop

### Out of Scope

<!-- Explicit boundaries. Reasons included so they don't sneak back in. -->

- **Becoming cloud-dependent** — Cloud LLM/TTS/STT is allowed as an *optional override* for users who want it, but the default build must remain fully usable with zero internet. Cloud lock-in is an explicit failure mode.
- **Shipping as a web app / Electron / browser UI** — Jarvis is a native desktop process, period. Any work that turns it into a web app is a wrong turn.
- **Cross-platform parity on day one** — macOS and Linux are nice-to-haves. We will not hold back a Windows feature because it can't be made cross-platform today. Avoid hardcoding Windows-only paths where the alternative is trivial, but don't build cross-platform shims speculatively.
- **Microservices / DI frameworks / premature abstractions** — The project is a single-file prototype today. Architectural complexity must earn its keep feature-by-feature. "Over-engineering" is an explicitly named failure mode.
- **Voice impersonation of a specific actor** — The assistant is "polished butler," not "Paul Bettany's JARVIS." The current system prompt already encodes this constraint. We train/tune voice models and personas toward the *archetype*, not a specific real person.
- **Image/video generation** — Jarvis consumes vision; it does not create images or video.
- **GUI / settings panel** — Configuration stays in `.env` and code. No settings app.

## Context

- **Starting point**: ~400 lines of Python in `src/jarvis.py`. Single file, two classes (`ContinuousVision`, `JarvisAssistant`), provider dispatch branching on `self.provider` at each call site. All features already work end-to-end: text, vision, mic, TTS, Ollama + OpenAI.
- **Environment**: Windows 11, local Ollama install with `gemma4:latest` (8B Q4, ~9.6 GB) already pulled. faster-whisper `base` model (~145 MB) already cached. Python 3.12 in a project-local `.venv`.
- **User profile**: The user built the prototype themselves and is comfortable running Python, editing `.env`, and installing Ollama models. They are the sole user and target audience — this is being built for them specifically, not for a general audience.
- **Biggest felt pain today**: "It doesn't really DO anything — it just chats." That's the wound driving every priority below. Solving the action layer *is* the roadmap.
- **Reference point**: Movie-JARVIS in vibe only. Not in look, voice, or branding. The existing system prompt is explicit about never impersonating the character or the actor.

## Constraints

- **Offline-capable**: Every must-have feature has to work with the network cable unplugged. Cloud is an opt-in speed/quality boost, never a dependency.
- **Single-user**: Built for one person on one machine. No multi-user model, no auth, no server.
- **Local storage only**: Memory, logs, cached models, recordings — all live on disk in the project directory or a local user folder. No cloud sync.
- **Python + local models**: Stay on Python and the current Ollama / faster-whisper ecosystem. Rewrites in another language are not on the table.
- **Minimal dependencies philosophy**: The project is a prototype; every new pip package needs a reason. Prefer stdlib and the few established libraries already in `requirements.txt`.
- **Platform**: Windows 11 primary target. Don't build Windows-specific hacks where a trivially portable alternative exists, but prioritize "works on this machine" over "works everywhere."
- **Trust model**: The user has opted into "trust by default" — actions run without confirmation. The only hard floor is that the system must expose *some* way to abort a running destructive action (Ctrl-C, hotkey, or voice interrupt). Everything else proceeds.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| **Action layer first, better brain later** | User's top pain is "doesn't do anything." Model quality is the wrong thing to optimize before tool use works at all. | — Pending |
| **Local high-quality TTS over cloud TTS** | "Voice is the whole point" + "no cloud lock-in" are both explicit user requirements. XTTS-v2 / Piper is the only way both can be true. | — Pending |
| **Wake word over push-to-talk** | User explicitly wants always-listening, not `m`-key recording. Turns Jarvis from a terminal program into a real ambient assistant. | — Pending |
| **Persistent memory is a first-class feature, not an add-on** | User flagged memory as "matters a lot" for daily-driver status. It needs to exist on day one of the memory phase, not be tacked on later. | — Pending |
| **Trust-by-default autonomy with a hard abort rail** | User wants speed and naturalness over confirm-dialog friction. A mid-action abort is the minimum safety guarantee. | — Pending |
| **Stay single-file as long as reasonably possible** | "Over-engineering" is an explicit anti-goal. Don't split into packages until a concrete feature needs it. | — Pending |
| **Windows-primary, no cross-platform shims yet** | User is on Windows 11. Cross-platform work is an anti-goal at this stage. | — Pending |
| **Ollama / faster-whisper stack stays** | Already working, already local, already cached. Changing the stack is wasted motion. | — Pending |

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
*Last updated: 2026-04-10 after initialization*
