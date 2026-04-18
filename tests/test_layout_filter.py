"""Tests for layout spatial filter."""

from readmypaper.services.layout_filter import _bboxes_overlap, _expand_bbox, filter_by_layout
from readmypaper.types import ExtractedBlock, LayoutRegion


def test_drops_block_inside_picture() -> None:
    """A text block whose bbox is inside a picture region should be dropped."""
    blocks = [
        ExtractedBlock(
            text="Normal paragraph", label="paragraph", page_no=1, bbox=(50, 100, 550, 130)
        ),
        ExtractedBlock(text="Axis label", label="paragraph", page_no=1, bbox=(200, 350, 350, 370)),
    ]
    regions = [
        LayoutRegion(kind="picture", page_no=1, bbox=(180, 300, 400, 500)),
    ]
    kept, dropped = filter_by_layout(blocks, regions)

    assert len(kept) == 1
    assert kept[0].text == "Normal paragraph"
    assert dropped == 1


def test_keeps_block_on_different_page() -> None:
    """A block on a different page from the region should be kept."""
    blocks = [
        ExtractedBlock(text="Page 2 text", label="paragraph", page_no=2, bbox=(200, 350, 350, 370)),
    ]
    regions = [
        LayoutRegion(kind="picture", page_no=1, bbox=(180, 300, 400, 500)),
    ]
    kept, dropped = filter_by_layout(blocks, regions)
    assert len(kept) == 1
    assert dropped == 0


def test_no_regions_keeps_all() -> None:
    """With no layout regions, all blocks are kept."""
    blocks = [
        ExtractedBlock(text="Text", label="paragraph", page_no=1, bbox=(50, 100, 200, 130)),
    ]
    kept, dropped = filter_by_layout(blocks, [])
    assert len(kept) == 1
    assert dropped == 0


def test_short_title_case_near_region_dropped() -> None:
    """Short Title Case blocks near a layout region are dropped."""
    blocks = [
        ExtractedBlock(
            text="Class Activation Map", label="paragraph", page_no=1, bbox=(200, 280, 350, 295)
        ),
    ]
    regions = [
        LayoutRegion(kind="picture", page_no=1, bbox=(180, 300, 400, 500)),
    ]
    kept, dropped = filter_by_layout(blocks, regions)
    # Should be dropped because it's Title Case, short, and close to the picture.
    assert dropped >= 1


# ---------------------------------------------------------------------------
# _expand_bbox — variable rename from l/t/r/b to left/top/right/bottom
# ---------------------------------------------------------------------------


def test_expand_bbox_adds_margin_symmetrically() -> None:
    """_expand_bbox should grow each side by the given margin."""
    result = _expand_bbox((100.0, 200.0, 300.0, 400.0), 10.0)
    assert result == (90.0, 190.0, 310.0, 410.0)


def test_expand_bbox_zero_margin_unchanged() -> None:
    """Zero margin should return the same bbox values."""
    bbox = (50.0, 60.0, 150.0, 160.0)
    assert _expand_bbox(bbox, 0.0) == bbox


def test_expand_bbox_large_margin() -> None:
    """Large margin can produce negative coordinates — that is expected."""
    result = _expand_bbox((10.0, 10.0, 20.0, 20.0), 100.0)
    assert result == (-90.0, -90.0, 120.0, 120.0)


# ---------------------------------------------------------------------------
# _bboxes_overlap — direct unit tests
# ---------------------------------------------------------------------------


def test_bboxes_overlap_clear_horizontal_separation() -> None:
    """Boxes separated horizontally do not overlap."""
    assert _bboxes_overlap(0, 0, 10, 10, 20, 0, 30, 10) is False


def test_bboxes_overlap_clear_vertical_separation() -> None:
    """Boxes separated vertically do not overlap."""
    assert _bboxes_overlap(0, 0, 10, 10, 0, 20, 10, 30) is False


def test_bboxes_overlap_partial_overlap() -> None:
    """Boxes that partially overlap should return True."""
    assert _bboxes_overlap(0, 0, 20, 20, 10, 10, 30, 30) is True


def test_bboxes_overlap_one_inside_other() -> None:
    """A box fully inside another counts as overlapping."""
    assert _bboxes_overlap(0, 0, 100, 100, 20, 20, 80, 80) is True


def test_bboxes_overlap_touching_edge_no_overlap() -> None:
    """Boxes that share only an edge (ar == bl_) are not considered overlapping."""
    assert _bboxes_overlap(0, 0, 10, 10, 10, 0, 20, 10) is False


def test_bboxes_overlap_identical_boxes() -> None:
    """Identical boxes fully overlap."""
    assert _bboxes_overlap(5, 5, 15, 15, 5, 5, 15, 15) is True
