"""Tests for TTS verbalizer."""

from readmypaper.services.tts_verbalizer import verbalize


def test_dimension_expansion() -> None:
    assert "224 by 224" in verbalize("The input size is 224×224 pixels.")


def test_percentage_expansion() -> None:
    result = verbalize("Accuracy was 95.3%.")
    assert "95.3 percent" in result


def test_pvalue_expansion() -> None:
    result = verbalize("with p<0.05 significance.")
    assert "p less than 0.05" in result


def test_fscore_expansion() -> None:
    result = verbalize("The F1-score improved.")
    assert "F1 score" in result


def test_abbreviation_expansion() -> None:
    result = verbalize("CT and MRI scans showed CSF accumulation.")
    assert "C.T." in result
    assert "M.R.I." in result
    assert "C.S.F." in result


def test_et_al_expansion() -> None:
    result = verbalize("As described by Smith et al.")
    assert "and others" in result


def test_ie_eg_expansion() -> None:
    result = verbalize("modalities, i.e. CT and e.g. ultrasound.")
    assert "that is," in result
    assert "for example," in result


def test_plus_minus_expansion() -> None:
    result = verbalize("mean age was 45.2±12.3 years.")
    assert "plus or minus" in result


def test_empty_string() -> None:
    assert verbalize("") == ""


def test_hyphen_break_fix() -> None:
    result = verbalize("recon-\nstructed")
    assert "reconstructed" in result
