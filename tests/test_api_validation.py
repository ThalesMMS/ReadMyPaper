from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from readmypaper import __version__, main
from readmypaper.job_store import JobStore
from readmypaper.types import JobResult, JobStatus


@pytest.fixture
def app_client(monkeypatch, tmp_path: Path, fake_executor):
    monkeypatch.setitem(main.settings.__dict__, "data_dir", tmp_path / "data")
    monkeypatch.setitem(main.settings.__dict__, "cache_dir", tmp_path / "cache")
    main.settings.ensure_dirs()

    monkeypatch.setattr(main, "EXECUTOR", fake_executor)
    monkeypatch.setattr(main, "JOBS", JobStore())

    with TestClient(main.app) as client:
        yield client, fake_executor


def _post_job(
    client: TestClient,
    *,
    voice_key: str,
    tts_engine: str,
    filename: str = "paper.pdf",
    content: bytes = b"%PDF-1.4\n%%EOF\n",
    content_type: str = "application/pdf",
    extra_data: dict[str, str] | None = None,
):
    data = {"voice_key": voice_key, "tts_engine": tts_engine}
    if extra_data:
        data.update(extra_data)
    return client.post(
        "/jobs",
        data=data,
        files={"pdf": (filename, content, content_type)},
        follow_redirects=False,
    )


def _create_completed_job(
    filename: str,
    *,
    cleaned_text_path: Path | None = None,
    audio_path: Path | None = None,
    original_pdf_path: Path | None = None,
):
    job = main.JOBS.create(filename)
    main.JOBS.update(
        job.job_id,
        status=JobStatus.COMPLETED,
        step="Completed",
        progress=1.0,
        result=JobResult(
            cleaned_text_path=cleaned_text_path,
            audio_path=audio_path,
            original_pdf_path=original_pdf_path,
            detected_language="en",
            engine_used="piper",
        ),
    )
    return job


def _extract_window_job_payload(html: str) -> tuple[str, dict[str, object]]:
    prefix = "window.__job = "
    start = html.index(prefix) + len(prefix)
    payload, end = json.JSONDecoder().raw_decode(html[start:])
    return html[start : start + end], payload


def _assert_no_internal_path_leaks(serialized: str) -> None:
    for token in (
        "/home/",
        "outputs/",
        "reading.wav",
        "cleaned.txt",
        ".wav",
        ".txt",
        "cleaned_text_path",
        "audio_path",
        "original_pdf_path",
    ):
        assert token not in serialized


def test_cli_version_prints_package_version(capsys) -> None:
    main.cli(["--version"])

    assert capsys.readouterr().out == f"readmypaper {__version__}\n"


def test_post_jobs_accepts_valid_engine_voice_combination(app_client) -> None:
    client, executor = app_client

    response = _post_job(client, voice_key="en_US-lessac-medium", tts_engine="piper")

    assert response.status_code == 303
    assert response.headers["location"].startswith("/jobs/")
    assert len(executor.submissions) == 1


def test_index_exposes_llm_controls_without_env_gate(app_client, monkeypatch) -> None:
    client, _executor = app_client
    monkeypatch.setitem(main.settings.__dict__, "llm_enabled", False)
    monkeypatch.setitem(main.settings.__dict__, "llm_base_url", "")
    monkeypatch.setitem(main.settings.__dict__, "llm_model", "")

    response = client.get("/")

    assert response.status_code == 200
    assert 'name="use_llm_cleaner"' in response.text
    assert 'name="llm_base_url"' in response.text
    assert "LLM base URL" in response.text
    assert "Include a port only when needed" in response.text
    assert "https://example.com/v1" in response.text
    assert 'name="llm_model"' in response.text
    assert 'id="llm-options" class="nested-option"' in response.text


def test_post_jobs_accepts_llm_options_from_form(app_client) -> None:
    client, executor = app_client

    response = _post_job(
        client,
        voice_key="auto",
        tts_engine="piper",
        extra_data={
            "use_llm_cleaner": "on",
            "llm_base_url": "http://127.0.0.1:11434/v1",
            "llm_model": "local-model",
        },
    )

    assert response.status_code == 303
    _, args, _ = executor.submissions[0]
    options = args[3]
    assert options.use_llm_cleaner is True
    assert options.llm_base_url == "http://127.0.0.1:11434/v1"
    assert options.llm_model == "local-model"


def test_post_jobs_applies_configured_llm_defaults(app_client, monkeypatch) -> None:
    client, executor = app_client
    monkeypatch.setitem(main.settings.__dict__, "llm_base_url", "http://127.0.0.1:11434/v1")
    monkeypatch.setitem(main.settings.__dict__, "llm_model", "default-model")

    response = _post_job(
        client,
        voice_key="auto",
        tts_engine="piper",
        extra_data={"use_llm_cleaner": "on"},
    )

    assert response.status_code == 303
    _, args, _ = executor.submissions[0]
    options = args[3]
    assert options.llm_base_url == "http://127.0.0.1:11434/v1"
    assert options.llm_model == "default-model"


def test_post_jobs_accepts_llm_base_url_with_embedded_port(app_client) -> None:
    client, executor = app_client

    response = _post_job(
        client,
        voice_key="auto",
        tts_engine="piper",
        extra_data={
            "use_llm_cleaner": "on",
            "llm_base_url": "127.0.0.1:11434/v1",
        },
    )

    assert response.status_code == 303
    _, args, _ = executor.submissions[0]
    options = args[3]
    assert options.llm_base_url == "http://127.0.0.1:11434/v1"


def test_post_jobs_rejects_unsupported_llm_base_url_scheme(app_client) -> None:
    client, executor = app_client

    response = _post_job(
        client,
        voice_key="auto",
        tts_engine="piper",
        extra_data={
            "use_llm_cleaner": "on",
            "llm_base_url": "ftp://127.0.0.1:11434/v1",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "LLM base URL must be a valid URL."
    assert executor.submissions == []


def test_post_jobs_requires_llm_base_url_when_llm_is_enabled(app_client, monkeypatch) -> None:
    client, executor = app_client
    monkeypatch.setitem(main.settings.__dict__, "llm_base_url", "")

    response = _post_job(
        client,
        voice_key="auto",
        tts_engine="piper",
        extra_data={"use_llm_cleaner": "on"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "LLM base URL is required when LLM cleaner is enabled."
    assert executor.submissions == []


def test_app_startup_restores_completed_jobs_from_disk(
    monkeypatch, tmp_path: Path, fake_executor
) -> None:
    monkeypatch.setitem(main.settings.__dict__, "data_dir", tmp_path / "data")
    monkeypatch.setitem(main.settings.__dict__, "cache_dir", tmp_path / "cache")
    main.settings.ensure_dirs()

    job_id = "job-123"
    created_at = "2026-04-16T12:00:00+00:00"
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
                "filename": "paper.pdf",
                "created_at": created_at,
                "source_pdf": str(source_pdf_path),
                "detected_language": "en",
                "effective_language": "en",
                "engine_used": "piper",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(main, "EXECUTOR", fake_executor)
    monkeypatch.setattr(main, "JOBS", JobStore())

    with TestClient(main.app) as client:
        response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["filename"] == "paper.pdf"
    assert response.json()["created_at"] == created_at


def test_app_startup_continues_when_restore_fails(
    monkeypatch, tmp_path: Path, fake_executor
) -> None:
    monkeypatch.setitem(main.settings.__dict__, "data_dir", tmp_path / "data")
    monkeypatch.setitem(main.settings.__dict__, "cache_dir", tmp_path / "cache")
    monkeypatch.setattr(
        main,
        "restore_jobs_from_disk",
        lambda _jobs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(main, "EXECUTOR", fake_executor)
    monkeypatch.setattr(main, "JOBS", JobStore())

    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_post_jobs_rejects_mismatched_engine_voice_combination(app_client) -> None:
    client, executor = app_client

    response = _post_job(client, voice_key="kokoro-en-heart", tts_engine="piper")

    assert response.status_code == 422
    assert "not compatible" in response.json()["detail"]
    assert executor.submissions == []


def test_post_jobs_rejects_unknown_tts_engine(app_client) -> None:
    client, executor = app_client

    response = _post_job(client, voice_key="auto", tts_engine="unknown")

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Unsupported TTS engine 'unknown'. Supported engines are: 'piper', 'kokoro'."
    )
    assert executor.submissions == []


def test_post_jobs_rejects_invalid_pdf_magic_bytes(app_client) -> None:
    client, executor = app_client

    response = _post_job(
        client,
        voice_key="auto",
        tts_engine="piper",
        content=b"not a pdf",
        content_type="text/plain",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Uploaded file is not a valid PDF."
    assert executor.submissions == []


def test_post_jobs_rejects_oversized_upload(app_client, monkeypatch) -> None:
    client, executor = app_client
    monkeypatch.setitem(main.settings.__dict__, "max_upload_bytes", 8)

    response = _post_job(
        client,
        voice_key="auto",
        tts_engine="piper",
        content=b"%PDF-1.4\n%%EOF\n",
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Uploaded PDF exceeds the maximum size of 8 bytes."
    assert executor.submissions == []


@pytest.mark.parametrize("speech_rate", ["0.4", "2.1"], ids=["below-min", "above-max"])
def test_post_jobs_rejects_out_of_bounds_speech_rate(app_client, speech_rate: str) -> None:
    client, executor = app_client

    response = _post_job(
        client,
        voice_key="auto",
        tts_engine="piper",
        extra_data={"speech_rate": speech_rate},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Speech rate must be between 0.5 and 2.0."
    assert executor.submissions == []


def test_post_jobs_rejects_non_numeric_speech_rate(app_client) -> None:
    client, executor = app_client

    response = _post_job(
        client,
        voice_key="auto",
        tts_engine="piper",
        extra_data={"speech_rate": "fast"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Speech rate must be a number."
    assert executor.submissions == []


def test_post_jobs_rejects_when_queue_is_at_capacity(app_client, monkeypatch) -> None:
    client, executor = app_client
    monkeypatch.setitem(main.settings.__dict__, "max_pending_jobs", 1)
    main.JOBS.create("existing.pdf")

    response = _post_job(client, voice_key="auto", tts_engine="piper")

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "The server is busy processing other jobs. Please retry later."
    )
    assert executor.submissions == []


@pytest.mark.parametrize("tts_engine", ["piper", "kokoro"])
def test_post_jobs_accepts_auto_voice_for_any_engine(app_client, tts_engine: str) -> None:
    client, executor = app_client

    response = _post_job(client, voice_key="auto", tts_engine=tts_engine)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/jobs/")
    assert len(executor.submissions) == 1


def test_index_escapes_bootstrap_json_and_hides_internal_paths(
    app_client, monkeypatch, tmp_path: Path
) -> None:
    client, _executor = app_client
    malicious_name = 'Voice </script><script>alert("xss")</script>'
    escaped_payload = (
        '\\u003c/script\\u003e\\u003cscript\\u003ealert(\\"xss\\")\\u003c/script\\u003e'
    )
    monkeypatch.setattr(
        main.VOICE_CATALOG,
        "list_for_ui",
        lambda: [
            {
                "key": "danger",
                "language_code": "en",
                "language_label": "English",
                "display_name": malicious_name,
                "engine": "piper",
            }
        ],
    )

    response = client.get("/")

    assert response.status_code == 200
    assert escaped_payload in response.text
    assert malicious_name not in response.text
    assert str(tmp_path / "data") not in response.text
    assert str(tmp_path / "cache") not in response.text


def test_job_page_escapes_script_breakout_in_filename(app_client) -> None:
    client, _executor = app_client
    filename = "paper </script><script>alert(1)//"
    escaped_fragment = "\\u003c/script\\u003e\\u003cscript\\u003ealert(1)//"
    job = _create_completed_job(filename)

    response = client.get(f"/jobs/{job.job_id}")
    raw_payload, payload = _extract_window_job_payload(response.text)

    assert response.status_code == 200
    assert filename not in response.text
    assert "</script><script>alert(1)//" not in raw_payload
    assert escaped_fragment in raw_payload
    assert payload["filename"] == filename


@pytest.mark.parametrize(
    ("filename", "expected_fragment"),
    [
        ("paper 'quote.pdf", None),
        ('paper "quote".pdf', '\\"'),
        (r"paper\backslash.pdf", r"\\"),
        ("paper\nnewline.pdf", r"\n"),
    ],
    ids=["single-quote", "double-quote", "backslash", "newline"],
)
def test_job_page_bootstrap_json_handles_special_filenames(
    app_client, filename: str, expected_fragment: str | None
) -> None:
    client, _executor = app_client
    job = _create_completed_job(filename)

    response = client.get(f"/jobs/{job.job_id}")
    raw_payload, payload = _extract_window_job_payload(response.text)

    assert response.status_code == 200
    assert payload["filename"] == filename
    if expected_fragment is not None:
        assert expected_fragment in raw_payload


def test_job_api_and_page_bootstrap_do_not_leak_internal_paths(app_client) -> None:
    client, _executor = app_client
    job = _create_completed_job(
        "paper.pdf",
        cleaned_text_path=Path("/home/tester/outputs/cleaned.txt"),
        audio_path=Path("/home/tester/outputs/reading.wav"),
        original_pdf_path=Path("/home/tester/outputs/source.pdf"),
    )

    api_response = client.get(f"/api/jobs/{job.job_id}")

    assert api_response.status_code == 200
    assert api_response.json()["result"] == {
        "has_text": True,
        "has_audio": True,
        "has_pdf": True,
        "detected_language": "en",
        "engine_used": "piper",
        "stats": None,
    }
    _assert_no_internal_path_leaks(api_response.text)

    page_response = client.get(f"/jobs/{job.job_id}")
    raw_payload, payload = _extract_window_job_payload(page_response.text)

    assert page_response.status_code == 200
    assert payload["result"] == {
        "has_text": True,
        "has_audio": True,
        "has_pdf": True,
        "detected_language": "en",
        "engine_used": "piper",
        "stats": None,
    }
    _assert_no_internal_path_leaks(raw_payload)
    assert "/home/" not in page_response.text
    assert "outputs/" not in page_response.text
    assert ".wav" not in page_response.text
    assert ".txt" not in page_response.text


def test_delete_job_removes_job_and_artifacts(app_client) -> None:
    client, _executor = app_client
    job = main.JOBS.create("paper.pdf")
    upload_dir = main.settings.uploads_dir / job.job_id
    output_dir = main.settings.outputs_dir / job.job_id
    upload_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    (upload_dir / "source.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (output_dir / "cleaned.txt").write_text("cleaned", encoding="utf-8")
    (output_dir / "reading.wav").write_bytes(b"wav")
    main.JOBS.update(
        job.job_id,
        status=JobStatus.COMPLETED,
        step="Completed",
        progress=1.0,
        result=JobResult(
            cleaned_text_path=output_dir / "cleaned.txt",
            audio_path=output_dir / "reading.wav",
            original_pdf_path=upload_dir / "source.pdf",
            detected_language="en",
            engine_used="piper",
        ),
    )

    response = client.delete(f"/jobs/{job.job_id}")

    assert response.status_code == 204
    assert response.text == ""
    assert main.JOBS.get(job.job_id) is None
    assert not upload_dir.exists()
    assert not output_dir.exists()


def test_delete_job_returns_404_for_missing_job(app_client) -> None:
    client, _executor = app_client

    response = client.delete("/jobs/missing-job")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found."


@pytest.mark.parametrize(
    "status",
    [JobStatus.PENDING, JobStatus.RUNNING],
    ids=["pending", "running"],
)
def test_delete_job_returns_409_for_active_job(app_client, status: JobStatus) -> None:
    client, _executor = app_client
    job = main.JOBS.create("paper.pdf")
    main.JOBS.update(job.job_id, status=status)

    response = client.delete(f"/jobs/{job.job_id}")

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot delete a job that is still processing."
    assert main.JOBS.get(job.job_id) is not None
