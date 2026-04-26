"""
OCR pipeline for scanned PDFs.

We use ocrmypdf, which wraps tesseract and produces a new PDF with a text layer
(idempotent: re-runs are no-ops; --skip-text guards already-OCR'd pages).
After OCR, the same `extract.text` pipeline ingests the output.

Requires system packages: tesseract-ocr, tesseract-ocr-por, ghostscript.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def ocr_required_tools() -> list[str]:
    """Return missing required system tools, empty list if all are present."""
    required = ["tesseract", "gs"]
    return [t for t in required if shutil.which(t) is None]


def ocr_pdf(in_path: Path, out_path: Path, *, force: bool = False) -> None:
    """OCR a PDF, writing a text-layered copy to out_path.

    `force=True`: replace any existing text layer. Useful for brochure-style
    PDFs (2001-2009 Correios annuals) where the existing text layer extracts
    in chaotic order.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ocrmypdf",
        "--language", "por",
        "--deskew",
        "--clean",
        "--clean-final",
        "--rotate-pages",
        "--rotate-pages-threshold", "5",
        "--output-type", "pdf",
        "--optimize", "0",
        "--quiet",
    ]
    if force:
        cmd.append("--force-ocr")
    else:
        cmd.append("--skip-text")
    cmd.extend([str(in_path), str(out_path)])
    subprocess.run(cmd, check=True)
