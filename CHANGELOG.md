# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project
uses semantic versioning.

## [Unreleased]

Current development target: `0.2.0`.

This version has not been tagged, published to a package index, or attached to a
GitHub Release yet. Treat the project as an unpublished source-only beta until
those release artifacts exist.

### Added

- Local FastAPI web UI for uploading scientific PDFs and reviewing cleaned text.
- Scientific-paper cleanup pipeline with reading-order repair, section filtering,
  layout-aware figure/table text removal, and scientific notation verbalisation.
- Local WAV generation with Piper as the default TTS engine and optional Kokoro
  quality TTS support.
- Optional OpenAI-compatible LLM cleanup for ambiguous document blocks.
- Packaging metadata for the future beta package publication.

### Changed

- Synchronized package version metadata and project ownership information for
  the `0.2.0` development target.
