"""Phase 1 model preloader + espeak-ng probe."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from config import Config

ESPEAK_INSTALL_URL = "https://github.com/espeak-ng/espeak-ng/releases"
ESPEAK_WINGET_CMD = "winget install eSpeak-NG.eSpeak-NG"


def verify_espeak_ng_or_exit() -> None:
    if shutil.which("espeak-ng"):
        return
    canonical_dll = Path(r"C:\Program Files\eSpeak NG\libespeak-ng.dll")
    canonical_exe = Path(r"C:\Program Files\eSpeak NG\espeak-ng.exe")
    if canonical_dll.exists() and canonical_exe.exists():
        os.environ.setdefault("PHONEMIZER_ESPEAK_LIBRARY", str(canonical_dll))
        os.environ.setdefault("PHONEMIZER_ESPEAK_PATH", str(canonical_exe))
        return
    if os.environ.get("PHONEMIZER_ESPEAK_LIBRARY"):
        lib = Path(os.environ["PHONEMIZER_ESPEAK_LIBRARY"])
        if lib.exists():
            return
    sys.stderr.write("\n" + "=" * 72 + "\n" + "FATAL: espeak-ng not found. Kokoro TTS cannot start without it.\n\n" + f"Install via:\n    {ESPEAK_WINGET_CMD}\n\n" + "Or download the MSI from:\n" + f"    {ESPEAK_INSTALL_URL}\n\n" + "After installing, restart Jarvis.\n" + "=" * 72 + "\n")
    sys.exit(2)


@dataclass
class PreloadedModels:
    oww: object
    vad_model: object
    whisper: object
    kokoro: object
    piper_voice: object


def preload_all(cfg: Config) -> PreloadedModels:
    import time
    print("Loading voice-loop models...", flush=True)
    verify_espeak_ng_or_exit()
    from openwakeword.model import Model as OwwModel
    import numpy as np
    oww = OwwModel(wakeword_models=[str(cfg.wake_model_path)], inference_framework="onnx", enable_speex_noise_suppression=False)
    oww.predict(np.zeros(1280, dtype=np.int16))
    from silero_vad import load_silero_vad
    vad_model = load_silero_vad(onnx=True)
    from faster_whisper import WhisperModel
    whisper = WhisperModel(cfg.whisper_model, device=cfg.whisper_device, compute_type=cfg.whisper_compute_type)
    _seg, _info = whisper.transcribe(np.zeros(16_000, dtype=np.float32))
    list(_seg)
    from kokoro import KPipeline
    kokoro_pipe = KPipeline(lang_code=cfg.kokoro_lang_code)
    for _ in kokoro_pipe("ready", voice=cfg.tts_voice):
        pass
    piper_onnx = cfg.piper_voice_dir / f"{cfg.piper_voice_name}.onnx"
    piper_cfg = cfg.piper_voice_dir / f"{cfg.piper_voice_name}.onnx.json"
    if not piper_onnx.exists():
        print(f"    FATAL: Piper voice missing at {piper_onnx}", file=sys.stderr)
        print("    Re-run voice asset download.", file=sys.stderr)
        sys.exit(2)
    from piper import PiperVoice
    piper_voice = PiperVoice.load(model_path=str(piper_onnx), config_path=str(piper_cfg))
    if cfg.provider == "ollama":
        try:
            import requests as _requests
            _requests.post(f"{cfg.ollama_url}/api/generate", json={"model": cfg.ollama_model, "prompt": "hi", "stream": False, "keep_alive": cfg.ollama_keep_alive, "options": {"num_ctx": cfg.ollama_num_ctx, "num_predict": 1}}, timeout=60).raise_for_status()
        except Exception:
            pass
    return PreloadedModels(oww=oww, vad_model=vad_model, whisper=whisper, kokoro=kokoro_pipe, piper_voice=piper_voice)
