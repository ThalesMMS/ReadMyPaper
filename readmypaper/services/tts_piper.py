from __future__ import annotations

import math
import wave
from collections.abc import Callable
from pathlib import Path

from ..types import ProcessingOptions
from .text_cleaner import ScientificTextCleaner
from .tts_verbalizer import verbalize
from .voice_catalog import VoiceSpec

ProgressCallback = Callable[[float, str], None]

# Punctuation-aware pause durations (ms).
_PAUSE_PERIOD_MS = 350
_PAUSE_PARAGRAPH_MS = 500
_PAUSE_COMMA_MS = 120


class PiperTtsEngine:
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
            from piper import PiperVoice
            from piper.config import SynthesisConfig
        except ImportError as exc:  # pragma: no cover - optional runtime dependency
            raise RuntimeError(
                "piper-tts is not installed. "
                "Run `pip install piper-tts` or install project dependencies."
            ) from exc

        from .voice_catalog import VoiceCatalog

        # Verbalise scientific notation before chunking.
        text = verbalize(text)

        cleaner = ScientificTextCleaner(options)
        chunks = cleaner.split_text(text, max_chars=options.chunk_max_chars)
        model_path, _config_path = VoiceCatalog().ensure_downloaded(voice_spec)
        voice = PiperVoice.load(str(model_path))

        length_scale = self._length_scale(options.speech_rate)
        synthesis_config = SynthesisConfig(length_scale=length_scale)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        sample_rate = None
        sample_width = None
        channels = None

        with wave.open(str(output_path), "wb") as wav_file:
            for idx, text_chunk in enumerate(chunks):
                chunk_generator = voice.synthesize(text_chunk, syn_config=synthesis_config)
                for audio_chunk in chunk_generator:
                    if sample_rate is None:
                        sample_rate = audio_chunk.sample_rate
                        sample_width = audio_chunk.sample_width
                        channels = audio_chunk.sample_channels
                        wav_file.setframerate(sample_rate)
                        wav_file.setsampwidth(sample_width)
                        wav_file.setnchannels(channels)
                    wav_file.writeframes(audio_chunk.audio_int16_bytes)

                # Punctuation-aware pause instead of fixed pause_ms.
                if idx < len(chunks) - 1 and sample_rate is not None:
                    pause = self._inter_chunk_pause(text_chunk, options.pause_ms)
                    silence = self._silence_bytes(
                        sample_rate=sample_rate,
                        sample_width=sample_width or 2,
                        channels=channels or 1,
                        pause_ms=pause,
                    )
                    if silence:
                        wav_file.writeframes(silence)

                if progress:
                    ratio = (idx + 1) / max(len(chunks), 1)
                    progress(ratio, f"Synthesizing audio ({idx + 1}/{len(chunks)} chunks)")

        return output_path, voice_spec

    @staticmethod
    def _length_scale(speech_rate: float) -> float:
        safe_rate = min(max(speech_rate, 0.7), 1.4)
        return round(1.0 / safe_rate, 3)

    @staticmethod
    def _inter_chunk_pause(chunk: str, default_pause_ms: int) -> int:
        """Select a pause duration based on the final punctuation of the chunk."""
        text = chunk.rstrip()
        if not text:
            return default_pause_ms
        last_char = text[-1]
        if last_char in ".!?":
            return _PAUSE_PERIOD_MS
        if last_char in ",;:":
            return _PAUSE_COMMA_MS
        return _PAUSE_PARAGRAPH_MS

    @staticmethod
    def _silence_bytes(
        *, sample_rate: int, sample_width: int, channels: int, pause_ms: int
    ) -> bytes:
        frames = math.floor(sample_rate * max(pause_ms, 0) / 1000)
        return b"\x00" * frames * sample_width * channels
