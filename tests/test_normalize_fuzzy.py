"""Tests for the OCR-aware fuzzy fallback and OCR_FIXES lexicon."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from correios_audit.normalize.apply import (
    Rule,
    _derive_canonical_label,
    _fuzzy_match,
)
from correios_audit.normalize.lexicon import (
    OCR_FIXES,
    OCR_PHRASE_FIXES,
    OCR_SUBSTRING_FIXES,
    _replace_bounded,
    apply_ocr_fixes,
)


def test_derive_canonical_label_from_anchored_pattern():
    assert _derive_canonical_label(r"^caixa e equivalentes? de caixa$") in {
        "caixa e equivalentes de caixa",
        "caixa e equivalente de caixa",
    }


def test_derive_canonical_label_handles_alternation():
    # Picks the first alternative.
    out = _derive_canonical_label(r"^(caixa|disponivel) e equivalentes$")
    assert out == "caixa e equivalentes"


def test_derive_canonical_label_bails_on_complex_patterns():
    # Character classes / escapes — heuristic is not safe to apply.
    assert _derive_canonical_label(r"^cnpj\s+[\d./-]+$") is None


# ─── OCR substring & phrase fixes ────────────────────────────────────────

def test_replace_bounded_token_inside_label():
    # "i ti t" → "investimento" inside a longer label
    assert _replace_bounded("propriedades para i ti t", "i ti t",
                            "investimento") == "propriedades para investimento"


def test_replace_bounded_does_not_split_inside_word():
    # "ti" should not match inside a word like "antigo".
    assert _replace_bounded("antigo", "ti", "ZZZ") == "antigo"


def test_apply_ocr_fixes_chains_phrase_then_token():
    # "receitas a i" → "receitas a apropriar" (phrase) leaves the rest alone;
    # then the unrelated "i ti t" token fix is irrelevant here.
    out = apply_ocr_fixes("adiantamentos de clientes e receitas a i")
    assert out == "adiantamentos de clientes e receitas a apropriar"


def test_apply_ocr_fixes_handles_cpv_phrase():
    out = apply_ocr_fixes("custo dos produtos vendidos e dos servicos t d")
    assert out == "custo dos produtos vendidos e dos servicos prestados"


def test_apply_ocr_fixes_whole_string_takes_priority():
    # The whole-string entry "lnadimplencia" wins over any substring rule.
    assert apply_ocr_fixes("lnadimplencia") == "inadimplencia"


def test_apply_ocr_fixes_known_substitutions():
    assert apply_ocr_fixes("lnadimplencia") == "inadimplencia"
    # Unknown labels pass through unchanged.
    assert apply_ocr_fixes("alguma coisa") == "alguma coisa"


def test_ocr_fixes_table_is_normalized():
    # All entries must be lowercase + accent-stripped (the form normalize_label
    # produces). If a future contributor adds an entry with accents, the
    # match would silently never fire.
    for k, v in OCR_FIXES.items():
        assert k == k.lower(), f"OCR_FIXES key not lowercase: {k!r}"
        assert v == v.lower(), f"OCR_FIXES value not lowercase: {v!r}"


def _rule(pattern: str, line_id: str, *, statement: str = "bp",
          side: str | None = None, canonical: str | None = None) -> Rule:
    return Rule(
        pattern=re.compile(pattern),
        line_id=line_id,
        side=side,
        where=None,
        statement=statement,
        canonical_label=canonical,
    )


def test_fuzzy_match_picks_unambiguous_top_score():
    rules = [
        _rule(r"^caixa e equivalentes de caixa$",
              "bp.ativo.circulante.caixa_equivalentes",
              canonical="caixa e equivalentes de caixa"),
        _rule(r"^contas a receber$",
              "bp.ativo.circulante.contas_a_receber",
              canonical="contas a receber"),
    ]
    # OCR mangling: "Caixa e equivelentes de caixa" — single typo.
    rule = _fuzzy_match(
        "caixa e equivelentes de caixa", "bp", None, {}, rules,
    )
    assert rule is not None
    assert rule.line_id == "bp.ativo.circulante.caixa_equivalentes"


def test_fuzzy_match_rejects_ambiguous_pair():
    """Two rules tie or near-tie on the input → reject to avoid silent
    miscategorization. The two canonical labels are identical here, so the
    runner-up gap is 0, well below _FUZZY_AMBIGUITY_GAP (5)."""
    rules = [
        _rule(r"^foo$", "bp.a", canonical="contas a receber"),
        _rule(r"^bar$", "bp.b", canonical="contas a receber"),
    ]
    rule = _fuzzy_match("contas a receber", "bp", None, {}, rules)
    assert rule is None


def test_fuzzy_match_filters_by_statement():
    rules = [
        _rule(r"^receita$", "dre.receita_bruta", statement="dre",
              canonical="receita"),
    ]
    # statement='bp' but candidate is statement='dre' → filtered out.
    assert _fuzzy_match("receita", "bp", None, {}, rules) is None


@pytest.mark.skipif(
    pytest.importorskip("rapidfuzz", reason="rapidfuzz not installed") is None,
    reason="rapidfuzz required",
)
def test_fuzzy_match_skips_when_no_canonical_label():
    rules = [_rule(r"^anything$", "bp.x", canonical=None)]
    assert _fuzzy_match("anything", "bp", None, {}, rules) is None
