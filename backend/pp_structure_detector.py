"""
PP-Structure Layout Detector  (Tier-0 detector for VisionExtract pipeline)
============================================================================

Wraps PaddleOCR 3.x's LayoutDetection model (PP-DocLayout) to detect figures,
tables, and images from a rendered PDF page.

Replaces the old PPStructure class (PaddleOCR 2.x) with the new LayoutDetection
API introduced in PaddleOCR 3.x / PaddleX 3.x.

Output contract (matches existing pipeline region dict format):
  {
    "bbox":     (x0_pt, y0_pt, x1_pt, y1_pt),   # in PDF-point space
    "type":     "figure" | "table",
    "source":   "pp_structure",
    "pp_label": str,    # raw label from the model, e.g. "image", "table"
    "pp_score": float,  # model confidence (0–1)
  }

Integration notes:
  - Lazy-loads the LayoutDetection model on first call (~3s startup).
  - Sets PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True to skip slow connectivity
    checks after the model has been cached locally.
  - Falls back gracefully (returns []) if PaddleOCR is unavailable, so the
    existing PyMuPDF + OpenCV pipeline continues to work unmodified.
  - Coordinates returned are in PDF point space, computed from pixel coords
    using the zoom factor used to render the page image.
"""

from __future__ import annotations
import os
import warnings
import logging

# Suppress PaddlePaddle's verbose environment warnings and logs
os.environ["PADDLE_SDK_LOG_LEVEL"] = "3"
os.environ["FLAGS_allocator_strategy"] = "naive_best_fit"
# This specifically helps with the 'ccache' warning in some environments
os.environ["PYTHONWARNINGS"] = "ignore::UserWarning:paddle.utils.cpp_extension.extension_utils"

logger = logging.getLogger(__name__)

# Skip the slow internet connectivity check (models are cached after first download)
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

# ── Lazy singleton ────────────────────────────────────────────────────────────

_engine = None           # type: ignore
_import_error: Exception | None = None


def _get_engine():
    """
    Initialise PaddleOCR 3.x LayoutDetection engine once; cache for reuse.
    Uses the PP-DocLayout_plus-L model (automatically downloaded on first run).
    """
    global _engine, _import_error

    if _engine is not None:
        return _engine
    if _import_error is not None:
        return None

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from paddleocr import LayoutDetection   # type: ignore

        _engine = LayoutDetection()
        logger.info("[pp-structure] LayoutDetection engine loaded successfully")
        return _engine

    except Exception as exc:
        _import_error = exc
        logger.warning(
            "[pp-structure] Could not load LayoutDetection engine — "
            f"running without PP-Structure. Reason: {exc}"
        )
        return None


# ── Label mapping ──────────────────────────────────────────────────────────────

# Map PP-DocLayout label strings → our internal asset types.
# Labels not in this map are text blocks, headers, etc. — ignored.
_LABEL_MAP: dict[str, str] = {
    "figure":  "figure",
    "image":   "figure",    # PP-DocLayout uses "image" for embedded pictures
    "chart":   "figure",
    "diagram": "figure",
    "table":   "table",
}

# Minimum model confidence to accept a detection
_MIN_SCORE = 0.40


# ── Public API ─────────────────────────────────────────────────────────────────

def detect_layout(img_rgb, zoom: float, page_w: float, page_h: float) -> list[dict]:
    """
    Run PP-DocLayout detection on a rendered PDF page image.

    Parameters
    ----------
    img_rgb : np.ndarray
        RGB image array (H×W×3) rendered from the PDF page at `zoom` scale.
    zoom : float
        Scale factor used to render the page (e.g. 2.0 = 2× PDF points per pixel).
        Used to invert pixel → PDF-point coordinate mapping.
    page_w, page_h : float
        PDF page dimensions in points (for coordinate clamping).

    Returns
    -------
    list[dict]
        Region dicts in the pipeline's standard format.
        Empty list on failure or if engine is unavailable.
    """
    engine = _get_engine()
    if engine is None:
        return []

    try:
        import cv2

        # LayoutDetection expects BGR
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = list(engine.predict(img_bgr))

        if not results:
            return []

        # Each call produces one DetResult dict per image
        det_result = results[0]
        boxes = det_result.get("boxes", [])

        regions: list[dict] = []

        for box in boxes:
            label = str(box.get("label", "")).lower().strip()
            asset_type = _LABEL_MAP.get(label)
            if asset_type is None:
                continue   # text, title, list, formula, etc. — skip

            score = float(box.get("score", 0.0))
            if score < _MIN_SCORE:
                continue

            # coordinate is [x0, y0, x1, y1] in pixel space
            coord = box.get("coordinate", [])
            if len(coord) < 4:
                continue

            px0, py0, px1, py1 = float(coord[0]), float(coord[1]), float(coord[2]), float(coord[3])

            # Convert pixel → PDF point space
            x0 = px0 / zoom
            y0 = py0 / zoom
            x1 = px1 / zoom
            y1 = py1 / zoom

            # Clamp to page bounds
            x0 = max(0.0, min(x0, page_w))
            y0 = max(0.0, min(y0, page_h))
            x1 = max(0.0, min(x1, page_w))
            y1 = max(0.0, min(y1, page_h))

            w, h = x1 - x0, y1 - y0
            if w < 20 or h < 20:    # skip degenerate micro-boxes
                continue

            regions.append({
                "bbox":      (x0, y0, x1, y1),
                "type":      asset_type,
                "source":    "pp_structure",
                "pp_label":  label,
                "pp_score":  round(score, 3),
            })

            logger.debug(
                f"[pp-structure] {label} ({score:.2f}) @ "
                f"({x0:.0f},{y0:.0f})–({x1:.0f},{y1:.0f})"
            )

        return regions

    except Exception as exc:
        logger.warning(f"[pp-structure] Detection failed: {exc}")
        return []
