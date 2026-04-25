from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from ..config import settings
from ..types import JobResult, ProcessingOptions
from .layout_filter import filter_by_layout
from .llm_cleaner import clean_and_reorder_blocks
from .pdf_extractor import DoclingPdfExtractor
from .reading_order import repair_reading_order
from .text_cleaner import ScientificTextCleaner
from .tts_piper import PiperTtsEngine
from .voice_catalog import VoiceCatalog, VoiceSpec

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[float, str], None]


class TtsEngineProtocol(Protocol):
    def synthesize(
        self,
        text: str,
        *,
        output_path: Path,
        options: ProcessingOptions,
        voice_spec: VoiceSpec,
        progress: ProgressCallback | None = None,
    ) -> tuple[Path, VoiceSpec]: ...


class ReadMyPaperPipeline:
    def __init__(
        self,
        extractor: DoclingPdfExtractor | None = None,
        tts_engine_piper: TtsEngineProtocol | None = None,
    ) -> None:
        self.extractor = extractor or DoclingPdfExtractor()
        self.tts_engine_piper = tts_engine_piper or PiperTtsEngine()

    def process(
        self,
        *,
        pdf_path: Path,
        output_dir: Path,
        options: ProcessingOptions,
        progress: ProgressCallback | None = None,
    ) -> JobResult:
        output_dir.mkdir(parents=True, exist_ok=True)

        def emit(ratio: float, step: str) -> None:
            if progress:
                progress(ratio, step)

        # ---- Stage 1: PDF extraction ----
        emit(0.05, "Extracting PDF (may take a few minutes)")
        logger.info("Starting PDF extraction for %s", pdf_path.name)
        extraction = self.extractor.extract(pdf_path)
        page_count = extraction.page_count
        if page_count > settings.max_pdf_pages:
            raise ValueError(
                f"PDF has {page_count} pages, which exceeds the limit of {settings.max_pdf_pages}."
            )
        page_sizes = extraction.page_sizes
        layout_regions = extraction.layout_regions
        logger.info(
            "Extraction complete: %d blocks, %d pages, %d layout regions",
            len(extraction.blocks),
            page_count,
            len(layout_regions),
        )

        # ---- Stage 2: Reading order repair ----
        emit(0.18, "Repairing reading order")
        blocks = repair_reading_order(extraction.blocks, page_sizes)
        logger.info("Reading order repair: %d blocks", len(blocks))

        # ---- Stage 3: Layout spatial filter ----
        emit(0.28, "Applying layout spatial filter")
        blocks, n_spatial_dropped = filter_by_layout(blocks, layout_regions)
        logger.info("Layout filter dropped %d blocks", n_spatial_dropped)

        # ---- Stage 4: Text cleaning (section whitelist + regex filters) ----
        emit(0.35, "Cleaning scientific content")
        cleaner = ScientificTextCleaner(options)
        cleaned_text, stats = cleaner.clean(blocks, page_count=page_count)
        stats.reading_order_repaired = True
        stats.layout_regions_found = len(layout_regions)
        stats.layout_filter_dropped = n_spatial_dropped

        # ---- Stage 5: LLM full-block cleaner (optional) ----
        llm_url = options.llm_base_url or settings.llm_base_url
        if options.use_llm_cleaner and llm_url:
            emit(0.42, "Running LLM cleaner")
            logger.info("LLM cleaner: using %s", llm_url)

            blocks = clean_and_reorder_blocks(
                blocks,
                page_count,
                base_url=llm_url,
                api_key=settings.llm_api_key,
                model=options.llm_model or settings.llm_model,
                stats=stats,
            )

            # Re-run deterministic cleaning on the LLM-filtered blocks.
            cleaned_text, stats2 = cleaner.clean(blocks, page_count=page_count)
            llm_dropped = stats.llm_blocks_dropped
            stats.kept_blocks = stats2.kept_blocks
            stats.dropped_blocks = stats2.dropped_blocks + llm_dropped
            stats.total_blocks = stats2.total_blocks + llm_dropped
            stats.dropped_by_rule.update(stats2.dropped_by_rule)
            stats.detected_language = stats2.detected_language

        # ---- Resolve effective language ----
        # If the user explicitly chose a language, honour it; otherwise use
        # the auto-detected language from the cleaned text.
        if options.language and options.language != "auto":
            effective_language = options.language
        else:
            effective_language = stats.detected_language

        emit(0.50, "Saved cleaned text")
        text_path = output_dir / "cleaned_text.txt"
        text_path.write_text(cleaned_text, encoding="utf-8")

        metadata_path = output_dir / "metadata.json"
        metadata = {
            "job_id": options.job_id,
            "filename": options.filename,
            "created_at": options.created_at,
            "source_pdf": str(pdf_path),
            "detected_language": stats.detected_language,
            "effective_language": effective_language,
            "options": asdict(options),
            "stats": asdict(stats),
        }
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # ---- Stage 6: TTS synthesis ----
        audio_path = output_dir / "reading.wav"
        emit(0.55, "Generating speech")

        voice_catalog = VoiceCatalog()
        requested_tts_engine = self._resolve_tts_engine(options)
        voice_spec = voice_catalog.resolve(
            options.voice_key, effective_language, tts_engine=requested_tts_engine
        )

        if requested_tts_engine == "kokoro" and voice_spec.engine == "kokoro":
            try:
                from .tts_kokoro import KokoroTtsEngine

                engine = KokoroTtsEngine()
                engine_used = "kokoro"
            except Exception:
                logger.warning("Kokoro engine unavailable, falling back to piper", exc_info=True)
                voice_spec = voice_catalog.resolve(
                    options.voice_key, effective_language, tts_engine="piper"
                )
                engine = self.tts_engine_piper
                engine_used = "piper"
        else:
            engine = self.tts_engine_piper
            engine_used = "piper"

        audio_path, voice_spec = engine.synthesize(
            cleaned_text,
            output_path=audio_path,
            options=options,
            voice_spec=voice_spec,
            progress=lambda inner, step: emit(0.55 + inner * 0.43, step),
        )

        metadata["voice"] = {
            "key": voice_spec.key,
            "display_name": voice_spec.display_name,
            "language_code": voice_spec.language_code,
            "engine": voice_spec.engine,
        }
        metadata["engine_used"] = engine_used
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        emit(1.0, "Done")

        return JobResult(
            cleaned_text_path=text_path,
            audio_path=audio_path,
            original_pdf_path=pdf_path,
            detected_language=effective_language,
            engine_used=engine_used,
            stats=stats,
        )

    @staticmethod
    def _resolve_tts_engine(options: ProcessingOptions) -> str:
        engine = options.tts_engine or "piper"
        if engine not in {"piper", "kokoro"}:
            logger.warning("Unknown TTS engine '%s', falling back to piper", engine)
            return "piper"
        return engine
