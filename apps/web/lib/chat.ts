"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";
import type { ChatMessage, ChatSession, EditOperation, TimelineDocument, TimelineState } from "@/lib/types";
import { timelineKey } from "@/lib/timeline";
import { useJobsStore } from "@/stores/jobs";

export interface ProposalPreview {
  document: TimelineDocument;
  duration_before: number;
  duration_after: number;
  applied: number;
  rejected: { operation: EditOperation; reason: string }[];
  removed_ranges: { start: number; end: number }[];
}

export function useChatSessions(projectId: string | undefined) {
  return useQuery({
    queryKey: ["chat", projectId],
    queryFn: () => apiGet<ChatSession[]>(`/projects/${projectId}/chat/sessions`),
    enabled: !!projectId,
    refetchInterval: (q) => (q.state.data?.some((s) => s.messages.some((m) => m.proposal?.status === "pending")) ? 3000 : false),
  });
}

export function useChatMutations(projectId: string) {
  const qc = useQueryClient();
  const upsert = useJobsStore((s) => s.upsert);
  const invalidate = () => qc.invalidateQueries({ queryKey: ["chat", projectId] });
  const send = useMutation({
    mutationFn: (body: { message: string; session_id?: string | null; asset_id?: string | null; timeline_id?: string | null }) =>
      apiPost<{ session: ChatSession; assistant_message: ChatMessage; job_id: string }>(`/projects/${projectId}/chat`, body),
    onSuccess: (res) => {
      upsert({ id: res.job_id, project_id: projectId, type: "EDIT_PLANNING", status: "QUEUED", progress: 0, message: "" });
      invalidate();
    },
  });
  const edit = useMutation({
    mutationFn: (body: { instruction: string; target_platform?: string; target_duration_seconds?: number; asset_id?: string | null; timeline_id?: string | null }) =>
      apiPost<{ session: ChatSession; assistant_message: ChatMessage; job_id: string }>(`/projects/${projectId}/edit`, body),
    onSuccess: invalidate,
  });
  const newSession = useMutation({ mutationFn: () => apiPost<ChatSession>(`/projects/${projectId}/chat/sessions`), onSuccess: invalidate });
  const preview = useMutation({ mutationFn: (messageId: string) => apiPost<ProposalPreview>(`/projects/${projectId}/chat/messages/${messageId}/preview`) });
  const apply = useMutation({
    mutationFn: (messageId: string) => apiPost<{ state: TimelineState; message: ChatMessage; jobs: { kind: string; job_id?: string }[] }>(`/projects/${projectId}/chat/messages/${messageId}/apply`),
    onSuccess: (res) => {
      qc.setQueryData(timelineKey(projectId, res.state.timeline.is_primary ? null : res.state.timeline.id), res.state);
      qc.invalidateQueries({ queryKey: ["timeline", projectId] });
      qc.invalidateQueries({ queryKey: ["timeline-versions", projectId] });
      invalidate();
    },
  });
  const reject = useMutation({ mutationFn: (messageId: string) => apiPost<ChatMessage>(`/projects/${projectId}/chat/messages/${messageId}/reject`), onSuccess: invalidate });
  return { send, edit, newSession, preview, apply, reject };
}
