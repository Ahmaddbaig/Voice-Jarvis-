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
import re
import sys
import threading
import wave
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

from jarvis.core.config import Config


# ---------------------------------------------------------------------------
# Sentence splitter (D-13, PERF-04)
# ---------------------------------------------------------------------------

_ABBREV_RE = re.compile(
    r'\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|approx|incl)\.\s*$'
)


_SENTENCE_SPLIT_RE = re.compile(
    r'(?<=[.!?])\s+'
)


def _is_real_sentence_boundary(text_before: str) -> bool:
    """Return True unless *text_before* ends with a known abbreviation.

    Decimals (e.g. "3.14") don't need special handling here because the split
    regex requires whitespace after the punctuation -- "3.14" mid-number has no
    trailing whitespace so won't trigger a split. "3.14. Next" IS a real
    sentence boundary (the period ends the sentence, not the decimal).
    """
    if _ABBREV_RE.search(text_before):
        return False
    return True


def split_sentences(text: str) -> list[str]:
    """Split text into sentences, respecting abbreviations and decimals."""
    text = text.strip()
    if not text:
        return []
    # Split on sentence-ending punctuation followed by whitespace, then
    # re-merge splits that were actually abbreviations or decimals.
    raw_parts = _SENTENCE_SPLIT_RE.split(text)
    merged: list[str] = []
    for part in raw_parts:
        if merged and not _is_real_sentence_boundary(merged[-1]):
            # Previous "split" was a false positive — re-join
            merged[-1] = merged[-1] + " " + part
        else:
            merged.append(part)
    return [p.strip() for p in merged if p.strip()]


# ---------------------------------------------------------------------------
# Crossfade utility (D-14, PERF-04)
# ---------------------------------------------------------------------------


def crossfade(a: np.ndarray, b: np.ndarray, overlap_samples: int) -> np.ndarray:
    """Linear crossfade between two 1D float32 audio arrays.

    30ms default at 24kHz = 720 samples. Output length = len(a) + len(b) - overlap_samples.
    """
    if overlap_samples <= 0 or len(a) < overlap_samples or len(b) < overlap_samples:
        return np.concatenate([a, b])
    fade_out = np.linspace(1.0, 0.0, overlap_samples, dtype=np.float32)
    fade_in = np.linspace(0.0, 1.0, overlap_samples, dtype=np.float32)
    overlap = a[-overlap_samples:] * fade_out + b[:overlap_samples] * fade_in
    return np.concatenate([a[:-overlap_samples], overlap, b[overlap_samples:]])


# ---------------------------------------------------------------------------
# Fast-ack phrase pool (D-10, PERF-05)
# ---------------------------------------------------------------------------

FAST_ACK_PHRASES = [
    "Certainly, sir.",
    "Right away, sir.",
    "One moment, sir.",
    "Working on it, sir.",
    "On it, sir.",
]


def play_cancellable(
    audio: np.ndarray,
    sr: int,
    cancel: threading.Event,
    chunk_ms: int = 50,
) -> bool:
    """Play audio with cancellation support via sd.OutputStream (D-03).

    Returns True if playback completed, False if cancelled or errored.
    Audio is written in small chunks (~50ms) with the cancel event checked
    between each write, giving ~50ms cancellation latency.
    """
    if audio.ndim == 1:
        audio = audio.reshape(-1, 1)
    chunk_samples = int(sr * chunk_ms / 1000)

    stream = sd.OutputStream(
        samplerate=sr, channels=audio.shape[1], dtype=audio.dtype
    )
    stream.start()
    try:
        offset = 0
        while offset < len(audio):
            if cancel.is_set():
                stream.abort()
                return False
            end = min(offset + chunk_samples, len(audio))
            stream.write(audio[offset:end])
            offset = end
        stream.stop()
        return True
    except Exception:
        stream.abort()
        return False
    finally:
        stream.close()


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
        # Fast-ack phrase pool (D-10, PERF-05): pre-synthesize at startup
        self._fast_ack_pool: list[tuple[np.ndarray, int]] = []
        self._cache_fast_ack_pool()

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

    def play_ack(self, cancel: threading.Event | None = None) -> None:
        """Play the pre-cached ack blob via cancellable OutputStream (D-03).

        Uses :func:`play_cancellable` so barge-in / abort can stop playback
        within ~50ms. Catches and logs any PortAudio / playback errors so a
        flaky output device cannot crash the loop.
        """
        if self._cached_ack is None:
            return
        try:
            play_cancellable(
                self._cached_ack,
                self._cached_sr,
                cancel or threading.Event(),
            )
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

    def _cache_fast_ack_pool(self) -> None:
        """Pre-synthesize the fast-ack phrase pool at startup (D-10, PERF-05)."""
        for phrase in FAST_ACK_PHRASES:
            try:
                audio, sr = self.synthesize(phrase)
                self._fast_ack_pool.append((audio, sr))
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[TTS] fast-ack cache failed for {phrase!r}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )

    @property
    def fast_ack_pool(self) -> list[tuple[np.ndarray, int]]:
        """Return the pre-synthesized fast-ack phrase pool."""
        return self._fast_ack_pool


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

    def speak(self, text: str, cancel: threading.Event | None = None) -> None:
        """Speak ``text`` using the first working backend in the chain.

        Empty / whitespace input is a no-op. Each backend is wrapped in its
        own try/except so a failure cleanly falls through to the next tier.
        ``speak()`` itself never raises — the voice loop must keep running
        even if every TTS backend is dead.

        When *cancel* is set, playback stops within ~50ms (D-03).
        """
        if not text or not text.strip():
            return

        _cancel = cancel or threading.Event()

        # Tier 1: Kokoro bm_george (primary)
        if self._kokoro is not None and not self._kokoro_broken:
            try:
                for _gs, _ps, audio in self._kokoro(
                    text,
                    voice=self._cfg.tts_voice,
                    speed=1.0,
                    split_pattern=r"\n+",
                ):
                    if not play_cancellable(audio, 24_000, _cancel):
                        return  # cancelled
                return
            except Exception as exc:  # noqa: BLE001 — fall through to next tier
                self._kokoro_broken = True
                self._log_degradation("kokoro", exc)

        # Tier 2: Piper on-demand (synthesize each reply fresh — no cache)
        if self._piper_ack is not None and not self._piper_broken:
            try:
                audio, sr = self._piper_ack.synthesize(text)
                if not play_cancellable(audio, sr, _cancel):
                    return  # cancelled
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

    def speak_streaming(
        self,
        text: str,
        cancel: threading.Event | None = None,
        crossfade_ms: int = 30,
    ) -> None:
        """Sentence-by-sentence Kokoro synthesis with crossfade (PERF-04).

        Only uses Kokoro. If Kokoro is broken or unavailable, falls back to
        :meth:`speak` which handles the Piper/SAPI chain. CloudTTS and Piper
        don't use this -- CloudTTS streams natively, Piper is short enough
        that streaming isn't needed (D-15).

        For single-sentence replies, delegates to :meth:`speak` (no streaming
        benefit). For multi-sentence replies, synthesizes each sentence with
        ``split_pattern=None`` and plays with a linear crossfade at boundaries.
        """
        if not text or not text.strip():
            return
        if self._kokoro is None or self._kokoro_broken:
            self.speak(text, cancel)
            return

        _cancel = cancel or threading.Event()
        sentences = split_sentences(text)
        if len(sentences) <= 1:
            self.speak(text, cancel)
            return

        sr = 24_000
        overlap_samples = int(sr * crossfade_ms / 1000)  # 30ms = 720 samples
        chunk_samples = int(sr * 50 / 1000)  # 50ms = 1200 samples

        stream = sd.OutputStream(samplerate=sr, channels=1, dtype="float32")
        stream.start()
        try:
            prev_tail: np.ndarray | None = None  # last overlap_samples of prev sentence

            for sentence in sentences:
                if _cancel.is_set():
                    stream.abort()
                    return

                # Synthesize one sentence with split_pattern=None (D-13, Pitfall 6).
                # KPipeline may yield multiple chunks per sentence if it exceeds
                # 510 phonemes internally, so concatenate all chunks first.
                sentence_chunks: list[np.ndarray] = []
                try:
                    for _gs, _ps, audio in self._kokoro(
                        sentence,
                        voice=self._cfg.tts_voice,
                        speed=1.0,
                        split_pattern=None,
                    ):
                        if _cancel.is_set():
                            stream.abort()
                            return
                        sentence_chunks.append(audio)
                except Exception as exc:
                    self._kokoro_broken = True
                    self._log_degradation("kokoro_streaming", exc)
                    stream.abort()
                    remaining = " ".join(sentences[sentences.index(sentence):])
                    self.speak(remaining, cancel)
                    return

                if not sentence_chunks:
                    continue

                sentence_audio = (
                    np.concatenate(sentence_chunks)
                    if len(sentence_chunks) > 1
                    else sentence_chunks[0]
                )

                # --- Crossfade logic (Research Pattern 3) ---
                # For each sentence:
                #   1. Crossfade prev_tail with sentence start (if prev_tail exists)
                #   2. Play everything except the last overlap_samples
                #   3. Save the last overlap_samples as prev_tail for next iteration

                if prev_tail is not None and len(sentence_audio) >= overlap_samples:
                    # Crossfade prev_tail with start of this sentence
                    xfaded = crossfade(prev_tail, sentence_audio[:overlap_samples], overlap_samples)
                    # Play: crossfaded region + middle (up to last overlap_samples)
                    if len(sentence_audio) > overlap_samples * 2:
                        play_audio = np.concatenate([
                            xfaded,
                            sentence_audio[overlap_samples:-overlap_samples],
                        ])
                    else:
                        # Sentence shorter than 2x overlap -- just play crossfade
                        play_audio = xfaded
                    # Save new tail
                    prev_tail = sentence_audio[-overlap_samples:].copy()
                elif prev_tail is not None:
                    # Sentence too short for crossfade -- concatenate directly
                    play_audio = np.concatenate([prev_tail, sentence_audio])
                    prev_tail = None
                else:
                    # First sentence: play everything except last overlap_samples
                    if len(sentence_audio) > overlap_samples:
                        play_audio = sentence_audio[:-overlap_samples]
                        prev_tail = sentence_audio[-overlap_samples:].copy()
                    else:
                        play_audio = sentence_audio
                        prev_tail = None

                # Write in small chunks, checking cancel between each (Pitfall 1)
                offset = 0
                while offset < len(play_audio):
                    if _cancel.is_set():
                        stream.abort()
                        return
                    end = min(offset + chunk_samples, len(play_audio))
                    stream.write(play_audio[offset:end].reshape(-1, 1))
                    offset = end

            # Play any remaining tail after the last sentence
            if prev_tail is not None:
                stream.write(prev_tail.reshape(-1, 1))

            stream.stop()  # drain remaining buffers
        except Exception as exc:
            self._log_degradation("kokoro_streaming", exc)
            try:
                stream.abort()
            except Exception:
                pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

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

    def speak(self, text: str, cancel: threading.Event | None = None) -> None:
        """Stream TTS audio directly to speakers with cancel support (D-03).

        When *cancel* is set, playback aborts immediately without draining.
        """
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
                    if cancel and cancel.is_set():
                        stream.abort()
                        return
                    audio_data = np.frombuffer(chunk, dtype=np.int16)
                    stream.write(audio_data)
                stream.stop()
            except Exception:
                stream.abort()
            finally:
                stream.close()
