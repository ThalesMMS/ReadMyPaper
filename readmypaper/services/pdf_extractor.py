from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..types import ExtractedBlock, LayoutRegion

logger = logging.getLogger(__name__)

# Docling labels to capture as layout regions (non-text obstacles).
_LAYOUT_REGION_LABELS = {"picture", "table", "caption"}


@dataclass(slots=True)
class ExtractionResult:
    """Everything the extractor returns in a single bundle."""

    blocks: list[ExtractedBlock]
    page_count: int
    page_sizes: dict[int, tuple[float, float]]  # {page_no: (width, height)}
    layout_regions: list[LayoutRegion]


class DoclingPdfExtractor:
    """Layout-aware local PDF extractor tuned for scientific papers."""

    def extract(self, pdf_path: Path) -> ExtractionResult:
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:  # pragma: no cover - optional runtime dependency
            raise RuntimeError(
                "Docling is not installed. "
                "Run `pip install docling` or install project dependencies."
            ) from exc

        logger.info("Initializing Docling DocumentConverter …")
        converter = DocumentConverter()
        logger.info("Starting PDF conversion (this may take a few minutes) …")
        result = converter.convert(pdf_path)
        logger.info("PDF conversion finished.")
        document = result.document

        page_count, page_sizes = self._extract_page_info(document)

        blocks: list[ExtractedBlock] = []
        layout_regions: list[LayoutRegion] = []

        for item, _level in document.iterate_items():
            label = self._normalize_label(getattr(item, "label", ""))
            text = getattr(item, "text", "") or ""
            if not text and hasattr(item, "caption_text"):
                try:
                    text = item.caption_text(document) or ""
                except Exception:
                    text = ""

            page_no, bbox = self._extract_provenance(item)
            blocks.append(ExtractedBlock(text=text, label=label, page_no=page_no, bbox=bbox))

            # Collect bounding boxes of non-text elements for the layout filter.
            if label in _LAYOUT_REGION_LABELS and page_no is not None and bbox is not None:
                layout_regions.append(LayoutRegion(kind=label, page_no=page_no, bbox=bbox))

        logger.info(
            "Extraction: %d blocks, %d pages, %d layout regions",
            len(blocks),
            page_count,
            len(layout_regions),
        )
        return ExtractionResult(
            blocks=blocks,
            page_count=page_count,
            page_sizes=page_sizes,
            layout_regions=layout_regions,
        )

    @staticmethod
    def _extract_page_info(document: Any) -> tuple[int, dict[int, tuple[float, float]]]:
        """Return (page_count, {page_no: (width, height)})."""
        pages = getattr(document, "pages", None) or {}
        page_count = len(pages)
        page_sizes: dict[int, tuple[float, float]] = {}

        if isinstance(pages, dict):
            for page_no, page_obj in pages.items():
                size = getattr(page_obj, "size", None)
                if size is not None:
                    w = getattr(size, "width", None)
                    h = getattr(size, "height", None)
                    if w is not None and h is not None:
                        page_sizes[int(page_no)] = (float(w), float(h))
        elif isinstance(pages, (list, tuple)):
            for idx, page_obj in enumerate(pages):
                size = getattr(page_obj, "size", None)
                if size is not None:
                    w = getattr(size, "width", None)
                    h = getattr(size, "height", None)
                    if w is not None and h is not None:
                        page_sizes[idx + 1] = (float(w), float(h))

        return page_count, page_sizes

    @staticmethod
    def _normalize_label(label: Any) -> str:
        value = getattr(label, "value", label)
        return str(value).strip().lower()

    @classmethod
    def _extract_provenance(
        cls, item: Any
    ) -> tuple[int | None, tuple[float, float, float, float] | None]:
        provenance = getattr(item, "prov", None)
        if provenance is None:
            return None, None

        if isinstance(provenance, (list, tuple)):
            provenance = provenance[0] if provenance else None
        if provenance is None:
            return None, None

        page_no = getattr(provenance, "page_no", None)
        bbox = cls._coerce_bbox(getattr(provenance, "bbox", None))
        return page_no, bbox

    @staticmethod
    def _coerce_bbox(bbox: Any) -> tuple[float, float, float, float] | None:
        if bbox is None:
            return None
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            return (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))

        attrs = (
            ("l", "t", "r", "b"),
            ("left", "top", "right", "bottom"),
            ("x0", "y0", "x1", "y1"),
        )
        for names in attrs:
            if all(hasattr(bbox, name) for name in names):
                return tuple(float(getattr(bbox, name)) for name in names)  # type: ignore[return-value]
        return None
