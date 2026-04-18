from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from readmypaper import main
from readmypaper.job_store import JobStore


def _configure_app(
    monkeypatch,
    tmp_path: Path,
    fake_executor,
    *,
    retention_hours: int,
    now: datetime,
) -> None:
    monkeypatch.setitem(main.settings.__dict__, "data_dir", tmp_path / "data")
    monkeypatch.setitem(main.settings.__dict__, "cache_dir", tmp_path / "cache")
    monkeypatch.setitem(main.settings.__dict__, "job_retention_hours", retention_hours)
    main.settings.ensure_dirs()

    monkeypatch.setattr(main, "EXECUTOR", fake_executor)
    monkeypatch.setattr(main, "JOBS", JobStore())
    monkeypatch.setattr(main, "_utc_now", lambda: now)


def _write_restorable_job(*, job_id: str, filename: str, created_at: str) -> tuple[Path, Path]:
    output_dir = main.settings.outputs_dir / job_id
    output_dir.mkdir(parents=True)
    (output_dir / "reading.wav").write_bytes(b"RIFF")
    (output_dir / "cleaned_text.txt").write_text("cleaned text", encoding="utf-8")

    upload_dir = main.settings.uploads_dir / job_id
    upload_dir.mkdir(parents=True)
    source_pdf_path = upload_dir / "source.pdf"
    source_pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    (output_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "filename": filename,
                "created_at": created_at,
                "source_pdf": str(source_pdf_path),
                "detected_language": "en",
                "effective_language": "en",
                "engine_used": "piper",
            }
        ),
        encoding="utf-8",
    )
    return upload_dir, output_dir


def _write_orphan_dirs(*, job_id: str) -> tuple[Path, Path]:
    upload_dir = main.settings.uploads_dir / job_id
    upload_dir.mkdir(parents=True)
    (upload_dir / "source.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")

    output_dir = main.settings.outputs_dir / job_id
    output_dir.mkdir(parents=True)
    (output_dir / "metadata.json").write_text("{not-json", encoding="utf-8")
    return upload_dir, output_dir


def _mock_old_directory_timestamps(monkeypatch, targets: set[Path], old_time: datetime) -> None:
    original_stat = Path.stat

    def fake_stat(self: Path, *args, **kwargs):
        stat_result = original_stat(self, *args, **kwargs)
        if self not in targets:
            return stat_result

        values = {
            field: getattr(stat_result, field)
            for field in dir(stat_result)
            if field.startswith("st_")
        }
        values["st_mtime"] = old_time.timestamp()
        values["st_ctime"] = old_time.timestamp()
        return SimpleNamespace(**values)

    monkeypatch.setattr(Path, "stat", fake_stat)


def test_startup_cleanup_deletes_jobs_older_than_ttl(
    monkeypatch, tmp_path: Path, fake_executor
) -> None:
    now = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)
    _configure_app(monkeypatch, tmp_path, fake_executor, retention_hours=24, now=now)
    upload_dir, output_dir = _write_restorable_job(
        job_id="job-old",
        filename="paper.pdf",
        created_at="2026-04-16T11:00:00+00:00",
    )

    with TestClient(main.app) as client:
        response = client.get("/api/jobs/job-old")

    assert response.status_code == 404
    assert not upload_dir.exists()
    assert not output_dir.exists()


def test_startup_cleanup_keeps_jobs_newer_than_ttl(
    monkeypatch, tmp_path: Path, fake_executor
) -> None:
    now = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)
    _configure_app(monkeypatch, tmp_path, fake_executor, retention_hours=24, now=now)
    upload_dir, output_dir = _write_restorable_job(
        job_id="job-new",
        filename="fresh.pdf",
        created_at="2026-04-17T06:00:00+00:00",
    )

    with TestClient(main.app) as client:
        response = client.get("/api/jobs/job-new")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert upload_dir.exists()
    assert output_dir.exists()


def test_startup_cleanup_removes_old_orphan_directories(
    monkeypatch, tmp_path: Path, fake_executor
) -> None:
    now = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)
    _configure_app(monkeypatch, tmp_path, fake_executor, retention_hours=24, now=now)
    upload_dir, output_dir = _write_orphan_dirs(job_id="job-orphan")
    _mock_old_directory_timestamps(
        monkeypatch,
        {upload_dir, output_dir},
        datetime(2026, 4, 16, 10, 0, tzinfo=timezone.utc),
    )

    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert not upload_dir.exists()
    assert not output_dir.exists()


def test_startup_cleanup_is_skipped_when_ttl_disabled(
    monkeypatch, tmp_path: Path, fake_executor
) -> None:
    now = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)
    _configure_app(monkeypatch, tmp_path, fake_executor, retention_hours=0, now=now)
    upload_dir, output_dir = _write_restorable_job(
        job_id="job-kept",
        filename="old-paper.pdf",
        created_at="2026-04-15T08:00:00+00:00",
    )
    orphan_upload_dir, orphan_output_dir = _write_orphan_dirs(
        job_id="job-orphan-kept",
    )

    with TestClient(main.app) as client:
        response = client.get("/api/jobs/job-kept")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert upload_dir.exists()
    assert output_dir.exists()
    assert orphan_upload_dir.exists()
    assert orphan_output_dir.exists()
