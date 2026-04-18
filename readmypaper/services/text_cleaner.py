from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable

try:
    from langdetect import DetectorFactory, LangDetectException, detect
except ImportError:  # pragma: no cover - lightweight fallback for tests / minimal installs

    class LangDetectException(Exception):
        """Fallback exception when langdetect is unavailable."""

    def detect(text: str) -> str:
        sample = text.casefold()
        portuguese_markers = ["ção", "ções", "não", "para", "com ", "uma ", "este ", "portugu"]
        score = sum(marker in sample for marker in portuguese_markers)
        return "pt" if score >= 2 else "en"

    class DetectorFactory:  # pragma: no cover
        seed = 0


from ..types import CleaningStats, ExtractedBlock, ProcessingOptions

DetectorFactory.seed = 0

# ---------------------------------------------------------------------------
# Label sets for Docling item types
# ---------------------------------------------------------------------------

KEEP_LABELS = {
    "title",
    "section_header",
    "paragraph",
    "text",
    "list_item",
}

DROP_LABELS = {
    "caption",
    "chart",
    "code",
    "document_index",
    "footnote",
    "formula",
    "page_footer",
    "page_header",
    "picture",
    "reference",
    "table",
}

# ---------------------------------------------------------------------------
# Section whitelist / droplist  (Phase 2)
# ---------------------------------------------------------------------------

# Sections that should be KEPT for listening (case-insensitive).
_WHITELIST_SECTIONS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"^abstract$",
        r"^resumo$",
        r"^introduction$",
        r"^introdu[cç][aã]o$",
        r"^background$",
        r"^contexto$",
        r"^methods?$",
        r"^m[eé]todos?$",
        r"^materials?\s+and\s+methods?$",
        r"^materiais?\s+e\s+m[eé]todos?$",
        r"^methodology$",
        r"^metodologia$",
        r"^experimental\s+(?:setup|design|methods?)$",
        r"^results?$",
        r"^resultados?$",
        r"^results?\s+and\s+discussion$",
        r"^resultados?\s+e\s+discuss[aã]o$",
        r"^discussion$",
        r"^discuss[aã]o$",
        r"^conclusions?$",
        r"^conclus[oõ]es?$",
        r"^limitations?$",
        r"^limita[cç][oõ]es?$",
        r"^related\s+work$",
        r"^trabalhos?\s+relacionados?$",
        r"^literature\s+review$",
        r"^revis[aã]o\s+(?:da\s+)?literatura$",
        r"^overview$",
        r"^proposed\s+(?:method|approach|framework|model|system)$",
        r"^implementation$",
        r"^implementa[cç][aã]o$",
        r"^evaluation$",
        r"^avalia[cç][aã]o$",
        r"^analysis$",
        r"^an[aá]lise$",
        r"^experiments?$",
        r"^experimentos?$",
        r"^case\s+stud(?:y|ies)$",
        r"^estudo(?:s)?\s+de\s+caso$",
        r"^clinical\s+(?:significance|implications?)$",
        r"^future\s+(?:work|directions?)$",
        r"^trabalhos?\s+futuros?$",
        # Numbered sections (e.g. "1. Introduction", "2 Methods")
        r"^\d+\.?\s+",
    ]
]

# Sections that should be DROPPED (end-matter, metadata, etc.).
_REFERENCE_SECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"^references?$",
        r"^bibliography$",
        r"^refer[eê]ncias?$",
        r"^bibliografia$",
        r"^literature\s+cited$",
    ]
]

_ACKNOWLEDGEMENT_SECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"^acknowledge?ments?$",
        r"^agradecimentos?$",
        r"^funding$",
        r"^financiamento$",
        r"^author\s+contributions?$",
        r"^contribui[cç][oõ]es?\s+dos?\s+autores?$",
        r"^conflicts?\s+of\s+interest$",
        r"^conflitos?\s+de\s+interesse$",
        r"^competing\s+interests?$",
        r"^ethics?\s*(?:statement|approval)?$",
        r"^declara[cç][aã]o\s+de\s+[eé]tica$",
        r"^declarations?$",
        r"^declara[cç][oõ]es?$",
        r"^data\s+availability\s*(?:statement)?$",
        r"^disponibilidade\s+(?:de\s+)?dados$",
        r"^code\s+availability$",
        r"^consent\s+(?:for\s+)?(?:publication|to\s+participate)?$",
        r"^consentimento$",
        r"^open\s+access$",
        r"^acesso\s+aberto$",
        r"^publisher['']?s?\s+note$",
        r"^nota\s+do\s+editor$",
        r"^author\s+(?:details?|information)$",
        r"^(?:about|information\s+about)\s+(?:the\s+)?authors?$",
        r"^corresponding\s+author$",
        r"^how\s+to\s+cite$",
        r"^como\s+citar$",
        r"^credit\s+author$",
        r"^informed\s+consent$",
    ]
]

_APPENDIX_SECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"^supplement(?:ary|al)?\s+(?:materials?|information|data)$",
        r"^material\s+suplementar$",
        r"^informa[cç][aã]o\s+suplementar$",
        r"^appendi(?:x|ces)$",
        r"^ap[eê]ndice(?:s)?$",
        r"^additional\s+files?$",
        r"^abbreviations?$",
        r"^abrevia[cç][oõ]es?$",
    ]
]

_DROPLIST_SECTIONS = [
    *_REFERENCE_SECTION_PATTERNS,
    *_ACKNOWLEDGEMENT_SECTION_PATTERNS,
    *_APPENDIX_SECTION_PATTERNS,
]

# Article-type labels that appear as headings in some layouts.
# These should be dropped as headings but must NOT activate skip_current_section
# (they appear at the top of the paper, before the real body sections).
_ARTICLE_TYPE_SECTIONS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"^technical\s+note$",
        r"^research\s+article$",
        r"^original\s+(?:article|research|paper)$",
        r"^review\s+article$",
        r"^case\s+report$",
        r"^short\s+communication$",
        r"^letter\s+to\s+(?:the\s+)?editor$",
        r"^brief\s+report$",
    ]
]

# ---------------------------------------------------------------------------
# Front-matter line regex (Phase 2)
# ---------------------------------------------------------------------------

_FRONT_MATTER_LINE_RE = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"^Received:?\s",
        r"^Accepted:?\s",
        r"^Published:?\s",
        r"^Revised:?\s",
        r"^Submitted:?\s",
        r"^Available\s+online:?\s",
        r"^https?://",
        r"^doi:\s*10\.",
        r"^DOI:\s*10\.",
        r"^\d+\.\d+/",
        r"^Keywords?:?\s",
        r"^Key\s*words?:?\s",
        r"^Palavras[\-\s]?chave:?\s",
        r"^Corresponding\s+author",
        r"^[*†‡§¶‖]\s*\w",
        r"^e[\-\s]?mail:",
        r"^Email:",
        r"^ORCID:",
        r"^©\s",
        r"^Copyright\s",
        r"^ISSN\s",
        r"^Volume\s+\d",
        r"^Article\s+(?:ID|number|info)",
        r"^Cite\s+(?:this|as)",
        r"^Editor:?\s",
        r"^Academic\s+Editor",
        r"^Handling\s+editor",
        r"^Reviewer",
        r"^TECHNICAL\s+NOTE",
        r"^RESEARCH\s+ARTICLE",
        r"^ORIGINAL\s+(?:ARTICLE|RESEARCH|PAPER)",
        r"^REVIEW\s+ARTICLE",
        r"^CASE\s+REPORT",
        r"^SHORT\s+COMMUNICATION",
        r"^LETTER\s+TO\s+(?:THE\s+)?EDITOR",
        r"^BRIEF\s+REPORT",
    ]
]

# ---------------------------------------------------------------------------
# End-matter prefixes (Phase 2)
# ---------------------------------------------------------------------------

_END_MATTER_PREFIXES = [
    "Supplementary Information",
    "Supplementary Material",
    "Additional file",
    "Publisher's Note",
    "Publisher's note",
    "Springer Nature",
    "Open Access This article",
    "Creative Commons",
    "How to cite this article",
    "This article is licensed under",
    "This is an open access article",
    "This is an Open Access article",
    "Distributed under the terms",
    "Disponível em:",
    "Acesso aberto",
]

# Inline end-matter headings: paragraph blocks that START with an end-matter
# section label followed by body text (common when Docling merges heading + body).
_INLINE_END_MATTER_RE = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"^Ethics\s+approval\b",
        r"^Consent\s+to\s+(?:participate|publication)\b",
        r"^Consent\s+for\s+publication\b",
        r"^Data\s+availability\b",
        r"^Code\s+availability\b",
        r"^Author\s+contributions?\b",
        r"^Acknowledgements?\b",
        r"^Acknowledgments?\b",
        r"^Conflicts?\s+of\s+interest\b",
        r"^Competing\s+interests?\b",
        r"^Funding\b",
        r"^Declarations?\b",
        r"^Informed\s+consent\b",
    ]
]

# Reference / bibliography entry pattern.
# Matches lines like: "Smith JA, Doe B (2024) Title of paper. Journal Name 12:345-350"
# or "Frid-Adar M, Ben-Cohen A et al Title. J Name 12:345"
_REFERENCE_ENTRY_RE = re.compile(
    r"^[A-ZÀ-Ý][a-zà-ý]+(?:[-'][A-Za-zÀ-ýà-ý]+)*\s+[A-ZÀ-Ý]{1,3}(?:,|\s+).*?(?:"
    r"\d+:\d+|pp\.?\s+\d+|vol\.?\s+\d+|Proc\.|Conf\.|"
    r"J\s+[A-Z]|Sci\s+Rep|Nature|Lancet|BMJ|Radiol|Neurosurg|Psychiatry|"
    r"Imaging|Med\s|Surg\s|Biomed|PLoS|arXiv|Springer|Elsevier|Wiley|"
    r"Ann[.,]|Cham[.,]|Int\s+J\s|Eur\s+J\s|Am\s+J\s|Br\s+J\s|"
    r"\(eds?\)|In:\s|Nerv\s+Syst|Neurol\s+J|Open\s+\w+\s+J|"
    r"https?://|doi\.?\s*(?:org|10\.)|Res\s+Technol|Skin\s+Res|"
    r"Pathol|Oncol|Clin\s|Acta\s|Comput|Inform"
    r")",
    re.IGNORECASE,
)

_NUMBERED_REFERENCE_RE = re.compile(
    r"^(?:\[\d+\]\s*|\d{1,3}\.\s+)[A-ZÀ-Ý][a-zà-ý]",
)

# ---------------------------------------------------------------------------
# Existing regex patterns (preserved from v1)
# ---------------------------------------------------------------------------

NUMERIC_CITATION_RE = re.compile(r"\s*\[(?:\d+\s*(?:[-–,;]\s*\d+)*)\]")
PAREN_NUMERIC_CITATION_RE = re.compile(r"\s*\((?:\d+\s*(?:[-–,;]\s*\d+)*)\)")
MULTISPACE_RE = re.compile(r"[ \t]{2,}")
MULTINEWLINE_RE = re.compile(r"\n{3,}")
CAPTION_RE = re.compile(
    r"^(?:figure|fig\.?|table|figura|tabela|supplementary figure|supplementary table)\s+\d+",
    re.IGNORECASE,
)
PAGE_NUM_RE = re.compile(r"^(?:page\s+)?\d{1,4}$", re.IGNORECASE)
TABLEISH_RE = re.compile(r"\|.+\||(?:\S+\s{3,}\S+\s{3,}\S+)")
NUMERIC_HEAVY_RE = re.compile(r"^[\d\s.,;%/()+\-–=]+$")

# Affiliation-like patterns: "1 Department of ...", "a University of ..."
_AFFILIATION_RE = re.compile(
    r"^(?:\d{1,2}\s+)?(?:Department|Faculty|School|Institute|Center|Centre|"
    r"Laboratory|Hospital|University|College|Universidade|Faculdade|Instituto|"
    r"Departamento|Laboratório|Hospital)\b",
    re.IGNORECASE,
)

# Email pattern.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# ORCID pattern.
_ORCID_RE = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]")


class ScientificTextCleaner:
    def __init__(self, options: ProcessingOptions) -> None:
        self.options = options

    def clean(
        self, blocks: Iterable[ExtractedBlock], page_count: int = 0
    ) -> tuple[str, CleaningStats]:
        stats = CleaningStats(pages=page_count)
        block_list = list(blocks)
        stats.total_blocks = len(block_list)
        repeated_furniture = self._find_repeated_furniture(block_list)

        kept_parts: list[str] = []
        skip_current_section = False

        for block in block_list:
            label = self._normalize_label(block.label)
            raw_text = block.text or ""
            text = self._normalize_text(raw_text)

            if not text:
                self._drop(stats, "empty")
                continue

            if label in DROP_LABELS:
                # When we see a 'reference'-labeled block, also activate
                # section skip so subsequent paragraph-labeled reference
                # entries (mislabeled by Docling) are caught.
                if label == "reference":
                    skip_current_section = True
                self._drop(stats, label, by_label=True)
                continue

            if label not in KEEP_LABELS and label:
                # Unknown labels are allowed only if the text looks like normal prose.
                if self._looks_like_non_prose(text):
                    self._drop(stats, f"non_prose:{label}")
                    continue

            if text.casefold() in repeated_furniture:
                self._drop(stats, "repeated_furniture")
                continue

            # ----- Section heading handling (whitelist-based) -----
            if label in {"title", "section_header"}:
                heading_action = self._classify_heading(text)

                if heading_action == "drop":
                    skip_current_section = True
                    self._drop(stats, "section_heading_drop")
                    continue
                elif heading_action == "drop_heading_only":
                    # Article-type labels are dropped but don't skip body.
                    self._drop(stats, "section_heading_drop")
                    continue
                elif heading_action == "keep":
                    skip_current_section = False
                    if self.options.keep_headings:
                        kept_parts.append(text)
                        stats.kept_blocks += 1
                    continue
                else:
                    # "unknown" — keep the heading, don't skip the section.
                    skip_current_section = False
                    if self.options.keep_headings:
                        kept_parts.append(text)
                        stats.kept_blocks += 1
                    continue

            if skip_current_section:
                self._drop(stats, "section_skip")
                continue

            if CAPTION_RE.match(text):
                self._drop(stats, "caption_like")
                continue

            if PAGE_NUM_RE.match(text):
                self._drop(stats, "page_number")
                continue

            if self._looks_like_table_line(text):
                self._drop(stats, "table_like")
                continue

            if self._looks_like_non_prose(text):
                self._drop(stats, "non_prose")
                continue

            # Front-matter line check.
            if self._is_front_matter_line(text):
                self._drop(stats, "front_matter")
                continue

            # End-matter prefix check.
            if self._is_end_matter_line(text):
                self._drop(stats, "end_matter")
                continue

            # Inline end-matter heading (paragraph starting with end-matter label).
            if self._is_inline_end_matter(text):
                self._drop(stats, "inline_end_matter")
                continue

            # Reference / bibliography entry detection.
            if self._looks_like_reference_entry(text):
                self._drop(stats, "reference_entry")
                continue

            # Affiliation / institutional lines.
            if self._looks_like_affiliation(text):
                self._drop(stats, "affiliation")
                continue

            if self.options.remove_numeric_citations:
                text = self._remove_numeric_citations(text)
                text = self._normalize_text(text)
                if not text:
                    self._drop(stats, "citations_only")
                    continue

            kept_parts.append(text)
            stats.kept_blocks += 1

        cleaned_text = self._merge_parts(kept_parts)
        stats.dropped_blocks = stats.total_blocks - stats.kept_blocks
        stats.detected_language = self.detect_language(cleaned_text)
        return cleaned_text, stats

    def detect_language(self, text: str) -> str:
        sample = (text or "").strip()
        if not sample:
            return "unknown"
        sample = sample[:4000]
        try:
            lang = detect(sample)
        except LangDetectException:
            return "unknown"
        if lang.startswith("pt"):
            return "pt-BR"
        if lang.startswith("en"):
            return "en"
        return lang

    def split_text(self, text: str, max_chars: int | None = None) -> list[str]:
        limit = max_chars or self.options.chunk_max_chars
        normalized = self._merge_parts([text])
        if len(normalized) <= limit:
            return [normalized]

        sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý0-9])", normalized)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            proposal = f"{current} {sentence}".strip()
            if current and len(proposal) > limit:
                chunks.append(current.strip())
                current = sentence
            elif len(sentence) > limit:
                chunks.extend(self._split_long_sentence(sentence, limit))
                current = ""
            else:
                current = proposal
        if current:
            chunks.append(current.strip())
        return [chunk for chunk in chunks if chunk]

    def _split_long_sentence(self, sentence: str, limit: int) -> list[str]:
        parts = re.split(r"(?<=[,;:])\s+", sentence)
        chunks: list[str] = []
        current = ""
        for part in parts:
            proposal = f"{current} {part}".strip()
            if current and len(proposal) > limit:
                chunks.append(current.strip())
                current = part
            else:
                current = proposal
        if current:
            if len(current) <= limit:
                chunks.append(current.strip())
            else:
                chunks.extend(self._split_by_words(current, limit))
        return chunks

    def _split_by_words(self, text: str, limit: int) -> list[str]:
        words = text.split()
        chunks: list[str] = []
        current = ""
        for word in words:
            proposal = f"{current} {word}".strip()
            if current and len(proposal) > limit:
                chunks.append(current.strip())
                current = word
            else:
                current = proposal
        if current:
            chunks.append(current.strip())
        return chunks

    # ----- Heading classification (whitelist approach) -----

    def _classify_heading(self, heading: str) -> str:
        """Classify a heading as 'keep', 'drop', or 'unknown'.

        In v1 we used a blacklist (only checked if the heading matched a
        skip-list).  Now we use a whitelist: headings matching body-section
        patterns are kept, headings matching end-matter patterns are dropped,
        and everything else is 'unknown' (kept by default, flagged for LLM
        review if enabled).
        """
        normalized = self._normalize_text(heading)

        # Strip leading numbering for matching ("1. Introduction" → "Introduction").
        stripped = re.sub(r"^\d+\.?\s+", "", normalized).strip()

        # Drop end-matter headings according to the corresponding UI toggles.
        if self.options.drop_references_section and self._matches_any(
            stripped, _REFERENCE_SECTION_PATTERNS
        ):
            return "drop"
        if self.options.drop_acknowledgements and self._matches_any(
            stripped, _ACKNOWLEDGEMENT_SECTION_PATTERNS
        ):
            return "drop"
        if self.options.drop_appendices and self._matches_any(stripped, _APPENDIX_SECTION_PATTERNS):
            return "drop"

        # Article-type labels: drop the heading only, don't skip the section.
        if self._matches_any(stripped, _ARTICLE_TYPE_SECTIONS):
            return "drop_heading_only"

        # Check whitelist.
        if self._matches_any(stripped, _WHITELIST_SECTIONS):
            return "keep"

        # Numbered headings that didn't match droplist are presumed body content.
        if re.match(r"^\d+\.?\s+\w", normalized):
            return "keep"

        return "unknown"

    # ----- Front-matter / end-matter detection -----

    @staticmethod
    def _is_front_matter_line(text: str) -> bool:
        return any(pattern.match(text) for pattern in _FRONT_MATTER_LINE_RE)

    @staticmethod
    def _is_end_matter_line(text: str) -> bool:
        return any(text.startswith(prefix) for prefix in _END_MATTER_PREFIXES)

    @staticmethod
    def _is_inline_end_matter(text: str) -> bool:
        """Detect paragraph blocks that start with an end-matter section label."""
        return any(pattern.match(text) for pattern in _INLINE_END_MATTER_RE)

    @staticmethod
    def _looks_like_reference_entry(text: str) -> bool:
        """Detect bibliography / reference list entries by pattern."""
        if len(text) < 30 or len(text) > 1000:
            return False
        if _REFERENCE_ENTRY_RE.match(text):
            return True
        if _NUMBERED_REFERENCE_RE.match(text):
            return True
        return False

    @staticmethod
    def _looks_like_affiliation(text: str) -> bool:
        """Detect author affiliation / institutional address lines."""
        if len(text) > 300:
            return False
        if _AFFILIATION_RE.match(text):
            return True
        # Lines that are mostly email/ORCID and short.
        if len(text) < 100:
            if _EMAIL_RE.search(text) and len(text.split()) < 15:
                return True
            if _ORCID_RE.search(text):
                return True
        return False

    @staticmethod
    def _normalize_label(label: str | None) -> str:
        if label is None:
            return ""
        value = getattr(label, "value", label)
        return str(value).strip().lower()

    @staticmethod
    def _matches_any(text: str, patterns: list[re.Pattern[str]]) -> bool:
        return any(pattern.match(text) for pattern in patterns)

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = unicodedata.normalize("NFKC", text)
        text = text.replace("\xad", "")
        text = text.replace("\xa0", " ")
        text = re.sub(r"(?<=\w)-\s+(?=\w)", "", text)
        text = re.sub(r"^([A-Z])\s+(?=[a-z]{2,}\b)", r"\1", text)
        text = text.replace("•", "")
        text = MULTISPACE_RE.sub(" ", text)
        text = text.strip(" \t\n\r")
        return text

    @staticmethod
    def _remove_numeric_citations(text: str) -> str:
        text = NUMERIC_CITATION_RE.sub("", text)
        text = PAREN_NUMERIC_CITATION_RE.sub("", text)
        text = re.sub(r"\s+([,.;:])", r"\1", text)
        return text.strip()

    @staticmethod
    def _merge_parts(parts: Iterable[str]) -> str:
        merged_parts: list[str] = []
        for part in (part.strip() for part in parts if part and part.strip()):
            if merged_parts and ScientificTextCleaner._should_merge_continuation(
                merged_parts[-1], part
            ):
                merged_parts[-1] = ScientificTextCleaner._merge_continuation(
                    merged_parts[-1], part
                )
            else:
                merged_parts.append(part)

        merged = "\n\n".join(merged_parts)
        return MULTINEWLINE_RE.sub("\n\n", merged).strip()

    @staticmethod
    def _should_merge_continuation(previous: str, current: str) -> bool:
        previous = previous.rstrip()
        current = current.lstrip()
        if not previous or not current:
            return False

        first = current[0]
        if previous.endswith("-") and first.islower():
            return True
        if previous.count("(") > previous.count(")"):
            return True
        if ScientificTextCleaner._looks_like_short_heading(previous):
            return False
        if first.islower() and not ScientificTextCleaner._ends_sentence(previous):
            return True
        return False

    @staticmethod
    def _merge_continuation(previous: str, current: str) -> str:
        previous = previous.rstrip()
        current = current.lstrip()
        if previous.endswith("-") and current[:1].islower():
            return previous[:-1] + current
        return f"{previous} {current}"

    @staticmethod
    def _ends_sentence(text: str) -> bool:
        return text.rstrip(")]}'\"").endswith((".", "?", "!"))

    @staticmethod
    def _looks_like_short_heading(text: str) -> bool:
        text = text.strip()
        if len(text) > 80 or re.search(r"[.!?]", text):
            return False
        words = text.split()
        if not words or len(words) > 8:
            return False
        heading_words = sum(
            1
            for word in words
            if word[:1].isupper() or word.isupper() or "/" in word or word.casefold() == "of"
        )
        return heading_words == len(words)

    @staticmethod
    def _looks_like_table_line(text: str) -> bool:
        if TABLEISH_RE.search(text):
            return True
        tokens = text.split()
        if len(tokens) >= 6:
            numeric_ratio = sum(token.replace(".", "", 1).isdigit() for token in tokens) / len(
                tokens
            )
            if numeric_ratio > 0.55:
                return True
        return False

    @staticmethod
    def _looks_like_non_prose(text: str) -> bool:
        if len(text) <= 2:
            return True
        if NUMERIC_HEAVY_RE.match(text) and len(text) < 40:
            return True
        if text.count("=") >= 2:
            return True
        return False

    @staticmethod
    def _find_repeated_furniture(blocks: list[ExtractedBlock]) -> set[str]:
        counts: Counter[str] = Counter()
        for block in blocks:
            text = ScientificTextCleaner._normalize_text(block.text).casefold()
            if not text:
                continue
            if len(text) > 90:
                continue
            if block.label and ScientificTextCleaner._normalize_label(block.label) in {
                "page_header",
                "page_footer",
            }:
                counts[text] += 1
                continue
            if text.isdigit():
                counts[text] += 1
                continue
            counts[text] += 1
        return {text for text, count in counts.items() if count >= 3}

    @staticmethod
    def _drop(stats: CleaningStats, key: str, by_label: bool = False) -> None:
        bucket = stats.dropped_by_label if by_label else stats.dropped_by_rule
        bucket[key] = bucket.get(key, 0) + 1
