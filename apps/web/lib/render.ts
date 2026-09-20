"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";
import type { ExportOut, ExportPreset, RenderOut } from "@/lib/types";
import { useJobsStore } from "@/stores/jobs";

export function usePresets() {
  return useQuery({ queryKey: ["render-presets"], queryFn: () => apiGet<ExportPreset[]>("/render/presets"), staleTime: Infinity });
}

export function useRenders(projectId: string | undefined) {
  return useQuery({
    queryKey: ["renders", projectId],
    queryFn: () => apiGet<RenderOut[]>(`/projects/${projectId}/renders`),
    enabled: !!projectId,
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "QUEUED" || r.status === "RUNNING") ? 3000 : false),
  });
}

export function useExports(projectId: string | undefined) {
  return useQuery({
    queryKey: ["exports", projectId],
    queryFn: () => apiGet<ExportOut[]>(`/projects/${projectId}/exports`),
    enabled: !!projectId,
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "QUEUED" || r.status === "RUNNING") ? 3000 : false),
  });
}

export function useRenderMutations(projectId: string) {
  const qc = useQueryClient();
  const upsert = useJobsStore((s) => s.upsert);
  const render = useMutation({
    mutationFn: (body: { preset: string; timeline_id?: string | null; kind?: "final" | "preview"; settings?: Record<string, unknown> }) => apiPost<RenderOut>(`/projects/${projectId}/render`, body),
    onSuccess: (r) => {
      if (r.job_id) upsert({ id: r.job_id, project_id: projectId, type: "RENDERING", status: "QUEUED", progress: 0, message: "" });
      qc.invalidateQueries({ queryKey: ["renders", projectId] });
    },
  });
  const exportTimeline = useMutation({
    mutationFn: (body: { format: string; preset?: string; timeline_id?: string | null; filename?: string | null; settings?: Record<string, unknown> }) => apiPost<ExportOut>(`/projects/${projectId}/exports`, body),
    onSuccess: (e) => {
      if (e.job_id) upsert({ id: e.job_id, project_id: projectId, type: "EXPORT", status: "QUEUED", progress: 0, message: "" });
      qc.invalidateQueries({ queryKey: ["exports", projectId] });
    },
  });
  return { render, exportTimeline };
}
