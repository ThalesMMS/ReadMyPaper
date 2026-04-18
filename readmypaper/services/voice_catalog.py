from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlretrieve

from ..config import settings

HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


@dataclass(frozen=True, slots=True)
class VoiceSpec:
    key: str
    language_code: str
    language_label: str
    display_name: str
    engine: str  # "piper" or "kokoro"
    # Piper-specific fields.
    folder: str = ""
    model_filename: str = ""
    config_filename: str = ""
    # Kokoro-specific field.
    kokoro_voice: str = ""

    @property
    def model_url(self) -> str:
        return f"{HF_BASE}/{self.folder}/{self.model_filename}"

    @property
    def config_url(self) -> str:
        return f"{HF_BASE}/{self.folder}/{self.config_filename}"

    def local_model_path(self, root: Path) -> Path:
        return root / self.key / self.model_filename

    def local_config_path(self, root: Path) -> Path:
        return root / self.key / self.config_filename


VOICE_SPECS: dict[str, VoiceSpec] = {
    # ---- Piper voices (fast mode) ----
    "en_US-lessac-medium": VoiceSpec(
        key="en_US-lessac-medium",
        language_code="en",
        language_label="English",
        display_name="English — Lessac (Piper, fast)",
        engine="piper",
        folder="en/en_US/lessac/medium",
        model_filename="en_US-lessac-medium.onnx",
        config_filename="en_US-lessac-medium.onnx.json",
    ),
    "en_US-hfc_female-medium": VoiceSpec(
        key="en_US-hfc_female-medium",
        language_code="en",
        language_label="English",
        display_name="English — HFC Female (Piper, fast)",
        engine="piper",
        folder="en/en_US/hfc_female/medium",
        model_filename="en_US-hfc_female-medium.onnx",
        config_filename="en_US-hfc_female-medium.onnx.json",
    ),
    "pt_BR-faber-medium": VoiceSpec(
        key="pt_BR-faber-medium",
        language_code="pt-BR",
        language_label="Português (Brasil)",
        display_name="Português — Faber (Piper, fast)",
        engine="piper",
        folder="pt/pt_BR/faber/medium",
        model_filename="pt_BR-faber-medium.onnx",
        config_filename="pt_BR-faber-medium.onnx.json",
    ),
    "pt_BR-cadu-medium": VoiceSpec(
        key="pt_BR-cadu-medium",
        language_code="pt-BR",
        language_label="Português (Brasil)",
        display_name="Português — Cadu (Piper, fast)",
        engine="piper",
        folder="pt/pt_BR/cadu/medium",
        model_filename="pt_BR-cadu-medium.onnx",
        config_filename="pt_BR-cadu-medium.onnx.json",
    ),
    # ---- Kokoro voices (quality mode) ----
    "kokoro-en-heart": VoiceSpec(
        key="kokoro-en-heart",
        language_code="en",
        language_label="English",
        display_name="English — Heart (Kokoro, quality)",
        engine="kokoro",
        kokoro_voice="af_heart",
    ),
    "kokoro-en-michael": VoiceSpec(
        key="kokoro-en-michael",
        language_code="en",
        language_label="English",
        display_name="English — Michael (Kokoro, quality)",
        engine="kokoro",
        kokoro_voice="am_michael",
    ),
    "kokoro-en-bella": VoiceSpec(
        key="kokoro-en-bella",
        language_code="en",
        language_label="English",
        display_name="English — Bella (Kokoro, quality)",
        engine="kokoro",
        kokoro_voice="af_bella",
    ),
    "kokoro-pt-dora": VoiceSpec(
        key="kokoro-pt-dora",
        language_code="pt-BR",
        language_label="Português (Brasil)",
        display_name="Português — Dora (Kokoro, quality)",
        engine="kokoro",
        kokoro_voice="pf_dora",
    ),
}

DEFAULT_VOICE_BY_LANGUAGE = {
    "en": "en_US-lessac-medium",
    "en-us": "en_US-lessac-medium",
    "pt": "pt_BR-faber-medium",
    "pt-br": "pt_BR-faber-medium",
}

# Quality-mode defaults (Kokoro).
DEFAULT_QUALITY_VOICE_BY_LANGUAGE = {
    "en": "kokoro-en-heart",
    "en-us": "kokoro-en-heart",
    "pt": "kokoro-pt-dora",
    "pt-br": "kokoro-pt-dora",
}


class VoiceCatalog:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or settings.voices_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def list_for_ui(self) -> list[dict[str, str]]:
        return [
            {
                "key": spec.key,
                "language_code": spec.language_code,
                "language_label": spec.language_label,
                "display_name": spec.display_name,
                "engine": spec.engine,
            }
            for spec in VOICE_SPECS.values()
        ]

    def resolve(
        self,
        requested_voice: str,
        detected_language: str | None = None,
        tts_engine: str | None = None,
    ) -> VoiceSpec:
        if requested_voice and requested_voice != "auto":
            if requested_voice in VOICE_SPECS:
                return VOICE_SPECS[requested_voice]

        language = (detected_language or "").strip().lower()
        defaults = (
            DEFAULT_QUALITY_VOICE_BY_LANGUAGE
            if tts_engine == "kokoro"
            else DEFAULT_VOICE_BY_LANGUAGE
        )

        if language in defaults:
            return VOICE_SPECS[defaults[language]]
        if language.startswith("pt"):
            return VOICE_SPECS[defaults.get("pt-br", DEFAULT_VOICE_BY_LANGUAGE["pt-br"])]
        return VOICE_SPECS[defaults.get("en", DEFAULT_VOICE_BY_LANGUAGE["en"])]

    def is_compatible(self, voice_key: str, tts_engine: str) -> bool:
        if voice_key == "auto":
            return True

        spec = VOICE_SPECS.get(voice_key)
        if spec is None:
            return True

        return spec.engine == tts_engine

    def ensure_downloaded(self, spec: VoiceSpec) -> tuple[Path, Path]:
        """Download Piper voice files if needed.  Kokoro voices are handled
        by the kokoro package itself."""
        if spec.engine == "kokoro":
            # Kokoro downloads models automatically on first use.
            return Path(), Path()

        voice_dir = self.root / spec.key
        voice_dir.mkdir(parents=True, exist_ok=True)
        model_path = spec.local_model_path(self.root)
        config_path = spec.local_config_path(self.root)

        if not model_path.exists():
            urlretrieve(spec.model_url, model_path)
        if not config_path.exists():
            urlretrieve(spec.config_url, config_path)

        return model_path, config_path
