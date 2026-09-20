"use client";
import { useMemo, useState } from "react";
import { AlertTriangle, BookOpen, FileText, Loader2, Pencil, Sparkles, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Badge, EmptyState, Progress, Skeleton } from "@/components/ui/misc";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tip } from "@/components/ui/tooltip";
import { useAssets } from "@/lib/assets";
import { useActiveAnalysisJobs, useAIStatus, useAnalysis, useRunAnalysis, useScenes, useTranscript, useTranscriptMutations } from "@/lib/analysis";
import { ApiError } from "@/lib/api";
import type { Transcript, TranscriptSegment } from "@/lib/types";
import { cn, formatDuration, formatTime } from "@/lib/utils";
import { useEditorStore } from "@/stores/editor";
import { JOB_LABEL } from "@/stores/jobs";

export function TranscriptPanel({ projectId }: { projectId: string }) {
  const [view, setView] = useState<"transcript" | "insights">("transcript");
  const { data: assets } = useAssets(projectId);
  const footage = useMemo(() => (assets ?? []).filter((a) => a.kind === "original" && a.status === "ready" && a.media_type !== "image"), [assets]);
  const [assetChoice, setAssetChoice] = useState<string | null>(null);
  const assetId = assetChoice && footage.some((a) => a.id === assetChoice) ? assetChoice : (footage[0]?.id ?? null);
  const { data: transcript, isLoading } = useTranscript(projectId, assetId);
  const { data: ai } = useAIStatus(projectId);
  const run = useRunAnalysis(projectId);
  const active = useActiveAnalysisJobs(projectId);
  const hasFootage = footage.length > 0;
  const analyzing = active.length > 0;

  const start = (steps: Parameters<typeof run.mutate>[0]["steps"]) =>
    run.mutate(
      { steps, asset_id: assetId },
      {
        onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not start analysis"),
        onSuccess: (r) => toast.success(`${r.jobs.length} job${r.jobs.length === 1 ? "" : "s"} queued`),
      },
    );

  return (
    <div className="flex h-full flex-col">
      <div className="panel-header justify-between">
        <Tabs value={view} onValueChange={(v) => setView(v as typeof view)}>
          <TabsList className="h-7">
            <TabsTrigger value="transcript" className="h-6"><FileText /> Transcript</TabsTrigger>
            <TabsTrigger value="insights" className="h-6"><Sparkles /> Insights</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex items-center gap-1">
          <Tip label="Transcribe footage (speech-to-text with word timestamps)">
            <Button variant="ghost" size="xs" disabled={!hasFootage || analyzing} loading={run.isPending} onClick={() => start(["transcription", "audio", "scenes"])}>
              <FileText /> Transcribe
            </Button>
          </Tip>
          <Tip label="Run the full analysis: transcript, silence, scenes, content understanding, vision">
            <Button variant="secondary" size="xs" disabled={!hasFootage || analyzing} onClick={() => start(["transcription", "audio", "scenes", "content", "vision"])}>
              <Wand2 /> Analyze
            </Button>
          </Tip>
        </div>
      </div>
      {footage.length > 1 && (
        <div className="border-b border-border px-2 py-1.5">
          <Select value={assetId ?? ""} onValueChange={(v) => setAssetChoice(v)}>
            <SelectTrigger className="h-7 text-[11.5px]"><SelectValue placeholder="Choose footage" /></SelectTrigger>
            <SelectContent>
              {footage.map((a) => (
                <SelectItem key={a.id} value={a.id}>{a.filename}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      {ai && !ai.transcription.available && (
        <div className="m-2 flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 p-2 text-[11.5px] text-warning">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span>No transcription provider configured. Set <code className="text-mono">OPENAI_API_KEY</code> or enable a local Whisper provider in the API environment.</span>
        </div>
      )}
      {active.length > 0 && (
        <div className="border-b border-border px-3 py-2">
          {active.map((j) => (
            <div key={j.id} className="mb-1.5 last:mb-0">
              <div className="flex items-center justify-between text-[11px]">
                <span className="flex items-center gap-1.5"><Loader2 className="size-3 animate-spin text-accent" />{JOB_LABEL[j.type] ?? j.type}</span>
                <span className="text-fg-subtle">{Math.round(j.progress * 100)}%</span>
              </div>
              <Progress className="mt-1" value={j.progress * 100} />
              {j.message && <div className="mt-0.5 truncate text-[10.5px] text-fg-subtle">{j.message}</div>}
            </div>
          ))}
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {view === "transcript" ? (
          isLoading ? (
            <div className="space-y-2 p-3">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
          ) : transcript ? (
            <TranscriptView projectId={projectId} transcript={transcript} />
          ) : (
            <EmptyState icon={<FileText />} title="No transcript yet" description={hasFootage ? "Transcribe your footage to edit by text and unlock AI editing." : "Upload footage first."} action={hasFootage ? <Button size="sm" onClick={() => start(["transcription", "audio", "scenes"])} disabled={analyzing}><FileText /> Transcribe</Button> : undefined} />
          )
        ) : (
          <InsightsView projectId={projectId} />
        )}
      </div>
    </div>
  );
}

function TranscriptView({ projectId, transcript }: { projectId: string; transcript: Transcript }) {
  const speakers = useMemo(() => Object.fromEntries(transcript.speakers.map((s) => [s.id, s])), [transcript.speakers]);
  const { renameSpeaker } = useTranscriptMutations(projectId);
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const totalWords = transcript.segments.reduce((n, s) => n + s.words.length, 0);
  const fillerCount = transcript.segments.reduce((n, s) => n + s.words.filter((w) => w.is_filler).length, 0);
  return (
    <div className="p-2">
      <div className="mb-2 flex flex-wrap items-center gap-1.5 px-1 text-[11px] text-fg-subtle">
        <Badge variant="secondary">{transcript.provider}</Badge>
        {transcript.language && <Badge variant="outline">{transcript.language}</Badge>}
        <span>{totalWords} words</span>
        {fillerCount > 0 && <span>· <span className="text-warning">{fillerCount} fillers</span></span>}
        <span className="ml-auto">click a word to seek · double-click text to edit</span>
      </div>
      {transcript.segments.map((seg, i) => {
        const prev = transcript.segments[i - 1];
        const showSpeaker = !prev || prev.speaker_id !== seg.speaker_id;
        const speaker = seg.speaker_id ? speakers[seg.speaker_id] : undefined;
        return (
          <div key={seg.id}>
            {showSpeaker && speaker && (
              <button className="mt-3 mb-1 flex items-center gap-1.5 px-1 text-[11px] font-semibold uppercase tracking-wider hover:underline" style={{ color: speaker.color ?? undefined }} onClick={() => setRenaming({ id: speaker.id, name: speaker.display_name })} title="Rename speaker">
                {speaker.display_name} <Pencil className="size-2.5 opacity-60" />
              </button>
            )}
            <SegmentRow projectId={projectId} segment={seg} />
          </div>
        );
      })}
      <Dialog open={!!renaming} onOpenChange={(o) => !o && setRenaming(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>Rename speaker</DialogTitle></DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (renaming) renameSpeaker.mutate({ id: renaming.id, display_name: renaming.name }, { onSuccess: () => setRenaming(null) });
            }}
          >
            <Input value={renaming?.name ?? ""} onChange={(e) => setRenaming((r) => (r ? { ...r, name: e.target.value } : r))} autoFocus />
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setRenaming(null)}>Cancel</Button>
              <Button type="submit" loading={renameSpeaker.isPending}>Save</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SegmentRow({ projectId, segment }: { projectId: string; segment: TranscriptSegment }) {
  const playhead = useEditorStore((s) => s.playhead);
  const setPlayhead = useEditorStore((s) => s.setPlayhead);
  const set = useEditorStore((s) => s.set);
  const { updateSegment, updateWord } = useTranscriptMutations(projectId);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(segment.text);
  const activeSeg = playhead >= segment.start && playhead < segment.end;
  const seek = (t: number) => {
    setPlayhead(t);
    set({ previewSource: { kind: "timeline" } });
  };
  if (editing) {
    return (
      <div className="mb-1 rounded-md border border-accent/50 bg-panel-2 p-2">
        <Textarea value={text} onChange={(e) => setText(e.target.value)} autoFocus className="min-h-[56px]" />
        <div className="mt-1.5 flex justify-end gap-1">
          <Button size="xs" variant="ghost" onClick={() => { setEditing(false); setText(segment.text); }}>Cancel</Button>
          <Button size="xs" loading={updateSegment.isPending} onClick={() => updateSegment.mutate({ id: segment.id, text }, { onSuccess: () => setEditing(false) })}>Save</Button>
        </div>
      </div>
    );
  }
  return (
    <div className={cn("group mb-0.5 flex gap-2 rounded-md px-1 py-1 hover:bg-panel-2", activeSeg && "bg-accent/5")} onDoubleClick={() => setEditing(true)}>
      <button className="mt-0.5 w-11 shrink-0 text-left text-mono text-[10.5px] text-fg-subtle hover:text-accent" onClick={() => seek(segment.start)}>{formatTime(segment.start)}</button>
      <p className="flex-1 text-[12.5px] leading-relaxed">
        {segment.words.length > 0
          ? segment.words.map((w) => (
              <span
                key={w.id}
                onClick={() => seek(w.start)}
                onContextMenu={(e) => { e.preventDefault(); updateWord.mutate({ id: w.id, is_filler: !w.is_filler }); }}
                title={w.is_filler ? "Filler word (right-click to unmark)" : `${formatTime(w.start)} (right-click to mark as filler)`}
                className={cn(
                  "cursor-pointer rounded-sm px-[1px] hover:bg-accent/25",
                  w.is_filler && "bg-warning/20 text-warning line-through decoration-warning/60",
                  playhead >= w.start && playhead < w.end && "bg-accent/40 text-white",
                )}
              >
                {w.text}{" "}
              </span>
            ))
          : segment.text}
      </p>
    </div>
  );
}

function InsightsView({ projectId }: { projectId: string }) {
  const { data: results, isLoading } = useAnalysis(projectId);
  const { data: scenes } = useScenes(projectId);
  const setPlayhead = useEditorStore((s) => s.setPlayhead);
  const byKind = useMemo(() => Object.fromEntries((results ?? []).map((r) => [r.kind, r.data])), [results]);
  const content = byKind.content as { summary?: { summary: string; topics: string[]; chapters: { start: number; end: number; title: string }[]; title_suggestions: string[]; pacing_notes: string; tone: string; audience: string }; aggregate?: Record<string, { start: number; end: number; reason?: string; text?: string; query?: string }[]> } | undefined;
  const silence = byKind.silence as { count: number; removable_seconds: number; total_silence_seconds: number } | undefined;
  const filler = byKind.filler as { count: number; removable_seconds: number } | undefined;
  const audio = byKind.audio_stats as { integrated_lufs?: number; needs_normalization?: boolean; max_volume_db?: number } | undefined;
  const vision = byKind.vision as { frames: { t: number; issues: string[] }[]; editing_opportunities: { t: number; suggestion: string; confidence: number }[] } | undefined;
  if (isLoading) return <div className="space-y-2 p-3">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-16" />)}</div>;
  if (!results?.length) return <EmptyState icon={<BookOpen />} title="No insights yet" description="Run Analyze to detect silence, filler words, scenes, chapters and visual notes." />;
  const issues = (vision?.frames ?? []).flatMap((f) => f.issues.map((i) => ({ t: f.t, issue: i })));
  return (
    <div className="space-y-3 p-3 text-[12px]">
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Pauses" value={silence ? `${silence.count}` : "–"} hint={silence ? `${formatDuration(silence.removable_seconds)} removable` : undefined} />
        <Stat label="Fillers" value={filler ? `${filler.count}` : "–"} hint={filler ? `${formatDuration(filler.removable_seconds)} removable` : undefined} />
        <Stat label="Loudness" value={audio?.integrated_lufs != null ? `${audio.integrated_lufs.toFixed(1)} LUFS` : "–"} hint={audio?.needs_normalization ? "normalize recommended" : undefined} />
      </div>
      {content?.summary && (
        <section>
          <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Summary</h4>
          <p className="leading-relaxed text-fg-muted">{content.summary.summary}</p>
          <div className="mt-1.5 flex flex-wrap gap-1">{content.summary.topics.slice(0, 10).map((t) => <Badge key={t} variant="secondary" className="normal-case tracking-normal">{t}</Badge>)}</div>
          {content.summary.title_suggestions?.length > 0 && (
            <div className="mt-2 text-[11.5px] text-fg-subtle">Titles: {content.summary.title_suggestions.slice(0, 3).join(" · ")}</div>
          )}
        </section>
      )}
      {content?.summary?.chapters?.length ? (
        <section>
          <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Chapters</h4>
          <ol className="space-y-0.5">
            {content.summary.chapters.map((c, i) => (
              <li key={i}><button className="flex w-full items-center gap-2 rounded-sm px-1 py-0.5 text-left hover:bg-panel-2" onClick={() => setPlayhead(c.start)}><span className="text-mono text-[10.5px] text-fg-subtle">{formatTime(c.start)}</span><span className="truncate">{c.title}</span></button></li>
            ))}
          </ol>
        </section>
      ) : null}
      {content?.aggregate?.removable_candidates?.length ? (
        <section>
          <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Removable candidates</h4>
          <ul className="space-y-0.5">
            {content.aggregate.removable_candidates.slice(0, 12).map((r, i) => (
              <li key={i}><button className="flex w-full gap-2 rounded-sm px-1 py-0.5 text-left hover:bg-panel-2" onClick={() => setPlayhead(r.start)}><span className="text-mono text-[10.5px] text-fg-subtle">{formatTime(r.start)}–{formatTime(r.end)}</span><span className="truncate text-fg-muted">{r.reason}</span></button></li>
            ))}
          </ul>
        </section>
      ) : null}
      {scenes && scenes.length > 0 && (
        <section>
          <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Scenes · {scenes.length}</h4>
          <div className="grid grid-cols-3 gap-1">
            {scenes.slice(0, 30).map((s) => (
              <button key={s.id} className="group relative aspect-video overflow-hidden rounded-sm bg-panel-2" onClick={() => setPlayhead(s.start)} title={s.description ?? undefined}>
                {s.thumbnail_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={s.thumbnail_url} alt="" className="size-full object-cover" loading="lazy" />
                ) : null}
                <span className="absolute bottom-0.5 left-0.5 rounded-sm bg-black/70 px-1 text-mono text-[9.5px]">{formatTime(s.start)}</span>
              </button>
            ))}
          </div>
        </section>
      )}
      {vision?.editing_opportunities?.length ? (
        <section>
          <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Visual opportunities</h4>
          <ul className="space-y-0.5">
            {vision.editing_opportunities.slice(0, 10).map((o, i) => (
              <li key={i}><button className="flex w-full gap-2 rounded-sm px-1 py-0.5 text-left hover:bg-panel-2" onClick={() => setPlayhead(o.t)}><span className="text-mono text-[10.5px] text-fg-subtle">{formatTime(o.t)}</span><span className="truncate text-fg-muted">{o.suggestion}</span></button></li>
            ))}
          </ul>
        </section>
      ) : null}
      {issues.length > 0 && (
        <section>
          <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Possible issues</h4>
          <ul className="space-y-0.5">
            {issues.slice(0, 10).map((o, i) => (
              <li key={i} className="flex gap-2 px-1 text-warning"><span className="text-mono text-[10.5px]">{formatTime(o.t)}</span><span className="truncate">{o.issue}</span></li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-border bg-panel-2 p-2">
      <div className="text-[10.5px] uppercase tracking-wider text-fg-subtle">{label}</div>
      <div className="text-[15px] font-semibold">{value}</div>
      {hint && <div className="truncate text-[10.5px] text-fg-subtle">{hint}</div>}
    </div>
  );
}
