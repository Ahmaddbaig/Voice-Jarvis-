"""Phase 1 audio output pipeline.

Two classes the voice loop calls when it has audio to play:

- :class:`PiperAck` â€” pre-caches the wake-acknowledgment phrase ("Sir?") as
  an in-memory numpy float32 blob using Piper at construction time, so every
  subsequent ``play_ack()`` is roughly a numpy copy + ``sd.play`` (~5 ms to
  start audio). This is the latency optimization Phase 1 actually ships per
  CONTEXT.md D-03.

- :class:`FallbackTTS` â€” runs Kokoro ``bm_george`` as the primary voice for
  main replies, with graceful degradation to on-demand Piper synthesis and
  finally to a pyttsx3/SAPI engine if both fail. Per-session "broken" flags
  ensure a single failure does not waste 1-2 s on every subsequent reply.
  This is CONTEXT.md "Claude's Discretion: log degradation, keep loop running."

Both classes are designed to be called from Plan 05's ``_turn_pipeline()``
coroutine via ``loop.run_in_executor`` â€” they are sync-blocking by design
because every ``sd.play`` call blocks until playback finishes. The caller
(Plan 05) sets its wake-suppression flag before calling ``speak()`` /
``play_ack()`` and clears it after the call returns; that flag's mechanics
live in Plan 05, not here. Plan 04 owns playback only.

Heavy library imports (kokoro, piper, pyttsx3) are deliberately NOT done at
module level â€” Plan 02's preloader already constructed those instances and
passes them in. Importing this module stays cheap.
"""

from __future__ import annotations

import io
import sys
import wave
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

from config import Config


# ---------------------------------------------------------------------------
# PiperAck â€” pre-cached wake acknowledgment ("Sir?")
# ---------------------------------------------------------------------------


class PiperAck:
    """Pre-caches the wake-acknowledgment phrase as an in-memory numpy blob.

    Synthesizes ``cfg.ack_phrase`` (default ``"Sir?"``) ONCE at construction
    using the supplied :class:`piper.PiperVoice` instance from the Plan 02
    preloader. The audio data and sample rate are stored as instance state
    so :meth:`play_ack` is just a ``sd.play`` of an existing numpy array â€”
    no synthesis on the hot path.

    Per CONTEXT.md D-03 + research Â§Pattern 8.

    Also exposes :meth:`synthesize` for the on-demand Piper fallback path
    used by :class:`FallbackTTS` (when Kokoro is broken). That path
    synthesizes fresh â€” only the ack phrase is cached.
    """

    def __init__(self, cfg: Config, piper_voice) -> None:
        self._cfg = cfg
        self._voice = piper_voice  # piper.PiperVoice (already loaded by preload)
        self._cached_ack: Optional[np.ndarray] = None
        self._cached_sr: int = 0
        self._cache_ack(cfg.ack_phrase)

    def _cache_ack(self, text: str) -> None:
        """Synthesize ``text`` once into the in-memory ack cache.

        Piper 1.4.x exposes ``synthesize_wav(text, wav_file)`` which writes
        a complete WAV stream (including header â€” ``set_wav_format=True``
        by default) to a ``wave.Wave_write`` handle. We capture it via
        ``io.BytesIO`` and decode the resulting WAV bytes with ``soundfile``
        to get a float32 numpy array + the sample rate the voice was trained
        at (22050 Hz for en_GB-alan-medium).
        """
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            self._voice.synthesize_wav(text, wav)
        buf.seek(0)
        data, sr = sf.read(buf, dtype="float32")
        self._cached_ack = data
        self._cached_sr = int(sr)

    def play_ack(self) -> None:
        """Play the pre-cached ack blob.

        Uses blocking playback so the caller (Plan 05) knows the audio is
        finished before its suppression flag clears â€” without that the
        wake word could re-trigger mid-playback. Catches and logs any
        PortAudio / playback errors so a flaky output device cannot crash
        the loop.
        """
        if self._cached_ack is None:
            return
        try:
            sd.play(self._cached_ack, samplerate=self._cached_sr, blocking=True)
        except Exception as exc:  # noqa: BLE001 â€” playback must never crash the loop
            print(f"[TTS] PiperAck play error: {exc}", file=sys.stderr, flush=True)

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Synthesize ``text`` fresh â€” used by FallbackTTS as the on-demand
        Piper fallback path for arbitrary replies. NOT cached: this path is
        only hit when Kokoro is broken for the session, so the extra Piper
        latency on every reply is acceptable.
        """
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            self._voice.synthesize_wav(text, wav)
        buf.seek(0)
        data, sr = sf.read(buf, dtype="float32")
        return data, int(sr)


# ---------------------------------------------------------------------------
# FallbackTTS â€” Kokoro -> Piper -> pyttsx3 chain
# ---------------------------------------------------------------------------


class FallbackTTS:
    """Kokoro -> Piper -> pyttsx3 graceful-degradation chain for main replies.

    Tier 1: Kokoro ``bm_george`` (primary, CONTEXT.md D-06). Iterates the
            KPipeline generator and plays each chunk at 24 kHz.
    Tier 2: Piper on-demand via :meth:`PiperAck.synthesize`. Hit only when
            Kokoro has failed in this session.
    Tier 3: pyttsx3 SAPI engine. Last-ditch â€” preserves voice output even
            if both ONNX backends are broken.

    Per-session ``_kokoro_broken`` / ``_piper_broken`` flags ensure that a
    single failure does NOT keep retrying for the rest of the session.
    """

    def __init__(
        self,
        cfg: Config,
        kokoro,
        piper_ack: "PiperAck",
        sapi,
    ) -> None:
        self._cfg = cfg
        self._kokoro = kokoro
        self._piper_ack = piper_ack
        self._sapi = sapi
        self._kokoro_broken = False
        self._piper_broken = False

    def speak(self, text: str) -> None:
        if not text or not text.strip():
            return

        if self._kokoro is not None and not self._kokoro_broken:
            try:
                for _gs, _ps, audio in self._kokoro(
                    text,
                    voice=self._cfg.tts_voice,
                    speed=1.0,
                    split_pattern=r"\n+",
                ):
                    sd.play(audio, samplerate=24_000, blocking=True)
                return
            except Exception as exc:
                self._kokoro_broken = True
                self._log_degradation("kokoro", exc)

        if self._piper_ack is not None and not self._piper_broken:
            try:
                audio, sr = self._piper_ack.synthesize(text)
                sd.play(audio, samplerate=sr, blocking=True)
                return
            except Exception as exc:
                self._piper_broken = True
                self._log_degradation("piper", exc)

        if self._sapi is not None:
            try:
                self._sapi.say(text)
                self._sapi.runAndWait()
                return
            except Exception as exc:
                self._log_degradation("sapi", exc)

        self._log_degradation("all", RuntimeError("all TTS backends failed"))

    def _log_degradation(self, backend: str, exc: BaseException) -> None:
        print(f"[TTS] {backend} failed: {exc}", file=sys.stderr, flush=True)
