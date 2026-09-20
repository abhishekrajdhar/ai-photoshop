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

export function ShortsDialog({ projectId, open, onOpenChange, highlightIds }: { projectId: string; open: boolean; onOpenChange: (o: boolean) => void; highlightIds: string[] }) {
  const m = useCreatorMutations(projectId);
  const [count, setCount] = useState("3");
  const [duration, setDuration] = useState("45");
  const [preset, setPreset] = useState("bold");
  const [reframe, setReframe] = useState(true);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Generate Shorts</DialogTitle>
          <DialogDescription>Each Short becomes its own 9:16 timeline with jump cuts, captions, smart zooms and subject tracking. Hook-first when a hook line is found.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-[12px]">
          {highlightIds.length > 0 ? (
            <div className="rounded-md border border-accent/40 bg-accent/10 p-2">Using {highlightIds.length} selected highlight{highlightIds.length > 1 ? "s" : ""}.</div>
          ) : (
            <div className="grid grid-cols-[100px_1fr] items-center gap-2"><Label>How many</Label><Select value={count} onValueChange={setCount}><SelectTrigger className="h-7"><SelectValue /></SelectTrigger><SelectContent>{["1", "2", "3", "5", "8"].map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}</SelectContent></Select></div>
          )}
          <div className="grid grid-cols-[100px_1fr] items-center gap-2"><Label>Duration</Label><Select value={duration} onValueChange={setDuration}><SelectTrigger className="h-7"><SelectValue /></SelectTrigger><SelectContent>{["15", "30", "45", "60", "90"].map((n) => <SelectItem key={n} value={n}>{n} seconds</SelectItem>)}</SelectContent></Select></div>
          <div className="grid grid-cols-[100px_1fr] items-center gap-2"><Label>Caption style</Label><Select value={preset} onValueChange={setPreset}><SelectTrigger className="h-7"><SelectValue /></SelectTrigger><SelectContent>{["bold", "karaoke", "clean", "minimal", "boxed"].map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}</SelectContent></Select></div>
          <div className="grid grid-cols-[100px_1fr] items-center gap-2"><Label>Track subject</Label><Switch checked={reframe} onCheckedChange={setReframe} /></div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button loading={m.generateShorts.isPending} onClick={() => m.generateShorts.mutate({ count: highlightIds.length || Number(count), duration: Number(duration) as 15 | 30 | 45 | 60 | 90, caption_preset: preset, reframe, highlight_ids: highlightIds.length ? highlightIds : undefined }, { onSuccess: () => { onOpenChange(false); toast.success("Generating Shorts — they will appear in the timeline switcher"); }, onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed") })}><Wand2 /> Generate</Button>
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
  const set = useEditorStore((s) => s.set);
  const shorts = (timelines ?? []).filter((t) => t.kind === "short");
  if (!shorts.length) return null;
  return (
    <section>
      <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Shorts · {shorts.length}</h4>
      <ul className="space-y-1">
        {shorts.map((t) => (
          <li key={t.id}>
            <button className="flex w-full items-center gap-2 rounded-md border border-border bg-panel-2 px-2 py-1.5 text-left hover:border-border-strong" onClick={() => set({ timelineId: t.id, selectedClipIds: [], previewDoc: null, previewSource: { kind: "timeline" }, playhead: 0 })}>
              <Sparkles className="size-3.5 text-accent" />
              <span className="min-w-0 flex-1 truncate text-[12px]">{t.name}</span>
              <span className="text-[10.5px] text-fg-subtle">9:16</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function EmptyCreator() {
  return <EmptyState icon={<Sparkles />} title="Creator tools" />;
}
