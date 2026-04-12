"""Phase 1 audio output pipeline.

Two classes the voice loop calls when it has audio to play:

- :class:`PiperAck` — pre-caches the wake-acknowledgment phrase ("Sir?") as
  an in-memory numpy float32 blob using Piper at construction time, so every
  subsequent ``play_ack()`` is roughly a numpy copy + ``sd.play`` (~5 ms to
  start audio). This is the latency optimization Phase 1 actually ships per
  CONTEXT.md D-03.

- :class:`FallbackTTS` — runs Kokoro ``bm_george`` as the primary voice for
  main replies, with graceful degradation to on-demand Piper synthesis and
  finally to a pyttsx3/SAPI engine if both fail. Per-session "broken" flags
  ensure a single failure does not waste 1-2 s on every subsequent reply.
  This is CONTEXT.md "Claude's Discretion: log degradation, keep loop running."

Both classes are designed to be called from Plan 05's ``_turn_pipeline()``
coroutine via ``loop.run_in_executor`` — they are sync-blocking by design
because every ``sd.play`` call blocks until playback finishes. The caller
(Plan 05) sets its wake-suppression flag before calling ``speak()`` /
``play_ack()`` and clears it after the call returns; that flag's mechanics
live in Plan 05, not here. Plan 04 owns playback only.

Heavy library imports (kokoro, piper, pyttsx3) are deliberately NOT done at
module level — Plan 02's preloader already constructed those instances and
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

from jarvis.core.config import Config


# ---------------------------------------------------------------------------
# PiperAck — pre-cached wake acknowledgment ("Sir?")
# ---------------------------------------------------------------------------


class PiperAck:
    """Pre-caches the wake-acknowledgment phrase as an in-memory numpy blob.

    Synthesizes ``cfg.ack_phrase`` (default ``"Sir?"``) ONCE at construction
    using the supplied :class:`piper.PiperVoice` instance from the Plan 02
    preloader. The audio data and sample rate are stored as instance state
    so :meth:`play_ack` is just a ``sd.play`` of an existing numpy array —
    no synthesis on the hot path.

    Per CONTEXT.md D-03 + research §Pattern 8.

    Also exposes :meth:`synthesize` for the on-demand Piper fallback path
    used by :class:`FallbackTTS` (when Kokoro is broken). That path
    synthesizes fresh — only the ack phrase is cached.
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
        a complete WAV stream (including header — ``set_wav_format=True``
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
        finished before its suppression flag clears — without that the
        wake word could re-trigger mid-playback. Catches and logs any
        PortAudio / playback errors so a flaky output device cannot crash
        the loop.
        """
        if self._cached_ack is None:
            return
        try:
            sd.play(self._cached_ack, samplerate=self._cached_sr, blocking=True)
        except Exception as exc:  # noqa: BLE001 — playback must never crash the loop
            print(f"[TTS] PiperAck play error: {exc}", file=sys.stderr, flush=True)

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Synthesize ``text`` fresh — used by FallbackTTS as the on-demand
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
# FallbackTTS — Kokoro -> Piper -> pyttsx3 chain
# ---------------------------------------------------------------------------


class FallbackTTS:
    """Kokoro -> Piper -> pyttsx3 graceful-degradation chain for main replies.

    Tier 1: Kokoro ``bm_george`` (primary, CONTEXT.md D-06). Iterates the
            KPipeline generator and plays each chunk at 24 kHz.
    Tier 2: Piper on-demand via :meth:`PiperAck.synthesize`. Hit only when
            Kokoro has failed in this session.
    Tier 3: pyttsx3 SAPI engine. Last-ditch — preserves voice output even
            if both ONNX backends are broken.

    Per-session ``_kokoro_broken`` / ``_piper_broken`` flags ensure that a
    single failure does NOT keep retrying for the rest of the session
    (each retry burns another 1-2 s). Reset only on process restart.

    Per CONTEXT.md Claude's Discretion + research §Pattern 9.
    """

    def __init__(
        self,
        cfg: Config,
        kokoro,
        piper_ack: "PiperAck",
        sapi,
    ) -> None:
        self._cfg = cfg
        self._kokoro = kokoro          # kokoro.KPipeline (already warmed)
        self._piper_ack = piper_ack    # used for on-demand Piper fallback
        self._sapi = sapi              # pyttsx3 engine (or None)
        self._kokoro_broken = False
        self._piper_broken = False

    def speak(self, text: str) -> None:
        """Speak ``text`` using the first working backend in the chain.

        Empty / whitespace input is a no-op. Each backend is wrapped in its
        own try/except so a failure cleanly falls through to the next tier.
        ``speak()`` itself never raises — the voice loop must keep running
        even if every TTS backend is dead.
        """
        if not text or not text.strip():
            return

        # Tier 1: Kokoro bm_george (primary)
        if self._kokoro is not None and not self._kokoro_broken:
            try:
                # KPipeline returns a generator yielding (graphemes, phonemes,
                # audio) per sentence. MUST iterate to actually trigger
                # phonemize+synthesize — calling self._kokoro(...) alone is
                # lazy and synthesizes nothing.
                for _gs, _ps, audio in self._kokoro(
                    text,
                    voice=self._cfg.tts_voice,
                    speed=1.0,
                    split_pattern=r"\n+",
                ):
                    sd.play(audio, samplerate=24_000, blocking=True)
                return
            except Exception as exc:  # noqa: BLE001 — fall through to next tier
                self._kokoro_broken = True
                self._log_degradation("kokoro", exc)

        # Tier 2: Piper on-demand (synthesize each reply fresh — no cache)
        if self._piper_ack is not None and not self._piper_broken:
            try:
                audio, sr = self._piper_ack.synthesize(text)
                sd.play(audio, samplerate=sr, blocking=True)
                return
            except Exception as exc:  # noqa: BLE001 — fall through to next tier
                self._piper_broken = True
                self._log_degradation("piper", exc)

        # Tier 3: SAPI / pyttsx3 (last ditch)
        if self._sapi is not None:
            try:
                self._sapi.say(text)
                self._sapi.runAndWait()
                return
            except Exception as exc:  # noqa: BLE001 — total failure path below
                self._log_degradation("sapi", exc)

        # Total failure — log and continue. Do NOT raise; the loop must
        # keep running so the user can still issue commands and read text
        # replies in the terminal.
        self._log_degradation("all", RuntimeError("all TTS backends failed"))

    def _log_degradation(self, backend: str, exc: BaseException) -> None:
        """Log a backend failure to stderr.

        Phase 1 just prints; in Phase 5 this becomes a structured component
        health write. Today the user just needs to see what fell over.
        """
        print(f"[TTS] {backend} failed: {exc}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# CloudTTS — streaming OpenAI TTS (Phase 2)
# ---------------------------------------------------------------------------


class CloudTTS:
    """Streaming OpenAI TTS — plays PCM audio directly as it arrives.

    D-01: Streaming OpenAI TTS for provider=openai.
    D-03: Voice configured via JARVIS_VOICE env var (default 'verse').
    D-04: speak() is the single method — pipeline doesn't know which backend.

    PCM format: 24kHz, 16-bit signed LE, mono. No WAV header.
    """

    SAMPLE_RATE = 24000
    CHANNELS = 1

    def __init__(self, client, model: str = "gpt-4o-mini-tts", voice: str = "verse"):
        self.client = client
        self.model = model
        self.voice = voice

    def speak(self, text: str) -> None:
        """Stream TTS audio directly to speakers. Blocking call."""
        import numpy as np
        import sounddevice as sd

        with self.client.audio.speech.with_streaming_response.create(
            model=self.model,
            voice=self.voice,
            input=text,
            response_format="pcm",
        ) as response:
            stream = sd.OutputStream(
                samplerate=self.SAMPLE_RATE,
                channels=self.CHANNELS,
                dtype="int16",
            )
            stream.start()
            try:
                for chunk in response.iter_bytes(chunk_size=4096):
                    audio_data = np.frombuffer(chunk, dtype=np.int16)
                    stream.write(audio_data)
            finally:
                stream.stop()
                stream.close()
