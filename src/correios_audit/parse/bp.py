"""
BP (Balanço Patrimonial) parser.

The BP page lays out ATIVO and PASSIVO side-by-side. To split the page, we
find the literal word "PASSIVO" in the header and use its x0 as the divider.
The label "Fornecedores" of the passivo column starts at the same x as
"PASSIVO", so splitting on the date-column midpoint loses every passivo label.
"""

from __future__ import annotations

from correios_audit.parse.common import (
    detect_period_columns,
    detect_period_columns_in_zone,
    find_word,
)
from correios_audit.parse.statement import StatementParse, parse_simple_statement


def _find_split_x(page: dict, header_idx: int, header_end: int) -> float | None:
    """Side-by-side BPs (modern annuals) have ATIVO and PASSIVO on the SAME
    header line. We only split in that case. Single-side pages (older
    annuals, all quarterlies) carry "ATIVO" or "PASSIVO" only in the page
    title — we must not split those, otherwise the only "PASSIVO" word on
    the page is the title and the split_x ends up at the title's x position."""
    for i in range(header_idx, header_end + 1):
        line = page["lines"][i]
        ativo = find_word(line, "ATIVO")
        passivo = find_word(line, "PASSIVO")
        if ativo is not None and passivo is not None:
            return passivo.x0 - 2.0
    # No ambiguity: side-by-side requires both labels co-located.
    return None


def _detect_single_side(page: dict) -> str | None:
    """For single-side BP layouts (older quarterlies), the page title carries
    'BALANÇO PATRIMONIAL - ATIVO' or '- PASSIVO'. Older annuals just have
    'ATIVO' or 'PASSIVO E PATRIMÔNIO LÍQUIDO' as a column header label."""
    head_text = " ".join(
        " ".join(w[2] for w in line["words"])
        for line in page["lines"][:8]
    ).upper()
    if "PASSIVO" in head_text or "PATRIMÔNIO LÍQUIDO" in head_text or "PATRIMONIO LIQUIDO" in head_text:
        return "passivo"
    if "ATIVO" in head_text:
        return "ativo"
    return None


def parse_bp_page(page: dict) -> tuple[StatementParse | None, StatementParse | None]:
    """Return (ativo, passivo) parses, or (None, None) if no header found.

    Skips body-text mentions of years (e.g., "EXERCÍCIO FINANCEIRO — 2009"
    has 1 date but isn't the BP header). The real header has at least 2
    period columns (current + prior).
    """
    lines = page["lines"]
    header_start = None
    header_end = None
    for i, ln in enumerate(lines):
        if not detect_period_columns(ln):
            continue
        end, cols = detect_period_columns_in_zone(lines, i)
        if len(cols) >= 2:
            header_start = i
            header_end = end
            break
    if header_start is None:
        return None, None
    split_x = _find_split_x(page, header_start, header_end)
    if split_x is None:
        # Single-side BP: parse the whole page as one statement and infer side
        # from the page title.
        single = parse_simple_statement(page, "bp")
        inferred_side = _detect_single_side(page)
        if single:
            for r in single.rows:
                r.side = inferred_side
        return single, None

    def _filter(line: dict, *, ativo: bool) -> dict:
        words = []
        for w in line["words"]:
            on_ativo_side = w[0] < split_x
            if ativo == on_ativo_side:
                words.append(w)
        return {"y": line["y"], "words": words}

    ativo_page = {
        "page": page["page"],
        "lines": [_filter(ln, ativo=True) for ln in lines],
    }
    passivo_page = {
        "page": page["page"],
        "lines": [_filter(ln, ativo=False) for ln in lines],
    }
    a = parse_simple_statement(ativo_page, "bp")
    p = parse_simple_statement(passivo_page, "bp")
    if a:
        for r in a.rows:
            r.side = "ativo"
    if p:
        for r in p.rows:
            r.side = "passivo"
    return a, p
