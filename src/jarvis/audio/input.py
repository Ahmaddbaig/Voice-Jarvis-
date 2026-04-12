"""Phase 1 audio-IN pipeline: wake word + VAD recorder + two-stage gate.

Three classes share this file because they share audio constants and live
on the same call path. Plan 05's ``_turn_pipeline()`` coroutine instantiates
all three at startup and drives them via ``loop.run_in_executor`` (the
methods here are deliberately sync-blocking — only :class:`WakeWordStream`
holds long-lived state, and it bridges the PortAudio thread back to the
asyncio loop via ``loop.call_soon_threadsafe``).

Pipeline shape:

  PortAudio callback (WakeWordStream)
      └── on score >= cfg.wake_threshold
          └── loop.call_soon_threadsafe(on_wake, score)   [bridge to asyncio]
              └── Plan 05's coroutine handler
                  └── TwoStageGate.process_wake(score)    [run_in_executor]
                      ├── VadRecorder.record_until_end()  [VAD-bounded capture]
                      ├── faster-whisper transcribe       [in-memory ndarray]
                      └── _JARVIS_RE first-word check
                          ├── reject  → wake_log + return ("", "reject_gate")
                          ├── inline  → return (after_text, "accept_gate_inline")
                          └── ack     → return (None, "accept_gate")

CONTEXT.md decisions enforced here: D-01 wake word "Jarvis", D-02 threshold
0.70 + two-stage gate, D-04 silent reject (caller decides), D-12 NOT
implemented here (Plan 05 owns the wake-during-TTS suppression flag),
D-18 sync-blocking ``run_in_executor`` shape.

Anti-patterns deliberately avoided (research §Anti-Patterns + Pitfall B/C):

  - No call to ``self._on_wake(score)`` from the PortAudio callback —
    everything bridges via ``loop.call_soon_threadsafe``.
  - No ``enable_speex_noise_suppression=True`` — it's already False in
    Plan 02's preload and would crash on Windows anyway.
  - No ``blocksize`` other than 512 for the silero-vad recorder (silero
    was trained on exactly 512/1024/1536 samples at 16 kHz).
  - No audio written to disk — every numpy buffer stays in memory and is
    handed to faster-whisper directly. PITFALLS.md §C1.
  - No openwakeword.Model construction here — Plan 02's preloader owns it.
"""

from __future__ import annotations

import re
import sys
import time
import asyncio
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from jarvis.core.config import Config


# ---------------------------------------------------------------------------
# Audio constants — load-bearing per Pattern 4 / Pattern 5 of research
# ---------------------------------------------------------------------------

SAMPLE_RATE = 16_000
OWW_CHUNK = 1280   # openWakeWord wants 80 ms chunks at 16 kHz (16000 * 0.080)
VAD_CHUNK = 512    # silero-vad MUST be 512 samples at 16 kHz (32 ms)

# Two-stage gate regex: matches "jarvis", "hey jarvis", "jarviss", "jarves",
# "jarys", etc., case-insensitive, anchored to the start of the transcript.
# Trailing word boundary prevents matching "jarvises" or "jared".
_JARVIS_RE = re.compile(
    r"^\s*(hey[ ,]+)?jarv(is|iss|es|ys)?\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Class 1: WakeWordStream — long-lived openWakeWord listener on PortAudio
# ---------------------------------------------------------------------------


class WakeWordStream:
    """Continuous openWakeWord listener bridging PortAudio → asyncio.

    Holds a long-lived ``sd.InputStream`` that calls ``oww_model.predict()``
    on every 80 ms float32 frame. When the prediction score crosses
    ``cfg.wake_threshold``, schedules ``on_wake(score)`` on the asyncio
    event loop via ``loop.call_soon_threadsafe`` (NEVER calls it directly
    from the PortAudio callback thread).

    The ``on_wake`` callback is provided by Plan 05; this module knows
    nothing about wake-during-TTS suppression — that flag lives on the
    asyncio loop side and is checked inside the callback (D-12).
    """

    def __init__(
        self,
        cfg: Config,
        oww_model,
        on_wake: Callable[[float], None],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._cfg = cfg
        self._oww = oww_model
        self._on_wake = on_wake
        self._loop = loop
        self._input_stream: Optional[sd.InputStream] = None

        # Discover the wake-word key from the preloaded model. For
        # hey_jarvis_v0.1.onnx the key is "hey_jarvis_v0.1" (with
        # underscores and version suffix — verified in Plan 02 SUMMARY).
        # If the model has no buffered keys yet, fall back defensively
        # to the canonical historical name; predict() will populate the
        # buffer on the first call regardless.
        try:
            keys = list(oww_model.prediction_buffer.keys())
        except Exception:  # noqa: BLE001
            keys = []
        if keys:
            self._wake_key = keys[0]
        else:
            self._wake_key = "hey_jarvis_v0.1"

    def start(self) -> None:
        """Open the PortAudio input stream and begin wake-word inference.

        Wraps construction + start in try/except to satisfy CONTEXT.md's
        narrow-graceful-degradation rule (PITFALLS.md §B2 / Pitfall 3): on
        a PortAudio failure, log a warning to stderr and continue. The
        worker loop is NOT crashed — Plan 05 will still respond to the
        global hotkey fallback.
        """
        try:
            self._input_stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=OWW_CHUNK,
                callback=self._callback,
                device=self._cfg.input_device or None,
            )
            self._input_stream.start()
        except sd.PortAudioError as exc:
            sys.stderr.write(
                f"[audio_in] WakeWordStream.start() PortAudioError: {exc}\n"
                "[audio_in] Continuing without wake-word listener; "
                "use the global hotkey to start a turn.\n"
            )
            self._input_stream = None
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(
                f"[audio_in] WakeWordStream.start() failed: {exc}\n"
                "[audio_in] Continuing without wake-word listener; "
                "use the global hotkey to start a turn.\n"
            )
            self._input_stream = None

    def stop(self) -> None:
        """Stop and close the input stream. Idempotent."""
        if self._input_stream is None:
            return
        try:
            self._input_stream.stop()
            self._input_stream.close()
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(
                f"[audio_in] WakeWordStream.stop() warning: {exc}\n"
            )
        finally:
            self._input_stream = None

    # -- internal --

    def _callback(self, indata, frames, time_info, status) -> None:
        """PortAudio thread callback. MUST NOT block, MUST NOT await."""
        if status:
            # XRuns happen on overloaded systems; not fatal.
            return
        try:
            # indata is float32 [-1, 1] per sounddevice docs;
            # openWakeWord wants int16 PCM at 16 kHz.
            pcm16 = (indata[:, 0] * 32767.0).astype(np.int16)
            prediction = self._oww.predict(pcm16)
            score = float(prediction.get(self._wake_key, 0.0))
        except Exception as exc:  # noqa: BLE001
            # Per Pitfall B2: never crash the audio thread.
            sys.stderr.write(
                f"[audio_in] WakeWordStream callback error: {exc}\n"
            )
            return

        if score >= self._cfg.wake_threshold:
            # Bridge to asyncio loop. Do NOT call self._on_wake directly
            # — that would run it on the PortAudio thread, where calling
            # asyncio.Event methods is unsafe (research Pitfall 8).
            try:
                self._loop.call_soon_threadsafe(self._on_wake, score)
            except RuntimeError:
                # Loop is closed (process shutting down); drop the event.
                pass


# ---------------------------------------------------------------------------
# Class 2: VadRecorder — silero-vad-bounded capture into a numpy buffer
# ---------------------------------------------------------------------------


class VadRecorder:
    """VAD-bounded recorder built on silero-vad's :class:`VADIterator`.

    Each call to :meth:`record_until_end` opens a fresh short-lived
    ``sd.InputStream``. Short-lived is deliberate — Pitfall 3: device
    changes (headset plug/unplug, default-device switch) recover naturally
    on the next turn instead of leaving us bound to a stale device.

    The recorder is sync-blocking; Plan 05 calls it via
    ``loop.run_in_executor`` from inside the turn coroutine.
    """

    def __init__(self, cfg: Config, vad_model) -> None:
        self._cfg = cfg
        self._vad_model = vad_model
        # silero-vad's VADIterator wraps the model with a stateful
        # start/end-event detector. Constructed once per VadRecorder
        # instance and reset between recordings via reset_states().
        from silero_vad import VADIterator

        self._vad = VADIterator(
            vad_model,
            threshold=0.5,
            sampling_rate=SAMPLE_RATE,
            min_silence_duration_ms=cfg.vad_trailing_silence_ms,
            speech_pad_ms=200,
        )

    def record_until_end(self) -> np.ndarray:
        """Block until silero-vad signals end-of-speech, return float32 audio.

        Returns ``np.zeros(0, dtype="float32")`` on:
          - device errors (PortAudio): logged to stderr, graceful degradation
          - max-utterance-duration timeout: returns whatever was captured
          - no speech detected: returns the empty buffer

        The returned array is mono float32 at 16 kHz, suitable for direct
        feeding to ``faster_whisper.WhisperModel.transcribe(audio_array)``.
        """
        max_duration_s = float(self._cfg.vad_max_utterance_s)
        buf: list[np.ndarray] = []
        started = False
        start_time = time.monotonic()

        try:
            self._vad.reset_states()
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=VAD_CHUNK,
                device=self._cfg.input_device or None,
            ) as stream:
                while True:
                    chunk, _overflow = stream.read(VAD_CHUNK)
                    chunk = chunk[:, 0]
                    event = self._vad(chunk)
                    if event and "start" in event:
                        started = True
                    if started:
                        buf.append(chunk.copy())
                    if event and "end" in event:
                        break
                    if time.monotonic() - start_time > max_duration_s:
                        break
        except sd.PortAudioError as exc:
            sys.stderr.write(
                f"[audio_in] VadRecorder PortAudioError: {exc}\n"
                "[audio_in] Returning empty buffer; turn will be aborted.\n"
            )
            return np.zeros(0, dtype="float32")
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(
                f"[audio_in] VadRecorder error: {exc}\n"
                "[audio_in] Returning empty buffer; turn will be aborted.\n"
            )
            return np.zeros(0, dtype="float32")

        if not buf:
            return np.zeros(0, dtype="float32")
        return np.concatenate(buf).astype(np.float32, copy=False)


# ---------------------------------------------------------------------------
# Class 3: TwoStageGate — wake → VAD → whisper → regex confirm
# ---------------------------------------------------------------------------


class TwoStageGate:
    """Post-wake confirmation: VAD-bounded capture + whisper + regex check.

    The gate runs after every wake fire. It performs a single VAD-bounded
    capture, transcribes it locally with faster-whisper (in-memory only —
    PITFALLS.md §C1), and applies the ``_JARVIS_RE`` regex to the first
    word of the transcript.

    Three outcomes (CONTEXT.md D-02 + research §Pattern 3 optimization):

      - **reject_gate** — first word is not "jarvis". Returns ``("", ...)``;
        Plan 05 should silently abort the turn (D-04). Logged with the
        first 6 words of what was actually said for tuning.
      - **accept_gate_inline** — first word IS "jarvis" AND there are >=4
        words after the wake word. The user spoke their command in the
        gate audio, so we skip the second recording entirely and feed
        the post-wake-word text straight to the brain. Saves ~1 s.
      - **accept_gate** — first word IS "jarvis" but the transcript is
        just "jarvis" / "jarvis?" / a couple of words. Plan 05 will play
        the Piper "Sir?" ack and start a fresh VAD-bounded recording.
    """

    def __init__(
        self,
        cfg: Config,
        vad_recorder: VadRecorder,
        whisper_model,
        wake_log,
    ) -> None:
        self._cfg = cfg
        self._vad_recorder = vad_recorder
        self._whisper = whisper_model
        self._wake_log = wake_log

    def process_wake(self, score: float) -> tuple[Optional[str], str]:
        """Run the gate flow for one wake event.

        :param score: openWakeWord confidence score that triggered the wake.
        :returns: ``(user_text, decision)`` where ``decision`` is one of
            ``"reject_gate"``, ``"accept_gate_inline"``, ``"accept_gate"``,
            and ``user_text`` is:

              - ``""`` for ``reject_gate`` (caller aborts the turn)
              - the post-wake-word command text for ``accept_gate_inline``
              - ``None`` for ``accept_gate`` (caller plays ack + records fresh)
        """
        # 1. VAD-bounded capture
        gate_audio = self._vad_recorder.record_until_end()

        # 2. Reject obviously-too-short captures (no speech / mic glitch)
        min_samples = self._cfg.vad_min_speech_ms * (SAMPLE_RATE // 1000)
        if len(gate_audio) < min_samples:
            self._wake_log.log_wake("reject_gate", score, "(too short)")
            return ("", "reject_gate")

        # 3. Transcribe in-memory (never on disk — PITFALLS.md C1)
        gate_transcript = self._whisper_transcribe_array(gate_audio)

        # 4. Content-based decision (trust the wake-word engine for positive
        # detection; rely on whisper + the vad_filter anti-hallucination flags
        # for silence rejection). The old "first word must be jarvis" regex
        # was broken because the post-wake capture starts AFTER the wake word
        # is already over — whisper never sees "jarvis" in the captured audio.
        #
        # Strip any stray "jarvis" / "hey jarvis" whisper echoes from the
        # transcript, then count the remaining substantive words:
        #
        #   - 0 words (silence or just-the-wake-word) → accept_gate:
        #     Plan 05 plays the Piper "Sir?" ack and records a fresh utterance
        #   - 1 word (fragment)                       → accept_gate:
        #     same as above — too short to be a real command
        #   - >= 2 words                              → accept_gate_inline:
        #     user spoke a command inline; skip the ack, send straight to brain
        cleaned = re.sub(
            r"(?i)\b(hey\s+)?jarv(is|iss|es|ys)?\b[,.:;!?\- ]*",
            " ",
            gate_transcript or "",
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.:;!?-")
        words = [w for w in cleaned.split() if w]

        if len(words) >= 2:
            self._wake_log.log_wake(
                "accept_gate_inline", score, gate_transcript[:60]
            )
            return (cleaned, "accept_gate_inline")

        # Silence, fragment, or wake-word-only → ack + fresh recording.
        self._wake_log.log_wake(
            "accept_gate", score, (gate_transcript or "")[:60]
        )
        return (None, "accept_gate")

    # -- internal --

    def _whisper_transcribe_array(self, audio: np.ndarray) -> str:
        """Run faster-whisper on an in-memory float32 ndarray.

        Mirrors :meth:`JarvisAssistant._transcribe_local` in src/jarvis.py
        but takes a numpy array instead of a Path — Plan 05 keeps gate
        audio in memory only (PITFALLS.md §C1: never write voice to disk).

        Anti-hallucination configuration (the silence → fabricated text bug):

        * ``vad_filter=True`` — whisper's own Silero-VAD pass drops near-
          silent regions before the decoder sees them, so the model can't
          fabricate plausible English out of room noise.
        * ``no_speech_threshold=0.6`` — if whisper's internal no-speech
          probability is above 60 %, the segment is emitted as empty.
        * ``condition_on_previous_text=False`` — breaks the well-known
          hallucination cascade where the decoder carries forward a bad
          context into the next segment.
        * ``language="en"`` — lock to English to skip slow, error-prone
          language auto-detection on sub-second clips.

        Empty string is returned on: whisper filtered everything as silence,
        whisper raised, or the audio buffer was empty.
        """
        if audio is None or len(audio) == 0:
            return ""
        try:
            segments, _info = self._whisper.transcribe(
                audio,
                language="en",
                beam_size=1,
                vad_filter=True,
                no_speech_threshold=0.6,
                condition_on_previous_text=False,
            )
            return "".join(seg.text for seg in segments).strip()
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(
                f"[audio_in] whisper transcribe error: {exc}\n"
            )
            return ""
