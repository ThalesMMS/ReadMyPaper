from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _load_config(monkeypatch, tmp_path: Path, **env: str):
    for name in [
        "READMYPAPER_LLM_URL",
        "READMYPAPER_LLM_MODEL",
        "READMYPAPER_LLM_ENABLED",
        "READMYPAPER_JOB_RETENTION_HOURS",
    ]:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("READMYPAPER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("READMYPAPER_CACHE_DIR", str(tmp_path / "cache"))
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    sys.modules.pop("readmypaper.config", None)
    package = importlib.import_module("readmypaper")
    if hasattr(package, "config"):
        delattr(package, "config")
    return importlib.import_module("readmypaper.config")


def test_llm_cleaner_defaults_to_unconfigured_and_disabled(monkeypatch, tmp_path: Path) -> None:
    config = _load_config(monkeypatch, tmp_path)

    assert config.settings.llm_base_url == ""
    assert config.settings.llm_model == ""
    assert config.settings.llm_enabled is False


def test_llm_cleaner_can_be_enabled_explicitly(monkeypatch, tmp_path: Path) -> None:
    config = _load_config(
        monkeypatch,
        tmp_path,
        READMYPAPER_LLM_URL="http://127.0.0.1:8000/v1",
        READMYPAPER_LLM_MODEL="local-model",
        READMYPAPER_LLM_ENABLED="true",
    )

    assert config.settings.llm_base_url == "http://127.0.0.1:8000/v1"
    assert config.settings.llm_model == "local-model"
    assert config.settings.llm_enabled is True


def test_llm_cleaner_env_values_are_stripped(monkeypatch, tmp_path: Path) -> None:
    config = _load_config(
        monkeypatch,
        tmp_path,
        READMYPAPER_LLM_URL="  http://127.0.0.1:8000/v1  ",
        READMYPAPER_LLM_MODEL="  local-model  ",
        READMYPAPER_LLM_ENABLED="  yes  ",
    )

    assert config.settings.llm_base_url == "http://127.0.0.1:8000/v1"
    assert config.settings.llm_model == "local-model"
    assert config.settings.llm_enabled is True


def test_job_retention_hours_defaults_to_disabled(monkeypatch, tmp_path: Path) -> None:
    config = _load_config(monkeypatch, tmp_path)

    assert config.settings.job_retention_hours == 0


def test_job_retention_hours_reads_from_environment(monkeypatch, tmp_path: Path) -> None:
    config = _load_config(
        monkeypatch,
        tmp_path,
        READMYPAPER_JOB_RETENTION_HOURS="24",
    )

    assert config.settings.job_retention_hours == 24
