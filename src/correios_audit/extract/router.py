"""
Decide whether a PDF is text-extractable or needs OCR.

We don't trust the year — some 2008 PDFs are born-digital, some 2015 ones are
scans. We measure: total characters extracted by pymupdf across the whole doc.
A born-digital financial statement of any era has at least a few thousand chars
of selectable text. Below `MIN_CHARS`, we route to OCR.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

# Empirically, modern Correios annuals have ~190k chars over ~60 pages (~3k/page);
# scanned scans are 0. Set a generous floor so corrupt extractions fall through
# to OCR rather than producing empty parquet rows.
MIN_CHARS_TOTAL = 1000
MIN_CHARS_PER_PAGE_AVG = 50


def measure_text(pdf_path: Path) -> dict[str, float | int]:
    with pymupdf.open(pdf_path) as doc:
        n_pages = len(doc)
        total_chars = 0
        for page in doc:
            total_chars += len(page.get_text())
    return {
        "n_pages": n_pages,
        "total_chars": total_chars,
        "chars_per_page": total_chars / max(n_pages, 1),
    }


def needs_ocr(pdf_path: Path) -> bool:
    m = measure_text(pdf_path)
    return (
        m["total_chars"] < MIN_CHARS_TOTAL
        or m["chars_per_page"] < MIN_CHARS_PER_PAGE_AVG
    )
