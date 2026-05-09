import { create } from 'zustand';

export interface Detection {
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
  detections: Detection[];                      // current page only (for viewer overlay)
  detectionsByPage: Record<number, Detection[]>; // accumulated cross-page cache
  isLoading: boolean;
  selectedAssetId: string | null;
  pageDimensions: { width: number; height: number };

  setSession: (id: string, pages: number) => void;
  setCurrentPage: (page: number) => void;
  setDetections: (detections: Detection[], dimensions: { width: number; height: number }) => void;
  addPageToCache: (page: number, detections: Detection[]) => void;
  clearSession: () => void;
  setLoading: (loading: boolean) => void;
  setSelectedAssetId: (id: string | null) => void;

  /** Flat sorted list of every detection across all processed pages */
  getAllDetections: () => Detection[];
  isPageInCache: (page: number) => boolean;
}

export const useStore = create<AppState>((set, get) => ({
  sessionId: null,
  totalPages: 0,
  currentPage: 1,
  detections: [],
  detectionsByPage: {},
  pageDimensions: { width: 595, height: 842 },
  isLoading: false,
  selectedAssetId: null,

  setSession: (id, pages) =>
    set({ sessionId: id, totalPages: pages, detectionsByPage: {}, detections: [], currentPage: 1 }),

  setCurrentPage: (page) => set({ currentPage: page }),

  setDetections: (detections, dimensions) =>
    set((state) => ({
      detections,
      pageDimensions: dimensions,
      // Also update the page cache so modal has access
      detectionsByPage: {
        ...state.detectionsByPage,
        [state.currentPage]: detections,
      },
    })),

  addPageToCache: (page, detections) =>
    set((state) => ({
      detectionsByPage: { ...state.detectionsByPage, [page]: detections },
    })),

  clearSession: () =>
    set({ sessionId: null, totalPages: 0, currentPage: 1, detections: [], detectionsByPage: {} }),

  setLoading: (loading) => set({ isLoading: loading }),
  setSelectedAssetId: (id) => set({ selectedAssetId: id }),

  getAllDetections: () => {
    const { detectionsByPage } = get();
    return Object.entries(detectionsByPage)
      .sort(([a], [b]) => Number(a) - Number(b))
      .flatMap(([, dets]) => dets);
  },

  isPageInCache: (page) => page in get().detectionsByPage,
}));
