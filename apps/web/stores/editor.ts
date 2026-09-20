import { create } from "zustand";

export type LeftTab = "media" | "transcript";
export type RightTab = "chat" | "inspector" | "versions" | "export";

interface EditorState {
  projectId: string | null;
  timelineId: string | null;
  leftTab: LeftTab;
  rightTab: RightTab;
  selectedAssetId: string | null;
  selectedClipIds: string[];
  previewSource: { kind: "timeline" } | { kind: "asset"; assetId: string };
  playhead: number;
  playing: boolean;
  zoom: number; // pixels per second
  scrollX: number;
  snapping: boolean;
  set: (patch: Partial<EditorState>) => void;
  selectClip: (id: string | null, additive?: boolean) => void;
  setPlayhead: (t: number) => void;
}

export const useEditorStore = create<EditorState>((set) => ({
  projectId: null,
  timelineId: null,
  leftTab: "media",
  rightTab: "chat",
  selectedAssetId: null,
  selectedClipIds: [],
  previewSource: { kind: "timeline" },
  playhead: 0,
  playing: false,
  zoom: 40,
  scrollX: 0,
  snapping: true,
  set: (patch) => set(patch),
  selectClip: (id, additive) =>
    set((s) => {
      if (id === null) return { selectedClipIds: [] };
      if (additive) return { selectedClipIds: s.selectedClipIds.includes(id) ? s.selectedClipIds.filter((x) => x !== id) : [...s.selectedClipIds, id] };
      return { selectedClipIds: [id] };
    }),
  setPlayhead: (t) => set({ playhead: Math.max(0, t) }),
}));
