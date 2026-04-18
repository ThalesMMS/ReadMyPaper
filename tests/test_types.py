from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from readmypaper.types import CleaningStats, JobResult, JobState, JobStatus


def test_job_state_as_public_dict_replaces_paths_with_readiness_flags() -> None:
    stats = CleaningStats(
        pages=12,
        total_blocks=120,
        kept_blocks=96,
        dropped_blocks=24,
        dropped_by_label={"caption": 4},
        dropped_by_rule={"references": 20},
        detected_language="en",
        reading_order_repaired=True,
        layout_regions_found=5,
        layout_filter_dropped=3,
        llm_blocks_processed=10,
        llm_blocks_dropped=2,
        llm_blocks_rewritten=6,
    )
    state = JobState(
        job_id="job-123",
        filename="paper.pdf",
        created_at=datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 16, 12, 30, tzinfo=timezone.utc),
        status=JobStatus.COMPLETED,
        step="Finished",
        progress=1.0,
        error=None,
        engine_used="kokoro",
        result=JobResult(
            cleaned_text_path=Path("/tmp/cleaned.txt"),
            audio_path=Path("/tmp/audio.wav"),
            original_pdf_path=None,
            detected_language="en",
            engine_used="kokoro",
            stats=stats,
        ),
    )

    payload = state.as_public_dict()

    assert payload == {
        "job_id": "job-123",
        "filename": "paper.pdf",
        "created_at": "2026-04-16T12:00:00+00:00",
        "updated_at": "2026-04-16T12:30:00+00:00",
        "status": "completed",
        "step": "Finished",
        "progress": 1.0,
        "error": None,
        "engine_used": "kokoro",
        "result": {
            "has_text": True,
            "has_audio": True,
            "has_pdf": False,
            "detected_language": "en",
            "engine_used": "kokoro",
            "stats": {
                "pages": 12,
                "total_blocks": 120,
                "kept_blocks": 96,
                "dropped_blocks": 24,
                "dropped_by_label": {"caption": 4},
                "dropped_by_rule": {"references": 20},
                "detected_language": "en",
                "reading_order_repaired": True,
                "layout_regions_found": 5,
                "layout_filter_dropped": 3,
                "llm_blocks_processed": 10,
                "llm_blocks_dropped": 2,
                "llm_blocks_rewritten": 6,
            },
        },
    }
    assert "cleaned_text_path" not in payload["result"]
    assert "audio_path" not in payload["result"]
    assert "original_pdf_path" not in payload["result"]
