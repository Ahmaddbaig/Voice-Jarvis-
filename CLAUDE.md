# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the prototype

The entire app is a single script launched from the project's `.venv`:

```
cd /d C:\Users\extin\Desktop\Jarvis
.venv\Scripts\python.exe src\jarvis.py
```

There is no build step, no test suite, and no linter configured. Changes are validated by running `jarvis.py` and exercising the REPL (`m` mic, `c` camera, `s` status, `q` quit, or plain text).

Installing/updating dependencies:

```
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Configuration is env-driven

All runtime behavior is switched through `.env` (loaded via `python-dotenv` in `JarvisAssistant.__init__`). When editing behavior, prefer adding an env flag (use the existing `_env_flag` helper) over hardcoding. Key switches:

- `ASSISTANT_PROVIDER` — `ollama` (default, fully local) or `openai`. Validated in `__init__`; `openai` without `OPENAI_API_KEY` raises at startup.
- `JARVIS_ALWAYS_SEE` — when true, `ask_text` auto-attaches the latest webcam frame to **every** text prompt by routing through `ask_with_image`. This is why plain text chat implicitly becomes vision chat.
- `JARVIS_LOCAL_STT` — when true (default), mic transcription uses local `faster-whisper`; falls back to OpenAI only if the local import fails and a client is configured.
- `JARVIS_WHISPER_MODEL` — `tiny` / `base` / `small` / `medium` / `large-v3`. Model is lazy-loaded on first `transcribe()` call via `_get_local_whisper` and cached on the instance.
- `OLLAMA_MODEL` — must be a tag actually pulled in the local Ollama install. Vision prompts require a multimodal-capable tag.

## Architecture (single file: `src/jarvis.py`)

Two classes do all the work:

**`ContinuousVision`** — background webcam thread. Opens `cv2.VideoCapture(camera_index)` once, captures at `JARVIS_CAMERA_FPS` (default 2), and stores the latest JPEG bytes behind a `threading.Lock`. Consumers call `latest_image_data_url()` (non-blocking) or `wait_for_image_data_url(timeout)` (short poll). It keeps the camera open for the whole session — do not open a second `VideoCapture` on the same index concurrently, it will fight for the device. `capture_camera_frame()` on `JarvisAssistant` is the fallback path that opens its own one-shot capture when the background thread hasn't produced a frame yet.

**`JarvisAssistant`** — provider-agnostic orchestrator. The critical dispatch logic lives in `ask_text` → `ask_with_image` → `ask_ollama`. The provider branch is checked inside each `ask_*` method rather than through polymorphism, so when adding a new capability you must handle both `openai` and `ollama` branches explicitly.

### Provider differences that matter

- **OpenAI path** uses the Responses API (`client.responses.create`) with `previous_response_id` threading conversation state server-side. History is **not** kept in memory.
- **Ollama path** hits `{OLLAMA_URL}/api/chat` directly via `requests`, passes images as a base64 string inside `user_message["images"]` (Ollama-specific; unlike OpenAI's `input_image` / `image_url` shape), and maintains its own in-memory rolling window in `self.history[-16:]` (last 8 exchanges).
- **TTS**: `speak()` uses `pyttsx3` (local SAPI5 on Windows) whenever the provider is `ollama` **or** `self.client` is None; otherwise it streams from OpenAI `audio.speech` as a WAV and plays via `sounddevice`. `_configure_local_tts` scores installed voices against British/English keywords to pick something closer to the target persona.
- **STT** (`transcribe`): local-first via `_transcribe_local` (faster-whisper, `beam_size=1`, VAD filter). OpenAI transcribe is only reached if `JARVIS_LOCAL_STT=false` or the local import fails AND `self.client` exists.

### System prompt and persona

`SYSTEM_PROMPT` at the top of the file encodes the persona constraints: polished/British-styled desktop assistant, no JARVIS/Tony Stark/real-actor impersonation, terse. This prompt is sent with **every** request in both providers. If you're tweaking personality or safety guardrails, that's the single source.

## Notes

- Microphone recording is fixed at 5 seconds (`RECORD_SECONDS`), mono 16 kHz, written to a temp WAV. There is no VAD on the input side.
- `previous_response_id` persists only within a single process run; restarting Jarvis starts a fresh OpenAI conversation. The Ollama history is likewise in-memory only.
- `.env` is git-ignored (see `.gitignore`); `.env.example` is the canonical list of supported variables.
- Windows-specific: paths use backslashes in docs, but forward slashes work fine in Python. When running commands via bash, use Unix-style paths (`.venv/Scripts/python.exe`).

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Jarvis**

A local, action-capable desktop AI assistant for Windows. Jarvis listens on a wake word, sees through the webcam, remembers its user across sessions, and *does things* — controlling the PC, searching the web, reading personal files, and communicating on the user's behalf — with a polished, genuinely pleasant voice. It is not a chatbot. It is a daily driver.

**Core Value:** **Jarvis takes real actions for its user, by voice, and stays useful with no internet connection.** Every trade-off resolves in favor of "can it actually *do* the thing you asked, right now, offline, without nagging you" over any other consideration.

### Constraints

- **Offline-capable**: Every must-have feature has to work with the network cable unplugged. Cloud is an opt-in speed/quality boost, never a dependency.
- **Single-user**: Built for one person on one machine. No multi-user model, no auth, no server.
- **Local storage only**: Memory, logs, cached models, recordings — all live on disk in the project directory or a local user folder. No cloud sync.
- **Python + local models**: Stay on Python and the current Ollama / faster-whisper ecosystem. Rewrites in another language are not on the table.
- **Minimal dependencies philosophy**: The project is a prototype; every new pip package needs a reason. Prefer stdlib and the few established libraries already in `requirements.txt`.
- **Platform**: Windows 11 primary target. Don't build Windows-specific hacks where a trivially portable alternative exists, but prioritize "works on this machine" over "works everywhere."
- **Trust model**: The user has opted into "trust by default" — actions run without confirmation. The only hard floor is that the system must expose *some* way to abort a running destructive action (Ctrl-C, hotkey, or voice interrupt). Everything else proceeds.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Executive Opinion (Read This First)
## Recommended Stack
### Dimension 1 — Wake-Word Engine
| Technology | Version | Purpose | Why |
|---|---|---|---|
| **openWakeWord** | `0.6.0` (pip: `openwakeword`) | Always-listening "Jarvis" detection | Apache-2.0, 100% offline, pure ONNX runtime, ~5% CPU on one core, custom wake-word training with synthetic data (no voice collection needed), pre-trained models include `hey_jarvis` out of the box |
### Dimension 2 — Voice Activity Detection (VAD)
| Technology | Version | Purpose | Why |
|---|---|---|---|
| **silero-vad** | `6.2.x` (pip: `silero-vad`) | Stop recording when user stops talking | MIT licensed, ONNX runtime, <1ms per 30ms chunk on single CPU thread, trained on 6000+ languages, zero telemetry |
# feed 512-sample (~32ms) chunks; VADIterator emits {'start': ...} / {'end': ...}
### Dimension 3 — Local Tool-Use LLM (the brain upgrade)
| Stage | Model | Ollama tag | RAM | Why |
|---|---|---|---|---|
| **Stage 0 (today)** | gemma4:latest | `gemma4:latest` | ~9.6 GB | Already pulled. Gemma's tool-use story is weak — use this only until Stage 1 is wired up, then switch. |
| **Stage 1 (immediate)** | **Qwen 3 4B** | `qwen3:4b` | ~4 GB | Best-in-class small-model tool calling (benchmarks show Qwen3 4B beating many 14B models at JSON-schema tool invocation). Apache-2.0. Fits in 8 GB RAM with room for whisper + vision + TTS loaded simultaneously. This is the right daily-driver default. |
| **Stage 2 (quality upgrade)** | **Qwen 3 14B** | `qwen3:14b` | ~10-12 GB | If Stage 1 proves reliable but needs stronger reasoning for multi-step tool sequences. Still fits on a 16 GB machine. |
| **Stage 3 (aspirational)** | **Llama 3.3 70B** or **Qwen 3 32B** | `llama3.3:70b` / `qwen3:32b` | 40+ GB | Only if you add a 32+ GB RAM / 24 GB VRAM GPU. Not needed for core functionality. |
### Dimension 4 — Ollama Tool-Use API
| Technology | Version | Purpose | Why |
|---|---|---|---|
| **Ollama `/api/chat` with `tools` parameter** | Ollama server ≥ 0.4 | Native function calling | First-class since Ollama 0.4; returns `message.tool_calls` as structured JSON; supports streaming with tools since Ollama 0.5 |
| **`ollama` Python package** | `0.4.x` or later | Typed Python client with auto-schema from docstrings | Optional — auto-converts Python functions into tool schemas via Pydantic + docstring parsing. Saves boilerplate vs hand-written JSON schemas. |
### Dimension 5 — Windows Automation
| Technology | Version | Purpose | Why |
|---|---|---|---|
| **`subprocess` (stdlib)** | Python 3.12 | Launching apps, running shell commands, media control via `nircmd`/`powershell` | Zero dependency. Correct abstraction for "launch Firefox" or "adjust volume." Use `subprocess.Popen` with `creationflags=subprocess.CREATE_NO_WINDOW` on Windows to avoid console flashes. |
| **`pywin32`** | `pywin32 >= 308` | Window enumeration, focus, close, minimize; COM access to Explorer/Outlook; registry reads | Official Microsoft Python bindings. Lower-level than pywinauto but rock-solid for "find the Firefox window and bring it forward." Ships `win32gui`, `win32con`, `win32com.client`. |
| **`pywinauto`** | `0.6.9` | UIA-based control of specific in-app widgets when you need to click a button inside a running program | Correct tool for the few cases where pywin32 is too low-level (e.g. "click Send in the new mail composer"). Uses Windows UI Automation backend, which is the modern accessibility API. |
### Dimension 6 — Shell Execution
| Technology | Version | Purpose | Why |
|---|---|---|---|
| **`subprocess` (stdlib)** | Python 3.12 | All shell execution | Only correct answer. Use `Popen` + non-blocking I/O for long commands; `run(..., capture_output=True, timeout=N)` for quick ones. |
| **`asyncio.create_subprocess_exec`** | Python 3.12 | When the LLM tool layer goes async | Needed once the voice loop is async (wake-word + VAD + TTS naturally want to be concurrent). |
# Keep a reference to proc so a voice "cancel" can call proc.terminate()
# Stream stdout on a thread; cap output at 4 KB before sending back to the model.
### Dimension 7 — File / PDF Reading
| Technology | Version | Purpose | Why |
|---|---|---|---|
| **PyMuPDF** | `pymupdf >= 1.24` (package renamed from `fitz`) | PDF text, layout, and image extraction | Fastest benchmarked extractor (~2.5x faster than pdfplumber), highest word-order accuracy, handles scanned PDFs with built-in OCR hooks |
| **pymupdf4llm** | `>= 0.0.17` | PDF → clean Markdown for LLM ingestion | Purpose-built for RAG/LLM workflows; preserves headings and tables as Markdown. Use this specifically when the LLM is going to summarize. |
| **stdlib `pathlib` + `open()`** | Python 3.12 | Text files, markdown, source code, .env | No library needed. |
| **`watchdog`** | `>= 4.0.0` | Directory monitoring for "Jarvis, what's new in my downloads folder?" | Cross-platform filesystem event library, actively maintained. |
### Dimension 8 — Web Search
| Technology | Version | Purpose | Why |
|---|---|---|---|
| **SearXNG** | Latest (`docker.io/searxng/searxng:latest`) | Metasearch aggregator, 70+ engines, no API keys | Free, self-hosted, returns JSON. Runs as a local Docker container on `localhost:8080`. Python hits it with `requests`. No cloud API, no rate limits tied to an account. |
| **`requests` (existing)** | — | Query SearXNG from Python | Already in requirements.txt. |
| **`trafilatura`** | `>= 1.12` | Fetch + extract clean article text from a URL the LLM picked | Best-in-class HTML-to-text extractor for LLM ingestion. Handles boilerplate removal, comments, navigation better than BeautifulSoup. |
### Dimension 9 — Email & Calendar (Windows desktop)
| Technology | Version | Purpose | Why |
|---|---|---|---|
| **`pywin32` → `win32com.client`** | `>= 308` | Read inbox, send mail, read calendar via the local Outlook client | Zero auth, zero API keys, works offline for cached mail, uses whatever Outlook profile is already set up. This is the only approach that respects the "no cloud lock-in" constraint. |
### Dimension 10 — Persistent Memory Storage
| Technology | Version | Purpose | Why |
|---|---|---|---|
| **`sqlite3` (stdlib)** | Python 3.12 | Conversation log, user profile, tool-call history, structured facts | Built into Python. Zero new dependency. Perfect for tabular memory. One `memory.db` file in the project dir. |
| **`sqlite-vec`** | `0.1.7` | Vector search on top of the same SQLite file for semantic recall | Pure C extension, zero dependencies, ~1 MB. Loads into the existing SQLite connection as `conn.enable_load_extension(True); sqlite_vec.load(conn)`. Brute-force KNN that's fast enough for any realistic personal-memory corpus (tens of thousands of items). |
| **`sentence-transformers`** | `>= 3.0` with `all-MiniLM-L6-v2` | Generate the embeddings that sqlite-vec searches over | 80 MB model, runs on CPU, 384-dim embeddings, ~5ms per sentence. Good enough for personal memory; no need for a larger embedding model. |
- One SQLite file at `~/.jarvis/memory.db` (NOT inside the project dir — the user's data shouldn't be git-adjacent).
- Tables: `conversations` (timestamped messages), `facts` (extracted user profile: preferences, names, projects), `tool_calls` (audit log with ability to abort mid-flight).
- A virtual `vec_memories` table from `sqlite-vec` storing embeddings + rowid references back to `facts`.
- Startup: load top-N recent conversation turns into context. On each new user turn, embed the query and pull top-K semantically similar `facts`.
### Dimension 11 — Local High-Quality TTS
| Technology | Version | Purpose | Why |
|---|---|---|---|
| **Kokoro** | `kokoro >= 0.9.2` (pip package) | Primary TTS — the "polished butler voice" | #1 on TTS Arena leaderboard January 2026, MOS 4.2, 82M params, 350 MB model, pip-installable, Apache-2.0 weights, runs on CPU in real-time, 54 built-in voices including British-sounding `bm_daniel` and `bm_george`. This is the single biggest upgrade to the project. |
| **Piper** | `piper-tts >= 1.4.2` | Fallback / low-latency path | Smaller and faster than Kokoro (sub-100ms latency on CPU), also MIT-licensed, runs on Raspberry Pi. Lower MOS (~3.5) but nearly zero first-token latency. Worth keeping as a "quick acknowledgment" voice before the Kokoro synthesis completes on longer replies. |
| **espeak-ng** | System install via chocolatey or winget | Phonemizer dependency for Kokoro | Kokoro needs espeak-ng on the PATH for text → phoneme conversion. This is the single gotcha that bites most Windows installs. |
- Kokoro on CPU: ~1-2 seconds for a 10-word reply. Fine for most responses.
- For multi-sentence replies, stream sentence-by-sentence: synthesize sentence 1 while speaking sentence 0.
- Alternative: use Piper for an immediate "Yes —" / "One moment —" acknowledgment while Kokoro is still synthesizing the real reply. This is a free UX upgrade.
### Dimension 12 — Process Architecture (background daemon)
| Technology | Version | Purpose | Why |
|---|---|---|---|
| **`pythonw.exe`** | bundled with Python 3.12 | Launch the app without a console window | Built-in. Change the shortcut target from `python.exe src\jarvis.py` to `pythonw.exe src\jarvis.pyw`. |
| **`pystray`** | `>= 0.19.5` | Taskbar tray icon for status + quit | Cross-platform, tiny, threaded correctly, still maintained. Provides the minimum GUI surface that PROJECT.md's "no settings panel" constraint permits. |
| **`Pillow`** | `>= 10.0` | Render the tray icon image | pystray dependency. |
| **`pynput`** | `>= 1.7.7` | Global hotkey registration (e.g. Ctrl+Shift+Space to force-listen) | Cross-platform, maintained, no admin required on Windows. |
| **Windows Startup folder shortcut** | — | Autostart on login | Simplest reliable autostart. `shell:startup` → drop a shortcut pointing at `pythonw.exe`. |
## Consolidated Installation Block
# Voice loop
# TTS upgrade
# Tool-use / actions
# File + web
# Memory
# Process / UX
- **espeak-ng** — required by Kokoro for phonemization. `winget install eSpeak-NG.eSpeak-NG` or `choco install espeak-ng`.
- **Docker Desktop** (or WSL2 with Docker) — required for SearXNG. Flag this in the roadmap as an optional dep for the web-search milestone; the rest of the stack works without it.
- **Ollama** with models pulled: `ollama pull qwen3:4b` (~2.6 GB) alongside the existing `gemma4:latest`.
- `ollama>=0.4.0` (Python SDK) — only if hand-rolling tool schemas becomes painful.
## Alternatives Considered (at-a-glance table)
| Dimension | Recommended | Alternative | Why Not Alternative |
|---|---|---|---|
| Wake word | openWakeWord | Porcupine | Account-gated, telemetry, cloud anti-goal |
| VAD | silero-vad | webrtcvad | 2015-era GMM, hallucinates on noise |
| Small tool-use LLM | Qwen 3 4B | Llama 3.3 8B | Qwen 3 benchmarks higher on tool calls |
| Tool API | Raw `requests` + `/api/chat` | `ollama` Python SDK | Adds dep; marginal value |
| Window automation | pywin32 + pywinauto | pyautogui | Brittle, coordinate-based, visible |
| PDF | PyMuPDF | pdfplumber | Slower, only wins on tables |
| Web search | Self-hosted SearXNG | Tavily / Serper | Paid, account-gated |
| Email | Outlook COM | MS Graph | Requires Azure app registration |
| Memory | SQLite + sqlite-vec | ChromaDB | 20+ transitive deps, telemetry |
| TTS | Kokoro | XTTS-v2 | GPU-bound, Coqui defunct |
| Background process | pythonw + pystray | Windows Service | Session 0 — no audio/webcam access |
## What NOT to Use
| Avoid | Why | Use Instead |
|---|---|---|
| **Porcupine** | Cloud account required, telemetry, device cap | openWakeWord |
| **webrtcvad** | Old, noisy, false positives on fans/music | silero-vad |
| **pyautogui as primary** | Coordinate-based, brittle, visible to user, blocked by locked screen | pywin32 + pywinauto |
| **`keyboard` package** | Needs admin on Windows, maintainer unresponsive | pynput or pywin32 RegisterHotKey |
| **`os.system()` for shell** | Can't cancel, can't capture output, blocks thread | `subprocess.Popen` |
| **pypdf for summarization** | Spacing artifacts, no layout awareness | PyMuPDF / pymupdf4llm |
| **ChromaDB** | 20+ transitive deps, telemetry, breaking migrations | sqlite-vec + sentence-transformers |
| **XTTS-v2 on CPU** | 3-5x real-time, unusable latency without GPU | Kokoro |
| **Coqui TTS** | Company defunct, unreliable forks | Kokoro |
| **Tortoise TTS** | 30s per sentence, DOA for real-time | Kokoro |
| **Windows Service for the main process** | Session 0 isolation blocks audio/webcam | pythonw + pystray |
| **Basic-auth IMAP against Outlook.com** | Deprecated Dec 2022 by Microsoft | Outlook COM via pywin32 |
| **Cloud TTS/STT/LLM as the default** | Project anti-goal: no cloud lock-in | All defaults stay local; cloud is opt-in only |
## Stack Patterns by Variant
- Bump to Qwen 3 14B as the default brain (`qwen3:14b`) — fits in VRAM with room for whisper.
- Flip `faster-whisper` compute to `float16` on GPU instead of `int8` on CPU (faster, more accurate).
- Kokoro on GPU gets you near-instant synthesis — stream sentence-by-sentence becomes unnecessary.
- Stage 1 = Qwen 3 4B. Don't push to 14B until you've measured tool-call reliability and decided you need more brain.
- Use Piper for short acknowledgment replies ("Yes —", "Done.") and Kokoro for substantive replies.
- Preload models at startup — don't lazy-load whisper on first mic press.
- Web search tool returns "I don't have web access configured right now" as an in-character response.
- Offline features (memory, file reading, app control, calendar, email via COM) all still work.
- This is the graceful-degradation contract the project already promises.
## Version Compatibility Notes
| Package | Compatible With | Notes |
|---|---|---|
| Python 3.12 | All recommended libs | Stay on 3.12 — do NOT move to 3.13 yet; several audio libs (sounddevice, pyttsx3) have known 3.13 issues as of April 2026. |
| `faster-whisper` | `ctranslate2` | Keep existing pin range; don't mix with `openai-whisper` in the same env. |
| `openwakeword` on Windows | `onnxruntime` only (no `tflite-runtime`) | Install with bare `pip install openwakeword`, not `[full]`. |
| `kokoro` | `espeak-ng` on PATH | Missing espeak-ng is the #1 install failure. Verify before first run. |
| `pywin32` | Post-install step | After `pip install pywin32`, run `python Scripts/pywin32_postinstall.py -install` once to register COM. |
| `sqlite-vec` + stdlib `sqlite3` | Python must be built with `enable-loadable-sqlite-extensions` | The official python.org Windows build has this enabled. Conda's build does NOT. If the user is on conda Python, they need `pip install pysqlite3-binary` or they'll get "not authorized" errors. |
| `silero-vad` + `torch` | Optional torch dep | v5+ has a pure-ONNX path that does NOT require torch. Use `load_silero_vad(onnx=True)`. Without `onnx=True`, it pulls in ~2 GB of torch. |
| `sentence-transformers` | `torch` | Unavoidable torch dep (~700 MB). Budget for this in the install footprint. If torch is a dealbreaker, switch to `fastembed` with ONNX-only models. |
## Windows-Specific Gotchas (summary)
## Confidence Summary
| Recommendation | Confidence | Basis |
|---|---|---|
| openWakeWord for wake word | HIGH | Only viable offline option; ships `hey_jarvis` pretrained model |
| silero-vad for VAD | HIGH | Clear quality winner; verified via multiple 2026 sources |
| Ollama `/api/chat` tool-calling protocol | HIGH | Documented, stable since Ollama 0.4 |
| Qwen 3 4B as Stage 1 brain | MEDIUM-HIGH | Strong benchmarks but small-model tool use is volatile; budget for A/B testing |
| pywin32 + pywinauto automation stack | HIGH | Well-established 2026 pattern for Windows desktop automation |
| SearXNG for web search | HIGH | Correct offline-first choice; Docker dependency is the main caveat |
| Outlook COM for email | HIGH (if Outlook present) | Only approach that avoids cloud OAuth on Outlook.com |
| sqlite-vec for memory | HIGH | Zero-dep, stable 0.1.7 release, pure C |
| Kokoro for TTS | HIGH (quality) / MEDIUM (Windows install smoothness) | Benchmark-leading; espeak-ng is the friction point |
| pythonw + pystray for process | HIGH | Correct architecture; Windows Service is the wrong shape |
## Sources
### Primary (HIGH confidence)
- Ollama tool calling docs — https://docs.ollama.com/capabilities/tool-calling
- Ollama Python library 0.4 blog — https://ollama.com/blog/functions-as-tools
- Ollama streaming tool calls — https://ollama.com/blog/streaming-tool
- openWakeWord GitHub — https://github.com/dscripka/openWakeWord
- silero-vad GitHub — https://github.com/snakers4/silero-vad
- sqlite-vec GitHub + PyPI — https://github.com/asg017/sqlite-vec, https://pypi.org/project/sqlite-vec/
- Kokoro-82M HuggingFace — https://huggingface.co/hexgrad/Kokoro-82M
- Kokoro pip package — https://github.com/hexgrad/kokoro
- Piper TTS releases — https://github.com/rhasspy/piper
- PyMuPDF docs — https://pymupdf.readthedocs.io/en/latest/
- pywinauto docs — https://pywinauto.readthedocs.io/en/latest/
- SearXNG API docs — https://docs.searxng.org/dev/search_api.html
- Qwen 3 on Ollama — https://ollama.com/library/qwen3
- Qwen3 official blog — https://qwenlm.github.io/blog/qwen3/
### Secondary (MEDIUM confidence, benchmark/review sources)
- 2026 local LLM tool-calling benchmark — https://www.jdhodges.com/blog/local-llms-on-tool-calling-2026-pt1-local-lm/
- Best Ollama models 2026 — https://www.morphllm.com/best-ollama-models
- Open-source TTS comparison 2026 — https://www.bentoml.com/blog/exploring-the-world-of-open-source-text-to-speech-models
- TTS quality rankings — https://www.codesota.com/guides/tts-models
- PDF parser benchmark — https://unstract.com/blog/evaluating-python-pdf-to-text-libraries/
- VAD comparison — https://picovoice.ai/blog/best-voice-activity-detection-vad/
- Wake word guide — https://picovoice.ai/blog/complete-guide-to-wake-word/
- Outlook COM guide 2026 — https://copyprogramming.com/howto/how-to-download-outlook-attachment-from-python-script
- sqlite-vec intro — https://alexgarcia.xyz/sqlite-vec/
### Tertiary (LOW confidence, community posts used for cross-checks only)
- DEV.to local LLM guide 2026
- Medium articles on pywinauto/pyautogui comparisons
- Various self-hosting SearXNG walkthroughs
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, or `.github/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
