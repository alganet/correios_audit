"""Tests for parse.common: number parsing, period detection, OCR tolerance."""

from __future__ import annotations

from correios_audit.parse.common import (
    Word,
    detect_period_columns,
    looks_like_value,
    normalize_label,
    parse_value,
)


def test_parse_value_brazilian_thousands():
    assert parse_value("1.234.567") == 1_234_567.0
    assert parse_value("1.234,56") == 1234.56
    assert parse_value("(1.234.567)") == -1_234_567.0
    assert parse_value("-") is None
    assert parse_value("—") is None


def test_parse_value_ocr_substitution_only_on_low_confidence():
    # Born-digital text must not be rewritten — confidence=1.0 default.
    assert parse_value("2OlO") is None
    # Low-confidence OCR token: digits leak into the substitution table.
    assert parse_value("1.234.S67", confidence=0.6) == 1_234_567.0
    assert parse_value("(1.234.567)", confidence=0.6) == -1_234_567.0


def test_looks_like_value_strict_vs_relaxed():
    assert looks_like_value("1.234.567") is True
    assert looks_like_value("(1.234,56)") is True
    assert looks_like_value("-") is True
    # Note ref like "21.1" must NOT look like a value.
    assert looks_like_value("21.1") is False
    # OCR-mangled value at low confidence: substitution recovers it.
    assert looks_like_value("1.234.S67", confidence=0.7) is True
    assert looks_like_value("1.234.S67", confidence=1.0) is False


def test_normalize_label_strip_accents_and_punctuation():
    assert normalize_label("Caixa e Equivalentes:") == "caixa e equivalentes"
    assert normalize_label("AÇÕES PRÓPRIAS") == "acoes proprias"
    assert normalize_label("  Total  do  Ativo  ") == "total do ativo"


def _fake_line(words: list[tuple[float, float, str, float]]) -> dict:
    """Build an extractor-shaped line dict from a list of words."""
    return {
        "y": 100.0,
        "words": [list(w) for w in words],
    }


def test_detect_period_columns_recognises_dates():
    line = _fake_line([
        (50.0, 90.0, "31/12/2024", 1.0),
        (200.0, 240.0, "31/12/2023", 1.0),
    ])
    cols = detect_period_columns(line)
    assert [c.period_year for c in cols] == [2024, 2023]


def test_detect_period_columns_ocr_tolerant():
    # Low-confidence OCR misread '0' as 'O' — must still recognise as 2010.
    line = _fake_line([
        (50.0, 90.0, "31/12/2OlO", 0.6),
        (200.0, 240.0, "31/12/2009", 0.95),
    ])
    cols = detect_period_columns(line)
    years = sorted(c.period_year for c in cols)
    assert 2010 in years
    assert 2009 in years


def test_detect_period_columns_high_confidence_does_not_substitute():
    # A clean-text token "2OlO" (confidence 1.0) is NOT a date — we never
    # rewrite born-digital text, so it must stay unmatched.
    line = _fake_line([(50.0, 90.0, "31/12/2OlO", 1.0)])
    cols = detect_period_columns(line)
    assert cols == []


def test_word_default_confidence_one():
    """Old fixtures using 3-tuple words still load, with confidence=1.0."""
    line = {"y": 0.0, "words": [[10.0, 20.0, "ATIVO"]]}
    from correios_audit.parse.common import words_from_line
    words = words_from_line(line)
    assert len(words) == 1
    assert words[0].confidence == 1.0
