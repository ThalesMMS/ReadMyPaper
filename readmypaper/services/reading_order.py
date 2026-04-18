"""Reading-order repair for multi-column scientific PDFs.

Docling's ``iterate_items`` usually respects reading order, but multi-column
papers can still produce interleaved text when blocks straddle columns or when
the layout model struggles with mixed figure/text pages.

This module re-sorts ``ExtractedBlock`` objects by detecting columns on each
page. Blocks that span multiple detected columns are kept as vertical anchors;
the column text between those anchors is ordered top-to-bottom within each
column, left-to-right across columns.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

from ..types import ExtractedBlock

logger = logging.getLogger(__name__)

# Blocks wider than this fraction of the page width are assumed to be
# full-width (titles, abstracts, full-width figures).
_FULL_WIDTH_RATIO = 0.60

# Minimum horizontal gap (as a fraction of page width) between the two column
# centres to split them into separate columns.
_COLUMN_GAP_RATIO = 0.10

# Ignore wider blocks when detecting column centres; they are often headings,
# abstracts, or figure/caption blocks that span multiple text columns.
_COLUMN_DETECTION_MAX_WIDTH_RATIO = 0.50

# Scientific layouts rarely use more than four prose columns. Extra clusters
# are usually noise from sidebars, marginalia, or mixed figure/text regions.
_MAX_COLUMNS = 4

# Small tolerance around column centres when deciding whether a block spans
# more than one detected column.
_COLUMN_SPAN_MARGIN = 4.0

# Treat blocks with nearly identical top coordinates as being on the same
# horizontal band, so spanning headings are not displaced by neighboring text.
_Y_TOLERANCE = 3.0


@dataclass(frozen=True, slots=True)
class _Column:
    center: float
    left: float
    right: float


def repair_reading_order(
    blocks: list[ExtractedBlock],
    page_sizes: dict[int, tuple[float, float]],
) -> list[ExtractedBlock]:
    """Re-order *blocks* to restore a natural left-to-right, top-to-bottom
    reading order suitable for listening.

    Parameters
    ----------
    blocks:
        Extracted text blocks with ``page_no`` and ``bbox`` (l, t, r, b).
    page_sizes:
        Mapping ``{page_no: (width, height)}``.  Used to normalise x-coordinates
        when detecting columns.

    Returns
    -------
    list[ExtractedBlock]
        The same blocks but re-ordered.
    """
    if not blocks:
        return blocks

    by_page: dict[int | None, list[tuple[int, ExtractedBlock]]] = defaultdict(list)
    for idx, blk in enumerate(blocks):
        by_page[blk.page_no].append((idx, blk))

    ordered: list[ExtractedBlock] = []

    for page_no in sorted(by_page, key=lambda p: (p is None, p or 0)):
        page_blocks = by_page[page_no]
        if page_no is None or page_no not in page_sizes:
            # No spatial info — keep original order.
            ordered.extend(blk for _, blk in page_blocks)
            continue

        page_w, page_h = page_sizes[page_no]
        if page_w <= 0 or page_h <= 0:
            ordered.extend(blk for _, blk in page_blocks)
            continue

        ordered.extend(_order_page(page_blocks, page_w, page_h))

    return ordered


def _order_page(
    page_blocks: list[tuple[int, ExtractedBlock]],
    page_width: float,
    page_height: float,
) -> list[ExtractedBlock]:
    """Sort blocks on a single page respecting column layout."""

    with_bbox: list[tuple[int, ExtractedBlock]] = []
    no_bbox: list[tuple[int, ExtractedBlock]] = []

    for item in page_blocks:
        if item[1].bbox is not None:
            with_bbox.append(item)
        else:
            no_bbox.append(item)

    if not with_bbox:
        return [blk for _, blk in page_blocks]

    columns = _detect_columns(with_bbox, page_width)

    if len(columns) <= 1:
        # Single column — just sort by y then original index.
        combined = with_bbox + no_bbox
        combined.sort(key=lambda item: (_bbox_y(item[1], page_height), item[0]))
        return [blk for _, blk in combined]

    spanning: list[tuple[int, ExtractedBlock]] = []
    column_items: list[tuple[int, tuple[int, ExtractedBlock]]] = []

    for item in with_bbox:
        if _spans_multiple_columns(item[1], columns, page_width):
            spanning.append(item)
        else:
            column_items.append((_nearest_column(item[1], columns), item))

    spanning.sort(key=lambda item: (_bbox_y(item[1], page_height), item[0]))

    result: list[ExtractedBlock] = []
    remaining = column_items

    for span in spanning:
        span_y = _bbox_y(span[1], page_height)
        before = [
            item
            for item in remaining
            if _bbox_y(item[1][1], page_height) < span_y - _Y_TOLERANCE
        ]
        if before:
            result.extend(_order_column_segment(before, len(columns), page_height))
            before_ids = {item[1][0] for item in before}
            remaining = [item for item in remaining if item[1][0] not in before_ids]
        result.append(span[1])

    if remaining:
        result.extend(_order_column_segment(remaining, len(columns), page_height))
    result.extend(blk for _, blk in no_bbox)

    return result


def _detect_columns(
    blocks: list[tuple[int, ExtractedBlock]],
    page_width: float,
) -> list[_Column]:
    """Detect 1-N text columns using horizontal midpoint clusters.

    Returns a single full-page column when there is not enough evidence for a
    multi-column layout.
    """
    default = [_Column(center=page_width / 2, left=0.0, right=page_width)]
    if len(blocks) < 3:
        return default

    candidates: list[tuple[float, float, float]] = []
    max_candidate_width = page_width * _COLUMN_DETECTION_MAX_WIDTH_RATIO
    for _idx, block in blocks:
        if block.bbox is None:
            continue
        left, _top, right, _bottom = block.bbox
        width = right - left
        if width <= 0 or width >= max_candidate_width:
            continue
        midpoint = (left + right) / 2
        candidates.append((midpoint, left, right))

    if len(candidates) < 3:
        return default

    candidates.sort(key=lambda item: item[0])
    min_gap = page_width * _COLUMN_GAP_RATIO
    clusters: list[list[tuple[float, float, float]]] = [[candidates[0]]]

    for candidate in candidates[1:]:
        previous_midpoint = clusters[-1][-1][0]
        if candidate[0] - previous_midpoint >= min_gap:
            clusters.append([candidate])
        else:
            clusters[-1].append(candidate)

    if len(clusters) <= 1:
        return default

    while len(clusters) > _MAX_COLUMNS:
        merge_at = _closest_cluster_pair(clusters)
        clusters[merge_at].extend(clusters.pop(merge_at + 1))
        clusters[merge_at].sort(key=lambda item: item[0])

    columns = [_make_column(cluster) for cluster in clusters]
    columns.sort(key=lambda column: column.center)
    return columns


def _closest_cluster_pair(clusters: list[list[tuple[float, float, float]]]) -> int:
    """Return the index of the closest adjacent cluster pair."""
    best_idx = 0
    best_gap = float("inf")
    centers = [_cluster_center(cluster) for cluster in clusters]
    for idx in range(len(centers) - 1):
        gap = centers[idx + 1] - centers[idx]
        if gap < best_gap:
            best_gap = gap
            best_idx = idx
    return best_idx


def _make_column(cluster: list[tuple[float, float, float]]) -> _Column:
    return _Column(
        center=_cluster_center(cluster),
        left=min(item[1] for item in cluster),
        right=max(item[2] for item in cluster),
    )


def _cluster_center(cluster: list[tuple[float, float, float]]) -> float:
    return sum(item[0] for item in cluster) / len(cluster)


def _spans_multiple_columns(
    block: ExtractedBlock,
    columns: list[_Column],
    page_width: float,
) -> bool:
    if block.bbox is None or len(columns) <= 1:
        return False

    left, _top, right, _bottom = block.bbox
    width = right - left
    if width >= page_width * _FULL_WIDTH_RATIO:
        return True

    covered_centers = sum(
        1
        for column in columns
        if left - _COLUMN_SPAN_MARGIN <= column.center <= right + _COLUMN_SPAN_MARGIN
    )
    return covered_centers >= 2


def _nearest_column(block: ExtractedBlock, columns: list[_Column]) -> int:
    if block.bbox is None:
        return 0
    left, _top, right, _bottom = block.bbox
    midpoint = (left + right) / 2
    return min(
        range(len(columns)),
        key=lambda idx: (abs(columns[idx].center - midpoint), idx),
    )


def _order_column_segment(
    column_items: list[tuple[int, tuple[int, ExtractedBlock]]],
    n_columns: int,
    page_height: float,
) -> list[ExtractedBlock]:
    ordered: list[ExtractedBlock] = []
    by_column: dict[int, list[tuple[int, ExtractedBlock]]] = defaultdict(list)

    for column_idx, item in column_items:
        by_column[column_idx].append(item)

    for column_idx in range(n_columns):
        items = by_column.get(column_idx, [])
        items.sort(key=lambda item: (_bbox_y(item[1], page_height), item[0]))
        ordered.extend(block for _idx, block in items)

    return ordered


def _bbox_y(block: ExtractedBlock, page_height: float) -> float:
    """Return visual distance from the top of the page.

    Some extractors use a top-left origin (top < bottom); Docling provenance for
    PDFs commonly uses a bottom-left origin (top > bottom). Normalising here
    keeps the ordering code independent of that coordinate convention.
    """
    if block.bbox is None:
        return 0.0
    top = block.bbox[1]
    bottom = block.bbox[3]
    if top <= bottom:
        return top
    return page_height - top
