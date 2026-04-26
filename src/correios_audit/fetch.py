"""
Download all PDFs in `catalog.DOCS` to `data/raw/pdfs/<sha256>.pdf`.

Plone (the CMS Correios uses) serves many PDFs from URLs without a `.pdf`
extension and via 302 redirects. We follow redirects, sniff the content type,
hash the bytes, and write a manifest line per doc.

Re-runs are idempotent: docs already in the manifest with a matching file are
skipped. To force a refetch, delete the manifest entry (or pass --force).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from correios_audit.catalog import DOCS, Doc

ROOT = Path(__file__).resolve().parents[2]
PDFS_DIR = ROOT / "data" / "raw" / "pdfs"
MANIFEST = ROOT / "data" / "raw" / "manifest.jsonl"

USER_AGENT = (
    "correios-audit/0.1 (financial-disclosure mirror) "
    "httpx"
)
TIMEOUT = httpx.Timeout(30.0, connect=15.0, read=120.0)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_manifest() -> dict[str, dict[str, Any]]:
    if not MANIFEST.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    with MANIFEST.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            out[row["doc_id"]] = row
    return out


def _write_manifest(rows: dict[str, dict[str, Any]]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST.with_suffix(".jsonl.tmp")
    with tmp.open("w") as f:
        for doc_id in sorted(rows):
            f.write(json.dumps(rows[doc_id], ensure_ascii=False) + "\n")
    tmp.replace(MANIFEST)


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    reraise=True,
)
def _download(client: httpx.Client, url: str) -> tuple[bytes, str]:
    resp = client.get(url, follow_redirects=True)
    resp.raise_for_status()
    return resp.content, str(resp.url)


def _is_pdf(data: bytes) -> bool:
    # Real PDFs start with %PDF-, sometimes after a small BOM/whitespace. Be strict.
    return data[:5] == b"%PDF-" or data.lstrip()[:5] == b"%PDF-"


def fetch_doc(client: httpx.Client, doc: Doc, manifest: dict[str, dict[str, Any]],
              *, force: bool = False) -> dict[str, Any]:
    existing = manifest.get(doc.doc_id)
    if existing and not force:
        path = PDFS_DIR / existing["filename"]
        if path.exists():
            return existing

    print(f"fetching {doc.doc_id}: {doc.url}", file=sys.stderr)
    data, final_url = _download(client, doc.url)
    if not _is_pdf(data):
        raise RuntimeError(f"{doc.doc_id}: response is not a PDF (final={final_url})")

    digest = hashlib.sha256(data).hexdigest()
    filename = f"{digest}.pdf"
    PDFS_DIR.mkdir(parents=True, exist_ok=True)
    out = PDFS_DIR / filename
    if not out.exists():
        out.write_bytes(data)

    row = {
        **asdict(doc),
        "final_url": final_url,
        "filename": filename,
        "sha256": digest,
        "bytes": len(data),
    }
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download Correios financial-disclosure PDFs.")
    parser.add_argument("--only", help="Comma-separated doc_ids (default: all)")
    parser.add_argument("--force", action="store_true", help="Refetch even if already present")
    args = parser.parse_args(argv)

    targets = list(DOCS)
    if args.only:
        wanted = set(args.only.split(","))
        targets = [d for d in DOCS if d.doc_id in wanted]
        missing = wanted - {d.doc_id for d in targets}
        if missing:
            parser.error(f"unknown doc_id(s): {sorted(missing)}")

    manifest = _read_manifest()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*;q=0.1"}
    failures: list[tuple[str, str]] = []
    fetched = skipped = 0
    with httpx.Client(headers=headers, timeout=TIMEOUT, follow_redirects=True) as client:
        for doc in targets:
            try:
                row = fetch_doc(client, doc, manifest, force=args.force)
            except Exception as exc:
                print(f"  FAIL {doc.doc_id}: {exc}", file=sys.stderr)
                failures.append((doc.doc_id, str(exc)))
                continue
            existed = manifest.get(doc.doc_id) == row
            manifest[doc.doc_id] = row
            if existed:
                skipped += 1
            else:
                fetched += 1
        _write_manifest(manifest)

    print(f"\nfetched={fetched} skipped={skipped} failed={len(failures)}", file=sys.stderr)
    if failures:
        print("\nfailures:", file=sys.stderr)
        for doc_id, err in failures:
            print(f"  {doc_id}: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
