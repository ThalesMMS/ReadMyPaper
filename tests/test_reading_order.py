"""Tests for reading order repair."""

from readmypaper.services.reading_order import repair_reading_order
from readmypaper.types import ExtractedBlock


def _make_block(text: str, page: int, bbox: tuple[float, float, float, float]) -> ExtractedBlock:
    return ExtractedBlock(text=text, label="paragraph", page_no=page, bbox=bbox)


def test_two_column_reordering() -> None:
    """Blocks in a 2-column layout should be ordered left-col then right-col."""
    # Page 612 pts wide.  Left col ≈ 0-280, right col ≈ 320-600.
    blocks = [
        _make_block("right-top", 1, (320, 100, 590, 130)),
        _make_block("left-top", 1, (30, 100, 270, 130)),
        _make_block("left-bottom", 1, (30, 200, 270, 230)),
        _make_block("right-bottom", 1, (320, 200, 590, 230)),
    ]
    page_sizes = {1: (612.0, 792.0)}

    ordered = repair_reading_order(blocks, page_sizes)
    texts = [b.text for b in ordered]

    assert texts.index("left-top") < texts.index("left-bottom")
    assert texts.index("left-bottom") < texts.index("right-top")
    assert texts.index("right-top") < texts.index("right-bottom")


def test_full_width_title_stays_first() -> None:
    """A full-width block (title) near the top stays before column content."""
    blocks = [
        _make_block("col-right", 1, (320, 150, 590, 180)),
        _make_block("col-left", 1, (30, 150, 270, 180)),
        _make_block("title", 1, (30, 30, 580, 70)),
    ]
    page_sizes = {1: (612.0, 792.0)}

    ordered = repair_reading_order(blocks, page_sizes)
    assert ordered[0].text == "title"


def test_single_column_preserves_y_order() -> None:
    """Single-column pages are sorted top-to-bottom."""
    blocks = [
        _make_block("bottom", 1, (50, 400, 550, 430)),
        _make_block("top", 1, (50, 100, 550, 130)),
        _make_block("mid", 1, (50, 250, 550, 280)),
    ]
    page_sizes = {1: (612.0, 792.0)}

    ordered = repair_reading_order(blocks, page_sizes)
    texts = [b.text for b in ordered]
    assert texts == ["top", "mid", "bottom"]


def test_no_bbox_preserves_original_order() -> None:
    """Blocks without bbox keep their original order."""
    blocks = [
        ExtractedBlock(text="a", label="paragraph", page_no=None, bbox=None),
        ExtractedBlock(text="b", label="paragraph", page_no=None, bbox=None),
    ]
    ordered = repair_reading_order(blocks, {})
    assert [b.text for b in ordered] == ["a", "b"]


def test_full_width_block_below_columns_goes_last() -> None:
    """Full-width block below column content should appear after both columns.

    Regression for the removal of the unused col_bottom_y variable — the
    ordering logic for bottom full-width blocks must still work correctly.
    """
    # Two-column layout with a full-width footer below the columns.
    # Page 612 pts wide. Left col ~30-270, right col ~330-590.
    blocks = [
        _make_block("footer", 1, (30, 700, 580, 730)),  # full-width, below columns
        _make_block("right-col", 1, (330, 200, 590, 230)),
        _make_block("left-col", 1, (30, 200, 270, 230)),
        _make_block("title", 1, (30, 50, 580, 80)),  # full-width, above columns
    ]
    page_sizes = {1: (612.0, 792.0)}

    ordered = repair_reading_order(blocks, page_sizes)
    texts = [b.text for b in ordered]

    # Title at the very top, footer at the very bottom.
    assert texts[0] == "title"
    assert texts[-1] == "footer"
    # Both column blocks appear between title and footer.
    assert "left-col" in texts
    assert "right-col" in texts
    assert texts.index("left-col") < texts.index("footer")
    assert texts.index("right-col") < texts.index("footer")


def test_two_column_no_col_bottom_y_variable_side_effect() -> None:
    """Removing col_bottom_y does not affect standard two-column ordering.

    This is an explicit regression guard for the dead-variable removal.
    Previously col_bottom_y = max(...) was computed but never used; its
    removal should be transparent.
    """
    blocks = [
        _make_block("r1", 1, (320, 100, 590, 130)),
        _make_block("l1", 1, (30, 100, 270, 130)),
        _make_block("r2", 1, (320, 300, 590, 330)),
        _make_block("l2", 1, (30, 300, 270, 330)),
        _make_block("r3", 1, (320, 500, 590, 530)),
        _make_block("l3", 1, (30, 500, 270, 530)),
    ]
    page_sizes = {1: (612.0, 792.0)}

    ordered = repair_reading_order(blocks, page_sizes)
    texts = [b.text for b in ordered]

    # All left-col blocks before all right-col blocks.
    last_left = max(texts.index(t) for t in ("l1", "l2", "l3"))
    first_right = min(texts.index(t) for t in ("r1", "r2", "r3"))
    assert last_left < first_right


def test_three_column_reordering() -> None:
    """Three-column pages should be ordered column by column, left to right."""
    blocks = [
        _make_block("c3-top", 1, (430, 100, 590, 130)),
        _make_block("c2-bottom", 1, (220, 250, 380, 280)),
        _make_block("c1-bottom", 1, (30, 250, 170, 280)),
        _make_block("c2-top", 1, (220, 100, 380, 130)),
        _make_block("c3-bottom", 1, (430, 250, 590, 280)),
        _make_block("c1-top", 1, (30, 100, 170, 130)),
    ]
    page_sizes = {1: (612.0, 792.0)}

    ordered = repair_reading_order(blocks, page_sizes)

    assert [b.text for b in ordered] == [
        "c1-top",
        "c1-bottom",
        "c2-top",
        "c2-bottom",
        "c3-top",
        "c3-bottom",
    ]


def test_spanning_block_splits_column_segments() -> None:
    """A block spanning columns should appear between above and below segments."""
    blocks = [
        _make_block("right-bottom", 1, (330, 320, 590, 350)),
        _make_block("left-bottom", 1, (30, 320, 270, 350)),
        _make_block("heading", 1, (30, 230, 590, 260)),
        _make_block("right-top", 1, (330, 120, 590, 150)),
        _make_block("left-top", 1, (30, 120, 270, 150)),
    ]
    page_sizes = {1: (612.0, 792.0)}

    ordered = repair_reading_order(blocks, page_sizes)

    assert [b.text for b in ordered] == [
        "left-top",
        "right-top",
        "heading",
        "left-bottom",
        "right-bottom",
    ]


def test_sidebar_does_not_push_main_title_after_front_matter() -> None:
    """A front-matter sidebar should not force main title/abstract blocks last."""
    blocks = [
        _make_block("main-right", 1, (400, 190, 560, 220)),
        _make_block("sidebar-author", 1, (30, 150, 170, 180)),
        _make_block("title", 1, (220, 100, 560, 125)),
        _make_block("objective", 1, (220, 130, 560, 160)),
        _make_block("main-left", 1, (220, 190, 360, 220)),
    ]
    page_sizes = {1: (612.0, 792.0)}

    ordered = repair_reading_order(blocks, page_sizes)
    texts = [b.text for b in ordered]

    assert texts[:2] == ["title", "objective"]
    assert texts.index("sidebar-author") > texts.index("objective")
