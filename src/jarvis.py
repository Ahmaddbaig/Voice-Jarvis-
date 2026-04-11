"""Phase 1 Jarvis voice-first entry point.

This file is the voice-first launcher. It owns the asyncio worker thread,
the wake-word stream, the global hotkey listener, and the turn pipeline
coroutine that wires Wave 1/2/3 components together.

The companion file ``src/jarvis_cli.py`` is the preserved push-to-talk REPL
(m/c/s/q keys) for development. Both share the :class:`JarvisAssistant`
class defined here, but the CLI constructs it with ``preloaded=None`` so it
skips the heavy openWakeWord/Kokoro/Piper preload (CONTEXT.md D-15).

ContinuousVision is preserved verbatim from the original prototype â€” it's
already a daemon thread, no asyncio integration needed. Vision is auto-
attached to every text turn via ``ask_text`` (existing behavior).
"""

from __future__ import annotations

import asyncio
import base64
import os
import platform
import re
import sys
import tempfile
import threading
import time
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

from config import Config, load_config
from preload import preload_all, PreloadedModels
from audio_in import WakeWordStream, VadRecorder, TwoStageGate
from audio_out import PiperAck, FallbackTTS
from wake_log import WakeLog


SAMPLE_RATE = 16_000
RECORD_SECONDS = 5
DEFAULT_CAMERA_INDEX = 0
DEFAULT_CAMERA_FPS = 2.0

SYSTEM_PROMPT = """
You are the user's private desktop assistant. You address the user as "sir"
on every turn. Your persona is that of a polished, calm British butler with
a consistent dry undertone.

Answer in ONE short sentence unless the user explicitly asks for detail.
Do not claim to be JARVIS, Tony Stark's assistant, Paul Bettany, or any real
actor. If the user asks for "the movie voice," acknowledge briefly that you
can speak in a polished British style but cannot clone or impersonate a
specific real voice.

When describing what the camera sees, describe only what is visible and
say when you are uncertain.
""".strip()


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
    def __init__(self, assistant: "JarvisAssistant", hotkey_str: str) -> None:
        self.assistant = assistant
        self._hotkey_str = hotkey_str
        self._hotkey: kb.GlobalHotKeys | None = None

    def start(self) -> None:
        try:
            self._hotkey = kb.GlobalHotKeys({self._hotkey_str: self._on_hotkey_pressed})
            self._hotkey.start()
        except Exception as exc:
            print(f"[hotkey] failed to register {self._hotkey_str}: {exc}", file=sys.stderr, flush=True)
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
            pass


class JarvisAssistant:
    def __init__(self, cfg: Config | None = None, preloaded: PreloadedModels | None = None) -> None:
        if cfg is None:
            load_dotenv()
            cfg = load_config()
        self.cfg = cfg
        self.provider = cfg.provider
        if self.provider not in {"openai", "ollama"}:
            raise RuntimeError("ASSISTANT_PROVIDER must be 'openai' or 'ollama'.")
        if self.provider == "openai" and not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("ASSISTANT_PROVIDER is 'openai' but OPENAI_API_KEY is not set.")

        self.client = OpenAI() if os.getenv("OPENAI_API_KEY") else None
        self.model = cfg.openai_model
        self.transcribe_model = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
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
        self.history: list[dict[str, object]] = []
        self.local_tts = pyttsx3.init()
        self._configure_local_tts()

        if self.always_see:
            self.vision.start()

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

        if preloaded is not None:
            self._wake_log = WakeLog(cfg.wake_log_path)
            self._vad_rec = VadRecorder(cfg, preloaded.vad_model)
            self._piper_ack = PiperAck(cfg, preloaded.piper_voice)
            self._fallback_tts = FallbackTTS(cfg, preloaded.kokoro, self._piper_ack, self.local_tts)
            self._gate = TwoStageGate(cfg, self._vad_rec, preloaded.whisper, self._wake_log)

    def start_voice_loop(self) -> None:
        if self.preloaded is None:
            raise RuntimeError("start_voice_loop requires JarvisAssistant(cfg, preloaded=...).")
        self._worker = threading.Thread(target=self._run_loop, daemon=True, name="jarvis-loop")
        self._worker.start()
        self._loop_ready.wait()
        self._wake_stream = WakeWordStream(self.cfg, self.preloaded.oww, on_wake=self._on_wake_detected, loop=self._loop)
        self._wake_stream.start()
        self._hotkey = HotkeyListener(self, self.cfg.hotkey)
        self._hotkey.start()

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
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
        while True:
            source = await self._turn_q.get()
            if source == "quit":
                return
            try:
                await self._turn_pipeline(source)
            except Exception as exc:
                print(f"[turn] error: {exc}", file=sys.stderr, flush=True)

    def _on_wake_detected(self, score: float) -> None:
        self._last_wake_score = score
        if self.tts_playing is not None and self.tts_playing.is_set():
            if self._wake_log is not None:
                self._wake_log.log_wake("suppressed_tts", score, "")
            return
        if self._turn_q is None or self._turn_q.full():
            return
        self._turn_q.put_nowait("wake")

    def _on_hotkey_triggered(self) -> None:
        if self.tts_playing is not None and self.tts_playing.is_set():
            return
        if self._turn_q is None or self._turn_q.full():
            return
        self._turn_q.put_nowait("hotkey")

    async def _turn_pipeline(self, source: str) -> None:
        loop = asyncio.get_running_loop()
        user_text: str | None = None

        if source == "wake":
            text, decision = await loop.run_in_executor(None, self._gate.process_wake, self._last_wake_score)
            if decision == "reject_gate":
                return
            if decision == "accept_gate_inline":
                user_text = text
        else:
            if self._wake_log is not None:
                self._wake_log.log_wake("accept_hotkey", 1.0, "")

        if user_text is None:
            await loop.run_in_executor(None, self._piper_ack.play_ack)
            audio = await loop.run_in_executor(None, self._vad_rec.record_until_end)
            if audio is None or len(audio) == 0:
                return
            user_text = await loop.run_in_executor(None, self._whisper_transcribe_array, audio)

        if not user_text or not user_text.strip():
            return

        reply = await loop.run_in_executor(None, self.ask_text, user_text)
        self.tts_playing.set()
        try:
            await loop.run_in_executor(None, self._fallback_tts.speak, reply)
        finally:
            self.tts_playing.clear()

    def _whisper_transcribe_array(self, audio: np.ndarray) -> str:
        if self.preloaded is None or self.preloaded.whisper is None or audio is None or len(audio) == 0:
            return ""
        try:
            segments, _info = self.preloaded.whisper.transcribe(audio, language="en", beam_size=1, vad_filter=True, no_speech_threshold=0.6, condition_on_previous_text=False)
            return "".join(seg.text for seg in segments).strip()
        except Exception as exc:
            print(f"[whisper] error: {exc}", file=sys.stderr, flush=True)
            return ""

    async def _enqueue_quit(self) -> None:
        if self._turn_q is not None:
            await self._turn_q.put("quit")

    def close(self) -> None:
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
        if self._loop is not None and self._loop.is_running() and self._turn_q is not None:
            try:
                asyncio.run_coroutine_threadsafe(self._enqueue_quit(), self._loop)
            except Exception:
                pass
            if self._worker is not None:
                self._worker.join(timeout=5)
        self.vision.stop()

    def ask_text(self, prompt: str) -> str:
        if self.always_see:
            image_data_url = self.vision.wait_for_image_data_url()
            if image_data_url:
                return self.ask_with_image(prompt, image_data_url)
        if self.provider == "ollama":
            return self.ask_ollama(prompt)
        request = {"model": self.model, "instructions": SYSTEM_PROMPT, "input": prompt}
        if self.previous_response_id:
            request["previous_response_id"] = self.previous_response_id
        response = self.client.responses.create(**request)
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
            "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}, {"type": "input_image", "image_url": image_data_url}]}],
        }
        if self.previous_response_id:
            request["previous_response_id"] = self.previous_response_id
        response = self.client.responses.create(**request)
        self.previous_response_id = response.id
        return response.output_text.strip()

    def ask_ollama(self, prompt: str, image_data_url: str | None = None) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.history[-8:])
        user_message: dict[str, object] = {"role": "user", "content": prompt}
        if image_data_url:
            user_message["images"] = [_extract_base64_from_data_url(image_data_url)]
        messages.append(user_message)
        response = requests.post(
            f"{self.ollama_url}/api/chat",
            json={"model": self.ollama_model, "messages": messages, "stream": False, "keep_alive": self.ollama_keep_alive, "options": {"num_ctx": self.ollama_num_ctx, "num_predict": self.ollama_num_predict}},
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        reply = data["message"]["content"].strip()
        self.history.append({"role": "user", "content": prompt})
        self.history.append({"role": "assistant", "content": reply})
        self.history = self.history[-16:]
        return reply

    def record_microphone(self) -> Path:
        samples = sd.rec(int(RECORD_SECONDS * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype=np.int16)
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
                    raise RuntimeError("Local transcription needs faster-whisper. Install with: pip install faster-whisper") from exc
        if not self.client:
            raise RuntimeError("Microphone transcription requires faster-whisper (local) or a valid OPENAI_API_KEY.")
        with audio_path.open("rb") as audio_file:
            transcript = self.client.audio.transcriptions.create(model=self.transcribe_model, file=audio_file)
        return transcript.text.strip()

    def _transcribe_local(self, audio_path: Path) -> str:
        model = self._get_local_whisper()
        language = os.getenv("JARVIS_STT_LANGUAGE") or None
        segments, _info = model.transcribe(str(audio_path), language=language, beam_size=1, vad_filter=True)
        return "".join(segment.text for segment in segments).strip()

    def _get_local_whisper(self):
        if self._local_whisper is None:
            from faster_whisper import WhisperModel
            self._local_whisper = WhisperModel(self.local_whisper_model_name, device=self.local_whisper_device, compute_type=self.local_whisper_compute_type)
        return self._local_whisper

    def speak(self, text: str) -> None:
        if self.provider == "ollama" or not self.client:
            self.local_tts.say(text)
            self.local_tts.runAndWait()
            return
        speech_path = Path(tempfile.gettempdir()) / "jarvis_reply.wav"
        with self.client.audio.speech.with_streaming_response.create(model=self.tts_model, voice=self.voice, input=text, response_format="wav") as response:
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
            haystack = " ".join([getattr(voice, "name", "") or "", getattr(voice, "id", "") or "", " ".join(languages)]).lower()
            score = sum(keyword in haystack for keyword in preferred_keywords)
            ranked.append((score, voice))
        ranked.sort(key=lambda item: item[0], reverse=True)
        self.local_tts.setProperty("voice", ranked[0][1].id)
        self.local_tts.setProperty("rate", 185 if platform.system() == "Darwin" else 175)

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


def main() -> None:
    cfg = load_config()
    active_model = cfg.openai_model if cfg.provider == "openai" else cfg.ollama_model
    print(f"Jarvis voice loop starting (provider={cfg.provider}, model={active_model})")
    print(f"  data dir: {cfg.localappdata_dir}")
    print(f"  hotkey:   {cfg.hotkey}")
    print(f"  wake threshold: {cfg.wake_threshold}")
    print()
    models = preload_all(cfg)
    assistant = JarvisAssistant(cfg, preloaded=models)
    assistant.start_voice_loop()
    print()
    print("Say 'Jarvis' to activate, or press the hotkey. Ctrl+C to quit.")
    print()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        assistant.close()


if __name__ == "__main__":
    main()
