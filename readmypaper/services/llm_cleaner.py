"""LLM-based ambiguity cleaner for blocks that survive deterministic filters.

This module classifies ambiguous text blocks using a local OpenAI-compatible
LLM endpoint.  It is **not** used on all blocks — only on blocks flagged as
potentially problematic:

- Unknown section headings (not in whitelist or droplist)
- Short non-prose fragments that passed the spatial filter
- Blocks from front/end-matter pages (first/last 2 pages)

The LLM returns a strict JSON verdict for each block: KEEP or DROP. It may also
return an order array in the full-block cleaner. The LLM never supplies
replacement text for the final output; excerpts sent to the model are
classification context only.

If the LLM endpoint is unavailable, the pipeline falls back silently (keeps
blocks unchanged).
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from typing import Any

from ..types import CleaningStats, ExtractedBlock

logger = logging.getLogger(__name__)

_BATCH_SIZE = 20  # blocks per LLM call

_SYSTEM_PROMPT = """\
You are a pre-processing filter for a scientific-paper text-to-speech pipeline.
Your task is to classify text blocks extracted from a PDF, deciding whether each
block is suitable for a spoken reading of the paper.

For each block in the list you receive, respond with a JSON object containing:

{
  "results": [
    {
      "id": <int>,
      "action": "KEEP" | "DROP",
      "reason": "<short>"
    }
  ]
}

Guidelines:
- KEEP: The block is useful narrative prose (introduction, methods, results, discussion).
- DROP: The block is NOT useful for listening. Examples: author affiliations, dates,
  keywords, "Received: ...", "Accepted: ...", figure internal labels, table column
  headers, axis labels, dataset names out of context, license boilerplate,
  DOIs, email addresses, ORCID, page numbers, abbreviated metadata.
- Do not rewrite, repair, summarise, paraphrase, or return replacement text.
  The excerpt is only context for deciding KEEP or DROP.

Respond ONLY with the JSON object. No markdown fences, no explanation.
Do NOT include any thinking or reasoning in your output.\
"""

_FULL_CLEAN_SYSTEM_PROMPT = """\
You are a pre-processing filter for a scientific-paper text-to-speech pipeline.
You receive text blocks extracted from PDF pages. Your job is to:

1. Classify each block as KEEP or DROP.
2. Return the IDs of kept blocks in the same relative order as the input.

Actions:
- KEEP: Useful narrative prose (abstract, introduction, methods, results, discussion).
- DROP: Not useful for listening — author affiliations, dates, keywords,
  "Received/Accepted" lines, figure labels, table headers, axis labels,
  DOIs, emails, ORCID, page numbers, journal metadata, license text,
  copyright lines, author lists without context, article-type labels.
- Do not rewrite, repair, summarise, paraphrase, or return replacement text.
  The excerpt is only context for deciding KEEP or DROP.

IMPORTANT: Do NOT drop section headings like "Introduction", "Methods", "Results",
"Discussion", "Conclusions", "References", "Acknowledgements". These are needed
by downstream processing.

The input order is already the best spatial reading order. Do not reorganize
blocks into conceptual paper order. The "order" array is only the list of kept
IDs after DROP decisions, preserving input order.

Respond ONLY with JSON (no markdown fences, no explanation):
{
  "order": [<id>, ...],
  "results": [
    {"id": <int>, "action": "KEEP"|"DROP", "reason": "<short>"}
  ]
}

Do NOT include any thinking or reasoning in your output.\
"""

_PAGE_BATCH_MAX_BLOCKS = 20
_PAGE_BATCH_MAX_CHARS = 6000


def classify_ambiguous_blocks(
    blocks: list[tuple[int, ExtractedBlock]],
    *,
    base_url: str,
    api_key: str = "",
    model: str = "",
    stats: CleaningStats | None = None,
) -> dict[int, tuple[str, str | None]]:
    """Classify *blocks* via the local LLM.

    Parameters
    ----------
    blocks:
        List of (original_index, block) tuples for blocks needing review.
    base_url:
        OpenAI-compatible API base URL, e.g. ``http://127.0.0.1:8000/v1``.
    model:
        Model name to pass in the request (empty = server default).
    stats:
        If provided, counters are updated in place.

    Returns
    -------
    dict mapping original_index -> (action, None).
    Actions are ``"KEEP"`` or ``"DROP"``. Legacy ``"REWRITE_MINIMAL"``
    responses are treated as ``"KEEP"`` without replacement text.
    """
    if not blocks:
        return {}

    try:
        import httpx
    except Exception:
        logger.warning("httpx unavailable — skipping LLM cleaner", exc_info=True)
        return {}

    results: dict[int, tuple[str, str | None]] = {}

    for batch_start in range(0, len(blocks), _BATCH_SIZE):
        batch = blocks[batch_start : batch_start + _BATCH_SIZE]
        batch_result = _call_llm(
            batch,
            base_url=base_url,
            api_key=api_key,
            model=model,
            httpx_module=httpx,
        )
        results.update(batch_result)

    if stats:
        stats.llm_blocks_processed = len(blocks)
        stats.llm_blocks_dropped = sum(1 for _, (a, _) in results.items() if a == "DROP")
        stats.llm_blocks_rewritten = 0

    return results


def _call_llm(
    batch: list[tuple[int, ExtractedBlock]],
    *,
    base_url: str,
    api_key: str = "",
    model: str,
    httpx_module: Any,
) -> dict[int, tuple[str, str | None]]:
    """Call the LLM for a single batch and parse results."""
    user_content = json.dumps(
        [{"id": idx, "excerpt": blk.text[:500], "label": blk.label} for idx, blk in batch],
        ensure_ascii=False,
    )

    body: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
        "max_tokens": 2048,
        # Disable Qwen3.5 thinking/reasoning to get pure JSON output.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if model:
        body["model"] = model

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        with httpx_module.Client(timeout=120) as client:
            resp = client.post(url, json=body, headers=headers)
            resp.raise_for_status()
    except Exception:
        logger.warning("LLM cleaner request failed — keeping all blocks in batch", exc_info=True)
        return {}

    return _parse_response(resp.json(), batch)


def _parse_response(
    response: dict[str, Any],
    batch: list[tuple[int, ExtractedBlock]],
) -> dict[int, tuple[str, str | None]]:
    """Parse the LLM chat-completion response into action decisions."""
    results: dict[int, tuple[str, str | None]] = {}
    valid_ids = {idx for idx, _ in batch}

    try:
        content = response["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            logger.warning("LLM cleaner response content was not text — keeping all blocks")
            return results

        # Strip markdown fences if the model included them despite the prompt.
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[: content.rfind("```")]
        content = content.strip()

        data = json.loads(content)
        items = data if isinstance(data, list) else data.get("results", [])

        for item in items:
            block_id = item.get("id")
            action = str(item.get("action", "KEEP")).upper()
            if action == "REWRITE_MINIMAL":
                action = "KEEP"
            if action not in {"KEEP", "DROP"}:
                action = "KEEP"
            if block_id in valid_ids:
                results[block_id] = (action, None)
    except (json.JSONDecodeError, KeyError, TypeError, IndexError):
        logger.warning(
            "LLM cleaner response could not be parsed — keeping all blocks", exc_info=True
        )

    return results


# Pre-compiled patterns for heading classification (mirrors text_cleaner logic).
# We need these here to avoid sending droplist/whitelist headings to the LLM.
_KNOWN_HEADING_RE = [
    re.compile(p, re.IGNORECASE)
    for p in [
        # Whitelist (body sections)
        r"^(?:\d+\.?\s+)?abstract$",
        r"^(?:\d+\.?\s+)?introduction$",
        r"^(?:\d+\.?\s+)?background$",
        r"^(?:\d+\.?\s+)?methods?$",
        r"^(?:\d+\.?\s+)?materials?\s+and\s+methods?$",
        r"^(?:\d+\.?\s+)?results?$",
        r"^(?:\d+\.?\s+)?discussion$",
        r"^(?:\d+\.?\s+)?conclusions?$",
        r"^(?:\d+\.?\s+)?limitations?$",
        r"^(?:\d+\.?\s+)?related\s+work$",
        r"^(?:\d+\.?\s+)?evaluation$",
        r"^(?:\d+\.?\s+)?experiments?$",
        # Droplist (end-matter) — these are critical: the cleaner uses them to
        # set skip_current_section, so the LLM must NOT remove them.
        r"^references?$",
        r"^bibliography$",
        r"^acknowledge?ments?$",
        r"^funding$",
        r"^author\s+contributions?$",
        r"^conflicts?\s+of\s+interest$",
        r"^competing\s+interests?$",
        r"^ethics",
        r"^declarations?$",
        r"^data\s+availability",
        r"^code\s+availability$",
        r"^supplement",
        r"^appendi",
        r"^consent\s+",
        r"^open\s+access$",
        r"^informed\s+consent$",
    ]
]


def _is_known_heading(text: str) -> bool:
    """Return True if this heading is already handled by the cleaner."""
    stripped = re.sub(r"^\d+\.?\s+", "", text.strip()).strip()
    return any(p.match(stripped) for p in _KNOWN_HEADING_RE)


def select_ambiguous_blocks(
    blocks: list[ExtractedBlock],
    page_count: int,
) -> list[tuple[int, ExtractedBlock]]:
    """Select blocks that need LLM review.

    Criteria for ambiguity:
    1. Blocks on the first or last 2 pages (where front/end matter lives).
    2. Section headers with unknown purpose (NOT headings the cleaner already
       handles — sending droplist headings like 'References' to the LLM would
       cause them to be removed, breaking the cleaner's section-skip logic).
    3. Very short blocks (< 40 chars) that are not already in a KEEP label.
    """
    ambiguous: list[tuple[int, ExtractedBlock]] = []

    for idx, block in enumerate(blocks):
        text = (block.text or "").strip()
        if not text:
            continue

        label = (block.label or "").lower()
        page = block.page_no

        # Blocks on front/end pages are higher risk.
        is_edge_page = page is not None and (
            page <= 2 or (page_count > 0 and page >= page_count - 1)
        )

        # Unknown-purpose section headers — only if the cleaner doesn't
        # already classify them as keep/drop.
        if label in {"section_header", "title"} and is_edge_page:
            if not _is_known_heading(text):
                ambiguous.append((idx, block))
            continue

        # Short blocks on edge pages.
        if is_edge_page and len(text) < 100:
            ambiguous.append((idx, block))
            continue

        # Blocks that look like metadata fragments anywhere.
        if len(text) < 40 and label in {"text", "paragraph", ""}:
            ambiguous.append((idx, block))
            continue

    return ambiguous


# ---------------------------------------------------------------------------
# Full-block LLM cleaner with reading-order repair
# ---------------------------------------------------------------------------


def clean_and_reorder_blocks(
    blocks: list[ExtractedBlock],
    page_count: int,
    *,
    base_url: str,
    api_key: str = "",
    model: str = "",
    stats: CleaningStats | None = None,
) -> list[ExtractedBlock]:
    """Process ALL blocks through the LLM for junk removal and reading-order repair.

    Blocks are grouped by page and sent in batches.  The LLM decides KEEP or
    DROP for each block and returns them in correct reading order. It never
    replaces block text.

    Falls back to the original block list if the LLM is unavailable.
    """
    if not blocks:
        return blocks

    try:
        import httpx
    except Exception:
        logger.warning("httpx unavailable — skipping LLM full cleaner", exc_info=True)
        return blocks

    indexed = list(enumerate(blocks))
    batches = _group_into_batches(indexed)

    all_ordered: list[ExtractedBlock] = []
    total_dropped = 0

    for batch in batches:
        decisions, order = _call_llm_full(
            batch,
            base_url=base_url,
            api_key=api_key,
            model=model,
            httpx_module=httpx,
        )

        # Safety net: never let the LLM drop known section headings.
        for idx, blk in batch:
            label = (blk.label or "").lower()
            if label in {"section_header", "title"} and _is_known_heading(blk.text):
                if idx in decisions and decisions[idx][0] == "DROP":
                    decisions[idx] = ("KEEP", None)

        batch_map = {idx: blk for idx, blk in batch}
        ordered_ids = order if order else [idx for idx, _ in batch]

        for idx in ordered_ids:
            if idx not in batch_map:
                continue
            action, _text = decisions.get(idx, ("KEEP", None))
            if action == "DROP":
                total_dropped += 1
                continue
            blk = batch_map[idx]
            all_ordered.append(blk)

        # Append any batch blocks missing from the order array (keep them).
        seen = set(ordered_ids)
        for idx, blk in batch:
            if idx in seen:
                continue
            action, _text = decisions.get(idx, ("KEEP", None))
            if action == "DROP":
                total_dropped += 1
                continue
            all_ordered.append(blk)

    if stats:
        stats.llm_blocks_processed = len(blocks)
        stats.llm_blocks_dropped = total_dropped
        stats.llm_blocks_rewritten = 0

    logger.info(
        "LLM full cleaner: %d blocks -> %d kept (%d dropped)",
        len(blocks),
        len(all_ordered),
        total_dropped,
    )

    return all_ordered


def _group_into_batches(
    indexed_blocks: list[tuple[int, ExtractedBlock]],
) -> list[list[tuple[int, ExtractedBlock]]]:
    """Group indexed blocks into page-based batches respecting size limits."""
    by_page: dict[int | None, list[tuple[int, ExtractedBlock]]] = defaultdict(list)
    for idx, blk in indexed_blocks:
        by_page[blk.page_no].append((idx, blk))

    batches: list[list[tuple[int, ExtractedBlock]]] = []
    current_batch: list[tuple[int, ExtractedBlock]] = []
    current_chars = 0

    for page_no in sorted(by_page, key=lambda p: (p is None, p or 0)):
        page_blocks = by_page[page_no]
        page_chars = sum(min(len(blk.text or ""), 500) for _, blk in page_blocks)

        if current_batch and (
            len(current_batch) + len(page_blocks) > _PAGE_BATCH_MAX_BLOCKS
            or current_chars + page_chars > _PAGE_BATCH_MAX_CHARS
        ):
            batches.append(current_batch)
            current_batch = []
            current_chars = 0

        current_batch.extend(page_blocks)
        current_chars += page_chars

    if current_batch:
        batches.append(current_batch)

    return batches


def _call_llm_full(
    batch: list[tuple[int, ExtractedBlock]],
    *,
    base_url: str,
    api_key: str,
    model: str,
    httpx_module: Any,
) -> tuple[dict[int, tuple[str, str | None]], list[int]]:
    """Call the LLM with the full-clean prompt.  Returns (decisions, order)."""
    user_content = json.dumps(
        [{"id": idx, "excerpt": blk.text[:500], "label": blk.label} for idx, blk in batch],
        ensure_ascii=False,
    )

    body: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": _FULL_CLEAN_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
        "max_tokens": 4096,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if model:
        body["model"] = model

    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{base_url.rstrip('/')}/chat/completions"

    try:
        with httpx_module.Client(timeout=120) as client:
            resp = client.post(url, json=body, headers=headers)
            resp.raise_for_status()
    except Exception:
        logger.warning(
            "LLM full cleaner request failed — keeping all blocks in batch",
            exc_info=True,
        )
        return {}, []

    return _parse_full_response(resp.json(), batch)


def _parse_full_response(
    response: dict[str, Any],
    batch: list[tuple[int, ExtractedBlock]],
) -> tuple[dict[int, tuple[str, str | None]], list[int]]:
    """Parse LLM response that includes an ``order`` array."""
    results: dict[int, tuple[str, str | None]] = {}
    order: list[int] = []
    valid_ids = {idx for idx, _ in batch}

    try:
        content = response["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            return results, order

        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[: content.rfind("```")]
        content = content.strip()

        data = json.loads(content)

        if isinstance(data, dict):
            raw_order = data.get("order", [])
            order = [i for i in raw_order if isinstance(i, int) and i in valid_ids]
            items = data.get("results", [])
        else:
            items = data if isinstance(data, list) else []

        for item in items:
            block_id = item.get("id")
            action = str(item.get("action", "KEEP")).upper()
            if action == "REWRITE_MINIMAL":
                action = "KEEP"
            if action not in {"KEEP", "DROP"}:
                action = "KEEP"
            if block_id in valid_ids:
                results[block_id] = (action, None)
    except (json.JSONDecodeError, KeyError, TypeError, IndexError):
        logger.warning(
            "LLM full cleaner response parse failed — keeping all blocks",
            exc_info=True,
        )

    return results, order
