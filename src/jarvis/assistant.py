"""Phase 1 Jarvis voice-first entry point.

This file is the voice-first launcher. It owns the asyncio worker thread,
the wake-word stream, the global hotkey listener, and the turn pipeline
coroutine that wires Wave 1/2/3 components together.

The companion file ``src/jarvis_cli.py`` is the preserved push-to-talk REPL
(m/c/s/q keys) for development. Both share the :class:`JarvisAssistant`
class defined here, but the CLI constructs it with ``preloaded=None`` so it
skips the heavy openWakeWord/Kokoro/Piper preload (CONTEXT.md D-15).

ContinuousVision is preserved verbatim from the original prototype — it's
already a daemon thread, no asyncio integration needed. Vision is auto-
attached to every text turn via ``ask_text`` (existing behavior).

Topology (CONTEXT.md D-17, research §Pattern 1):

  main thread:           load_config → preload_all → JarvisAssistant
                                    → start_voice_loop → time.sleep loop (Ctrl+C)
  worker thread:         asyncio event loop → _async_main → _turn_pipeline
  PortAudio thread:      WakeWordStream callback → call_soon_threadsafe → loop
  pynput thread:         GlobalHotKeys → call_soon_threadsafe → loop
  ContinuousVision:      daemon thread, untouched
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import platform
import re
import sys
import tempfile
import threading
import time
import uuid
import wave
from pathlib import Path

import cv2
import numpy as np
import pyttsx3
import requests
import sounddevice as sd
from dotenv import load_dotenv
from openai import OpenAI
from pynput import keyboard as kb

from jarvis.core.config import Config, load_config
from jarvis.core.preload import preload_all, PreloadedModels
from jarvis.core.brain import Brain, BrainResponse, ToolCall
from jarvis.core.abort import PopenRegistry, AbortController
from jarvis.core.audit import AuditLog
from jarvis.core.memory import MemoryStore
from jarvis.audio.input import WakeWordStream, VadRecorder, TwoStageGate
from jarvis.audio.output import PiperAck, FallbackTTS, CloudTTS
from jarvis.audio.wake_log import WakeLog
from jarvis.tools import all_schemas, call_tool, get_tier, discover_tools
from jarvis.tools.shell import set_popen_registry
from jarvis.tools.search import set_searxng_url
from jarvis.tools.memory_tools import set_memory_store


SAMPLE_RATE = 16_000
RECORD_SECONDS = 5
DEFAULT_CAMERA_INDEX = 0
DEFAULT_CAMERA_FPS = 2.0

SYSTEM_PROMPT = """
You are the user's private desktop assistant. You address the user as "sir"
on every turn. Your persona is that of a polished, calm British butler with
a consistent dry undertone — think Alfred from Batman who happens to run a
computer. Most replies carry a wry edge, not just the absurd ones.

Answer in ONE short sentence unless the user explicitly asks for detail
("tell me more", "go deeper", "explain"). Keep the dry butler wit but get
to the point. Never rambling. Never servile. Never open with filler like
"Certainly, sir" — the answer itself is the reply.

Do not claim to be JARVIS, Tony Stark's assistant, Paul Bettany, or any real
actor. If the user asks for "the movie voice," acknowledge briefly that you
can speak in a polished British style but cannot clone or impersonate a
specific real voice.

When describing what the camera sees, describe only what is visible and
say when you are uncertain.
""".strip()


EXTRACTION_SYSTEM_PROMPT = """You extract facts about the user from conversations.

Analyze the exchange below and return a JSON array of facts learned about the user.
Each fact is an object with these fields:
- "type": one of "identity", "preference", "profile", "state", "event"
- "key": a short identifier (e.g. "name", "reply_style", "current_project")
- "value": the fact value as a concise string

If no new facts are present, return an empty array: []

If a new fact contradicts a previously known fact, include a "supersedes_key" field
with the key of the old fact.

Return ONLY valid JSON. No markdown, no explanation.

Type definitions:
- identity: name, age, pronouns -- things that rarely change
- preference: communication style, units, language -- user preferences
- profile: job, location, interests, family -- biographical info
- state: current project, mood, what they're working on -- changes often
- event: meetings, trips, appointments -- time-bound occurrences"""


def _extract_base64_from_data_url(image_data_url: str) -> str:
    match = re.match(r"^data:image/[^;]+;base64,(.+)$", image_data_url)
    if not match:
        raise ValueError("Unsupported image data URL.")
    return match.group(1)


class ContinuousVision:
    def __init__(self, camera_index: int, fps: float) -> None:
        self.camera_index = camera_index
        self.fps = max(fps, 0.2)
        self._lock = threading.Lock()
        self._latest_jpeg: bytes | None = None
        self._latest_captured_at: float | None = None
        self._error: str | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def status(self) -> str:
        with self._lock:
            if self._latest_captured_at:
                age = time.time() - self._latest_captured_at
                return f"camera online, latest frame {age:.1f}s ago"
            if self._error:
                return f"camera unavailable: {self._error}"
            return "camera starting"

    def latest_image_data_url(self) -> str | None:
        with self._lock:
            if not self._latest_jpeg:
                return None
            b64_image = base64.b64encode(self._latest_jpeg).decode("ascii")
        return f"data:image/jpeg;base64,{b64_image}"

    def wait_for_image_data_url(self, timeout_seconds: float = 2.0) -> str | None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            image_data_url = self.latest_image_data_url()
            if image_data_url:
                return image_data_url
            time.sleep(0.05)
        return self.latest_image_data_url()

    def _capture_loop(self) -> None:
        camera = cv2.VideoCapture(self.camera_index)
        try:
            if not camera.isOpened():
                self._set_error("could not open the webcam")
                return

            while not self._stop_event.is_set():
                ok, frame = camera.read()
                if not ok:
                    self._set_error("could not read a frame")
                    time.sleep(1)
                    continue

                ok, encoded = cv2.imencode(".jpg", frame)
                if not ok:
                    self._set_error("could not encode a frame")
                    time.sleep(1)
                    continue

                with self._lock:
                    self._latest_jpeg = encoded.tobytes()
                    self._latest_captured_at = time.time()
                    self._error = None

                time.sleep(1 / self.fps)
        finally:
            camera.release()

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._error = message


class HotkeyListener:
    """pynput GlobalHotKeys -> asyncio bridge (research §Pattern 10).

    Registers ``cfg.hotkey`` (default ``<ctrl>+<alt>+j``) and routes presses
    to :meth:`JarvisAssistant._on_hotkey_triggered` via ``call_soon_threadsafe``.
    The pynput listener runs on its own background thread and MUST NOT
    touch any asyncio primitive directly — that would race the loop thread.
    """

    def __init__(self, assistant: "JarvisAssistant", hotkey_str: str) -> None:
        self.assistant = assistant
        self._hotkey_str = hotkey_str
        self._hotkey: kb.GlobalHotKeys | None = None

    def start(self) -> None:
        try:
            self._hotkey = kb.GlobalHotKeys(
                {self._hotkey_str: self._on_hotkey_pressed}
            )
            self._hotkey.start()
        except Exception as exc:
            print(
                f"[hotkey] failed to register {self._hotkey_str}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            self._hotkey = None

    def stop(self) -> None:
        if self._hotkey is not None:
            try:
                self._hotkey.stop()
            except Exception:
                pass
            self._hotkey = None

    def _on_hotkey_pressed(self) -> None:
        loop = self.assistant._loop
        if loop is None or not loop.is_running():
            return
        try:
            loop.call_soon_threadsafe(self.assistant._on_hotkey_triggered)
        except RuntimeError:
            # Loop closed mid-press; drop silently.
            pass


class JarvisAssistant:
    """Phase 1 Jarvis assistant.

    Two construction modes:

    - **Voice-first** (``preloaded`` is provided): owns the asyncio worker
      loop, wake stream, hotkey listener, two-stage gate, and TTS chain.
      Used by ``src/jarvis.py``'s :func:`main`.
    - **CLI / dev** (``preloaded=None``): skips every Phase 1 voice
      component (no openWakeWord, no Kokoro, no Piper preload). Only the
      brain dispatch + ``record_microphone`` + pyttsx3 ``speak`` are
      available. Used by ``src/jarvis_cli.py``.

    Both modes share the same brain dispatch methods (``ask_text`` /
    ``ask_with_image`` / ``ask_ollama`` / ``ask_with_camera``) and the
    pyttsx3 ``speak`` fallback so changing brain behavior in one entry
    point affects both.
    """

    def __init__(
        self,
        cfg: Config | None = None,
        preloaded: PreloadedModels | None = None,
    ) -> None:
        # Allow legacy zero-arg construction for backwards compat — load
        # cfg lazily if not provided. The CLI passes cfg explicitly.
        if cfg is None:
            load_dotenv()
            cfg = load_config()
        self.cfg = cfg

        self.provider = cfg.provider
        if self.provider not in {"openai", "ollama"}:
            raise RuntimeError("ASSISTANT_PROVIDER must be 'openai' or 'ollama'.")
        if self.provider == "openai" and not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError(
                "ASSISTANT_PROVIDER is 'openai' but OPENAI_API_KEY is not set."
            )

        self.client = OpenAI() if os.getenv("OPENAI_API_KEY") else None
        self.model = cfg.openai_model
        self.transcribe_model = os.getenv(
            "OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"
        )
        self.tts_model = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
        self.voice = os.getenv("JARVIS_VOICE", "verse")
        self.ollama_url = cfg.ollama_url
        self.ollama_model = cfg.ollama_model
        self.ollama_keep_alive = cfg.ollama_keep_alive
        self.ollama_num_ctx = cfg.ollama_num_ctx
        self.ollama_num_predict = cfg.ollama_num_predict
        self.local_stt_enabled = cfg.local_stt_enabled
        self.local_whisper_model_name = cfg.whisper_model
        self.local_whisper_device = cfg.whisper_device
        self.local_whisper_compute_type = cfg.whisper_compute_type
        self._local_whisper = None
        self.always_see = cfg.always_see
        self.camera_index = cfg.camera_index
        self.camera_fps = cfg.camera_fps
        self.vision = ContinuousVision(self.camera_index, self.camera_fps)
        self.previous_response_id: str | None = None
        # self.history retired (D-12) — SQLite turns table is the single source of truth
        self.local_tts = pyttsx3.init()
        self._configure_local_tts()

        if self.always_see:
            self.vision.start()

        # ----- Phase 1 voice-loop wiring -----
        # Populated only when running in voice-first mode (preloaded != None).
        # The asyncio Event/Queue must be created INSIDE the loop thread
        # (research Pitfall 8), so they stay None until _run_loop sets them.
        self.preloaded = preloaded
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._worker: threading.Thread | None = None
        self.tts_playing: asyncio.Event | None = None
        self._turn_q: asyncio.Queue | None = None
        self._wake_stream: WakeWordStream | None = None
        self._gate: TwoStageGate | None = None
        self._vad_rec: VadRecorder | None = None
        self._piper_ack: PiperAck | None = None
        self._fallback_tts: FallbackTTS | None = None
        self._wake_log: WakeLog | None = None
        self._hotkey: HotkeyListener | None = None
        self._last_wake_score: float = 0.0

        # ----- Phase 2 tool framework wiring -----
        self._popen_registry = PopenRegistry()
        self._abort_controller = AbortController(self._popen_registry)
        db_path = cfg.localappdata_dir / "jarvis.db"
        self._audit_log = AuditLog(db_path)
        self._brain = Brain(cfg, self.client)

        # Phase 4: persistent memory
        self._session_id = str(uuid.uuid4())
        if preloaded is not None and hasattr(preloaded, 'embedder') and preloaded.embedder is not None:
            self._memory = MemoryStore(cfg.memory_db_path, preloaded.embedder)
        else:
            # CLI mode or no embedder — try to create MemoryStore with lazy load
            try:
                from sentence_transformers import SentenceTransformer
                _embedder = SentenceTransformer(cfg.memory_embedding_model)
                self._memory = MemoryStore(cfg.memory_db_path, _embedder)
            except Exception:
                self._memory = None

        # Inject shared instances into tools that need them
        set_popen_registry(self._popen_registry)
        set_searxng_url(cfg.searxng_url)
        if self._memory is not None:
            set_memory_store(self._memory)

        # CloudTTS for OpenAI provider (D-01, D-04)
        self._cloud_tts: CloudTTS | None = None
        if self.client and cfg.provider == "openai":
            self._cloud_tts = CloudTTS(
                self.client,
                model=self.tts_model,
                voice=self.voice,
            )

        if preloaded is not None:
            # Voice-first mode — construct the audio classes immediately so
            # they're ready when start_voice_loop() spins up the worker.
            # The asyncio Event/Queue still wait until _run_loop runs.
            self._wake_log = WakeLog(cfg.wake_log_path)
            self._vad_rec = VadRecorder(cfg, preloaded.vad_model)
            self._piper_ack = PiperAck(cfg, preloaded.piper_voice)
            self._fallback_tts = FallbackTTS(
                cfg, preloaded.kokoro, self._piper_ack, self.local_tts
            )
            self._gate = TwoStageGate(
                cfg, self._vad_rec, preloaded.whisper, self._wake_log
            )

    # ------------------------------------------------------------------
    # Voice-loop lifecycle (asyncio worker + wake stream + hotkey)
    # ------------------------------------------------------------------

    def start_voice_loop(self) -> None:
        """Start the asyncio worker thread, wake stream, and hotkey listener.

        Voice-first mode only. Blocks until the worker loop is alive on the
        background thread, then registers the wake stream's bridge callback
        and the global hotkey.
        """
        if self.preloaded is None:
            raise RuntimeError(
                "start_voice_loop requires JarvisAssistant(cfg, preloaded=...)."
            )
        self._worker = threading.Thread(
            target=self._run_loop, daemon=True, name="jarvis-loop"
        )
        self._worker.start()
        self._loop_ready.wait()  # block until _run_loop sets self._loop

        # The wake stream and hotkey listener both bridge into self._loop,
        # so they MUST be constructed AFTER the loop exists.
        self._wake_stream = WakeWordStream(
            self.cfg,
            self.preloaded.oww,
            on_wake=self._on_wake_detected,
            loop=self._loop,
        )
        self._wake_stream.start()
        self._hotkey = HotkeyListener(self, self.cfg.hotkey)
        self._hotkey.start()

    def _run_loop(self) -> None:
        """Worker thread entry point: own the asyncio event loop end-to-end."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        # PITFALL 8: Event and Queue MUST be created on the loop thread,
        # NOT in __init__ (which runs on the main thread).
        self.tts_playing = asyncio.Event()
        self._turn_q = asyncio.Queue(maxsize=1)
        self._loop_ready.set()
        try:
            self._loop.run_until_complete(self._async_main())
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    async def _async_main(self) -> None:
        """Top-level loop coroutine: drain the turn queue forever."""
        while True:
            source = await self._turn_q.get()
            if source == "quit":
                return
            try:
                # Create a child task for the turn so abort can cancel it
                turn_task = asyncio.create_task(self._turn_pipeline(source))
                self._abort_controller.set_current_turn(turn_task)
                await turn_task
            except asyncio.CancelledError:
                # Abort fired — silently end the turn (D-06)
                pass
            except Exception as exc:
                # Top-of-pipeline catch — single place we mop up turn errors
                # so the loop keeps running.
                print(f"[turn] error: {exc}", file=sys.stderr, flush=True)
            finally:
                self._abort_controller.clear_current_turn()

    def _on_wake_detected(self, score: float) -> None:
        """Wake-stream bridge callback. Runs on the asyncio loop thread.

        Called via ``call_soon_threadsafe`` from the PortAudio callback in
        :class:`WakeWordStream`. Implements VOICE-04 (D-12): drop wake
        events while ``tts_playing`` is set, log them as ``suppressed_tts``.
        """
        self._last_wake_score = score
        if self.tts_playing is not None and self.tts_playing.is_set():
            if self._wake_log is not None:
                self._wake_log.log_wake("suppressed_tts", score, "")
            return
        if self._turn_q is None:
            return
        if self._turn_q.full():
            # A turn is already in flight; drop the new wake.
            return
        self._turn_q.put_nowait("wake")

    def _on_hotkey_triggered(self) -> None:
        """Context-dependent hotkey: idle=start turn, busy=cancel turn (D-05)."""
        if self._abort_controller.is_busy:
            # ABORT path (D-06: silent abort with log)
            import sounddevice as sd
            self._abort_controller.abort(self.tts_playing, sd.stop)
            if self._wake_log is not None:
                self._wake_log.log_wake("abort_hotkey", 1.0, "")
        else:
            # START path (existing behavior)
            if self.tts_playing is not None and self.tts_playing.is_set():
                return
            if self._turn_q is None:
                return
            if self._turn_q.full():
                return
            self._turn_q.put_nowait("hotkey")

    async def _turn_pipeline(self, source: str) -> None:
        """One full turn: gate? -> ack? -> record -> brain -> speak.

        ``source`` is ``"wake"`` (came from openWakeWord) or ``"hotkey"``
        (came from the global hotkey, bypasses the gate).

        Per-stage timing logs are printed with the ``[turn +X.XXs]`` prefix
        so the user can decompose end-to-end latency into its components
        (gate vs whisper vs brain vs TTS). This is the observability we
        need to make real latency decisions — see 01-LATENCY-RESEARCH.md.
        """
        loop = asyncio.get_running_loop()
        user_text: str | None = None

        t0 = time.monotonic()

        def log_t(stage: str) -> None:
            print(f"[turn +{time.monotonic() - t0:5.2f}s] {stage}", flush=True)

        log_t(f"start  source={source}")

        if source == "wake":
            # Run the two-stage gate. process_wake() returns
            # (text, decision) where decision is one of:
            #   "reject_gate"        - gate rejected; abort silently
            #   "accept_gate_inline" - inline command in gate audio; use it
            #   "accept_gate"        - need ack + fresh recording
            text, decision = await loop.run_in_executor(
                None, self._gate.process_wake, self._last_wake_score
            )
            log_t(f"gate   decision={decision}")
            if decision == "reject_gate":
                return
            if decision == "accept_gate_inline":
                user_text = text  # already have the command
            # else decision == "accept_gate" — fall through, fresh capture below
        else:
            # Hotkey path — log it and proceed straight to ack + record.
            if self._wake_log is not None:
                self._wake_log.log_wake("accept_hotkey", 1.0, "")
            log_t("gate   skipped (hotkey)")

        # Ack + fresh recording (skipped if we already have inline user_text).
        if user_text is None:
            await loop.run_in_executor(None, self._piper_ack.play_ack)
            log_t("ack    played")
            audio = await loop.run_in_executor(
                None, self._vad_rec.record_until_end
            )
            log_t(f"record samples={len(audio) if audio is not None else 0}")
            if audio is None or len(audio) == 0:
                return
            user_text = await loop.run_in_executor(
                None, self._whisper_transcribe_array, audio
            )
            log_t(f"stt    text={(user_text or '')[:40]!r}")

        if not user_text or not user_text.strip():
            return

        print(f"[user] {user_text}", flush=True)

        # Store user turn in memory DB
        if self._memory:
            self._memory.store_turn("user", user_text, self._session_id)

        # ----- Brain + Tool-Call Loop (BRAIN-06: cap N=8, duplicate detection) -----
        turn_id = str(uuid.uuid4())
        tools_schema = all_schemas() if discover_tools() else None
        messages = self._build_messages(user_text)
        # If vision attached, include image in user message
        if self.always_see:
            image_url = self.vision.latest_image_data_url()
            if image_url:
                messages[-1] = {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }

        MAX_TOOL_CALLS = 8
        seen_hashes: set[str] = set()
        reply_text = ""

        for iteration in range(MAX_TOOL_CALLS + 1):
            resp = await loop.run_in_executor(None, self._brain.ask, messages, tools_schema)
            log_t(f"brain  iter={iteration} tools={bool(resp.tool_calls)}")

            if not resp.tool_calls:
                reply_text = resp.text
                break

            # Append assistant message with tool_calls
            assistant_msg: dict = {"role": "assistant", "content": resp.text or ""}
            if self.cfg.provider == "openai":
                assistant_msg["tool_calls"] = [
                    {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                    for tc in resp.tool_calls
                ]
            else:
                assistant_msg["tool_calls"] = [
                    {"function": {"name": tc.name, "arguments": tc.arguments}}
                    for tc in resp.tool_calls
                ]
            messages.append(assistant_msg)

            for tc in resp.tool_calls:
                # Duplicate detection (BRAIN-06)
                call_hash = hashlib.md5(
                    f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True)}".encode()
                ).hexdigest()

                if call_hash in seen_hashes:
                    result = f"[Duplicate call -- you already called {tc.name} with these arguments.]"
                else:
                    seen_hashes.add(call_hash)
                    # Audit log BEFORE execution (SAFE-02)
                    tier = get_tier(tc.name)
                    t_start = time.monotonic()
                    audit_id = self._audit_log.insert_pending(turn_id, tc.name, tier, tc.arguments)
                    # Execute tool
                    result = await loop.run_in_executor(None, call_tool, tc.name, tc.arguments)
                    duration_ms = int((time.monotonic() - t_start) * 1000)
                    self._audit_log.update_result(audit_id, result, duration_ms)

                # Image result detection (ACT-PC-05: vision-as-tool)
                is_image = result.startswith("data:image/")

                if is_image:
                    # Screenshots are our own output — no untrusted_content wrapping.
                    # Neither OpenAI nor Ollama support image arrays on role:"tool"
                    # messages reliably. The pattern that works for both providers:
                    #   1. Add a text-only tool result to satisfy the protocol
                    #   2. Inject a follow-up user message carrying the actual image
                    if self.cfg.provider == "openai":
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": "Screenshot captured. See the image below.",
                        })
                        messages.append({
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Here is the screenshot. Describe what you see:"},
                                {"type": "image_url", "image_url": {"url": result}},
                            ],
                        })
                    else:
                        # Ollama: images field on a user message
                        messages.append({"role": "tool", "content": "Screenshot captured."})
                        b64_data = result.split(",", 1)[1]  # Strip data:image/jpeg;base64, prefix
                        messages.append({
                            "role": "user",
                            "content": "Here is the screenshot. Describe what you see:",
                            "images": [b64_data],
                        })
                else:
                    # SAFE-06: Wrap in untrusted_content markers (normal text results)
                    wrapped = f'<untrusted_content source="{tc.name}">{result}</untrusted_content>'
                    if self.cfg.provider == "openai":
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": wrapped})
                    else:
                        messages.append({"role": "tool", "content": wrapped})

            log_t(f"tools  executed={len(resp.tool_calls)}")
        else:
            # Loop cap reached — force text reply
            reply_text = resp.text or "I've reached my action limit for this turn."

        if not reply_text:
            reply_text = "(no response)"

        log_t(f"brain  words={len(reply_text.split())}")
        print(f"[jarvis] {reply_text}", flush=True)

        # Store assistant turn in memory DB
        if self._memory and reply_text and reply_text != "(no response)":
            self._memory.store_turn("assistant", reply_text, self._session_id)

        # Speak — D-04: routing pushed into speak layer
        self.tts_playing.set()
        try:
            if self._cloud_tts and self.cfg.provider == "openai":
                await loop.run_in_executor(None, self._cloud_tts.speak, reply_text)
            elif self._fallback_tts:
                await loop.run_in_executor(None, self._fallback_tts.speak, reply_text)
            else:
                await loop.run_in_executor(None, self._speak_local, reply_text)
            log_t("tts    done")
        finally:
            self.tts_playing.clear()
            # D-01: fire-and-forget async extraction after TTS (D-02: only substantive)
            if (self._memory and reply_text and user_text
                    and reply_text != "(no response)"):
                asyncio.ensure_future(self._extract_and_store_facts(user_text, reply_text))

    # ------------------------------------------------------------------
    # Memory-augmented message builder (D-07, D-08, MEMORY-03, MEMORY-04)
    # ------------------------------------------------------------------

    def _build_messages(self, user_text: str) -> list[dict]:
        """Construct messages with memory-augmented system prompt."""
        if self._memory is None:
            # Fallback: no memory available
            return [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ]

        # Block 1: Profile facts (always present, ~500 tok max) — MEMORY-03
        profile_facts = self._memory.get_profile_facts()
        profile_block = ""
        if profile_facts:
            lines: list[str] = []
            tok_count = 0
            for f in profile_facts:
                line = f"- {f['key']}: {f['value']}"
                line_tokens = self._estimate_tokens(line)
                if tok_count + line_tokens > self.cfg.memory_profile_max_tokens:
                    break
                lines.append(line)
                tok_count += line_tokens
            if lines:
                profile_block = "## What you know about the user\n" + "\n".join(lines)

        # Block 2: Semantic recall (per-turn, remaining budget) — MEMORY-04
        profile_tokens = self._estimate_tokens(profile_block) if profile_block else 0
        remaining = self.cfg.memory_total_max_tokens - profile_tokens
        recall_max = min(remaining, self.cfg.memory_recall_max_tokens)

        recall_block = ""
        if recall_max > 50:  # Only bother if meaningful budget remains
            recalled = self._memory.recall_similar(user_text, k=self.cfg.memory_top_k)
            if recalled:
                lines = []
                tok_count = 0
                for r in recalled:
                    # MEMORY-05: tag uncertain results
                    confidence = "" if r.get("confident", True) else " (uncertain)"
                    ts = r.get("ts", "")[:10]  # date only
                    content = r.get("content") or r.get("value", "")
                    line = f"[{ts}]{confidence} {content}"
                    line_tokens = self._estimate_tokens(line)
                    if tok_count + line_tokens > recall_max:
                        break
                    lines.append(line)
                    tok_count += line_tokens
                if lines:
                    recall_block = "## Relevant prior context\n" + "\n".join(lines)

        # Compose system prompt
        extended_system = SYSTEM_PROMPT
        if profile_block:
            extended_system += "\n\n" + profile_block
        if recall_block:
            extended_system += "\n\n" + recall_block

        messages: list[dict] = [{"role": "system", "content": extended_system}]

        # Short-term context: recent turns from DB (replaces self.history) — D-13
        recent = self._memory.get_recent_turns(
            n=self.cfg.memory_recent_turns, session_id=self._session_id
        )
        messages.extend(recent)

        messages.append({"role": "user", "content": user_text})
        return messages

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Word-count * 1.3 approximation (per research)."""
        return int(len(text.split()) * 1.3) if text else 0

    # ------------------------------------------------------------------
    # Async fact extraction (D-01, D-02)
    # ------------------------------------------------------------------

    async def _extract_and_store_facts(self, user_text: str, reply_text: str) -> None:
        """Background fact extraction. Best-effort, never crashes the loop."""
        try:
            loop = asyncio.get_event_loop()
            messages = [
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": f"User said: {user_text}\nAssistant replied: {reply_text}"},
            ]
            resp = await loop.run_in_executor(None, self._brain.ask, messages, None)
            text = resp.text.strip()
            # Handle markdown-wrapped JSON
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            facts = json.loads(text)
            if not isinstance(facts, list):
                return
            for fact in facts:
                if not all(k in fact for k in ("type", "key", "value")):
                    continue
                supersedes_key = fact.get("supersedes_key")
                self._memory.upsert_fact(
                    fact["type"], fact["key"], fact["value"],
                    "auto", supersedes_key
                )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).debug(f"Fact extraction failed: {exc}")

    # ------------------------------------------------------------------
    # Whisper transcription
    # ------------------------------------------------------------------

    def _whisper_transcribe_array(self, audio: np.ndarray) -> str:
        """In-memory faster-whisper transcribe for the voice-first pipeline.

        Mirrors :meth:`_transcribe_local` but takes a numpy float32 array
        instead of a Path — PITFALLS.md §C1: never write voice audio to disk.

        Anti-hallucination configuration (same flags as the TwoStageGate
        transcribe in src/audio_in.py — see fc8f9c6): vad_filter=True drops
        near-silent regions before the decoder sees them, no_speech_threshold
        bails if whisper's own no-speech probability is high, and
        condition_on_previous_text=False breaks the known hallucination
        cascade where silence becomes fabricated plausible English.

        This matters for the post-ack fresh-recording path — if the user
        said just "Jarvis" and then went silent, the fresh recording is
        near-silent and whisper WILL hallucinate without these flags.
        """
        if self.preloaded is None or self.preloaded.whisper is None:
            return ""
        if audio is None or len(audio) == 0:
            return ""
        try:
            segments, _info = self.preloaded.whisper.transcribe(
                audio,
                language="en",
                beam_size=1,
                vad_filter=True,
                no_speech_threshold=0.6,
                condition_on_previous_text=False,
            )
            return "".join(seg.text for seg in segments).strip()
        except Exception as exc:
            print(f"[whisper] error: {exc}", file=sys.stderr, flush=True)
            return ""

    def _speak_local(self, text: str) -> None:
        """pyttsx3 local TTS fallback (used when no FallbackTTS or CloudTTS)."""
        self.local_tts.say(text)
        self.local_tts.runAndWait()

    async def _enqueue_quit(self) -> None:
        if self._turn_q is not None:
            await self._turn_q.put("quit")

    def close(self) -> None:
        """Stop every background thread cleanly. Idempotent.

        Order matters: stop the hotkey listener first (so no new turns get
        queued), then the wake stream (same reason), then drain the asyncio
        loop with a "quit" sentinel, then stop ContinuousVision.
        """
        if self._hotkey is not None:
            try:
                self._hotkey.stop()
            except Exception:
                pass
        if self._wake_stream is not None:
            try:
                self._wake_stream.stop()
            except Exception:
                pass
        if (
            self._loop is not None
            and self._loop.is_running()
            and self._turn_q is not None
        ):
            try:
                asyncio.run_coroutine_threadsafe(
                    self._enqueue_quit(), self._loop
                )
            except Exception:
                pass
            if self._worker is not None:
                self._worker.join(timeout=5)
        if self._memory:
            self._memory.close()
        self._audit_log.close()
        self.vision.stop()

    # ------------------------------------------------------------------
    # Brain dispatch — preserved from the prototype (used by both modes)
    # ------------------------------------------------------------------

    def ask_text(self, prompt: str) -> str:
        if self.always_see:
            image_data_url = self.vision.wait_for_image_data_url()
            if image_data_url:
                return self.ask_with_image(prompt, image_data_url)

        if self.provider == "ollama":
            return self.ask_ollama(prompt)

        request = {
            "model": self.model,
            "instructions": SYSTEM_PROMPT,
            "input": prompt,
        }
        if self.previous_response_id:
            request["previous_response_id"] = self.previous_response_id

        response = self.client.responses.create(
            **request,
        )
        self.previous_response_id = response.id
        return response.output_text.strip()

    def ask_with_camera(self, prompt: str) -> str:
        image_data_url = self.vision.wait_for_image_data_url()
        if not image_data_url:
            image_data_url = self.capture_camera_frame()
        return self.ask_with_image(prompt, image_data_url)

    def ask_with_image(self, prompt: str, image_data_url: str) -> str:
        if self.provider == "ollama":
            return self.ask_ollama(prompt, image_data_url)

        request = {
            "model": self.model,
            "instructions": SYSTEM_PROMPT,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": image_data_url},
                    ],
                }
            ],
        }
        if self.previous_response_id:
            request["previous_response_id"] = self.previous_response_id

        response = self.client.responses.create(
            **request,
        )
        self.previous_response_id = response.id
        return response.output_text.strip()

    def ask_ollama(self, prompt: str, image_data_url: str | None = None) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        # D-12: self.history retired; recent turns loaded from DB when available
        if self._memory:
            messages.extend(self._memory.get_recent_turns(n=self.cfg.memory_recent_turns))

        user_message: dict[str, object] = {"role": "user", "content": prompt}
        if image_data_url:
            user_message["images"] = [_extract_base64_from_data_url(image_data_url)]
        messages.append(user_message)

        response = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.ollama_model,
                "messages": messages,
                "stream": False,
                "keep_alive": self.ollama_keep_alive,
                "options": {
                    "num_ctx": self.ollama_num_ctx,
                    "num_predict": self.ollama_num_predict,
                },
            },
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        reply = data["message"]["content"].strip()

        # D-12: store turns in DB instead of in-memory history
        if self._memory:
            self._memory.store_turn("user", prompt, self._session_id)
            self._memory.store_turn("assistant", reply, self._session_id)
        return reply

    # ------------------------------------------------------------------
    # CLI plumbing — used by src/jarvis_cli.py m/c keys
    # ------------------------------------------------------------------

    def record_microphone(self) -> Path:
        print(f"Recording for {RECORD_SECONDS} seconds...")
        samples = sd.rec(
            int(RECORD_SECONDS * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype=np.int16,
        )
        sd.wait()

        path = Path(tempfile.gettempdir()) / "jarvis_microphone.wav"
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(samples.tobytes())
        return path

    def transcribe(self, audio_path: Path) -> str:
        if self.local_stt_enabled:
            try:
                return self._transcribe_local(audio_path)
            except ImportError as exc:
                if not self.client:
                    raise RuntimeError(
                        "Local transcription needs faster-whisper. "
                        "Install with: pip install faster-whisper"
                    ) from exc
                print(f"Local whisper unavailable ({exc}); falling back to OpenAI.")

        if not self.client:
            raise RuntimeError(
                "Microphone transcription requires faster-whisper (local) "
                "or a valid OPENAI_API_KEY."
            )
        with audio_path.open("rb") as audio_file:
            transcript = self.client.audio.transcriptions.create(
                model=self.transcribe_model,
                file=audio_file,
            )
        return transcript.text.strip()

    def _transcribe_local(self, audio_path: Path) -> str:
        model = self._get_local_whisper()
        language = os.getenv("JARVIS_STT_LANGUAGE") or None
        segments, _info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=1,
            vad_filter=True,
        )
        return "".join(segment.text for segment in segments).strip()

    def _get_local_whisper(self):
        if self._local_whisper is None:
            from faster_whisper import WhisperModel

            print(
                f"Loading local Whisper model '{self.local_whisper_model_name}' "
                f"on {self.local_whisper_device} "
                f"({self.local_whisper_compute_type})..."
            )
            self._local_whisper = WhisperModel(
                self.local_whisper_model_name,
                device=self.local_whisper_device,
                compute_type=self.local_whisper_compute_type,
            )
            print("Local Whisper ready.")
        return self._local_whisper

    def speak(self, text: str) -> None:
        """CLI-mode speak — uses pyttsx3/SAPI (the legacy path).

        The voice-first loop does NOT call this; it calls
        ``self._fallback_tts.speak()`` (Kokoro -> Piper -> SAPI chain) via
        the asyncio executor in ``_turn_pipeline``. This method is kept
        for ``src/jarvis_cli.py`` only.
        """
        if self.provider == "ollama" or not self.client:
            self.local_tts.say(text)
            self.local_tts.runAndWait()
            return

        speech_path = Path(tempfile.gettempdir()) / "jarvis_reply.wav"
        with self.client.audio.speech.with_streaming_response.create(
            model=self.tts_model,
            voice=self.voice,
            input=text,
            response_format="wav",
        ) as response:
            response.stream_to_file(speech_path)
        self.play_wav(speech_path)

    def play_wav(self, path: Path) -> None:
        with wave.open(str(path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())

        audio = np.frombuffer(frames, dtype=np.int16)
        if channels > 1:
            audio = audio.reshape(-1, channels)
        sd.play(audio, samplerate=sample_rate)
        sd.wait()

    def _configure_local_tts(self) -> None:
        voices = self.local_tts.getProperty("voices")
        if not voices:
            return

        preferred_keywords = ["english", "en_", "en-", "gb", "uk", "british", "daniel"]
        ranked = []
        for voice in voices:
            languages = []
            for language in getattr(voice, "languages", []) or []:
                if isinstance(language, bytes):
                    languages.append(language.decode("utf-8", errors="ignore"))
                else:
                    languages.append(str(language))
            haystack = " ".join(
                [
                    getattr(voice, "name", "") or "",
                    getattr(voice, "id", "") or "",
                    " ".join(languages),
                ]
            ).lower()
            score = sum(keyword in haystack for keyword in preferred_keywords)
            ranked.append((score, voice))

        ranked.sort(key=lambda item: item[0], reverse=True)
        self.local_tts.setProperty("voice", ranked[0][1].id)
        if platform.system() == "Darwin":
            self.local_tts.setProperty("rate", 185)
        else:
            self.local_tts.setProperty("rate", 175)

    def capture_camera_frame(self) -> str:
        camera = cv2.VideoCapture(self.camera_index)
        try:
            if not camera.isOpened():
                raise RuntimeError("Could not open the webcam.")

            ok, frame = camera.read()
            if not ok:
                raise RuntimeError("Could not read a frame from the webcam.")

            ok, encoded = cv2.imencode(".jpg", frame)
            if not ok:
                raise RuntimeError("Could not encode the webcam frame.")

            b64_image = base64.b64encode(encoded.tobytes()).decode("ascii")
            return f"data:image/jpeg;base64,{b64_image}"
        finally:
            camera.release()
