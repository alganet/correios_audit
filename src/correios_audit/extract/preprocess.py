"""
Page rasterization + image cleanup for OCR.

Brochure-era Correios PDFs (2001-2009) are scanned at moderate resolution with
mild skew, scanner noise, and bleed-through. We rasterize at 400 DPI, deskew
via the longest-line angle in a Hough transform, binarize with Otsu, and
denoise with a small median filter. Output is a uint8 grayscale numpy array
ready for the recognizer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pymupdf

DEFAULT_DPI = 400


@dataclass(frozen=True)
class PageImage:
    page_index: int       # 0-based
    image: np.ndarray     # grayscale uint8, H x W
    pdf_size: tuple[float, float]  # original PDF point size (W, H)
    dpi: int


def _to_grayscale(pix: pymupdf.Pixmap) -> np.ndarray:
    """pymupdf Pixmap → numpy grayscale uint8."""
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 1:
        gray = arr.squeeze(-1)
    elif pix.n in (3, 4):
        bgr = arr[:, :, :3][:, :, ::-1]   # RGB → BGR for cv2
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = arr.mean(axis=-1).astype(np.uint8)
    return gray


def _deskew(gray: np.ndarray, max_angle_deg: float = 5.0) -> np.ndarray:
    """Estimate skew via the dominant Hough line angle, then rotate.

    Bounded to ±max_angle_deg — we don't want to rotate genuinely-rotated
    landscape pages (those are handled separately by the page-rotation step).
    """
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 720,    # 0.25-degree resolution
        threshold=200,
        minLineLength=gray.shape[1] // 4,
        maxLineGap=20,
    )
    if lines is None or len(lines) == 0:
        return gray
    angles: list[float] = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if x2 == x1:
            continue
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        # Only near-horizontal lines (within 30 deg) inform the skew estimate.
        if abs(angle) <= 30:
            angles.append(angle)
    if not angles:
        return gray
    skew = float(np.median(angles))
    if abs(skew) < 0.1 or abs(skew) > max_angle_deg:
        return gray
    h, w = gray.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), skew, 1.0)
    return cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def _binarize_and_denoise(gray: np.ndarray) -> np.ndarray:
    """Otsu binarize, then a 3x3 median to wipe pepper noise. Returns uint8
    grayscale (0/255) so PaddleOCR's preprocessing still works."""
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw = cv2.medianBlur(bw, 3)
    return bw


def render_pages(pdf_path: Path, *, dpi: int = DEFAULT_DPI,
                 clean: bool = True) -> list[PageImage]:
    """Rasterize each page of the PDF to a clean uint8 grayscale image."""
    out: list[PageImage] = []
    with pymupdf.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csGRAY)
            gray = _to_grayscale(pix)
            if clean:
                gray = _deskew(gray)
                gray = _binarize_and_denoise(gray)
            out.append(
                PageImage(
                    page_index=i,
                    image=gray,
                    pdf_size=(page.rect.width, page.rect.height),
                    dpi=dpi,
                )
            )
    return out
