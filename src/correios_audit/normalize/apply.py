"""
Apply YAML mappings to parsed rows, producing canonical (doc_id, vintage,
statement, line_id, period_year, value) rows.

Unmapped labels (above a tiny noise threshold) are written to
data/interim/unmapped/<doc_id>.csv so the taxonomy/mapping can be extended.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from correios_audit.catalog import by_id
from correios_audit.normalize.taxonomy import LINES_BY_ID
from correios_audit.parse.common import normalize_label

ROOT = Path(__file__).resolve().parents[3]
PARSED_DIR = ROOT / "data" / "interim" / "parsed"
UNMAPPED_DIR = ROOT / "data" / "interim" / "unmapped"
PROCESSED_DIR = ROOT / "data" / "processed"
MAPPINGS_DIR = Path(__file__).resolve().parent / "mappings"
MANUAL_DIR = ROOT / "data" / "manual_overrides"


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern
    line_id: str
    side: str | None
    where: str | None
    statement: str


def _load_manual_overrides() -> list[dict]:
    """Read `data/manual_overrides/*.yaml`. Each file represents a single
    source (typically the auditor's opinion or a published figure that the
    parser can't reach because the source PDF is a brochure-style layout).

    YAML format:
        source: "Relatório do Auditor Independente 2008 (descrição)"
        sha256: "<hash of the source PDF, optional but recommended>"
        page: 3                          # source page in PDF
        url: "https://..."               # source URL
        vintage_year: 2008               # for restatement-vintage tracking
        currency_unit: thousands         # 'thousands' or 'units' (millions = 1000 thousands)
        rows:
          - line_id: dre.receita_liquida
            period_year: 2008
            period_kind: fy
            value: 7494100               # interpreted in `currency_unit`
            label_raw: "Receita líquida (auditor)"  # optional

    Values are stored multiplied by 1000 (consistent with parser output).
    `doc_id` becomes `manual:<filename>`.
    """
    if not MANUAL_DIR.exists():
        return []
    out: list[dict] = []
    valid_line_ids = set(LINES_BY_ID)
    for path in sorted(MANUAL_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if not data:
            continue
        unit = (data.get("currency_unit") or "thousands").lower()
        scale = 1000.0 if unit == "thousands" else 1_000_000.0 if unit == "millions" else 1.0
        vintage = data.get("vintage_year")
        for r in data.get("rows", []):
            lid = r["line_id"]
            if lid not in valid_line_ids:
                print(f"WARN manual override {path.name}: unknown line_id {lid}",
                      file=sys.stderr)
                continue
            stmt = LINES_BY_ID[lid].statement
            out.append({
                "doc_id": f"manual:{path.stem}",
                "vintage_year": int(r.get("vintage_year") or vintage or 0),
                "statement": stmt,
                "side": r.get("side"),
                "line_id": lid,
                "label_raw": r.get("label_raw") or LINES_BY_ID[lid].label_pt,
                "note_ref": r.get("note_ref"),
                "period_year": int(r["period_year"]),
                "period_kind": r.get("period_kind", "fy"),
                "period_label": r.get("period_label", f"manual-{r['period_year']}"),
                "scope": r.get("scope", "consolidado"),
                "value": float(r["value"]) * scale,
                "page": int(r.get("page") or data.get("page") or 0),
            })
    return out


def _load_mappings() -> list[Rule]:
    rules: list[Rule] = []
    for yaml_path in sorted(MAPPINGS_DIR.glob("*.yaml")):
        statement = yaml_path.stem  # bp / dre / dfc / dva
        data = yaml.safe_load(yaml_path.read_text())
        for r in data.get("rules", []):
            rules.append(
                Rule(
                    pattern=re.compile(r["pattern"]),
                    line_id=r["line_id"],
                    side=r.get("side"),
                    where=r.get("where"),
                    statement=statement,
                )
            )
    # Sanity: every line_id must exist in the taxonomy.
    bad = [r for r in rules if r.line_id not in LINES_BY_ID]
    if bad:
        unknown = sorted({r.line_id for r in bad})
        raise SystemExit(f"mapping references unknown line_ids: {unknown}")
    return rules


def _evaluate_where(expr: str | None, ctx: dict) -> bool:
    if not expr:
        return True
    # Tiny safe evaluator: only attribute access on `ctx` keys via locals.
    # The grammar in YAML is restricted to "key OP literal" forms.
    try:
        return bool(eval(expr, {"__builtins__": {}}, dict(ctx)))  # noqa: S307
    except Exception:
        return False


# Section labels that mark "current" state for `parent_section` matching.
_SECTION_HINTS: dict[str, list[tuple[re.Pattern, str]]] = {
    "bp": [
        (re.compile(r"^circulante$|^ativo circulante$|^passivo circulante$"), "circulante"),
        (re.compile(r"^nao circulante$|^ativo nao circulante$|^passivo nao circulante$"),
         "nao_circulante"),
        (re.compile(r"^realizavel a longo prazo$"), "realizavel_longo_prazo"),
        (re.compile(r"^patrimonio liquido"), "patrimonio_liquido"),
    ],
    "dfc": [
        (re.compile(r"^atividades operacionais$"), "operacional"),
        (re.compile(r"^atividades de investimento$"), "investimento"),
        (re.compile(r"^atividades de financiamento$"), "financiamento"),
    ],
}

# When a BP row's `side` is None (single-side layout), infer it by walking
# rows top-to-bottom. These patterns mark transitions.
_BP_SIDE_HINTS = [
    (re.compile(r"^ativo$|^total do ativo$|^ativo circulante$|^ativo nao circulante$"), "ativo"),
    (re.compile(
        r"^passivo$|^total do passivo|^passivo circulante$|^passivo nao circulante$"
        r"|^patrimonio liquido"
    ), "passivo"),
]


_VALID_YEAR = range(1990, 2031)

# A pure note reference like "5", "5.1", "11.3.2" — never a label.
_PURE_NOTE_RE = re.compile(r"^\d+(?:\.\d+)*$")
# Trailing parenthesized note ref like "Provisões (nota 4.5.2)" — strip
# before pattern matching.
_PAREN_NOTE_RE = re.compile(r"\s*\(notas?\s*[\d.,\s]+\)\s*$", re.IGNORECASE)
# Trailing inline note number after the label, e.g.
# "Despesas com vendas/serviços 4.2.4 (27.1 ..." — peel the digits and any
# trailing fragment.
_TRAILING_NOTE_RE = re.compile(r"\s+\d+(?:\.\d+){1,4}(?:\s*\(.*\))?\s*$")
# Trailing dash/null marker, e.g. "Receitas Recebidas -" or "Patrimonial-".
_TRAILING_NULL_RE = re.compile(r"\s*[-–—]+\s*$")
# Trailing parenthesised numeric tokens — happens in 2022 Q2 ITR layouts where
# the published row prints "Resultado financeiro (28.642) (269.030)" with
# per-quarter accumulated values inline. The actual H1 values are still in
# the column zone and get parsed correctly; we just need to strip the inline
# numeric tail from the label so it matches the canonical pattern.
_TRAILING_PAREN_NUM_RE = re.compile(r"(?:\s*\([-\d.,\s]+\)\s*)+$")
# Words that, when ending a label, signal the next short token is a wrap
# continuation (e.g., "Insumos adquiridos de" + "Terceiros").
_TRAILING_CONNECTORS = {
    "de", "da", "do", "dos", "das", "em", "no", "na", "nos", "nas",
    "para", "por", "com", "ao", "aos", "a"
}


_CONT_PREFIXES = ("–", "-", "—", "/", "(", ")")
_CONT_FIRST_WORDS = {"e", "ou", "de", "da", "do", "das", "dos", "para", "em",
                     "por", "no", "na", "ao", "a", "uso", "venda"}


def _is_continuation_label(label: str, prev_label: str = "") -> bool:
    """Heuristic: does this short label look like a wrapped continuation of
    a previous row? Examples that should return True: "uso", "venda",
    "– AFAC", "(continued) administrativos", "patrocinadas/mantidas",
    "TERCEIROS" (when prev ends with "DE").
    Examples that should NOT: "Patrimônio Líquido", "Capital".
    """
    if not label:
        return False
    if _PURE_NOTE_RE.match(label):
        return False
    words = label.split()
    if len(words) > 5:
        return False
    first = words[0]
    if (
        first[:1].islower()
        or first.startswith(_CONT_PREFIXES)
        or first.lower() in _CONT_FIRST_WORDS
    ):
        return True
    # Uppercase short tails (1-2 words) when the previous label ends with a
    # connector word like "de", "do", "para".
    if len(words) <= 2 and prev_label:
        prev_words = prev_label.rstrip(":.").split()
        if prev_words and prev_words[-1].lower() in _TRAILING_CONNECTORS:
            return True
    return False


def _close_y(a: dict, b: dict, tol: float = 18.0) -> bool:
    return (
        a.get("page") == b.get("page")
        and a.get("statement") == b.get("statement")
        and a.get("side") == b.get("side")
        and abs((a.get("y") or 0) - (b.get("y") or 0)) <= tol
    )


def _stitch_and_clean(rows: list[dict]) -> list[dict]:
    """Pre-pass over parsed rows before mapping:

    1. Drop pure note-ref noise rows (label like "5.1", "14.10" with no
       values). 2014–2019 BPs print a note number on its own y-bucket below
       each line item; the parser picks them up as separate rows.
    2. Reconnect labels split across a value-bearing line. The published BPs
       sometimes wrap a long label across two rows with the values printed in
       between, producing parser output:

           {label: "Adiantamento para futuro aumento de capital", values: {}}
           {label: "(continued)",                               values: {...}}
           {label: "– AFAC",                                    values: {}}

       We collapse this into a single row with the full stitched label and
       the value from the middle row.
    3. Merge dangling label-only rows that follow a value-bearing row, for
       cases where the wrap is just trailing text:

           {label: "(-) Depreciação de imóveis de direito de", values: {...}}
           {label: "uso",                                       values: {}}
    """
    cleaned: list[dict] = []
    i = 0
    while i < len(rows):
        r = dict(rows[i])
        label = (r.get("label") or "").strip()
        values = r.get("values") or {}

        # 1. Drop pure note-ref noise.
        if not values and _PURE_NOTE_RE.match(label):
            i += 1
            continue

        # 2. Values-bearing row whose own label is either "(continued)" (parser
        #    placeholder) OR a short continuation fragment — and which is
        #    preceded by a label-only row. We adopt the prior label as a prefix
        #    and drop the placeholder/fragment row's redundant label.
        is_short_cont = (
            label == "(continued)"
            or _is_continuation_label(label, cleaned[-1].get("label", "") if cleaned else "")
        )
        if (
            is_short_cont
            and values
            and cleaned
            and not (cleaned[-1].get("values") or {})
            and _close_y(cleaned[-1], r)
        ):
            prev_label = cleaned[-1].get("label") or ""
            if label == "(continued)":
                r["label"] = prev_label or label
            else:
                # Append continuation fragment (e.g., "financiamento") to
                # the prior label ("Caixa originado nas atividades de").
                r["label"] = (prev_label.rstrip() + " " + label).strip()
            cleaned.pop()
            cleaned.append(r)
            # Look ahead: append trailing wrap fragments that follow.
            i += 1
            while i < len(rows):
                nxt = rows[i]
                if not _close_y(cleaned[-1], nxt):
                    break
                if nxt.get("values"):
                    break
                nxt_label = (nxt.get("label") or "").strip()
                if not nxt_label or _PURE_NOTE_RE.match(nxt_label):
                    i += 1
                    continue
                if not _is_continuation_label(nxt_label, cleaned[-1]["label"]):
                    break
                cleaned[-1]["label"] = (cleaned[-1]["label"].rstrip()
                                       + " " + nxt_label).strip()
                i += 1
            continue

        # 3. Trailing wrap: empty-values row right after a values-bearing row.
        if not values and label and cleaned and (cleaned[-1].get("values") or {}):
            if _close_y(cleaned[-1], r) and _is_continuation_label(label, cleaned[-1]["label"]):
                cleaned[-1]["label"] = (cleaned[-1]["label"].rstrip()
                                       + " " + label).strip()
                i += 1
                continue

        cleaned.append(r)
        i += 1
    return cleaned

# Per-doc currency scale. The Correios reports changed scale several times:
#   2001-2003: "Valores em R$" — raw R$ values, no scaling
#   2004-2009: brochure-era reports use millions (display values like
#              "6.794,9" representing R$ 6.79 billion total ativo)
#   2010:      "Valores em R$" — raw R$ values again
#   2011+:     "Em milhares de R$" / "milhares de Reais" — thousands
# Detected by vintage_year per inspection of the source PDFs.
_DOC_SCALES = {
    # 2001-2007: "Valores em R$" — values shown as raw R$.
    2001: 1.0,
    2002: 1.0,
    2003: 1.0,
    2004: 1.0,
    2005: 1.0,
    2006: 1.0,
    2007: 1.0,
    # 2008-2009: "Em milhares de R$" header but values are actually in milhões
    # (Total Ativo ~6.79 bi for Correios). Scale 1M to match.
    2008: 1_000_000.0,
    2009: 1_000_000.0,
    # 2010: "(Valores em R$)" — raw R$ again.
    2010: 1.0,
}
_DEFAULT_SCALE = 1_000.0


def _scale_for_doc(doc) -> float:
    return _DOC_SCALES.get(doc.year, _DEFAULT_SCALE)


def _extract_period(period_label: str) -> tuple[int, str] | None:
    """Extract (period_year, period_kind) from a column header label.

    period_kind:
      "fy"   year-end balance / full-year flow (31/12, 01/01 of next year)
      "q1"   31/03 balance / Q1 cumulative
      "q2"   30/06 balance / H1 cumulative
      "q3"   30/09 balance / 9M cumulative
      "ye"   bare year (older quarterlies just say "2014") — interpret as fy
    """
    m = re.match(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", period_label)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if month == 1 and day == 1:
            return year - 1, "fy"
        if month == 12 and day == 31:
            return year, "fy"
        if month == 3:
            return year, "q1"
        if month == 6:
            return year, "q2"
        if month == 9:
            return year, "q3"
        # Other day/month combos — fall through to fy, retaining year.
        return year, "fy"
    # Brazilian spelled date "31 dez 2014".
    m2 = re.match(r"(\d{1,2})\s+(\w+)\.?\s+(\d{4})", period_label, re.I)
    if m2:
        day, month_text, year = int(m2.group(1)), m2.group(2).lower(), int(m2.group(3))
        month_num = {
            "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
            "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
        }.get(month_text[:3])
        if month_num is None:
            return year, "fy"
        if month_num == 1 and day == 1:
            return year - 1, "fy"
        if month_num == 12:
            return year, "fy"
        kind = {3: "q1", 6: "q2", 9: "q3"}.get(month_num, "fy")
        return year, kind
    m3 = re.match(r"^(\d{4})$", period_label)
    if m3:
        return int(m3.group(1)), "fy"
    return None


def apply_doc(parsed: dict, doc) -> tuple[list[dict], list[dict]]:
    """Returns (canonical_rows, unmapped_rows)."""
    rules = _load_mappings()
    scale = _scale_for_doc(doc)
    canonical: list[dict] = []
    unmapped: list[dict] = []

    # Track parent_section per (statement, side) as we walk rows top-to-bottom.
    # DFC pages in 2019+ omit the "Atividades operacionais" header at the top
    # (the section is implicit), so default to operacional and let explicit
    # "Atividades de investimento" / "de financiamento" headers switch it.
    sections: dict[tuple[str, str | None], str] = defaultdict(lambda: "")
    sections[("dfc", None)] = "operacional"
    # Track inferred BP side for rows whose parser-side is None.
    inferred_bp_side: str | None = None

    # Header noise: column-header artifacts that have no values and shouldn't
    # count as unmapped. (REAPRESENTADO, NOTA, CNPJ, page numbers, dates, plus
    # contextual/section headers that the taxonomy doesn't represent.)
    NOISE_PATTERNS = [
        re.compile(r"^reapresentado(\s+reapresentado)*$"),
        re.compile(r"^nota$|^nota reapresentado$"),
        re.compile(r"^cnpj\s+[\d./-]+$"),
        re.compile(r"^\d{1,2}/\d{1,2}/\d{4}( \d{1,2}/\d{1,2}/\d{4})*$"),
        re.compile(r"^geracao do valor adicionado$|^i geracao do valor adicionado$"),
        re.compile(r"^distribuicao do valor adicionado$|^ii distribuicao do valor adicionado$"),
        re.compile(r"^\(continued\)$"),
        # Note ref-only labels left over after stripping trailing dashes,
        # e.g. "16.3.2 - -" → "16.3.2".
        re.compile(r"^\d+(?:\.\d+)+$"),
        # "As notas explicativas..." footer.
        re.compile(r"^as notas explicativas.*$"),
        # Page footers / DVA section dividers.
        re.compile(r"^postal$"),
    ]
    for raw in _stitch_and_clean(parsed["rows"]):
        statement = raw["statement"]
        side = raw.get("side")
        label = raw["label"]
        norm = normalize_label(label)
        # Strip parenthesized / trailing note refs and dangling null markers
        # before pattern matching, so labels with embedded note numbers
        # ("provisoes (nota 4.5.2)", "receitas recebidas -") still resolve.
        prev_norm = ""
        while prev_norm != norm:
            prev_norm = norm
            norm = _PAREN_NOTE_RE.sub("", norm).strip()
            norm = _TRAILING_PAREN_NUM_RE.sub("", norm).strip()
            norm = _TRAILING_NOTE_RE.sub("", norm).strip()
            norm = _TRAILING_NULL_RE.sub("", norm).strip()
        # Drop pure header artifacts.
        if any(p.match(norm) for p in NOISE_PATTERNS):
            continue
        # Update BP side inference walker.
        if statement == "bp":
            for pat, s in _BP_SIDE_HINTS:
                if pat.search(norm):
                    inferred_bp_side = s
                    break
            if side is None and inferred_bp_side is not None:
                side = inferred_bp_side
        # Update section context.
        for pat, sect in _SECTION_HINTS.get(statement, []):
            if pat.search(norm):
                sections[(statement, side)] = sect
                break

        ctx = {
            "statement": statement,
            "side": side,
            "parent_section": sections[(statement, side)],
        }
        rule = next(
            (
                r for r in rules
                if r.statement == statement
                and (r.side is None or r.side == side)
                and r.pattern.match(norm)
                and _evaluate_where(r.where, ctx)
            ),
            None,
        )
        if rule is None:
            unmapped.append({
                "doc_id": parsed["doc_id"],
                "page": raw["page"],
                "y": raw["y"],
                "statement": statement,
                "side": side,
                "label": label,
                "label_normalized": norm,
                "values": json.dumps(raw["values"], ensure_ascii=False),
            })
            continue
        # Emit one row per period. Period keys carry "<label>|<scope>" so
        # 4-column Controladora+Consolidado layouts emit two rows per period.
        for period_key, value in raw["values"].items():
            if value is None:
                continue
            if "|" in period_key:
                period_label, scope = period_key.rsplit("|", 1)
            else:
                period_label, scope = period_key, "consolidado"
            period = _extract_period(period_label)
            if period is None:
                continue
            period_year, period_kind = period
            if period_year not in _VALID_YEAR:
                continue
            canonical.append({
                "doc_id": parsed["doc_id"],
                "vintage_year": doc.year,
                "statement": statement,
                "side": side,
                "line_id": rule.line_id,
                "label_raw": label,
                "note_ref": raw.get("note_ref"),
                "period_year": period_year,
                "period_kind": period_kind,
                "period_label": period_label,
                "scope": scope,
                "value": float(value) * scale,
                "page": raw["page"],
            })
    return canonical, unmapped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Comma-separated doc_ids")
    args = parser.parse_args(argv)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    UNMAPPED_DIR.mkdir(parents=True, exist_ok=True)

    targets = sorted(PARSED_DIR.glob("*.json"))
    if args.only:
        wanted = set(args.only.split(","))
        targets = [t for t in targets if t.stem in wanted]

    all_canonical: list[dict] = []
    all_unmapped_count = 0
    for t in targets:
        parsed = json.loads(t.read_text())
        try:
            doc = by_id(parsed["doc_id"])
        except KeyError:
            print(f"WARN unknown doc_id {parsed['doc_id']}, skipping", file=sys.stderr)
            continue
        canonical, unmapped = apply_doc(parsed, doc)
        all_canonical.extend(canonical)
        all_unmapped_count += len(unmapped)
        # Write per-doc unmapped CSV.
        if unmapped:
            up = UNMAPPED_DIR / f"{parsed['doc_id']}.csv"
            with up.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(unmapped[0].keys()))
                writer.writeheader()
                writer.writerows(unmapped)
        print(f"{parsed['doc_id']}: mapped={len(canonical)} unmapped={len(unmapped)}",
              file=sys.stderr)

    # Apply manual overrides (hand-typed figures from sources we can't extract).
    manual_rows = _load_manual_overrides()
    if manual_rows:
        all_canonical.extend(manual_rows)
        print(f"\nmanual overrides: +{len(manual_rows)} rows", file=sys.stderr)

    if all_canonical:
        df = pd.DataFrame(all_canonical)
        out = PROCESSED_DIR / "canonical.parquet"
        df.to_parquet(out, index=False)
        print(f"\nwrote {len(df)} rows -> {out}", file=sys.stderr)
        # Per-year shards.
        by_year_dir = PROCESSED_DIR / "by_year"
        by_year_dir.mkdir(parents=True, exist_ok=True)
        for yr, sub in df.groupby("vintage_year"):
            sub.to_parquet(by_year_dir / f"{yr}.parquet", index=False)
    print(f"unmapped total: {all_unmapped_count}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
