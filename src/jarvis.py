from __future__ import annotations

import base64
import os
import platform
import re
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


SAMPLE_RATE = 16_000
RECORD_SECONDS = 5
DEFAULT_CAMERA_INDEX = 0
DEFAULT_CAMERA_FPS = 2.0

SYSTEM_PROMPT = """
You are a private, capable desktop assistant.
Speak with calm precision, dry wit when appropriate, and short answers by default.
Do not claim to be JARVIS, Tony Stark's assistant, or any real actor.
If the user asks for the movie voice, explain briefly that you can use a polished
British-style assistant voice but cannot clone or impersonate the exact voice.
When using camera input, describe only what is visible and say when you are unsure.
"""


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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


class JarvisAssistant:
    def __init__(self) -> None:
        load_dotenv()
        self.provider = os.getenv("ASSISTANT_PROVIDER", "ollama").strip().lower()
        if self.provider not in {"openai", "ollama"}:
            raise RuntimeError("ASSISTANT_PROVIDER must be 'openai' or 'ollama'.")
        if self.provider == "openai" and not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError(
                "ASSISTANT_PROVIDER is 'openai' but OPENAI_API_KEY is not set."
            )

        self.client = OpenAI() if os.getenv("OPENAI_API_KEY") else None
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.4")
        self.transcribe_model = os.getenv(
            "OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"
        )
        self.tts_model = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
        self.voice = os.getenv("JARVIS_VOICE", "verse")
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "gemma3:4b")
        self.ollama_keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "5m")
        self.always_see = _env_flag("JARVIS_ALWAYS_SEE", default=True)
        self.camera_index = int(os.getenv("JARVIS_CAMERA_INDEX", DEFAULT_CAMERA_INDEX))
        self.camera_fps = float(os.getenv("JARVIS_CAMERA_FPS", DEFAULT_CAMERA_FPS))
        self.vision = ContinuousVision(self.camera_index, self.camera_fps)
        self.previous_response_id: str | None = None
        self.history: list[dict[str, object]] = []
        self.local_tts = pyttsx3.init()
        self._configure_local_tts()

        if self.always_see:
            self.vision.start()

    def close(self) -> None:
        self.vision.stop()

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
        messages.extend(self.history[-8:])

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
            },
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
        if not self.client:
            raise RuntimeError(
                "Microphone transcription requires OPENAI_API_KEY in this version."
            )
        with audio_path.open("rb") as audio_file:
            transcript = self.client.audio.transcriptions.create(
                model=self.transcribe_model,
                file=audio_file,
            )
        return transcript.text.strip()

    def speak(self, text: str) -> None:
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


def main() -> None:
    assistant = JarvisAssistant()
    time.sleep(0.5)
    print("Jarvis prototype ready.")
    print(f"Provider: {assistant.provider}")
    if assistant.provider == "ollama":
        print(f"Ollama model: {assistant.ollama_model}")
    print(f"Vision: {assistant.vision.status()}")
    print("Type a message, 'm' for microphone, 'c' for camera, 's' for status, or 'q' to quit.")

    try:
        while True:
            try:
                choice = input("\n> ").strip()
                if not choice:
                    continue
                if choice.lower() == "q":
                    break
                if choice.lower() == "s":
                    if assistant.provider == "ollama":
                        print(f"Provider: {assistant.provider} ({assistant.ollama_model})")
                    else:
                        print(f"Provider: {assistant.provider} ({assistant.model})")
                    print(f"Vision: {assistant.vision.status()}")
                    continue

                if choice.lower() == "m":
                    audio_path = assistant.record_microphone()
                    prompt = assistant.transcribe(audio_path)
                    print(f"You said: {prompt}")
                    if not prompt:
                        print("I did not catch that.")
                        continue
                    reply = assistant.ask_text(prompt)
                elif choice.lower() == "c":
                    prompt = input("Ask about the camera view: ").strip()
                    if not prompt:
                        prompt = "What do you see?"
                    reply = assistant.ask_with_camera(prompt)
                else:
                    reply = assistant.ask_text(choice)

                print(f"\nAssistant: {reply}")
                assistant.speak(reply)
            except Exception as exc:
                print(f"Error: {exc}")
    except KeyboardInterrupt:
        pass
    finally:
        assistant.close()


if __name__ == "__main__":
    main()
