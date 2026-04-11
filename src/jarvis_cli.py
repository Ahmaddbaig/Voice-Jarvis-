"""Jarvis CLI — preserved push-to-talk REPL.

This is the Phase 1 dev-mode entry point. The voice-first loop lives in
``src/jarvis.py``; this file preserves the original ``m`` / ``c`` / ``s`` /
``q`` REPL behaviour for development and debugging.

Both entry points share the same :class:`JarvisAssistant` class so changing
brain or vision behaviour in one affects the other. The CLI mode constructs
``JarvisAssistant(cfg, preloaded=None)`` to skip the heavy voice-loop
preload (no openWakeWord, no Kokoro, no Piper download), which keeps the
CLI cold-start fast for iterative development.

CONTEXT.md D-15: "Phase 1 ships two entry points." This is the second.
"""

from __future__ import annotations

import time

from config import load_config
from jarvis import JarvisAssistant


def main() -> None:
    cfg = load_config()
    # CLI mode: skip the heavy voice-loop preload (no wake stream, no Kokoro)
    assistant = JarvisAssistant(cfg, preloaded=None)
    time.sleep(0.5)
    print("Jarvis CLI ready (push-to-talk REPL).")
    print(f"Provider: {assistant.provider}")
    if assistant.provider == "ollama":
        print(f"Ollama model: {assistant.ollama_model}")
    print(f"Vision: {assistant.vision.status()}")
    print(
        "Type a message, 'm' for microphone, 'c' for camera, "
        "'s' for status, or 'q' to quit."
    )

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
                        print(
                            f"Provider: {assistant.provider} "
                            f"({assistant.ollama_model})"
                        )
                    else:
                        print(
                            f"Provider: {assistant.provider} "
                            f"({assistant.model})"
                        )
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
