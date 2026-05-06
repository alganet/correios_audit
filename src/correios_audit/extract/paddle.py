"""
PaddleOCR-backed extraction for scanned PDFs.

For each page we:

1. Rasterize at 400 DPI and clean (preprocess.render_pages).
2. Run PaddleOCR detection + recognition (latin model — covers Portuguese).
3. Map the polygon bounding box to a tight axis-aligned rect in PDF
   coordinate space, so downstream parsing logic that compares X positions
   across pages keeps working.
4. Emit `(x0, y0, x1, y1, text, confidence)` per recognized box, then cluster
   into lines with the same logic the born-digital path uses.

PaddleOCR's first run downloads detection + recognition + classifier model
weights to ~/.paddleocr/ (~250 MB). Subsequent runs are fully local.

Fallback: if PaddleOCR fails on a specific page (rare — happens with fully
blank scans), the page is emitted with an empty `lines` list and a warning is
printed. The doc still completes; the verify layer will catch missing totals.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

from correios_audit.extract.preprocess import PageImage, render_pages
from correios_audit.extract.text import _cluster_words

# Cache the PaddleOCR instance — loading the model takes several seconds and
# the same instance is safe to reuse across pages.
_PADDLE_INSTANCE: Any = None


def _get_paddle() -> Any:
    """Lazy import + lazy init. Importing paddleocr is slow (~3s).

    `lang="latin"` selects the multilingual Latin recognition model, which
    is the closest fit for Portuguese (PaddleOCR doesn't ship a dedicated
    `pt` recognizer, but `latin` is trained on the Romance-language Latin
    Extended set and significantly outperforms the default English model on
    accented Portuguese text).
    """
    global _PADDLE_INSTANCE
    if _PADDLE_INSTANCE is not None:
        return _PADDLE_INSTANCE
    import warnings as _warnings

    _warnings.filterwarnings("ignore")
    from paddleocr import PaddleOCR

    _PADDLE_INSTANCE = PaddleOCR(
        use_angle_cls=True,
        lang="latin",
        det_db_box_thresh=0.5,
        show_log=False,
    )
    return _PADDLE_INSTANCE


def _box_to_rect(box: list[list[float]]) -> tuple[float, float, float, float]:
    """PaddleOCR returns a 4-point polygon. Take the axis-aligned bounding
    rectangle (min/max X and Y)."""
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return min(xs), min(ys), max(xs), max(ys)


def _scale_to_pdf(
    rect: tuple[float, float, float, float],
    image_size: tuple[int, int],
    pdf_size: tuple[float, float],
) -> tuple[float, float, float, float]:
    """Map an image-pixel rect to PDF point coordinates.

    image_size is (W, H) in pixels; pdf_size is (W, H) in points.
    """
    img_w, img_h = image_size
    pdf_w, pdf_h = pdf_size
    sx = pdf_w / max(img_w, 1)
    sy = pdf_h / max(img_h, 1)
    x0, y0, x1, y1 = rect
    return x0 * sx, y0 * sy, x1 * sx, y1 * sy


def _split_to_words(
    rect: tuple[float, float, float, float], text: str, confidence: float
) -> list[tuple[float, float, float, float, str, float]]:
    """PaddleOCR returns one box per *line* of text — a whole row of a
    financial table comes back as a single "Caixa e equivalentes 1.234.567 1.000.000"
    string in one rectangle. We split on whitespace and partition the rect
    horizontally so downstream parsing (which expects per-word X positions)
    keeps working.

    Y coordinates stay constant within a line. X is partitioned by character
    count weighted by token length.
    """
    tokens = text.split()
    if not tokens:
        return []
    if len(tokens) == 1:
        x0, y0, x1, y1 = rect
        return [(x0, y0, x1, y1, tokens[0], confidence)]
    # Width-allocate by total characters (including a single-char gap between tokens).
    char_total = sum(len(t) for t in tokens) + (len(tokens) - 1)
    x0, y0, x1, y1 = rect
    width = x1 - x0
    out: list[tuple[float, float, float, float, str, float]] = []
    cursor = 0
    for t in tokens:
        start = x0 + width * (cursor / char_total)
        end = x0 + width * ((cursor + len(t)) / char_total)
        out.append((start, y0, end, y1, t, confidence))
        cursor += len(t) + 1
    return out


def _recognize(image: np.ndarray) -> list[tuple[list[list[float]], str, float]]:
    """Wrap PaddleOCR.ocr to return [(box, text, confidence), ...]."""
    paddle = _get_paddle()
    # PaddleOCR expects RGB or grayscale arrays; uint8 grayscale works.
    result = paddle.ocr(image, det=True, rec=True, cls=True)
    if not result:
        return []
    # PaddleOCR 2.x returns [[(box, (text, conf)), ...]] — one outer list per
    # input image. We only ever pass a single image.
    inner = result[0] if isinstance(result, list) and result else None
    if not inner:
        return []
    out: list[tuple[list[list[float]], str, float]] = []
    for entry in inner:
        if entry is None:
            continue
        box, txt = entry
        if isinstance(txt, (list, tuple)) and len(txt) == 2:
            text, conf = txt
        else:
            text, conf = str(txt), 1.0
        out.append((box, str(text), float(conf)))
    return out


def extract_pages(pdf_path: Path, *, dpi: int = 400) -> dict[str, Any]:
    """Run PaddleOCR over every page. Returns the page-list payload that
    `text.write_extracted_from_pages` consumes.

    `pages` is `[{"page": int, "lines": [{"y": float, "words": [[x0,x1,text,conf], ...]}]}]`
    in PDF point coordinates.
    """
    rendered = render_pages(pdf_path, dpi=dpi, clean=True)
    if not rendered:
        return {"pages": [], "page_size": (0.0, 0.0)}
    page_size = rendered[0].pdf_size
    out_pages: list[dict[str, Any]] = []
    for pi in rendered:
        try:
            recognized = _recognize(pi.image)
        except Exception as exc:  # noqa: BLE001 — keep the run going on per-page failures
            print(
                f"WARN paddleocr failed on page {pi.page_index + 1}: {exc}",
                file=sys.stderr,
            )
            recognized = []
        word_tuples: list[tuple[float, float, float, float, str, float]] = []
        img_h, img_w = pi.image.shape[:2]
        for box, text, conf in recognized:
            rect = _box_to_rect(box)
            scaled = _scale_to_pdf(rect, (img_w, img_h), pi.pdf_size)
            word_tuples.extend(_split_to_words(scaled, text, conf))
        out_pages.append({"page": pi.page_index + 1, "lines": _cluster_words(word_tuples)})
    return {"pages": out_pages, "page_size": page_size}
