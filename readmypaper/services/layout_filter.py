"""Spatial layout filter — drops text blocks that overlap figures or tables.

Docling already labels ``PictureItem`` and ``TableItem`` entries, but the text
that *was inside* those graphics (axis labels, matrix cells, CAM annotations)
often leaks through as ordinary ``paragraph`` or ``text`` blocks whose bounding
box sits inside or very near the graphical region.

This module eliminates those blocks by checking bbox overlap against known
layout regions (picture / table / caption bounding boxes collected during
extraction).
"""

from __future__ import annotations

import logging
import re

from ..types import ExtractedBlock, LayoutRegion

logger = logging.getLogger(__name__)

# Extra margin (points) around each layout region when checking overlap.
_MARGIN = 12.0

# Short blocks in Title Case with no verb are common for axis labels,
# matrix headers, etc.
_TITLECASE_NON_PROSE_RE = re.compile(r"^(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+|\s+[A-Z]{2,}|\s+\d+)*\s*)$")
_SHORT_BLOCK_THRESHOLD = 60  # characters


def filter_by_layout(
    blocks: list[ExtractedBlock],
    layout_regions: list[LayoutRegion],
    *,
    margin: float = _MARGIN,
) -> tuple[list[ExtractedBlock], int]:
    """Remove text blocks whose bbox overlaps a known non-text layout region.

    Parameters
    ----------
    blocks:
        Text blocks (already reading-order-repaired).
    layout_regions:
        Bounding boxes of pictures, tables, and captions.
    margin:
        Extra margin (in points) applied to each layout region.

    Returns
    -------
    (kept_blocks, n_dropped)
    """
    if not layout_regions:
        return blocks, 0

    # Index regions by page for fast lookup.
    regions_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
    for region in layout_regions:
        expanded = _expand_bbox(region.bbox, margin)
        regions_by_page.setdefault(region.page_no, []).append(expanded)

    kept: list[ExtractedBlock] = []
    n_dropped = 0

    for block in blocks:
        if _should_drop(block, regions_by_page):
            logger.debug("Layout filter dropped: %.60s…", block.text)
            n_dropped += 1
        else:
            kept.append(block)

    if n_dropped:
        logger.info("Layout spatial filter dropped %d blocks", n_dropped)

    return kept, n_dropped


def _should_drop(
    block: ExtractedBlock,
    regions_by_page: dict[int, list[tuple[float, float, float, float]]],
) -> bool:
    """Return True if a block should be dropped due to layout overlap."""
    if block.page_no is None or block.bbox is None:
        return False

    page_regions = regions_by_page.get(block.page_no)
    if not page_regions:
        return False

    bl, bt, br, bb = block.bbox

    for rl, rt, rr, rb in page_regions:
        if _bboxes_overlap(bl, bt, br, bb, rl, rt, rr, rb):
            return True

    # Heuristic: short, Title-Case blocks near layout regions are suspicious
    # (axis labels, matrix headers, CAM labels).
    text = (block.text or "").strip()
    if len(text) <= _SHORT_BLOCK_THRESHOLD and _TITLECASE_NON_PROSE_RE.match(text):
        # Check with a larger margin.
        for rl, rt, rr, rb in page_regions:
            if _bboxes_overlap(bl, bt, br, bb, rl - 30, rt - 30, rr + 30, rb + 30):
                return True

    return False


def _bboxes_overlap(
    al: float,
    at: float,
    ar: float,
    ab: float,
    bl_: float,
    bt_: float,
    br_: float,
    bb_: float,
) -> bool:
    """Return True if box A and box B overlap (any intersection)."""
    if ar <= bl_ or br_ <= al:
        return False
    if ab <= bt_ or bb_ <= at:
        return False
    return True


def _expand_bbox(
    bbox: tuple[float, float, float, float],
    margin: float,
) -> tuple[float, float, float, float]:
    left, top, right, bottom = bbox
    return (left - margin, top - margin, right + margin, bottom + margin)
