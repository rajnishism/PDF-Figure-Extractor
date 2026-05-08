import React from 'react';
import { useStore } from '../store/useStore';
import { Download, ExternalLink, Tag, Info, Copy } from 'lucide-react';

const AssetList: React.FC = () => {
  const { detections, selectedAssetId, setSelectedAssetId } = useStore();

  const handleDownload = (url: string, filename: string) => {
    const link = document.createElement('a');
    link.href = `http://localhost:8001${url}`;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleCopyCaption = (caption: string) => {
    navigator.clipboard.writeText(caption).catch(() => {});
  };

  if (detections.length === 0) {
    return (
      <>
        <div className="asset-panel-header">
          <h2>
            <Tag className="w-4 h-4" style={{ color: '#818cf8' }} />
            Extracted Assets
          </h2>
          <span className="badge">0 found</span>
        </div>
        <div className="empty-state">
          <div className="empty-icon">
            <Info className="w-6 h-6" style={{ color: 'rgba(255,255,255,0.2)' }} />
          </div>
          <p style={{ fontSize: 13, fontWeight: 600, color: 'rgba(255,255,255,0.7)' }}>
            No visual assets on this page
          </p>
          <p style={{ fontSize: 11, color: 'hsl(220,10%,45%)', lineHeight: 1.5 }}>
            Try navigating to a page<br />with figures or tables
          </p>
        </div>
      </>
    );
  }

  return (
    <>
      {/* Panel header */}
      <div className="asset-panel-header">
        <h2>
          <Tag className="w-4 h-4" style={{ color: '#818cf8' }} />
          Extracted Assets
        </h2>
        <span className="badge">{detections.length} found</span>
      </div>

      {/* Scrollable list */}
      <div className="asset-list">
        {detections.map((asset, idx) => (
          <div
            key={asset.id}
            id={`asset-${asset.id}`}
            onClick={() => setSelectedAssetId(asset.id)}
            className={`asset-card fade-in ${selectedAssetId === asset.id ? 'selected' : ''}`}
            style={{ animationDelay: `${idx * 50}ms` }}
          >
            {/* Thumbnail */}
            <div className="asset-thumbnail">
              <img
                src={`http://localhost:8001${asset.image_url}`}
                alt={asset.caption || 'Extracted asset'}
                loading="lazy"
              />
              <div className="thumbnail-overlay">
                <button
                  className="icon-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    window.open(`http://localhost:8001${asset.image_url}`, '_blank');
                  }}
                  title="Open in new tab"
                >
                  <ExternalLink className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Info */}
            <div className="asset-info">
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 4 }}>
                <p className="asset-figure-no">{asset.figure_no || 'Visual Asset'}</p>
                <span className="asset-type-chip">{asset.type}</span>
              </div>
              <p className="asset-caption">{asset.caption || 'No caption detected'}</p>

              {/* Confidence bar */}
              {asset.confidence !== undefined && (
                <div style={{ marginTop: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                    <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.3)' }}>
                      Confidence
                    </span>
                    <span style={{
                      fontSize: 9, fontWeight: 800,
                      color: asset.confidence >= 0.75 ? '#34d399' : asset.confidence >= 0.5 ? '#fbbf24' : '#f87171'
                    }}>
                      {Math.round(asset.confidence * 100)}%
                    </span>
                  </div>
                  <div style={{ height: 3, borderRadius: 99, background: 'rgba(255,255,255,0.07)', overflow: 'hidden' }}>
                    <div style={{
                      height: '100%',
                      width: `${asset.confidence * 100}%`,
                      borderRadius: 99,
                      background: asset.confidence >= 0.75
                        ? 'linear-gradient(90deg, #34d399, #10b981)'
                        : asset.confidence >= 0.5
                        ? 'linear-gradient(90deg, #fbbf24, #f59e0b)'
                        : 'linear-gradient(90deg, #f87171, #ef4444)',
                      transition: 'width 0.6s ease',
                    }} />
                  </div>
                </div>
              )}
            </div>

            {/* Actions */}
            <div className="asset-actions">
              <button
                className="btn-download"
                onClick={(e) => {
                  e.stopPropagation();
                  handleDownload(asset.image_url, `${asset.figure_no || asset.id}.png`);
                }}
              >
                <Download className="w-3.5 h-3.5" />
                Download
              </button>
              <button
                className="btn-icon-sm"
                onClick={(e) => {
                  e.stopPropagation();
                  handleCopyCaption(asset.caption || '');
                }}
                title="Copy caption"
              >
                <Copy className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </>
  );
};

export default AssetList;
