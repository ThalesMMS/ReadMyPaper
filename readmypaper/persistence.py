from __future__ import annotations

import json
import logging
import re
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings
from .job_store import JobStore
from .types import CleaningStats, JobResult, JobState, JobStatus

logger = logging.getLogger(__name__)
_SAFE_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def restore_jobs_from_disk(store: JobStore) -> None:
    if not settings.outputs_dir.exists() or not settings.outputs_dir.is_dir():
        logger.info(
            "Skipping restore because outputs directory is unavailable: %s",
            settings.outputs_dir,
        )
        return

    try:
        output_dirs = iter(settings.outputs_dir.iterdir())
    except OSError as exc:
        logger.warning("Skipping restore because outputs directory cannot be read: %s", exc)
        return

    restored_sources: dict[str, Path] = {}

    while True:
        try:
            output_dir = next(output_dirs)
        except StopIteration:
            break
        except OSError as exc:
            logger.warning(
                "Skipping an entry while iterating outputs directory %s: %s",
                settings.outputs_dir,
                exc,
            )
            continue

        try:
            if not output_dir.is_dir():
                continue
        except OSError as exc:
            logger.warning("Skipping unreadable outputs entry %s: %s", output_dir, exc)
            continue

        job = _restore_job_from_output_dir(output_dir)
        if job is None:
            continue
        if not store.restore_if_absent(job):
            logger.warning(
                (
                    "Skipping duplicate restored job_id %s from %s because "
                    "that job_id already exists from %s"
                ),
                job.job_id,
                output_dir,
                restored_sources.get(job.job_id, Path("<unknown>")),
            )
            continue
        restored_sources[job.job_id] = output_dir


def _restore_job_from_output_dir(output_dir: Path) -> JobState | None:
    audio_path = output_dir / "reading.wav"
    if not audio_path.is_file():
        return None

    metadata_path = output_dir / "metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError("metadata.json must contain a JSON object")

        job_id = _require_metadata_str(metadata, "job_id")
        filename = _require_metadata_str(metadata, "filename")
        created_at = _parse_created_at(_require_metadata_str(metadata, "created_at"))
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Skipping restore for %s: %s", output_dir, exc)
        return None

    cleaned_text_path = output_dir / "cleaned_text.txt"
    source_pdf_path = _restore_source_pdf_path(metadata, job_id)
    effective_language = _optional_metadata_str(metadata, "effective_language")
    detected_language = (
        _optional_metadata_str(
            metadata,
            "detected_language",
        )
        or effective_language
    )
    engine_used = _optional_metadata_str(metadata, "engine_used")
    stats = _restore_stats(metadata.get("stats"))

    return JobState(
        job_id=job_id,
        filename=filename,
        created_at=created_at,
        updated_at=created_at,
        status=JobStatus.COMPLETED,
        step="Completed",
        progress=1.0,
        engine_used=engine_used,
        result=JobResult(
            cleaned_text_path=cleaned_text_path if cleaned_text_path.is_file() else None,
            audio_path=audio_path,
            original_pdf_path=source_pdf_path,
            detected_language=detected_language,
            engine_used=engine_used,
            stats=stats,
        ),
    )


def _require_metadata_str(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"metadata.json missing valid '{key}'")
    return value


def _optional_metadata_str(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _parse_created_at(value: str) -> datetime:
    created_at = datetime.fromisoformat(value)
    if created_at.tzinfo is None:
        return created_at.replace(tzinfo=timezone.utc)
    return created_at


def _restore_source_pdf_path(metadata: dict[str, Any], job_id: str) -> Path | None:
    source_pdf = _optional_metadata_str(metadata, "source_pdf")
    if source_pdf:
        try:
            uploads_root = settings.uploads_dir.resolve()
            source_pdf_path = Path(source_pdf).resolve(strict=True)
            if source_pdf_path.is_file() and source_pdf_path.is_relative_to(uploads_root):
                return source_pdf_path
        except OSError:
            pass

    if not _SAFE_JOB_ID_PATTERN.fullmatch(job_id):
        logger.warning("Skipping fallback source PDF restore for invalid job_id %s", job_id)
        return None

    try:
        uploads_root = settings.uploads_dir.resolve()
        fallback_pdf_path = (settings.uploads_dir / job_id / "source.pdf").resolve()
        if fallback_pdf_path.is_file() and fallback_pdf_path.is_relative_to(uploads_root):
            return fallback_pdf_path
    except OSError:
        pass
    return None


def _restore_stats(payload: Any) -> CleaningStats | None:
    if not isinstance(payload, dict):
        return None

    stats_fields = {field.name for field in fields(CleaningStats)}
    stats_data = {key: value for key, value in payload.items() if key in stats_fields}
    return CleaningStats(**stats_data)
