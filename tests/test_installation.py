from __future__ import annotations

import builtins
import importlib
from pathlib import Path

import pytest

from readmypaper.services.tts_kokoro import KokoroTtsEngine
from readmypaper.services.tts_piper import PiperTtsEngine
from readmypaper.services.voice_catalog import VOICE_SPECS, VoiceCatalog
from readmypaper.types import ProcessingOptions


def test_core_piper_module_import_succeeds() -> None:
    module = importlib.import_module("piper")

    assert module is not None


def test_piper_tts_engine_instantiates_with_lazy_import(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "piper":
            raise AssertionError("Piper should not be imported during engine construction")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    engine = PiperTtsEngine()

    assert isinstance(engine, PiperTtsEngine)


def test_kokoro_synthesize_reports_install_instructions_when_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "kokoro":
            raise ImportError("No module named 'kokoro'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    engine = KokoroTtsEngine()

    with pytest.raises(RuntimeError, match="kokoro is not installed") as exc_info:
        engine.synthesize(
            "Test sentence.",
            output_path=tmp_path / "audio.wav",
            options=ProcessingOptions(tts_engine="kokoro"),
            voice_spec=VOICE_SPECS["kokoro-en-heart"],
        )

    message = str(exc_info.value)
    assert "pip install .[kokoro]" in message
    assert "espeak-ng" in message


def test_kokoro_installation_smoke_when_available(tmp_path: Path) -> None:
    pytest.importorskip("kokoro")

    engine = KokoroTtsEngine()
    catalog = VoiceCatalog(root=tmp_path / "voices")
    spec = catalog.resolve("auto", "en", tts_engine="kokoro")

    assert isinstance(engine, KokoroTtsEngine)
    assert spec.key == "kokoro-en-heart"
    assert spec.engine == "kokoro"
