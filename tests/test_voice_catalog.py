from __future__ import annotations

from pathlib import Path

from readmypaper.services.voice_catalog import VOICE_SPECS, VoiceCatalog


def test_resolve_explicit_piper_voice(tmp_path: Path) -> None:
    catalog = VoiceCatalog(root=tmp_path / "voices")

    spec = catalog.resolve("en_US-lessac-medium", "en", tts_engine="piper")

    assert spec.key == "en_US-lessac-medium"
    assert spec.engine == "piper"


def test_resolve_explicit_kokoro_voice(tmp_path: Path) -> None:
    catalog = VoiceCatalog(root=tmp_path / "voices")

    spec = catalog.resolve("kokoro-en-heart", "en", tts_engine="kokoro")

    assert spec.key == "kokoro-en-heart"
    assert spec.engine == "kokoro"


def test_resolve_auto_piper_default(tmp_path: Path) -> None:
    catalog = VoiceCatalog(root=tmp_path / "voices")

    spec = catalog.resolve("auto", "en", tts_engine="piper")

    assert spec.key == "en_US-lessac-medium"
    assert spec.engine == "piper"


def test_resolve_auto_kokoro_default(tmp_path: Path) -> None:
    catalog = VoiceCatalog(root=tmp_path / "voices")

    spec = catalog.resolve("auto", "en", tts_engine="kokoro")

    assert spec.key == "kokoro-en-heart"
    assert spec.engine == "kokoro"


def test_is_compatible_accepts_matching_combinations(tmp_path: Path) -> None:
    catalog = VoiceCatalog(root=tmp_path / "voices")

    assert catalog.is_compatible("en_US-lessac-medium", "piper") is True
    assert catalog.is_compatible("kokoro-en-heart", "kokoro") is True


def test_is_compatible_accepts_auto_voice(tmp_path: Path) -> None:
    catalog = VoiceCatalog(root=tmp_path / "voices")

    assert catalog.is_compatible("auto", "piper") is True
    assert catalog.is_compatible("auto", "kokoro") is True


def test_is_compatible_accepts_unknown_voice(tmp_path: Path) -> None:
    catalog = VoiceCatalog(root=tmp_path / "voices")

    assert catalog.is_compatible("unknown-voice", "piper") is True
    assert catalog.is_compatible("unknown-voice", "kokoro") is True


def test_is_compatible_rejects_cross_engine_mismatches(tmp_path: Path) -> None:
    catalog = VoiceCatalog(root=tmp_path / "voices")

    assert catalog.is_compatible("en_US-lessac-medium", "kokoro") is False
    assert catalog.is_compatible("kokoro-en-heart", "piper") is False


def test_voice_specs_have_expected_engine_counts(tmp_path: Path) -> None:
    piper_specs = [spec for spec in VOICE_SPECS.values() if spec.engine == "piper"]
    kokoro_specs = [spec for spec in VOICE_SPECS.values() if spec.engine == "kokoro"]

    assert len(piper_specs) == 4
    assert len(kokoro_specs) == 4


def test_ensure_downloaded_is_noop_for_kokoro_voices(tmp_path: Path) -> None:
    catalog = VoiceCatalog(root=tmp_path / "voices")

    model_path, config_path = catalog.ensure_downloaded(VOICE_SPECS["kokoro-en-heart"])

    assert model_path == Path()
    assert config_path == Path()
