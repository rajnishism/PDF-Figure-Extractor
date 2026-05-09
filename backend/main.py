import os
import uuid
import shutil
import asyncio
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import uvicorn

# Import our processing logic
from processor import PDFProcessor

app = FastAPI(title="PDF Visual Extraction API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directories
UPLOAD_DIR = "uploads"
ASSETS_DIR = "assets"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)

# Mount static files for assets
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

# Processor instance
processor = PDFProcessor(UPLOAD_DIR, ASSETS_DIR)

# Global store for progress (export and background processing)
# Format: { session_id: { "current": int, "total": int, "status": str } }
export_progress = {}

def background_process_all_pages(session_id: str, file_path: str, total_pages: int):
    """Background task: scan every page and cache results to disk.
    
    Each page is processed with the full fast pipeline (PyMuPDF-Layout + CV)
    and saved to uploads/<session_id>/page_N.json. Export reads from this cache
    and completes instantly without re-processing.
    """
    print(f"\n[background] Scanning {total_pages} pages for session {session_id[:8]}")
    export_progress[session_id] = {"current": 0, "total": total_pages, "status": "background_processing"}

    for page_no in range(1, total_pages + 1):
        try:
            processor.process_page(file_path, session_id, page_no)
            export_progress[session_id]["current"] = page_no
            print(f"[background] page {page_no}/{total_pages}", end="\r", flush=True)
        except Exception as e:
            print(f"\n[background] Error on page {page_no}: {e}")

    export_progress[session_id]["status"] = "idle"
    print(f"\n[background] Done — all pages cached for session {session_id[:8]}")

class Detection(BaseModel):
    id: str
    bbox: List[float]
    type: str
    page: Optional[int] = None
    figure_no: Optional[str] = None
    caption: Optional[str] = None
    image_url: str
    confidence: Optional[float] = None

class PageResponse(BaseModel):
    page: int
    width: float
    height: float
    detections: List[Detection]

class ExportAsset(BaseModel):
    image_url: str          # e.g. /assets/page_1_img_0_abc123.png
    caption: Optional[str] = None
    figure_no: Optional[str] = None

class ExportRequest(BaseModel):
    assets: List[ExportAsset]
    zip_name: Optional[str] = "extracted_assets"

@app.post("/upload")
async def upload_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    
    session_id = str(uuid.uuid4())
    session_dir = os.path.join(UPLOAD_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)
    
    file_path = os.path.join(session_dir, "document.pdf")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    total_pages = processor.get_total_pages(file_path)

    # Write metadata so session can be restored after page reload
    meta = {"filename": file.filename, "total_pages": total_pages}
    with open(os.path.join(session_dir, "meta.json"), "w") as f:
        import json; json.dump(meta, f)

    # Start background rendering
    background_tasks.add_task(background_process_all_pages, session_id, file_path, total_pages)

    return {
        "session_id": session_id,
        "total_pages": total_pages,
        "filename": file.filename
    }

@app.get("/session/{session_id}")
async def get_session(session_id: str):
    """Validate a session and return its metadata — used for page-reload recovery."""
    import json
    session_dir = os.path.join(UPLOAD_DIR, session_id)
    meta_path   = os.path.join(session_dir, "meta.json")
    pdf_path    = os.path.join(session_dir, "document.pdf")

    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Session not found or expired")

    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)

    total_pages   = meta.get("total_pages") or processor.get_total_pages(pdf_path)
    cached_pages  = [
        int(fn.replace("page_", "").replace(".json", ""))
        for fn in os.listdir(session_dir)
        if fn.startswith("page_") and fn.endswith(".json")
    ]

    return {
        "session_id": session_id,
        "total_pages": total_pages,
        "filename": meta.get("filename", "document.pdf"),
        "cached_pages": sorted(cached_pages),
    }

@app.get("/pdf/{session_id}")
async def serve_pdf(session_id: str):
    """Serve the original PDF so PdfViewer can load it via URL after a page reload."""
    from fastapi.responses import FileResponse
    pdf_path = os.path.join(UPLOAD_DIR, session_id, "document.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(pdf_path, media_type="application/pdf")

@app.get("/process-page/{session_id}/{page_no}", response_model=PageResponse)
async def process_page(session_id: str, page_no: int):
    file_path = os.path.join(UPLOAD_DIR, session_id, "document.pdf")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        data = processor.process_page(file_path, session_id, page_no)
        return {
            "page": page_no,
            "width": data["width"],
            "height": data["height"],
            "detections": data["detections"]
        }
    except Exception as e:
        print(f"Error processing page: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/export-zip")
async def export_zip(request: ExportRequest):
    """
    Build a ZIP of requested assets, naming each file after its caption.
    Returns the zip as a streaming file download.
    """
    import zipfile
    import re
    import io
    from fastapi.responses import StreamingResponse

    def sanitize(name: str, max_len: int = 80) -> str:
        """Turn a caption string into a safe filename."""
        name = name.strip()
        # Replace any character that isn't alphanumeric, space, dash, or dot
        name = re.sub(r'[^\w\s\-.]', '', name, flags=re.UNICODE)
        name = re.sub(r'\s+', '_', name)
        name = name[:max_len].strip('_')
        return name or "asset"

    buf = io.BytesIO()
    seen_names: dict[str, int] = {}   # deduplicate filenames

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, asset in enumerate(request.assets):
            # Resolve the physical path: image_url is like /assets/<filename>
            rel_path = asset.image_url.lstrip("/")          # "assets/page_1_img_0_abc.png"
            src_path = os.path.join(os.getcwd(), rel_path)

            if not os.path.exists(src_path):
                print(f"Warning: asset not found at {src_path}, skipping")
                continue

            # Build a human-readable filename
            if asset.figure_no and asset.caption:
                base = sanitize(f"{asset.figure_no} - {asset.caption}")
            elif asset.figure_no:
                base = sanitize(asset.figure_no)
            elif asset.caption and asset.caption != "Visual Asset":
                base = sanitize(asset.caption)
            else:
                base = f"asset_{idx + 1}"

            arcname = f"{base}.png"

            # Deduplicate: if the same filename appears again, add a counter
            if arcname in seen_names:
                seen_names[arcname] += 1
                arcname = f"{base}_{seen_names[arcname]}.png"
            else:
                seen_names[arcname] = 1

            zf.write(src_path, arcname=arcname)

    buf.seek(0)
    zip_filename = f"{sanitize(request.zip_name or 'extracted_assets')}.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )

@app.get("/export-status/{session_id}")
async def get_export_status(session_id: str):
    """Return the current export progress for a session."""
    return export_progress.get(session_id, {"current": 0, "total": 0, "status": "idle"})

@app.get("/export-document/{session_id}")
async def export_document(session_id: str):
    """
    Scan the entire document, process every page, and return a ZIP of all assets.
    Updates global export_progress for frontend polling.
    """
    import zipfile
    import re
    import io
    from fastapi.responses import StreamingResponse

    file_path = os.path.join(UPLOAD_DIR, session_id, "document.pdf")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Session not found")

    def sanitize(name: str, max_len: int = 80) -> str:
        name = name.strip()
        name = re.sub(r'[^\w\s\-.]', '', name, flags=re.UNICODE)
        name = re.sub(r'\s+', '_', name)
        name = name[:max_len].strip('_')
        return name or "asset"

    total_pages = processor.get_total_pages(file_path)
    all_assets = []
    
    # Initialize progress
    export_progress[session_id] = {"current": 0, "total": total_pages, "status": "processing"}
    print(f"\n[export] Starting full export for session {session_id[:8]} ({total_pages} pages)")

    # 1. Collect all assets from all pages
    for page_no in range(1, total_pages + 1):
        try:
            print(f"[export] Processing page {page_no}/{total_pages}...", end="\r")
            export_progress[session_id]["current"] = page_no
            # Yield to event loop so /export-status can respond
            await asyncio.sleep(0.01)
            
            data = processor.process_page(file_path, session_id, page_no)
            all_assets.extend(data["detections"])
        except Exception as e:
            print(f"\n[export] Error processing page {page_no}: {e}")

    if not all_assets:
        raise HTTPException(status_code=404, detail="No visual assets found in document")

    print(f"\n[export] Collection complete. {len(all_assets)} assets found. Sorting and Zipping...")
    export_progress[session_id]["status"] = "zipping"

    # 2. Create ZIP with folder structure
    buf = io.BytesIO()
    seen_names: dict[str, int] = {}

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, asset in enumerate(all_assets):
            # Resolve physical path
            rel_path = asset["image_url"].lstrip("/")
            src_path = os.path.join(os.getcwd(), rel_path)

            if not os.path.exists(src_path):
                continue

            # Determine confidence and target folder
            is_high_confidence = bool(asset.get("caption") or asset.get("type") == "table")
            
            if is_high_confidence:
                folder = "Tables" if (asset.get("type") == "table" or (asset.get("figure_no") and "table" in asset["figure_no"].lower())) else "Figures"
            else:
                folder = "Unconfirmed"

            # Naming
            if asset.get("figure_no") and asset.get("caption"):
                base = sanitize(f"{asset['figure_no']} - {asset['caption']}")
            elif asset.get("figure_no"):
                base = sanitize(asset["figure_no"])
            elif asset.get("caption") and asset["caption"] != "Visual Asset":
                base = sanitize(asset["caption"])
            else:
                base = f"asset_p{asset.get('page', 'x')}_{idx + 1}"

            arcname = f"{folder}/{base}.png"
            
            # Deduplicate within the folder
            if arcname in seen_names:
                seen_names[arcname] += 1
                name_part, ext = os.path.splitext(arcname)
                arcname = f"{name_part}_{seen_names[arcname]}{ext}"
            else:
                seen_names[arcname] = 1

            zf.write(src_path, arcname=arcname)

    print(f"[export] ZIP generation finished. Sending to client.")
    # Reset progress
    export_progress[session_id] = {"current": total_pages, "total": total_pages, "status": "complete"}
    
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="confident_assets_{session_id[:8]}.zip"'},
    )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
