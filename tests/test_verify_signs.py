"""Tests for the new verify checks: sign convention, restatement drift,
DFC↔BP cash reconciliation, BR-GAAP DRE cross-foot."""

from __future__ import annotations

import pandas as pd

from correios_audit.verify.checks import (
    cross_foot_dfc_bp_cash,
    cross_foot_dre,
    restatement_drift_check,
    sign_convention_check,
)


def _row(**kwargs) -> dict:
    """Default canonical row with sensible defaults."""
    base = {
        "doc_id": "2024-fy-df",
        "vintage_year": 2024,
        "statement": "dre",
        "side": None,
        "line_id": "dre.receita_liquida",
        "label_raw": "Receita líquida",
        "note_ref": None,
        "period_year": 2024,
        "period_kind": "fy",
        "period_label": "31/12/2024",
        "scope": "consolidado",
        "value": 18_900_000_000.0,
        "page": 1,
        "mapping_method": "regex",
    }
    base.update(kwargs)
    return base


def test_sign_convention_passes_when_signs_match_taxonomy():
    df = pd.DataFrame([
        _row(line_id="dre.receita_liquida", value=18_900_000_000.0),
        _row(line_id="dre.cpv", value=-15_000_000_000.0),  # CPV negative ✓
    ])
    results = sign_convention_check(df)
    assert all(r.passed for r in results), [
        (r.name, r.message) for r in results if not r.passed
    ]


def test_sign_convention_flags_positive_cpv():
    df = pd.DataFrame([
        _row(line_id="dre.cpv", value=15_000_000_000.0),  # WRONG: should be negative
    ])
    results = sign_convention_check(df)
    failures = [r for r in results if not r.passed]
    assert any("dre.cpv" in r.name for r in failures)


def test_sign_convention_skips_any_sign_lines():
    df = pd.DataFrame([
        _row(line_id="dre.lucro_bruto", value=-1_000.0),  # any sign — no fail
    ])
    results = sign_convention_check(df)
    assert all(r.passed for r in results)


def test_dfc_bp_cash_recon_passes_when_aligned():
    df = pd.DataFrame([
        _row(statement="dfc", line_id="dfc.caixa_fim", value=1_000_000.0),
        _row(statement="bp", side="ativo",
             line_id="bp.ativo.circulante.caixa_equivalentes",
             value=1_000_000.0),
    ])
    res = cross_foot_dfc_bp_cash(df, 2024)
    assert res is not None
    assert res.passed


def test_dfc_bp_cash_recon_flags_mismatch():
    df = pd.DataFrame([
        _row(statement="dfc", line_id="dfc.caixa_fim", value=1_000_000.0),
        _row(statement="bp", side="ativo",
             line_id="bp.ativo.circulante.caixa_equivalentes",
             value=2_000_000.0),  # 100% off → fails
    ])
    res = cross_foot_dfc_bp_cash(df, 2024)
    assert res is not None
    assert not res.passed


def test_dfc_bp_cash_recon_returns_none_when_either_missing():
    df = pd.DataFrame([
        _row(statement="dfc", line_id="dfc.caixa_fim", value=1_000_000.0),
    ])
    res = cross_foot_dfc_bp_cash(df, 2024)
    assert res is None


def test_dfc_bp_cash_recon_ignores_cross_vintage_restatements():
    """If DFC reports caixa_fim=914M for 2021 (in vintage 2021) and BP later
    restates the same period to 87M (vintage 2023), the recon must NOT flag
    that as a mismatch — it's a real restatement, caught by the drift check
    instead. The recon only compares values from the same source doc.
    """
    df = pd.DataFrame([
        _row(doc_id="2021-fy-df", vintage_year=2021,
             statement="dfc", line_id="dfc.caixa_fim",
             period_year=2021, value=914_000_000.0),
        _row(doc_id="2021-fy-df", vintage_year=2021,
             statement="bp", side="ativo",
             line_id="bp.ativo.circulante.caixa_equivalentes",
             period_year=2021, value=914_000_000.0),
        # Restated value, separate doc/vintage:
        _row(doc_id="2023-fy-df", vintage_year=2023,
             statement="bp", side="ativo",
             line_id="bp.ativo.circulante.caixa_equivalentes",
             period_year=2021, value=87_000_000.0),
    ])
    res = cross_foot_dfc_bp_cash(df, 2021)
    assert res is not None
    assert res.passed, f"recon should pass when same-doc DFC/BP align: {res.message}"


def test_restatement_drift_passes_under_threshold():
    df = pd.DataFrame([
        _row(doc_id="2017-fy-df", vintage_year=2017, period_year=2017,
             value=10_000_000.0, line_id="bp.ativo.total"),
        _row(doc_id="2018-fy-df", vintage_year=2018, period_year=2017,
             value=10_050_000.0, line_id="bp.ativo.total"),  # 0.5% drift
    ])
    results = restatement_drift_check(df)
    failures = [r for r in results if not r.passed]
    assert not failures


def test_restatement_drift_fails_above_threshold():
    df = pd.DataFrame([
        _row(doc_id="2017-fy-df", vintage_year=2017, period_year=2017,
             value=10_000_000.0, line_id="bp.ativo.total"),
        _row(doc_id="2018-fy-df", vintage_year=2018, period_year=2017,
             value=12_000_000.0, line_id="bp.ativo.total"),  # 20% drift
    ])
    results = restatement_drift_check(df)
    failures = [r for r in results if not r.passed]
    assert any("bp.ativo.total/2017" in r.name for r in failures)


def test_br_gaap_dre_crossfoot_includes_plr_and_jcp():
    """Pre-2010 cross-foot must include PLR and reversao_jcp legs."""
    df = pd.DataFrame([
        _row(period_year=2008, line_id="dre.resultado_antes_ir",
             value=1_000_000.0),
        _row(period_year=2008, line_id="dre.tributos_sobre_lucro",
             value=-300_000.0),
        _row(period_year=2008, line_id="dre.participacao_lucros",
             value=-100_000.0),
        _row(period_year=2008, line_id="dre.reversao_jcp",
             value=200_000.0),
        _row(period_year=2008, line_id="dre.resultado_liquido",
             value=800_000.0),  # 1,000 + (-300) + (-100) + 200 = 800 ✓
    ])
    results = cross_foot_dre(df, 2008)
    rl_check = [r for r in results if "resultado_liquido" in r.name]
    assert rl_check and rl_check[0].passed
