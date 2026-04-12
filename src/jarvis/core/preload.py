"""Phase 1 model preloader + espeak-ng probe (VOICE-06).

Two responsibilities:

1. :func:`verify_espeak_ng_or_exit` — fail-fast probe that runs BEFORE any
   :class:`kokoro.KPipeline` instantiation. This is the VOICE-06
   implementation. Exits the process with code 2 and a remediation banner if
   espeak-ng cannot be located via any of three probe paths.

2. :func:`preload_all` — constructs and warms every voice-loop heavy model
   (openWakeWord, silero-vad, faster-whisper, Kokoro, Piper) so the first
   user interaction is not delayed by lazy init (PERF-05 foundation).

Heavy library imports happen lazily inside :func:`preload_all` so importing
``preload`` itself stays cheap — Plan 05 may import this module just to
get the :class:`PreloadedModels` type.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from jarvis.core.config import Config


# ---------------------------------------------------------------------------
# VOICE-06: espeak-ng probe (Pattern 7)
# ---------------------------------------------------------------------------

ESPEAK_INSTALL_URL = "https://github.com/espeak-ng/espeak-ng/releases"
ESPEAK_WINGET_CMD = "winget install eSpeak-NG.eSpeak-NG"


def verify_espeak_ng_or_exit() -> None:
    """Phase 1 VOICE-06: fail loudly if espeak-ng is not reachable.

    Probe order:
      1. ``espeak-ng`` on PATH (``shutil.which``)
      2. Canonical Windows install path —
         ``C:\\Program Files\\eSpeak NG\\libespeak-ng.dll`` + ``espeak-ng.exe``
      3. ``PHONEMIZER_ESPEAK_LIBRARY`` env var already set

    On (2) success the function also sets ``PHONEMIZER_ESPEAK_LIBRARY`` and
    ``PHONEMIZER_ESPEAK_PATH`` so Kokoro's phonemizer backend can find the
    DLL even when ``espeak-ng.exe`` is not on PATH (the Windows MSI installer
    historically does not add itself to PATH).

    On total failure: writes a remediation banner to stderr and calls
    ``sys.exit(2)``. This is a hard process exit, NOT an exception — the
    user wants a clean error message, not a Python traceback.
    """
    # 1. PATH probe
    if shutil.which("espeak-ng"):
        return

    # 2. Canonical install path
    canonical_dll = Path(r"C:\Program Files\eSpeak NG\libespeak-ng.dll")
    canonical_exe = Path(r"C:\Program Files\eSpeak NG\espeak-ng.exe")
    if canonical_dll.exists() and canonical_exe.exists():
        os.environ.setdefault("PHONEMIZER_ESPEAK_LIBRARY", str(canonical_dll))
        os.environ.setdefault("PHONEMIZER_ESPEAK_PATH", str(canonical_exe))
        return

    # 3. Pre-set env var
    if os.environ.get("PHONEMIZER_ESPEAK_LIBRARY"):
        lib = Path(os.environ["PHONEMIZER_ESPEAK_LIBRARY"])
        if lib.exists():
            return

    # FAIL LOUDLY — VOICE-06 requirement
    sys.stderr.write(
        "\n" + "=" * 72 + "\n"
        "FATAL: espeak-ng not found. Kokoro TTS cannot start without it.\n\n"
        "Install via:\n"
        f"    {ESPEAK_WINGET_CMD}\n\n"
        "Or download the MSI from:\n"
        f"    {ESPEAK_INSTALL_URL}\n\n"
        "After installing, restart Jarvis.\n"
        + "=" * 72 + "\n"
    )
    sys.exit(2)


# ---------------------------------------------------------------------------
# Container — Plans 03/04/05 read from this bundle.
# ---------------------------------------------------------------------------


@dataclass
class PreloadedModels:
    """Bundle of warm voice-loop models returned by :func:`preload_all`.

    Field types are :class:`object` so importing this module does not force
    importing the heavy libraries themselves. The actual concrete types are:

    - ``oww``: :class:`openwakeword.model.Model`         (Plan 03 consumer)
    - ``vad_model``: :func:`silero_vad.load_silero_vad`  (Plan 03 consumer)
    - ``whisper``: :class:`faster_whisper.WhisperModel`  (Plan 03 consumer)
    - ``kokoro``: :class:`kokoro.KPipeline`              (Plan 04 consumer)
    - ``piper_voice``: :class:`piper.PiperVoice`         (Plan 04 consumer —
        wraps it in a ``PiperAck`` class)

    Not frozen — internal state on these instances is mutated during use
    (e.g. silero VADIterator state in Plan 03).
    """

    oww: object
    vad_model: object
    whisper: object
    kokoro: object
    piper_voice: object


# ---------------------------------------------------------------------------
# preload_all — Pattern 12 + the consolidated example at research lines 945-1010
# ---------------------------------------------------------------------------


def preload_all(cfg: Config) -> PreloadedModels:
    """Construct and warm every voice-loop model.

    Order is load-bearing: the espeak-ng probe MUST run before
    :class:`kokoro.KPipeline` is constructed (VOICE-06). All other heavy
    library imports happen inside this function so module-level imports stay
    cheap.

    First run is slow (~30-60 s) because Kokoro downloads ~350 MB from
    HuggingFace. Subsequent runs reuse the cached weights and complete in
    roughly 6 seconds.
    """
    import time

    started = time.perf_counter()
    print("Loading voice-loop models...", flush=True)

    # [1/6] espeak-ng probe — MUST be first, BEFORE KPipeline construction
    print("  [1/6] Checking espeak-ng...", flush=True)
    verify_espeak_ng_or_exit()

    # [2/6] openWakeWord
    print("  [2/6] openWakeWord...", flush=True)
    if not cfg.wake_model_path.exists():
        try:
            import openwakeword.utils

            openwakeword.utils.download_models()
        except Exception as exc:  # noqa: BLE001 — best-effort fetch
            print(f"    download_models() warning: {exc}", flush=True)
    from openwakeword.model import Model as OwwModel

    oww = OwwModel(
        wakeword_models=[str(cfg.wake_model_path)],
        inference_framework="onnx",  # REQUIRED on Windows (no tflite wheels)
        enable_speex_noise_suppression=False,  # NOT supported on Windows
    )
    import numpy as np

    oww.predict(np.zeros(1280, dtype=np.int16))  # warmup
    keys = list(oww.prediction_buffer.keys())
    print(f"    ready. Model keys: {keys}", flush=True)

    # [3/6] silero-vad (ONNX path — keeps the perf-critical path off torch)
    print("  [3/6] silero-vad (ONNX)...", flush=True)
    from silero_vad import load_silero_vad

    vad_model = load_silero_vad(onnx=True)
    # No VADIterator here — Plan 03 constructs it (the iterator is stateful
    # per recording and belongs to the audio_in module).

    # [4/6] faster-whisper
    print("  [4/6] faster-whisper...", flush=True)
    from faster_whisper import WhisperModel

    whisper = WhisperModel(
        cfg.whisper_model,
        device=cfg.whisper_device,
        compute_type=cfg.whisper_compute_type,
    )
    # Warmup with 1 s of silence at 16 kHz; force the generator
    _seg, _info = whisper.transcribe(np.zeros(16_000, dtype=np.float32))
    list(_seg)

    # [5/6] Kokoro — first run downloads ~350 MB from HuggingFace
    print("  [5/6] Kokoro (first run downloads ~350 MB)...", flush=True)
    from kokoro import KPipeline

    kokoro_pipe = KPipeline(lang_code=cfg.kokoro_lang_code)
    # Warmup synthesis — the generator is lazy, iterate to force phonemize+TTS.
    for _ in kokoro_pipe("ready", voice=cfg.tts_voice):
        pass

    # [6/6] Piper ack voice
    print("  [6/6] Piper ack voice...", flush=True)
    piper_onnx = cfg.piper_voice_dir / f"{cfg.piper_voice_name}.onnx"
    piper_cfg = cfg.piper_voice_dir / f"{cfg.piper_voice_name}.onnx.json"
    if not piper_onnx.exists():
        print(
            f"    FATAL: Piper voice missing at {piper_onnx}",
            file=sys.stderr,
        )
        print(
            "    Re-run Plan 01 Task 3 to download it.",
            file=sys.stderr,
        )
        sys.exit(2)
    from piper import PiperVoice

    piper_voice = PiperVoice.load(
        model_path=str(piper_onnx),
        config_path=str(piper_cfg),
    )

    # [7/7] Warm up Ollama — make gemma resident in RAM with num_ctx pinned
    # so the FIRST real turn doesn't pay the cold-load tax (5-10s on 8B Q4).
    # Best-effort: if Ollama is down, log and continue — Phase 1 startup has
    # already verified Ollama in the preloader's upstream callers.
    if cfg.provider == "ollama":
        print("  [7/7] Warming up Ollama...", flush=True)
        try:
            import requests as _requests

            _requests.post(
                f"{cfg.ollama_url}/api/generate",
                json={
                    "model": cfg.ollama_model,
                    "prompt": "hi",
                    "stream": False,
                    "keep_alive": cfg.ollama_keep_alive,
                    "options": {
                        "num_ctx": cfg.ollama_num_ctx,
                        "num_predict": 1,
                    },
                },
                timeout=60,
            ).raise_for_status()
            print("    ready.", flush=True)
        except Exception as exc:  # noqa: BLE001 — best effort
            print(f"    warning: Ollama warmup failed: {exc}", flush=True)
            print(
                "    first real turn may pay the cold-load tax.",
                flush=True,
            )

    elapsed = time.perf_counter() - started
    print(f"All models loaded in {elapsed:.1f}s.", flush=True)

    return PreloadedModels(
        oww=oww,
        vad_model=vad_model,
        whisper=whisper,
        kokoro=kokoro_pipe,
        piper_voice=piper_voice,
    )
