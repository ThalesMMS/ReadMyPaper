# Contributing

ReadMyPaper is a small beta project. Contributions are welcome, but keep changes
focused and easy to review.

## Prerequisites

- Python 3.10, 3.11, or 3.12
- git
- `espeak-ng` if you are testing Kokoro TTS:
  - Debian/Ubuntu: `sudo apt install espeak-ng`
  - macOS: `brew install espeak-ng`
  - Windows: install from the
    [eSpeak NG releases](https://github.com/espeak-ng/espeak-ng/releases)

Python 3.12 is recommended because it matches the main development target.

## Local setup

```bash
git clone https://github.com/ThalesMMS/ReadMyPaper.git
cd ReadMyPaper
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install '.[dev]'
```

On Windows PowerShell:

```powershell
git clone https://github.com/ThalesMMS/ReadMyPaper.git
cd ReadMyPaper
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install '.[dev]'
```

If you need to test Kokoro:

```bash
python -m pip install '.[kokoro,dev]'
```

## Validation

Run the same basic checks used by CI before opening a pull request:

```bash
pytest
ruff check .
ruff format --check .
```

For UI changes, also run the app locally and check the affected screen:

```bash
python -m readmypaper.main
```

Then open:

```text
http://127.0.0.1:8000
```

## Change scope

- Keep changes focused on the problem being fixed.
- Avoid unrelated refactors, formatting churn, or cleanup.
- Match the existing code and documentation style.
- See [AGENTS.md](AGENTS.md) for the repository's working principles.

## Bug-oriented contributions

For bug fixes, include enough context for someone else to reproduce the issue:

- operating system and version
- Python version
- TTS backend used, such as Piper or Kokoro
- whether optional LLM cleaning was enabled
- clear reproduction steps
- the validation commands you ran

Do not attach private PDFs, generated audio, cleaned text, screenshots with
private content, medical documents, or PHI to public issues, pull requests, or
test fixtures. Use small synthetic examples whenever possible.
