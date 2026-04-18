"""Tests for LLM-based ambiguity cleaner (llm_cleaner.py).

Focuses on the changes introduced in this PR:
- classify_ambiguous_blocks now catches `Exception` (not just ImportError)
- _call_llm now receives httpx as an injected parameter
- _parse_response handles markdown fences, list vs dict responses
- select_ambiguous_blocks edge-page logic
- _is_known_heading helper
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from readmypaper.services.llm_cleaner import (
    _group_into_batches,
    _is_known_heading,
    _parse_full_response,
    _parse_response,
    classify_ambiguous_blocks,
    clean_and_reorder_blocks,
    select_ambiguous_blocks,
)
from readmypaper.types import CleaningStats, ExtractedBlock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _block(text: str, label: str = "paragraph", page: int | None = 1) -> ExtractedBlock:
    return ExtractedBlock(text=text, label=label, page_no=page)


def _make_llm_response(results: list[dict]) -> dict:
    """Build a minimal OpenAI-style chat completion response."""
    return {"choices": [{"message": {"content": json.dumps({"results": results})}}]}


# ---------------------------------------------------------------------------
# classify_ambiguous_blocks — httpx import failure handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exception",
    [
        RuntimeError("httpx broken"),
        ImportError("no httpx"),
    ],
)
def test_classify_returns_empty_when_httpx_import_fails(exception: Exception) -> None:
    """Any failure during httpx import should trigger a warning and return {}."""
    blocks = [(0, _block("Some text"))]

    with patch.dict("sys.modules", {"httpx": None}):
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "httpx":
                raise exception
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = classify_ambiguous_blocks(blocks, base_url="http://localhost:8000/v1")

    assert result == {}


def test_classify_returns_empty_for_empty_blocks() -> None:
    """Empty block list should return {} without importing optional dependencies."""
    with patch("builtins.__import__", side_effect=AssertionError("unexpected import")):
        result = classify_ambiguous_blocks([], base_url="http://localhost:8000/v1")
    assert result == {}


def test_classify_passes_httpx_to_call_llm() -> None:
    """classify_ambiguous_blocks should pass the imported httpx module to _call_llm."""
    blocks = [(0, _block("Some scientific finding."))]

    fake_httpx = MagicMock()
    call_llm = MagicMock(return_value={0: ("KEEP", None)})

    with (
        patch.dict("sys.modules", {"httpx": fake_httpx}),
        patch("readmypaper.services.llm_cleaner._call_llm", call_llm),
    ):
        result = classify_ambiguous_blocks(blocks, base_url="http://localhost:8000/v1")

    call_llm.assert_called_once()
    assert call_llm.call_args.kwargs["httpx_module"] is fake_httpx
    assert result == {0: ("KEEP", None)}


def test_classify_updates_stats() -> None:
    """Stats object should be populated with counts after classification."""
    blocks = [
        (0, _block("Keep this sentence about results.")),
        (1, _block("Drop this axis label.")),
        (2, _block("Rewrite this garbled sentence.")),
    ]

    fake_response = MagicMock()
    fake_response.json.return_value = _make_llm_response(
        [
            {"id": 0, "action": "KEEP", "reason": "prose"},
            {"id": 1, "action": "DROP", "reason": "label"},
            {"id": 2, "action": "REWRITE_MINIMAL", "reason": "garbled", "text": "Rewritten."},
        ]
    )
    fake_response.raise_for_status = MagicMock()

    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post = MagicMock(return_value=fake_response)

    fake_httpx = MagicMock()
    fake_httpx.Client = MagicMock(return_value=fake_client)

    stats = CleaningStats(pages=3)

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        result = classify_ambiguous_blocks(
            blocks,
            base_url="http://localhost:8000/v1",
            stats=stats,
        )

    assert stats.llm_blocks_processed == 3
    assert stats.llm_blocks_dropped == 1
    assert stats.llm_blocks_rewritten == 0
    assert len(result) == 3
    assert result[2] == ("KEEP", None)


def test_classify_returns_empty_when_request_fails() -> None:
    """If the HTTP request raises, _call_llm returns {} and classify returns {}."""
    blocks = [(0, _block("Some text."))]

    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post = MagicMock(side_effect=Exception("connection refused"))

    fake_httpx = MagicMock()
    fake_httpx.Client = MagicMock(return_value=fake_client)

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        result = classify_ambiguous_blocks(blocks, base_url="http://localhost:8000/v1")

    assert result == {}


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


def test_parse_response_standard() -> None:
    """Parses a standard {'results': [...]} shaped response."""
    batch = [(10, _block("text A")), (20, _block("text B"))]
    response = _make_llm_response(
        [
            {"id": 10, "action": "KEEP", "reason": "prose"},
            {"id": 20, "action": "DROP", "reason": "label"},
        ]
    )

    result = _parse_response(response, batch)

    assert result[10] == ("KEEP", None)
    assert result[20] == ("DROP", None)


def test_parse_response_legacy_rewrite_minimal_keeps_original() -> None:
    """Legacy REWRITE_MINIMAL responses must not carry replacement text."""
    batch = [(5, _block("garbled text here"))]
    response = _make_llm_response(
        [
            {"id": 5, "action": "REWRITE_MINIMAL", "reason": "junk", "text": "Clean text."},
        ]
    )

    result = _parse_response(response, batch)

    assert result[5] == ("KEEP", None)


def test_parse_response_strips_markdown_fences() -> None:
    """Response wrapped in ```json fences should be parsed correctly."""
    batch = [(0, _block("some content"))]
    inner = json.dumps({"results": [{"id": 0, "action": "KEEP", "reason": "prose"}]})
    response = {"choices": [{"message": {"content": f"```json\n{inner}\n```"}}]}

    result = _parse_response(response, batch)
    assert result[0] == ("KEEP", None)


def test_parse_response_handles_list_response() -> None:
    """Response that is a direct list (not wrapped in 'results') should parse."""
    batch = [(3, _block("some content"))]
    inner = json.dumps([{"id": 3, "action": "DROP", "reason": "boilerplate"}])
    response = {"choices": [{"message": {"content": inner}}]}

    result = _parse_response(response, batch)
    assert result[3] == ("DROP", None)


def test_parse_response_unknown_action_defaults_to_keep() -> None:
    """An unrecognised action string should be normalised to KEEP."""
    batch = [(7, _block("some text"))]
    response = _make_llm_response(
        [
            {"id": 7, "action": "MYSTERY", "reason": "unknown"},
        ]
    )

    result = _parse_response(response, batch)
    assert result[7] == ("KEEP", None)


def test_parse_response_ignores_ids_not_in_batch() -> None:
    """Block IDs not present in the batch should be silently ignored."""
    batch = [(1, _block("text"))]
    response = _make_llm_response(
        [
            {"id": 1, "action": "KEEP", "reason": "ok"},
            {"id": 99, "action": "DROP", "reason": "not in batch"},
        ]
    )

    result = _parse_response(response, batch)
    assert 1 in result
    assert 99 not in result


def test_parse_response_invalid_json_returns_empty() -> None:
    """Invalid JSON in the response content returns an empty dict."""
    batch = [(0, _block("text"))]
    response = {"choices": [{"message": {"content": "this is not json at all"}}]}

    result = _parse_response(response, batch)
    assert result == {}


def test_parse_response_non_string_content_returns_empty() -> None:
    """Non-string response content returns an empty dict."""
    batch = [(0, _block("text"))]
    response = {"choices": [{"message": {"content": None}}]}

    result = _parse_response(response, batch)
    assert result == {}


def test_parse_response_malformed_structure_returns_empty() -> None:
    """Missing 'choices' key should not raise — returns empty dict."""
    batch = [(0, _block("text"))]
    result = _parse_response({}, batch)
    assert result == {}


# ---------------------------------------------------------------------------
# _is_known_heading
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "heading",
    [
        "Abstract",
        "Introduction",
        "Methods",
        "Results",
        "Discussion",
        "Conclusions",
        "References",
        "Acknowledgements",
        "Funding",
        "Author Contributions",
        "Conflicts of Interest",
        "Data Availability",
        "Appendix",
        "1. Introduction",
        "2. Methods",
    ],
)
def test_is_known_heading_recognises_standard_headings(heading: str) -> None:
    assert _is_known_heading(heading) is True


@pytest.mark.parametrize(
    "heading",
    [
        "Experimental Setup",
        "Our Approach",
        "System Architecture",
        "Baseline Comparison",
    ],
)
def test_is_known_heading_rejects_unknown_headings(heading: str) -> None:
    assert _is_known_heading(heading) is False


# ---------------------------------------------------------------------------
# select_ambiguous_blocks — edge-page logic
# ---------------------------------------------------------------------------


def test_select_edge_page_short_block_selected() -> None:
    """Short blocks on first two pages are selected as ambiguous."""
    blocks = [
        ExtractedBlock(text="Short text", label="paragraph", page_no=1),
        ExtractedBlock(text="A" * 200, label="paragraph", page_no=1),  # long block, skip
    ]
    result = select_ambiguous_blocks(blocks, page_count=10)
    texts = [b.text for _, b in result]
    assert "Short text" in texts
    assert "A" * 200 not in texts


def test_select_edge_page_last_two_pages_selected() -> None:
    """Short blocks on last two pages are selected as ambiguous."""
    middle_text = "This middle-page paragraph is long enough to avoid short-fragment selection."
    blocks = [
        ExtractedBlock(text="Last page text", label="paragraph", page_no=10),
        ExtractedBlock(text="Before last", label="paragraph", page_no=9),
        ExtractedBlock(text=middle_text, label="paragraph", page_no=5),
    ]
    result = select_ambiguous_blocks(blocks, page_count=10)
    texts = [b.text for _, b in result]
    assert "Last page text" in texts
    assert "Before last" in texts
    assert middle_text not in texts


def test_select_unknown_section_header_on_edge_page_selected() -> None:
    """Unknown section headers on edge pages should be selected."""
    blocks = [
        ExtractedBlock(text="Our Approach", label="section_header", page_no=1),
        ExtractedBlock(text="Introduction", label="section_header", page_no=1),  # known
    ]
    result = select_ambiguous_blocks(blocks, page_count=10)
    texts = [b.text for _, b in result]
    assert "Our Approach" in texts
    assert "Introduction" not in texts


def test_select_known_section_header_not_selected() -> None:
    """Known section headers should not be sent to the LLM."""
    blocks = [
        ExtractedBlock(text="References", label="section_header", page_no=9),
        ExtractedBlock(text="Acknowledgements", label="section_header", page_no=9),
    ]
    result = select_ambiguous_blocks(blocks, page_count=10)
    assert result == []


def test_select_short_paragraph_in_middle_selected() -> None:
    """Very short paragraph blocks anywhere can be flagged as ambiguous."""
    blocks = [
        ExtractedBlock(text="Short.", label="paragraph", page_no=5),
    ]
    result = select_ambiguous_blocks(blocks, page_count=10)
    texts = [b.text for _, b in result]
    assert "Short." in texts


def test_select_empty_text_blocks_skipped() -> None:
    """Blocks with empty text are always skipped."""
    blocks = [
        ExtractedBlock(text="   ", label="paragraph", page_no=1),
        ExtractedBlock(text="", label="paragraph", page_no=1),
    ]
    result = select_ambiguous_blocks(blocks, page_count=5)
    assert result == []


def test_select_returns_original_indices() -> None:
    """Result tuples carry the original list index (not renumbered)."""
    blocks = [
        ExtractedBlock(text="A" * 200, label="paragraph", page_no=3),  # 0 — not selected
        ExtractedBlock(text="Short", label="paragraph", page_no=1),  # 1 — selected (edge)
    ]
    result = select_ambiguous_blocks(blocks, page_count=10)
    # Only block at index 1 should be selected
    indices = [idx for idx, _ in result]
    assert 1 in indices
    assert 0 not in indices


def test_select_page_count_zero_edge_logic() -> None:
    """When page_count=0, page >= page_count-1 check is skipped gracefully."""
    blocks = [
        ExtractedBlock(
            text="This middle-page paragraph is long enough to avoid metadata selection.",
            label="paragraph",
            page_no=5,
        ),
    ]
    # Should not raise — page_count=0 means the `page >= page_count - 1` branch
    # would otherwise make every page look like trailing end matter.
    result = select_ambiguous_blocks(blocks, page_count=0)
    assert result == []


# ---------------------------------------------------------------------------
# Batch splitting (>20 blocks)
# ---------------------------------------------------------------------------


def test_classify_batches_large_input() -> None:
    """classify_ambiguous_blocks should split >20 blocks into batches."""
    n = 25
    blocks = [(i, _block(f"Block {i}", page=3)) for i in range(n)]
    input_ids = {idx for idx, _ in blocks}

    call_count = 0

    def fake_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        # Parse the user content to get ids
        json_payload = kwargs["json"]
        user_content = json_payload["messages"][1]["content"]
        batch_items = json.loads(user_content)
        results = [{"id": item["id"], "action": "KEEP", "reason": "ok"} for item in batch_items]
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = _make_llm_response(results)
        return resp

    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post = MagicMock(side_effect=fake_post)

    fake_httpx = MagicMock()
    fake_httpx.Client = MagicMock(return_value=fake_client)

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        result = classify_ambiguous_blocks(blocks, base_url="http://localhost:8000/v1")

    # Two batches: 20 + 5
    assert call_count == 2
    assert len(result) == n
    assert set(result) == input_ids


# ---------------------------------------------------------------------------
# _parse_full_response
# ---------------------------------------------------------------------------


def _make_full_response(results: list[dict], order: list[int] | None = None) -> dict:
    """Build an OpenAI-style response with order + results."""
    payload: dict = {"results": results}
    if order is not None:
        payload["order"] = order
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


def test_parse_full_response_with_order() -> None:
    batch = [(0, _block("A")), (1, _block("B")), (2, _block("C"))]
    resp = _make_full_response(
        [
            {"id": 0, "action": "KEEP", "reason": "ok"},
            {"id": 1, "action": "DROP", "reason": "junk"},
            {"id": 2, "action": "KEEP", "reason": "ok"},
        ],
        order=[2, 0],
    )
    results, order = _parse_full_response(resp, batch)
    assert order == [2, 0]
    assert results[1] == ("DROP", None)
    assert results[0] == ("KEEP", None)


def test_parse_full_response_no_order_key() -> None:
    """When the LLM omits 'order', we get an empty list."""
    batch = [(5, _block("text"))]
    resp = _make_full_response(
        [{"id": 5, "action": "KEEP", "reason": "ok"}],
    )
    results, order = _parse_full_response(resp, batch)
    assert order == []
    assert results[5] == ("KEEP", None)


def test_parse_full_response_filters_invalid_order_ids() -> None:
    batch = [(0, _block("A")), (1, _block("B"))]
    resp = _make_full_response(
        [{"id": 0, "action": "KEEP", "reason": "ok"}],
        order=[0, 99, 1],  # 99 is not in the batch
    )
    _, order = _parse_full_response(resp, batch)
    assert order == [0, 1]


def test_parse_full_response_markdown_fences() -> None:
    batch = [(0, _block("text"))]
    inner = json.dumps({
        "order": [0],
        "results": [{"id": 0, "action": "KEEP", "reason": "ok"}],
    })
    resp = {"choices": [{"message": {"content": f"```json\n{inner}\n```"}}]}
    results, order = _parse_full_response(resp, batch)
    assert order == [0]
    assert results[0] == ("KEEP", None)


def test_parse_full_response_invalid_json() -> None:
    batch = [(0, _block("text"))]
    resp = {"choices": [{"message": {"content": "not json"}}]}
    results, order = _parse_full_response(resp, batch)
    assert results == {}
    assert order == []


def test_parse_full_response_legacy_rewrite_minimal_keeps_original() -> None:
    batch = [(0, _block("Original text."))]
    resp = _make_full_response(
        [{"id": 0, "action": "REWRITE_MINIMAL", "reason": "noise", "text": "Changed."}],
        order=[0],
    )
    results, order = _parse_full_response(resp, batch)
    assert order == [0]
    assert results[0] == ("KEEP", None)


# ---------------------------------------------------------------------------
# _group_into_batches
# ---------------------------------------------------------------------------


def test_group_into_batches_single_page() -> None:
    blocks = [(i, _block(f"B{i}", page=1)) for i in range(5)]
    batches = _group_into_batches(blocks)
    assert len(batches) == 1
    assert len(batches[0]) == 5


def test_group_into_batches_splits_by_block_count() -> None:
    """Pages are not split across batches; a new batch starts when limits are hit."""
    blocks = []
    for page in range(1, 6):
        for i in range(5):
            idx = (page - 1) * 5 + i
            blocks.append((idx, _block(f"B{idx}", page=page)))
    # 25 blocks across 5 pages, limit 20 → batch 1 gets pages 1-4 (20), batch 2 page 5 (5)
    batches = _group_into_batches(blocks)
    assert len(batches) == 2
    assert len(batches[0]) == 20
    assert len(batches[1]) == 5


def test_group_into_batches_splits_by_char_count() -> None:
    """When text is large, batches split by char limit."""
    # 3 pages, each with 1 block of 4000 chars; excerpts are capped at 500 chars.
    blocks = [
        (0, _block("A" * 4000, page=1)),
        (1, _block("B" * 4000, page=2)),
        (2, _block("C" * 4000, page=3)),
    ]
    batches = _group_into_batches(blocks)
    assert len(batches) == 1


def test_group_into_batches_none_page() -> None:
    """Blocks with page_no=None are grouped together at the end."""
    blocks = [
        (0, _block("A", page=None)),
        (1, _block("B", page=1)),
        (2, _block("C", page=None)),
    ]
    batches = _group_into_batches(blocks)
    assert len(batches) == 1
    # Page 1 block comes first, then None blocks
    ids = [idx for idx, _ in batches[0]]
    assert ids == [1, 0, 2]


# ---------------------------------------------------------------------------
# clean_and_reorder_blocks
# ---------------------------------------------------------------------------


def _mock_httpx_for_full_clean(response_fn):
    """Create a fake httpx module whose Client.post calls response_fn(body)."""
    def fake_post(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = response_fn(kwargs.get("json", {}))
        return resp

    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post = MagicMock(side_effect=fake_post)

    fake_httpx = MagicMock()
    fake_httpx.Client = MagicMock(return_value=fake_client)
    return fake_httpx, fake_client


def test_clean_and_reorder_drops_junk() -> None:
    blocks = [
        ExtractedBlock(text="Author affiliations", label="paragraph", page_no=1),
        ExtractedBlock(text="Introduction text here.", label="paragraph", page_no=1),
        ExtractedBlock(text="DOI: 10.1234/test", label="paragraph", page_no=1),
    ]

    def respond(body):
        return _make_full_response(
            [
                {"id": 0, "action": "DROP", "reason": "affiliation"},
                {"id": 1, "action": "KEEP", "reason": "prose"},
                {"id": 2, "action": "DROP", "reason": "DOI"},
            ],
            order=[1],
        )

    fake_httpx, _ = _mock_httpx_for_full_clean(respond)
    stats = CleaningStats()

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        result = clean_and_reorder_blocks(
            blocks, page_count=5, base_url="http://localhost:8000/v1", stats=stats,
        )

    assert len(result) == 1
    assert result[0].text == "Introduction text here."
    assert stats.llm_blocks_dropped == 2
    assert stats.llm_blocks_processed == 3


def test_clean_and_reorder_respects_order() -> None:
    blocks = [
        ExtractedBlock(text="Paragraph B", label="paragraph", page_no=1),
        ExtractedBlock(text="Paragraph A", label="paragraph", page_no=1),
    ]

    def respond(body):
        return _make_full_response(
            [
                {"id": 0, "action": "KEEP", "reason": "ok"},
                {"id": 1, "action": "KEEP", "reason": "ok"},
            ],
            order=[1, 0],  # reverse order
        )

    fake_httpx, _ = _mock_httpx_for_full_clean(respond)

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        result = clean_and_reorder_blocks(
            blocks, page_count=5, base_url="http://localhost:8000/v1",
        )

    assert [b.text for b in result] == ["Paragraph A", "Paragraph B"]


def test_clean_and_reorder_legacy_rewrite_keeps_original() -> None:
    blocks = [
        ExtractedBlock(text="Garbled 123 text here", label="paragraph", page_no=1),
    ]

    def respond(body):
        return _make_full_response(
            [{"id": 0, "action": "REWRITE_MINIMAL", "reason": "noise", "text": "Text here."}],
            order=[0],
        )

    fake_httpx, _ = _mock_httpx_for_full_clean(respond)
    stats = CleaningStats()

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        result = clean_and_reorder_blocks(
            blocks, page_count=5, base_url="http://localhost:8000/v1", stats=stats,
        )

    assert len(result) == 1
    assert result[0].text == "Garbled 123 text here"
    assert stats.llm_blocks_rewritten == 0


def test_clean_and_reorder_long_text_is_not_truncated_by_rewrite() -> None:
    original = "A" * 700
    blocks = [
        ExtractedBlock(text=original, label="paragraph", page_no=1),
    ]

    def respond(body):
        assert body["messages"][1]["content"]
        return _make_full_response(
            [{"id": 0, "action": "REWRITE_MINIMAL", "reason": "legacy", "text": "A" * 500}],
            order=[0],
        )

    fake_httpx, _ = _mock_httpx_for_full_clean(respond)
    stats = CleaningStats()

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        result = clean_and_reorder_blocks(
            blocks, page_count=1, base_url="http://localhost:8000/v1", stats=stats,
        )

    assert result[0].text == original
    assert len(result[0].text) == 700
    assert stats.llm_blocks_rewritten == 0


def test_clean_and_reorder_protects_known_headings() -> None:
    """Known section headings must not be dropped even if the LLM says DROP."""
    blocks = [
        ExtractedBlock(text="References", label="section_header", page_no=5),
        ExtractedBlock(text="Some junk", label="paragraph", page_no=5),
    ]

    def respond(body):
        return _make_full_response(
            [
                {"id": 0, "action": "DROP", "reason": "heading"},
                {"id": 1, "action": "DROP", "reason": "junk"},
            ],
            order=[],
        )

    fake_httpx, _ = _mock_httpx_for_full_clean(respond)

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        result = clean_and_reorder_blocks(
            blocks, page_count=10, base_url="http://localhost:8000/v1",
        )

    texts = [b.text for b in result]
    assert "References" in texts
    assert "Some junk" not in texts


def test_clean_and_reorder_fallback_on_failure() -> None:
    """If the LLM request fails, all blocks are returned unchanged."""
    blocks = [
        ExtractedBlock(text="Keep me", label="paragraph", page_no=1),
    ]

    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post = MagicMock(side_effect=Exception("timeout"))

    fake_httpx = MagicMock()
    fake_httpx.Client = MagicMock(return_value=fake_client)

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        result = clean_and_reorder_blocks(
            blocks, page_count=5, base_url="http://localhost:8000/v1",
        )

    assert len(result) == 1
    assert result[0].text == "Keep me"


def test_clean_and_reorder_empty_blocks() -> None:
    result = clean_and_reorder_blocks(
        [], page_count=0, base_url="http://localhost:8000/v1",
    )
    assert result == []


def test_clean_and_reorder_sends_api_key_header() -> None:
    """The Authorization header should be set when api_key is provided."""
    blocks = [
        ExtractedBlock(text="Some text.", label="paragraph", page_no=1),
    ]

    def respond(body):
        return _make_full_response(
            [{"id": 0, "action": "KEEP", "reason": "ok"}],
            order=[0],
        )

    fake_httpx, fake_client = _mock_httpx_for_full_clean(respond)

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        clean_and_reorder_blocks(
            blocks, page_count=5, base_url="http://localhost:8000/v1", api_key="mykey",
        )

    call_kwargs = fake_client.post.call_args
    headers = call_kwargs.kwargs.get("headers", {})
    assert headers.get("Authorization") == "Bearer mykey"
