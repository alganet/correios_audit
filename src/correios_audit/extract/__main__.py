"""
Walk the manifest, route each PDF to text or OCR extraction, and write
positional JSON to data/interim/text/<doc_id>.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from correios_audit.extract import router, text

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "data" / "raw" / "manifest.jsonl"
PDFS_DIR = ROOT / "data" / "raw" / "pdfs"
TEXT_DIR = ROOT / "data" / "interim" / "text"
ROUTING_REPORT = ROOT / "data" / "interim" / "extract_routing.json"

# These PDFs have a text layer but extract in chaotic reading order because the
# source uses absolute positioning for visual layout (designed annual-report
# brochures). Force OCR to rebuild a clean text layer.
_FORCE_OCR_DOC_IDS = {
    "2001-fy-df", "2002-fy-df", "2003-fy-df", "2004-fy-df", "2005-fy-df",
    "2006-fy-df", "2007-fy-df", "2008-fy-df", "2009-fy-df",
}


def _read_manifest() -> list[dict]:
    if not MANIFEST.exists():
        return []
    rows = []
    with MANIFEST.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _ocr_paddle(doc_id: str, pdf: Path) -> Path:
    """OCR via PaddleOCR. Imported lazily so missing model weights only
    fail when actually needed."""
    from correios_audit.extract import paddle as paddle_mod

    payload = paddle_mod.extract_pages(pdf)
    return text.write_extracted_from_pages(
        doc_id,
        payload["pages"],
        payload["page_size"],
        TEXT_DIR,
        ocr_engine="paddleocr",
    )


def _ocr_tesseract(doc_id: str, pdf: Path, *, force: bool) -> Path:
    """Legacy OCR via ocrmypdf+tesseract. Retained for A/B testing."""
    from correios_audit.extract import ocr

    OCR_DIR = ROOT / "data" / "interim" / "ocr_pdfs"
    ocr_pdf = OCR_DIR / pdf.name
    missing = ocr.ocr_required_tools()
    if missing:
        raise RuntimeError(f"tesseract OCR engine requires: {missing}")
    if not ocr_pdf.exists() or force:
        ocr.ocr_pdf(pdf, ocr_pdf, force=force)
    return text.write_extracted_text(doc_id, ocr_pdf, TEXT_DIR)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Comma-separated doc_ids")
    parser.add_argument(
        "--ocr-engine",
        choices=["paddleocr", "tesseract"],
        default="paddleocr",
        help="OCR engine for scanned/forced-OCR docs (default: paddleocr).",
    )
    parser.add_argument("--no-ocr", action="store_true",
                        help="Skip docs that need OCR.")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    rows = _read_manifest()
    if args.only:
        wanted = set(args.only.split(","))
        rows = [r for r in rows if r["doc_id"] in wanted]

    n_text = n_ocr = n_skipped = 0
    routing: list[dict] = []
    for r in rows:
        doc_id = r["doc_id"]
        pdf = PDFS_DIR / r["filename"]
        out = TEXT_DIR / f"{doc_id}.json"
        if out.exists() and not args.force:
            print(f"skip {doc_id} (already extracted)", file=sys.stderr)
            continue
        if not pdf.exists():
            print(f"WARN {doc_id}: pdf missing at {pdf}", file=sys.stderr)
            continue
        try:
            force_ocr = doc_id in _FORCE_OCR_DOC_IDS
            density = router.measure_text(pdf)
            decision = "ocr" if (force_ocr or router.needs_ocr(pdf)) else "text"
            routing.append({
                "doc_id": doc_id,
                "decision": decision,
                "force_ocr": force_ocr,
                "ocr_engine": args.ocr_engine if decision == "ocr" else None,
                **density,
            })
            if decision == "ocr":
                if args.no_ocr:
                    print(f"OCR-needed {doc_id}; --no-ocr set, skipping", file=sys.stderr)
                    n_skipped += 1
                    continue
                label = "force-OCR" if force_ocr else "OCR"
                print(f"{label}/{args.ocr_engine}  {doc_id}", file=sys.stderr)
                if args.ocr_engine == "paddleocr":
                    _ocr_paddle(doc_id, pdf)
                else:
                    _ocr_tesseract(doc_id, pdf, force=force_ocr)
                n_ocr += 1
            else:
                print(f"text {doc_id}", file=sys.stderr)
                text.write_extracted_text(doc_id, pdf, TEXT_DIR)
                n_text += 1
        except Exception as exc:
            print(f"FAIL {doc_id}: {exc}", file=sys.stderr)

    if routing:
        ROUTING_REPORT.parent.mkdir(parents=True, exist_ok=True)
        ROUTING_REPORT.write_text(json.dumps(routing, indent=2, ensure_ascii=False))

    print(f"\ntext={n_text} ocr={n_ocr} skipped(ocr-needed)={n_skipped}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
