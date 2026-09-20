"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import type { AnalysisResult, Job, Scene, Transcript } from "@/lib/types";
import { useJobsStore } from "@/stores/jobs";

export type AnalysisStep = "transcription" | "audio" | "scenes" | "content" | "vision" | "highlights" | "thumbnails";

export interface AIStatus {
  preferred: string;
  fallback: string | null;
  available: string[];
  configured: boolean;
  models: Record<string, { planner: string; vision: string }>;
  transcription: { provider: string; local_enabled: boolean; diarization: boolean; available: boolean };
}

export function useTranscript(projectId: string | undefined, assetId?: string | null) {
  return useQuery({
    queryKey: ["transcript", projectId, assetId ?? "primary"],
    queryFn: () => apiGet<Transcript | null>(`/projects/${projectId}/transcript`, { asset_id: assetId ?? undefined }),
    enabled: !!projectId,
  });
}

export function useAnalysis(projectId: string | undefined, kinds?: string[]) {
  return useQuery({
    queryKey: ["analysis", projectId, kinds?.join(",") ?? "all"],
    queryFn: async () => {
      const params = new URLSearchParams();
      for (const k of kinds ?? []) params.append("kind", k);
      const qs = params.toString();
      return apiGet<AnalysisResult[]>(`/projects/${projectId}/analysis${qs ? `?${qs}` : ""}`);
    },
    enabled: !!projectId,
  });
}

export function useScenes(projectId: string | undefined) {
  return useQuery({ queryKey: ["scenes", projectId], queryFn: () => apiGet<Scene[]>(`/projects/${projectId}/scenes`), enabled: !!projectId });
}

export function useAIStatus(projectId: string | undefined) {
  return useQuery({ queryKey: ["ai-status", projectId], queryFn: () => apiGet<AIStatus>(`/projects/${projectId}/ai-status`), enabled: !!projectId, staleTime: 60_000 });
}

export function useRunAnalysis(projectId: string) {
  const upsertMany = useJobsStore((s) => s.upsertMany);
  return useMutation({
    mutationFn: (body: { steps: AnalysisStep[]; asset_id?: string | null; language?: string | null; force?: boolean }) => apiPost<{ jobs: Job[] }>(`/projects/${projectId}/analyze`, body),
    onSuccess: (res) => upsertMany(res.jobs),
  });
}

export function useTranscriptMutations(projectId: string) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["transcript", projectId] });
  const updateSegment = useMutation({ mutationFn: ({ id, text }: { id: string; text: string }) => apiPatch(`/projects/${projectId}/transcript/segments/${id}`, { text }), onSuccess: invalidate });
  const updateWord = useMutation({ mutationFn: ({ id, ...body }: { id: string; text?: string; is_filler?: boolean }) => apiPatch(`/projects/${projectId}/transcript/words/${id}`, body), onSuccess: invalidate });
  const renameSpeaker = useMutation({ mutationFn: ({ id, display_name }: { id: string; display_name: string }) => apiPatch(`/projects/${projectId}/transcript/speakers/${id}`, { display_name }), onSuccess: invalidate });
  return { updateSegment, updateWord, renameSpeaker };
}

export function useActiveAnalysisJobs(projectId: string) {
  const jobs = useJobsStore((s) => s.jobs);
  return Object.values(jobs).filter((j) => j.project_id === projectId && (j.status === "QUEUED" || j.status === "RUNNING") && ["TRANSCRIPTION", "AUDIO_ANALYSIS", "SCENE_DETECTION", "CONTENT_ANALYSIS", "VISION_ANALYSIS", "HIGHLIGHT_DETECTION"].includes(j.type));
}
