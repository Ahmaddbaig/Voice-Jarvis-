"""Jarvis CLI â€” preserved push-to-talk REPL.

This is the Phase 1 dev-mode entry point. The voice-first loop lives in
``src/jarvis.py``; this file preserves the original ``m`` / ``c`` / ``s`` /
``q`` REPL behaviour for development and debugging.
"""

from __future__ import annotations

import time

from config import load_config
from jarvis import JarvisAssistant


def main() -> None:
    cfg = load_config()
    assistant = JarvisAssistant(cfg, preloaded=None)
    time.sleep(0.5)
    print("Jarvis CLI ready (push-to-talk REPL).")
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
                if choice.lower() == 'q':
                    break
                if choice.lower() == 's':
                    if assistant.provider == "ollama":
                        print(f"Provider: {assistant.provider} ({assistant.ollama_model})")
                    else:
                        print(f"Provider: {assistant.provider} ({assistant.model})")
                    print(f"Vision: {assistant.vision.status()}")
                    continue
                if choice.lower() == 'm':
                    audio_path = assistant.record_microphone()
                    prompt = assistant.transcribe(audio_path)
                    print(f"You said: {prompt}")
                    if not prompt:
                        print("I did not catch that.")
                        continue
                    reply = assistant.ask_text(prompt)
                elif choice.lower() == 'c':
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
