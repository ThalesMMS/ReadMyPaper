from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_cache_dir, user_data_dir

APP_NAME = "ReadMyPaper"
PACKAGE_NAME = "readmypaper"


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default.resolve()


def _legacy_data_dir() -> tuple[Path, ...]:
    try:
        cwd = Path.cwd().resolve()
    except OSError:
        return ()
    candidates = [cwd / "outputs"]

    for parent in cwd.parents:
        if (parent / "pyproject.toml").is_file() and (parent / PACKAGE_NAME).is_dir():
            candidates.append(parent / "outputs")
            break

    seen: set[Path] = set()
    unique_candidates: list[Path] = []
    for candidate in candidates:
        try:
            resolved_candidate = candidate.resolve()
        except OSError:
            continue
        if resolved_candidate not in seen:
            seen.add(resolved_candidate)
            unique_candidates.append(resolved_candidate)
    return tuple(unique_candidates)


def _legacy_data_dir_has_files(path: Path) -> bool:
    try:
        if not path.exists():
            return False
        for _, _, filenames in os.walk(path, onerror=_raise_walk_error):
            if filenames:
                return True
    except OSError:
        return False
    return False


def _raise_walk_error(error: OSError) -> None:
    raise error


_legacy_data_dir_warning_emitted = False


def _warn_if_legacy_data_dir_has_files(data_dir: Path) -> None:
    global _legacy_data_dir_warning_emitted

    if _legacy_data_dir_warning_emitted:
        return

    current_data_dir = data_dir.resolve()
    for legacy_data_dir in _legacy_data_dir():
        if legacy_data_dir == current_data_dir:
            continue
        if not _legacy_data_dir_has_files(legacy_data_dir):
            continue

        print(
            "ReadMyPaper detected files in the legacy data directory "
            f"{legacy_data_dir}. New runtime data is stored in {current_data_dir}. "
            "Migrate any PDFs, cleaned text, or audio files manually if you still need them.",
            file=sys.stderr,
        )
        _legacy_data_dir_warning_emitted = True
        return


@dataclass(frozen=True)
class Settings:
    host: str = os.environ.get("READMYPAPER_HOST", "127.0.0.1")
    port: int = int(os.environ.get("READMYPAPER_PORT", "8000"))
    data_dir: Path = field(
        default_factory=lambda: _env_path(
            "READMYPAPER_DATA_DIR",
            Path(user_data_dir(APP_NAME, appauthor=False)),
        )
    )
    cache_dir: Path = field(
        default_factory=lambda: _env_path(
            "READMYPAPER_CACHE_DIR",
            Path(user_cache_dir(APP_NAME, appauthor=False, opinion=False)),
        )
    )
    jobs_max_workers: int = int(os.environ.get("READMYPAPER_MAX_WORKERS", "2"))

    # --- LLM cleaner settings ---
    llm_base_url: str = os.environ.get("READMYPAPER_LLM_URL", "").strip()
    llm_model: str = os.environ.get("READMYPAPER_LLM_MODEL", "").strip()
    llm_api_key: str = "apikey"
    llm_enabled: bool = os.environ.get("READMYPAPER_LLM_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    max_upload_bytes: int = int(
        os.environ.get("READMYPAPER_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024))
    )
    max_pdf_pages: int = int(os.environ.get("READMYPAPER_MAX_PDF_PAGES", "200"))
    speech_rate_min: float = float(os.environ.get("READMYPAPER_SPEECH_RATE_MIN", "0.5"))
    speech_rate_max: float = float(os.environ.get("READMYPAPER_SPEECH_RATE_MAX", "2.0"))
    max_pending_jobs: int = int(os.environ.get("READMYPAPER_MAX_PENDING_JOBS", "10"))
    job_retention_hours: int = int(os.environ.get("READMYPAPER_JOB_RETENTION_HOURS", "0"))

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def voices_dir(self) -> Path:
        return self.cache_dir / "voices"

    @property
    def models_dir(self) -> Path:
        return self.cache_dir / "models"

    def ensure_dirs(self) -> None:
        _warn_if_legacy_data_dir_has_files(self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
