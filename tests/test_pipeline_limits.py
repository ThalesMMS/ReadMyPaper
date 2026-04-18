from __future__ import annotations

import json
from pathlib import Path

import pytest

from readmypaper.config import settings
from readmypaper.services.pdf_extractor import ExtractionResult
from readmypaper.services.pipeline import ReadMyPaperPipeline
from readmypaper.types import ExtractedBlock, ProcessingOptions


class _FakeExtractor:
    def __init__(self, extraction: ExtractionResult) -> None:
        self._extraction = extraction

    def extract(self, pdf_path: Path) -> ExtractionResult:
        return self._extraction


class _FakeTtsEngine:
    def synthesize(self, text: str, *, output_path: Path, options, voice_spec, progress=None):
        del text, options
        output_path.write_bytes(b"RIFF")
        if progress:
            progress(1.0, "Done")
        return output_path, voice_spec


def test_pipeline_rejects_pdf_when_page_count_exceeds_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(settings.__dict__, "max_pdf_pages", 2)
    extraction = ExtractionResult(
        blocks=[],
        page_count=3,
        page_sizes={1: (612.0, 792.0), 2: (612.0, 792.0), 3: (612.0, 792.0)},
        layout_regions=[],
    )
    pipeline = ReadMyPaperPipeline(extractor=_FakeExtractor(extraction))
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    with pytest.raises(
        ValueError,
        match=r"PDF has 3 pages, which exceeds the limit of 2\.",
    ):
        pipeline.process(
            pdf_path=pdf_path,
            output_dir=tmp_path / "output",
            options=ProcessingOptions(),
        )


def test_pipeline_metadata_includes_job_lifecycle_fields(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(settings.__dict__, "max_pdf_pages", 10)
    extraction = ExtractionResult(
        blocks=[ExtractedBlock(text="Hello from the paper body.", label="paragraph", page_no=1)],
        page_count=1,
        page_sizes={1: (612.0, 792.0)},
        layout_regions=[],
    )
    pipeline = ReadMyPaperPipeline(
        extractor=_FakeExtractor(extraction),
        tts_engine_piper=_FakeTtsEngine(),
    )
    pdf_path = tmp_path / "uploads" / "job-123" / "source.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    output_dir = tmp_path / "outputs" / "job-123"

    pipeline.process(
        pdf_path=pdf_path,
        output_dir=output_dir,
        options=ProcessingOptions(
            job_id="job-123",
            filename="paper.pdf",
            created_at="2026-04-16T12:00:00+00:00",
        ),
    )

    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))

    assert metadata["job_id"] == "job-123"
    assert metadata["filename"] == "paper.pdf"
    assert metadata["created_at"] == "2026-04-16T12:00:00+00:00"
