from readmypaper.services.text_cleaner import ScientificTextCleaner
from readmypaper.types import ExtractedBlock, ProcessingOptions


def test_drops_reference_section_and_caption() -> None:
    cleaner = ScientificTextCleaner(ProcessingOptions())
    blocks = [
        ExtractedBlock(text="Title", label="title"),
        ExtractedBlock(text="Abstract", label="section_header"),
        ExtractedBlock(text="Useful body text [1] with science.", label="paragraph"),
        ExtractedBlock(text="Figure 1 Study flow", label="caption"),
        ExtractedBlock(text="References", label="section_header"),
        ExtractedBlock(text="1. Author et al.", label="paragraph"),
    ]
    cleaned, stats = cleaner.clean(blocks, page_count=2)

    assert "Useful body text with science." in cleaned
    assert "Study flow" not in cleaned
    assert "Author et al." not in cleaned
    assert stats.kept_blocks == 3


def test_detects_portuguese() -> None:
    cleaner = ScientificTextCleaner(ProcessingOptions())
    blocks = [
        ExtractedBlock(text="Título do estudo", label="title"),
        ExtractedBlock(
            text="Este é um texto científico em português com resultados clínicos.",
            label="paragraph",
        ),
    ]
    cleaned, stats = cleaner.clean(blocks, page_count=1)

    assert "português" in cleaned.lower()
    assert stats.detected_language.startswith("pt")


def test_section_whitelist_drops_end_matter() -> None:
    """Section whitelist drops acknowledgements, data availability, etc."""
    cleaner = ScientificTextCleaner(ProcessingOptions())
    blocks = [
        ExtractedBlock(text="Introduction", label="section_header"),
        ExtractedBlock(
            text="This study investigates a new approach to deep learning.", label="paragraph"
        ),
        ExtractedBlock(text="Acknowledgements", label="section_header"),
        ExtractedBlock(text="We thank the reviewers for helpful comments.", label="paragraph"),
        ExtractedBlock(text="Data Availability", label="section_header"),
        ExtractedBlock(text="Data is available on request.", label="paragraph"),
        ExtractedBlock(text="Author Contributions", label="section_header"),
        ExtractedBlock(text="J.S. wrote the paper.", label="paragraph"),
    ]
    cleaned, stats = cleaner.clean(blocks, page_count=5)

    assert "deep learning" in cleaned
    assert "thank the reviewers" not in cleaned
    assert "available on request" not in cleaned
    assert "wrote the paper" not in cleaned


def test_end_matter_heading_options_allow_selected_sections() -> None:
    cleaner = ScientificTextCleaner(
        ProcessingOptions(
            drop_references_section=False,
            drop_acknowledgements=False,
            drop_appendices=False,
        )
    )
    blocks = [
        ExtractedBlock(text="References", label="section_header"),
        ExtractedBlock(text="Reference section prose stays available.", label="paragraph"),
        ExtractedBlock(text="Acknowledgements", label="section_header"),
        ExtractedBlock(text="The team thanks reviewers for helpful input.", label="paragraph"),
        ExtractedBlock(text="Appendix", label="section_header"),
        ExtractedBlock(text="Extra implementation detail stays available.", label="paragraph"),
    ]
    cleaned, _stats = cleaner.clean(blocks, page_count=5)

    assert "Reference section prose stays available." in cleaned
    assert "thanks reviewers" in cleaned
    assert "Extra implementation detail" in cleaned


def test_front_matter_lines_dropped() -> None:
    cleaner = ScientificTextCleaner(ProcessingOptions())
    blocks = [
        ExtractedBlock(text="TECHNICAL NOTE", label="paragraph"),
        ExtractedBlock(text="Received: 15 January 2024", label="paragraph"),
        ExtractedBlock(text="Keywords: deep learning, CT, classification", label="paragraph"),
        ExtractedBlock(text="doi: 10.1234/example.2024", label="paragraph"),
        ExtractedBlock(
            text="This study presents a novel approach to image classification.", label="paragraph"
        ),
    ]
    cleaned, _stats = cleaner.clean(blocks, page_count=3)

    assert "TECHNICAL NOTE" not in cleaned
    assert "Received:" not in cleaned
    assert "Keywords:" not in cleaned
    assert "doi:" not in cleaned
    assert "novel approach" in cleaned


def test_affiliation_lines_dropped() -> None:
    cleaner = ScientificTextCleaner(ProcessingOptions())
    blocks = [
        ExtractedBlock(text="Department of Computer Science, MIT", label="paragraph"),
        ExtractedBlock(text="john.doe@university.edu", label="paragraph"),
        ExtractedBlock(text="The proposed method achieves high accuracy.", label="paragraph"),
    ]
    cleaned, _stats = cleaner.clean(blocks, page_count=2)

    assert "Department" not in cleaned
    assert "university.edu" not in cleaned
    assert "high accuracy" in cleaned


def test_reference_label_activates_section_skip() -> None:
    """Blocks labeled 'reference' should activate section skip.

    Subsequent paragraph-labeled entries should also be skipped.
    """
    cleaner = ScientificTextCleaner(ProcessingOptions())
    blocks = [
        ExtractedBlock(text="Discussion text about deep learning results.", label="paragraph"),
        # Docling labels this individual reference as 'reference'
        ExtractedBlock(text="Smith JA et al. Something. J Med 10:100", label="reference"),
        # But the next entry was mislabeled as 'paragraph'
        ExtractedBlock(
            text="Doe B, Jones C. Another paper about neural networks. Nature 500:200-205",
            label="paragraph",
        ),
    ]
    cleaned, stats = cleaner.clean(blocks, page_count=3)

    assert "deep learning" in cleaned
    assert "Another paper" not in cleaned


def test_numbered_reference_entries_dropped() -> None:
    """Numbered reference entries like '[1] Author...' should be detected."""
    cleaner = ScientificTextCleaner(ProcessingOptions())
    blocks = [
        ExtractedBlock(text="This is real scientific content.", label="paragraph"),
        ExtractedBlock(text="[1] Smith JA, Doe B. A study of deep learning.", label="paragraph"),
        ExtractedBlock(
            text="2. Johnson RM, Lee KS. Neural network classification.", label="paragraph"
        ),
    ]
    cleaned, _stats = cleaner.clean(blocks, page_count=3)

    assert "real scientific" in cleaned
    assert "Smith JA" not in cleaned
    assert "Johnson RM" not in cleaned


def test_url_reference_entries_dropped() -> None:
    """Reference entries containing URLs/DOIs should be detected."""
    cleaner = ScientificTextCleaner(ProcessingOptions())
    blocks = [
        ExtractedBlock(text="Our method outperforms prior work.", label="paragraph"),
        ExtractedBlock(
            text=(
                "Howard J, Gugger S Fastai: a layered API for deep learning. "
                "Information. https://doi.org/10.3390/info"
            ),
            label="paragraph",
        ),
    ]
    cleaned, _stats = cleaner.clean(blocks, page_count=3)

    assert "outperforms" in cleaned
    assert "Howard J" not in cleaned


def test_article_type_heading_dropped() -> None:
    """Article-type labels like 'TECHNICAL NOTE' as headings should be dropped."""
    cleaner = ScientificTextCleaner(ProcessingOptions())
    blocks = [
        ExtractedBlock(text="TECHNICAL NOTE", label="section_header"),
        ExtractedBlock(text="This study presents a novel approach.", label="paragraph"),
        ExtractedBlock(text="RESEARCH ARTICLE", label="section_header"),
        ExtractedBlock(text="Another useful paragraph.", label="paragraph"),
    ]
    cleaned, _stats = cleaner.clean(blocks, page_count=3)

    assert "TECHNICAL NOTE" not in cleaned
    assert "RESEARCH ARTICLE" not in cleaned
    # Body text under these headings should still be kept (they're just
    # article-type labels, not section boundaries that skip content).
    assert "novel approach" in cleaned
    assert "Another useful" in cleaned


def test_long_reference_entry_dropped() -> None:
    """Reference entries > 500 chars but <= 1000 chars should be caught."""
    cleaner = ScientificTextCleaner(ProcessingOptions())
    long_ref = (
        "Haenssle HA, Fink C, Schneiderbauer R, Toberer F, Buhl T, Blum A, "
        "Kalloo A, Hassen ABH, Thomas L, Enk A, Uhlmann L, Alt C, "
        "Arenbergerova M, Bakos R, Banber A, Bertlich I, Blum A, Bokor-Billmann T, "
        "Bowling J, Braghiroli N, Braun R, Buder-Bakhaya K, Bugert P, Carl C, "
        "Chamaidi A, Combalia M, Dermoscopy Study Group, et al. Man against machine: "
        "diagnostic performance of a deep learning convolutional neural network "
        "for dermoscopic melanoma recognition in comparison to 58 dermatologists. "
        "Annals of Oncology 29:1836-1842. This reference is intentionally long "
        "to test the upper boundary of 1000 characters for reference detection."
    )
    assert len(long_ref) > 500
    blocks = [
        ExtractedBlock(text="Real scientific content here.", label="paragraph"),
        ExtractedBlock(text=long_ref, label="paragraph"),
    ]
    cleaned, _stats = cleaner.clean(blocks, page_count=5)

    assert "Real scientific" in cleaned
    assert "Man against machine" not in cleaned


def test_end_matter_prefix_dropped() -> None:
    cleaner = ScientificTextCleaner(ProcessingOptions())
    blocks = [
        ExtractedBlock(text="The results confirm our hypothesis.", label="paragraph"),
        ExtractedBlock(
            text="Open Access This article is distributed under a Creative Commons license.",
            label="paragraph",
        ),
        ExtractedBlock(text="Publisher's Note Springer Nature remains neutral.", label="paragraph"),
    ]
    cleaned, _stats = cleaner.clean(blocks, page_count=5)

    assert "results confirm" in cleaned
    assert "Open Access" not in cleaned
    assert "Publisher" not in cleaned


def test_merge_parts_repairs_cross_block_hyphenation() -> None:
    cleaner = ScientificTextCleaner(ProcessingOptions())
    blocks = [
        ExtractedBlock(
            text="Infection, leukemia, and rare renal tumors in-",
            label="paragraph",
        ),
        ExtractedBlock(
            text="cluding collecting duct carcinoma may present similarly.",
            label="paragraph",
        ),
        ExtractedBlock(
            text="Secondary renal involvement in pa-",
            label="paragraph",
        ),
        ExtractedBlock(
            text="tients with widespread disease may not affect prognosis.",
            label="paragraph",
        ),
    ]

    cleaned, _stats = cleaner.clean(blocks, page_count=1)

    assert "tumors including collecting duct" in cleaned
    assert "in patients with widespread disease" in cleaned
    assert "in-\n\ncluding" not in cleaned
    assert "pa-\n\ntients" not in cleaned


def test_merge_parts_does_not_merge_short_heading_into_body() -> None:
    cleaner = ScientificTextCleaner(ProcessingOptions())
    blocks = [
        ExtractedBlock(text="Methods", label="section_header"),
        ExtractedBlock(text="the cohort included fifty patients.", label="paragraph"),
    ]

    cleaned, _stats = cleaner.clean(blocks, page_count=1)

    assert "Methods\n\nthe cohort" in cleaned


def test_repeated_section_headers_are_dropped_before_heading_keep() -> None:
    cleaner = ScientificTextCleaner(ProcessingOptions())
    blocks = [
        ExtractedBlock(text="Primary and Secondary Renal Lymphoma", label="section_header"),
        ExtractedBlock(text="Primary and Secondary Renal Lymphoma", label="section_header"),
        ExtractedBlock(text="Primary and Secondary Renal Lymphoma", label="section_header"),
        ExtractedBlock(text="The useful body paragraph remains.", label="paragraph"),
    ]

    cleaned, stats = cleaner.clean(blocks, page_count=3)

    assert "Primary and Secondary Renal Lymphoma" not in cleaned
    assert "useful body paragraph" in cleaned
    assert stats.dropped_by_rule["repeated_furniture"] == 3


def test_normalize_text_repairs_drop_cap_spacing() -> None:
    cleaner = ScientificTextCleaner(ProcessingOptions())
    blocks = [
        ExtractedBlock(
            text="R enal involvement in lymphoma is clinically important.",
            label="paragraph",
        ),
    ]

    cleaned, _stats = cleaner.clean(blocks, page_count=1)

    assert "Renal involvement" in cleaned
    assert "R enal" not in cleaned


def test_select_ambiguous_blocks_skips_known_headings() -> None:
    """Known droplist/whitelist headings should NOT be sent to the LLM."""
    from readmypaper.services.llm_cleaner import select_ambiguous_blocks

    blocks = [
        ExtractedBlock(text="Introduction", label="section_header", page_no=1),
        ExtractedBlock(text="Body text", label="paragraph", page_no=1),
        ExtractedBlock(text="References", label="section_header", page_no=5),
        ExtractedBlock(text="Smith J et al. J Med 10:1", label="paragraph", page_no=5),
        ExtractedBlock(text="Unknown Heading XYZ", label="section_header", page_no=5),
        ExtractedBlock(text="Short frag", label="paragraph", page_no=5),
    ]
    page_count = 5

    ambiguous = select_ambiguous_blocks(blocks, page_count)
    ambiguous_indices = {idx for idx, _ in ambiguous}

    # "Introduction" (idx 0) and "References" (idx 2) are known headings — NOT sent.
    assert 0 not in ambiguous_indices
    assert 2 not in ambiguous_indices
    # "Unknown Heading XYZ" (idx 4) IS unknown — should be sent.
    assert 4 in ambiguous_indices
    # "Short frag" (idx 5) is short and on edge page — should be sent.
    assert 5 in ambiguous_indices
