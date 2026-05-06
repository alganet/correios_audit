"""
Extract positional text from a born-digital PDF.

Output schema (one JSON file per doc):

{
  "doc_id": "2024-fy-df",
  "ocr_engine": "text" | "paddleocr" | "tesseract",
  "page_size": [width, height],
  "n_pages": 58,
  "ocr_mean_confidence": 1.0,         # 1.0 for born-digital
  "ocr_low_conf_count": 0,            # words with confidence < LOW_CONF_THRESHOLD
  "pages": [
    {
      "page": 1,
      "lines": [
        {"y": 154.0, "words": [[39.5, 79.6, "CIRCULANTE", 1.0], ...]},
        ...
      ]
    },
    ...
  ]
}

Each word is a 4-tuple [x0, x1, text, confidence]. Born-digital words are
emitted with confidence=1.0; OCR words carry the recognizer's own score.

We deliberately do NOT try to reconstruct tables here — that's the parser's
job. We just give it the cleanest possible "lines of (x0, x1, text, conf)
tuples" view.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pymupdf

# Y-coordinates of words on the same visual line typically agree to within
# a small fraction of font height. Cluster into 2-pt buckets — empirically
# tight enough to separate adjacent rows in financial tables, loose enough
# that subscripts/superscripts merge with their host line.
LINE_BUCKET = 2

# Words below this OCR confidence are flagged for the quality dashboard.
LOW_CONF_THRESHOLD = 0.7


def _cluster_words(
    words: list[tuple[float, float, float, float, str, float]],
) -> list[dict[str, Any]]:
    """words: (x0, y0, x1, y1, text, confidence). Cluster by Y bucket, sort by X.

    Born-digital callers pass confidence=1.0 for every word.
    """
    by_y: dict[int, list[tuple[float, float, str, float]]] = defaultdict(list)
    for x0, y0, x1, _y1, text, conf in words:
        if not text.strip():
            continue
        bucket = round(y0 / LINE_BUCKET) * LINE_BUCKET
        by_y[bucket].append((x0, x1, text, conf))
    out: list[dict[str, Any]] = []
    for y in sorted(by_y):
        ws = sorted(by_y[y], key=lambda w: w[0])
        out.append(
            {
                "y": float(y),
                "words": [[float(x0), float(x1), t, float(c)] for x0, x1, t, c in ws],
            }
        )
    return out


def _confidence_summary(pages: list[dict[str, Any]]) -> tuple[float, int]:
    total = 0
    score = 0.0
    low = 0
    for p in pages:
        for line in p["lines"]:
            for w in line["words"]:
                conf = w[3] if len(w) > 3 else 1.0
                total += 1
                score += conf
                if conf < LOW_CONF_THRESHOLD:
                    low += 1
    mean = score / total if total else 1.0
    return mean, low


def extract_pdf(pdf_path: Path) -> dict[str, Any]:
    """Born-digital extraction via pymupdf. Confidence is always 1.0."""
    with pymupdf.open(pdf_path) as doc:
        pages: list[dict[str, Any]] = []
        first_size = (doc[0].rect.width, doc[0].rect.height) if len(doc) else (0.0, 0.0)
        for i, page in enumerate(doc):
            words = page.get_text("words")
            # pymupdf returns (x0, y0, x1, y1, text, block, line, word). Drop
            # the structural ints, append confidence=1.0.
            tagged = [(w[0], w[1], w[2], w[3], w[4], 1.0) for w in words]
            pages.append({"page": i + 1, "lines": _cluster_words(tagged)})
        mean_conf, low_conf = _confidence_summary(pages)
        return {
            "ocr_engine": "text",
            "page_size": [float(first_size[0]), float(first_size[1])],
            "n_pages": len(doc),
            "ocr_mean_confidence": mean_conf,
            "ocr_low_conf_count": low_conf,
            "pages": pages,
        }


def write_extracted_text(doc_id: str, pdf_path: Path, out_dir: Path) -> Path:
    """Born-digital path: pymupdf only, no OCR."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{doc_id}.json"
    data = {"doc_id": doc_id, **extract_pdf(pdf_path)}
    out_path.write_text(json.dumps(data, ensure_ascii=False))
    return out_path


def write_extracted_from_pages(
    doc_id: str,
    pages: list[dict[str, Any]],
    page_size: tuple[float, float],
    out_dir: Path,
    *,
    ocr_engine: str,
) -> Path:
    """OCR path: caller supplies already-clustered pages with per-word confidence.

    Each page must be `{"page": int, "lines": [{"y": float, "words": [[x0, x1, text, conf], ...]}]}`.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{doc_id}.json"
    mean_conf, low_conf = _confidence_summary(pages)
    data = {
        "doc_id": doc_id,
        "ocr_engine": ocr_engine,
        "page_size": [float(page_size[0]), float(page_size[1])],
        "n_pages": len(pages),
        "ocr_mean_confidence": mean_conf,
        "ocr_low_conf_count": low_conf,
        "pages": pages,
    }
    out_path.write_text(json.dumps(data, ensure_ascii=False))
    return out_path


# Backwards-compatible shim: older callers may still import write_extracted.
def write_extracted(
    doc_id: str, pdf_path: Path, out_dir: Path, *, method: str = "text"
) -> Path:
    if method != "text":
        raise ValueError(
            "write_extracted only supports method='text' now; "
            "call write_extracted_from_pages for OCR output."
        )
    return write_extracted_text(doc_id, pdf_path, out_dir)
