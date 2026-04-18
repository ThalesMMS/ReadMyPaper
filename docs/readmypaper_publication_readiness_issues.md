# ReadMyPaper publication-readiness review

This review is based on the uploaded code bundle. I reconstructed the project locally and ran the included test suite; all 32 tests passed. The core text-processing architecture is solid, but I would still treat the app as **pre-publication / alpha** rather than publish-ready.

## High-level assessment

### What is already strong
- The processing pipeline is well modularized: extraction, reading-order repair, layout filtering, cleaning, verbalization, and TTS are clearly separated.
- The text-cleaning core has unusually good unit coverage for an early-stage app.
- The UI is simple and understandable.
- The project already has a `pyproject.toml`, package entrypoint, and a coherent README narrative.

### What blocks publication
The main blockers are not the algorithmic core. They are release engineering, security hardening, installation consistency, and a few real runtime bugs in the app layer:
- release metadata is inconsistent
- runtime data defaults are unsafe for installed packages
- the optional LLM cleaner ships with private network defaults enabled
- the UI/backend allow invalid TTS engine + voice combinations
- template JSON is embedded unsafely
- uploads/jobs/artifacts have no lifecycle management
- the dependency story is contradictory
- there is no visible CI in the provided tree

## Code references used in this review
- `pyproject.toml:7-12,26-37`
- `readmypaper/__init__.py:1-4`
- `readmypaper/config.py:20-35`
- `readmypaper/main.py:46-113`
- `readmypaper/types.py:90-120`
- `readmypaper/services/pipeline.py:148-166`
- `readmypaper/services/tts_piper.py:23-49`
- `readmypaper/services/voice_catalog.py:152-176`
- `readmypaper/static/app.js:17-36`
- `readmypaper/templates/index.html:35-52,110-114`
- `readmypaper/templates/job.html:73-77`
- `README.md:107-118,127-152,221-253`

---

## Issue 1 — Fix package metadata, ownership, and release files

**Title**  
Fix package metadata, ownership, and release files before publication

**Problem**  
The release metadata is inconsistent and still looks placeholder-level:
- `pyproject.toml` declares version `0.2.0`
- `readmypaper.__version__` is still `0.1.0`
- `authors = [{name = "OpenAI"}]` is not publication-ready metadata
- the provided repository tree does not include a top-level `LICENSE` file even though the package metadata and README both declare GPL-3.0-or-later

**Why this matters**  
Version drift breaks support, bug reports, and release automation. Placeholder authorship and missing license files make the repository look unfinished and can create legal ambiguity.

**Suggested tasks**
- sync `pyproject.toml` and `readmypaper.__version__`
- replace placeholder author metadata with the real maintainer(s)
- add `project.urls` (`Homepage`, `Repository`, `Issues`)
- add Trove classifiers and keywords
- add a top-level `LICENSE` file
- add a minimal `CHANGELOG.md` or release notes entry for the current version

**Acceptance criteria**
- `import readmypaper; readmypaper.__version__` matches package metadata
- the repository includes a LICENSE file consistent with the declared GPL license
- `python -m build` produces valid wheel and sdist metadata
- the package metadata no longer contains placeholder authorship

---

## Issue 2 — Move runtime data out of the package directory

**Title**  
Move runtime data out of the package directory and into per-user app data

**Problem**  
`readmypaper/config.py` defaults `data_dir` to a repo/package-relative `outputs/` directory instead of a per-user application data directory, even though `user_data_dir` is already imported.

**Why this matters**  
This works in a source checkout, but it is brittle for installed-package use because site-packages may not be writable. It also mixes user-generated PDFs/audio with repository files.

**Suggested tasks**
- change the default `data_dir` to `platformdirs.user_data_dir(...)`
- keep caches under `user_cache_dir(...)`
- migrate or detect existing legacy `./outputs` data when upgrading from source-based installs
- clearly print or expose the resolved storage paths in the UI or CLI

**Acceptance criteria**
- the app runs after `pip install .` without needing a writable source tree
- uploaded PDFs, cleaned text, and audio are stored in a per-user writable location by default
- the README documents where runtime data is stored on each supported OS

---

## Issue 3 — Disable the LLM cleaner by default and remove private network defaults

**Title**  
Disable the LLM cleaner by default and remove private network defaults

**Problem**  
Previously identified defaults included:
- a private-network LLM URL
- an internal model path
- the LLM cleaner enabled by default

The README repeated the same private-network example values.

**Why this matters**  
A public repo should not ship with private IP defaults or enabled network features by default. This conflicts with the “local processing” message and makes the feature feel internally hard-coded.

**Suggested tasks**
- set `READMYPAPER_LLM_ENABLED` default to `false`
- set the default base URL to empty or a localhost example only
- remove private/internal model path defaults
- gate the UI checkbox behind an explicit config check or healthcheck
- rewrite README examples to use generic localhost placeholders

**Acceptance criteria**
- a clean install does not expose the LLM cleaner unless the user explicitly configures it
- the repository contains no private IPs or internal model paths
- README examples use safe public placeholders such as `http://127.0.0.1:8000/v1`

---

## Issue 4 — Enforce valid TTS engine and voice combinations

**Title**  
Enforce valid TTS engine and voice combinations in both UI and backend

**Problem**  
The UI filters voices only by language, not by engine. The backend returns any explicitly requested voice immediately, regardless of the selected TTS engine.

This creates a real bug:
- selecting a Kokoro voice while `tts_engine=piper` is allowed
- `pipeline.py` will then fall back to the Piper engine
- `tts_piper.py` calls `VoiceCatalog.ensure_downloaded(voice_spec)`
- for Kokoro specs, `ensure_downloaded` returns `Path(), Path()`
- Piper then attempts to load `PiperVoice.load(str(model_path))`, which is invalid for a Kokoro voice

The opposite mismatch is also possible: choosing a Piper voice while `tts_engine=kokoro` silently results in Piper being used.

**Why this matters**  
This is a publication blocker because the UI currently allows combinations that can fail at runtime or silently ignore the user’s engine choice.

**Suggested tasks**
- filter voice options by both language **and** selected engine in the UI
- validate `voice_key` + `tts_engine` combinations server-side
- return `422` for invalid combinations or auto-reset `voice_key=auto`
- add tests for all valid/invalid combinations
- make the final job metadata explicit about which engine was actually used

**Acceptance criteria**
- the UI never offers invalid engine/voice combinations
- the backend rejects invalid combinations deterministically
- selecting Kokoro always uses Kokoro, and selecting Piper always uses Piper
- automated tests cover the mismatch cases

---

## Issue 5 — Harden browser payload injection and remove path leakage

**Title**  
Harden browser payload injection and remove filesystem path leakage

**Problem**  
The templates inject JSON into `<script>` tags using `| safe`:
- `window.__voices = {{ voices_json | safe }}`
- `window.__job = {{ job_json | safe }}`

At the same time, `JobState.as_dict()` includes absolute filesystem paths for generated artifacts.

**Why this matters**  
Using `| safe` for raw JSON inside a `<script>` block is a known XSS footgun when any field can contain user-controlled content (for example uploaded filenames). Exposing absolute paths to the browser is unnecessary and leaks local filesystem structure.

**Suggested tasks**
- replace manual `json.dumps(...) | safe` with Jinja’s `| tojson`
- remove internal filesystem paths from API responses and browser state
- return public download URLs or boolean readiness flags instead
- add tests for dangerous filenames containing `</script>` and quotes

**Acceptance criteria**
- script payloads are serialized with `tojson`
- no API response exposes internal absolute paths
- malicious filenames cannot break out of the script context
- job pages still function with only public-facing download URLs

---

## Issue 6 — Validate uploads and bound resource usage

**Title**  
Validate uploads and bound resource usage for the `/jobs` endpoint

**Problem**  
The upload endpoint currently:
- trusts the filename extension to decide whether the file is a PDF
- copies the uploaded file directly to disk
- casts `speech_rate` with `float(...)`
- has no visible size limit, page limit, or queue limit

**Why this matters**  
Malformed inputs can trigger 500s, and very large PDFs can consume disk, memory, or processing capacity. Even for a local-first app, public publication should include basic defensive limits.

**Suggested tasks**
- validate MIME type and optionally inspect the first bytes for `%PDF`
- add maximum upload size and page-count limits
- validate numeric form fields with bounded constraints
- return user-facing 4xx errors for invalid input instead of uncaught exceptions
- consider bounding the executor queue or rejecting excessive concurrent jobs

**Acceptance criteria**
- invalid PDFs receive a deterministic 4xx response
- malformed form values do not produce uncaught 500s
- oversized PDFs are rejected with a clear message
- the app cannot enqueue unbounded work indefinitely

---

## Issue 7 — Add artifact retention, deletion, and restart behavior

**Title**  
Add artifact retention, deletion, and explicit restart behavior for jobs

**Problem**  
Each job creates upload/output directories on disk, but the job index is memory-only:
- files persist on disk
- jobs disappear on process restart
- there is no delete endpoint, cleanup command, TTL, or retention policy

**Why this matters**  
This is bad for privacy, disk usage, and user trust. A user can accumulate sensitive PDFs/audio files without any obvious cleanup path, while the app itself forgets the jobs on restart.

**Suggested tasks**
- add a delete-job action that removes uploaded and generated artifacts
- add optional automatic cleanup (TTL or max-age)
- either persist lightweight job metadata across restarts or clearly document that the app is ephemeral
- expose storage usage and cleanup guidance in the UI/README

**Acceptance criteria**
- users can delete a completed job and its files
- the app has a documented retention policy
- restart behavior is deterministic and documented
- automated tests cover deletion/cleanup logic

---

## Issue 8 — Align dependency management, optional extras, and predownload behavior

**Title**  
Align dependency management, optional extras, and voice predownload behavior

**Problem**  
The install story is inconsistent:
- `pyproject.toml` makes Kokoro optional
- `requirements.txt` installs `kokoro` and `soundfile` unconditionally
- the README says Kokoro is optional
- `scripts/predownload_voices.py` iterates through all voice specs, including Kokoro entries, even though `ensure_downloaded()` only downloads Piper files

**Why this matters**  
Users should have exactly one clear installation story. Right now the docs and packaging disagree, which increases support burden and makes failures harder to reason about.

**Suggested tasks**
- decide whether `requirements.txt` is baseline runtime, dev-only, or should be removed
- make the optional-extra story match the actual runtime dependencies
- restrict the predownload script to Piper voices or rename it to reflect its real behavior
- add installation smoke tests for the supported install paths

**Acceptance criteria**
- README, `pyproject.toml`, and `requirements.txt` describe the same install model
- Kokoro is either truly optional everywhere or mandatory everywhere
- the predownload script does exactly what its name claims
- supported install commands are tested in CI

---

## Issue 9 — Add CI for tests, packaging, and app smoke tests

**Title**  
Add GitHub Actions for tests, packaging, and minimal app smoke tests

**Problem**  
The provided tree includes a good unit test suite, but there is no visible CI workflow in the repository bundle.

**Why this matters**  
For a public repo, CI is part of the product. Without it, regressions in packaging, templating, or platform-specific startup will slip into the default branch.

**Suggested tasks**
- add GitHub Actions for `pytest`
- add linting (`ruff`) and optionally formatting checks
- add `python -m build` and install-from-wheel smoke tests
- add a minimal FastAPI startup smoke test
- run the matrix on the OSes you claim to support

**Acceptance criteria**
- every push/PR runs tests automatically
- wheels and sdists build successfully in CI
- the app can start in a clean CI environment
- the README includes CI badges or at least references the workflow status

---

## Issue 10 — Upgrade README from “prototype explanation” to “public release guide”

**Title**  
Upgrade README from prototype explanation to public release guide

**Problem**  
The README explains the pipeline well, but it still leaves release-critical gaps:
- it mixes source-checkout usage with package usage
- it does not clearly explain how to install the package before running `readmypaper`
- it does not document storage locations or cleanup
- it does not define the support matrix beyond a brief macOS/Windows note
- it claims “local” operation while also documenting optional networked LLM configuration

**Why this matters**  
A public repo is judged first by its README. Right now the technical story is good, but the operational story is still too ambiguous for new users.

**Suggested tasks**
- split installation into “from source” vs “installed package”
- add a platform support matrix and required system dependencies
- document where files are stored and how to remove them
- add a short privacy/data-handling section
- add screenshots or a short demo GIF
- add a troubleshooting section for common setup failures

**Acceptance criteria**
- a new user can install and run the app from the README alone
- the README explicitly documents storage, cleanup, and optional network features
- the README includes at least one screenshot or demo artifact
- the support matrix and system dependencies are explicit

---

## Recommended publication order

### Must fix before making the repo public as a polished project
1. Issue 1 — metadata / license / release identity
2. Issue 2 — storage defaults
3. Issue 3 — LLM defaults
4. Issue 4 — TTS engine/voice validation
5. Issue 5 — template hardening and path leakage
6. Issue 8 — dependency/install consistency
7. Issue 9 — CI

### Strongly recommended in the same cycle
8. Issue 6 — upload/resource validation
9. Issue 7 — retention/deletion/restart behavior
10. Issue 10 — README/public docs

## Bottom line

The project already looks like a serious prototype, not a toy. The scientific text-cleaning core is the strongest part and the included tests are a good foundation. The remaining work is mostly about making the app safe, predictable, and legible to strangers.
