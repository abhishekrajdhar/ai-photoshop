"use client";
import { useState } from "react";
import { Clapperboard, Image as ImageIcon, Sparkles, Star, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Badge, EmptyState } from "@/components/ui/misc";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useAIStatus } from "@/lib/analysis";
import { ApiError } from "@/lib/api";
import { useCreatorMutations, useHighlights, useThumbnails } from "@/lib/creator";
import { useTimelines } from "@/lib/timeline";
import { useRenders } from "@/lib/render";
import { Download, Play } from "lucide-react";
import { useJobsStore } from "@/stores/jobs";
import { Progress } from "@/components/ui/misc";
import type { Highlight } from "@/lib/types";
import { cn, formatDuration, formatTime } from "@/lib/utils";
import { useEditorStore } from "@/stores/editor";

const FACTOR_LABEL: Record<string, string> = { informative: "Informative", surprising: "Surprising", funny: "Funny", emotional: "Emotional", hook_strength: "Hook", clarity: "Clarity", self_contained: "Self-contained" };

export function HighlightsSection({ projectId }: { projectId: string }) {
  const { data: highlights } = useHighlights(projectId);
  const { data: ai } = useAIStatus(projectId);
  const m = useCreatorMutations(projectId);
  const setPlayhead = useEditorStore((s) => s.setPlayhead);
  const [shortsOpen, setShortsOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const onErr = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Request failed");
  return (
    <section>
      <div className="mb-1 flex items-center justify-between">
        <h4 className="text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Highlights · {highlights?.length ?? 0}</h4>
        <div className="flex gap-1">
          <Button size="xs" variant="ghost" disabled={!ai?.configured} loading={m.detectHighlights.isPending} onClick={() => m.detectHighlights.mutate({ count: 5 }, { onError: onErr, onSuccess: () => toast.success("Finding highlights…") })}><Star /> Find</Button>
          <Button size="xs" disabled={!ai?.configured} onClick={() => setShortsOpen(true)}><Clapperboard /> Shorts</Button>
        </div>
      </div>
      {!highlights?.length ? (
        <div className="rounded-md border border-dashed border-border p-3 text-[11.5px] text-fg-subtle">Detect highlights to see the strongest moments with their scoring factors, then turn them into Shorts.</div>
      ) : (
        <ul className="space-y-1.5">
          {highlights.map((h: Highlight) => (
            <li key={h.id} className={cn("rounded-md border bg-panel-2 p-2", selected.includes(h.id) ? "border-accent" : "border-border")}>
              <div className="flex items-start gap-2">
                <input type="checkbox" className="mt-0.5 accent-accent" checked={selected.includes(h.id)} onChange={(e) => setSelected((s) => (e.target.checked ? [...s, h.id] : s.filter((x) => x !== h.id)))} />
                <div className="min-w-0 flex-1">
                  <button className="block truncate text-left text-[12px] font-medium hover:underline" onClick={() => setPlayhead(h.start)}>{h.title}</button>
                  <div className="text-[10.5px] text-fg-subtle">{formatTime(h.start)}–{formatTime(h.end)} · {formatDuration(h.end - h.start)} · {h.category}</div>
                  <div className="mt-1 text-[11px] text-fg-muted">{h.reason}</div>
                  <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5">
                    {Object.entries(h.factors).filter(([k, v]) => typeof v === "number" && FACTOR_LABEL[k]).map(([k, v]) => (
                      <div key={k} className="flex items-center gap-1.5 text-[10px]">
                        <span className="w-16 truncate text-fg-subtle">{FACTOR_LABEL[k]}</span>
                        <div className="h-1 flex-1 overflow-hidden rounded-full bg-border-strong/60"><div className="h-full bg-accent" style={{ width: `${Math.round((v as number) * 100)}%` }} /></div>
                        <span className="w-6 text-right text-mono text-fg-subtle">{Math.round((v as number) * 100)}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <Badge variant="default">{Math.round(h.score * 100)}</Badge>
              </div>
            </li>
          ))}
        </ul>
      )}
      <ShortsDialog projectId={projectId} open={shortsOpen} onOpenChange={setShortsOpen} highlightIds={selected} />
    </section>
  );
}

const SHORT_PLATFORMS = [
  { id: "youtube_shorts", label: "YouTube Shorts", preset: "youtube_shorts", max: 60 },
  { id: "instagram_reels", label: "Instagram Reels", preset: "instagram_reel", max: 90 },
  { id: "tiktok", label: "TikTok", preset: "tiktok", max: 90 },
];

export function ShortsDialog({ projectId, open, onOpenChange, highlightIds }: { projectId: string; open: boolean; onOpenChange: (o: boolean) => void; highlightIds: string[] }) {
  const m = useCreatorMutations(projectId);
  const { data: ai } = useAIStatus(projectId);
  const set = useEditorStore((s) => s.set);
  const [platform, setPlatform] = useState("instagram_reels");
  const [count, setCount] = useState("3");
  const [duration, setDuration] = useState("45");
  const [preset, setPreset] = useState("bold");
  const [reframe, setReframe] = useState(true);
  const [autoRender, setAutoRender] = useState(true);
  const plat = SHORT_PLATFORMS.find((p) => p.id === platform)!;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Create Shorts & Reels from the best moments</DialogTitle>
          <DialogDescription>The AI picks the strongest sections (with explained scores), then builds one vertical 9:16 clip each — hook first, jump cuts, captions, smart zooms and subject tracking — and can render them straight to the platform preset.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-[12px]">
          <div className="grid grid-cols-3 gap-1.5">
            {SHORT_PLATFORMS.map((p) => (
              <button key={p.id} type="button" onClick={() => { setPlatform(p.id); if (Number(duration) > p.max) setDuration(String(p.max)); }} className={cn("rounded-md border px-2 py-2 text-center text-[12px] transition-colors", platform === p.id ? "border-accent bg-accent/10" : "border-border bg-panel-2 hover:border-border-strong")}>
                <div className="font-medium">{p.label}</div>
                <div className="text-[10.5px] text-fg-subtle">9:16 · ≤ {p.max}s</div>
              </button>
            ))}
          </div>
          {highlightIds.length > 0 ? (
            <div className="rounded-md border border-accent/40 bg-accent/10 p-2">Using {highlightIds.length} selected highlight{highlightIds.length > 1 ? "s" : ""}.</div>
          ) : (
            <div className="grid grid-cols-[110px_1fr] items-center gap-2"><Label>How many clips</Label><Select value={count} onValueChange={setCount}><SelectTrigger className="h-7"><SelectValue /></SelectTrigger><SelectContent>{["1", "2", "3", "5", "8"].map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}</SelectContent></Select></div>
          )}
          <div className="grid grid-cols-[110px_1fr] items-center gap-2"><Label>Length</Label><Select value={duration} onValueChange={setDuration}><SelectTrigger className="h-7"><SelectValue /></SelectTrigger><SelectContent>{["15", "30", "45", "60", "90"].filter((n) => Number(n) <= plat.max).map((n) => <SelectItem key={n} value={n}>{n} seconds</SelectItem>)}</SelectContent></Select></div>
          <div className="grid grid-cols-[110px_1fr] items-center gap-2"><Label>Caption style</Label><Select value={preset} onValueChange={setPreset}><SelectTrigger className="h-7"><SelectValue /></SelectTrigger><SelectContent>{["bold", "karaoke", "clean", "minimal", "boxed"].map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}</SelectContent></Select></div>
          <div className="grid grid-cols-[110px_1fr] items-center gap-2"><Label>Track subject</Label><Switch checked={reframe} onCheckedChange={setReframe} /></div>
          <div className="grid grid-cols-[110px_1fr] items-center gap-2"><Label>Render now</Label><div className="flex items-center gap-2"><Switch checked={autoRender} onCheckedChange={setAutoRender} /><span className="text-[11px] text-fg-subtle">export each clip with the {plat.label} preset</span></div></div>
          {!ai?.configured && <div className="rounded-md border border-warning/30 bg-warning/10 p-2 text-[11px] text-warning">Finding the best moments needs an AI provider key (Anthropic or OpenAI).</div>}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!ai?.configured} loading={m.generateShorts.isPending} onClick={() => m.generateShorts.mutate({ count: highlightIds.length || Number(count), duration: Number(duration) as 15 | 30 | 45 | 60 | 90, platform, caption_preset: preset, reframe, highlight_ids: highlightIds.length ? highlightIds : undefined, auto_render: autoRender, render_preset: plat.preset }, { onSuccess: () => { onOpenChange(false); set({ rightTab: "export" }); toast.success(`Creating ${plat.label} clips — they appear in Export › Shorts & Reels`); }, onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed") })}><Wand2 /> Create {plat.label}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ThumbnailsSection({ projectId }: { projectId: string }) {
  const { data } = useThumbnails(projectId);
  const m = useCreatorMutations(projectId);
  const set = useEditorStore((s) => s.set);
  const setPlayhead = useEditorStore((s) => s.setPlayhead);
  return (
    <section>
      <div className="mb-1 flex items-center justify-between">
        <h4 className="text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Thumbnail candidates</h4>
        <Button size="xs" variant="ghost" loading={m.generateThumbnails.isPending} onClick={() => m.generateThumbnails.mutate(undefined, { onSuccess: () => toast.success("Scoring frames…"), onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed") })}><ImageIcon /> Suggest</Button>
      </div>
      {!data?.candidates.length ? (
        <div className="rounded-md border border-dashed border-border p-3 text-[11.5px] text-fg-subtle">Candidates are scored on sharpness, exposure, face visibility, framing and text-safe area.</div>
      ) : (
        <div className="grid grid-cols-2 gap-1.5">
          {data.candidates.map((c) => (
            <button key={c.asset_id} className="group overflow-hidden rounded-md border border-border bg-panel-2 text-left hover:border-border-strong" onClick={() => { set({ previewSource: { kind: "asset", assetId: c.asset_id } }); setPlayhead(c.time); }} title={Object.entries(c.factors).map(([k, v]) => `${k}: ${Math.round(v * 100)}`).join("\n")}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={c.url} alt="" className="aspect-video w-full object-cover" loading="lazy" />
              <div className="flex items-center justify-between px-1.5 py-1 text-[10.5px]"><span className="text-mono text-fg-subtle">{formatTime(c.time)}</span><span className="font-semibold text-accent">{Math.round(c.score * 100)}</span></div>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

export function ShortsList({ projectId }: { projectId: string }) {
  const { data: timelines } = useTimelines(projectId);
  const { data: renders } = useRenders(projectId);
  const jobs = useJobsStore((s) => s.jobs);
  const set = useEditorStore((s) => s.set);
  const [open, setOpen] = useState(false);
  const shorts = (timelines ?? []).filter((t) => t.kind === "short");
  const generating = Object.values(jobs).some((j) => j.project_id === projectId && j.type === "SHORT_GENERATION" && (j.status === "QUEUED" || j.status === "RUNNING"));
  return (
    <section>
      <div className="mb-1 flex items-center justify-between">
        <h4 className="text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Shorts & Reels · {shorts.length}</h4>
        <Button size="xs" onClick={() => setOpen(true)}><Clapperboard /> Create</Button>
      </div>
      {generating && <div className="mb-1.5 flex items-center gap-2 rounded-md border border-accent/40 bg-accent/10 p-2 text-[11.5px]"><span className="size-2 animate-pulse rounded-full bg-accent" /> Finding the best moments and building clips…</div>}
      {!shorts.length && !generating && <div className="rounded-md border border-dashed border-border p-3 text-[11.5px] text-fg-subtle">Turn the most important parts of this video into vertical clips for YouTube Shorts, Instagram Reels or TikTok.</div>}
      <ul className="space-y-1">
        {shorts.map((t) => {
          const settings = t.settings as { platform?: string; target_duration?: number; highlight?: { title?: string; caption_suggestion?: string; score?: number } };
          const render = (renders ?? []).find((r) => r.timeline_version_id === t.current_version_id) ?? (renders ?? []).find((r) => String(r.settings.filename ?? "").startsWith((settings.highlight?.title ?? "\u0000").slice(0, 60)));
          const job = render?.job_id ? jobs[render.job_id] : undefined;
          const active = render && (render.status === "QUEUED" || render.status === "RUNNING");
          const platformLabel = SHORT_PLATFORMS.find((p) => p.id === settings.platform)?.label ?? "Short";
          return (
            <li key={t.id} className="rounded-md border border-border bg-panel-2 p-2">
              <div className="flex items-center gap-2">
                <Sparkles className="size-3.5 shrink-0 text-accent" />
                <button className="min-w-0 flex-1 truncate text-left text-[12px] font-medium hover:underline" onClick={() => set({ timelineId: t.id, selectedClipIds: [], previewDoc: null, previewSource: { kind: "timeline" }, playhead: 0 })} title="Open in the timeline editor">{t.name}</button>
                <Badge variant="secondary">{platformLabel}</Badge>
              </div>
              {settings.highlight?.caption_suggestion && <div className="mt-1 truncate text-[11px] text-fg-muted" title={settings.highlight.caption_suggestion}>{settings.highlight.caption_suggestion}</div>}
              <div className="mt-1.5 flex items-center gap-2 text-[10.5px] text-fg-subtle">
                <span>9:16 · ≤ {settings.target_duration ?? 45}s</span>
                {active && <span className="flex-1"><Progress value={(job?.progress ?? 0) * 100} /></span>}
                {render?.status === "FAILED" && <span className="text-danger">render failed</span>}
                {render?.status === "COMPLETED" && render.output_asset_id && (
                  <span className="ml-auto flex gap-1">
                    <Button size="xs" variant="ghost" onClick={() => set({ previewSource: { kind: "asset", assetId: render.output_asset_id! } })}><Play /> Play</Button>
                    <Button size="xs" variant="secondary" asChild><a href={render.download_url ?? "#"} download><Download /> Download</a></Button>
                  </span>
                )}
                {!render && <span className="ml-auto text-fg-subtle">not rendered — open to edit, or export</span>}
              </div>
            </li>
          );
        })}
      </ul>
      <ShortsDialog projectId={projectId} open={open} onOpenChange={setOpen} highlightIds={[]} />
    </section>
  );
}

export function EmptyCreator() {
  return <EmptyState icon={<Sparkles />} title="Creator tools" />;
}
