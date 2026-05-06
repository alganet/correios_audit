"""
Per-doc data-quality summary.

Builds `data/processed/quality.json` with one entry per `doc_id`, plus
aggregated per-vintage statistics. Consumed by the site builder to render
the `qualidade/` pages.

Each entry is intentionally narrow — extraction method, OCR confidence band,
mapping coverage, materiality status, cross-foot status, restatement count.
The site renders this as a colored badge per vintage.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from correios_audit.normalize.taxonomy import LINES_BY_ID

ROOT = Path(__file__).resolve().parents[3]
TEXT_DIR = ROOT / "data" / "interim" / "text"
UNMAPPED_DIR = ROOT / "data" / "interim" / "unmapped"
PROCESSED = ROOT / "data" / "processed" / "canonical.parquet"
QUALITY_JSON = ROOT / "data" / "processed" / "quality.json"


def _confidence_band(mean_conf: float | None) -> str:
    if mean_conf is None:
        return "unknown"
    if mean_conf >= 0.95:
        return "high"      # green
    if mean_conf >= 0.80:
        return "medium"    # yellow
    return "low"           # red


def _read_extracted_meta(doc_id: str) -> dict[str, Any]:
    """Pull OCR-engine, confidence, low-conf count from the per-doc text JSON."""
    path = TEXT_DIR / f"{doc_id}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return {
        "ocr_engine": data.get("ocr_engine", "text"),
        "ocr_mean_confidence": data.get("ocr_mean_confidence"),
        "ocr_low_conf_count": data.get("ocr_low_conf_count", 0),
        "n_pages": data.get("n_pages", 0),
    }


def _count_unmapped(doc_id: str) -> tuple[int, int]:
    """Return (n_unmapped_rows, n_unmapped_with_values).

    A row in the unmapped CSV with a populated 'values' field represents
    extracted-but-unmapped data — it had numbers, just no matching rule.
    Rows with empty 'values' are pure noise (page footers, director names).
    """
    path = UNMAPPED_DIR / f"{doc_id}.csv"
    if not path.exists():
        return 0, 0
    import csv
    n_total = 0
    n_with_values = 0
    with path.open() as f:
        for row in csv.DictReader(f):
            n_total += 1
            if row.get("values") and row["values"] not in ("{}", "", "null"):
                n_with_values += 1
    return n_total, n_with_values


def _doc_metrics(doc_id: str, df: pd.DataFrame) -> dict[str, Any]:
    """Per-doc canonical metrics: row counts split by mapping_method."""
    sub = df[df.doc_id == doc_id]
    if sub.empty:
        return {
            "rows_canonical": 0,
            "rows_regex": 0,
            "rows_fuzzy_ocr": 0,
            "statements": [],
            "revenue_liquida": None,
            "ativo_total": None,
        }
    methods = sub.get("mapping_method", pd.Series(dtype=str))
    # Pull headline figures for the most-recent FY in this doc.
    rev_rows = sub[(sub.line_id == "dre.receita_liquida") & (sub.period_kind == "fy")]
    ativo_rows = sub[(sub.line_id == "bp.ativo.total") & (sub.period_kind == "fy")]
    return {
        "rows_canonical": int(len(sub)),
        "rows_regex": int((methods == "regex").sum()) if len(methods) else 0,
        "rows_fuzzy_ocr": int((methods == "fuzzy_ocr").sum()) if len(methods) else 0,
        "statements": sorted(sub.statement.dropna().unique().tolist()),
        "revenue_liquida": (
            float(rev_rows.sort_values("period_year").iloc[-1]["value"])
            if not rev_rows.empty else None
        ),
        "ativo_total": (
            float(ativo_rows.sort_values("period_year").iloc[-1]["value"])
            if not ativo_rows.empty else None
        ),
    }


def _doc_cross_foot_status(doc_id: str, df: pd.DataFrame) -> dict[str, Any]:
    """Lightweight per-doc cross-foot summary. Returns the diff in R$ for BP
    and DRE-lucro_bruto; the verify script does the strict pass/fail.
    """
    sub = df[df.doc_id == doc_id]
    if sub.empty:
        return {"bp_diff": None, "dre_lucro_bruto_diff": None}
    out: dict[str, Any] = {"bp_diff": None, "dre_lucro_bruto_diff": None}
    for py in sorted(sub.period_year.dropna().unique()):
        py_sub = sub[sub.period_year == py]
        a = py_sub[py_sub.line_id == "bp.ativo.total"]
        p = py_sub[py_sub.line_id == "bp.passivo.total"]
        if not a.empty and not p.empty:
            diff = float(a.iloc[0]["value"]) - float(p.iloc[0]["value"])
            out["bp_diff"] = diff
        rl = py_sub[py_sub.line_id == "dre.receita_liquida"]
        cpv = py_sub[py_sub.line_id == "dre.cpv"]
        lb = py_sub[py_sub.line_id == "dre.lucro_bruto"]
        if not rl.empty and not cpv.empty and not lb.empty:
            diff = (float(rl.iloc[0]["value"]) + float(cpv.iloc[0]["value"])
                    - float(lb.iloc[0]["value"]))
            out["dre_lucro_bruto_diff"] = diff
    return out


def _sign_violations_per_doc(df: pd.DataFrame) -> dict[str, int]:
    """Count sign-convention violations per doc_id."""
    out: dict[str, int] = defaultdict(int)
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
        for doc_id in wrong.doc_id.dropna():
            out[doc_id] += 1
    return dict(out)


def build_quality_report(df: pd.DataFrame) -> dict[str, Any]:
    """Compose the per-doc quality dict + per-vintage rollup."""
    sign_violations = _sign_violations_per_doc(df)
    by_doc: dict[str, Any] = {}
    for doc_id in sorted(df.doc_id.dropna().unique()):
        if not isinstance(doc_id, str):
            continue
        if doc_id.startswith("manual:"):
            continue
        meta = _read_extracted_meta(doc_id)
        unmapped_total, unmapped_with_values = _count_unmapped(doc_id)
        metrics = _doc_metrics(doc_id, df)
        cross = _doc_cross_foot_status(doc_id, df)
        by_doc[doc_id] = {
            "doc_id": doc_id,
            **meta,
            "confidence_band": _confidence_band(meta.get("ocr_mean_confidence")),
            "unmapped_total": unmapped_total,
            "unmapped_with_values": unmapped_with_values,
            **metrics,
            **cross,
            "sign_violations": sign_violations.get(doc_id, 0),
        }
    # Per-vintage rollup: pick the FY-DF doc as representative when present.
    by_vintage: dict[str, Any] = {}
    for vintage_year in sorted(df.vintage_year.dropna().unique()):
        try:
            vy = int(vintage_year)
        except (TypeError, ValueError):
            continue
        candidates = [
            d for d in by_doc.values()
            if d["doc_id"].startswith(f"{vy}-fy-df")
        ] or [
            d for d in by_doc.values()
            if d["doc_id"].startswith(f"{vy}-")
        ]
        if not candidates:
            continue
        primary = candidates[0]
        all_docs = sorted(
            d["doc_id"] for d in by_doc.values()
            if d["doc_id"].startswith(f"{vy}-")
        )
        by_vintage[str(vy)] = {
            "vintage_year": vy,
            "primary_doc_id": primary["doc_id"],
            "all_doc_ids": all_docs,
            "ocr_engine": primary.get("ocr_engine"),
            "confidence_band": primary.get("confidence_band"),
            "ocr_mean_confidence": primary.get("ocr_mean_confidence"),
            "rows_canonical": primary.get("rows_canonical", 0),
            "rows_fuzzy_ocr": primary.get("rows_fuzzy_ocr", 0),
            "unmapped_with_values": primary.get("unmapped_with_values", 0),
            "bp_diff": primary.get("bp_diff"),
            "dre_lucro_bruto_diff": primary.get("dre_lucro_bruto_diff"),
            "sign_violations": primary.get("sign_violations", 0),
            "revenue_liquida": primary.get("revenue_liquida"),
            "ativo_total": primary.get("ativo_total"),
        }
    return {"by_doc": by_doc, "by_vintage": by_vintage}


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.parse_args(argv)
    if not PROCESSED.exists():
        print(f"ERROR: {PROCESSED} not found. Run `make normalize` first.")
        return 2
    df = pd.read_parquet(PROCESSED)
    report = build_quality_report(df)
    QUALITY_JSON.parent.mkdir(parents=True, exist_ok=True)
    QUALITY_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    n_docs = len(report["by_doc"])
    n_vintages = len(report["by_vintage"])
    print(f"wrote quality report: {n_docs} docs across {n_vintages} vintages -> {QUALITY_JSON}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
