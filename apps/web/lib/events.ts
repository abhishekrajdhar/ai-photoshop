"use client";
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useJobsStore } from "@/stores/jobs";
import type { JobStatus } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";

type EventPayload = {
  event: string;
  data: Record<string, unknown>;
  ts: string;
};

/**
 * Subscribes to the project's Server-Sent Events stream and keeps caches fresh:
 * job progress → jobs store, asset/timeline/transcript events → query invalidation.
 */
export function useProjectEvents(projectId: string | undefined, handlers: Partial<Record<string, (data: Record<string, unknown>) => void>> = {}) {
  const qc = useQueryClient();
  const upsert = useJobsStore((s) => s.upsert);
  const handlersRef = { current: handlers };
  useEffect(() => {
    if (!projectId) return;
    let source: EventSource | null = null;
    let closed = false;
    let retry = 1000;

    const connect = () => {
      if (closed) return;
      source = new EventSource(`${API_BASE}/events/projects/${projectId}`, { withCredentials: true });
      source.onopen = () => (retry = 1000);
      source.onerror = () => {
        source?.close();
        if (!closed) {
          setTimeout(connect, retry);
          retry = Math.min(retry * 2, 15000);
        }
      };
      const onAny = (ev: MessageEvent) => {
        let payload: EventPayload;
        try {
          payload = JSON.parse(ev.data);
        } catch {
          return;
        }
        const event = payload.event ?? ev.type;
        const data: Record<string, unknown> = payload.data ?? {};
        if (event === "heartbeat") return;
        if (data.job_id) {
          upsert({
            id: String(data.job_id),
            project_id: (data.project_id as string) ?? projectId,
            type: String(data.type ?? "JOB"),
            status: data.status as JobStatus,
            progress: Number(data.progress ?? 0),
            message: String(data.message ?? ""),
            error: (data.error as string) ?? null,
            result: (data.result as Record<string, unknown>) ?? {},
            meta: (data.meta as Record<string, unknown>) ?? {},
          });
        }
        if (event.startsWith("upload.") || event === "job.failed" || event.endsWith(".completed")) {
          qc.invalidateQueries({ queryKey: ["assets", projectId] });
        }
        if (event === "timeline.updated" || event.endsWith(".completed")) {
          qc.invalidateQueries({ queryKey: ["timeline", projectId] });
          qc.invalidateQueries({ queryKey: ["timelines", projectId] });
        }
        if (event.startsWith("transcription.") || event === "transcript.updated") {
          qc.invalidateQueries({ queryKey: ["transcript", projectId] });
        }
        if (event.endsWith(".completed") || event === "analysis.updated") {
          qc.invalidateQueries({ queryKey: ["analysis", projectId] });
          qc.invalidateQueries({ queryKey: ["highlights", projectId] });
          qc.invalidateQueries({ queryKey: ["thumbnails", projectId] });
          qc.invalidateQueries({ queryKey: ["renders", projectId] });
          qc.invalidateQueries({ queryKey: ["exports", projectId] });
        }
        if (event === "chat.message") {
          qc.invalidateQueries({ queryKey: ["chat", projectId] });
        }
        if (event === "job.failed") {
          toast.error(`${String(data.type ?? "Job").replace(/_/g, " ").toLowerCase()} failed`, { description: String(data.error ?? "") });
        }
        if (event === "upload.duplicate") {
          toast.warning("Duplicate file skipped", { description: "An identical file already exists in this project." });
        }
        handlersRef.current[event]?.(data);
        handlersRef.current["*"]?.({ event, ...data });
      };
      // sse-starlette emits named events; listen to the common ones plus generic messages.
      const names = [
        "message", "heartbeat", "job.queued", "job.started", "job.retrying", "job.failed", "job.cancelled",
        "upload.started", "upload.processing", "upload.completed", "upload.duplicate", "upload_processing.progress", "upload_processing.completed",
        "transcription.progress", "transcription.completed", "scene_detection.progress", "scene_detection.completed",
        "audio_analysis.progress", "audio_analysis.completed", "vision_analysis.progress", "vision_analysis.completed",
        "content_analysis.progress", "content_analysis.completed", "edit_planning.progress", "edit_planning.completed",
        "highlight_detection.progress", "highlight_detection.completed", "short_generation.progress", "short_generation.completed",
        "thumbnail_generation.progress", "thumbnail_generation.completed", "reframe_tracking.progress", "reframe_tracking.completed",
        "rendering.progress", "rendering.completed", "export.progress", "export.completed", "render.progress", "render.completed",
        "timeline.updated", "transcript.updated", "analysis.updated", "analysis.completed", "chat.message",
      ];
      for (const n of names) source.addEventListener(n, onAny as EventListener);
    };
    connect();
    return () => {
      closed = true;
      source?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);
}
