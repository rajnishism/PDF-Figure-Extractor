"""
PDF Visual Extraction Processor — Hybrid Pipeline v2
=====================================================

Architecture
------------
Stage 1 — PDF Object Scan (fast, catches clean embedded images)
Stage 2 — Render + CV Region Detection (catches vector diagrams, flowcharts)
Stage 3 — Deduplication via Perceptual Hashing (removes logos / repeated headers)
Stage 4 — Positional Margin Filtering (removes header/footer objects)
Stage 5 — Scored Caption Association (distance + alignment + font pattern)
Stage 6 — Confidence Scoring (quality signal per detection)
Stage 7 — Extraction (high-res page clip → PNG)

Why Hybrid?
  - PDF object model alone misses composite vector diagrams
  - CV region detection alone produces noisy fragments
  - Both together with cross-validation gives the best recall + precision
"""

import os
import re
import uuid
import zipfile
import hashlib
from collections import defaultdict
from typing import Optional

import fitz            # PyMuPDF
import cv2
import numpy as np
from PIL import Image
import imagehash


# ── Tunables ───────────────────────────────────────────────────────────────────

MARGIN_TOP    = 55   # points — ignore objects whose top edge is above this
MARGIN_BOTTOM = 55   # points — ignore objects whose bottom edge is below (page_h - this)
MIN_AREA_PTS  = 30   # minimum width AND height in PDF points
HASH_THRESHOLD = 8   # phash hamming distance to consider two images "the same"
LOGO_PAGE_PCT  = 0.60  # if image appears on ≥60% of pages → treat as logo/watermark
CAPTION_SEARCH_DIST = 60   # points above/below image to scan for captions
CV_MIN_AREA    = 5000   # minimum pixel area for CV-detected regions (at 2x zoom)
CV_MERGE_GAP   = 18     # pixels — merge nearby rectangles within this gap

# Matches all common caption variants:
#   Figure 1   Fig. 1   Table No. 2   Fig No.3   Table #4   Exhibit 1.2
CAPTION_RE = re.compile(
    r"(Figure|Fig\.?|Plate|Table|Map|Chart|Diagram|Exhibit|Appendix)"
    r"\s*(?:No\.?|Number|#)?\s*\.?\s*(\d+[\.-]?\d*)",
    re.IGNORECASE,
)

# Maximum fraction of a region's area that can be covered by text blocks
# before we decide it's a paragraph, not a visual element (for CV regions).
# Lower = stricter (bordered text blocks are now correctly dropped).
MAX_TEXT_COVERAGE_CV  = 0.30
# Caption-only regions: if height < this many points AND content is all text → skip
MIN_VISUAL_HEIGHT_PTS = 40
# Hard limit: a caption further than this many PDF-pts from the figure edge
# is treated as unrelated body text, not a caption. (~2 lines of 11pt text ≈ 30pt;
# 150pt = ~5cm which is generous enough for any real document layout).
MAX_CAPTION_DISTANCE_PTS   = 150   # above captions (primary)
MAX_CAPTION_DISTANCE_BELOW =  80   # below captions (fallback, tighter)


# ── Main Processor Class ───────────────────────────────────────────────────────

class PDFProcessor:

    def __init__(self, upload_dir: str, assets_dir: str):
        self.upload_dir = upload_dir
        self.assets_dir = assets_dir
        # Persisted across calls for the same session: hash → page_count
        # Structure: {session_id: {phash_str: set_of_page_nos}}
        self._hash_registry: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_total_pages(self, file_path: str) -> int:
        doc = fitz.open(file_path)
        n = doc.page_count
        doc.close()
        return n

    def process_page(self, file_path: str, session_id: str, page_no: int) -> dict:
        """
        Full hybrid pipeline for a single page.
        Returns {detections, width, height}.
        """
        doc = fitz.open(file_path)
        page = doc.load_page(page_no - 1)
        page_w = page.rect.width
        page_h = page.rect.height

        # ── Stage 1: render page at 2× for CV analysis ─────────────────────
        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)

        # ── Stage 2: collect candidate regions from ALL three detectors ──────
        # Priority: table_detect (vector lines) > pdf_object > cv_region
        pdf_regions   = self._pdf_object_regions(page, page_no)
        table_regions = self._table_regions(page)               # NEW: PyMuPDF grid analysis
        cv_regions    = self._cv_region_detection(img_np, zoom, page_w, page_h)
        all_regions   = self._merge_region_lists(table_regions, pdf_regions, cv_regions, page_w, page_h)

        # ── Stage 3 & 4: positional + text-coverage filter ───────────────
        filtered = self._apply_position_filter(all_regions, page_w, page_h)
        filtered = self._apply_text_coverage_filter(filtered, page)

        # ── Stage 5b: drop caption-only regions before association ─────────
        filtered = self._drop_caption_only_regions(filtered, page)

        # ── Stage 5: multi-signal page-wide caption association ───────────
        # One full-page text scan → scoring matrix → greedy assignment.
        # Ensures every caption is matched to at most one figure.
        filtered = self._associate_captions_to_figures(filtered, page)

        # ── Stage 6: extract images + perceptual hash filter ─────────────
        detections = []
        for region in filtered:
            asset_id   = f"p{page_no}_{uuid.uuid4().hex[:8]}"
            image_path = self._extract_asset(page, region["bbox"], session_id, asset_id)

            if image_path is None:
                continue

            # Perceptual hash
            phash = self._compute_phash(image_path)
            if phash:
                self._hash_registry[session_id][phash].add(page_no)

            region["id"]         = asset_id
            region["image_url"]  = f"/assets/{os.path.basename(image_path)}"
            region["page"]       = page_no
            region["phash"]      = phash
            region["confidence"] = self._compute_confidence(region, page_h)
            detections.append(region)

        # ── Stage 7: deduplicate logos using hash registry ────────────────
        total_pages = doc.page_count
        detections  = self._filter_repeated_images(detections, session_id, total_pages)

        doc.close()
        return {"detections": detections, "width": page_w, "height": page_h}

    def create_page_zip(self, session_id: str, page_no: int) -> str:
        """Legacy single-page zip (kept for API compatibility)."""
        zip_filename = f"session_{session_id}_page_{page_no}.zip"
        zip_path = os.path.join(self.assets_dir, zip_filename)
        prefix = f"p{page_no}_"
        assets = [f for f in os.listdir(self.assets_dir)
                  if f.startswith(prefix) and f.endswith(".png")]
        with zipfile.ZipFile(zip_path, "w") as zf:
            for asset in assets:
                zf.write(os.path.join(self.assets_dir, asset), arcname=asset)
        return zip_path

    # ── Stage 1: PDF Object Regions ────────────────────────────────────────────

    def _pdf_object_regions(self, page: fitz.Page, page_no: int) -> list[dict]:
        """
        Use the PDF's internal image object table.
        Fast and accurate for clean embedded rasters.
        """
        regions = []
        seen_bboxes: list[tuple] = []

        for i, img in enumerate(page.get_image_info(xrefs=True)):
            bbox = img.get("bbox") or img.get("rect")
            if bbox is None:
                continue
            x0, y0, x1, y1 = bbox
            w, h = x1 - x0, y1 - y0

            if w < MIN_AREA_PTS or h < MIN_AREA_PTS:
                continue

            # Skip near-identical bboxes (same image placed twice)
            if any(self._iou((x0, y0, x1, y1), sb) > 0.85 for sb in seen_bboxes):
                continue
            seen_bboxes.append((x0, y0, x1, y1))

            regions.append({
                "bbox":   (x0, y0, x1, y1),
                "type":   "figure",
                "source": "pdf_object",
            })

        return regions

    # ── Stage 1.5: Table Detection via PyMuPDF vector-line analysis ────────────

    def _table_regions(self, page: fitz.Page) -> list[dict]:
        """
        Use PyMuPDF's built-in find_tables() to detect tables from vector drawing
        commands (horizontal & vertical rules forming a grid). This is far more
        reliable than CV edge detection for tables because:
          • It reads the PDF's actual line-drawing primitives
          • No dilation/merging artifacts
          • Tables with text-dense cells that would fail the text-coverage filter
            are correctly identified here without relying on CV at all

        Requires PyMuPDF ≥ 1.23.0.  Gracefully falls back to empty list on
        older versions or if the page has no detectable grid structure.
        """
        regions = []
        try:
            tab_finder = page.find_tables()   # TableFinder object
            for tab in tab_finder.tables:
                x0, y0, x1, y1 = tab.bbox
                w, h = x1 - x0, y1 - y0

                # Skip degenerate bboxes
                if w < MIN_AREA_PTS or h < MIN_AREA_PTS:
                    continue

                # Require at least a 2×2 grid (otherwise it's just a ruled line)
                if getattr(tab, "col_count", 1) < 2 or getattr(tab, "row_count", 1) < 2:
                    continue

                regions.append({
                    "bbox":      (x0, y0, x1, y1),
                    "type":      "table",
                    "source":    "table_detect",
                    "row_count": getattr(tab, "row_count", None),
                    "col_count": getattr(tab, "col_count", None),
                })
                print(
                    f"[table-detect] Found {getattr(tab, 'row_count', '?')}×"
                    f"{getattr(tab, 'col_count', '?')} table at "
                    f"({x0:.0f},{y0:.0f})–({x1:.0f},{y1:.0f})"
                )
        except AttributeError:
            pass   # PyMuPDF < 1.23 — find_tables() not available
        except Exception as e:
            print(f"[table-detect] Error on page: {e}")

        return regions


    def _cv_region_detection(self, img: np.ndarray, zoom: float,
                              page_w: float, page_h: float) -> list[dict]:
        """
        Render-based detection using edge detection + morphological grouping.
        Catches vector diagrams, flowcharts, and composite figures that are
        NOT stored as single image XObjects in the PDF.
        """
        gray  = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        # Edges — conservative threshold to avoid over-detecting text strokes
        edges = cv2.Canny(gray, 60, 180)
        # Dilate to bridge nearby strokes (e.g. arrows between boxes).
        # iterations=1 prevents text lines above/below a table from merging
        # into one giant contour that spans the whole content area.
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (int(CV_MERGE_GAP), int(CV_MERGE_GAP))
        )
        dilated = cv2.dilate(edges, kernel, iterations=1)
        # Find external contours
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        regions = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < CV_MIN_AREA:
                continue
            cx, cy, cw, ch = cv2.boundingRect(cnt)
            # Convert pixel coords back to PDF point space
            x0_pt = cx / zoom
            y0_pt = cy / zoom
            x1_pt = (cx + cw) / zoom
            y1_pt = (cy + ch) / zoom
            # Skip thin lines / text rows
            ar = cw / ch if ch > 0 else 1
            if ar > 20 or ar < 0.05:
                continue
            if cw < MIN_AREA_PTS or ch < MIN_AREA_PTS:
                continue

            regions.append({
                "bbox":   (x0_pt, y0_pt, x1_pt, y1_pt),
                "type":   "figure",
                "source": "cv_region",
            })

        return regions

    # ── Merge table + PDF object + CV regions ─────────────────────────────────

    def _merge_region_lists(
        self,
        table_regions: list,
        pdf_regions:   list,
        cv_regions:    list,
        page_w: float,
        page_h: float,
    ) -> list[dict]:
        """
        Three-tier merge with strict priority:

          Tier 1 – table_detect (PyMuPDF vector-line grid analysis)
            Highest confidence. Added unconditionally.

          Tier 2 – pdf_object (embedded image XObjects)
            High confidence. Added if it doesn't substantially
            overlap a Tier 1 region (IoU > 0.4).

          Tier 3 – cv_region (render-based contour detection)
            Lowest confidence — catches vector diagrams not in Tiers 1/2.
            Added only if IoU < 0.3 with anything already accepted.
        """
        merged: list[dict] = []

        # ─ Tier 1: table detections (authoritative) ─
        for r in table_regions:
            merged.append(r)

        existing = [r["bbox"] for r in merged]

        # ─ Tier 2: PDF image objects ─
        for r in pdf_regions:
            if not any(self._iou(r["bbox"], eb) > 0.4 for eb in existing):
                merged.append(r)
                existing.append(r["bbox"])

        # ─ Tier 3: CV regions (fill gaps for vector diagrams) ─
        for r in cv_regions:
            if not any(self._iou(r["bbox"], eb) > 0.3 for eb in existing):
                merged.append(r)
                existing.append(r["bbox"])

        return merged

    # ── Stage 3 & 4: Positional + Text-Coverage Filters ──────────────────────

    def _apply_position_filter(
        self, regions: list[dict], page_w: float, page_h: float
    ) -> list[dict]:
        """
        Remove objects sitting in the top/bottom margins
        (likely headers, footers, page numbers, logos).
        Also drops any region whose area exceeds PAGE_MAX_AREA_FRAC of the
        actual page area — computed from the real page width/height, not an
        A4 hardcode, so landscape, letter, legal, and custom sizes all work.
        """
        PAGE_MAX_AREA_FRAC = 0.90   # fraction of page area above which → drop
        page_area = page_w * page_h  # exact, from PyMuPDF page.rect

        keep = []
        for r in regions:
            x0, y0, x1, y1 = r["bbox"]

            # ─ Margin guard: must sit inside top/bottom content bands ─
            if y0 < MARGIN_TOP or y1 > (page_h - MARGIN_BOTTOM):
                continue

            # ─ Size guard: reject whole-page / nearly-whole-page captures ─
            region_area = (x1 - x0) * (y1 - y0)
            if region_area > PAGE_MAX_AREA_FRAC * page_area:
                print(
                    f"[size-filter] Dropping oversized region "
                    f"{region_area:.0f}pt² ({region_area/page_area:.0%} of "
                    f"{page_w:.0f}×{page_h:.0f}pt page)"
                )
                continue

            keep.append(r)
        return keep

    def _compute_text_coverage(self, page: fitz.Page, bbox: tuple) -> float:
        """
        Return the fraction of bbox area that is covered by text blocks.
        Pure text paragraphs → high coverage. Images/diagrams → low coverage.
        """
        x0, y0, x1, y1 = bbox
        bbox_area = (x1 - x0) * (y1 - y0)
        if bbox_area <= 0:
            return 0.0

        rect = fitz.Rect(x0, y0, x1, y1)
        text_area = 0.0
        for block in page.get_text("blocks", clip=rect):
            btype = block[6]   # 0=text, 1=image
            if btype != 0:
                continue
            bx0, by0, bx1, by1 = block[:4]
            # Intersection with our query rect
            ix0, iy0 = max(x0, bx0), max(y0, by0)
            ix1, iy1 = min(x1, bx1), min(y1, by1)
            if ix1 > ix0 and iy1 > iy0:
                text_area += (ix1 - ix0) * (iy1 - iy0)

        return text_area / bbox_area

    def _apply_text_coverage_filter(self, regions: list[dict],
                                    page: fitz.Page) -> list[dict]:
        """
        For CV-sourced regions only: if ≥ MAX_TEXT_COVERAGE_CV of the region
        is covered by text blocks, it's a paragraph — drop it.
        PDF-object regions pass through unconditionally (the PDF itself said
        there's an image XObject there).
        """
        keep = []
        for r in regions:
            # ─ Trust the PDF's own image object table and the table detector ─
            # table_detect regions are inherently text-dense (cell content) and
            # would be wrongly rejected by the text-coverage gate.
            if r.get("source") in ("pdf_object", "table_detect"):
                keep.append(r)
                continue
            coverage = self._compute_text_coverage(page, r["bbox"])
            if coverage >= MAX_TEXT_COVERAGE_CV:
                print(f"[text-filter] Dropping region with {coverage:.0%} text coverage")
                continue
            keep.append(r)
        return keep

    def _drop_caption_only_regions(self, regions: list[dict],
                                   page: fitz.Page) -> list[dict]:
        """
        Bug-fix #3: A caption line (e.g. 'Table No. 2 Summary…') near the
        bottom of a page produces edges → CV contour → false detection.
        Symptoms of a caption-only region:
          • Very short height (< MIN_VISUAL_HEIGHT_PTS)
          • The text inside it matches a caption pattern
          • It comes from CV (not a real image XObject)
        """
        keep = []
        for r in regions:
            if r.get("source") == "pdf_object":
                keep.append(r)
                continue
            x0, y0, x1, y1 = r["bbox"]
            h = y1 - y0
            if h < MIN_VISUAL_HEIGHT_PTS:
                # Narrow region — check whether it's entirely a caption label
                rect = fitz.Rect(x0, y0, x1, y1)
                text = page.get_text("text", clip=rect).strip()
                if text and CAPTION_RE.search(text):
                    print(f"[caption-filter] Dropping caption-only region: {text[:60]!r}")
                    continue  # it's just a label, not an image
            keep.append(r)
        return keep

    # ── Stage 5: Multi-Signal Caption Association ─────────────────────────────
    #
    # Architecture:
    #   1. Full-page scan  → CaptionCandidate inventory (ALL text blocks, one pass)
    #   2. Scoring matrix  → for every (figure, caption) pair, compute 7 signals
    #   3. Global assignment → greedy bipartite match, one caption per figure max
    #
    # Signals scored:
    #   S1  Caption regex match           (strongest: +4.0)
    #   S2  Vertical distance decay       (exponential falloff)
    #   S3  Direction preference          (below > above)
    #   S4  Horizontal centre alignment   (caption cx ≈ figure cx)
    #   S5  Width proportion match        (caption width ≈ figure width)
    #   S6  Typographic signals           (italic, small font)
    #   S7  No-intervening-element check  (heavy penalty if another image is between)

    def _build_page_caption_inventory(self, page: fitz.Page) -> list[dict]:
        """
        Single full-page text extraction pass.
        Builds candidate caption objects with full typographic metadata.
        Merges multi-line blocks into one candidate each.
        Casts a WIDE net — filtering happens in the scorer.
        """
        candidates = []
        body_sizes: list[float] = []

        # First pass: collect ALL span font sizes to estimate body font size
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    s = span.get("size", 0)
                    if s > 0:
                        body_sizes.append(s)

        # Median body font size (robust to outliers)
        if body_sizes:
            body_sizes_sorted = sorted(body_sizes)
            n = len(body_sizes_sorted)
            median_size = body_sizes_sorted[n // 2]
        else:
            median_size = 11.0

        # Second pass: build candidates
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue

            lines = block.get("lines", [])
            if not lines:
                continue

            # Merge all lines in the block into one text string
            all_spans: list[dict] = []
            line_texts: list[str] = []
            for line in lines:
                spans = line.get("spans", [])
                line_texts.append(" ".join(sp.get("text", "") for sp in spans).strip())
                all_spans.extend(spans)

            block_text = " ".join(t for t in line_texts if t).strip()
            if not block_text:
                continue

            # Typographic metadata
            sizes   = [sp.get("size", median_size) for sp in all_spans]
            avg_sz  = sum(sizes) / len(sizes) if sizes else median_size
            has_italic = any(sp.get("flags", 0) & 2 for sp in all_spans)
            has_bold   = any(sp.get("flags", 0) & 4 for sp in all_spans)
            is_smaller = avg_sz < (median_size - 0.5)   # smaller than body text

            # Regex match on the FULL block text (catches multi-line captions)
            match = CAPTION_RE.search(block_text)

            bx0, by0, bx1, by1 = block["bbox"]

            candidates.append({
                "bbox":       (bx0, by0, bx1, by1),
                "text":       block_text[:300],
                "match":      match,
                "avg_size":   avg_sz,
                "is_smaller": is_smaller,
                "has_italic": has_italic,
                "has_bold":   has_bold,
                "width":      bx1 - bx0,
                "center_x":  (bx0 + bx1) / 2,
            })

        return candidates

    def _score_caption_for_figure(
        self,
        cap: dict,
        fig_bbox: tuple,
        all_visual_bboxes: list[tuple],
    ) -> tuple[float, str | None]:
        """
        Score how likely 'cap' is the caption for the figure at 'fig_bbox'.
        Returns (score, position) where position is 'above' | 'below' | None.

        Priority:
          ABOVE captions → primary (full score, 150pt cap)
          BELOW captions → fallback (-2.0 penalty, tighter 80pt cap)
                           Wins only when nothing above is available.
        """
        x0, y0, x1, y1 = fig_bbox
        fig_cx    = (x0 + x1) / 2
        fig_width = max(x1 - x0, 1)

        cx0, cy0, cx1, cy1 = cap["bbox"]
        cap_cx = cap["center_x"]

        score = 0.0
        position: str | None = None

        # ── S1: Caption regex match (required gate) ─────────────────────
        if cap["match"]:
            score += 4.0
        else:
            return -999.0, None   # no regex match — hard fail

        # ── S2: Vertical distance + direction ─────────────────────────
        if cy1 <= y0:              # caption is ABOVE the figure (primary)
            vert_dist = y0 - cy1
            position  = "above"
            if vert_dist > MAX_CAPTION_DISTANCE_PTS:
                return -999.0, None

        elif cy0 >= y1:            # caption is BELOW the figure (fallback)
            vert_dist = cy0 - y1
            position  = "below"
            if vert_dist > MAX_CAPTION_DISTANCE_BELOW:
                return -999.0, None   # tighter cap for below
            score -= 2.0             # directional penalty — only wins if nothing above

        else:                      # overlapping — penalise
            vert_dist = 0
            score -= 1.5

        # Distance decay: closer caption → higher score.
        if vert_dist <= 0:
            score += 2.0
        elif vert_dist < 20:
            score += 1.8
        elif vert_dist < 50:
            score += 1.4
        elif vert_dist < 100:
            score += 0.8
        else:
            score += 0.2   # within cap but far — plausible

        # ── S4: Horizontal centre alignment ─────────────────────────────
        cx_diff = abs(fig_cx - cap_cx)
        if cx_diff < 15:
            score += 1.5
        elif cx_diff < 40:
            score += 1.0
        elif cx_diff < 80:
            score += 0.5
        else:
            score -= 0.3

        # ── S5: Width proportion ────────────────────────────────────
        w_ratio = cap["width"] / fig_width
        if 0.4 <= w_ratio <= 1.4:
            score += 0.8
        elif w_ratio > 1.4:
            score += 0.2
        else:
            score -= 0.3

        # ── S6: Typographic signals ──────────────────────────────────
        if cap["has_italic"]:
            score += 0.5
        if cap["is_smaller"]:
            score += 0.4

        # ── S7: No-intervening-element ──────────────────────────────
        # If another visual region sits between this caption and the figure,
        # it's almost certainly the NEXT figure's title — penalise heavily.
        # This is the key guard for "two tables stacked" scenarios:
        #   Table A bottom → [caption of Table B] → Table B top
        # The caption midpoint falls between Table A mid and Table B mid,
        # so when scoring caption→Table A, Table B is "between" them → -2.5.
        cap_mid = (cy0 + cy1) / 2
        fig_mid = (y0 + y1) / 2
        y_lo, y_hi = min(cap_mid, fig_mid), max(cap_mid, fig_mid)

        for ob in all_visual_bboxes:
            if ob == fig_bbox:
                continue
            ox0, oy0, ox1, oy1 = ob
            o_mid = (oy0 + oy1) / 2
            if y_lo < o_mid < y_hi:
                h_overlap = min(ox1, max(x1, cx1)) - max(ox0, min(x0, cx0))
                if h_overlap > 20:
                    score -= 2.5   # heavy penalty

        return score, position

    def _associate_captions_to_figures(
        self, regions: list[dict], page: fitz.Page
    ) -> list[dict]:
        """
        Page-wide greedy bipartite assignment.

        Steps:
          1. Build full caption inventory (one page scan)
          2. Build N×M score matrix (figures × captions)
          3. Greedy: pick highest-score unassigned (figure, caption) pair
          4. Threshold: only assign when score ≥ 3.5
             (needs regex match + above-caption proximity, OR regex match +
              below-caption proximity but below must overcome -2.0 penalty
              → so below captions need score ≥ 3.5 too, meaning they must be
              very close and well-aligned to win at all)
        """
        ASSIGNMENT_THRESHOLD = 3.5

        # Initialise all figures with no caption
        for r in regions:
            r["figure_no"] = None
            r["caption"]   = None

        if not regions:
            return regions

        caps = self._build_page_caption_inventory(page)
        if not caps:
            return regions

        all_visual_bboxes = [r["bbox"] for r in regions]

        # Build N×M matrix — now stores (score, position) tuples
        matrix: list[list[tuple[float, str | None]]] = [
            [
                self._score_caption_for_figure(cap, fig["bbox"], all_visual_bboxes)
                for cap in caps
            ]
            for fig in regions
        ]

        assigned_caps: set[int] = set()
        assigned_figs: set[int] = set()

        # Flatten all (score, fig_idx, cap_idx, position) and sort descending
        pairs = [
            (matrix[fi][ci][0], fi, ci, matrix[fi][ci][1])
            for fi in range(len(regions))
            for ci in range(len(caps))
        ]
        pairs.sort(key=lambda t: t[0], reverse=True)

        for score, fi, ci, position in pairs:
            if score < ASSIGNMENT_THRESHOLD:
                break   # pairs are sorted; everything below is worse
            if fi in assigned_figs or ci in assigned_caps:
                continue

            cap = caps[ci]
            m   = cap["match"]
            regions[fi]["figure_no"] = f"{m.group(1)} {m.group(2)}" if m else None
            regions[fi]["caption"]   = cap["text"]

            # ── Expand bbox to include caption in screenshot ────────────────
            # Rule: only absorb the caption's own text block, never pull in
            # surrounding paragraphs.  We clamp to at most CAP_ABSORB_MAX pts
            # of expansion from the figure edge in the caption's direction.
            CAP_PAD        = 5    # padding around the merged area
            CAP_ABSORB_MAX = 80   # max pt we expand toward the caption

            fx0, fy0, fx1, fy1 = regions[fi]["bbox"]
            cx0, cy0, cx1, cy1 = cap["bbox"]
            cap_height = cy1 - cy0

            if cy1 <= fy0:          # caption is ABOVE the figure
                # Only pull ny0 up by at most the caption's own height + gap + pad
                allowed_up = cap_height + (fy0 - cy1) + CAP_PAD
                allowed_up = min(allowed_up, CAP_ABSORB_MAX)
                ny0 = max(cy0 - CAP_PAD, fy0 - allowed_up)
                ny1 = fy1 + CAP_PAD
            elif cy0 >= fy1:        # caption is BELOW the figure
                allowed_dn = cap_height + (cy0 - fy1) + CAP_PAD
                allowed_dn = min(allowed_dn, CAP_ABSORB_MAX)
                ny0 = fy0 - CAP_PAD
                ny1 = min(cy1 + CAP_PAD, fy1 + allowed_dn)
            else:                   # overlapping — leave as-is
                ny0, ny1 = fy0 - CAP_PAD, fy1 + CAP_PAD

            nx0 = min(fx0, cx0) - CAP_PAD
            nx1 = max(fx1, cx1) + CAP_PAD
            regions[fi]["bbox"] = (nx0, ny0, nx1, ny1)

            assigned_figs.add(fi)
            assigned_caps.add(ci)
            regions[fi]["caption_position"] = position   # 'above' | 'below'

        return regions


    def _compute_phash(self, image_path: str) -> Optional[str]:
        try:
            img = Image.open(image_path).convert("RGB")
            return str(imagehash.phash(img))
        except Exception:
            return None

    def _filter_repeated_images(self, detections: list, session_id: str,
                                 total_pages: int) -> list:
        """
        Remove any detection whose perceptual hash has appeared on ≥ LOGO_PAGE_PCT
        of the document's pages.  Works across calls (hashes accumulate in memory).
        Only applies when we have a meaningful number of pages.
        """
        if total_pages < 3:
            return detections   # Too few pages to make a reliable determination

        threshold_pages = max(2, int(total_pages * LOGO_PAGE_PCT))
        registry = self._hash_registry[session_id]

        kept = []
        for det in detections:
            phash = det.get("phash")
            if phash and len(registry.get(phash, set())) >= threshold_pages:
                print(f"[filter] Dropping repeated image (hash={phash}, "
                      f"pages={registry[phash]})")
                # Remove the file too
                fpath = os.path.join(os.getcwd(), det["image_url"].lstrip("/"))
                try:
                    os.remove(fpath)
                except OSError:
                    pass
            else:
                kept.append(det)

        return kept

    # ── Stage 7: Confidence Scoring ───────────────────────────────────────────

    def _compute_confidence(self, region: dict, page_h: float) -> float:
        """
        Returns a 0–1 confidence score.

        Tier logic:
          Tier A: table_detect or pdf_object + above caption + figure_no  → 1.00
          Tier B: any source        + above caption + figure_no            → 0.95
          Tier C: above caption only (no figure_no regex)                  → 0.80
          Tier D: below caption (fallback)                                 → 0.70
          Tier E: no caption at all                                        → base + signals
        """
        x0, y0, x1, y1 = region["bbox"]
        w, h = x1 - x0, y1 - y0
        source   = region.get("source", "cv_region")
        has_figno = bool(region.get("figure_no"))
        has_cap   = bool(region.get("caption"))
        pos       = region.get("caption_position")  # 'above' | 'below' | None

        # ── Fast path: definitive detections ──────────────────────────────
        if has_figno and pos == "above":
            if source in ("table_detect", "pdf_object"):
                return 1.0   # Tier A: authoritative source + labeled caption above
            return 0.95      # Tier B: cv_region with clear above-caption label

        if has_cap and pos == "above":
            return 0.80      # Tier C: above caption but no explicit figure/table number

        if has_cap and pos == "below":
            return 0.70      # Tier D: below caption (fallback, rare)

        # ── Tier E: no caption — scored by signals ─────────────────────────
        score = 0.5

        # Source reliability
        if source == "table_detect":
            score += 0.15   # find_tables() is authoritative
        elif source == "pdf_object":
            score += 0.10   # embedded XObject is reliable
        # cv_region: no bonus

        # Aspect ratio — wide tables (ar > 4) and tall figures (ar < 0.25) are normal;
        # only penalise extreme (> 10:1 or < 1:10) shapes that are probably artefacts.
        ar = w / h if h > 0 else 1
        if 0.1 <= ar <= 10.0:
            score += 0.10

        # Decently sized (> 5% of page area)
        page_area = page_h * (x1 - x0)
        obj_area  = w * h
        if page_area > 0 and (obj_area / page_area) > 0.05:
            score += 0.10

        return round(min(score, 1.0), 2)

    # ── Extraction Utility ─────────────────────────────────────────────────────

    def _extract_asset(self, page: fitz.Page, bbox: tuple,
                        session_id: str, asset_id: str) -> Optional[str]:
        """
        High-resolution (3×) clip of the PDF page at the given bbox → PNG.
        """
        try:
            rect = fitz.Rect(*bbox) & page.rect   # clamp to page
            if rect.is_empty or rect.width < 5 or rect.height < 5:
                return None
            mat  = fitz.Matrix(3.0, 3.0)
            pix  = page.get_pixmap(matrix=mat, clip=rect)
            fname = f"{asset_id}.png"
            fpath = os.path.join(self.assets_dir, fname)
            pix.save(fpath)
            return fpath
        except Exception as e:
            print(f"[extract] Failed for {asset_id}: {e}")
            return None

    # ── Geometry helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _iou(a: tuple, b: tuple) -> float:
        """Intersection over Union of two (x0,y0,x1,y1) rects."""
        ix0 = max(a[0], b[0])
        iy0 = max(a[1], b[1])
        ix1 = min(a[2], b[2])
        iy1 = min(a[3], b[3])
        if ix1 <= ix0 or iy1 <= iy0:
            return 0.0
        inter = (ix1 - ix0) * (iy1 - iy0)
        area_a = (a[2] - a[0]) * (a[3] - a[1])
        area_b = (b[2] - b[0]) * (b[3] - b[1])
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0
