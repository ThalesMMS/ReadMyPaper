"""End-to-end cleaning guard test.

Feeds a synthetic multi-section paper (as ExtractedBlock list) through the
full cleaning pipeline and asserts that none of the unwanted text leaks into
the final output.  No PDF extraction, LLM, or TTS is needed — this is a
fast, deterministic test.
"""

from __future__ import annotations

from readmypaper.services.text_cleaner import ScientificTextCleaner
from readmypaper.types import ExtractedBlock, ProcessingOptions

# ---------------------------------------------------------------------------
# Synthetic paper structure
# ---------------------------------------------------------------------------

_BLOCKS: list[ExtractedBlock] = [
    # ----- Front matter -----
    ExtractedBlock(text="RESEARCH ARTICLE", label="section_header", page_no=1),
    ExtractedBlock(
        text="Deep Learning for CSF Shunt Valve Identification", label="title", page_no=1
    ),
    ExtractedBlock(
        text="John A Smith 1, Maria B Costa 2, David C Lee 3", label="paragraph", page_no=1
    ),
    ExtractedBlock(
        text="1 Department of Neurosurgery, University Hospital Zurich, Switzerland",
        label="paragraph",
        page_no=1,
    ),
    ExtractedBlock(
        text="2 Instituto de Neurociências, Universidade de São Paulo, Brazil",
        label="paragraph",
        page_no=1,
    ),
    ExtractedBlock(
        text="Received: 5 January 2024 / Accepted: 15 March 2024 / Published: 1 April 2024",
        label="paragraph",
        page_no=1,
    ),
    ExtractedBlock(
        text="Keywords: deep learning, CSF shunt, image classification",
        label="paragraph",
        page_no=1,
    ),
    ExtractedBlock(text="https://doi.org/10.1007/s00701-024-05940-3", label="paragraph", page_no=1),
    # ----- Body sections -----
    ExtractedBlock(text="Abstract", label="section_header", page_no=1),
    ExtractedBlock(
        text="This study evaluates the feasibility of an AI-assisted shunt valve detection system "
        "using deep learning on plain radiographs.",
        label="paragraph",
        page_no=1,
    ),
    ExtractedBlock(text="Introduction", label="section_header", page_no=1),
    ExtractedBlock(
        text=(
            "Over recent decades the number of different manufacturers and models of "
            "cerebrospinal fluid shunt valves has constantly increased. Proper identification of "
            "shunt valves on X-ray images is crucial to neurosurgeons and radiologists."
        ),
        label="paragraph",
        page_no=2,
    ),
    ExtractedBlock(text="Methods", label="section_header", page_no=2),
    ExtractedBlock(
        text="The dataset used contains 2070 anonymized images of ten different commonly used "
        "shunt valve types acquired from skull X-rays or scout CT images.",
        label="paragraph",
        page_no=2,
    ),
    ExtractedBlock(text="Results", label="section_header", page_no=3),
    ExtractedBlock(
        text="Overall our model achieved an F1 score of 99 percent with a weighted average recall "
        "of 98 percent across all ten shunt valve models.",
        label="paragraph",
        page_no=3,
    ),
    ExtractedBlock(text="Discussion", label="section_header", page_no=4),
    ExtractedBlock(
        text="Our results demonstrate the feasibility of using deep learning for automatic "
        "identification of CSF shunt valves on radiographs.",
        label="paragraph",
        page_no=4,
    ),
    ExtractedBlock(text="Conclusion", label="section_header", page_no=4),
    ExtractedBlock(
        text="This technology has the potential to automatically detect different shunt valve "
        "models in a fast and precise way.",
        label="paragraph",
        page_no=4,
    ),
    # ----- End matter -----
    ExtractedBlock(text="Acknowledgements", label="section_header", page_no=5),
    ExtractedBlock(
        text="We thank the radiology departments of University Hospital Zurich and "
        "Kepler University Hospital for providing the imaging data.",
        label="paragraph",
        page_no=5,
    ),
    ExtractedBlock(text="Funding", label="section_header", page_no=5),
    ExtractedBlock(
        text="Open access funding provided by University of Zurich.", label="paragraph", page_no=5
    ),
    ExtractedBlock(text="Author Contributions", label="section_header", page_no=5),
    ExtractedBlock(
        text=(
            "JAS designed the study and wrote the manuscript. "
            "MBC collected the data. DCL trained the model."
        ),
        label="paragraph",
        page_no=5,
    ),
    ExtractedBlock(text="Conflicts of Interest", label="section_header", page_no=5),
    ExtractedBlock(
        text="The authors declare no competing interests.", label="paragraph", page_no=5
    ),
    ExtractedBlock(text="Ethics Approval", label="section_header", page_no=5),
    ExtractedBlock(
        text="Ethics approval was obtained from the local ethics committee (KEK-2023-01234).",
        label="paragraph",
        page_no=5,
    ),
    ExtractedBlock(text="Data Availability", label="section_header", page_no=5),
    ExtractedBlock(
        text="The datasets generated during the current study are not publicly available.",
        label="paragraph",
        page_no=5,
    ),
    ExtractedBlock(text="References", label="section_header", page_no=6),
    ExtractedBlock(
        text="Haenssle HA, Fink C, Schneiderbauer R, et al. Man against machine: diagnostic "
        "performance of a deep learning convolutional neural network. Ann Oncol 29:1836-1842",
        label="reference",
        page_no=6,
    ),
    ExtractedBlock(
        text="Howard J, Gugger S. Fastai: a layered API for deep learning. Information. "
        "https://doi.org/10.3390/info11020108",
        label="paragraph",
        page_no=6,
    ),
    ExtractedBlock(
        text="[3] Smith JA, Doe B. Neural network classification of CSF shunt valves. "
        "J Neurosurg 135:200-210",
        label="paragraph",
        page_no=6,
    ),
    ExtractedBlock(
        text="4. Esteva A, Kuprel B, Novoa RA, et al. Dermatologist-level classification "
        "of skin cancer with deep neural networks. Nature 542:115-118",
        label="paragraph",
        page_no=6,
    ),
    # ----- Boilerplate end-matter -----
    ExtractedBlock(
        text="Publisher's Note Springer Nature remains neutral with regard to jurisdictional "
        "claims in published maps and institutional affiliations.",
        label="paragraph",
        page_no=6,
    ),
    ExtractedBlock(
        text="Open Access This article is licensed under a Creative Commons Attribution 4.0 "
        "International License.",
        label="paragraph",
        page_no=6,
    ),
    ExtractedBlock(text="© The Author(s) 2024", label="paragraph", page_no=6),
]


# ---------------------------------------------------------------------------
# Forbidden patterns — these must NOT appear in the cleaned output.
# ---------------------------------------------------------------------------

_FORBIDDEN = [
    # End-matter section headings
    "Acknowledgements",
    "Funding",
    "Author Contributions",
    "Conflicts of Interest",
    "Ethics Approval",
    "Data Availability",
    "References",
    # Article-type heading
    "RESEARCH ARTICLE",
    # Reference entries
    "Haenssle HA",
    "Howard J, Gugger",
    "Smith JA, Doe B",
    "Esteva A, Kuprel",
    "Ann Oncol",
    "J Neurosurg",
    # Boilerplate
    "Publisher's Note",
    "Springer Nature",
    "Creative Commons",
    "Open Access This article",
    "The Author(s)",
    # Front-matter fragments
    "Received:",
    "Keywords:",
    "doi.org",
    # Affiliations
    "Department of Neurosurgery",
    "Instituto de Neurociências",
]

# ---------------------------------------------------------------------------
# Required patterns — body text that MUST survive.
# ---------------------------------------------------------------------------

_REQUIRED = [
    "AI-assisted shunt valve",
    "X-ray images is crucial",
    "2070 anonymized images",
    "F1 score of 99 percent",
    "feasibility of using deep learning",
    "fast and precise way",
]


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_cleaning_e2e_no_leaks() -> None:
    """Full cleaning pipeline must drop all end-matter and keep all body text."""
    cleaner = ScientificTextCleaner(ProcessingOptions())
    cleaned, stats = cleaner.clean(_BLOCKS, page_count=6)

    for forbidden in _FORBIDDEN:
        assert forbidden not in cleaned, (
            f"Leaked forbidden text: {forbidden!r}\n\n--- cleaned output ---\n{cleaned[:500]}"
        )

    for required in _REQUIRED:
        assert required in cleaned, (
            f"Missing required text: {required!r}\n\n--- cleaned output ---\n{cleaned[:500]}"
        )

    # Sanity: we should have a reasonable number of kept blocks.
    assert stats.kept_blocks >= 6, f"Only {stats.kept_blocks} blocks kept — too few"
    assert stats.dropped_blocks > 15, f"Only {stats.dropped_blocks} blocks dropped — too few"
