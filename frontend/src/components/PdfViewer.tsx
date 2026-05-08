import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import { useStore } from '../store/useStore';
import {
  Loader2, ZoomIn, ZoomOut, RotateCcw, AlertCircle,
  Maximize2, Minimize2
} from 'lucide-react';

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

interface PdfViewerProps {
  file: File | string | null;
}

const PdfViewer: React.FC<PdfViewerProps> = ({ file }) => {
  const { currentPage, detections, setSelectedAssetId, selectedAssetId, pageDimensions } = useStore();
  const [scale, setScale] = useState(1.0);
  const [fitMode, setFitMode] = useState<'width' | 'free'>('width');
  const containerRef = useRef<HTMLDivElement>(null);
  const [pageWidth, setPageWidth] = useState(0);
  const [pageRenderDimensions, setPageRenderDimensions] = useState<{ width: number; height: number } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isPageLoading, setIsPageLoading] = useState(false);

  const getContainerWidth = useCallback(() => {
    if (containerRef.current) {
      const w = containerRef.current.clientWidth - 64;
      return w > 0 ? w : 600;
    }
    return 600;
  }, []);

  const updateWidth = useCallback(() => {
    setPageWidth(getContainerWidth());
  }, [getContainerWidth]);

  useEffect(() => {
    updateWidth();
    const ro = new ResizeObserver(updateWidth);
    if (containerRef.current) ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, [updateWidth]);

  // Reset page loading state when page changes
  useEffect(() => {
    setIsPageLoading(true);
    setPageRenderDimensions(null);
  }, [currentPage]);

  const effectiveWidth = fitMode === 'width'
    ? pageWidth * scale
    : Math.min(pageWidth * scale, pageWidth * 2);

  const handleBoxClick = (id: string) => {
    setSelectedAssetId(id);
    const element = document.getElementById(`asset-${id}`);
    if (element) element.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  const onPageLoadSuccess = (page: any) => {
    const viewport = page.getViewport({ scale: 1 });
    setPageRenderDimensions({ width: viewport.width, height: viewport.height });
    setIsPageLoading(false);
    setLoadError(null);
  };

  const zoomIn  = () => setScale(s => Math.min(3, parseFloat((s + 0.15).toFixed(2))));
  const zoomOut = () => setScale(s => Math.max(0.4, parseFloat((s - 0.15).toFixed(2))));
  const zoomReset = () => { setScale(1.0); setFitMode('width'); };

  const ZOOM_PRESETS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0];

  return (
    <div className="pdf-reader-shell">
      {/* ── Toolbar ── */}
      <div className="pdf-toolbar">
        <div className="pdf-toolbar-group">
          <button className="pdf-tool-btn" onClick={zoomOut} title="Zoom out (-)">
            <ZoomOut className="w-4 h-4" />
          </button>

          <select
            className="pdf-zoom-select"
            value={Math.round(scale * 100)}
            onChange={e => { setScale(parseInt(e.target.value) / 100); setFitMode('free'); }}
          >
            {ZOOM_PRESETS.map(p => (
              <option key={p} value={Math.round(p * 100)}>
                {Math.round(p * 100)}%
              </option>
            ))}
          </select>

          <button className="pdf-tool-btn" onClick={zoomIn} title="Zoom in (+)">
            <ZoomIn className="w-4 h-4" />
          </button>
        </div>

        <div className="pdf-toolbar-divider" />

        <div className="pdf-toolbar-group">
          <button
            className={`pdf-tool-btn ${fitMode === 'width' ? 'active' : ''}`}
            onClick={() => { setFitMode('width'); setScale(1.0); }}
            title="Fit to width"
          >
            <Maximize2 className="w-4 h-4" />
          </button>
          <button
            className="pdf-tool-btn"
            onClick={zoomReset}
            title="Reset zoom"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
        </div>

        <div className="pdf-toolbar-spacer" />

        <div className="pdf-zoom-badge">
          {Math.round(scale * 100)}%
        </div>
      </div>

      {/* ── Scrollable Canvas ── */}
      <div ref={containerRef} className="pdf-canvas-scroll">
        {loadError ? (
          <div className="pdf-error-state">
            <div className="pdf-error-icon">
              <AlertCircle className="w-8 h-8" style={{ color: '#f87171' }} />
            </div>
            <p className="pdf-error-title">PDF Load Error</p>
            <p className="pdf-error-sub">{loadError}</p>
          </div>
        ) : (
          <div className="pdf-page-wrap">
            {/* Loading shimmer behind the page */}
            {isPageLoading && (
              <div
                className="pdf-page-skeleton"
                style={{
                  width: effectiveWidth,
                  height: effectiveWidth * (pageDimensions.height / (pageDimensions.width || 1)),
                }}
              >
                <Loader2 className="w-8 h-8 text-indigo-400 animate-spin" />
              </div>
            )}

            <div className="pdf-page-shadow" style={{ display: isPageLoading ? 'none' : 'block' }}>
              <Document
                file={file}
                onLoadError={(e) => { console.error(e); setLoadError('Could not load PDF. Try re-uploading.'); }}
                loading={null}
              >
                <Page
                  pageNumber={currentPage}
                  width={effectiveWidth > 0 ? effectiveWidth : undefined}
                  renderTextLayer={true}
                  renderAnnotationLayer={false}
                  onLoadSuccess={onPageLoadSuccess}
                />
              </Document>

              {/* Bounding Box Overlay */}
              {pageRenderDimensions && (
                <div className="absolute inset-0 pointer-events-none">
                  {detections.map((det) => {
                    const [x0, y0, x1, y1] = det.bbox;
                    const renderedW = effectiveWidth;
                    const renderedH = renderedW * (pageDimensions.height / pageDimensions.width);

                    const left   = (x0 / pageDimensions.width)  * renderedW;
                    const top    = (y0 / pageDimensions.height) * renderedH;
                    const width  = ((x1 - x0) / pageDimensions.width)  * renderedW;
                    const height = ((y1 - y0) / pageDimensions.height) * renderedH;

                    const isSelected = selectedAssetId === det.id;
                    const isTable = det.type === 'table';

                    return (
                      <div
                        key={det.id}
                        onClick={(e) => { e.stopPropagation(); handleBoxClick(det.id); }}
                        className={`absolute cursor-pointer pointer-events-auto transition-all duration-200 ${
                          isSelected
                            ? 'bbox-selected'
                            : isTable ? 'bbox-table' : 'bbox-figure'
                        }`}
                        style={{ left, top, width, height }}
                        title={det.caption || det.figure_no || 'Visual Asset'}
                      >
                        {/* Label pill */}
                        <div className={`bbox-label ${isSelected ? 'bbox-label-selected' : ''}`}>
                          {det.figure_no || det.type}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
        {/* bottom breathing room */}
        <div style={{ height: 48 }} />
      </div>
    </div>
  );
};

export default PdfViewer;
