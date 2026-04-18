from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class ProcessingOptions:
    language: str = "auto"
    voice_key: str = "auto"
    speech_rate: float = 1.0
    remove_numeric_citations: bool = True
    drop_references_section: bool = True
    drop_acknowledgements: bool = True
    drop_appendices: bool = True
    keep_headings: bool = True
    chunk_max_chars: int = 900
    pause_ms: int = 220
    # --- v2 additions ---
    tts_engine: str = "piper"  # "piper" or "kokoro"
    use_llm_cleaner: bool = False
    llm_base_url: str = ""
    llm_model: str = ""
    job_id: str = ""
    filename: str = ""
    created_at: str = ""


@dataclass(slots=True)
class ExtractedBlock:
    text: str
    label: str
    page_no: int | None = None
    bbox: tuple[float, float, float, float] | None = None


@dataclass(slots=True)
class LayoutRegion:
    """Bounding box of a non-text element (picture, table, caption)."""

    kind: str  # "picture", "table", "caption"
    page_no: int
    bbox: tuple[float, float, float, float]  # (l, t, r, b)


@dataclass(slots=True)
class CleaningStats:
    pages: int = 0
    total_blocks: int = 0
    kept_blocks: int = 0
    dropped_blocks: int = 0
    dropped_by_label: dict[str, int] = field(default_factory=dict)
    dropped_by_rule: dict[str, int] = field(default_factory=dict)
    detected_language: str = "unknown"
    # --- v2 additions ---
    reading_order_repaired: bool = False
    layout_regions_found: int = 0
    layout_filter_dropped: int = 0
    llm_blocks_processed: int = 0
    llm_blocks_dropped: int = 0
    llm_blocks_rewritten: int = 0


@dataclass(slots=True)
class JobResult:
    cleaned_text_path: Path | None = None
    audio_path: Path | None = None
    original_pdf_path: Path | None = None
    detected_language: str | None = None
    engine_used: str | None = None
    stats: CleaningStats | None = None


@dataclass(slots=True)
class JobState:
    job_id: str
    filename: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: JobStatus = JobStatus.PENDING
    step: str = "Queued"
    progress: float = 0.0
    error: str | None = None
    engine_used: str | None = None
    result: JobResult = field(default_factory=JobResult)

    @staticmethod
    def _serialize_stats(stats: CleaningStats | None) -> dict[str, Any] | None:
        if not stats:
            return None

        return {
            "pages": stats.pages,
            "total_blocks": stats.total_blocks,
            "kept_blocks": stats.kept_blocks,
            "dropped_blocks": stats.dropped_blocks,
            "dropped_by_label": stats.dropped_by_label,
            "dropped_by_rule": stats.dropped_by_rule,
            "detected_language": stats.detected_language,
            "reading_order_repaired": stats.reading_order_repaired,
            "layout_regions_found": stats.layout_regions_found,
            "layout_filter_dropped": stats.layout_filter_dropped,
            "llm_blocks_processed": stats.llm_blocks_processed,
            "llm_blocks_dropped": stats.llm_blocks_dropped,
            "llm_blocks_rewritten": stats.llm_blocks_rewritten,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "filename": self.filename,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "status": self.status.value,
            "step": self.step,
            "progress": self.progress,
            "error": self.error,
            "engine_used": self.engine_used or self.result.engine_used,
            "result": {
                "cleaned_text_path": (
                    str(self.result.cleaned_text_path) if self.result.cleaned_text_path else None
                ),
                "audio_path": str(self.result.audio_path) if self.result.audio_path else None,
                "original_pdf_path": str(self.result.original_pdf_path)
                if self.result.original_pdf_path
                else None,
                "detected_language": self.result.detected_language,
                "engine_used": self.result.engine_used,
                "stats": self._serialize_stats(self.result.stats),
            },
        }

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "filename": self.filename,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "status": self.status.value,
            "step": self.step,
            "progress": self.progress,
            "error": self.error,
            "engine_used": self.engine_used or self.result.engine_used,
            "result": {
                "has_text": self.result.cleaned_text_path is not None,
                "has_audio": self.result.audio_path is not None,
                "has_pdf": self.result.original_pdf_path is not None,
                "detected_language": self.result.detected_language,
                "engine_used": self.result.engine_used,
                "stats": self._serialize_stats(self.result.stats),
            },
        }
