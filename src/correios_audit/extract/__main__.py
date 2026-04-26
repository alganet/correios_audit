"""
Walk the manifest, route each PDF to text or OCR extraction, and write
positional JSON to data/interim/text/<doc_id>.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from correios_audit.extract import ocr, router, text

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "data" / "raw" / "manifest.jsonl"
PDFS_DIR = ROOT / "data" / "raw" / "pdfs"
OCR_DIR = ROOT / "data" / "interim" / "ocr_pdfs"
TEXT_DIR = ROOT / "data" / "interim" / "text"

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Comma-separated doc_ids")
    parser.add_argument("--no-ocr", action="store_true",
                        help="Skip docs that need OCR (useful when tesseract isn't installed)")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    rows = _read_manifest()
    if args.only:
        wanted = set(args.only.split(","))
        rows = [r for r in rows if r["doc_id"] in wanted]

    missing_ocr_tools = ocr.ocr_required_tools()
    n_text = n_ocr = n_skipped = 0
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
            if force_ocr or router.needs_ocr(pdf):
                if missing_ocr_tools or args.no_ocr:
                    print(f"OCR-needed {doc_id} but tools missing "
                          f"({missing_ocr_tools or 'flag --no-ocr'}); skipping", file=sys.stderr)
                    n_skipped += 1
                    continue
                ocr_pdf = OCR_DIR / r["filename"]
                if not ocr_pdf.exists() or args.force:
                    label = "force-OCR" if force_ocr else "OCR"
                    print(f"{label}  {doc_id}", file=sys.stderr)
                    ocr.ocr_pdf(pdf, ocr_pdf, force=force_ocr)
                text.write_extracted(doc_id, ocr_pdf, TEXT_DIR, method="ocr+text")
                n_ocr += 1
            else:
                print(f"text {doc_id}", file=sys.stderr)
                text.write_extracted(doc_id, pdf, TEXT_DIR, method="text")
                n_text += 1
        except Exception as exc:
            print(f"FAIL {doc_id}: {exc}", file=sys.stderr)

    print(f"\ntext={n_text} ocr={n_ocr} skipped(ocr-needed)={n_skipped}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
