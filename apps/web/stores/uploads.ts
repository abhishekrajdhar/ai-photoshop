import { create } from "zustand";
import { uploadFile, type UploadHandle } from "@/lib/assets";
import type { MediaAsset } from "@/lib/types";

export interface UploadItem {
  id: string;
  projectId: string;
  file: File;
  kind: string;
  progress: number;
  sent: number;
  status: "queued" | "uploading" | "processing" | "done" | "duplicate" | "error" | "cancelled";
  error?: string;
  asset?: MediaAsset;
  jobId?: string | null;
  handle?: UploadHandle;
  startedAt: number;
}

interface UploadsState {
  items: Record<string, UploadItem>;
  enqueue: (projectId: string, files: File[], kind?: string) => void;
  cancel: (id: string) => void;
  retry: (id: string) => void;
  dismiss: (id: string) => void;
  clearFinished: () => void;
  onAssetReady: (assetId: string) => void;
  onAssetFailed: (assetId: string, error: string) => void;
}

const MAX_PARALLEL_FILES = 2;

export const useUploadsStore = create<UploadsState>((set, get) => {
  const pump = () => {
    const items = Object.values(get().items);
    const active = items.filter((i) => i.status === "uploading").length;
    const queued = items.filter((i) => i.status === "queued").sort((a, b) => a.startedAt - b.startedAt);
    for (const item of queued.slice(0, Math.max(0, MAX_PARALLEL_FILES - active))) start(item.id);
  };
  const patch = (id: string, data: Partial<UploadItem>) =>
    set((s) => (s.items[id] ? { items: { ...s.items, [id]: { ...s.items[id]!, ...data } } } : s));

  const start = (id: string) => {
    const item = get().items[id];
    if (!item) return;
    const handle = uploadFile(item.projectId, item.file, {
      kind: item.kind,
      onProgress: (progress, sent) => patch(id, { progress, sent }),
    });
    patch(id, { status: "uploading", handle, error: undefined });
    handle.promise
      .then(({ asset, job_id, duplicate }) => {
        patch(id, { asset, jobId: job_id, status: duplicate ? "duplicate" : "processing", progress: 1 });
      })
      .catch((err: Error) => {
        patch(id, { status: err.name === "AbortError" ? "cancelled" : "error", error: err.message });
      })
      .finally(pump);
  };

  return {
    items: {},
    enqueue: (projectId, files, kind = "original") => {
      const additions: Record<string, UploadItem> = {};
      for (const file of files) {
        const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        additions[id] = { id, projectId, file, kind, progress: 0, sent: 0, status: "queued", startedAt: Date.now() + Object.keys(additions).length };
      }
      set((s) => ({ items: { ...s.items, ...additions } }));
      pump();
    },
    cancel: (id) => {
      get().items[id]?.handle?.cancel();
      patch(id, { status: "cancelled" });
      pump();
    },
    retry: (id) => {
      patch(id, { status: "queued", progress: 0, sent: 0, error: undefined });
      pump();
    },
    dismiss: (id) =>
      set((s) => {
        const items = { ...s.items };
        delete items[id];
        return { items };
      }),
    clearFinished: () =>
      set((s) => ({ items: Object.fromEntries(Object.entries(s.items).filter(([, i]) => !["done", "duplicate", "cancelled", "error"].includes(i.status))) })),
    onAssetReady: (assetId) => {
      const item = Object.values(get().items).find((i) => i.asset?.id === assetId);
      if (item) patch(item.id, { status: "done" });
    },
    onAssetFailed: (assetId, error) => {
      const item = Object.values(get().items).find((i) => i.asset?.id === assetId);
      if (item) patch(item.id, { status: "error", error });
    },
  };
});
