"use client";
import { useTimeline } from "@/lib/timeline";
import { formatTime } from "@/lib/utils";

/** Minimal timeline listing; replaced by the interactive timeline editor in the timeline module. */
export function TimelinePanel({ projectId }: { projectId: string }) {
  const { data } = useTimeline(projectId);
  const doc = data?.document;
  return (
    <div className="flex h-full flex-col">
      <div className="panel-header justify-between">
        <span>Timeline · {doc?.name ?? "…"}</span>
        <span className="text-mono normal-case tracking-normal">{formatTime(data?.version.duration ?? 0)}</span>
      </div>
      <div className="flex-1 overflow-auto p-2 text-[12px]">
        {doc?.tracks.map((t) => (
          <div key={t.id} className="mb-1 flex items-center gap-2">
            <div className="w-20 shrink-0 text-fg-muted">{t.name}</div>
            <div className="flex flex-1 gap-1 overflow-x-auto">
              {t.clips.map((c) => (
                <div key={c.id} className="shrink-0 rounded-sm bg-elevated px-2 py-1 text-[11px]">
                  {c.name || c.kind} · {formatTime(c.timeline_start)}–{formatTime(c.timeline_start + c.duration)}
                </div>
              ))}
              {t.clips.length === 0 && <span className="text-[11px] text-fg-subtle">empty</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
