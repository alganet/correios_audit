"""Smoke test for the PaddleOCR extraction wrapper.

Skipped if paddleocr (or its model weights) aren't available — running
the OCR is expensive and depends on a one-time model download. The test
verifies the integration shape: render → recognize → cluster → confidence
fields populated.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.slow
def test_paddle_extraction_smoke(tmp_path):
    paddleocr = pytest.importorskip(
        "paddleocr", reason="paddleocr not installed"
    )
    pymupdf = pytest.importorskip("pymupdf")
    from correios_audit.extract import paddle as paddle_mod

    # Build a tiny one-page PDF with a known string. We render it as a PDF
    # via pymupdf so the OCR path executes (it would route a born-digital
    # PDF to the text extractor instead).
    pdf_path = tmp_path / "tiny.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=120)
    page.insert_text((20, 60), "RECEITA LIQUIDA 1.234.567")
    doc.save(pdf_path)
    doc.close()

    # Force the OCR path explicitly by calling paddle.extract_pages.
    payload = paddle_mod.extract_pages(pdf_path, dpi=200)
    assert payload["pages"], "expected at least one page of OCR output"
    page0 = payload["pages"][0]
    assert page0["lines"], "PaddleOCR returned no lines"
    # Each word must be 4-tuple [x0, x1, text, conf].
    first_word = page0["lines"][0]["words"][0]
    assert len(first_word) == 4
    assert isinstance(first_word[3], float)
    assert 0.0 <= first_word[3] <= 1.0
