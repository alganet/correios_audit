"""
Render the static HTML site from data/processed/canonical.parquet.

Pages:
- index.html — executive summary + multi-decade charts
- years.html — table of years
- year/<YYYY>.html — full canonical statements for a year
- lens/{profitability,balance_sheet,cash_flow,governance}.html
- doc/<doc_id>.html — provenance: every figure with page number + raw label

Charts: Plotly via embedded JSON, single shared plotly.min.js.
"""

from __future__ import annotations

import json
import shutil
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import jinja2
import pandas as pd

from correios_audit.catalog import DOCS, by_id
from correios_audit.normalize.taxonomy import LINES_BY_ID, ALL_LINES

ROOT = Path(__file__).resolve().parents[3]
PROCESSED = ROOT / "data" / "processed" / "canonical.parquet"
SITE_DIR = ROOT / "data" / "site"
TEMPLATES = Path(__file__).resolve().parent / "templates"
STATIC_SRC = Path(__file__).resolve().parent / "static"

PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"


# ---------------------------- regime transitions ----------------------------
#
# When a chart series spans a year where the underlying accounting regime,
# scope, or extraction quality changed, we draw a vertical reference line on
# the chart and surface a short rationale below it. This makes year-over-year
# jumps that aren't real economic movement (just a methodology change)
# visible to the reader instead of looking like a sudden trend break.

@dataclass(frozen=True)
class Transition:
    year: int
    short_label: str            # rendered alongside the vertical bar
    long_text: str              # rendered in the chart-notes block
    line_id_prefixes: tuple[str, ...]
    color: str = "rgba(220,80,80,0.55)"


REGIME_TRANSITIONS: tuple[Transition, ...] = (
    Transition(
        year=2010,
        short_label="BR-GAAP → IFRS",
        long_text=(
            "2010 — adoção plena do IFRS no Brasil (Lei 11.638/2007 + CPCs). "
            "Reclassifica linhas do BP (eliminação do Diferido, novo Realizável "
            "a Longo Prazo), introduz a Demonstração do Resultado Abrangente "
            "(DRA), altera tratamento de tributos diferidos e arrendamentos. "
            "Comparações de saldos entre 2009 e 2010 não são diretas."
        ),
        line_id_prefixes=("dre.", "bp.", "dfc.", "dva.", "dra."),
        color="rgba(220,80,80,0.55)",
    ),
    Transition(
        year=2019,
        short_label="IFRS 16 (leases)",
        long_text=(
            "2019 — adoção do IFRS 16/CPC 06(R2). Operações de arrendamento "
            "antes off-balance passam a ser reconhecidas como passivo de "
            "direito de uso e contrapartida em ativo imobilizado. O salto em "
            "imobilizado e em passivo neste ano é majoritariamente efeito "
            "contábil, não desembolso de caixa novo."
        ),
        line_id_prefixes=(
            "bp.passivo.circulante.arrendamento",
            "bp.passivo.nao_circulante.arrendamento",
            "bp.passivo.circulante.passivo_direito_uso",
            "bp.passivo.nao_circulante.passivo_direito_uso",
            "bp.ativo.nao_circulante.imobilizado.bens_direito_uso",
            "bp.ativo.nao_circulante.imobilizado",
            "bp.ativo.total",
            "bp.passivo.total",
            "bp.passivo.nao_circulante",
            "dfc.fin.arrendamento",
        ),
        color="rgba(80,150,220,0.55)",
    ),
    Transition(
        year=2020,
        short_label="Pandemia / e-commerce",
        long_text=(
            "2020–2021 — choque de demanda por encomendas durante a pandemia "
            "eleva a receita líquida e o resultado de forma única. Os lucros "
            "de 2020 (R$ 1,53 bi) e 2021 (R$ 2,28 bi) refletem esse ciclo "
            "extraordinário, não tendência estrutural — em 2022 o resultado "
            "volta a ser negativo."
        ),
        line_id_prefixes=("dre.receita_liquida", "dre.resultado_liquido",
                          "dre.lucro_bruto", "dre.resultado_operacional",
                          "dfc.op.recursos_liquidos"),
        color="rgba(120,180,80,0.45)",
    ),
)


# Per-statement coverage notes. Surfaced under tables that mix statements.
COVERAGE_NOTES: dict[str, str] = {
    "dre": (
        "Cobertura DRE: 2014 e 2018+ são completas; 2001–2013 e 2015–2017 "
        "têm extração parcial (layouts BR-GAAP em brochuras escaneadas, "
        "labels diferentes a cada ano). Linhas pré-2010 como reversão de JCP "
        "e PLR pré-tributos não têm equivalente IFRS direto."
    ),
    "dra": (
        "DRA (Resultado Abrangente) introduzida pelo CPC 26 em 2010 — "
        "antes disso essa demonstração não existia."
    ),
    "dfc": (
        "DFC obrigatória só a partir de 2008 (Lei 11.638/2007). Antes "
        "disso publicava-se a DOAR (Demonstração de Origens e Aplicações), "
        "que não é diretamente convertível para o formato indireto da DFC."
    ),
    "dva": (
        "DVA cobre 2006 em diante; anos OCR'd têm lacunas em sub-itens "
        "(7.x trabalho, 8.x governo). Os totais por categoria são confiáveis."
    ),
    "bp": (
        "BP cobre todo o período mas com profundidade desigual: 2008–2024 "
        "completo até a sub-categoria; 2001–2007 só níveis-cabeçalho (Total "
        "Ativo, Permanente, Disponível) por causa do OCR de brochuras."
    ),
}


def _applicable_transitions(line_ids: list[str]) -> list[Transition]:
    """Return transitions whose `line_id_prefixes` match any of the chart's
    series. Order preserved (year ascending)."""
    out: list[Transition] = []
    for t in REGIME_TRANSITIONS:
        if any(lid.startswith(p) for lid in line_ids for p in t.line_id_prefixes):
            out.append(t)
    return out


def _format_year_list(years: set[int]) -> str:
    """Render a set of years as compact ranges: {2002,2003,2005,2006,2007} →
    '2002–2003, 2005–2007'. Useful for surfacing coverage gaps."""
    if not years:
        return ""
    sorted_ys = sorted(years)
    runs: list[tuple[int, int]] = []
    a = sorted_ys[0]
    b = a
    for y in sorted_ys[1:]:
        if y == b + 1:
            b = y
        else:
            runs.append((a, b))
            a = b = y
    runs.append((a, b))
    return ", ".join(f"{a}" if a == b else f"{a}–{b}" for a, b in runs)


# ---------------------------- helpers ----------------------------------------

def format_num(v: float | None) -> str:
    if v is None or pd.isna(v):
        return "—"
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1e9:
        return f"{sign}{v/1e9:,.2f}".replace(",", ".") + " bi"
    if v >= 1e6:
        return f"{sign}{v/1e6:,.1f}".replace(",", ".") + " mi"
    return f"{sign}{v:,.0f}".replace(",", ".")


def format_num_simple(v: float | None) -> str:
    """Compact thousand-separated number, no abbreviation. Use in dense tables."""
    if v is None or pd.isna(v):
        return "—"
    sign = "-" if v < 0 else ""
    v = abs(v)
    s = f"{v:,.0f}".replace(",", ".")
    return f"{sign}{s}"


def format_num_or_dash(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return format_num(v)


def _depth(line_id: str) -> int:
    return line_id.count(".") - 1


def latest_value(df: pd.DataFrame, *, line_id: str, period_year: int,
                 period_kind: str = "fy", scope: str = "consolidado") -> float | None:
    """Returns the consolidated FY value if present, else falls back to the
    controlling-entity (Controladora) view."""
    base = df[(df.line_id == line_id) & (df.period_year == period_year)
              & (df.period_kind == period_kind)]
    sub = base[base.scope == scope] if "scope" in base.columns else base
    if sub.empty and scope == "consolidado" and "scope" in base.columns:
        sub = base[base.scope == "controladora"]
    if sub.empty:
        return None
    sub = sub.copy()
    sub["_pref"] = sub["doc_id"].str.contains("-fy-").astype(int)
    return float(sub.sort_values(["vintage_year", "_pref"]).iloc[-1]["value"])


def time_series(df: pd.DataFrame, line_id: str, period_kind: str = "fy",
                scope: str = "consolidado") -> dict[int, float]:
    base = df[(df.line_id == line_id) & (df.period_kind == period_kind)]
    if base.empty:
        return {}
    out: dict[int, float] = {}
    for py in sorted(base.period_year.unique()):
        v = latest_value(df, line_id=line_id, period_year=int(py),
                         period_kind=period_kind, scope=scope)
        if v is not None:
            out[int(py)] = v
    return out


# ---------------------------- charts -----------------------------------------

def _chart(line_ids: list[tuple[str, str]], title: str, df: pd.DataFrame, *,
           div_id: str, fmt: str = "real") -> dict:
    """Make a Plotly chart spec.

    fmt: 'real' (R$) or 'pct'.

    Side effects: computes a list of disclaimers covering (a) regime/method
    transitions that fall inside the chart's x-range, drawn as vertical
    reference bars on the chart, and (b) coverage gaps per series. The
    disclaimers are returned in `chart["disclaimers"]` for the template to
    render alongside the chart.
    """
    series = []
    series_years: dict[str, set[int]] = {}
    series_labels: dict[str, str] = {}
    all_years: set[int] = set()
    implausible: dict[str, set[int]] = {}
    for lid, label in line_ids:
        ts = time_series(df, lid)
        if not ts:
            continue
        # Drop values that violate the canonical sign convention. Pre-2010
        # OCR'd brochures sometimes emit a CPV-shaped (negative) value into
        # the receita-líquida column because of column misalignment; rather
        # than show "-R$ 5 bi receita" as if it were real, filter the
        # implausible point and surface the year in the chart notes.
        meta = LINES_BY_ID.get(lid)
        bad = set()
        if meta is not None:
            for y, v in list(ts.items()):
                if meta.sign == "+" and v < 0:
                    bad.add(y)
                elif meta.sign == "-" and v > 0:
                    bad.add(y)
        ts_kept = {y: v for y, v in ts.items() if y not in bad}
        if not ts_kept:
            continue
        xs = sorted(ts_kept)
        ys = [ts_kept[x] / 1e9 for x in xs]  # billions
        series.append({"type": "scatter", "mode": "lines+markers",
                       "name": label, "x": xs, "y": ys})
        series_years[lid] = set(xs)
        series_labels[lid] = label
        all_years |= set(xs)
        if bad:
            implausible[lid] = bad

    transitions = _applicable_transitions([lid for lid, _ in line_ids])
    shapes: list[dict] = []
    annotations: list[dict] = []
    if all_years:
        x_min, x_max = min(all_years), max(all_years)
        for t in transitions:
            if not (x_min <= t.year <= x_max):
                continue
            shapes.append({
                "type": "line",
                "x0": t.year, "x1": t.year,
                "y0": 0, "y1": 1, "yref": "paper",
                "line": {"color": t.color, "width": 2, "dash": "dash"},
            })
            annotations.append({
                "x": t.year, "y": 1.04, "yref": "paper",
                "text": t.short_label,
                "showarrow": False, "yanchor": "bottom",
                "font": {"size": 10, "color": t.color.replace("0.55", "0.9")
                                                      .replace("0.45", "0.9")},
                "bgcolor": "rgba(255,255,255,0.7)",
            })

    # Per-series coverage: first/last year + internal gaps within the chart's
    # x-range. Skip noise (single-year series): they give no useful gap info.
    coverage_lines: list[str] = []
    for lid, ys in series_years.items():
        if len(ys) < 2:
            continue
        a, b = min(ys), max(ys)
        full = set(range(a, b + 1))
        gaps = full - ys
        if gaps:
            coverage_lines.append(
                f"{series_labels[lid]}: {a}–{b} com lacuna em "
                f"{_format_year_list(gaps)}."
            )
        else:
            coverage_lines.append(f"{series_labels[lid]}: {a}–{b} (contínuo).")

    disclaimers = [t.long_text for t in transitions]
    if coverage_lines:
        disclaimers.append("Cobertura por série: " + " ".join(coverage_lines))
    if implausible:
        bad_lines = []
        for lid, ys in implausible.items():
            bad_lines.append(
                f"{series_labels[lid]} (anos {_format_year_list(ys)})"
            )
        disclaimers.append(
            "Pontos ocultados por violarem a convenção de sinal canônica "
            "(provável erro de OCR/desalinhamento de coluna em brochura "
            "escaneada): " + "; ".join(bad_lines)
            + ". Os valores brutos seguem disponíveis na tabela e na página "
            "do documento de origem."
        )

    return {
        "id": div_id,
        "title": title,
        "data": json.dumps(series, ensure_ascii=False),
        "layout": json.dumps({
            "title": title,
            "xaxis": {"title": ""},
            "yaxis": {"title": "R$ bilhões"},
            "margin": {"t": 60, "b": 40, "l": 60, "r": 20},
            "hovermode": "x unified",
            "shapes": shapes,
            "annotations": annotations,
        }, ensure_ascii=False),
        "disclaimers": disclaimers,
    }


# ---------------------------- pages ------------------------------------------

def _build_year_statement(df: pd.DataFrame, *, period_year: int, statement: str,
                          title: str, columns: list[int],
                          subtitle: str | None = None,
                          ) -> dict | None:
    sub = df[(df.statement == statement) & (df.period_year.isin(columns))
             & (df.period_kind == "fy")]
    if "scope" in df.columns:
        # Show consolidado where available; falls back to controladora when the
        # doc only carries that view (handled by latest_value below).
        sub = sub[sub.scope.isin(["consolidado", "controladora"])]
    if sub.empty:
        return None
    # Order by taxonomy declaration to keep statement structure.
    order = {ln.line_id: i for i, ln in enumerate(ALL_LINES)}
    line_ids = sorted(sub.line_id.unique(), key=lambda x: order.get(x, 1e9))
    rows = []
    for lid in line_ids:
        meta = LINES_BY_ID.get(lid)
        if meta is None:
            continue
        vals = []
        for col_year in columns:
            v = latest_value(df, line_id=lid, period_year=col_year)
            vals.append(v)
        if all(v is None for v in vals):
            continue
        rows.append({
            "label": meta.label_pt,
            "values": vals,
            "is_total": meta.is_total,
            "depth": _depth(lid),
        })
    return {
        "title": title,
        "subtitle": subtitle,
        "columns": [str(c) for c in columns],
        "rows": rows,
    }


def _build_timeline_table(df: pd.DataFrame, line_ids: list[tuple[str, str]],
                          years: list[int]) -> dict:
    """Build a (rows × years) table for the index timeline."""
    rows = []
    for lid, label in line_ids:
        ts = time_series(df, lid)
        if not ts:
            continue
        rows.append({
            "label": label,
            "line_id": lid,
            "values": [ts.get(y) for y in years],
        })
    return {"years": years, "rows": rows}


def render_index(env: jinja2.Environment, df: pd.DataFrame, docs_status: list[dict]) -> str:
    fy = df[df.period_kind == "fy"]
    years = sorted(fy.period_year.dropna().unique().astype(int))
    latest = max(years) if years else None
    if latest is None:
        return env.get_template("index.html").render(
            title="Auditoria Correios",
            year_min=None, year_max=None, n_docs=len(docs_status),
            kpis=[], charts=[], years=[], docs=docs_status, root="",
            timeline=None,
            build_date=datetime.now(UTC).strftime("%Y-%m-%d"),
        )

    def kpi(label, line_id, py=latest, tone_neg=True):
        v = latest_value(df, line_id=line_id, period_year=py)
        if v is None:
            return None
        tone = ""
        if tone_neg and v < 0:
            tone = "neg"
        elif v >= 0 and not tone_neg:
            tone = "pos"
        return {"label": label, "formatted": format_num(v),
                "period": str(py), "tone": tone}

    raw_kpis = [
        kpi("Receita líquida", "dre.receita_liquida"),
        kpi("Resultado líquido", "dre.resultado_liquido"),
        kpi("Patrimônio líquido", "bp.patrimonio_liquido"),
        kpi("Caixa e equivalentes", "bp.ativo.circulante.caixa_equivalentes"),
        kpi("Total ativo", "bp.ativo.total"),
        kpi("Postalis (LP)", "bp.passivo.nao_circulante.beneficios_pos_emprego"),
    ]
    kpis = [k for k in raw_kpis if k]

    charts = [
        _chart([("dre.receita_liquida", "Receita líquida"),
                ("dre.lucro_bruto", "Lucro bruto"),
                ("dre.resultado_liquido", "Resultado líquido")],
               "P&L: receita, lucro bruto, resultado líquido (R$ bi)",
               df, div_id="chart-pnl"),
        _chart([("bp.ativo.total", "Total ativo"),
                ("bp.passivo.nao_circulante.beneficios_pos_emprego",
                 "Benefícios pós-emprego (LP)"),
                ("bp.patrimonio_liquido", "Patrimônio líquido")],
               "Balanço: ativos, pensão e equity (R$ bi)",
               df, div_id="chart-bs"),
        _chart([("bp.ativo.circulante.caixa_equivalentes", "Caixa e equivalentes"),
                ("bp.ativo.circulante.aplicacoes", "Aplicações financeiras (CP)")],
               "Liquidez (R$ bi)", df, div_id="chart-liquidity"),
        _chart([("dre.despesas_administrativas",
                 "Despesas administrativas (negativo)"),
                ("dre.despesas_vendas", "Despesas com vendas (negativo)"),
                ("dre.despesas_financeiras", "Despesas financeiras (negativo)")],
               "Estrutura de despesas (R$ bi)", df, div_id="chart-expenses"),
    ]

    # Multi-decade key-figures table.
    timeline_rows = [
        ("dre.receita_liquida", "Receita líquida"),
        ("dre.cpv", "Custo dos serviços (CPV)"),
        ("dre.lucro_bruto", "Lucro bruto"),
        ("dre.despesas_administrativas", "Despesas administrativas"),
        ("dre.despesas_vendas", "Despesas com vendas"),
        ("dre.outras_receitas_operacionais", "Outras receitas operacionais"),
        ("dre.outras_despesas_operacionais", "Outras despesas operacionais"),
        ("dre.resultado_operacional", "Resultado operacional"),
        ("dre.receitas_financeiras", "Receitas financeiras"),
        ("dre.despesas_financeiras", "Despesas financeiras"),
        ("dre.resultado_financeiro", "Resultado financeiro"),
        ("dre.resultado_antes_ir", "Resultado antes do IR"),
        ("dre.tributos_sobre_lucro", "Tributos sobre o lucro"),
        ("dre.resultado_liquido", "Resultado líquido"),
        ("bp.ativo.total", "Total ativo"),
        ("bp.ativo.circulante.caixa_equivalentes", "Caixa e equivalentes"),
        ("bp.ativo.nao_circulante.imobilizado", "Imobilizado"),
        ("bp.passivo.total", "Total passivo + PL"),
        ("bp.passivo.nao_circulante.beneficios_pos_emprego",
         "Benefícios pós-emprego (LP)"),
        ("bp.passivo.nao_circulante.processos_judiciais", "Processos judiciais (LP)"),
        ("bp.patrimonio_liquido", "Patrimônio líquido"),
        ("bp.patrimonio_liquido.capital", "Capital social"),
        ("bp.patrimonio_liquido.lucros_prejuizos_acumulados",
         "Lucros / prejuízos acumulados"),
        ("dfc.op.recursos_liquidos", "Caixa operacional"),
        ("dfc.inv.imobilizado_adicoes", "Capex (imobilizado)"),
        ("dfc.caixa_fim", "Caixa no fim do período"),
    ]
    timeline = _build_timeline_table(df, timeline_rows, years)
    transition_years = _transition_years_in_range(years)
    coverage_notes = list(COVERAGE_NOTES.values())

    return env.get_template("index.html").render(
        title="Auditoria Correios",
        year_min=min(years), year_max=max(years), n_docs=len(docs_status),
        kpis=kpis, charts=charts, years=years, docs=docs_status, root="",
        timeline=timeline,
        transition_years=transition_years,
        coverage_notes=coverage_notes,
        build_date=datetime.now(UTC).strftime("%Y-%m-%d"),
    )


def render_year(env: jinja2.Environment, df: pd.DataFrame, year: int) -> str:
    sub = df[(df.period_year == year) & (df.period_kind == "fy")]
    if sub.empty:
        return ""
    doc_id = sub.doc_id.iloc[0]
    # Show a 5-year history per statement: year, year-1, year-2, year-3, year-4.
    # We collapse to columns we actually have data for.
    history_years = list(range(year - 4, year + 1))
    statements = []
    for stmt, title in [("bp", "Balanço Patrimonial"),
                        ("dre", "Demonstração do Resultado"),
                        ("dra", "Resultado Abrangente"),
                        ("dfc", "Fluxos de Caixa"),
                        ("dva", "Valor Adicionado")]:
        # Filter to columns where any data exists.
        all_data = df[(df.statement == stmt) & (df.period_year.isin(history_years))
                      & (df.period_kind == "fy")]
        cols = sorted(set(all_data.period_year.astype(int).tolist()))
        if not cols:
            continue
        s = _build_year_statement(df, period_year=year, statement=stmt, title=title,
                                  columns=cols)
        if s is None:
            continue
        statements.append(s)

    # Quarterly snapshot for this year, if any.
    qtr_df = df[(df.period_year == year) & (df.period_kind != "fy")
                & (df.statement == "bp")]
    qtr_table = None
    if not qtr_df.empty:
        kinds = sorted(qtr_df.period_kind.unique())
        order = {ln.line_id: i for i, ln in enumerate(ALL_LINES)}
        line_ids = sorted(qtr_df.line_id.unique(), key=lambda x: order.get(x, 1e9))
        rows = []
        for lid in line_ids:
            meta = LINES_BY_ID.get(lid)
            if meta is None:
                continue
            vals = []
            for k in kinds:
                v = latest_value(df, line_id=lid, period_year=year, period_kind=k)
                vals.append(v)
            if all(v is None for v in vals):
                continue
            rows.append({
                "label": meta.label_pt,
                "values": vals,
                "is_total": meta.is_total,
                "depth": _depth(lid),
            })
        if rows:
            qtr_table = {
                "title": "Snapshots intra-anuais (BP)",
                "subtitle": f"Saldos em {year} por trimestre",
                "columns": [k.upper() for k in kinds],
                "rows": rows,
            }

    summary_parts = []
    rl = latest_value(df, line_id="dre.receita_liquida", period_year=year)
    rn = latest_value(df, line_id="dre.resultado_liquido", period_year=year)
    pl = latest_value(df, line_id="bp.patrimonio_liquido", period_year=year)
    if rl is not None:
        summary_parts.append(f"Receita líquida {format_num(rl)}")
    if rn is not None:
        summary_parts.append(f"resultado líquido {format_num(rn)}")
    if pl is not None:
        summary_parts.append(f"PL {format_num(pl)}")
    summary = "; ".join(summary_parts) + "." if summary_parts else "Dados parciais."

    # Per-year inline charts (5-year context).
    charts = [
        _chart([("dre.receita_liquida", "Receita líquida"),
                ("dre.resultado_liquido", "Resultado líquido")],
               f"Trajetória até {year} (R$ bi)",
               df, div_id="chart-pnl-trend"),
    ]
    # Per-statement coverage notes for this year's tables.
    statements_in_page = [s["title"].split()[0].lower() for s in statements]
    statement_keys = []
    for stmt in statements:
        ttl = stmt["title"].lower()
        if "balanço" in ttl:
            statement_keys.append("bp")
        elif "resultado abrangente" in ttl:
            statement_keys.append("dra")
        elif "resultado" in ttl:
            statement_keys.append("dre")
        elif "fluxo" in ttl:
            statement_keys.append("dfc")
        elif "valor adicionado" in ttl:
            statement_keys.append("dva")
    coverage_notes = [COVERAGE_NOTES[k] for k in statement_keys
                      if k in COVERAGE_NOTES]
    return env.get_template("year.html").render(
        title=str(year), year=year, doc_id=doc_id, summary=summary,
        statements=statements, qtr_table=qtr_table, charts=charts, root="../",
        coverage_notes=coverage_notes,
        build_date=datetime.now(UTC).strftime("%Y-%m-%d"),
    )


def render_lens(env: jinja2.Environment, df: pd.DataFrame, *,
                lens: str, title: str, description: str,
                line_ids: list[str], chart_groups: list[tuple[str, str, list[tuple[str, str]]]]) -> str:
    years = sorted(df.period_year.dropna().unique().astype(int))
    rows = []
    order = {ln.line_id: i for i, ln in enumerate(ALL_LINES)}
    statements_seen: set[str] = set()
    for lid in sorted(line_ids, key=lambda x: order.get(x, 1e9)):
        meta = LINES_BY_ID.get(lid)
        if meta is None:
            continue
        ts = time_series(df, lid)
        if not ts:
            continue
        statements_seen.add(meta.statement)
        first_year = min(ts) if ts else None
        last_year = max(ts) if ts else None
        rows.append({
            "label": meta.label_pt,
            "is_total": meta.is_total,
            "depth": _depth(lid),
            "values": [ts.get(y) for y in years],
            "first_year": first_year,
            "last_year": last_year,
        })
    charts = [_chart(group, ttl, df, div_id=cid)
              for cid, ttl, group in chart_groups]
    # Coverage notes: one per statement appearing in this lens.
    coverage_notes = [COVERAGE_NOTES[st] for st in sorted(statements_seen)
                      if st in COVERAGE_NOTES]
    transition_years = _transition_years_in_range(years)
    return env.get_template("lens.html").render(
        title=title, lens_title=title, lens_description=description,
        years=years, rows=rows, charts=charts, root="../",
        coverage_notes=coverage_notes,
        transition_years=transition_years,
        build_date=datetime.now(UTC).strftime("%Y-%m-%d"),
    )


def _transition_years_in_range(years: list[int]) -> list[dict]:
    """Return [{year, label, long_text}] for regime transitions whose year
    falls inside `years`. Used by table templates to draw a column-border
    marker at the transition year."""
    if not years:
        return []
    a, b = min(years), max(years)
    out = []
    for t in REGIME_TRANSITIONS:
        if a <= t.year <= b:
            out.append({"year": t.year, "label": t.short_label,
                        "long_text": t.long_text})
    return out


def render_ratios(env: jinja2.Environment, df: pd.DataFrame) -> str:
    """Compute derived ratios per year and render them with charts."""
    fy = df[df.period_kind == "fy"]
    years = sorted(fy.period_year.dropna().unique().astype(int))

    def lv(lid, y):
        return latest_value(df, line_id=lid, period_year=y)

    rows: list[dict] = []
    for label, fn, fmt in [
        ("Margem bruta",
         lambda y: (lv("dre.lucro_bruto", y), lv("dre.receita_liquida", y)),
         "pct"),
        ("Margem operacional",
         lambda y: (lv("dre.resultado_operacional", y), lv("dre.receita_liquida", y)),
         "pct"),
        ("Margem líquida",
         lambda y: (lv("dre.resultado_liquido", y), lv("dre.receita_liquida", y)),
         "pct"),
        ("Liquidez corrente (Ativo CP / Passivo CP)",
         lambda y: (lv("bp.ativo.circulante", y), lv("bp.passivo.circulante", y)),
         "ratio"),
        ("Liquidez imediata (Caixa / Passivo CP)",
         lambda y: (lv("bp.ativo.circulante.caixa_equivalentes", y),
                    lv("bp.passivo.circulante", y)),
         "ratio"),
        ("Postalis / PL",
         lambda y: (lv("bp.passivo.nao_circulante.beneficios_pos_emprego", y),
                    lv("bp.patrimonio_liquido", y)),
         "ratio"),
        ("Crescimento da receita YoY",
         lambda y: (lv("dre.receita_liquida", y), lv("dre.receita_liquida", y - 1)),
         "growth"),
    ]:
        values = []
        for y in years:
            n, d = fn(y)
            if n is None or d is None or d == 0:
                values.append(None)
                continue
            if fmt == "pct":
                values.append(n / d * 100)
            elif fmt == "growth":
                values.append((n / d - 1) * 100)
            else:
                values.append(n / d)
        rows.append({"label": label, "values": values, "fmt": fmt})

    return env.get_template("ratios.html").render(
        title="Indicadores",
        years=years,
        rows=rows,
        root="../",
        transition_years=_transition_years_in_range(years),
        coverage_notes=[COVERAGE_NOTES["dre"], COVERAGE_NOTES["bp"]],
        build_date=datetime.now(UTC).strftime("%Y-%m-%d"),
    )


def render_doc(env: jinja2.Environment, df: pd.DataFrame, doc_id: str) -> str:
    sub = df[df.doc_id == doc_id].sort_values(["statement", "page", "line_id"])
    rows = []
    for _, r in sub.iterrows():
        rows.append({
            "statement": r["statement"],
            "line_id": r["line_id"],
            "label_raw": r["label_raw"],
            "period_label": r["period_label"],
            "value": float(r["value"]),
            "page": int(r["page"]),
            "note_ref": r.get("note_ref"),
        })
    doc = by_id(doc_id)
    kind_label = {"df": "Demonstração financeira",
                  "audit": "Relatório do auditor independente",
                  "cf": "Parecer do Conselho Fiscal"}[doc.kind]
    return env.get_template("doc.html").render(
        title=doc_id, doc_id=doc_id, year=doc.year, period=doc.period,
        url=doc.url, rows=rows, kind_label=kind_label, root="../",
        build_date=datetime.now(UTC).strftime("%Y-%m-%d"),
    )


def render_years_table(env: jinja2.Environment, df: pd.DataFrame) -> str:
    years = sorted(df.period_year.dropna().unique().astype(int))
    rows = []
    for y in years:
        rows.append({
            "year": y,
            "receita": latest_value(df, line_id="dre.receita_liquida", period_year=y),
            "resultado": latest_value(df, line_id="dre.resultado_liquido", period_year=y),
            "pl": latest_value(df, line_id="bp.patrimonio_liquido", period_year=y),
            "caixa": latest_value(df, line_id="bp.ativo.circulante.caixa_equivalentes",
                                  period_year=y),
            "postalis": latest_value(
                df, line_id="bp.passivo.nao_circulante.beneficios_pos_emprego",
                period_year=y),
        })
    return env.get_template("years.html").render(
        title="Anos cobertos", rows=rows, root="",
        build_date=datetime.now(UTC).strftime("%Y-%m-%d"),
    )


# ---------------------------- main -------------------------------------------

def _ensure_plotly() -> Path:
    static_out = SITE_DIR / "static"
    static_out.mkdir(parents=True, exist_ok=True)
    plotly_path = static_out / "plotly.min.js"
    if not plotly_path.exists():
        print(f"downloading plotly.min.js from {PLOTLY_CDN}")
        try:
            urllib.request.urlretrieve(PLOTLY_CDN, plotly_path)
        except Exception as exc:
            # Fallback stub: charts won't render but pages will load.
            plotly_path.write_text(f"/* plotly download failed: {exc} */\n")
    return plotly_path


def main() -> int:
    if not PROCESSED.exists():
        print(f"missing {PROCESSED}; run `make normalize` first")
        return 1
    df = pd.read_parquet(PROCESSED)
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    # Copy static
    out_static = SITE_DIR / "static"
    out_static.mkdir(parents=True, exist_ok=True)
    for f in STATIC_SRC.iterdir():
        shutil.copy2(f, out_static / f.name)
    _ensure_plotly()

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    env.filters["format_num"] = format_num
    env.filters["format_num_or_dash"] = format_num_or_dash
    env.filters["format_num_simple"] = format_num_simple

    docs_status: list[dict] = []
    for d in DOCS:
        n_rows = int(df[df.doc_id == d.doc_id].shape[0])
        if n_rows == 0:
            continue
        docs_status.append({"doc_id": d.doc_id, "n_rows": n_rows, "url": d.url})

    # index
    (SITE_DIR / "index.html").write_text(render_index(env, df, docs_status))
    # years table
    (SITE_DIR / "years.html").write_text(render_years_table(env, df))
    # per-year
    year_dir = SITE_DIR / "year"
    year_dir.mkdir(parents=True, exist_ok=True)
    for y in sorted(df.period_year.dropna().unique().astype(int)):
        html = render_year(env, df, int(y))
        if html:
            (year_dir / f"{y}.html").write_text(html)
    # per-doc
    doc_dir = SITE_DIR / "doc"
    doc_dir.mkdir(parents=True, exist_ok=True)
    for d in docs_status:
        (doc_dir / f"{d['doc_id']}.html").write_text(render_doc(env, df, d["doc_id"]))
    # lens pages
    lens_dir = SITE_DIR / "lens"
    lens_dir.mkdir(parents=True, exist_ok=True)
    (lens_dir / "profitability.html").write_text(render_lens(
        env, df, lens="profitability",
        title="Lucratividade & Operações",
        description="Receita líquida, custos, despesas operacionais, resultado "
                    "operacional e líquido. A análise mostra a estrutura completa "
                    "do P&L (DRE) e do valor adicionado (DVA).",
        line_ids=[ln.line_id for ln in ALL_LINES if ln.statement in ("dre", "dra", "dva")],
        chart_groups=[
            ("c-receita", "Receita líquida vs custos (R$ bi)",
             [("dre.receita_liquida", "Receita líquida"),
              ("dre.cpv", "Custo dos serviços (CPV)")]),
            ("c-margem", "Resultado bruto, operacional e líquido (R$ bi)",
             [("dre.lucro_bruto", "Lucro bruto"),
              ("dre.resultado_operacional", "Resultado operacional"),
              ("dre.resultado_liquido", "Resultado líquido")]),
            ("c-financeiro", "Resultado financeiro (R$ bi)",
             [("dre.receitas_financeiras", "Receitas financeiras"),
              ("dre.despesas_financeiras", "Despesas financeiras"),
              ("dre.resultado_financeiro", "Resultado financeiro líquido")]),
            ("c-dva", "Distribuição do valor adicionado (R$ bi)",
             [("dva.dist.trabalho", "Trabalho (pessoal)"),
              ("dva.dist.governo", "Governo (impostos)"),
              ("dva.dist.terceiros", "Capital de terceiros (juros)"),
              ("dva.dist.acionistas", "Acionistas (lucro retido)")]),
        ]))
    (lens_dir / "balance_sheet.html").write_text(render_lens(
        env, df, lens="balance_sheet",
        title="Balanço Patrimonial",
        description="Ativos, passivos e patrimônio líquido. A obrigação Postalis "
                    "(benefícios pós-emprego) é a maior linha do passivo não "
                    "circulante e o principal fator do PL negativo.",
        line_ids=[ln.line_id for ln in ALL_LINES if ln.statement == "bp"],
        chart_groups=[
            ("c-bp-tot", "Composição do ativo (R$ bi)",
             [("bp.ativo.total", "Total ativo"),
              ("bp.ativo.circulante", "Ativo circulante"),
              ("bp.ativo.nao_circulante.imobilizado", "Imobilizado")]),
            ("c-bp-pl", "Patrimônio líquido (R$ bi)",
             [("bp.patrimonio_liquido", "Patrimônio líquido total"),
              ("bp.patrimonio_liquido.capital", "Capital social"),
              ("bp.patrimonio_liquido.lucros_prejuizos_acumulados",
               "Lucros / prejuízos acumulados"),
              ("bp.patrimonio_liquido.ora", "Outros resultados abrangentes")]),
            ("c-bp-pension", "Benefícios pós-emprego — Postalis + saúde (R$ bi)",
             [("bp.passivo.nao_circulante.beneficios_pos_emprego",
               "Obrigação atuarial (LP)")]),
            ("c-bp-current", "Liquidez (R$ bi)",
             [("bp.ativo.circulante.caixa_equivalentes", "Caixa e equivalentes"),
              ("bp.ativo.circulante.aplicacoes", "Aplicações financeiras (CP)"),
              ("bp.passivo.circulante.fornecedores", "Fornecedores"),
              ("bp.passivo.circulante.beneficios_a_empregados",
               "Benefícios a empregados (CP)")]),
        ]))
    (lens_dir / "cash_flow.html").write_text(render_lens(
        env, df, lens="cash_flow",
        title="Fluxo de Caixa",
        description="DFC pelo método indireto: caixa operacional, capex e "
                    "atividades de financiamento. Mostra como a empresa gera (ou "
                    "consome) caixa e financia investimentos.",
        line_ids=[ln.line_id for ln in ALL_LINES if ln.statement == "dfc"],
        chart_groups=[
            ("c-dfc-op", "Caixa das atividades operacionais (R$ bi)",
             [("dfc.op.recursos_liquidos", "Caixa operacional líquido"),
              ("dfc.op.itens_nao_caixa.depreciacao_amortizacao",
               "Depreciação + amortização")]),
            ("c-dfc-cap", "Atividades de investimento (R$ bi)",
             [("dfc.inv.imobilizado_adicoes", "Adições imobilizado (capex)"),
              ("dfc.inv.intangivel_adicoes", "Adições intangível"),
              ("dfc.inv.recursos_liquidos", "Caixa de investimento (líquido)")]),
            ("c-dfc-fin", "Financiamento (R$ bi)",
             [("dfc.fin.captacoes", "Captações de empréstimos"),
              ("dfc.fin.amortizacoes", "Amortizações"),
              ("dfc.fin.arrendamento", "Pagamentos de arrendamento (IFRS 16)")]),
            ("c-dfc-cash", "Saldos de caixa (R$ bi)",
             [("dfc.caixa_inicio", "Saldo inicial"),
              ("dfc.caixa_fim", "Saldo final")]),
        ]))
    (lens_dir / "governance.html").write_text(render_lens(
        env, df, lens="governance",
        title="Governança & Contingências",
        description="Provisões para processos judiciais (CP+LP), arrendamentos "
                    "(IFRS 16), instrumentos derivativos e tributos diferidos.",
        line_ids=[
            "bp.passivo.circulante.processos_judiciais",
            "bp.passivo.nao_circulante.processos_judiciais",
            "bp.passivo.circulante.precatorios",
            "bp.passivo.nao_circulante.precatorios",
            "bp.passivo.circulante.arrendamento",
            "bp.passivo.nao_circulante.arrendamento",
            "bp.passivo.circulante.derivativos",
            "bp.ativo.nao_circulante.realizavel_longo_prazo.tributos_diferidos",
            "bp.passivo.nao_circulante.tributos_diferidos",
            "bp.passivo.nao_circulante.beneficios_pos_emprego",
        ],
        chart_groups=[
            ("c-gov-cont", "Provisões para processos judiciais (R$ bi)",
             [("bp.passivo.nao_circulante.processos_judiciais", "Provisão LP"),
              ("bp.passivo.circulante.processos_judiciais", "Provisão CP")]),
            ("c-gov-arr", "Arrendamentos (IFRS 16) (R$ bi)",
             [("bp.passivo.nao_circulante.arrendamento", "Passivo arrendamento LP"),
              ("bp.passivo.circulante.arrendamento", "Passivo arrendamento CP")]),
            ("c-gov-tax", "Tributos diferidos (R$ bi)",
             [("bp.ativo.nao_circulante.realizavel_longo_prazo.tributos_diferidos",
               "Ativo tributário diferido"),
              ("bp.passivo.nao_circulante.tributos_diferidos",
               "Passivo tributário diferido")]),
        ]))

    # Ratios lens — derived metrics, not raw line items.
    (lens_dir / "ratios.html").write_text(render_ratios(env, df))

    print(f"site rendered to {SITE_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
