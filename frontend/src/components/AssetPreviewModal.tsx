import React, { useEffect, useCallback, useRef, useState } from 'react';
import {
  X, ChevronLeft, ChevronRight, Download, Copy,
  ZoomIn, ZoomOut, RotateCcw, Maximize2, FileImage, Table2,
  Loader2, AlertCircle, RefreshCw
} from 'lucide-react';

const API_BASE = 'http://localhost:8001';

interface Detection {
  id: string;
  bbox: number[];
  type: string;
  page?: number;
  figure_no?: string;
  caption?: string;
  image_url: string;
  confidence?: number;
}

interface AssetPreviewModalProps {
  /** All detections accumulated so far (across all processed pages) */
  assets: Detection[];
  initialIndex: number;
  onClose: () => void;
  /** Total pages in the document */
  totalPages: number;
  /** Which pages have already been processed */
  processedPages: Set<number>;
  /** Called when modal needs a page that hasn't been processed yet */
  onFetchPage: (page: number) => Promise<void>;
  /** Set so that when a new page is processed, the modal gets fresh assets */
  onNavigateToPage?: (page: number) => void;
}

const AssetPreviewModal: React.FC<AssetPreviewModalProps> = ({
  assets,
  initialIndex,
  onClose,
  totalPages,
  processedPages,
  onFetchPage,
  onNavigateToPage,
}) => {
  const [index, setIndex] = useState(Math.min(initialIndex, assets.length - 1));
  const [zoom, setZoom] = useState(1);
  const [copied, setCopied] = useState(false);
  const [imgState, setImgState] = useState<'loading' | 'ok' | 'error'>('loading');
  const [fetchingPage, setFetchingPage] = useState<number | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const thumbStripRef = useRef<HTMLDivElement>(null);

  // Keep index in bounds when assets array grows after fetching
  const safeIndex = Math.max(0, Math.min(index, assets.length - 1));
  const asset = assets[safeIndex];
  const total = assets.length;

  // Which pages are in the current assets list
  const pagesInAssets = new Set(assets.map(a => a.page ?? 1));

  // Determine the next unprocessed page after current asset's page
  const currentAssetPage = asset?.page ?? 1;
  const nextUnprocessedPage = (() => {
    for (let p = currentAssetPage + 1; p <= totalPages; p++) {
      if (!processedPages.has(p)) return p;
    }
    return null;
  })();

  // Are there more pages with assets we haven't loaded yet?
  const hasMorePages = nextUnprocessedPage !== null;

  // ── Navigation ──────────────────────────────────────────────────
  const goTo = useCallback((newIndex: number) => {
    setIndex(newIndex);
    setZoom(1);
    setImgState('loading');
    setFetchError(null);
    // Scroll corresponding thumb into view
    setTimeout(() => {
      const strip = thumbStripRef.current;
      if (strip) {
        const thumb = strip.children[newIndex] as HTMLElement;
        thumb?.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
      }
    }, 50);
  }, []);

  const goNext = useCallback(() => {
    if (safeIndex < total - 1) {
      goTo(safeIndex + 1);
    }
  }, [safeIndex, total, goTo]);

  const goPrev = useCallback(() => {
    if (safeIndex > 0) {
      goTo(safeIndex - 1);
    }
  }, [safeIndex, goTo]);

  // Fetch the next unprocessed page's assets
  const handleFetchNextPage = useCallback(async (page: number) => {
    setFetchingPage(page);
    setFetchError(null);
    try {
      await onFetchPage(page);
      // After fetch, assets prop will have been updated by parent
      // Navigate to the first asset of the newly fetched page
      onNavigateToPage?.(page);
    } catch {
      setFetchError(`Failed to load Page ${page}. Try again.`);
    } finally {
      setFetchingPage(null);
    }
  }, [onFetchPage, onNavigateToPage]);

  // When assets list grows (after a page fetch), move to the first new asset
  const prevTotalRef = useRef(total);
  useEffect(() => {
    if (total > prevTotalRef.current) {
      // Jump to the first newly loaded asset
      goTo(prevTotalRef.current);
    }
    prevTotalRef.current = total;
  }, [total, goTo]);

  // Keyboard
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') goNext();
      else if (e.key === 'ArrowLeft') goPrev();
      else if (e.key === 'Escape') onClose();
      else if (e.key === '+' || e.key === '=') setZoom(z => Math.min(4, parseFloat((z + 0.25).toFixed(2))));
      else if (e.key === '-') setZoom(z => Math.max(0.5, parseFloat((z - 0.25).toFixed(2))));
      else if (e.key === '0') setZoom(1);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [goNext, goPrev, onClose]);

  // Lock body scroll
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, []);

  // Fullscreen
  const [isFullscreen, setIsFullscreen] = useState(false);
  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      overlayRef.current?.requestFullscreen?.();
    } else {
      document.exitFullscreen?.();
    }
  }, []);
  useEffect(() => {
    const h = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', h);
    return () => document.removeEventListener('fullscreenchange', h);
  }, []);

  // ── Helpers ─────────────────────────────────────────────────────
  const handleCopy = () => {
    navigator.clipboard.writeText(asset?.caption || '').then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const handleDownload = async () => {
    if (!asset) return;
    try {
      const resp = await fetch(`${API_BASE}${asset.image_url}`);
      const blob = await resp.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = `${asset.figure_no || asset.id}.png`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(objectUrl);
    } catch (e) {
      console.error('Download failed', e);
    }
  };

  const confidenceColor = (c?: number) => {
    if (!c) return 'hsl(220,10%,45%)';
    if (c >= 0.95) return '#34d399';
    if (c >= 0.75) return '#10b981';
    if (c >= 0.5) return '#fbbf24';
    return '#f87171';
  };

  if (!asset) return null;

  return (
    <div className="preview-overlay" ref={overlayRef} onClick={onClose}>
      <div className="preview-shell" onClick={e => e.stopPropagation()}>

        {/* ── Top bar ── */}
        <div className="preview-topbar">
          <div className="preview-topbar-left">
            <div className={`preview-type-badge ${asset.type === 'table' ? 'preview-type-table' : 'preview-type-figure'}`}>
              {asset.type === 'table' ? <Table2 className="w-3 h-3" /> : <FileImage className="w-3 h-3" />}
              {asset.type}
            </div>
            <span className="preview-figno">{asset.figure_no || 'Visual Asset'}</span>
            {asset.page && <span className="preview-page-chip">Page {asset.page}</span>}
            {asset.confidence !== undefined && (
              <span className="preview-confidence" style={{ color: confidenceColor(asset.confidence) }}>
                {Math.round(asset.confidence * 100)}% confidence
              </span>
            )}
          </div>

          <div className="preview-topbar-right">
            <div className="preview-zoom-group">
              <button className="preview-icon-btn" onClick={() => setZoom(z => Math.max(0.5, parseFloat((z - 0.25).toFixed(2))))} title="Zoom out (-)">
                <ZoomOut className="w-4 h-4" />
              </button>
              <span className="preview-zoom-label">{Math.round(zoom * 100)}%</span>
              <button className="preview-icon-btn" onClick={() => setZoom(z => Math.min(4, parseFloat((z + 0.25).toFixed(2))))} title="Zoom in (+)">
                <ZoomIn className="w-4 h-4" />
              </button>
              <button className="preview-icon-btn" onClick={() => setZoom(1)} title="Reset zoom (0)">
                <RotateCcw className="w-3.5 h-3.5" />
              </button>
            </div>
            <button className="preview-icon-btn" onClick={toggleFullscreen} title="Fullscreen">
              <Maximize2 className="w-4 h-4" />
            </button>
            <button className="preview-icon-btn preview-btn-download" onClick={handleDownload} title="Download">
              <Download className="w-4 h-4" />
            </button>
            <button className="preview-close-btn" onClick={onClose} title="Close (Esc)">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* ── Main canvas ── */}
        <div className="preview-canvas-area">
          {/* Prev */}
          <button
            className="preview-nav-btn preview-nav-prev"
            onClick={goPrev}
            disabled={safeIndex === 0}
            title="Previous asset (←)"
          >
            <ChevronLeft className="w-6 h-6" />
          </button>

          {/* Image stage */}
          <div className="preview-stage">
            {/* Loading spinner */}
            {imgState === 'loading' && (
              <div className="preview-loader">
                <div className="preview-spinner" />
              </div>
            )}
            {/* Error state */}
            {imgState === 'error' && (
              <div className="preview-error-state">
                <AlertCircle className="w-10 h-10" style={{ color: '#f87171', marginBottom: 12 }} />
                <p style={{ color: '#f87171', fontWeight: 600, marginBottom: 4 }}>Image failed to load</p>
                <p style={{ color: 'hsl(220,10%,45%)', fontSize: 12 }}>{asset.image_url}</p>
                <button
                  className="preview-copy-btn"
                  style={{ marginTop: 16 }}
                  onClick={() => { setImgState('loading'); if (imgRef.current) imgRef.current.src = `${API_BASE}${asset.image_url}?t=${Date.now()}`; }}
                >
                  <RefreshCw className="w-3.5 h-3.5" /> Retry
                </button>
              </div>
            )}

            <div
              className="preview-img-wrap"
              style={{ transform: `scale(${zoom})`, transition: 'transform 0.2s ease' }}
            >
              <img
                ref={imgRef}
                key={asset.id} /* force remount on asset change */
                src={`${API_BASE}${asset.image_url}`}
                alt={asset.caption || asset.figure_no || 'Asset preview'}
                className="preview-img"
                style={{ opacity: imgState === 'ok' ? 1 : 0 }}
                onLoad={() => setImgState('ok')}
                onError={() => setImgState('error')}
                draggable={false}
              />
            </div>
          </div>

          {/* Next */}
          <button
            className="preview-nav-btn preview-nav-next"
            onClick={goNext}
            disabled={safeIndex >= total - 1 && !hasMorePages}
            title="Next asset (→)"
          >
            <ChevronRight className="w-6 h-6" />
          </button>
        </div>

        {/* ── Fetch-next-page banner ── */}
        {safeIndex === total - 1 && hasMorePages && (
          <div className="preview-fetch-banner">
            {fetchingPage ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Loader2 className="w-4 h-4 animate-spin" style={{ color: '#818cf8' }} />
                <span>Loading Page {fetchingPage} assets…</span>
              </div>
            ) : fetchError ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <AlertCircle className="w-4 h-4" style={{ color: '#f87171' }} />
                <span style={{ color: '#f87171' }}>{fetchError}</span>
                <button
                  className="preview-fetch-btn"
                  onClick={() => nextUnprocessedPage && handleFetchNextPage(nextUnprocessedPage)}
                >
                  <RefreshCw className="w-3.5 h-3.5" /> Retry
                </button>
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span>
                  End of loaded assets · {totalPages - processedPages.size} more page{totalPages - processedPages.size !== 1 ? 's' : ''} available
                </span>
                <button
                  className="preview-fetch-btn"
                  onClick={() => nextUnprocessedPage && handleFetchNextPage(nextUnprocessedPage)}
                >
                  Load Page {nextUnprocessedPage} →
                </button>
              </div>
            )}
          </div>
        )}

        {/* ── Caption bar ── */}
        <div className="preview-caption-bar">
          <div className="preview-caption-text">
            {asset.caption
              ? <p>{asset.caption}</p>
              : <p className="preview-no-caption">No caption detected for this asset</p>
            }
          </div>
          {asset.caption && (
            <button className="preview-copy-btn" onClick={handleCopy}>
              <Copy className="w-3.5 h-3.5" />
              {copied ? 'Copied!' : 'Copy'}
            </button>
          )}
        </div>

        {/* ── Thumbnail strip ── */}
        <div className="preview-strip" ref={thumbStripRef}>
          {assets.map((a, i) => {
            const isActive = i === safeIndex;
            // Show a page-break separator between different pages
            const prevPage = i > 0 ? (assets[i - 1]?.page ?? 1) : null;
            const thisPage = a.page ?? 1;
            const showPageSep = prevPage !== null && thisPage !== prevPage;
            return (
              <React.Fragment key={a.id}>
                {showPageSep && (
                  <div className="preview-strip-sep" title={`Page ${thisPage}`}>
                    <span>p{thisPage}</span>
                  </div>
                )}
                <button
                  className={`preview-thumb ${isActive ? 'preview-thumb-active' : ''}`}
                  onClick={() => goTo(i)}
                  title={a.figure_no || `Asset ${i + 1} · Page ${a.page ?? 1}`}
                >
                  <img
                    src={`${API_BASE}${a.image_url}`}
                    alt={a.figure_no || `Asset ${i + 1}`}
                    loading="lazy"
                  />
                  {isActive && <div className="preview-thumb-ring" />}
                </button>
              </React.Fragment>
            );
          })}

          {/* Ghost "Load more" tile at end if more pages available */}
          {hasMorePages && (
            <button
              className="preview-thumb preview-thumb-load-more"
              onClick={() => nextUnprocessedPage && handleFetchNextPage(nextUnprocessedPage)}
              title={`Load Page ${nextUnprocessedPage}`}
              disabled={!!fetchingPage}
            >
              {fetchingPage
                ? <Loader2 className="w-4 h-4 animate-spin" style={{ color: '#818cf8' }} />
                : <span className="preview-thumb-more-label">+p{nextUnprocessedPage}</span>
              }
            </button>
          )}
        </div>

        {/* ── Footer ── */}
        <div className="preview-footer">
          <span className="preview-counter">
            {safeIndex + 1} / {total}
            {hasMorePages && <span style={{ color: 'hsl(220,10%,35%)', marginLeft: 6 }}>({totalPages - processedPages.size} pages unloaded)</span>}
          </span>
          <span className="preview-keys">← → navigate &nbsp;·&nbsp; +/− zoom &nbsp;·&nbsp; 0 reset &nbsp;·&nbsp; Esc close</span>
        </div>

      </div>
    </div>
  );
};

export default AssetPreviewModal;
