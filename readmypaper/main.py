from __future__ import annotations

import logging
import math
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .job_store import JobStore
from .persistence import restore_jobs_from_disk
from .services.pipeline import ReadMyPaperPipeline
from .services.voice_catalog import VoiceCatalog
from .types import JobStatus, ProcessingOptions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
_ORPHAN_DIR_GRACE_PERIOD = timedelta(minutes=10)

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
VOICE_CATALOG = VoiceCatalog()
PIPELINE = ReadMyPaperPipeline()
JOBS = JobStore()
EXECUTOR = ThreadPoolExecutor(max_workers=settings.jobs_max_workers)
SUPPORTED_TTS_ENGINES = ("piper", "kokoro")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        settings.ensure_dirs()
    except Exception:
        logger.exception("lifespan: settings.ensure_dirs failed")

    try:
        restore_jobs_from_disk(JOBS)
    except Exception:
        logger.exception("lifespan: restore_jobs_from_disk failed")

    try:
        _cleanup_expired_jobs_on_startup()
    except Exception:
        logger.exception("lifespan: _cleanup_expired_jobs_on_startup failed")

    try:
        yield
    finally:
        EXECUTOR.shutdown(wait=False, cancel_futures=False)


app = FastAPI(title="ReadMyPaper", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    recent_jobs = sorted(JOBS.list(), key=lambda job: job.created_at, reverse=True)[:10]
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "voices": VOICE_CATALOG.list_for_ui(),
            "jobs": recent_jobs,
            "default_llm_enabled": settings.llm_enabled,
            "default_llm_url": settings.llm_base_url,
            "default_llm_model": settings.llm_model,
        },
    )


@app.post("/jobs")
async def create_job(
    request: Request,
    pdf: UploadFile = File(...),
    language: str = Form("auto"),
    voice_key: str = Form("auto"),
    speech_rate: str = Form("1.0"),
    remove_numeric_citations: str | None = Form(None),
    drop_references_section: str | None = Form(None),
    drop_acknowledgements: str | None = Form(None),
    drop_appendices: str | None = Form(None),
    keep_headings: str | None = Form(None),
    tts_engine: str = Form("piper"),
    use_llm_cleaner: str | None = Form(None),
    llm_base_url: str = Form(""),
    llm_port: str = Form(""),
    llm_model: str = Form(""),
) -> RedirectResponse:
    del request
    if not pdf.filename:
        raise HTTPException(status_code=400, detail="No PDF file provided.")

    pdf_magic_bytes = await pdf.read(5)
    if pdf_magic_bytes != b"%PDF-":
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF.")

    await pdf.seek(0)
    if not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    upload_bytes = await pdf.read(settings.max_upload_bytes + 1)
    if len(upload_bytes) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=(f"Uploaded PDF exceeds the maximum size of {settings.max_upload_bytes} bytes."),
        )

    if tts_engine not in SUPPORTED_TTS_ENGINES:
        supported_engines = ", ".join(f"'{engine}'" for engine in SUPPORTED_TTS_ENGINES)
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported TTS engine '{tts_engine}'. "
                f"Supported engines are: {supported_engines}."
            ),
        )

    selected_tts_engine = tts_engine
    if not VOICE_CATALOG.is_compatible(voice_key, selected_tts_engine):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Voice '{voice_key}' is not compatible with TTS engine '{selected_tts_engine}'. "
                "Choose a matching voice or use voice_key='auto'."
            ),
        )

    try:
        parsed_speech_rate = float(speech_rate)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Speech rate must be a number.") from exc

    if (
        not math.isfinite(parsed_speech_rate)
        or parsed_speech_rate < settings.speech_rate_min
        or parsed_speech_rate > settings.speech_rate_max
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Speech rate must be between "
                f"{settings.speech_rate_min} and {settings.speech_rate_max}."
            ),
        )

    use_llm = _checkbox_to_bool(use_llm_cleaner)
    llm_url = ""
    selected_llm_model = ""
    if use_llm:
        llm_url = _build_llm_base_url(llm_base_url, llm_port)
        if not llm_url and not settings.llm_base_url:
            raise HTTPException(
                status_code=422,
                detail="LLM endpoint is required when LLM cleaner is enabled.",
            )
        selected_llm_model = llm_model.strip()

    job = JOBS.create_with_capacity_check(pdf.filename, settings.max_pending_jobs)
    if job is None:
        raise HTTPException(
            status_code=503,
            detail="The server is busy processing other jobs. Please retry later.",
        )
    upload_dir = settings.uploads_dir / job.job_id
    output_dir = settings.outputs_dir / job.job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = upload_dir / "source.pdf"
    with pdf_path.open("wb") as out_file:
        out_file.write(upload_bytes)

    options = ProcessingOptions(
        language=language,
        voice_key=voice_key,
        speech_rate=parsed_speech_rate,
        remove_numeric_citations=_checkbox_to_bool(remove_numeric_citations),
        drop_references_section=_checkbox_to_bool(drop_references_section),
        drop_acknowledgements=_checkbox_to_bool(drop_acknowledgements),
        drop_appendices=_checkbox_to_bool(drop_appendices),
        keep_headings=_checkbox_to_bool(keep_headings),
        tts_engine=selected_tts_engine,
        use_llm_cleaner=use_llm,
        llm_base_url=llm_url,
        llm_model=selected_llm_model,
        job_id=job.job_id,
        filename=job.filename,
        created_at=job.created_at.isoformat(),
    )

    JOBS.update(
        job.job_id,
        status=JobStatus.PENDING,
        step="Queued",
        progress=0.02,
    )
    EXECUTOR.submit(run_pipeline_job, job.job_id, pdf_path, output_dir, options)
    return RedirectResponse(url=f"/jobs/{job.job_id}", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str) -> HTMLResponse:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    preview_text = None
    if job.result.cleaned_text_path and job.result.cleaned_text_path.exists():
        preview_text = job.result.cleaned_text_path.read_text(encoding="utf-8")[:8000]
    return TEMPLATES.TemplateResponse(
        request,
        "job.html",
        {
            "request": request,
            "job": job,
            "job_data": job.as_public_dict(),
            "preview_text": preview_text,
        },
    )


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str) -> JSONResponse:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JSONResponse(job.as_public_dict(), headers={"Cache-Control": "no-store"})


@app.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str) -> Response:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status in {JobStatus.PENDING, JobStatus.RUNNING}:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a job that is still processing.",
        )

    _delete_job_artifacts_and_state(job_id)
    return Response(status_code=204)


@app.get("/jobs/{job_id}/audio")
async def download_audio(job_id: str) -> FileResponse:
    job = _require_job_result(job_id, "audio_path")
    return FileResponse(job.result.audio_path, media_type="audio/wav", filename="reading.wav")


@app.get("/jobs/{job_id}/text")
async def download_text(job_id: str) -> FileResponse:
    job = _require_job_result(job_id, "cleaned_text_path")
    return FileResponse(
        job.result.cleaned_text_path,
        media_type="text/plain",
        filename="cleaned_text.txt",
    )


@app.get("/jobs/{job_id}/pdf")
async def download_pdf(job_id: str) -> FileResponse:
    job = _require_job_result(job_id, "original_pdf_path")
    return FileResponse(
        job.result.original_pdf_path,
        media_type="application/pdf",
        filename=job.filename,
    )


@app.get("/health")
async def healthcheck() -> JSONResponse:
    return JSONResponse({"status": "ok"})


def run_pipeline_job(
    job_id: str,
    pdf_path: Path,
    output_dir: Path,
    options: ProcessingOptions,
) -> None:
    try:
        JOBS.update(job_id, status=JobStatus.RUNNING, step="Starting", progress=0.05)

        def progress(ratio: float, step: str) -> None:
            JOBS.update(job_id, status=JobStatus.RUNNING, step=step, progress=ratio)

        result = PIPELINE.process(
            pdf_path=pdf_path,
            output_dir=output_dir,
            options=options,
            progress=progress,
        )
        JOBS.update(
            job_id,
            status=JobStatus.COMPLETED,
            step="Completed",
            progress=1.0,
            engine_used=result.engine_used,
            result=result,
        )
    except Exception as exc:  # pragma: no cover - runtime path
        logging.getLogger(__name__).exception("Pipeline failed for job %s", job_id)
        JOBS.update(
            job_id,
            status=JobStatus.FAILED,
            step="Failed",
            progress=1.0,
            error=str(exc),
        )


def _checkbox_to_bool(value: str | None) -> bool:
    return value not in {None, "", "0", "false", "False", "off"}


def _build_llm_base_url(endpoint: str, port: str) -> str:
    endpoint = endpoint.strip()
    port = port.strip()
    if not endpoint:
        return ""

    if "://" not in endpoint:
        endpoint = f"http://{endpoint}"

    parts = urlsplit(endpoint)
    if not parts.scheme or not parts.netloc:
        raise HTTPException(status_code=422, detail="LLM endpoint must be a valid URL.")

    netloc = parts.netloc
    if port:
        parsed_port = _parse_llm_port(port)
        host = parts.hostname
        if not host:
            raise HTTPException(status_code=422, detail="LLM endpoint must include a host.")
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = f"{host}:{parsed_port}"

    return urlunsplit((parts.scheme, netloc, parts.path.rstrip("/"), "", "")).rstrip("/")


def _parse_llm_port(port: str) -> int:
    try:
        parsed_port = int(port)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="LLM port must be a number.") from exc

    if parsed_port < 1 or parsed_port > 65535:
        raise HTTPException(status_code=422, detail="LLM port must be between 1 and 65535.")
    return parsed_port


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _delete_job_artifacts(job_id: str) -> None:
    uploads_dir = settings.uploads_dir / job_id
    outputs_dir = settings.outputs_dir / job_id
    if uploads_dir.exists():
        shutil.rmtree(uploads_dir)
    if outputs_dir.exists():
        shutil.rmtree(outputs_dir)


def _delete_job_artifacts_and_state(job_id: str) -> None:
    _delete_job_artifacts(job_id)
    JOBS.delete(job_id)


def _cleanup_expired_jobs_on_startup() -> None:
    if settings.job_retention_hours <= 0:
        return

    now = _utc_now()
    cutoff = now - timedelta(hours=settings.job_retention_hours)
    restored_job_ids = {job.job_id for job in JOBS.list()}

    for job in list(JOBS.list()):
        if job.created_at >= cutoff:
            continue
        logger.info(
            "Cleaning expired job %s created at %s",
            job.job_id,
            job.created_at.isoformat(),
        )
        _delete_job_artifacts_and_state(job.job_id)

    for root_dir in (settings.uploads_dir, settings.outputs_dir):
        if not root_dir.exists() or not root_dir.is_dir():
            continue
        for child in root_dir.iterdir():
            if not child.is_dir() or child.name in restored_job_ids:
                continue
            if not _directory_is_older_than(child, cutoff):
                continue
            logger.info("Cleaning orphan directory %s", child)
            shutil.rmtree(child)


def _directory_is_older_than(path: Path, cutoff: datetime) -> bool:
    stat_result = path.stat()
    grace_cutoff = cutoff - _ORPHAN_DIR_GRACE_PERIOD
    modified_at = datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc)
    created_at = datetime.fromtimestamp(stat_result.st_ctime, tz=timezone.utc)
    return max(modified_at, created_at) < grace_cutoff


def _require_job_result(job_id: str, attr_name: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    result_path = getattr(job.result, attr_name)
    if not result_path or not Path(result_path).exists():
        raise HTTPException(status_code=404, detail="Requested file is not ready yet.")
    return job


def cli() -> None:
    print(f"Data directory: {settings.data_dir}")
    print(f"Cache directory: {settings.cache_dir}")
    uvicorn.run(
        "readmypaper.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        factory=False,
    )


if __name__ == "__main__":  # pragma: no cover
    cli()
