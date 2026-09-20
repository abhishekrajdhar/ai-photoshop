"use client";
import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Download, FileText, Film, Loader2, Play } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, Progress, Separator } from "@/components/ui/misc";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ApiError } from "@/lib/api";
import { useExports, usePresets, useRenderMutations, useRenders } from "@/lib/render";
import { useTimeline } from "@/lib/timeline";
import { cn, formatBytes, formatDuration, relativeTime } from "@/lib/utils";
import { useEditorStore } from "@/stores/editor";
import { useJobsStore } from "@/stores/jobs";
import { ShortsList } from "@/components/editor/creator-panel";

const CAPTION_FORMATS = [{ id: "srt", label: "SRT" }, { id: "vtt", label: "WebVTT" }, { id: "ass", label: "ASS" }];
const PRO_FORMATS = [{ id: "otio", label: "OpenTimelineIO" }, { id: "edl", label: "EDL (CMX3600)" }, { id: "fcpxml", label: "FCPXML" }];

export function ExportPanel({ projectId }: { projectId: string }) {
  const timelineId = useEditorStore((s) => s.timelineId);
  const set = useEditorStore((s) => s.set);
  const { data: state } = useTimeline(projectId, timelineId);
  const { data: presets } = usePresets();
  const { data: renders } = useRenders(projectId);
  const { data: exports } = useExports(projectId);
  const m = useRenderMutations(projectId);
  const jobs = useJobsStore((s) => s.jobs);
  const [presetId, setPresetId] = useState("youtube_1080p");
  const [custom, setCustom] = useState({ width: 1920, height: 1080, fps: "", video_bitrate: "12M", codec: "libx264", filename: "" });
  const preset = presets?.find((p) => p.id === presetId);
  const duration = state?.version.duration ?? 0;
  const aspectMismatch = useMemo(() => preset && state && preset.aspect_ratio !== state.document.settings.aspect_ratio && presetId !== "custom", [preset, state, presetId]);
  const settings = presetId === "custom" ? { width: custom.width, height: custom.height, fps: custom.fps ? Number(custom.fps) : null, video_bitrate: custom.video_bitrate, codec: custom.codec, filename: custom.filename || null } : { filename: custom.filename || null };
  const onErr = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Request failed");

  return (
    <div className="flex h-full flex-col">
      <div className="panel-header">Export</div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3 text-[12px]">
        <ShortsList projectId={projectId} />
        <Separator className="my-3" />
        <section className="space-y-2.5">
          <div className="grid grid-cols-[80px_1fr] items-center gap-2">
            <Label>Preset</Label>
            <Select value={presetId} onValueChange={setPresetId}>
              <SelectTrigger className="h-7"><SelectValue /></SelectTrigger>
              <SelectContent>{(presets ?? []).map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          {preset && <div className="text-[11px] text-fg-subtle">{preset.description}</div>}
          {presetId === "custom" && (
            <div className="grid grid-cols-2 gap-2">
              <div><Label>Width</Label><Input type="number" className="h-7" value={custom.width} onChange={(e) => setCustom({ ...custom, width: Number(e.target.value) })} /></div>
              <div><Label>Height</Label><Input type="number" className="h-7" value={custom.height} onChange={(e) => setCustom({ ...custom, height: Number(e.target.value) })} /></div>
              <div><Label>FPS (blank = sequence)</Label><Input className="h-7" value={custom.fps} onChange={(e) => setCustom({ ...custom, fps: e.target.value })} placeholder="30" /></div>
              <div><Label>Bitrate</Label><Input className="h-7" value={custom.video_bitrate} onChange={(e) => setCustom({ ...custom, video_bitrate: e.target.value })} /></div>
              <div className="col-span-2">
                <Label>Codec</Label>
                <Select value={custom.codec} onValueChange={(v) => setCustom({ ...custom, codec: v })}>
                  <SelectTrigger className="h-7"><SelectValue /></SelectTrigger>
                  <SelectContent><SelectItem value="libx264">H.264 (libx264)</SelectItem><SelectItem value="libx265">H.265 (libx265)</SelectItem><SelectItem value="libvpx-vp9">VP9</SelectItem></SelectContent>
                </Select>
              </div>
            </div>
          )}
          <div className="grid grid-cols-[80px_1fr] items-center gap-2">
            <Label>File name</Label>
            <Input className="h-7" placeholder="Optional" value={custom.filename} onChange={(e) => setCustom({ ...custom, filename: e.target.value })} />
          </div>
          {aspectMismatch && (
            <div className="flex items-start gap-1.5 rounded-md border border-warning/30 bg-warning/10 p-2 text-[11px] text-warning"><AlertTriangle className="mt-0.5 size-3 shrink-0" />Preset is {preset?.aspect_ratio} but the sequence is {state?.document.settings.aspect_ratio}. Use the AI (“Reframe for 9:16”) or expect letterboxing.</div>
          )}
          <div className="flex gap-1.5">
            <Button className="flex-1" disabled={duration <= 0} loading={m.render.isPending} onClick={() => m.render.mutate({ preset: presetId, timeline_id: timelineId, settings }, { onError: onErr, onSuccess: () => toast.success("Render started") })}><Film /> Render {formatDuration(duration)}</Button>
            <Button variant="secondary" disabled={duration <= 0} onClick={() => m.render.mutate({ preset: "preview", kind: "preview", timeline_id: timelineId, settings: {} }, { onError: onErr, onSuccess: () => toast.success("Preview render started") })}>Draft</Button>
          </div>
        </section>
        <Separator className="my-3" />
        <section>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Captions</div>
          <div className="flex flex-wrap gap-1">{CAPTION_FORMATS.map((f) => <Button key={f.id} size="xs" variant="outline" disabled={duration <= 0} onClick={() => m.exportTimeline.mutate({ format: f.id, timeline_id: timelineId }, { onError: onErr })}><FileText /> {f.label}</Button>)}</div>
          <div className="mb-1.5 mt-3 text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Professional NLE</div>
          <div className="flex flex-wrap gap-1">{PRO_FORMATS.map((f) => <Button key={f.id} size="xs" variant="outline" disabled={duration <= 0} onClick={() => m.exportTimeline.mutate({ format: f.id, timeline_id: timelineId }, { onError: onErr })}><Download /> {f.label}</Button>)}</div>
        </section>
        <Separator className="my-3" />
        <section>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Renders</div>
          {(renders ?? []).length === 0 && <div className="text-[11.5px] text-fg-subtle">No renders yet.</div>}
          {(renders ?? []).map((r) => {
            const job = r.job_id ? jobs[r.job_id] : undefined;
            const active = r.status === "QUEUED" || r.status === "RUNNING";
            return (
              <div key={r.id} className={cn("mb-1.5 rounded-md border border-border bg-panel-2 p-2", r.status === "FAILED" && "border-danger/40")}>
                <div className="flex items-center gap-1.5">
                  {active ? <Loader2 className="size-3.5 animate-spin text-accent" /> : r.status === "COMPLETED" ? <CheckCircle2 className="size-3.5 text-success" /> : <AlertTriangle className="size-3.5 text-danger" />}
                  <span className="min-w-0 flex-1 truncate font-medium">{String(r.settings.filename ?? r.preset)}</span>
                  <Badge variant="secondary">{r.kind === "preview" ? "draft" : r.preset.replace(/_/g, " ")}</Badge>
                </div>
                {active && <Progress className="mt-1.5" value={(job?.progress ?? 0) * 100} />}
                <div className="mt-1 flex items-center gap-2 text-[10.5px] text-fg-subtle">
                  <span>{String(r.settings.width)}×{String(r.settings.height)}</span>
                  {r.duration != null && <span>· {formatDuration(r.duration)}</span>}
                  <span>· {relativeTime(r.created_at)}</span>
                  {active && job?.message && <span className="truncate">· {job.message}</span>}
                  {r.status === "COMPLETED" && r.output_asset_id && (
                    <span className="ml-auto flex gap-1">
                      <Button size="xs" variant="ghost" onClick={() => set({ previewSource: { kind: "asset", assetId: r.output_asset_id! } })}><Play /> Play</Button>
                      <Button size="xs" variant="secondary" asChild><a href={r.download_url ?? "#"} download><Download /> Download</a></Button>
                    </span>
                  )}
                </div>
                {r.error && <div className="mt-1 text-[11px] text-danger">{r.error}</div>}
              </div>
            );
          })}
          {(exports ?? []).length > 0 && <div className="mb-1.5 mt-3 text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Exports</div>}
          {(exports ?? []).map((e) => (
            <div key={e.id} className="mb-1 flex items-center gap-2 rounded-md border border-border bg-panel-2 px-2 py-1.5">
              {e.status === "QUEUED" || e.status === "RUNNING" ? <Loader2 className="size-3.5 animate-spin text-accent" /> : e.status === "COMPLETED" ? <CheckCircle2 className="size-3.5 text-success" /> : <AlertTriangle className="size-3.5 text-danger" />}
              <span className="min-w-0 flex-1 truncate">{e.filename}</span>
              <span className="text-[10.5px] text-fg-subtle">{e.size_bytes ? formatBytes(e.size_bytes) : e.format.toUpperCase()}</span>
              {e.download_url && <Button size="icon-xs" variant="ghost" asChild><a href={e.download_url} download><Download /></a></Button>}
              {e.error && <span className="truncate text-[10.5px] text-danger" title={e.error}>{e.error}</span>}
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
