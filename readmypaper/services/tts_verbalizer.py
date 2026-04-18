"""TTS verbaliser — normalise scientific text for spoken output.

This module expands abbreviations, measurements, and patterns that cause TTS
engines to produce robotic or unintelligible output.  It runs *after* text
cleaning but *before* chunking and synthesis.
"""

from __future__ import annotations

import re

# --- Fixed expansions (case-sensitive where needed) ---

_ABBREVIATION_MAP: dict[str, str] = {
    "CT": "C.T.",
    "MRI": "M.R.I.",
    "CSF": "C.S.F.",
    "CNN": "C.N.N.",
    "DNN": "D.N.N.",
    "RNN": "R.N.N.",
    "GAN": "G.A.N.",
    "AUC": "A.U.C.",
    "ROC": "R.O.C.",
    "ICU": "I.C.U.",
    "IoU": "I.o.U.",
    "GPU": "G.P.U.",
    "CPU": "C.P.U.",
    "EEG": "E.E.G.",
    "ECG": "E.C.G.",
    "DICOM": "DICOM",
    "PACS": "PACS",
    "AI": "A.I.",
    "ML": "M.L.",
    "DL": "D.L.",
    "NLP": "N.L.P.",
    "LSTM": "L.S.T.M.",
    "CAM": "C.A.M.",
    "ResNet": "ResNet",
    "VGG": "V.G.G.",
    "BERT": "BERT",
    "IEEE": "I.E.E.E.",
    "HIPAA": "HIPAA",
    "PHI": "P.H.I.",
    "TPU": "T.P.U.",
    "RAM": "RAM",
    "FPS": "F.P.S.",
    "RGB": "R.G.B.",
    "vs": "versus",
    "vs.": "versus",
    "w.r.t.": "with respect to",
    "i.e.": "that is,",
    "e.g.": "for example,",
    "et al.": "and others",
    "etc.": "etcetera",
    "Fig.": "Figure",
    "fig.": "figure",
    "Figs.": "Figures",
    "figs.": "figures",
    "Tab.": "Table",
    "tab.": "table",
    "Eq.": "Equation",
    "eq.": "equation",
    "Eqs.": "Equations",
    "eqs.": "equations",
    "Ref.": "Reference",
    "ref.": "reference",
    "Sec.": "Section",
    "sec.": "section",
    "Sect.": "Section",
    "approx.": "approximately",
}

# Build a regex that matches whole-word abbreviations.
_ABBREV_PATTERN = re.compile(
    r"\b("
    + "|".join(re.escape(k) for k in sorted(_ABBREVIATION_MAP, key=len, reverse=True))
    + r")(?=[\s,.:;!?\)\]\-]|$)"
)

# --- Numeric and symbolic patterns ---

# 224×224, 3x3, 512 × 512
_DIMENSION_RE = re.compile(r"(\d+)\s*[×xX]\s*(\d+)")
# p<0.05, p < 0.001
_PVALUE_RE = re.compile(r"\bp\s*([<>≤≥])\s*([\d.]+)")
# F1-score, F1 score
_F_SCORE_RE = re.compile(r"\bF(\d)[\-\s]?score", re.IGNORECASE)
# 78.3%, 0.5%
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
# ±, +-
_PLUS_MINUS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[±]\s*(\d+(?:\.\d+)?)")
# ≥, ≤, >, <  between numbers
_COMPARISON_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([≤≥><])\s*(\d+(?:\.\d+)?)")
# Hyphenated compounds at line breaks (re-\nconstructed → reconstructed)
_HYPHEN_BREAK_RE = re.compile(r"(\w+)-\s*\n\s*(\w+)")
# En-dash / em-dash between words
_DASH_RE = re.compile(r"(\w)\s*[–—]\s*(\w)")


_COMPARISON_WORDS = {
    "<": "less than",
    ">": "greater than",
    "≤": "less than or equal to",
    "≥": "greater than or equal to",
}


def verbalize(text: str) -> str:
    """Expand scientific notation and abbreviations for TTS consumption."""
    if not text:
        return text

    # Fix hyphenated line breaks first.
    text = _HYPHEN_BREAK_RE.sub(r"\1\2", text)

    # Dimensions.
    text = _DIMENSION_RE.sub(r"\1 by \2", text)

    # P-values.
    text = _PVALUE_RE.sub(
        lambda m: f"p {_COMPARISON_WORDS.get(m.group(1), m.group(1))} {m.group(2)}", text
    )

    # F-scores.
    text = _F_SCORE_RE.sub(r"F\1 score", text)

    # Plus-minus.
    text = _PLUS_MINUS_RE.sub(r"\1 plus or minus \2", text)

    # Comparisons between numbers.
    text = _COMPARISON_RE.sub(
        lambda m: f"{m.group(1)} {_COMPARISON_WORDS.get(m.group(2), m.group(2))} {m.group(3)}",
        text,
    )

    # Percentages.
    text = _PERCENT_RE.sub(r"\1 percent", text)

    # Abbreviations (whole-word).
    text = _ABBREV_PATTERN.sub(lambda m: _ABBREVIATION_MAP.get(m.group(1), m.group(1)), text)

    # Normalize dashes between words to ", ".
    text = _DASH_RE.sub(r"\1, \2", text)

    # Clean up double spaces introduced by expansions.
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip()
