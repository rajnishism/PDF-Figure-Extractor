import { create } from 'zustand';

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

interface AppState {
  sessionId: string | null;
  totalPages: number;
  currentPage: number;
  detections: Detection[];
  isLoading: boolean;
  selectedAssetId: string | null;
  pageDimensions: { width: number; height: number };
  setSession: (id: string, pages: number) => void;
  setCurrentPage: (page: number) => void;
  setDetections: (detections: Detection[], dimensions: { width: number; height: number }) => void;
  setLoading: (loading: boolean) => void;
  setSelectedAssetId: (id: string | null) => void;
}

export const useStore = create<AppState>((set) => ({
  sessionId: null,
  totalPages: 0,
  currentPage: 1,
  detections: [],
  pageDimensions: { width: 595, height: 842 },
  isLoading: false,
  selectedAssetId: null,
  setSession: (id, pages) => set({ sessionId: id, totalPages: pages }),
  setCurrentPage: (page) => set({ currentPage: page }),
  setDetections: (detections, dimensions) => set({ detections, pageDimensions: dimensions }),
  setLoading: (loading) => set({ isLoading: loading }),
  setSelectedAssetId: (id) => set({ selectedAssetId: id }),
}));
