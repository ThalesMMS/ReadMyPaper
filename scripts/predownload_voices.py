from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from readmypaper.services.voice_catalog import VOICE_SPECS, VoiceCatalog

if __name__ == "__main__":
    catalog = VoiceCatalog()
    # Kokoro voices are excluded here because the kokoro package manages their
    # model downloads at runtime.
    piper_voice_specs = {key: spec for key, spec in VOICE_SPECS.items() if spec.engine == "piper"}
    for key, spec in piper_voice_specs.items():
        model_path, _config_path = catalog.ensure_downloaded(spec)
        print(f"Downloaded {key} -> {model_path}")
