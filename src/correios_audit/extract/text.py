"""
Extract positional text from a born-digital PDF.

Output schema (one JSON file per doc, gzip not used — pages are small):

{
  "doc_id": "2024-fy-df",
  "method": "text" | "ocr+text",
  "page_size": [width, height],
  "n_pages": 58,
  "pages": [
    {
      "page": 1,
      "lines": [
        {"y": 154.0, "words": [[39.5, 79.6, "CIRCULANTE"], [206.4, 240.1, "2.647.765"], ...]},
        ...
      ]
    },
    ...
  ]
}

We deliberately do NOT try to reconstruct tables here — that's the parser's job.
We just give it the cleanest possible "lines of (x, x1, text) tuples" view.
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


def _cluster_words(words: list[tuple]) -> list[dict[str, Any]]:
    """words is pymupdf's words tuples: (x0, y0, x1, y1, text, block, line, word)."""
    by_y: dict[int, list[tuple[float, float, str]]] = defaultdict(list)
    for x0, y0, x1, _y1, text, *_ in words:
        if not text.strip():
            continue
        bucket = round(y0 / LINE_BUCKET) * LINE_BUCKET
        by_y[bucket].append((x0, x1, text))
    out: list[dict[str, Any]] = []
    for y in sorted(by_y):
        ws = sorted(by_y[y], key=lambda w: w[0])
        out.append({"y": float(y), "words": [[float(x0), float(x1), t] for x0, x1, t in ws]})
    return out


def extract_pdf(pdf_path: Path, *, method: str = "text") -> dict[str, Any]:
    with pymupdf.open(pdf_path) as doc:
        pages: list[dict[str, Any]] = []
        first_size = (doc[0].rect.width, doc[0].rect.height) if len(doc) else (0.0, 0.0)
        for i, page in enumerate(doc):
            words = page.get_text("words")
            pages.append({"page": i + 1, "lines": _cluster_words(words)})
        return {
            "method": method,
            "page_size": [float(first_size[0]), float(first_size[1])],
            "n_pages": len(doc),
            "pages": pages,
        }


def write_extracted(doc_id: str, pdf_path: Path, out_dir: Path, *, method: str = "text") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{doc_id}.json"
    data = {"doc_id": doc_id, **extract_pdf(pdf_path, method=method)}
    out_path.write_text(json.dumps(data, ensure_ascii=False))
    return out_path
