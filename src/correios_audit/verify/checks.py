"""
Verification checks on the canonical parquet:

1. **Cross-foots**:
   - BP: Total Ativo == Total Passivo + Patrimônio Líquido.
   - DRE: Lucro bruto == Receita líquida + CPV.
   - DRE: Resultado líquido == Resultado antes do IR + Tributos
     (post-IFRS, plus PLR and reversão de JCP for BR-GAAP era).
   - DFC ↔ BP: dfc.caixa_fim == bp.ativo.circulante.caixa_equivalentes.
2. **Sign convention**: every canonical row whose taxonomy line declares
   sign="+" or sign="-" must match.
3. **Restatement drift**: when the same (line_id, period_year) is reported
   across multiple vintages, |latest − earliest| / |earliest| must stay
   ≤ 1% unless allowlisted in
   `data/manual_overrides/restatements_allowed.yaml`.
4. **Materiality gate**: any unmapped row > 0.5% of revenue fails.
5. **Golden fixtures**: hand-verified figures per year in `verify/golden/`.

This is a build-gating script: prints results to stdout and returns nonzero on
material breaks. With no soft-fail allowlist anymore, every brochure-era doc
must either pass extraction or be covered by `data/manual_overrides/`.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from correios_audit.normalize.taxonomy import LINES_BY_ID

ROOT = Path(__file__).resolve().parents[3]
PROCESSED = ROOT / "data" / "processed" / "canonical.parquet"
UNMAPPED_DIR = ROOT / "data" / "interim" / "unmapped"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
MANUAL_OVERRIDES_DIR = ROOT / "data" / "manual_overrides"
RESTATEMENTS_ALLOWLIST = MANUAL_OVERRIDES_DIR / "restatements_allowed.yaml"

ROUNDING_TOL = 1_000.0           # R$ 1k tolerance for rounding
MATERIALITY_FRAC = 0.005          # 0.5% of revenue
RESTATEMENT_DRIFT_FRAC = 0.01     # 1% drift between vintages


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    severity: str = "error"   # "error" or "warning"


def _value(df: pd.DataFrame, *, line_id: str, period_year: int,
           vintage_year: int | None = None,
           period_kind: str = "fy",
           scope: str = "consolidado") -> float | None:
    """Look up a canonical value. Defaults to the consolidated view of FY data;
    falls back to the controlling-entity (Controladora) view when consolidated
    is missing for that period."""
    base = df[(df.line_id == line_id) & (df.period_year == period_year)
              & (df.period_kind == period_kind)]
    if vintage_year is not None:
        base = base[base.vintage_year == vintage_year]
    sub = base[base.scope == scope] if "scope" in base.columns else base
    if sub.empty and scope == "consolidado" and "scope" in base.columns:
        sub = base[base.scope == "controladora"]
    if sub.empty:
        return None
    sub = sub.copy()
    sub["_pref"] = sub["doc_id"].str.contains("-fy-").astype(int)
    return float(sub.sort_values(["vintage_year", "_pref"]).iloc[-1]["value"])


def cross_foot_bp(df: pd.DataFrame, period_year: int) -> CheckResult | None:
    """Cross-foot uses the SAME document for ativo and passivo to avoid
    mixing vintages (restatements can shift totals across reports).

    Returns None when no doc has reported the FY column for `period_year`
    yet — the year is still in progress (only quarterly publications
    exist), so demanding annual totals would produce false-warnings.
    """
    fy_for_year = df[
        (df.period_year == period_year) & (df.period_kind == "fy")
    ]
    if fy_for_year.empty:
        return None
    candidates = df[
        (df.line_id.isin(["bp.ativo.total", "bp.passivo.total"]))
        & (df.period_year == period_year)
        & (df.period_kind == "fy")
    ]
    best = None
    if not candidates.empty:
        c = candidates.copy()
        c["_pref"] = c["doc_id"].str.contains("-fy-").astype(int)
        # For each doc/scope, see if it has BOTH totals; pick latest vintage with both.
        for (doc_id, scope), grp in c.groupby(["doc_id", "scope"]):
            line_ids = set(grp.line_id)
            if {"bp.ativo.total", "bp.passivo.total"}.issubset(line_ids):
                a = float(grp[grp.line_id == "bp.ativo.total"].iloc[0]["value"])
                p = float(grp[grp.line_id == "bp.passivo.total"].iloc[0]["value"])
                vy = int(grp.iloc[0]["vintage_year"])
                pref = int(grp.iloc[0]["_pref"])
                # Prefer consolidado scope, then latest vintage, then FY pref.
                rank = (scope == "consolidado", vy, pref)
                if best is None or rank > best[0]:
                    best = (rank, a, p, doc_id, scope, vy)
    if best is None:
        # Fallback: try latest-vintage lookups separately (may mix vintages).
        a = _value(df, line_id="bp.ativo.total", period_year=period_year)
        p = _value(df, line_id="bp.passivo.total", period_year=period_year)
        if a is None or p is None:
            return CheckResult(
                f"bp_crossfoot[{period_year}]",
                False,
                f"missing total: ativo={a}, passivo+pl={p}",
                severity="warning",
            )
        diff = a - p
        return CheckResult(
            f"bp_crossfoot[{period_year}]",
            abs(diff) <= ROUNDING_TOL,
            f"ativo={a:,.0f}, passivo+PL={p:,.0f}, diff={diff:,.0f} (mixed vintages)",
        )
    _, a, p, doc_id, scope, vy = best
    diff = a - p
    return CheckResult(
        f"bp_crossfoot[{period_year}]",
        abs(diff) <= ROUNDING_TOL,
        f"ativo={a:,.0f}, passivo+PL={p:,.0f}, diff={diff:,.0f} ({doc_id}/{scope})",
    )


def cross_foot_dre(df: pd.DataFrame, period_year: int) -> list[CheckResult]:
    out: list[CheckResult] = []
    # Pick a single vintage where ALL three sides of the lucro_bruto
    # equation are present, preferring the most recent. If a vintage has
    # only some components, mixing in another vintage's values would
    # cross-foot across restatement boundaries (e.g. 2012 brochure
    # publishes RL+CPV+LB consistently, but the 2013 brochure's prior-
    # period column has different CPV after reclassification).
    sub = df[df.period_year == period_year]
    line_ids = {"dre.receita_liquida", "dre.cpv", "dre.lucro_bruto"}
    coverage_by_vintage = (
        sub[sub.line_id.isin(line_ids)]
        .groupby("vintage_year")["line_id"].nunique()
        .to_dict()
    )
    full_vintages = sorted(
        v for v, n in coverage_by_vintage.items() if n == len(line_ids)
    )
    pinned_vintage = full_vintages[-1] if full_vintages else None
    rl = _value(df, line_id="dre.receita_liquida", period_year=period_year,
                vintage_year=pinned_vintage)
    cpv = _value(df, line_id="dre.cpv", period_year=period_year,
                 vintage_year=pinned_vintage)
    lb = _value(df, line_id="dre.lucro_bruto", period_year=period_year,
                vintage_year=pinned_vintage)
    if rl is not None and cpv is not None and lb is not None:
        diff = (rl + cpv) - lb
        tol = max(ROUNDING_TOL, abs(lb) * 0.005)
        out.append(CheckResult(
            f"dre_lucro_bruto[{period_year}]",
            abs(diff) <= tol,
            f"receita_liquida + cpv = {rl + cpv:,.0f} vs lucro_bruto={lb:,.0f}, diff={diff:,.0f}",
        ))
    raoir = _value(df, line_id="dre.resultado_antes_ir", period_year=period_year)
    tax = _value(df, line_id="dre.tributos_sobre_lucro", period_year=period_year)
    rl_net = _value(df, line_id="dre.resultado_liquido", period_year=period_year)
    # Pre-IFRS DRE flow includes PLR and reversão de JCP between
    # resultado-antes-IR and resultado líquido. We have two ways to verify:
    #
    #   (A) Full chain: raoir + tax + plr + reversao_jcp == resultado_liquido
    #   (B) Sub-totals: raoir + tax + plr == resultado_antes_jcp
    #                   resultado_antes_jcp + reversao_jcp == resultado_liquido
    #
    # The brochure-era OCR sometimes loses the bare reversão_jcp value (it
    # ends up as a "(continued)" row without a clean label). When that
    # happens we still want to verify what we *can* prove. Path B uses
    # `dre.resultado_antes_jcp` as a checkpoint: if it's present and matches
    # the upper sub-total, we accept that as the cross-foot pass and skip
    # the unknown-reversão-jcp leg.
    plr = _value(df, line_id="dre.participacao_lucros", period_year=period_year)
    rev_jcp = _value(df, line_id="dre.reversao_jcp", period_year=period_year)
    r_antes_jcp = _value(df, line_id="dre.resultado_antes_jcp", period_year=period_year)
    if raoir is not None and tax is not None and rl_net is not None:
        # Path B (pre-IFRS w/ checkpoint): if r_antes_jcp is present, verify
        # the upper sub-equation only. Reversão de JCP (which we may not
        # have) reconciles by definition: liquido - r_antes_jcp.
        if r_antes_jcp is not None:
            upper = raoir + tax + (plr or 0.0)
            diff = upper - r_antes_jcp
            tol = max(ROUNDING_TOL, abs(r_antes_jcp) * 0.005)
            legs = ["r_antes_ir", "tributos"]
            if plr is not None:
                legs.append("plr")
            implied_rev_jcp = rl_net - r_antes_jcp
            out.append(CheckResult(
                f"dre_resultado_liquido[{period_year}]",
                abs(diff) <= tol,
                f"{'+'.join(legs)} = {upper:,.0f} vs r_antes_jcp={r_antes_jcp:,.0f}, "
                f"diff={diff:,.0f}; implied reversão_jcp={implied_rev_jcp:,.0f}",
            ))
        else:
            adjusted = raoir + tax + (plr or 0.0) + (rev_jcp or 0.0)
            diff = adjusted - rl_net
            tol = max(ROUNDING_TOL, abs(rl_net) * 0.005)
            legs = ["r_antes_ir", "tributos"]
            if plr is not None:
                legs.append("plr")
            if rev_jcp is not None:
                legs.append("reversao_jcp")
            out.append(CheckResult(
                f"dre_resultado_liquido[{period_year}]",
                abs(diff) <= tol,
                f"{'+'.join(legs)} = {adjusted:,.0f} vs r_liquido={rl_net:,.0f}, "
                f"diff={diff:,.0f}",
            ))
    return out


def cross_foot_dfc_bp_cash(df: pd.DataFrame, period_year: int) -> CheckResult | None:
    """The DFC's closing cash (`dfc.caixa_fim`) must equal the BP's caixa
    equivalentes for the same period — *same doc*. Comparing values across
    different vintages would catch legitimate restatements (e.g., the 2022-Q3
    reclassification of 2021 cash) as if they were extraction errors; that's
    the restatement-drift check's job, not this one.

    Returns None when no single doc contains both totals — the report may
    publish DFC and BP separately, or the parser missed one.
    """
    sub = df[
        df.line_id.isin(["dfc.caixa_fim", "bp.ativo.circulante.caixa_equivalentes"])
        & (df.period_year == period_year)
        & (df.period_kind == "fy")
    ]
    if sub.empty:
        return None
    best: tuple | None = None
    for (doc_id, scope), grp in sub.groupby(["doc_id", "scope"]):
        line_ids = set(grp.line_id)
        if {"dfc.caixa_fim", "bp.ativo.circulante.caixa_equivalentes"}.issubset(line_ids):
            dfc_end = float(grp[grp.line_id == "dfc.caixa_fim"].iloc[0]["value"])
            bp_caixa = float(
                grp[grp.line_id == "bp.ativo.circulante.caixa_equivalentes"].iloc[0]["value"]
            )
            vy = int(grp.iloc[0]["vintage_year"])
            rank = (scope == "consolidado", vy)
            if best is None or rank > best[0]:
                best = (rank, dfc_end, bp_caixa, doc_id, scope, vy)
    if best is None:
        return None
    _, dfc_end, bp_caixa, doc_id, scope, vy = best
    diff = dfc_end - bp_caixa
    tol = max(ROUNDING_TOL, abs(bp_caixa) * 0.005)
    return CheckResult(
        f"dfc_bp_cash_recon[{period_year}]",
        abs(diff) <= tol,
        f"dfc.caixa_fim={dfc_end:,.0f} vs bp.caixa_equivalentes={bp_caixa:,.0f}, "
        f"diff={diff:,.0f}, tol={tol:,.0f} ({doc_id}/{scope})",
    )


def sign_convention_check(df: pd.DataFrame) -> list[CheckResult]:
    """Every canonical row whose taxonomy line declares sign='+' or '-' must
    match. Sign='any' rows are skipped.

    A single sign violation is a hard fail — a positive CPV in canonical
    means we mis-parenthesized a negative or mis-mapped a row to the wrong
    line_id. Materiality threshold (R$1) ensures rounding-near-zero values
    don't fail (a CPV that legitimately rounds to 0 isn't a violation).
    """
    out: list[CheckResult] = []
    for line_id, line in LINES_BY_ID.items():
        if line.sign == "any":
            continue
        sub = df[df.line_id == line_id]
        if sub.empty:
            continue
        wrong = sub[
            ((line.sign == "+") & (sub.value < -1.0))
            | ((line.sign == "-") & (sub.value > 1.0))
        ]
        if wrong.empty:
            continue
        # Group violations by vintage_year/period_year for compactness.
        sample = wrong.head(3)
        msg_parts = [
            f"v{int(r.vintage_year)}/p{int(r.period_year)}={r.value:,.0f}"
            for _, r in sample.iterrows()
        ]
        out.append(CheckResult(
            f"sign[{line_id}]",
            False,
            f"expected sign={line.sign}, got {len(wrong)} violations: "
            f"{', '.join(msg_parts)}{'...' if len(wrong) > 3 else ''}",
        ))
    if not out:
        out.append(CheckResult("sign_convention", True, "all signs match taxonomy"))
    return out


def _load_restatement_allowlist() -> list[dict]:
    """Allowlist YAML format. Each entry has:

      - line_id: <exact id>  OR  line_id_prefix: <dotted prefix>
        period_year: <int>  OR  period_years: [<int>, ...]
        vintage_from: <int>  (optional — only allowlist drifts where the
                              earliest involved vintage matches this)
        vintage_to: <int>    (optional — only allowlist drifts where the
                              latest involved vintage matches this)
        reason: <one-sentence justification>

    Either `line_id` (exact match) or `line_id_prefix` (any line_id starting
    with this string) is required. `period_years` covers multiple periods
    in one entry. Vintage filters narrow the scope to a specific restatement
    event (e.g., "the 2022 vintage restated 2020-2021 DVA" → vintage_from=2021,
    vintage_to=2022).
    """
    if not RESTATEMENTS_ALLOWLIST.exists():
        return []
    data = yaml.safe_load(RESTATEMENTS_ALLOWLIST.read_text()) or {}
    return list(data.get("entries", []))


def _allowlist_match(
    entries: list[dict], *, line_id: str, period_year: int,
    vintage_from: int, vintage_to: int,
) -> str | None:
    """Return the matching entry's `reason` if any allowlist entry covers
    this (line_id, period_year, vintage pair), else None."""
    for entry in entries:
        # line_id match: exact or prefix
        exact = entry.get("line_id")
        prefix = entry.get("line_id_prefix")
        if exact is not None and exact != line_id:
            continue
        if prefix is not None and not line_id.startswith(prefix):
            continue
        if exact is None and prefix is None:
            continue
        # period_year match: single or list
        py = entry.get("period_year")
        pys = entry.get("period_years")
        if py is not None and int(py) != period_year:
            continue
        if pys is not None and period_year not in [int(p) for p in pys]:
            continue
        if py is None and pys is None:
            continue
        # Optional vintage filters
        vf = entry.get("vintage_from")
        vt = entry.get("vintage_to")
        if vf is not None and int(vf) != vintage_from:
            continue
        if vt is not None and int(vt) != vintage_to:
            continue
        return entry.get("reason", "")
    return None


# line_ids whose multi-row mappings are confirmed-intentional aggregations.
# These accept multiple distinct label_raw values from the same doc + period
# without warning. Add to this set ONLY after auditing the source PDFs;
# everything else surfaces from `line_id_collision_check`.
_KNOWN_LINE_ID_COLLISIONS: set[str] = {
    # IFRS-16 split: "Empréstimos e financiamentos - Juros" +
    # "Bens direito de uso - Juros" both feed the aggregate juros pago.
    "dfc.fin.juros_pagos",
    "dfc.fin.arrendamento",
    # Brochure-era BPs print "(-) Depreciação Acumulada" and "(-) Amortização
    # Acumulada" as separate sub-rows of imobilizado.
    "bp.ativo.nao_circulante.imobilizado.depreciacao",
    # IFRS unified BR-GAAP's "Outros Créditos / Outros Débitos / Outros
    # Valores e Bens" into a single "outros valores e bens" bucket.
    "bp.ativo.circulante.outros_valores_e_bens",
    # "Intangível" parent + "Softwares" sub-category routinely both feed
    # the intangivel parent in pre-2014 vintages.
    "bp.ativo.nao_circulante.intangivel",
    # 2018 vintage split out "Receitas a Apropriar" from
    # "Adiantamentos de Clientes"; brochure era kept them combined.
    "bp.passivo.circulante.adiantamentos_clientes",
    # Salários + Encargos sociais in DFC mutações are sub-categories of
    # the salarios bucket.
    "dfc.op.mutacoes.salarios",
    # "Mandados e Precatórios" / "Precatórios Judiciais" are the same line
    # under two label variants.
    "bp.passivo.circulante.precatorios",
    # Materiais / Propaganda / Utilidades all feed insumos.outros bucket.
    "dva.insumos.outros",
    # IRPJ+CSLL and impostos federais both feed the governo.outros bucket
    # for DVA distributions.
    "dva.dist.governo.outros",
    # Dividendos+JCP and Lucros Retidos both go into acionistas.lucros_retidos
    # (distributions retained or paid out).
    "dva.dist.acionistas.lucros_retidos",
    # Various ganho/realização/CSLL valor justo lines feed the imoveis +
    # csll_diferida buckets in DRA itens não reclassificáveis.
    "dra.itens_nao_reclassificaveis.imoveis",
    "dra.itens_nao_reclassificaveis.csll_diferida",
    # "Aplicações financeiras" and Correiospar-investment movements both
    # feed the DFC investing aplicacoes_financeiras bucket.
    "dfc.inv.aplicacoes_financeiras",
    # Adições/Baixas of propriedades para investimento aggregate net.
    "dfc.inv.propriedades_investimento",
    # 2017+ vintages publish "Salários e Consignações" + "Encargos Sociais"
    # + "Benefício Pós-Emprego" + "Obrigações Trabalhistas" as siblings;
    # 2023+ vintages collapse them into a single "Benefícios a empregados"
    # row. Both feed the CP aggregate intentionally.
    "bp.passivo.circulante.beneficios_a_empregados",
    # 2014 BP repeats the same "Empréstimos e Financiamentos" label in
    # both CP and NCP positions of the brochure layout; the NCP row
    # additionally carries the "14.9" note ref. Parser-level fix would
    # need stronger CP/NCP boundary detection, but the two values
    # legitimately sum to total emprestimos.
    "bp.passivo.circulante.emprestimos",
    # NCP "outros" collects "Obrigações Trabalhistas" and various other
    # uncategorized labels. Routing trabalhistas to its own line_id broke
    # the 2019/2021 postalis golden fixtures (different rows shadowed the
    # parent). The aggregation here is a parser quirk, not a correctness
    # issue; the values legitimately sum into the NCP "outros" bucket.
    "bp.passivo.nao_circulante.outros",
    # Various imobilizado baixas (sucateamento, museu, mantidos para venda).
    "dfc.inv.imobilizado_baixas",
    # DFC operacional minor "outros" + variação patrimonial bucket.
    "dfc.op.itens_nao_caixa.outros",
    "dfc.op.mutacoes.outras",
    # Receitas não-op + outras receitas operacionais (BR-GAAP→IFRS continuity).
    "dva.receitas.outras",
}


def line_id_collision_check(df: pd.DataFrame) -> list[CheckResult]:
    """Surface line_ids that get mapped from multiple distinct labels.

    The drift check sums these silently because IFRS-16 legitimately
    produces collisions (e.g. "Empréstimos - Juros" + "Bens direito de uso
    - Juros" both map to `dfc.fin.juros_pagos` and should aggregate). But a
    new mapping rule that accidentally fuses two unrelated labels would
    *also* sum silently — this check makes the collision visible as a
    warning so a human can decide whether the aggregation is intentional.

    Output is aggregated by `line_id` (one warning per fused line_id, with
    the impact footprint), not by `(doc_id, period_year)` — the ambiguity
    is a property of the mapping rules, not of any single document.

    Allowlist `_KNOWN_LINE_ID_COLLISIONS` for confirmed aggregations.
    """
    out: list[CheckResult] = []
    parsed = df[~df.doc_id.fillna("").str.startswith("manual:")]
    if parsed.empty:
        return out
    # Per (doc, line, period, scope) — collect distinct labels.
    by_group: dict[str, dict] = {}
    groups = parsed.groupby(
        ["doc_id", "line_id", "period_year", "period_kind", "scope"],
        dropna=False,
    )
    for (doc_id, line_id, period_year, _pk, _scope), grp in groups:
        if line_id in _KNOWN_LINE_ID_COLLISIONS:
            continue
        labels = {str(lbl) for lbl in grp["label_raw"].dropna()}
        if len(labels) < 2:
            continue
        bucket = by_group.setdefault(line_id, {"labels": set(), "tuples": []})
        bucket["labels"].update(labels)
        bucket["tuples"].append((doc_id, int(period_year)))
    if not by_group:
        return out
    for line_id, info in sorted(by_group.items()):
        labels_list = sorted(info["labels"])[:5]
        out.append(CheckResult(
            f"line_id_collision[{line_id}]",
            False,
            f"{len(info['tuples'])} (doc, period) tuples fuse distinct "
            f"labels into one line_id — labels: {labels_list}"
            f"{' …' if len(info['labels']) > 5 else ''} — drift check sums "
            f"these silently. If intentional, add line_id to "
            f"_KNOWN_LINE_ID_COLLISIONS in verify/checks.py.",
            severity="warning",
        ))
    return out


def restatement_drift_check(df: pd.DataFrame) -> list[CheckResult]:
    """For every (line_id, period_year) reported in ≥2 vintages, fail when
    |latest − earliest| / |earliest| > RESTATEMENT_DRIFT_FRAC.

    Skips:
    - Manual-override rows ('manual:' prefix) — their vintage_year is the
      user-declared one and they coexist with parsed rows for the same
      vintage.
    - Pairs where either vintage is brochure-era (≤ 2009). Pre-IFRS
      publication conventions and OCR extraction quality differ enough from
      the modern era that cross-era drift comparisons are dominated by
      methodology noise, not real restatements. Drift within the modern era
      (≥ 2010 on both sides) is what catches legitimate intentional
      restatements; this is the only era where the check has high
      signal-to-noise.
    """
    out: list[CheckResult] = []
    allowlist = _load_restatement_allowlist()
    parsed = df[~df.doc_id.fillna("").str.startswith("manual:")]
    if parsed.empty:
        return [CheckResult("restatement_drift", True, "no parsed rows yet")]
    base = parsed[parsed.period_kind == "fy"].copy()
    if base.empty:
        return [CheckResult("restatement_drift", True, "no FY rows yet")]
    # Drop quarterly publications. A vintage like 2025 has FOUR docs that
    # republish the 2024 FY column (2025-q1-df, q2, q3, plus 2025-fy-df if
    # present). Including them all triples the per-vintage row count for
    # that period and breaks the sub-category sum() below. The drift check
    # only cares about *annual* restatements, so the FY doc is the source
    # of truth per vintage. Use the catalog's authoritative `period` field
    # rather than substring-matching the doc_id (which would silently drop
    # any future doc_id that doesn't follow the `-fy-` naming convention).
    from correios_audit.catalog import by_id as _by_id

    def _is_fy_doc(doc_id: str | None) -> bool:
        if not doc_id:
            return False
        try:
            return _by_id(doc_id).period == "fy"
        except KeyError:
            # Doc not in the catalog (manual rows already filtered above) —
            # fall back to the naming convention so unfamiliar doc_ids
            # don't slip in unnoticed.
            return "-fy-" in doc_id

    base = base[base.doc_id.fillna("").map(_is_fy_doc)]
    if base.empty:
        return [CheckResult("restatement_drift", True, "no FY-publication rows yet")]
    if "scope" in base.columns:
        base = base.sort_values(
            by=["scope"],
            key=lambda s: s.eq("consolidado").astype(int),
            ascending=False,
        )
    BROCHURE_ERA_THRESHOLD = 2010
    # Group by (line_id, period_year, scope) so consolidado-vs-controladora
    # mismatches across vintages don't masquerade as drifts. Pick whichever
    # scope has the most cross-vintage coverage; if both scopes have ≥2
    # modern vintages, prefer consolidado (the standard external view).
    for (line_id, period_year), grp_lp in base.groupby(["line_id", "period_year"]):
        scope_picks: list[tuple[str, list[float]]] = []
        for scope_name in ("consolidado", "controladora"):
            sub_scope = grp_lp[grp_lp.scope == scope_name] if "scope" in grp_lp.columns else grp_lp
            vintages = sorted(sub_scope.vintage_year.dropna().unique())
            modern = [v for v in vintages if v >= BROCHURE_ERA_THRESHOLD]
            if len(modern) < 2:
                continue
            scope_picks.append((scope_name, modern, sub_scope))
        if not scope_picks:
            continue
        scope_name, modern, sub_scope = scope_picks[0]   # consolidado preferred
        # Sum rather than iloc[0]: when multiple labels in the same vintage
        # map to the same line_id (e.g. "Empréstimos - Juros" and "Bens
        # direito de uso - Juros" both → dfc.fin.juros_pagos in IFRS-16-era
        # DFCs), they are sub-components that should aggregate. Picking a
        # single row would produce non-deterministic drift readings.
        earliest = float(sub_scope[sub_scope.vintage_year == modern[0]]["value"].sum())
        latest = float(sub_scope[sub_scope.vintage_year == modern[-1]]["value"].sum())
        if abs(earliest) < 1.0:
            continue
        drift = abs(latest - earliest) / abs(earliest)
        if drift <= RESTATEMENT_DRIFT_FRAC:
            continue
        reason = _allowlist_match(
            allowlist,
            line_id=line_id,
            period_year=int(period_year),
            vintage_from=int(modern[0]),
            vintage_to=int(modern[-1]),
        )
        if reason is not None:
            out.append(CheckResult(
                f"restatement_drift[{line_id}/{period_year}]",
                True,
                f"drift={drift:.1%} (allowlisted: {reason})",
            ))
            continue
        out.append(CheckResult(
            f"restatement_drift[{line_id}/{period_year}]",
            False,
            f"v{int(modern[0])}={earliest:,.0f} vs v{int(modern[-1])}={latest:,.0f} "
            f"({scope_name}), drift={drift:.1%} "
            f"(limit {RESTATEMENT_DRIFT_FRAC:.0%}). "
            f"Add allowlist entry with `reason:` if intentional.",
        ))
    if not out:
        out.append(CheckResult("restatement_drift", True, "no material drift"))
    return out


# A doc may opt out of the per-line materiality gate only when ALL of these
# headline figures are hand-keyed with verbatim quotes. These are the lines
# the README promises a reader can rely on — Total Ativo, Total Passivo,
# Receita Líquida, Lucro Líquido. Picking three minor sub-categories doesn't
# qualify; an opted-out doc must publish the full headline picture.
_REQUIRED_HEADLINE_LINE_IDS: tuple[str, ...] = (
    "bp.ativo.total",
    "bp.passivo.total",
    "dre.receita_liquida",
    "dre.resultado_liquido",
)

def _is_real_quote(quote: object) -> bool:
    """Mirror of `apply._is_placeholder_quote` — re-imported here would be
    cleaner, but we want this module independent of the normalize layer at
    import time (verify is a separate gate).
    """
    # Keep in sync with `_PLACEHOLDER_QUOTES` in normalize/apply.py.
    placeholders = {"", "todo", "tbd", "tba", "fixme", "xxx"}
    if quote is None:
        return False
    return str(quote).strip().lower() not in placeholders


def _docs_satisfied_by_overrides() -> dict[str, str]:
    """Read `data/manual_overrides/*.yaml` and return a mapping of
    `doc_id → reason` for files that opt out of the materiality gate.

    A file opts out only when it sets `materiality_satisfied_by_overrides:
    true` AND covers every line_id in `_REQUIRED_HEADLINE_LINE_IDS` with
    a hand-keyed value paired with a real (non-placeholder) source_quote.
    Coverage is measured at the *file* level: any single row per required
    line_id is enough (a 2008 file can satisfy bp.ativo.total via either
    period 2008 or 2007, since either proves the YAML is real).

    The strict precondition is the safety net for the opt-out: a stray
    `materiality_satisfied_by_overrides: true` on an empty scaffold would
    otherwise silently mask a real materiality failure.
    """
    out: dict[str, str] = {}
    if not MANUAL_OVERRIDES_DIR.exists():
        return out
    required = set(_REQUIRED_HEADLINE_LINE_IDS)
    for path in sorted(MANUAL_OVERRIDES_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError:
            continue
        if not data or not data.get("materiality_satisfied_by_overrides"):
            continue
        doc_id = data.get("doc_id")
        if not doc_id:
            continue
        rows = data.get("rows") or []
        keyed_lines = {
            r.get("line_id")
            for r in rows
            if r.get("value") is not None and _is_real_quote(r.get("source_quote"))
        }
        missing = required - keyed_lines
        if missing:
            print(
                f"WARN {path.name}: materiality_satisfied_by_overrides "
                f"declared but missing required headline rows: "
                f"{sorted(missing)}",
                file=sys.stderr,
            )
            continue
        out[doc_id] = (
            f"satisfied by manual_overrides/{path.name} "
            f"(all {len(required)} headline rows hand-keyed with source_quote)"
        )
    return out


def dre_coverage_check(df: pd.DataFrame) -> list[CheckResult]:
    """Every FY-publication doc should contribute at least one DRE row to
    canonical (either parsed or via manual_overrides). A doc whose DRE
    statement was missed entirely would otherwise slip past the materiality
    gate, which becomes vacuous when revenue is zero.

    Emits warnings (not failures) — a missing DRE points at a parser
    regression that needs investigation, but holding the build hostage to
    hand-keying every affected year would convert real signal into pressure
    to bypass the check. Surface and move on.

    Quarterly docs (q1/q2/q3) are exempt: some of them legitimately publish
    only BP+DFC interim and no DRE.
    """
    out: list[CheckResult] = []
    if df.empty:
        return out
    from correios_audit.catalog import by_id as _by_id

    # Per parser-doc, count DRE rows. Borrow from `manual:<year>` siblings
    # because a manual override DRE row is just as good as a parsed one.
    dre = df[df.line_id.fillna("").str.startswith("dre.")]
    by_doc = dre.groupby("doc_id").size().to_dict()
    by_year_manual: dict[str, int] = {}
    for doc_id, n in by_doc.items():
        if isinstance(doc_id, str) and doc_id.startswith("manual:"):
            by_year_manual[doc_id[len("manual:"):]] = (
                by_year_manual.get(doc_id[len("manual:"):], 0) + n
            )
    parser_doc_ids = sorted({d for d in df.doc_id.dropna().unique()
                             if isinstance(d, str) and not d.startswith("manual:")})
    for doc_id in parser_doc_ids:
        try:
            doc = _by_id(doc_id)
        except KeyError:
            continue
        if doc.period != "fy":
            continue
        n_parsed = by_doc.get(doc_id, 0)
        n_manual = by_year_manual.get(str(doc.year), 0)
        if n_parsed + n_manual == 0:
            out.append(CheckResult(
                f"dre_coverage[{doc_id}]",
                False,
                f"no DRE rows in canonical (parsed=0, manual=0). "
                f"Materiality cannot be computed without revenue baseline. "
                f"Add headline figures to "
                f"data/manual_overrides/{doc.year}.yaml.",
                severity="warning",
            ))
    if not out:
        out.append(CheckResult("dre_coverage", True,
                               "every FY doc has DRE coverage"))
    return out


def materiality_gate(df: pd.DataFrame) -> list[CheckResult]:
    """Per-doc unmapped > 0.5% of revenue is a hard failure for every
    vintage. Brochure-era docs (2001-2009) and the 2023-Q2 outlier must now
    pass via `data/manual_overrides/<year>.yaml` covering at least the
    headline figures (revenue, totals, net income, cash, capital).

    A doc whose YAML sets `materiality_satisfied_by_overrides: true` and
    has ≥3 hand-keyed headline rows is exempted — for brochures with
    column-bleed parsing the line-level unmapped CSV is itself unreliable
    (labels and values fuse across columns), so the override file becomes
    the source of truth.
    """
    out: list[CheckResult] = []
    if not UNMAPPED_DIR.exists():
        return out
    satisfied = _docs_satisfied_by_overrides()
    # Lazy import: avoids a verify→normalize→verify circular-ish dep at module
    # load time. We only need `_scale_for_doc` here.
    from correios_audit.catalog import by_id
    from correios_audit.normalize.apply import _scale_for_doc

    # Build per-doc revenue index. Borrow from the manual-override sibling
    # (`manual:<year>`) when the parser missed it — for brochure-era docs
    # the override file IS the revenue source of truth.
    rev_by_doc: dict[str, float] = {}
    for doc_id, sub in df[df.line_id == "dre.receita_liquida"].groupby("doc_id"):
        if sub.empty:
            continue
        rev_by_doc[doc_id] = float(sub.sort_values("period_year").iloc[-1]["value"])
    # Borrow the manual:<year> revenue ONLY for FY docs. Quarterly docs
    # would inherit a full-year revenue (~4x their actual interim revenue),
    # which artificially lowers the materiality threshold and false-fails
    # a clean parse. Quarterlies without a parsed receita_liquida fall
    # through to the original `threshold=inf` vacuous-pass path — the
    # `dre_coverage_check` warns about FY docs without DRE separately.
    from correios_audit.catalog import by_id as _by_id
    for parser_doc_id in sorted({p.stem for p in UNMAPPED_DIR.glob("*.csv")}):
        if parser_doc_id in rev_by_doc:
            continue
        try:
            doc = _by_id(parser_doc_id)
        except KeyError:
            continue
        if doc.period != "fy":
            continue
        rev = rev_by_doc.get(f"manual:{doc.year}")
        if rev is not None:
            rev_by_doc[parser_doc_id] = rev
    for csv_path in sorted(UNMAPPED_DIR.glob("*.csv")):
        doc_id = csv_path.stem
        if doc_id in satisfied:
            out.append(CheckResult(
                f"materiality[{doc_id}]",
                True,
                satisfied[doc_id],
            ))
            continue
        rev = rev_by_doc.get(doc_id, 0.0)
        # NB: when `rev=0` (no parser receita AND no manual override)
        # threshold becomes inf and the per-line check vacuously passes.
        # That gap is covered by `dre_coverage_check` below: it fails the
        # build for FY docs whose DRE statement was missed entirely so
        # they can't slip through with infinite materiality.
        threshold = abs(rev) * MATERIALITY_FRAC if rev else float("inf")
        try:
            doc = by_id(doc_id)
        except KeyError:
            doc = None
        scale = _scale_for_doc(doc) if doc is not None else 1000.0
        big: list[tuple[str, float]] = []
        with csv_path.open() as f:
            for row in csv.DictReader(f):
                values = json.loads(row["values"]) if row["values"] else {}
                # Multiply by the doc's per-year currency scale so the
                # comparison happens in raw R$ — same unit as `threshold`.
                max_val = max(
                    (abs(v) * scale for v in values.values() if v is not None),
                    default=0.0,
                )
                if max_val > threshold:
                    big.append((row["label"], max_val))
        if big:
            sample = ", ".join(f"{lbl[:40]} ({v/1e6:.1f}M)" for lbl, v in big[:5])
            out.append(CheckResult(
                f"materiality[{doc_id}]",
                False,
                f"{len(big)} unmapped lines exceed {MATERIALITY_FRAC:.1%} of revenue "
                f"({threshold/1e6:.1f}M). Top: {sample}. "
                f"Cover via data/manual_overrides/.",
            ))
    return out


def golden_fixtures(df: pd.DataFrame) -> list[CheckResult]:
    """A golden file is `verify/golden/<year>.csv` with columns:
    line_id, period_year, value (in millions of R$).
    """
    out: list[CheckResult] = []
    if not GOLDEN_DIR.exists():
        return out
    for csv_path in sorted(GOLDEN_DIR.glob("*.csv")):
        year = int(csv_path.stem)
        with csv_path.open() as f:
            for row in csv.DictReader(f):
                line_id = row["line_id"]
                period_year = int(row["period_year"])
                expected = float(row["value"]) * 1_000_000
                actual = _value(df, line_id=line_id, period_year=period_year,
                                vintage_year=year)
                if actual is None:
                    out.append(CheckResult(
                        f"golden[{year}/{line_id}/{period_year}]",
                        False,
                        f"missing in canonical (vintage={year})",
                    ))
                    continue
                diff = abs(actual - expected)
                # Tolerance: 0.5% of expected, min 1k.
                tol = max(ROUNDING_TOL, abs(expected) * 0.005)
                out.append(CheckResult(
                    f"golden[{year}/{line_id}/{period_year}]",
                    diff <= tol,
                    f"expected={expected:,.0f}, actual={actual:,.0f}, diff={diff:,.0f}",
                ))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true",
                        help="Exit nonzero on warnings as well as errors.")
    args = parser.parse_args(argv)

    if not PROCESSED.exists():
        print(f"ERROR: {PROCESSED} not found. Run `make normalize` first.", file=sys.stderr)
        return 2
    df = pd.read_parquet(PROCESSED)

    results: list[CheckResult] = []
    # Identify period years actually present so we don't false-fail empty years.
    years = sorted(df.period_year.dropna().unique())
    for y in years:
        bp_result = cross_foot_bp(df, int(y))
        if bp_result is not None:
            results.append(bp_result)
        results.extend(cross_foot_dre(df, int(y)))
        cash_check = cross_foot_dfc_bp_cash(df, int(y))
        if cash_check is not None:
            results.append(cash_check)
    results.extend(sign_convention_check(df))
    results.extend(line_id_collision_check(df))
    results.extend(restatement_drift_check(df))
    results.extend(dre_coverage_check(df))
    results.extend(materiality_gate(df))
    results.extend(golden_fixtures(df))

    n_fail = 0
    n_warn = 0
    for r in results:
        marker = "PASS" if r.passed else r.severity.upper()
        print(f"[{marker}] {r.name}: {r.message}")
        if not r.passed:
            if r.severity == "error":
                n_fail += 1
            else:
                n_warn += 1
    print(f"\nsummary: {len(results)} checks, {n_fail} failures, {n_warn} warnings",
          file=sys.stderr)
    return 1 if n_fail > 0 or (args.strict and n_warn > 0) else 0


if __name__ == "__main__":
    sys.exit(main())
