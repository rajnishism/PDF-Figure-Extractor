"""
PyMuPDF-Layout Detector (Tier-0c detector for VisionExtract pipeline)
=====================================================================

Wraps the new pymupdf-layout package (introduced in PyMuPDF 1.24.2+) to detect
document structure blocks like tables, pictures, and captions.

This uses a GNN-based ONNX model to analyze the relationship between text and
image blocks, providing a fast and robust alternative/complement to PaddleOCR.

Output contract:
  {
    "bbox":   (x0_pt, y0_pt, x1_pt, y1_pt),
    "type":   "figure" | "table",
    "source": "pymupdf_layout",
    "label":  str,  # raw label like 'table' or 'picture'
  }
"""

import os
import logging
import warnings

# Suppress some common library warnings
os.environ["PYTHONWARNINGS"] = "ignore"

logger = logging.getLogger(__name__)

_model = None
_import_error = None

def _get_model():
    global _model, _import_error
    if _model is not None:
        return _model
    if _import_error is not None:
        return None
    
    try:
        # Import needs to be specific to avoid clashes
        import fitz
        import pymupdf.layout.DocumentLayoutAnalyzer as dla
        _model = dla.get_model()
        logger.info("[pymupdf-layout] Model loaded successfully")
        return _model
    except Exception as e:
        _import_error = e
        logger.warning(f"[pymupdf-layout] Could not load model: {e}")
        return None

_LABEL_MAP = {
    "table": "table",
    "picture": "figure",
    "figure": "figure",
}

def detect_layout(page) -> list[dict]:
    """
    Run PyMuPDF-Layout analysis on a fitz.Page object.
    
    Returns a list of regions in the standard pipeline format.
    """
    model = _get_model()
    if model is None:
        return []
    
    try:
        # Prediction returns a list of [x0, y0, x1, y1, label]
        results = model.predict(page)
        if not results:
            return []
        
        page_w, page_h = page.rect.width, page.rect.height
        regions = []
        
        for item in results:
            if len(item) < 5:
                continue
            
            x0, y0, x1, y1, raw_label = item
            asset_type = _LABEL_MAP.get(raw_label.lower())
            
            if asset_type is None:
                continue
            
            # Clamp and validate
            x0 = max(0, min(x0, page_w))
            y0 = max(0, min(y0, page_h))
            x1 = max(0, min(x1, page_w))
            y1 = max(0, min(y1, page_h))
            
            if (x1 - x0) < 10 or (y1 - y0) < 10:
                continue
                
            regions.append({
                "bbox": (x0, y0, x1, y1),
                "type": asset_type,
                "source": "pymupdf_layout",
                "label": raw_label,
            })
            
        return regions
    except Exception as e:
        logger.error(f"[pymupdf-layout] Detection failed: {e}")
        return []
