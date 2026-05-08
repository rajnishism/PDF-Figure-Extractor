<<<<<<< HEAD
<div align="center">

# 🔍 VisionExtract

### Intelligent PDF Visual Asset Extraction Engine

**Automatically detect, extract, and export every Figure, Chart, Map, and Table from any PDF — with captions, confidence scores, and structured ZIP exports.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)](https://react.dev)
[![PyMuPDF](https://img.shields.io/badge/PyMuPDF-1.24%2B-orange)](https://pymupdf.readthedocs.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

</div>

---

## ✨ What is VisionExtract?

VisionExtract is a full-stack web application that reads any PDF document and intelligently extracts all visual assets — figures, charts, maps, diagrams, and tables — along with their associated captions. It presents them in a beautiful, interactive interface and lets you export everything as an organized ZIP archive.

> Built for engineers, researchers, and analysts who need to quickly pull visuals out of large technical reports, academic papers, or mining/geological PDFs.

---

## 🎯 Key Features

| Feature | Description |
|---|---|
| **3-Tier Detection Pipeline** | Combines PyMuPDF vector-grid analysis, PDF XObject extraction, and OpenCV edge detection in priority order |
| **Smart Caption Association** | Multi-signal scoring matrix with direction-aware logic (above = primary, below = fallback) |
| **5-Tier Confidence Scoring** | Deterministic confidence from 70%–100% based on detection source and caption quality |
| **Interactive PDF Reader** | Dark-mode PDF viewer with zoom controls, dot-grid canvas, and click-to-highlight bounding boxes |
| **Resizable Split Layout** | Drag the divider to resize the PDF viewer and asset panel |
| **Real-Time Export Progress** | Full-document export with live page-by-page progress bar and percentage |
| **Structured ZIP Export** | Assets organized into `Figures/`, `Tables/`, and `Unconfirmed/` folders |
| **Perceptual Hash Deduplication** | Repeated logos and headers are automatically filtered out |
| **100% Confidence Filter** | Export only high-confidence verified assets, with fallbacks in a separate folder |

---

## 🏗️ Architecture

```
Report Parse/
├── backend/                    # FastAPI Python backend
│   ├── main.py                 # API routes & export logic
│   ├── processor.py            # Core PDF extraction engine
│   ├── assets/                 # Runtime: extracted image PNGs (git-ignored)
│   └── uploads/                # Runtime: uploaded PDFs (git-ignored)
│
└── frontend/                   # React + TypeScript frontend
    └── src/
        ├── App.tsx              # Main layout, export flow, resize logic
        ├── index.css            # Full design system (dark theme)
        ├── components/
        │   ├── PdfViewer.tsx    # PDF reader with bbox overlay
        │   └── AssetList.tsx    # Extracted asset cards panel
        └── store/
            └── useStore.ts      # Zustand global state
```

---

## 🔬 How the Extraction Pipeline Works

### Stage 1 — Rendering
The PDF page is rendered to a high-resolution raster image (zoom factor) for OpenCV processing.

### Stage 2 — Three-Tier Detection

| Priority | Detector | Method | What it Catches |
|---|---|---|---|
| **Tier 1** | `table_detect` | `page.find_tables()` — PyMuPDF vector line analysis | Grid-based tables with ruled borders |
| **Tier 2** | `pdf_object` | XObject scan from PDF structure | Raster images, embedded charts |
| **Tier 3** | `cv_region` | OpenCV Canny edge + contour detection | Vector diagrams, maps, unlabeled figures |

### Stage 3 — Filtering
- **Position filter**: Drops header/footer regions and oversized captures (>90% of page)
- **Text coverage filter**: `cv_region` detections with ≥30% text coverage are dropped (prevents bordered paragraphs being extracted as figures)
- **Caption-only filter**: Tiny text-only regions are dropped

### Stage 4 — Caption Association (Multi-Signal Scoring)
For each figure, all nearby text blocks are scored against 7 signals:

| Signal | Points |
|---|---|
| Regex match (`Figure X`, `Table X`, `Map X`, `Chart X`) | +4.0 (required gate) |
| **Above** figure (primary) | Full weight + distance decay up to 150pt |
| **Below** figure (fallback) | −2.0 directional penalty + 80pt hard cap |
| Distance decay (closer = higher) | +0.2 to +2.0 |
| Horizontal centre alignment | +0.5 to +1.5 |
| Width proportion match | +0.2 to +0.8 |
| Italic / smaller font | +0.4 to +0.5 |
| Intervening element (another figure between caption and this one) | −2.5 |

The greedy bipartite assignment ensures each caption is matched to at most one figure.

### Stage 5 — Confidence Scoring

| Tier | Condition | Confidence |
|---|---|---|
| **A** | `table_detect`/`pdf_object` + above-caption + labeled figure number | **100%** |
| **B** | `cv_region` + above-caption + labeled figure number | **95%** |
| **C** | Any source + above-caption (no number) | **80%** |
| **D** | Any source + below-caption (fallback) | **70%** |
| **E** | No caption found | **50–75%** |

### Stage 6 — Deduplication
Perceptual hashing (pHash) tracks repeated images across pages. Images appearing on ≥20% of pages (logos, watermarks) are automatically filtered.

---

## 🚀 Setup Guide

### Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| Node.js | 18+ |
| pip | latest |
| npm | latest |

---

### Backend Setup

```bash
# 1. Navigate to backend directory
cd "Report Parse/backend"

# 2. Create and activate a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate       # macOS / Linux
# .venv\Scripts\activate        # Windows

# 3. Install Python dependencies
pip install fastapi uvicorn pymupdf opencv-python numpy pillow imagehash python-multipart

# 4. Create required runtime directories
mkdir -p assets uploads

# 5. Start the backend server
python3 main.py
# → Server running at http://localhost:8001
```

---

### Frontend Setup

```bash
# 1. Navigate to frontend directory (new terminal)
cd "Report Parse/frontend"

# 2. Install Node dependencies
npm install

# 3. Start the development server
npm run dev
# → App running at http://localhost:5173
```

---

### Environment Summary

| Service | URL |
|---|---|
| Frontend (React) | http://localhost:5173 |
| Backend (FastAPI) | http://localhost:8001 |
| API Docs (Swagger) | http://localhost:8001/docs |

---

## 📖 How to Use

### 1. Upload a PDF

Click **"Choose File"** in the top-right header and select any PDF. The document is uploaded to the backend and the first page is automatically processed.

### 2. Navigate Pages

Use the **◀ / ▶** arrows in the header to move between pages. Each page is processed on-demand — detected assets appear in the right panel within 1–2 seconds.

### 3. Review Extracted Assets

The right-hand panel shows all detected assets for the current page:
- **Thumbnail** of the extracted image
- **Figure/Table label** (e.g., "Figure 7.1", "Table 16.16")
- **Caption text** associated with the asset
- **Confidence bar** (green = 100%, yellow = 70–80%)
- **Download** or **Copy Caption** buttons

### 4. Click Assets on the PDF

Each detected asset is highlighted on the PDF with a colored bounding box:
- 🟣 **Purple** = Figure / Diagram
- 🟢 **Green** = Table (vector grid detected)
- 🔵 **Indigo glow** = Selected asset

Click a bounding box on the PDF to select it and auto-scroll the right panel to that asset.

### 5. Zoom & Navigate the PDF

The toolbar at the top of the PDF viewer provides:
- **−/+** zoom buttons
- **Preset dropdown** (50%, 75%, 100%, 125%, 150%, 200%)
- **Fit to Width** button
- **Reset** button

The canvas is fully scrollable both horizontally and vertically.

### 6. Export Full Report

Click **"Export Full Report"** in the header to extract all visual assets from every page of the document.

A live progress overlay shows:
- Current page being processed (`Processing Page X of Y`)
- Percentage completion bar
- Zipping phase indicator

The downloaded ZIP is organized as:
```
confident_assets_[id].zip
├── Figures/
│   ├── Figure_7.1_-_ESML_Project_Location.png
│   └── Figure_8.2_-_Geological_Cross_Section.png
├── Tables/
│   ├── Table_16.16_-_Estimated_Number_of_Drills.png
│   └── Table_3.1_-_Resource_Estimate.png
└── Unconfirmed/
    └── asset_p42_1.png    ← Detected but no caption found
```

### 7. Upload a New File

Click **"New File"** in the header to reset the session and upload a different document.

---

## 🔌 API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/upload` | Upload a PDF, returns `session_id` and `total_pages` |
| `GET` | `/process/{session_id}/{page_no}` | Process a specific page, returns detections |
| `GET` | `/export-document/{session_id}` | Export all pages as structured ZIP |
| `GET` | `/export-status/{session_id}` | Poll real-time export progress |
| `GET` | `/assets/{filename}` | Serve extracted asset images |

---

## 🛠️ Configuration (processor.py)

Key constants you can tune at the top of `processor.py`:

| Constant | Default | Description |
|---|---|---|
| `MARGIN_TOP` | `50` | Top margin (pts) — content above is ignored (headers) |
| `MARGIN_BOTTOM` | `50` | Bottom margin (pts) — content below is ignored (footers) |
| `MAX_TEXT_COVERAGE_CV` | `0.30` | CV regions with >30% text density are dropped |
| `MAX_CAPTION_DISTANCE_PTS` | `150` | Max distance (pts) to search for a caption **above** |
| `MAX_CAPTION_DISTANCE_BELOW` | `80` | Max distance (pts) to search for a caption **below** (fallback) |
| `LOGO_PAGE_PCT` | `0.20` | Images appearing on >20% of pages are treated as logos |

---

## 📦 Dependencies

### Backend
| Package | Purpose |
|---|---|
| `fastapi` | REST API framework |
| `uvicorn` | ASGI server |
| `pymupdf` (fitz) | PDF parsing, rendering, `find_tables()` |
| `opencv-python` | Edge detection for vector diagrams |
| `numpy` | Array operations |
| `pillow` | Image processing |
| `imagehash` | Perceptual hashing for deduplication |
| `python-multipart` | Multipart file upload support |

### Frontend
| Package | Purpose |
|---|---|
| `react` + `typescript` | UI framework |
| `vite` | Build tool & dev server |
| `react-pdf` | PDF rendering in browser |
| `axios` | HTTP client |
| `zustand` | Global state management |
| `lucide-react` | Icon library |

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">
Built with ❤️ for document intelligence
</div>
=======
# PDF-Figure-Extractor
PDF Figure Extractor automatically extracts figures, charts, diagrams, tables, and captions from PDF documents using AI-powered layout analysis and high-resolution visual detection. Ideal for research papers, technical reports, and engineering documents.
>>>>>>> 10919c09560860b4bf4db3fee2d1a3402342d1da
