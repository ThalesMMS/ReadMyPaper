from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from readmypaper.config import settings
from readmypaper.job_store import JobStore
from readmypaper.persistence import restore_jobs_from_disk
from readmypaper.types import JobStatus


@pytest.fixture
def configured_storage(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(settings.__dict__, "data_dir", tmp_path / "data")
    monkeypatch.setitem(settings.__dict__, "cache_dir", tmp_path / "cache")
    settings.ensure_dirs()


def _write_restorable_job(
    *,
    job_id: str,
    filename: str,
    created_at: str,
    include_audio: bool = True,
    metadata_content: str | None = None,
) -> tuple[Path, Path]:
    output_dir = settings.outputs_dir / job_id
    output_dir.mkdir(parents=True)

    if include_audio:
        (output_dir / "reading.wav").write_bytes(b"RIFF")
    (output_dir / "cleaned_text.txt").write_text("cleaned text", encoding="utf-8")

    upload_dir = settings.uploads_dir / job_id
    upload_dir.mkdir(parents=True)
    source_pdf_path = upload_dir / "source.pdf"
    source_pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    if metadata_content is None:
        metadata_content = json.dumps(
            {
                "job_id": job_id,
                "filename": filename,
                "created_at": created_at,
                "source_pdf": str(source_pdf_path),
                "detected_language": "en",
                "effective_language": "en",
                "engine_used": "piper",
                "stats": {"pages": 1, "kept_blocks": 3},
            }
        )
    (output_dir / "metadata.json").write_text(metadata_content, encoding="utf-8")
    return output_dir, source_pdf_path


def test_restore_jobs_from_disk_restores_completed_jobs(configured_storage) -> None:
    del configured_storage
    created_at = "2026-04-16T12:00:00+00:00"
    output_dir, source_pdf_path = _write_restorable_job(
        job_id="job-123",
        filename="paper.pdf",
        created_at=created_at,
    )
    store = JobStore()

    restore_jobs_from_disk(store)

    job = store.get("job-123")
    assert job is not None
    assert job.status == JobStatus.COMPLETED
    assert job.filename == "paper.pdf"
    assert job.created_at == datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
    assert job.result.audio_path == output_dir / "reading.wav"
    assert job.result.cleaned_text_path == output_dir / "cleaned_text.txt"
    assert job.result.original_pdf_path == source_pdf_path
    assert job.result.engine_used == "piper"
    assert job.result.detected_language == "en"


def test_restore_jobs_from_disk_prefers_detected_language_over_effective_language(
    configured_storage,
) -> None:
    del configured_storage
    _write_restorable_job(
        job_id="job-language",
        filename="paper.pdf",
        created_at="2026-04-16T12:00:00+00:00",
        metadata_content=json.dumps(
            {
                "job_id": "job-language",
                "filename": "paper.pdf",
                "created_at": "2026-04-16T12:00:00+00:00",
                "detected_language": "de",
                "effective_language": "en",
                "engine_used": "piper",
            }
        ),
    )
    store = JobStore()

    restore_jobs_from_disk(store)

    job = store.get("job-language")
    assert job is not None
    assert job.result.detected_language == "de"


def test_restore_jobs_from_disk_skips_incomplete_jobs(configured_storage) -> None:
    del configured_storage
    _write_restorable_job(
        job_id="job-incomplete",
        filename="draft.pdf",
        created_at="2026-04-16T12:00:00+00:00",
        include_audio=False,
    )
    store = JobStore()

    restore_jobs_from_disk(store)

    assert store.get("job-incomplete") is None


def test_restore_jobs_from_disk_skips_malformed_metadata(configured_storage) -> None:
    del configured_storage
    _write_restorable_job(
        job_id="job-bad-metadata",
        filename="broken.pdf",
        created_at="2026-04-16T12:00:00+00:00",
        metadata_content="{not-json",
    )
    store = JobStore()

    restore_jobs_from_disk(store)

    assert store.get("job-bad-metadata") is None
    assert list(store.list()) == []


def test_restore_jobs_from_disk_skips_missing_outputs_directory(configured_storage) -> None:
    del configured_storage
    settings.outputs_dir.rmdir()
    store = JobStore()

    restore_jobs_from_disk(store)

    assert list(store.list()) == []


def test_restore_jobs_from_disk_continues_past_iteration_errors(
    configured_storage, monkeypatch
) -> None:
    del configured_storage
    _write_restorable_job(
        job_id="job-first",
        filename="first.pdf",
        created_at="2026-04-16T12:00:00+00:00",
    )
    _write_restorable_job(
        job_id="job-second",
        filename="second.pdf",
        created_at="2026-04-16T13:00:00+00:00",
    )
    original_iterdir = Path.iterdir
    first = settings.outputs_dir / "job-first"
    second = settings.outputs_dir / "job-second"

    class _BrokenIterator:
        def __init__(self) -> None:
            self._items: list[Path | OSError] = [first, OSError("boom"), second]

        def __iter__(self) -> _BrokenIterator:
            return self

        def __next__(self) -> Path:
            if not self._items:
                raise StopIteration
            item = self._items.pop(0)
            if isinstance(item, OSError):
                raise item
            return item

    def fake_iterdir(self: Path) -> Iterator[Path]:
        if self == settings.outputs_dir:
            return _BrokenIterator()
        return original_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)
    store = JobStore()

    restore_jobs_from_disk(store)

    assert store.get("job-first") is not None
    assert store.get("job-second") is not None


def test_restore_jobs_from_disk_skips_duplicate_job_ids(configured_storage) -> None:
    del configured_storage
    duplicate_job_id = "job-duplicate"
    first_dir = settings.outputs_dir / "first-copy"
    first_dir.mkdir(parents=True)
    (first_dir / "reading.wav").write_bytes(b"RIFF")
    (first_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": duplicate_job_id,
                "filename": "first.pdf",
                "created_at": "2026-04-16T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    second_dir = settings.outputs_dir / "second-copy"
    second_dir.mkdir(parents=True)
    (second_dir / "reading.wav").write_bytes(b"RIFF")
    (second_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": duplicate_job_id,
                "filename": "second.pdf",
                "created_at": "2026-04-16T13:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    original_iterdir = Path.iterdir

    def fake_iterdir(self: Path) -> Iterator[Path]:
        if self == settings.outputs_dir:
            return iter([first_dir, second_dir])
        return original_iterdir(self)

    store = JobStore()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(Path, "iterdir", fake_iterdir)
    try:
        restore_jobs_from_disk(store)
    finally:
        monkeypatch.undo()

    job = store.get(duplicate_job_id)
    assert job is not None
    assert job.filename == "first.pdf"


def test_restore_jobs_from_disk_rejects_fallback_source_pdf_outside_uploads_root(
    configured_storage,
) -> None:
    del configured_storage
    output_dir = settings.outputs_dir / "job-fallback-path"
    output_dir.mkdir(parents=True)
    (output_dir / "reading.wav").write_bytes(b"RIFF")
    (output_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "../escape",
                "filename": "paper.pdf",
                "created_at": "2026-04-16T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    escaped_pdf_path = (settings.uploads_dir / "../escape" / "source.pdf").resolve()
    escaped_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    escaped_pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    store = JobStore()

    restore_jobs_from_disk(store)

    job = store.get("../escape")
    assert job is not None
    assert job.result.original_pdf_path is None


def test_restore_jobs_from_disk_rejects_source_pdf_outside_uploads_root(
    configured_storage,
) -> None:
    del configured_storage
    external_pdf_path = settings.data_dir / "external.pdf"
    external_pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    _write_restorable_job(
        job_id="job-external-pdf",
        filename="paper.pdf",
        created_at="2026-04-16T12:00:00+00:00",
        metadata_content=json.dumps(
            {
                "job_id": "job-external-pdf",
                "filename": "paper.pdf",
                "created_at": "2026-04-16T12:00:00+00:00",
                "source_pdf": str(external_pdf_path),
            }
        ),
    )
    fallback_pdf = settings.uploads_dir / "job-external-pdf" / "source.pdf"
    fallback_pdf.unlink()
    store = JobStore()

    restore_jobs_from_disk(store)

    job = store.get("job-external-pdf")
    assert job is not None
    assert job.result.original_pdf_path is None
