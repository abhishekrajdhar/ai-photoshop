"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import type { Highlight, Job } from "@/lib/types";
import { useJobsStore } from "@/stores/jobs";

export interface ThumbnailCandidate {
  asset_id: string;
  time: number;
  score: number;
  factors: Record<string, number>;
  face: { x: number; y: number; w: number; h: number } | null;
  url: string;
}

export function useHighlights(projectId: string | undefined) {
  return useQuery({ queryKey: ["highlights", projectId], queryFn: () => apiGet<Highlight[]>(`/projects/${projectId}/highlights`), enabled: !!projectId });
}

export function useThumbnails(projectId: string | undefined) {
  return useQuery({ queryKey: ["thumbnails", projectId], queryFn: () => apiGet<{ source_asset_id: string | null; candidates: ThumbnailCandidate[] }>(`/projects/${projectId}/thumbnails`), enabled: !!projectId });
}

export function useCreatorMutations(projectId: string) {
  const qc = useQueryClient();
  const upsertMany = useJobsStore((s) => s.upsertMany);
  const track = (res: { jobs: Job[] }) => upsertMany(res.jobs);
  const detectHighlights = useMutation({ mutationFn: (body: { count?: number; min_seconds?: number; max_seconds?: number; asset_id?: string | null }) => apiPost<{ jobs: Job[] }>(`/projects/${projectId}/highlights`, body), onSuccess: track });
  const generateShorts = useMutation({ mutationFn: (body: { count?: number; duration: 15 | 30 | 45 | 60 | 90; platform?: string; caption_preset?: string; reframe?: boolean; highlight_ids?: string[]; asset_id?: string | null; auto_render?: boolean; render_preset?: string | null }) => apiPost<{ jobs: Job[] }>(`/projects/${projectId}/shorts`, body), onSuccess: track });
  const generateThumbnails = useMutation({ mutationFn: () => apiPost<{ jobs: Job[] }>(`/projects/${projectId}/thumbnails`), onSuccess: track });
  const trackReframe = useMutation({ mutationFn: () => apiPost<{ jobs: Job[] }>(`/projects/${projectId}/reframe/track`), onSuccess: track });
  const resolveBroll = useMutation({
    mutationFn: (timelineId?: string | null) => apiPost<{ placed: unknown[]; unresolved: { marker_id: string; query: string }[] }>(`/projects/${projectId}/broll/resolve`, undefined, { timeline_id: timelineId ?? undefined }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["timeline", projectId] }),
  });
  const updateSequence = useMutation({
    mutationFn: (body: { caption_style?: Record<string, unknown>; audio?: Record<string, unknown>; aspect_ratio?: string; reframe_mode?: "center" | "track" | "off"; timeline_id?: string | null }) => apiPatch<{ version: number; document: unknown }>(`/projects/${projectId}/sequence`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["timeline", projectId] });
      qc.invalidateQueries({ queryKey: ["timeline-versions", projectId] });
    },
  });
  const multicamSync = useMutation({
    mutationFn: (body: { reference_asset_id: string; asset_ids: string[]; place_on_timeline: boolean }) => apiPost<{ offsets: { asset_id: string; filename: string; offset: number; confidence: number }[] }>(`/projects/${projectId}/multicam/sync`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["timeline", projectId] }),
  });
  return { detectHighlights, generateShorts, generateThumbnails, trackReframe, resolveBroll, updateSequence, multicamSync };
}

export function useAIUsage(projectId: string | undefined) {
  return useQuery({
    queryKey: ["ai-usage", projectId],
    queryFn: () => apiGet<{ total_cost_usd: number; total_requests: number; items: { provider: string; model: string; operation: string; requests: number; estimated_cost_usd: number }[] }>(`/projects/${projectId}/ai-usage`),
    enabled: !!projectId,
    staleTime: 30_000,
  });
}
