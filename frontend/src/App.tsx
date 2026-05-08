import React, { useState, useEffect } from 'react';
import axios from 'axios';
import {
  Upload,
  ChevronLeft,
  ChevronRight,
  FileText,
  Layers,
  FileDown,
  Tag,
  Download,
  Loader2,
} from 'lucide-react';
import PdfViewer from './components/PdfViewer';
import AssetList from './components/AssetList';
import { useStore } from './store/useStore';

const API_BASE = 'http://localhost:8001';

const App: React.FC = () => {
  const {
    sessionId,
    totalPages,
    currentPage,
    setSession,
    setCurrentPage,
    setDetections,
    isLoading,
    setLoading,
  } = useStore();

  const [file, setFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [filename, setFilename] = useState('');
  const [assetPanelWidth, setAssetPanelWidth] = useState(380);
  const [isResizing, setIsResizing] = useState(false);
  const [exportProgress, setExportProgress] = useState<{ current: number; total: number; status: string } | null>(null);

  const startResizing = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
  };

  const stopResizing = () => {
    setIsResizing(false);
  };

  const resize = (e: MouseEvent) => {
    if (isResizing) {
      const newWidth = window.innerWidth - e.clientX;
      if (newWidth > 300 && newWidth < 800) {
        setAssetPanelWidth(newWidth);
      }
    }
  };

  useEffect(() => {
    if (isResizing) {
      window.addEventListener('mousemove', resize);
      window.addEventListener('mouseup', stopResizing);
    } else {
      window.removeEventListener('mousemove', resize);
      window.removeEventListener('mouseup', stopResizing);
    }
    return () => {
      window.removeEventListener('mousemove', resize);
      window.removeEventListener('mouseup', stopResizing);
    };
  }, [isResizing]);

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const uploadedFile = event.target.files?.[0];
    if (!uploadedFile) return;

    setFile(uploadedFile);
    setFilename(uploadedFile.name);
    setIsUploading(true);

    const formData = new FormData();
    formData.append('file', uploadedFile);

    try {
      const response = await axios.post(`${API_BASE}/upload`, formData);
      setSession(response.data.session_id, response.data.total_pages);
      processCurrentPage(response.data.session_id, 1);
    } catch (error) {
      console.error('Upload failed', error);
      alert('Failed to upload PDF. Make sure the backend is running at http://localhost:8001');
    } finally {
      setIsUploading(false);
    }
  };

  const processCurrentPage = async (sid: string, pageNum: number) => {
    setLoading(true);
    try {
      const response = await axios.get(`${API_BASE}/process-page/${sid}/${pageNum}`);
      setDetections(response.data.detections, {
        width: response.data.width,
        height: response.data.height,
      });
    } catch (error) {
      console.error('Processing failed', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (sessionId) {
      processCurrentPage(sessionId, currentPage);
    }
  }, [currentPage]);

  const goToNextPage = () => {
    if (currentPage < totalPages) setCurrentPage(currentPage + 1);
  };

  const goToPrevPage = () => {
    if (currentPage > 1) setCurrentPage(currentPage - 1);
  };

  const handleExportAll = async () => {
    if (!sessionId) return;

    setIsExporting(true);
    setExportProgress({ current: 0, total: totalPages, status: 'starting' });

    // Start polling for progress
    const pollInterval = setInterval(async () => {
      try {
        const res = await axios.get(`${API_BASE}/export-status/${sessionId}`);
        setExportProgress(res.data);
        if (res.data.status === 'complete') {
          clearInterval(pollInterval);
        }
      } catch (err) {
        console.error('Progress polling failed', err);
      }
    }, 800);

    try {
      const response = await axios.get(`${API_BASE}/export-document/${sessionId}`, {
        responseType: 'blob',
      });

      const zipName = filename
        ? filename.replace(/\.pdf$/i, '') + '_full_assets.zip'
        : 'full_report_assets.zip';

      const url = URL.createObjectURL(new Blob([response.data], { type: 'application/zip' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = zipName;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Export failed', err);
      alert('Export failed. The document might be too large or the server disconnected.');
    } finally {
      clearInterval(pollInterval);
      setIsExporting(false);
      setExportProgress(null);
    }
  };

  return (
    <div className="app-shell">
      {/* Upload progress overlay */}
      {isUploading && (
        <div className="upload-overlay">
          <div className="upload-card">
            <Loader2 className="w-10 h-10 text-indigo-400 animate-spin" />
            <div>
              <p className="font-bold text-white text-base mb-1">Uploading & Processing</p>
              <p className="text-sm" style={{ color: 'hsl(220,10%,55%)' }}>
                {filename || 'document.pdf'}
              </p>
            </div>
            <div className="w-48 h-1 rounded-full bg-white/10 overflow-hidden">
              <div className="h-full w-1/2 rounded-full bg-indigo-500 animate-pulse" />
            </div>
          </div>
        </div>
      )}

      {/* Export progress overlay */}
      {isExporting && (
        <div className="upload-overlay">
          <div className="upload-card">
            <div className="relative">
              <Loader2 className="w-10 h-10 text-indigo-400 animate-spin" />
              {exportProgress && exportProgress.status !== 'zipping' && (
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="text-[10px] font-black text-white">
                    {Math.round(((exportProgress.current || 0) / (exportProgress.total || totalPages)) * 100)}%
                  </span>
                </div>
              )}
            </div>
            <div style={{ textAlign: 'center' }}>
              <p className="font-bold text-white text-base mb-1">
                {exportProgress?.status === 'zipping' ? 'Finalizing ZIP Package' : 'Exporting Document Assets'}
              </p>
              <p className="text-sm" style={{ color: 'hsl(220,10%,55%)' }}>
                {exportProgress?.status === 'zipping'
                  ? 'Organizing Figures & Tables...'
                  : `Processing Page ${exportProgress?.current || 0} of ${exportProgress?.total || totalPages}`}
              </p>
            </div>
            <div className="w-64 h-1.5 rounded-full bg-white/10 overflow-hidden mt-2">
              <div
                className="h-full bg-indigo-500 transition-all duration-300"
                style={{
                  width: exportProgress?.status === 'zipping'
                    ? '95%'
                    : `${((exportProgress?.current || 0) / (exportProgress?.total || 1)) * 100}%`
                }}
              />
            </div>
          </div>
        </div>
      )}

      {/* ── Header ── */}
      <header className="app-header">
        {/* Brand */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div className="logo-mark">
            <Layers className="w-5 h-5 text-white" />
          </div>
          <div className="logo-text">
            <h1>VisionExtract</h1>
            <p>Intelligence Engine</p>
          </div>
        </div>

        {/* Right controls */}
        {sessionId ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            {/* Status */}
            <div className="status-pill">
              <div className={isLoading ? 'status-dot-loading' : 'status-dot-active'} />
              {isLoading ? 'Processing…' : 'Analysis Ready'}
            </div>

            {/* Page nav */}
            <div className="page-nav">
              <button className="nav-btn" onClick={goToPrevPage} disabled={currentPage === 1} aria-label="Previous page">
                <ChevronLeft className="w-4 h-4" />
              </button>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, fontWeight: 700 }}>
                <span style={{ color: 'white' }}>{currentPage}</span>
                <span style={{ color: 'rgba(255,255,255,0.25)', fontSize: 11 }}>/</span>
                <span style={{ color: 'rgba(255,255,255,0.45)' }}>{totalPages}</span>
              </div>
              <button className="nav-btn" onClick={goToNextPage} disabled={currentPage === totalPages} aria-label="Next page">
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>

            {/* File info */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, maxWidth: 180, overflow: 'hidden' }}>
              <FileText className="w-4 h-4 flex-shrink-0" style={{ color: 'rgba(255,255,255,0.4)' }} />
              <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.5)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {filename}
              </span>
            </div>

            {/* Export */}
            <button
              className="btn-secondary"
              style={{ fontSize: 12, opacity: isExporting ? 0.7 : 1, cursor: isExporting ? 'not-allowed' : 'pointer' }}
              onClick={handleExportAll}
              disabled={isExporting}
              title="Export all visual assets from the entire document as a ZIP"
            >
              {isExporting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <FileDown className="w-4 h-4" />
              )}
              {isExporting
                ? (exportProgress?.status === 'zipping'
                  ? 'Finalizing ZIP...'
                  : `Processing Page ${exportProgress?.current || 0}/${exportProgress?.total || totalPages}`)
                : 'Export Full Report'}
            </button>

            {/* Upload new */}
            <label className="btn-primary" style={{ fontSize: 12 }}>
              <Upload className="w-4 h-4" />
              New File
              <input type="file" className="hidden" accept=".pdf" onChange={handleUpload} />
            </label>
          </div>
        ) : (
          <label className="btn-primary">
            <Upload className="w-4 h-4" />
            Upload PDF Report
            <input type="file" className="hidden" accept=".pdf" onChange={handleUpload} />
          </label>
        )}
      </header>

      {/* ── Main ── */}
      <main className="main-content">
        {sessionId ? (
          <>
            {/* PDF panel */}
            <div className="pdf-panel">
              <PdfViewer file={file} />
            </div>

            {/* Resize handle */}
            <div
              className={`resize-handle ${isResizing ? 'is-resizing' : ''}`}
              onMouseDown={startResizing}
            />

            {/* Asset panel */}
            <div
              className="asset-panel"
              style={{ width: assetPanelWidth, minWidth: 300, flex: 'none' }}
            >
              <AssetList />
            </div>
          </>
        ) : (
          /* Landing hero */
          <div className="landing-hero">
            <div className="hero-glow" />

            <div className="hero-icon-wrap" style={{ position: 'relative', zIndex: 1 }}>
              <FileText className="w-10 h-10" style={{ color: '#818cf8' }} />
            </div>

            <h2 className="hero-title" style={{ position: 'relative', zIndex: 1 }}>
              Process Your<br />PDF Reports
            </h2>
            <p className="hero-subtitle" style={{ position: 'relative', zIndex: 1 }}>
              Upload technical documents to automatically detect, extract, and categorize
              figures, charts, maps, and tables with AI precision.
            </p>

            <label className="btn-primary" style={{ fontSize: 14, padding: '12px 28px', marginBottom: 40, position: 'relative', zIndex: 1 }}>
              <Upload className="w-5 h-5" />
              Upload PDF Report
              <input type="file" className="hidden" accept=".pdf" onChange={handleUpload} />
            </label>

            <div className="feature-grid" style={{ position: 'relative', zIndex: 1 }}>
              {[
                { icon: Layers, label: 'Multi-Asset\nDetection' },
                { icon: Tag, label: 'Smart\nCaptioning' },
                { icon: Download, label: 'Batch\nExport' },
              ].map((feature, i) => (
                <div key={i} className="feature-card">
                  <div className="feature-icon-wrap">
                    <feature.icon className="w-5 h-5" style={{ color: '#818cf8' }} />
                  </div>
                  <span className="feature-label">{feature.label.replace('\\n', '\n')}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
};

export default App;
