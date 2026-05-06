"""Tests for the manual_overrides corrections mechanism, value↔quote lint,
and the materiality opt-out gate.

These cover the new infrastructure added to handle parser bugs the code
itself can't reasonably fix (brochure column-bleed, OCR truncation,
fundamental fusion of label columns)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from correios_audit.normalize.apply import (
    _apply_canonical_corrections,
    _format_value_digits,
    _is_placeholder_quote,
    _load_canonical_corrections,
    _load_manual_overrides,
    _quote_contains_value,
)


# ─── Placeholder quote detection ─────────────────────────────────────────

@pytest.mark.parametrize("quote", ["TODO", "todo", " TODO ", "TBD", "FIXME", "", None])
def test_is_placeholder_quote_recognizes_scaffolding(quote):
    assert _is_placeholder_quote(quote) is True


@pytest.mark.parametrize("quote", [
    "Receita Líquida 1.234,5",
    "T O T A L  6.794,9  6.282,9",
    "0",  # might be a real value
])
def test_is_placeholder_quote_accepts_real(quote):
    assert _is_placeholder_quote(quote) is False


# ─── Value digit formatter ───────────────────────────────────────────────

def test_format_value_digits_drops_trailing_zero_for_integer_floats():
    assert _format_value_digits(10453859.0) == "10453859"


def test_format_value_digits_preserves_decimal_for_non_integers():
    assert _format_value_digits(9316.2) == "9316.2"


def test_format_value_digits_full_precision_brl():
    # 2002 brochure prints values in raw R$ — 12+ significant digits.
    assert _format_value_digits(4159071396.73) == "4159071396.73"


# ─── Value↔quote consistency lint ────────────────────────────────────────

def test_quote_contains_value_matches_brazilian_thousands_separator():
    # Brochure prints "9.316,2" — the digits "9316" and "2" must appear in
    # any order inside the quote (separators stripped).
    assert _quote_contains_value(9316.2, scale=1_000_000.0,
                                 source_quote="RECEITA LÍQUIDA  9.316,2") is True


def test_quote_contains_value_matches_full_precision_units():
    assert _quote_contains_value(
        4159071396.73, scale=1.0,
        source_quote="T O T A L  4.159.071.396,73  3.406.191.009,76",
    ) is True


def test_quote_contains_value_rejects_typo():
    # User typed 9326.2 (typo) but quote shows 9316,2.
    assert _quote_contains_value(9326.2, scale=1_000_000.0,
                                 source_quote="LÍQUIDA  9.316,2") is False


def test_quote_contains_value_skips_tiny_amounts():
    # Below R$ 10 we don't even check — any short digit sequence will
    # collide with random numbers in the quote.
    assert _quote_contains_value(0.01, scale=1.0, source_quote="zzz") is True


# ─── Loader: corrections ─────────────────────────────────────────────────

def _write_yaml(tmpdir: Path, name: str, content: str) -> Path:
    p = tmpdir / name
    p.write_text(textwrap.dedent(content))
    return p


def test_load_corrections_picks_up_replace_and_suppress(tmp_path, monkeypatch):
    monkeypatch.setattr("correios_audit.normalize.apply.MANUAL_DIR", tmp_path)
    _write_yaml(tmp_path, "fixtures.yaml", """
        currency_unit: thousands
        corrections:
          - doc_id: 2008-fy-df
            line_id: dre.receita_liquida
            period_year: 2007
            action: replace
            currency_unit: millions
            value: 9316.2
            source_page: 2
            source_quote: "RECEITA LÍQUIDA  9.316,2"
            reason: "test"
          - doc_id: 2008-fy-df
            line_id: dre.receitas_financeiras
            period_year: 2007
            action: suppress
            reason: "bare 'Financeiras' is a NET"
    """)
    out = _load_canonical_corrections()
    assert {(c["action"], c["line_id"]) for c in out} == {
        ("replace", "dre.receita_liquida"),
        ("suppress", "dre.receitas_financeiras"),
    }
    replace = [c for c in out if c["action"] == "replace"][0]
    # 9316.2 millions → 9_316_200_000 R$
    assert replace["value"] == 9_316_200_000.0


def test_load_corrections_rejects_replace_without_provenance(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("correios_audit.normalize.apply.MANUAL_DIR", tmp_path)
    _write_yaml(tmp_path, "fixtures.yaml", """
        currency_unit: thousands
        corrections:
          - doc_id: 2008-fy-df
            line_id: dre.receita_liquida
            period_year: 2007
            action: replace
            value: 9316200
            # No source_page, no source_quote.
    """)
    out = _load_canonical_corrections()
    assert out == []
    err = capsys.readouterr().err
    assert "replace requires source_quote" in err


def test_load_corrections_aborts_on_value_quote_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr("correios_audit.normalize.apply.MANUAL_DIR", tmp_path)
    _write_yaml(tmp_path, "fixtures.yaml", """
        currency_unit: millions
        corrections:
          - doc_id: 2008-fy-df
            line_id: dre.receita_liquida
            period_year: 2007
            action: replace
            value: 9999.9
            source_page: 2
            source_quote: "RECEITA LÍQUIDA  9.316,2"
            reason: "deliberate typo"
    """)
    with pytest.raises(SystemExit):
        _load_canonical_corrections()


# ─── Apply: corrections to canonical rows ────────────────────────────────

def _row(doc_id="2008-fy-df", line_id="dre.receita_liquida", period_year=2007,
         value=-6_604_400_000.0):
    return {
        "doc_id": doc_id,
        "line_id": line_id,
        "period_year": period_year,
        "period_kind": "fy",
        "scope": "consolidado",
        "value": value,
        "label_raw": "RECEITA LÍQUIDA",
    }


def test_apply_corrections_suppress_drops_row():
    canonical = [_row(), _row(period_year=2008)]
    corr = [{
        "action": "suppress",
        "doc_id": "2008-fy-df",
        "line_id": "dre.receita_liquida",
        "period_year": 2007,
        "period_kind": "fy",
        "scope": "consolidado",
        "reason": "test",
        "_source_file": "test.yaml",
    }]
    out = _apply_canonical_corrections(canonical, corr)
    assert len(out) == 1
    assert out[0]["period_year"] == 2008


def test_apply_corrections_replace_overrides_value_and_provenance():
    canonical = [_row()]
    corr = [{
        "action": "replace",
        "doc_id": "2008-fy-df",
        "line_id": "dre.receita_liquida",
        "period_year": 2007,
        "period_kind": "fy",
        "scope": "consolidado",
        "value": 9_316_200_000.0,
        "source_page": 2,
        "source_quote": "RECEITA LÍQUIDA  9.316,2",
        "reason": "column-bleed",
        "_source_file": "test.yaml",
    }]
    out = _apply_canonical_corrections(canonical, corr)
    assert len(out) == 1
    assert out[0]["value"] == 9_316_200_000.0
    assert out[0]["mapping_method"] == "manual_correction"
    assert "9.316,2" in out[0]["source_quote"]


def test_apply_corrections_warns_on_unmatched_target(capsys):
    canonical = [_row(period_year=2008)]
    corr = [{
        "action": "suppress",
        "doc_id": "9999-fy-df",  # doesn't exist in canonical
        "line_id": "dre.receita_liquida",
        "period_year": 2007,
        "period_kind": "fy",
        "scope": "consolidado",
        "reason": "test",
        "_source_file": "test.yaml",
    }]
    out = _apply_canonical_corrections(canonical, corr)
    assert len(out) == 1
    err = capsys.readouterr().err
    assert "no canonical row matched" in err


def test_apply_corrections_warns_on_duplicate_keys(capsys):
    canonical = [_row()]
    base = {
        "action": "suppress",
        "doc_id": "2008-fy-df",
        "line_id": "dre.receita_liquida",
        "period_year": 2007,
        "period_kind": "fy",
        "scope": "consolidado",
        "reason": "first",
    }
    corr = [
        {**base, "_source_file": "first.yaml"},
        {**base, "_source_file": "second.yaml"},
    ]
    _apply_canonical_corrections(canonical, corr)
    err = capsys.readouterr().err
    assert "duplicate correction" in err


# ─── Loader: manual override placeholder rejection ───────────────────────

def test_manual_override_value_with_placeholder_quote_aborts(tmp_path, monkeypatch):
    monkeypatch.setattr("correios_audit.normalize.apply.MANUAL_DIR", tmp_path)
    _write_yaml(tmp_path, "fixtures.yaml", """
        vintage_year: 2008
        currency_unit: millions
        rows:
          - line_id: dre.receita_liquida
            period_year: 2008
            value: 10397.7
            source_page: 2
            source_quote: TODO
    """)
    with pytest.raises(SystemExit):
        _load_manual_overrides()


# ─── Materiality opt-out gate ────────────────────────────────────────────

def test_opt_out_requires_full_headline_set(tmp_path, monkeypatch):
    from correios_audit.verify import checks as verify_checks
    monkeypatch.setattr(verify_checks, "MANUAL_OVERRIDES_DIR", tmp_path)
    # Only 2 of the 4 required headlines.
    _write_yaml(tmp_path, "partial.yaml", """
        materiality_satisfied_by_overrides: true
        doc_id: 2008-fy-df
        rows:
          - line_id: bp.ativo.total
            period_year: 2008
            value: 6794.9
            source_quote: "T O T A L  6.794,9"
          - line_id: dre.receita_liquida
            period_year: 2008
            value: 10397.7
            source_quote: "RECEITA LÍQUIDA  10.397,7"
    """)
    out = verify_checks._docs_satisfied_by_overrides()
    assert out == {}


def test_opt_out_accepts_full_headline_set(tmp_path, monkeypatch):
    from correios_audit.verify import checks as verify_checks
    monkeypatch.setattr(verify_checks, "MANUAL_OVERRIDES_DIR", tmp_path)
    _write_yaml(tmp_path, "full.yaml", """
        materiality_satisfied_by_overrides: true
        doc_id: 2008-fy-df
        rows:
          - line_id: bp.ativo.total
            period_year: 2008
            value: 6794.9
            source_quote: "T O T A L 6.794,9"
          - line_id: bp.passivo.total
            period_year: 2008
            value: 6794.9
            source_quote: "T O T A L 6.794,9"
          - line_id: dre.receita_liquida
            period_year: 2008
            value: 10397.7
            source_quote: "RECEITA LÍQUIDA 10.397,7"
          - line_id: dre.resultado_liquido
            period_year: 2008
            value: 801.1
            source_quote: "LUCRO LÍQUIDO 801,1"
    """)
    out = verify_checks._docs_satisfied_by_overrides()
    assert out.keys() == {"2008-fy-df"}


def test_opt_out_rejects_placeholder_quotes(tmp_path, monkeypatch):
    from correios_audit.verify import checks as verify_checks
    monkeypatch.setattr(verify_checks, "MANUAL_OVERRIDES_DIR", tmp_path)
    _write_yaml(tmp_path, "scaffold.yaml", """
        materiality_satisfied_by_overrides: true
        doc_id: 2008-fy-df
        rows:
          - line_id: bp.ativo.total
            period_year: 2008
            value: 6794.9
            source_quote: TODO
          - line_id: bp.passivo.total
            period_year: 2008
            value: 6794.9
            source_quote: tbd
          - line_id: dre.receita_liquida
            period_year: 2008
            value: 10397.7
            source_quote: ""
          - line_id: dre.resultado_liquido
            period_year: 2008
            value: 801.1
            source_quote: FIXME
    """)
    out = verify_checks._docs_satisfied_by_overrides()
    assert out == {}
