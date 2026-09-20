"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import type { ApplyOperationsResponse, EditOperation, Timeline, TimelineDocument, TimelineState, TimelineVersion } from "@/lib/types";

export const timelineKey = (projectId: string, timelineId?: string | null) => ["timeline", projectId, timelineId ?? "primary"] as const;

export function useTimeline(projectId: string | undefined, timelineId?: string | null) {
  return useQuery({
    queryKey: timelineKey(projectId ?? "", timelineId),
    queryFn: () => apiGet<TimelineState>(`/projects/${projectId}/timeline`, { timeline_id: timelineId ?? undefined }),
    enabled: !!projectId,
  });
}

export function useTimelines(projectId: string | undefined) {
  return useQuery({ queryKey: ["timelines", projectId], queryFn: () => apiGet<Timeline[]>(`/projects/${projectId}/timelines`), enabled: !!projectId });
}

export function useTimelineVersions(projectId: string | undefined, timelineId?: string | null) {
  return useQuery({
    queryKey: ["timeline-versions", projectId, timelineId ?? "primary"],
    queryFn: () => apiGet<TimelineVersion[]>(`/projects/${projectId}/timeline/versions`, { timeline_id: timelineId ?? undefined }),
    enabled: !!projectId,
  });
}

export function useTimelineMutations(projectId: string, timelineId?: string | null) {
  const qc = useQueryClient();
  const key = timelineKey(projectId, timelineId);
  const q = { timeline_id: timelineId ?? undefined };
  const settle = (state: TimelineState) => {
    qc.setQueryData(key, state);
    qc.invalidateQueries({ queryKey: ["timeline-versions", projectId] });
  };
  const applyOps = useMutation({
    mutationFn: (body: { operations: EditOperation[]; label?: string; source?: string }) => apiPost<ApplyOperationsResponse>(`/projects/${projectId}/timeline/operations`, body, q),
    onSuccess: (res) => settle(res.state),
  });
  const save = useMutation({
    mutationFn: (body: { document: TimelineDocument; label?: string }) => apiPut<TimelineState>(`/projects/${projectId}/timeline`, body, q),
    onSuccess: settle,
  });
  const undo = useMutation({ mutationFn: () => apiPost<TimelineState>(`/projects/${projectId}/timeline/undo`, undefined, q), onSuccess: settle });
  const redo = useMutation({ mutationFn: () => apiPost<TimelineState>(`/projects/${projectId}/timeline/redo`, undefined, q), onSuccess: settle });
  const restore = useMutation({ mutationFn: (versionId: string) => apiPost<TimelineState>(`/projects/${projectId}/timeline/versions/${versionId}/restore`), onSuccess: settle });
  return { applyOps, save, undo, redo, restore };
}
