"""Phase 1 typed configuration loaded from .env.

Single source of runtime configuration for the voice loop. Replaces the
scattered ``os.getenv`` calls in ``JarvisAssistant.__init__``. Loaded once
at startup via :func:`load_config` and treated as immutable thereafter.

CONTEXT.md D-19: this is the first non-``jarvis.py`` source module. ``src/``
is intentionally not a Python package — there is no ``__init__.py``. Import
as ``from config import Config, load_config`` when ``src/`` is on
``sys.path`` or is the CWD.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Coercion helpers — keep blank ``.env`` keys falling back to defaults.
# ---------------------------------------------------------------------------


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    return int(v) if v is not None and v != "" else default


def _env_float(key: str, default: float) -> float:
    v = os.environ.get(key)
    return float(v) if v is not None and v != "" else default


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(key: str, default: Path) -> Path:
    v = os.environ.get(key)
    return Path(v) if v else default


def _env_duration(key: str, default: str) -> str:
    v = os.environ.get(key)
    if v is None or v == "":
        return default
    value = v.strip()
    if all(ch in "-0123456789" for ch in value):
        return f"{value}m"
    return value


# ---------------------------------------------------------------------------
# Frozen Config dataclass — every Phase 1 tunable lives here.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    # --- Brain (existing) ---
    provider: str = "openai"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:latest"
    # "-1" keeps gemma4 resident forever; avoids the 5-10s cold-load tax every
    # time Ollama's default 5m idle timer ticks over between turns.
    ollama_keep_alive: str = "-1m"
    # Context window pinned explicitly (research: Ollama's default 2048 silently
    # truncates tool schemas and long turns; 4096 is the CPU sweet spot for
    # short voice turns — prefill cost grows super-linearly with num_ctx).
    ollama_num_ctx: int = 4096
    ollama_num_ctx_tools: int = 16384
    # Hard ceiling on generated tokens per turn. Gemma is chatty; this is the
    # brake. Pair with the terse system prompt in src/jarvis.py for short replies.
    ollama_num_predict: int = 80
    openai_model: str = "gpt-5.4"
    searxng_url: str = "http://localhost:8888"
    eval_models: str = "gemma4:latest,qwen3:4b,qwen3:14b"
    # --- STT (existing) ---
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    local_stt_enabled: bool = True
    # --- Vision (existing) ---
    # OFF by default: attaching a webcam frame to every Ollama request costs
    # 40-130s of CPU prompt prefill per turn (per 01-LATENCY-RESEARCH.md).
    # Use the CLI REPL's `c` key for explicit camera questions instead.
    always_see: bool = False
    camera_index: int = 0
    camera_fps: float = 2.0
    # --- Phase 1 NEW: wake word ---
    wake_model_path: Path = field(default_factory=lambda: Path())
    wake_threshold: float = 0.70
    wake_log_path: Path = field(default_factory=lambda: Path())
    # --- Phase 1 NEW: VAD ---
    vad_trailing_silence_ms: int = 700
    vad_min_speech_ms: int = 250
    vad_max_utterance_s: int = 30
    # --- Phase 1 NEW: TTS ---
    tts_voice: str = "bm_george"
    kokoro_lang_code: str = "b"  # British English
    piper_voice_dir: Path = field(default_factory=lambda: Path("models/piper"))
    piper_voice_name: str = "en_GB-alan-medium"
    ack_phrase: str = "Sir?"
    # --- Phase 1 NEW: input device + hotkey ---
    input_device: str | None = None
    hotkey: str = "<ctrl>+<alt>+j"
    # --- Phase 1 NEW: runtime data dir ---
    localappdata_dir: Path = field(default_factory=lambda: Path())


# ---------------------------------------------------------------------------
# Factory — read .env, compute paths, return a fully-populated Config.
# ---------------------------------------------------------------------------


def load_config() -> Config:
    """Load environment variables and return a frozen :class:`Config`.

    - Reads ``.env`` via python-dotenv (no-op if already loaded).
    - Ensures ``%LOCALAPPDATA%\\Jarvis\\logs\\`` exists.
    - Resolves the openWakeWord default model path lazily so importing
      ``config`` itself stays cheap (Plan 03 may import this module without
      paying for the openwakeword load).
    """
    load_dotenv()

    localappdata = Path(os.environ["LOCALAPPDATA"]) / "Jarvis"
    (localappdata / "logs").mkdir(parents=True, exist_ok=True)

    # Project root = parent of src/ (this file lives in src/jarvis/core/config.py).
    # .parent = core/, .parent.parent = jarvis/, .parent.parent.parent = src/,
    # .parent.parent.parent.parent = project root.
    project_root = Path(__file__).resolve().parent.parent.parent.parent

    # Lazy import — keep ``from config import Config`` cheap.
    import openwakeword  # noqa: WPS433 (intentional local import)

    owww_models = Path(openwakeword.__file__).parent / "resources" / "models"

    # Resolve piper voice dir against project root if it's a relative path,
    # so ``models/piper`` works whether the user runs from project root or src/.
    piper_dir_default = project_root / "models" / "piper"
    piper_dir_env = os.environ.get("JARVIS_PIPER_VOICE_DIR")
    if piper_dir_env:
        piper_dir_path = Path(piper_dir_env)
        if not piper_dir_path.is_absolute():
            piper_dir_path = project_root / piper_dir_path
    else:
        piper_dir_path = piper_dir_default

    return Config(
        provider=_env_str("ASSISTANT_PROVIDER", "openai").lower(),
        ollama_url=_env_str("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=_env_str("OLLAMA_MODEL", "gemma4:latest"),
        ollama_keep_alive=_env_duration("OLLAMA_KEEP_ALIVE", "-1m"),
        ollama_num_ctx=_env_int("OLLAMA_NUM_CTX", 4096),
        ollama_num_ctx_tools=_env_int("OLLAMA_NUM_CTX_TOOLS", 16384),
        ollama_num_predict=_env_int("OLLAMA_NUM_PREDICT", 80),
        openai_model=_env_str("OPENAI_MODEL", "gpt-5.4"),
        searxng_url=_env_str("SEARXNG_URL", "http://localhost:8888").rstrip("/"),
        eval_models=_env_str("JARVIS_EVAL_MODELS", "gemma4:latest,qwen3:4b,qwen3:14b"),
        whisper_model=_env_str("JARVIS_WHISPER_MODEL", "base"),
        whisper_device=_env_str("JARVIS_WHISPER_DEVICE", "cpu"),
        whisper_compute_type=_env_str("JARVIS_WHISPER_COMPUTE_TYPE", "int8"),
        local_stt_enabled=_env_bool("JARVIS_LOCAL_STT", True),
        always_see=_env_bool("JARVIS_ALWAYS_SEE", False),
        camera_index=_env_int("JARVIS_CAMERA_INDEX", 0),
        camera_fps=_env_float("JARVIS_CAMERA_FPS", 2.0),
        wake_model_path=_env_path(
            "JARVIS_WAKE_MODEL", owww_models / "hey_jarvis_v0.1.onnx"
        ),
        wake_threshold=_env_float("JARVIS_WAKE_THRESHOLD", 0.70),
        wake_log_path=_env_path(
            "JARVIS_WAKE_LOG", localappdata / "logs" / "wake.log"
        ),
        vad_trailing_silence_ms=_env_int("JARVIS_VAD_SILENCE_MS", 700),
        vad_min_speech_ms=_env_int("JARVIS_VAD_MIN_SPEECH_MS", 250),
        vad_max_utterance_s=_env_int("JARVIS_VAD_MAX_S", 30),
        tts_voice=_env_str("JARVIS_TTS_VOICE", "bm_george"),
        kokoro_lang_code=_env_str("JARVIS_KOKORO_LANG", "b"),
        piper_voice_dir=piper_dir_path,
        piper_voice_name=_env_str("JARVIS_PIPER_VOICE_NAME", "en_GB-alan-medium"),
        ack_phrase=_env_str("JARVIS_ACK_PHRASE", "Sir?"),
        input_device=(_env_str("JARVIS_INPUT_DEVICE", "") or None),
        hotkey=_env_str("JARVIS_HOTKEY", "<ctrl>+<alt>+j"),
        localappdata_dir=localappdata,
    )
