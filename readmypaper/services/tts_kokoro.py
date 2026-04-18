"""Kokoro TTS engine — quality-tier local neural speech synthesis.

Kokoro is an 82M-parameter open-weight model producing 24 kHz audio with
natural prosody.  It is used as the **quality** option alongside Piper (fast).

Requirements:
    pip install .[kokoro]
    brew install espeak-ng   # macOS system dependency
"""

from __future__ import annotations

import logging
import math
import wave
from collections.abc import Callable
from pathlib import Path

from ..types import ProcessingOptions
from .text_cleaner import ScientificTextCleaner
from .tts_verbalizer import verbalize
from .voice_catalog import VoiceSpec

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[float, str], None]

# Pause durations for punctuation-aware synthesis (ms).
_PAUSE_PERIOD_MS = 400
_PAUSE_PARAGRAPH_MS = 600
_PAUSE_COMMA_MS = 150

KOKORO_SAMPLE_RATE = 24000
KOKORO_SAMPLE_WIDTH = 2  # 16-bit PCM
KOKORO_CHANNELS = 1


class KokoroTtsEngine:
    """Quality-tier TTS using Kokoro."""

    def synthesize(
        self,
        text: str,
        *,
        output_path: Path,
        options: ProcessingOptions,
        voice_spec: VoiceSpec,
        progress: ProgressCallback | None = None,
    ) -> tuple[Path, VoiceSpec]:
        try:
            from kokoro import KPipeline
        except ImportError as exc:
            raise RuntimeError(
                "kokoro is not installed. Install it with `pip install .[kokoro]`. "
                "On macOS, also install the system dependency with `brew install espeak-ng`."
            ) from exc

        # Verbalize before chunking.
        text = verbalize(text)

        cleaner = ScientificTextCleaner(options)
        # Kokoro handles longer chunks natively — use 2000 chars for smoother prosody.
        chunk_limit = (
            max(options.chunk_max_chars, 2000)
            if options.tts_engine == "kokoro"
            else options.chunk_max_chars
        )
        chunks = cleaner.split_text(text, max_chars=chunk_limit)

        lang_code = self._kokoro_lang_code(voice_spec.language_code)
        kokoro_voice = self._kokoro_voice_name(voice_spec)
        speed = min(max(options.speech_rate, 0.5), 2.0)

        logger.info(
            "Kokoro: lang=%s, voice=%s, speed=%.2f, chunks=%d",
            lang_code,
            kokoro_voice,
            speed,
            len(chunks),
        )

        pipeline = KPipeline(lang_code=lang_code)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setframerate(KOKORO_SAMPLE_RATE)
            wav_file.setsampwidth(KOKORO_SAMPLE_WIDTH)
            wav_file.setnchannels(KOKORO_CHANNELS)

            for idx, chunk in enumerate(chunks):
                chunk = chunk.strip()
                if not chunk:
                    continue

                try:
                    for _gs, _ps, audio in pipeline(chunk, voice=kokoro_voice, speed=speed):
                        if audio is not None and len(audio) > 0:
                            pcm_bytes = self._numpy_to_pcm16(audio)
                            wav_file.writeframes(pcm_bytes)
                except Exception:
                    logger.warning(
                        "Kokoro synthesis failed on chunk %d, skipping", idx, exc_info=True
                    )
                    continue

                # Punctuation-aware pause between chunks.
                if idx < len(chunks) - 1:
                    pause = self._inter_chunk_pause(chunk)
                    if pause > 0:
                        wav_file.writeframes(self._silence_bytes(pause))

                if progress:
                    ratio = (idx + 1) / max(len(chunks), 1)
                    progress(ratio, f"Synthesizing audio ({idx + 1}/{len(chunks)} chunks)")

        return output_path, voice_spec

    @staticmethod
    def _kokoro_lang_code(language_code: str) -> str:
        """Map our language codes to Kokoro's single-letter lang codes."""
        lc = language_code.lower()
        if lc.startswith("pt"):
            return "p"  # Portuguese
        return "a"  # American English (default)

    @staticmethod
    def _kokoro_voice_name(voice_spec: VoiceSpec) -> str:
        """Map a VoiceSpec to a Kokoro voice identifier."""
        # Use the kokoro_voice field if set on the spec.
        kokoro_voice = getattr(voice_spec, "kokoro_voice", None)
        if kokoro_voice:
            return kokoro_voice
        # Fallback defaults.
        if voice_spec.language_code.lower().startswith("pt"):
            return "pf_dora"  # Portuguese female
        return "af_heart"  # American English female

    @staticmethod
    def _numpy_to_pcm16(audio) -> bytes:
        """Convert a numpy/torch float array to 16-bit PCM bytes."""
        import numpy as np

        if not isinstance(audio, np.ndarray):
            audio = audio.cpu().numpy()
        audio_clamped = np.clip(audio, -1.0, 1.0)
        pcm = (audio_clamped * 32767).astype(np.int16)
        return pcm.tobytes()

    @staticmethod
    def _inter_chunk_pause(chunk: str) -> int:
        """Return pause duration (ms) based on how the chunk ends."""
        text = chunk.rstrip()
        if not text:
            return _PAUSE_PERIOD_MS
        last_char = text[-1]
        if last_char in ".!?":
            return _PAUSE_PERIOD_MS
        if last_char in ",;:":
            return _PAUSE_COMMA_MS
        # No explicit sentence end — probably a paragraph break.
        return _PAUSE_PARAGRAPH_MS

    @staticmethod
    def _silence_bytes(pause_ms: int) -> bytes:
        frames = math.floor(KOKORO_SAMPLE_RATE * max(pause_ms, 0) / 1000)
        return b"\x00" * frames * KOKORO_SAMPLE_WIDTH * KOKORO_CHANNELS
