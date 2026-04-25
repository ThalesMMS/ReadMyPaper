# Releasing

ReadMyPaper is currently an unpublished source-only beta. Do not call a version
released until the source tag, build artifacts, package index entry, and
validation evidence all exist for the same commit.

CI should be the primary validation path. Until GitHub Actions billing is
restored, use the local validation section below as the substitute release
evidence.

## Pre-release checks

- Confirm CI is green for the exact commit being released. If CI is unavailable,
  follow the [Local validation](#local-validation) outage procedure instead.
- Confirm there are no critical open issues that should block the release.
- Confirm `README.md` install instructions match the intended publication state.
  If the package is not published yet, keep source install primary.

## Version bump

- Update `pyproject.toml::version`.
- Update `readmypaper/__init__.py::__version__`.
- Keep those version sources in sync with the new `CHANGELOG.md` entry.
- Confirm the target version, for example `0.2.0`, and whether it is beta,
  pre-release, or stable.

## Changelog update

- Move completed notes from `[Unreleased]` in `CHANGELOG.md` into a new dated
  version heading, for example `## [0.2.0] - YYYY-MM-DD`.
- Leave a fresh empty `[Unreleased]` section at the top of `CHANGELOG.md`.
- Use the completed version entry as the source for GitHub Release notes.

## Local validation

Use this section as the substitute validation path while GitHub Actions billing
is blocked. Save the command transcript before publishing.

Run lint and format checks:

```bash
ruff check .
ruff format --check .
```

Run tests locally:

```bash
pytest
```

Build the distributions and verify `dist/` contains one wheel and one sdist:

```bash
python -m pip install build
python -c "import pathlib, shutil; shutil.rmtree(pathlib.Path('dist'), ignore_errors=True)"
python -m build
ls dist/
```

Install the built wheel in a fresh virtual environment, then run the installed
app smoke test from outside the source checkout:

```bash
python -m venv /tmp/readmypaper-smoke-venv
/tmp/readmypaper-smoke-venv/bin/python -m pip install --upgrade pip
/tmp/readmypaper-smoke-venv/bin/python -m pip install dist/*.whl
cd /tmp
/tmp/readmypaper-smoke-venv/bin/python - <<'PY'
from fastapi.testclient import TestClient
from readmypaper.main import PACKAGE_DIR, app

assert (PACKAGE_DIR / "templates" / "index.html").is_file()
assert (PACKAGE_DIR / "static" / "app.js").is_file()

with TestClient(app) as client:
    response = client.get("/health")

assert response.status_code == 200
assert response.json() == {"status": "ok"}
PY
```

## Commit and tag

- Commit the version bump, changelog, and any release documentation changes.
- Create an annotated tag from the exact validated commit:

  ```bash
  git tag -a vX.Y.Z -m "ReadMyPaper vX.Y.Z"
  git push origin vX.Y.Z
  ```

## Build

Build wheel and sdist from the validated source commit:

```bash
python -c "import pathlib, shutil; shutil.rmtree(pathlib.Path('dist'), ignore_errors=True)"
python -m build
```

The resulting files must be in `dist/`.

## Publish

Publish only when the release is ready and validation evidence exists. TestPyPI
can be used first for a dry run.

```bash
python -m pip install twine
python -m twine upload dist/*
```

## GitHub Release

- Create the GitHub Release from the exact tag, for example `v0.2.0`.
- Copy the matching `CHANGELOG.md` notes into the release body.
- Attach the validated wheel and sdist, or link to the package index entry.
- Mark beta or pre-release versions with GitHub's pre-release setting.

## Verification

- Confirm the package index sees the version:

  ```bash
  python -m pip index versions readmypaper
  ```

- Install from the intended index in a clean environment.
- Run the `/health` smoke test from the local validation section.
- Confirm the installed CLI reports the expected version:

  ```bash
  readmypaper --version
  ```

- Confirm `README.md` install commands work exactly as written.

## Rollback and abort notes

- If validation fails before publishing, resolve the issue, rebuild, rerun the full
  checklist, and tag only after the final validated commit is ready.
- If a tag was pushed before publication and the release is abandoned, delete the
  remote tag only if no release artifacts have been published from it:

  ```bash
  git push origin :refs/tags/vX.Y.Z
  git tag -d vX.Y.Z
  ```

- If a package was published with a critical issue, publish a fixed patch version
  rather than replacing files for the same version. Yank the bad package index
  release if the index supports yanking and users should avoid it.
- If the README advertised a package install before publication was verified,
  revert that wording to source-install-only until the package index check passes.
