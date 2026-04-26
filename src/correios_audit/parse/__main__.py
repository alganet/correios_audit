"""
Walk extracted JSONs and parse each into raw statement rows.

Header detection identifies which statement is on each page. We currently emit
rows for BP, DRE, DRA, DFC, DVA, and DMPL.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import asdict
from pathlib import Path

from correios_audit.catalog import by_id
from correios_audit.parse.bp import parse_bp_page
from correios_audit.parse.common import RawRow, detect_period_columns
from correios_audit.parse.statement import parse_simple_statement

ROOT = Path(__file__).resolve().parents[3]
TEXT_DIR = ROOT / "data" / "interim" / "text"
PARSED_DIR = ROOT / "data" / "interim" / "parsed"


_HEADER_PATTERNS = [
    ("bp", re.compile(r"balanc?o patrimonial", re.I)),
    ("dra", re.compile(r"demonstrac?ao do resultado abrangente", re.I)),
    ("dre", re.compile(r"demonstrac?ao do resultado(?! abrangente)", re.I)),
    ("dmpl", re.compile(r"mutac?o\w* do patrimonio", re.I)),
    ("dfc", re.compile(r"fluxos de caixa", re.I)),
    ("dva", re.compile(r"valor adicionado", re.I)),
]


_TOC_HINT = re.compile(r"\.{4,}")  # dotted leaders in TOC entries
_TOC_PAGE = re.compile(r"\b(sum[aá]rio|[ií]ndice)\b", re.I)


def _is_toc_page(page: dict) -> bool:
    """A TOC page typically opens with 'SUMÁRIO' or 'ÍNDICE' near the top."""
    for line in page["lines"][:6]:
        text = " ".join(w[2] for w in line["words"])
        if _TOC_PAGE.search(text):
            return True
    return False


def _split_page_by_subheaders(page: dict) -> list[tuple[str, dict]]:
    """If multiple real statement headers appear on one page (e.g., DRE+DRA on
    page 4 of the 2024 annual), split into virtual sub-pages keyed by statement.

    Filters out:
    - TOC entries (lines with dotted leaders like "Balanço Patrimonial.....3").
    - Lines that look like narrative references inside Notas Explicativas
      (we already short-circuit at the first Notas page in `parse_doc`).

    Does NOT require a nearby date header — the OCR'd 2010-2017 era often has
    the date header detached from or absent on the statement page; the parser
    now infers columns from body rows when needed.
    """
    splits: list[tuple[str, int]] = []
    for i, line in enumerate(page["lines"]):
        text = " ".join(w[2] for w in line["words"])
        if _TOC_HINT.search(text):
            continue
        # Skip narrative lines (mid-paragraph references to a statement).
        if len(text) > 80:
            continue
        norm = _strip_accents(text)
        for stmt, pat in _HEADER_PATTERNS:
            if not pat.search(norm):
                continue
            # Require a date-column line within the next ~12 lines so we don't
            # falsely split on titles that have no readable data table below.
            has_period_below = any(
                detect_period_columns(page["lines"][j])
                for j in range(i + 1, min(i + 13, len(page["lines"])))
            )
            if has_period_below:
                splits.append((stmt, i))
            break
    # De-dupe consecutive duplicates (DRE matched on lines i and i+1, etc.)
    cleaned: list[tuple[str, int]] = []
    for s in splits:
        if cleaned and cleaned[-1][0] == s[0]:
            continue
        cleaned.append(s)
    splits = cleaned
    if not splits:
        return []
    if len(splits) == 1:
        return [(splits[0][0], page)]
    out: list[tuple[str, dict]] = []
    for k, (stmt, start) in enumerate(splits):
        end = splits[k + 1][1] if k + 1 < len(splits) else len(page["lines"])
        sub_lines = page["lines"][start:end]
        out.append((stmt, {"page": page["page"], "lines": sub_lines}))
    return out


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def detect_statement(page: dict) -> str | None:
    # Look only in the first 6 lines of the page.
    head_text = " ".join(
        " ".join(w[2] for w in line["words"])
        for line in page["lines"][:6]
    )
    head = _strip_accents(head_text)
    for stmt, pat in _HEADER_PATTERNS:
        if pat.search(head):
            return stmt
    return None


_NOTES_HEADER = re.compile(r"notas?\s+explicativas?", re.I)


def _is_notes_page(page: dict) -> bool:
    for line in page["lines"][:6]:
        text = " ".join(w[2] for w in line["words"])
        if _NOTES_HEADER.search(_strip_accents(text)):
            return True
    return False


_DEFERRED_STATEMENTS = {"dmpl"}  # complex multi-column equity rollforward; handled later


def parse_doc(extracted: dict, *, vintage_year: int | None = None,
              period: str = "fy") -> dict:
    """Parse the main statements before the Notas Explicativas section.

    BP is special-cased: in modern annuals it sits on one page with ATIVO and
    PASSIVO side-by-side; in older / quarterly reports ATIVO is on one page
    and PASSIVO+Patrimônio on the next. We allow up to 2 BP sub-pages.
    Other statements are taken once (first occurrence)."""
    rows: list[dict] = []
    statements_found: list[str] = []
    seen: set[str] = set()
    bp_pages_seen = 0
    for page in extracted["pages"]:
        if _is_notes_page(page):
            break
        if _is_toc_page(page):
            continue
        for stmt, sub_page in _split_page_by_subheaders(page):
            if stmt in _DEFERRED_STATEMENTS:
                continue
            if stmt == "bp":
                if bp_pages_seen >= 2:
                    continue
                bp_pages_seen += 1
            elif stmt in seen:
                continue
            else:
                seen.add(stmt)
            statements_found.append(f"p{page['page']}={stmt}")
            if stmt == "bp":
                ativo, passivo = parse_bp_page(sub_page)
                for sp in (ativo, passivo):
                    if not sp:
                        continue
                    for r in sp.rows:
                        rows.append({"statement": stmt, **asdict(r)})
            else:
                # Body-row column inference is only safe for annual reports
                # (quarterlies have 8-column layouts that can't be disambiguated
                # without explicit headers).
                fallback_year = vintage_year if period == "fy" else None
                sp = parse_simple_statement(sub_page, stmt, vintage_year=fallback_year)
                if not sp:
                    continue
                for r in sp.rows:
                    rows.append({"statement": stmt, **asdict(r)})
    return {
        "doc_id": extracted["doc_id"],
        "statements_found": statements_found,
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Comma-separated doc_ids")
    args = parser.parse_args(argv)

    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    targets = sorted(TEXT_DIR.glob("*.json"))
    if args.only:
        wanted = set(args.only.split(","))
        targets = [t for t in targets if t.stem in wanted]
    n_ok = 0
    for tpath in targets:
        try:
            doc = by_id(tpath.stem)
        except KeyError:
            print(f"WARN unknown doc_id {tpath.stem}, skipping", file=sys.stderr)
            continue
        # Only financial-statement docs (kind="df") have canonical line items.
        # Audit reports and Conselho Fiscal opinions are narrative; skip them.
        if doc.kind != "df":
            print(f"skip {doc.doc_id} (kind={doc.kind})", file=sys.stderr)
            continue
        extracted = json.loads(tpath.read_text())
        out = parse_doc(extracted, vintage_year=doc.year, period=doc.period)
        out_path = PARSED_DIR / tpath.name
        out_path.write_text(json.dumps(out, ensure_ascii=False, default=lambda o: asdict(o)))
        print(f"parsed {tpath.stem}: {len(out['rows'])} rows, statements={out['statements_found']}",
              file=sys.stderr)
        n_ok += 1
    print(f"\nparsed={n_ok}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
