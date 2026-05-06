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
    """Side-by-side BPs put ATIVO and PASSIVO on the same line, but that line
    is often *above* the date-header line by a few rows (brochure-era 2001-2009
    use one row for `ATIVO PASSIVO` and the next for `2001 2000`). Search the
    header zone a few lines back, not just the date row.

    The two labels must be visually separated (>50 pt) — a single-side title
    like `BALANÇO PATRIMONIAL — ATIVO E PASSIVO` would also match find_word
    for both names but the words sit adjacent.
    """
    look_back = 8
    start = max(0, header_idx - look_back)
    end = min(len(page["lines"]), header_end + 2)
    for i in range(start, end):
        line = page["lines"][i]
        ativo = find_word(line, "ATIVO")
        passivo = find_word(line, "PASSIVO")
        if ativo is not None and passivo is not None:
            if abs(ativo.x_center - passivo.x_center) > 50:
                return passivo.x0 - 2.0
    return None


def _detect_single_side(page: dict) -> str | None:
    """Single-side BP layouts (older quarterlies, occasional brochures): the
    page title carries 'BALANÇO PATRIMONIAL - ATIVO' or '- PASSIVO E
    PATRIMÔNIO LÍQUIDO'.

    Disambiguation rules:
    - Inspect each of the first 8 lines individually (not concatenated text),
      so a brochure title 'ATIVO E PASSIVO' on one line is treated as a
      side-by-side hint, not a passivo single-side page.
    - If a line contains BOTH 'ATIVO' and 'PASSIVO', it's a side-by-side
      header — return None so parse_bp_page falls into the split path.
    - If we see only 'PASSIVO' (and 'PATRIMÔNIO'/'LÍQUIDO'-like terms),
      single-side passivo.
    - If we see only 'ATIVO', single-side ativo.
    - Mixed across separate lines: ambiguous; return None and let the
      apply.py BP-side walker infer per row.
    """
    saw_ativo = False
    saw_passivo = False
    for line in page["lines"][:8]:
        text = " ".join(w[2] for w in line["words"]).upper()
        line_ativo = "ATIVO" in text
        line_passivo = (
            "PASSIVO" in text
            or "PATRIMÔNIO LÍQUIDO" in text
            or "PATRIMONIO LIQUIDO" in text
        )
        if line_ativo and line_passivo:
            return None
        saw_ativo |= line_ativo
        saw_passivo |= line_passivo
    if saw_ativo and saw_passivo:
        return None
    if saw_passivo:
        return "passivo"
    if saw_ativo:
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
