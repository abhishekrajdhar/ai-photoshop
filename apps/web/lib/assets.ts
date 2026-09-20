"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import type { MediaAsset } from "@/lib/types";

export function useAssets(projectId: string | undefined) {
  return useQuery({
    queryKey: ["assets", projectId],
    queryFn: () => apiGet<MediaAsset[]>(`/projects/${projectId}/assets`),
    enabled: !!projectId,
    refetchInterval: (q) => (q.state.data?.some((a) => a.status === "pending" || a.status === "processing") ? 4000 : false),
  });
}

export function useAssetActions(projectId: string) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["assets", projectId] });
  const remove = useMutation({ mutationFn: (id: string) => apiDelete<{ ok: boolean }>(`/assets/${id}`), onSuccess: invalidate });
  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: string; filename?: string; role?: string; kind?: string }) => apiPatch<MediaAsset>(`/assets/${id}`, body),
    onSuccess: invalidate,
  });
  return { remove, update };
}

/* ── Chunked, resumable upload ───────────────────────────────────────────── */

export interface UploadHandle {
  promise: Promise<{ asset: MediaAsset; job_id: string | null; duplicate: boolean }>;
  cancel: () => void;
}

interface InitResponse {
  upload_id: string | null;
  chunk_size: number;
  total_chunks: number;
  received_chunks: number[];
  duplicate_of: MediaAsset | null;
}

async function sha256(file: File): Promise<string | null> {
  // Hash files up to 256 MB client-side to short-circuit duplicate uploads.
  if (file.size > 256 * 1024 * 1024 || !crypto?.subtle) return null;
  const buf = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function uploadFile(projectId: string, file: File, opts: { kind?: string; role?: string; onProgress?: (fraction: number, sent: number) => void } = {}): UploadHandle {
  const controller = new AbortController();
  const promise = (async () => {
    const client_hash = await sha256(file);
    const init = await apiPost<InitResponse>(`/projects/${projectId}/uploads`, {
      filename: file.name,
      mime_type: file.type || "application/octet-stream",
      size_bytes: file.size,
      client_hash,
      kind: opts.kind ?? "original",
      role: opts.role ?? null,
    });
    if (init.duplicate_of) {
      opts.onProgress?.(1, file.size);
      return { asset: init.duplicate_of, job_id: null, duplicate: true };
    }
    const uploadId = init.upload_id!;
    const received = new Set(init.received_chunks);
    const total = init.total_chunks;
    const chunkSize = init.chunk_size;
    let sent = received.size * chunkSize;
    const queue = Array.from({ length: total }, (_, i) => i).filter((i) => !received.has(i));
    const CONCURRENCY = 3;

    const sendChunk = async (index: number, attempt = 0): Promise<void> => {
      const blob = file.slice(index * chunkSize, Math.min(file.size, (index + 1) * chunkSize));
      try {
        await api(`/projects/${projectId}/uploads/${uploadId}/chunks/${index}`, { method: "PUT", body: blob, signal: controller.signal });
        sent += blob.size;
        opts.onProgress?.(Math.min(0.99, sent / file.size), sent);
      } catch (err) {
        if (controller.signal.aborted) throw err;
        if (attempt < 4) {
          await new Promise((r) => setTimeout(r, 500 * 2 ** attempt));
          return sendChunk(index, attempt + 1);
        }
        throw err;
      }
    };
    const workers = Array.from({ length: Math.min(CONCURRENCY, queue.length) }, async () => {
      while (queue.length) {
        const idx = queue.shift();
        if (idx === undefined) break;
        await sendChunk(idx);
      }
    });
    await Promise.all(workers);
    const done = await apiPost<{ asset: MediaAsset; job_id: string }>(`/projects/${projectId}/uploads/${uploadId}/complete`);
    opts.onProgress?.(1, file.size);
    return { asset: done.asset, job_id: done.job_id, duplicate: false };
  })();
  return { promise, cancel: () => controller.abort() };
}
