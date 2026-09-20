import { create } from "zustand";

export type LeftTab = "media" | "transcript";
export type RightTab = "chat" | "inspector" | "versions" | "export";

export interface DragState {
  kind: "move" | "trim-in" | "trim-out" | "playhead" | "asset";
  clipId?: string;
  assetId?: string;
}

interface EditorState {
  projectId: string | null;
  timelineId: string | null;
  leftTab: LeftTab;
  rightTab: RightTab;
  selectedAssetId: string | null;
  selectedClipIds: string[];
  selectedMarkerId: string | null;
  previewSource: { kind: "timeline" } | { kind: "asset"; assetId: string };
  playhead: number;
  playing: boolean;
  playbackRate: number;
  volume: number;
  muted: boolean;
  zoom: number; // pixels per second
  scrollX: number;
  snapping: boolean;
  drag: DragState | null;
  /** A transient client-side document while dragging (null = use server document). */
  hoverTime: number | null;
  set: (patch: Partial<EditorState>) => void;
  selectClip: (id: string | null, additive?: boolean) => void;
  setPlayhead: (t: number) => void;
  togglePlay: () => void;
}

export const useEditorStore = create<EditorState>((set) => ({
  projectId: null,
  timelineId: null,
  leftTab: "media",
  rightTab: "chat",
  selectedAssetId: null,
  selectedClipIds: [],
  selectedMarkerId: null,
  previewSource: { kind: "timeline" },
  playhead: 0,
  playing: false,
  playbackRate: 1,
  volume: 1,
  muted: false,
  zoom: 40,
  scrollX: 0,
  snapping: true,
  drag: null,
  hoverTime: null,
  set: (patch) => set(patch),
  selectClip: (id, additive) =>
    set((s) => {
      if (id === null) return { selectedClipIds: [], selectedMarkerId: null };
      if (additive) return { selectedClipIds: s.selectedClipIds.includes(id) ? s.selectedClipIds.filter((x) => x !== id) : [...s.selectedClipIds, id] };
      return { selectedClipIds: [id], selectedMarkerId: null, rightTab: s.rightTab === "chat" ? "inspector" : s.rightTab };
    }),
  setPlayhead: (t) => set({ playhead: Math.max(0, t), previewSource: { kind: "timeline" } }),
  togglePlay: () => set((s) => ({ playing: !s.playing, previewSource: { kind: "timeline" } })),
}));
