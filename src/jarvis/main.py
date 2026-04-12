"""Voice-first entry point logic (extracted from old src/jarvis.py)."""

from __future__ import annotations

import time

from jarvis.core.config import load_config
from jarvis.core.preload import preload_all
from jarvis.assistant import JarvisAssistant


def main() -> None:
    """Voice-first launcher.

    Sequence:
      1. load_config() — read .env once into a frozen Config
      2. preload_all(cfg) — espeak-ng probe + warm every voice-loop model
         (espeak-ng failure exits with code 2 here)
      3. JarvisAssistant(cfg, preloaded=models) — wire the audio classes
      4. assistant.start_voice_loop() — start asyncio worker + wake stream + hotkey
      5. block on a main-thread sleep loop until Ctrl+C
      6. assistant.close() — graceful shutdown of every background thread
    """
    cfg = load_config()
    active_model = cfg.openai_model if cfg.provider == "openai" else cfg.ollama_model
    print(
        f"Jarvis voice loop starting (provider={cfg.provider}, "
        f"model={active_model})"
    )
    print(f"  data dir: {cfg.localappdata_dir}")
    print(f"  hotkey:   {cfg.hotkey}")
    print(f"  wake threshold: {cfg.wake_threshold}")
    print()

    # Wave 1 preload — runs verify_espeak_ng_or_exit then constructs every
    # heavy model. First run downloads ~350 MB Kokoro weights from HF.
    models = preload_all(cfg)

    # Construct the assistant in voice-first mode and start the loop.
    assistant = JarvisAssistant(cfg, preloaded=models)
    assistant.start_voice_loop()
    print()
    print("Say 'Jarvis' to activate, or press the hotkey. Ctrl+C to quit.")
    print()

    try:
        # The asyncio loop, wake stream, hotkey listener, and ContinuousVision
        # all run on background threads. The main thread just blocks here
        # until Ctrl+C, leaving room for Phase 5's pystray icon later.
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        assistant.close()
