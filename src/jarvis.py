from __future__ import annotations

import base64
import os
import tempfile
import wave
from pathlib import Path

import cv2
import numpy as np
import sounddevice as sd
from dotenv import load_dotenv
from openai import OpenAI


SAMPLE_RATE = 16_000
RECORD_SECONDS = 5

SYSTEM_PROMPT = """
You are a private, capable desktop assistant.
Speak with calm precision, dry wit when appropriate, and short answers by default.
Do not claim to be JARVIS, Tony Stark's assistant, or any real actor.
If the user asks for the movie voice, explain briefly that you can use a polished
British-style assistant voice but cannot clone or impersonate the exact voice.
When using camera input, describe only what is visible and say when you are unsure.
"""


class JarvisAssistant:
    def __init__(self) -> None:
        load_dotenv()
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("Set OPENAI_API_KEY in .env before running.")

        self.client = OpenAI()
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.4")
        self.transcribe_model = os.getenv(
            "OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"
        )
        self.tts_model = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
        self.voice = os.getenv("JARVIS_VOICE", "verse")
        self.previous_response_id: str | None = None

    def ask_text(self, prompt: str) -> str:
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
        image_data_url = self.capture_camera_frame()
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
        with audio_path.open("rb") as audio_file:
            transcript = self.client.audio.transcriptions.create(
                model=self.transcribe_model,
                file=audio_file,
            )
        return transcript.text.strip()

    def speak(self, text: str) -> None:
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

    def capture_camera_frame(self) -> str:
        camera = cv2.VideoCapture(0)
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
    print("Jarvis prototype ready.")
    print("Type a message, 'm' for microphone, 'c' for camera, or 'q' to quit.")

    while True:
        choice = input("\n> ").strip()
        if not choice:
            continue
        if choice.lower() == "q":
            break

        try:
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
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f"Error: {exc}")


if __name__ == "__main__":
    main()
