"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { GitCompare, History, RotateCcw, SlidersHorizontal, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge, EmptyState, Separator } from "@/components/ui/misc";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { useTimelineActions } from "@/components/timeline/use-timeline-actions";
import { apiGet } from "@/lib/api";
import { useAssets } from "@/lib/assets";
import { useTimelineVersions } from "@/lib/timeline";
import { findClip } from "@/lib/timeline-engine";
import type { Clip, TimelineVersion } from "@/lib/types";
import { cn, formatBytes, formatDuration, formatTime, relativeTime } from "@/lib/utils";
import { useEditorStore, type RightTab } from "@/stores/editor";
import { ChatPanel } from "@/components/editor/chat-panel";
import { ExportPanel } from "@/components/editor/export-panel";

export function RightPanel({ projectId, tab }: { projectId: string; tab: RightTab }) {
  if (tab === "inspector") return <Inspector projectId={projectId} />;
  if (tab === "versions") return <VersionsPanel projectId={projectId} />;
  if (tab === "export") return <ExportPanel projectId={projectId} />;
  return <ChatPanel projectId={projectId} />;
}

/* ── Inspector ───────────────────────────────────────────────────────────── */

function Inspector({ projectId }: { projectId: string }) {
  const selectedClipIds = useEditorStore((s) => s.selectedClipIds);
  const selectedAssetId = useEditorStore((s) => s.selectedAssetId);
  const actions = useTimelineActions(projectId);
  const { data: assets } = useAssets(projectId);
  const clipId = selectedClipIds[0];
  const found = clipId && actions.doc ? findClip(actions.doc, clipId) : undefined;
  if (found) return <ClipInspector clip={found.clip} trackKind={found.track.kind} actions={actions} />;
  const asset = assets?.find((a) => a.id === selectedAssetId);
  if (!asset) return <EmptyState icon={<SlidersHorizontal />} title="Inspector" description="Select a timeline clip or a media asset to see its properties." />;
  const m = asset.metadata;
  const rows: [string, string][] = [
    ["File", asset.filename], ["Type", `${asset.media_type} · ${asset.mime_type}`], ["Size", formatBytes(asset.size_bytes)], ["Status", asset.status],
    ...(m ? ([["Duration", m.duration != null ? formatDuration(m.duration) : "–"], ["Resolution", m.width ? `${m.width} × ${m.height}` : "–"], ["Frame rate", m.fps ? `${m.fps} fps` : "–"], ["Video codec", m.video_codec ?? "–"], ["Audio", m.audio_codec ? `${m.audio_codec} · ${m.audio_channels ?? "?"} ch · ${m.sample_rate ?? "?"} Hz` : "none"], ["Bitrate", m.bitrate ? `${Math.round(m.bitrate / 1000)} kb/s` : "–"]] as [string, string][]) : []),
  ];
  return (
    <div className="p-3">
      <div className="mb-2 text-[11px] uppercase tracking-wider text-fg-subtle">Asset</div>
      <dl className="space-y-1.5 text-[12px]">{rows.map(([k, v]) => <div key={k} className="grid grid-cols-[90px_1fr] gap-2"><dt className="text-fg-muted">{k}</dt><dd className="truncate" title={v}>{v}</dd></div>)}</dl>
      {asset.error && <div className="mt-3 rounded-md border border-danger/30 bg-danger/10 p-2 text-[12px] text-danger">{asset.error}</div>}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[92px_1fr] items-center gap-2">
      <Label className="text-[11.5px]">{label}</Label>
      {children}
    </div>
  );
}

function ClipInspector({ clip, trackKind, actions }: { clip: Clip; trackKind: string; actions: ReturnType<typeof useTimelineActions> }) {
  const [name, setName] = useState(clip.name);
  const [text, setText] = useState(clip.text ?? "");
  const patch = (p: Partial<Clip>, label?: string) => actions.updateClip(clip.id, p, label);
  const isAudio = trackKind === "audio";
  return (
    <div className="space-y-3 p-3 text-[12px]">
      <div className="flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-wider text-fg-subtle">Clip · {clip.kind}</div>
        <Button variant="ghost" size="xs" onClick={() => actions.deleteClips([clip.id], true)}><Trash2 /> Delete</Button>
      </div>
      <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} onBlur={() => name !== clip.name && patch({ name }, "Rename clip")} className="h-7" /></Field>
      <Field label="Start"><span className="text-mono">{formatTime(clip.timeline_start, { frames: true })}</span></Field>
      <Field label="Duration"><span className="text-mono">{formatTime(clip.duration, { frames: true })}</span></Field>
      {clip.asset_id && <Field label="Source"><span className="text-mono">{formatTime(clip.source_in)} → {formatTime(clip.source_out)}</span></Field>}
      {(clip.kind === "video" || clip.kind === "audio") && (
        <Field label="Speed">
          <Select value={String(clip.speed)} onValueChange={(v) => actions.applyOps([{ type: "speed_change", source_clip_id: clip.id, time_ref: "timeline", params: { speed: Number(v) } }], `Speed ${v}×`)}>
            <SelectTrigger className="h-7"><SelectValue /></SelectTrigger>
            <SelectContent>{[0.5, 0.75, 1, 1.25, 1.5, 2, 3].map((s) => <SelectItem key={s} value={String(s)}>{s}×</SelectItem>)}</SelectContent>
          </Select>
        </Field>
      )}
      {(isAudio || clip.kind === "video") && (
        <>
          <Field label="Muted"><Switch checked={clip.muted} onCheckedChange={(v) => patch({ muted: v }, v ? "Mute clip" : "Unmute clip")} /></Field>
          {isAudio && (
            <>
              <Field label={`Gain ${clip.gain_db.toFixed(0)} dB`}><Slider min={-40} max={12} step={1} value={[clip.gain_db]} onValueCommit={([v]) => patch({ gain_db: v ?? 0 }, "Gain")} /></Field>
              <Field label="Fade in (s)"><Input type="number" min={0} step={0.1} className="h-7" defaultValue={clip.fade_in} onBlur={(e) => patch({ fade_in: Number(e.target.value) || 0 }, "Fade in")} /></Field>
              <Field label="Fade out (s)"><Input type="number" min={0} step={0.1} className="h-7" defaultValue={clip.fade_out} onBlur={(e) => patch({ fade_out: Number(e.target.value) || 0 }, "Fade out")} /></Field>
              {clip.kind === "music" && <Field label="Duck under voice"><Switch checked={clip.ducking} onCheckedChange={(v) => patch({ ducking: v }, "Ducking")} /></Field>}
              {clip.kind === "music" && <Field label="Loop"><Switch checked={clip.loop} onCheckedChange={(v) => patch({ loop: v }, "Loop")} /></Field>}
            </>
          )}
        </>
      )}
      {(clip.kind === "caption" || clip.kind === "text") && (
        <Field label="Text"><Input value={text} onChange={(e) => setText(e.target.value)} onBlur={() => text !== clip.text && patch({ text }, "Edit text")} className="h-7" /></Field>
      )}
      {trackKind === "video" && (
        <>
          <Field label="Transition out">
            <Select value={clip.transition_out.type} onValueChange={(v) => patch({ transition_out: { type: v as Clip["transition_out"]["type"], duration: v === "cut" ? 0 : clip.transition_out.duration || 0.5 } }, "Transition")}>
              <SelectTrigger className="h-7"><SelectValue /></SelectTrigger>
              <SelectContent>{["cut", "crossfade", "fade_black", "dip_to_white"].map((t) => <SelectItem key={t} value={t}>{t.replace("_", " ")}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          {clip.transition_out.type !== "cut" && <Field label="Duration (s)"><Input type="number" min={0.1} max={3} step={0.1} className="h-7" defaultValue={clip.transition_out.duration} onBlur={(e) => patch({ transition_out: { ...clip.transition_out, duration: Number(e.target.value) || 0.5 } }, "Transition duration")} /></Field>}
        </>
      )}
      <Separator />
      <div>
        <div className="mb-1 flex items-center justify-between text-[11px] uppercase tracking-wider text-fg-subtle">
          <span>Effects · {clip.effects.length}</span>
          {(clip.kind === "video" || clip.kind === "broll") && <Button variant="ghost" size="xs" onClick={() => actions.applyOps([{ type: "zoom", source_clip_id: clip.id, time_ref: "timeline", timestamp: clip.timeline_start, duration: 2, scale: 1.12 }], "Add zoom")}>+ Zoom</Button>}
        </div>
        {clip.effects.length === 0 && <div className="text-[11.5px] text-fg-subtle">No effects.</div>}
        {clip.effects.map((fx) => (
          <div key={fx.id} className="mb-1 flex items-center justify-between rounded-md border border-border bg-panel-2 px-2 py-1">
            <div>
              <div className="font-medium">{fx.type.replace(/_/g, " ")}</div>
              <div className="text-[10.5px] text-fg-subtle">{fx.start != null ? `@ ${formatTime(fx.start)}` : "whole clip"}{fx.duration != null ? ` · ${fx.duration.toFixed(1)}s` : ""} {fx.type === "zoom" ? `· ${Number(fx.params.scale ?? 1).toFixed(2)}×` : ""}</div>
            </div>
            <div className="flex items-center gap-1">
              <Switch checked={fx.enabled} onCheckedChange={(v) => patch({ effects: clip.effects.map((e) => (e.id === fx.id ? { ...e, enabled: v } : e)) }, "Toggle effect")} />
              <Button variant="ghost" size="icon-xs" onClick={() => patch({ effects: clip.effects.filter((e) => e.id !== fx.id) }, "Remove effect")}><Trash2 /></Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Versions ────────────────────────────────────────────────────────────── */

interface Compare { duration_delta: number; added_clips: unknown[]; removed_clips: unknown[]; changed_clips: unknown[] }

function VersionsPanel({ projectId }: { projectId: string }) {
  const timelineId = useEditorStore((s) => s.timelineId);
  const { data: versions } = useTimelineVersions(projectId, timelineId);
  const actions = useTimelineActions(projectId);
  const current = actions.state?.version.id;
  const [compareWith, setCompareWith] = useState<string | null>(null);
  const { data: diff } = useQuery({
    queryKey: ["compare", projectId, compareWith, current],
    queryFn: () => apiGet<Compare>(`/projects/${projectId}/timeline/versions/${compareWith}/compare/${current}`),
    enabled: !!compareWith && !!current,
  });
  if (!versions?.length) return <EmptyState icon={<History />} title="Edit history" description="Versions appear here as you and the AI edit." />;
  const ordered = [...versions].reverse();
  return (
    <div className="flex h-full flex-col">
      <div className="panel-header">Edit history · {versions.length} versions</div>
      {diff && compareWith && (
        <div className="border-b border-border bg-panel-2 p-2 text-[11.5px]">
          <div className="mb-1 flex items-center justify-between"><span className="font-medium">v{versions.find((v) => v.id === compareWith)?.version} → current</span><Button variant="ghost" size="xs" onClick={() => setCompareWith(null)}>Close</Button></div>
          <div className="text-fg-muted">Duration {diff.duration_delta >= 0 ? "+" : ""}{diff.duration_delta.toFixed(1)}s · {diff.added_clips.length} added · {diff.removed_clips.length} removed · {diff.changed_clips.length} changed</div>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {ordered.map((v: TimelineVersion) => (
          <div key={v.id} className={cn("mb-1 rounded-md border px-2 py-1.5 text-[12px]", v.id === current ? "border-accent bg-accent/10" : "border-border bg-panel-2")}>
            <div className="flex items-center gap-1.5">
              <span className="text-mono text-[10.5px] text-fg-subtle">v{v.version}</span>
              <span className="truncate font-medium">{v.label || "Edit"}</span>
              <Badge variant={v.source === "ai" ? "default" : v.source === "system" ? "secondary" : "outline"} className="ml-auto">{v.source}</Badge>
            </div>
            <div className="mt-0.5 flex items-center gap-2 text-[10.5px] text-fg-subtle">
              <span>{formatDuration(v.duration)}</span>
              {v.operation_count > 0 && <span>· {v.operation_count} ops</span>}
              <span>· {relativeTime(v.created_at)}</span>
              <span className="ml-auto flex gap-0.5">
                {v.id !== current && <Button variant="ghost" size="icon-xs" title="Compare with current" onClick={() => setCompareWith(v.id)}><GitCompare /></Button>}
                {v.id !== current && <Button variant="ghost" size="icon-xs" title="Restore this version" onClick={() => actions.restore(v.id)}><RotateCcw /></Button>}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
