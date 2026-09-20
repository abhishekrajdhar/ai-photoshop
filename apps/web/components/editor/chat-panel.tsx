"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Bot, Check, Eye, EyeOff, Loader2, Plus, Scissors, Send, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Badge, EmptyState, Progress } from "@/components/ui/misc";
import { Tip } from "@/components/ui/tooltip";
import { useAIStatus, useTranscript } from "@/lib/analysis";
import { ApiError } from "@/lib/api";
import { useAssets } from "@/lib/assets";
import { useChatMutations, useChatSessions } from "@/lib/chat";
import { useAIUsage } from "@/lib/creator";
import type { ChatMessage, ChatSession, EditOperation } from "@/lib/types";
import { cn, formatDuration, formatTime, relativeTime } from "@/lib/utils";
import { useEditorStore } from "@/stores/editor";
import { useJobsStore } from "@/stores/jobs";

const SUGGESTIONS = [
  "Remove pauses longer than 1 second",
  "Remove filler words",
  "Add captions",
  "Turn this into a fast-paced 6-minute YouTube video. Remove pauses, filler words and repeated points. Add captions and subtle zooms.",
  "Zoom in whenever the speaker says something important",
  "Create three 45-second Shorts from the strongest sections",
  "Reframe this video for 9:16",
  "Clean the audio and normalize loudness",
];

const OP_LABEL: Record<string, string> = {
  remove_segment: "cuts", silence_removal: "pause removals", filler_word_removal: "filler removals", jump_cut: "jump cuts", caption: "captions", subtitle: "subtitles",
  zoom: "zooms", insert_broll: "B-roll suggestions", reframe: "reframe", normalize_audio: "loudness normalization", noise_reduction: "noise reduction", voice_enhancement: "voice enhancement",
  audio_gain: "gain changes", music: "music", split: "cuts", transition: "transitions", text_overlay: "text overlays", speed_change: "speed changes", fade_audio: "audio fades", fade_video: "video fades",
};

export function ChatPanel({ projectId }: { projectId: string }) {
  const { data: sessions, isLoading } = useChatSessions(projectId);
  const { data: ai } = useAIStatus(projectId);
  const { data: transcript } = useTranscript(projectId);
  const { data: assets } = useAssets(projectId);
  const { data: usage } = useAIUsage(projectId);
  const m = useChatMutations(projectId);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [text, setText] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const session: ChatSession | undefined = useMemo(() => (sessionId ? sessions?.find((s) => s.id === sessionId) : sessions?.[0]), [sessions, sessionId]);
  const hasFootage = (assets ?? []).some((a) => a.kind === "original" && a.status === "ready" && a.media_type !== "image");
  const pending = session?.messages.some((x) => x.proposal?.status === "pending") ?? false;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [session?.messages.length, pending]);

  const submit = (message: string) => {
    const msg = message.trim();
    if (!msg || pending) return;
    setText("");
    m.send.mutate({ message: msg, session_id: session?.id ?? null }, { onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not send") });
  };

  return (
    <div className="flex h-full flex-col">
      <div className="panel-header justify-between">
        <span className="truncate">{session?.title || "AI editor"}</span>
        <div className="flex items-center gap-1">
          {sessions && sessions.length > 1 && (
            <select className="h-6 max-w-[120px] rounded-sm border border-border bg-panel-2 px-1 text-[11px] normal-case tracking-normal" value={session?.id ?? ""} onChange={(e) => setSessionId(e.target.value)}>
              {sessions.map((s) => <option key={s.id} value={s.id}>{s.title || "Chat"}</option>)}
            </select>
          )}
          <Tip label="New conversation"><Button variant="ghost" size="icon-xs" onClick={() => m.newSession.mutate(undefined, { onSuccess: (s) => setSessionId(s.id) })}><Plus /></Button></Tip>
        </div>
      </div>
      {ai && !ai.configured && (
        <div className="m-2 flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 p-2 text-[11.5px] text-warning">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span>No AI provider configured. Set <code className="text-mono">OPENAI_API_KEY</code> or <code className="text-mono">ANTHROPIC_API_KEY</code> in the API environment to enable AI editing.</span>
        </div>
      )}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto p-3">
        {isLoading ? null : !session || session.messages.length === 0 ? (
          <div className="space-y-3">
            <EmptyState icon={<Bot />} title="Describe the edit you want" description={transcript ? "The AI knows your transcript, pauses, filler words, scenes and content analysis." : hasFootage ? "Transcribe your footage first so the AI can edit by content." : "Upload footage to get started."} className="p-4" />
            <div className="space-y-1">
              {SUGGESTIONS.slice(0, 6).map((s) => (
                <button key={s} className="block w-full rounded-md border border-border bg-panel-2 px-2.5 py-1.5 text-left text-[12px] text-fg-muted hover:border-border-strong hover:text-fg" onClick={() => submit(s)} disabled={!hasFootage || pending}>
                  <Sparkles className="mr-1.5 inline size-3 text-accent" />{s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          session.messages.map((msg) => <MessageBubble key={msg.id} projectId={projectId} msg={msg} />)
        )}
      </div>
      <form
        className="border-t border-border p-2"
        onSubmit={(e) => {
          e.preventDefault();
          submit(text);
        }}
      >
        <div className="flex items-end gap-1.5">
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={pending ? "Working on it…" : "e.g. Remove pauses and add captions"}
            className="min-h-[40px] max-h-32 resize-none"
            rows={2}
            disabled={pending}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(text);
              }
            }}
          />
          <Button type="submit" size="icon" disabled={!text.trim() || pending || !hasFootage} loading={m.send.isPending}><Send /></Button>
        </div>
        <div className="mt-1 flex justify-between text-[10.5px] text-fg-subtle">
          <span>Enter to send · Shift+Enter for a new line · proposals need your approval</span>
          {usage && usage.total_requests > 0 && <span title={`${usage.total_requests} AI requests`}>~${usage.total_cost_usd.toFixed(3)} AI spend</span>}
        </div>
      </form>
    </div>
  );
}

function summarizeOps(ops: EditOperation[]): { label: string; count: number; seconds: number }[] {
  const acc = new Map<string, { count: number; seconds: number }>();
  for (const op of ops) {
    const key = op.type;
    const cur = acc.get(key) ?? { count: 0, seconds: 0 };
    const segs = op.segments?.length ? op.segments : op.start != null && op.end != null ? [{ start: op.start, end: op.end }] : [];
    const secs = ["remove_segment", "silence_removal", "filler_word_removal", "jump_cut"].includes(key) ? segs.reduce((n, s) => n + (Number(s.end) - Number(s.start)), 0) : 0;
    const n = ["silence_removal", "filler_word_removal"].includes(key) ? segs.length : 1;
    acc.set(key, { count: cur.count + n, seconds: cur.seconds + secs });
  }
  return [...acc.entries()].map(([k, v]) => ({ label: OP_LABEL[k] ?? k.replace(/_/g, " "), ...v }));
}

function MessageBubble({ projectId, msg }: { projectId: string; msg: ChatMessage }) {
  const m = useChatMutations(projectId);
  const job = useJobsStore((s) => (msg.job_id ? s.jobs[msg.job_id] : undefined));
  const { previewMessageId, cutOverlay, set } = useEditorStore();
  const p = msg.proposal;
  const isUser = msg.role === "user";
  if (isUser) {
    return (
      <div className="mb-3 flex justify-end">
        <div className="max-w-[88%] rounded-lg rounded-br-sm bg-accent/20 px-3 py-2 text-[12.5px]">{msg.content}</div>
      </div>
    );
  }
  const pendingState = p?.status === "pending";
  const ops = (p?.operations ?? []) as EditOperation[];
  const groups = summarizeOps(ops);
  const removalRanges = ops.flatMap((op) => (["remove_segment", "silence_removal", "filler_word_removal", "jump_cut"].includes(op.type) ? (op.segments?.length ? op.segments : op.start != null && op.end != null ? [{ start: op.start, end: op.end }] : []) : [])).map((s) => ({ start: Number(s.start), end: Number(s.end) }));
  const assetId = (ops.find((o) => o.asset_id)?.asset_id as string | undefined) ?? null;
  const showingCuts = cutOverlay !== null && previewMessageId === null && cutOverlay.ranges === removalRanges;
  const previewing = previewMessageId === msg.id;
  const previewProposal = () => {
    m.preview.mutate(msg.id, {
      onSuccess: (res) => set({ previewDoc: res.document, previewMessageId: msg.id, cutOverlay: { assetId, ranges: res.removed_ranges }, playing: false }),
      onError: (e) => toast.error(e instanceof ApiError ? e.message : "Preview failed"),
    });
  };
  const applyProposal = () => {
    m.apply.mutate(msg.id, {
      onSuccess: (res) => {
        set({ previewDoc: null, previewMessageId: null, cutOverlay: null });
        toast.success("Applied", { description: `Timeline is now ${formatDuration(res.state.version.duration)} (v${res.state.version.version})` });
        if (res.jobs.length) toast.info(`${res.jobs.length} job${res.jobs.length > 1 ? "s" : ""} started`);
      },
      onError: (e) => toast.error(e instanceof ApiError ? e.message : "Apply failed"),
    });
  };
  return (
    <div className="mb-3 flex justify-start">
      <div className="w-full max-w-[94%] rounded-lg rounded-bl-sm border border-border bg-panel-2 px-3 py-2 text-[12.5px]">
        {pendingState ? (
          <div>
            <div className="flex items-center gap-2 text-fg-muted"><Loader2 className="size-3.5 animate-spin text-accent" />{job?.message || "Thinking…"}</div>
            {job && <Progress className="mt-2" value={Math.max(5, job.progress * 100)} />}
          </div>
        ) : (
          <>
            <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
            {p?.status === "failed" && <div className="mt-2 flex items-center gap-1.5 text-[11.5px] text-danger"><AlertTriangle className="size-3.5" /> Request failed</div>}
            {p && (p.status === "proposed" || p.status === "applied" || p.status === "rejected") && (ops.length > 0 || p.side_effects?.length) ? (
              <div className={cn("mt-2 rounded-md border p-2", p.status === "applied" ? "border-success/40 bg-success/5" : p.status === "rejected" ? "border-border opacity-70" : "border-accent/40 bg-accent/5")}>
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">Proposal</span>
                  <Badge variant={p.status === "applied" ? "success" : p.status === "rejected" ? "secondary" : "default"}>{p.status}</Badge>
                </div>
                {p.summary && p.summary !== msg.content && <div className="mb-1.5 text-fg-muted">{p.summary}</div>}
                <ul className="mb-1.5 space-y-0.5 text-[12px]">
                  {groups.map((g) => (
                    <li key={g.label} className="flex justify-between"><span>{g.count} {g.label}</span>{g.seconds > 0 && <span className="text-mono text-fg-subtle">−{formatTime(g.seconds)}</span>}</li>
                  ))}
                  {(p.side_effects ?? []).map((se, i) => (
                    <li key={i} className="text-fg-muted">→ starts {se.kind === "shorts" ? "Shorts generation" : se.kind === "render" ? "a render" : se.kind}</li>
                  ))}
                </ul>
                {p.estimated_duration_delta != null && (
                  <div className="text-[11.5px] text-fg-muted">Duration change: <span className={cn("text-mono", p.estimated_duration_delta < 0 ? "text-success" : "text-fg")}>{p.estimated_duration_delta > 0 ? "+" : ""}{formatTime(Math.abs(p.estimated_duration_delta))}</span>{p.duration_after != null && <> · result {formatDuration(p.duration_after)}</>}</div>
                )}
                {p.warnings?.length > 0 && <ul className="mt-1 space-y-0.5 text-[11px] text-warning">{p.warnings.slice(0, 4).map((w, i) => <li key={i}>• {w}</li>)}</ul>}
                {p.rejected?.length ? <div className="mt-1 text-[11px] text-fg-subtle">{p.rejected.length} operation(s) skipped as not applicable.</div> : null}
                {p.status === "proposed" && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    <Button size="xs" onClick={applyProposal} loading={m.apply.isPending}><Check /> Apply changes</Button>
                    {previewing ? (
                      <Button size="xs" variant="secondary" onClick={() => set({ previewDoc: null, previewMessageId: null, cutOverlay: null })}><EyeOff /> Exit preview</Button>
                    ) : (
                      <Button size="xs" variant="secondary" onClick={previewProposal} loading={m.preview.isPending}><Eye /> Preview</Button>
                    )}
                    {removalRanges.length > 0 && (
                      <Button size="xs" variant="ghost" onClick={() => set({ cutOverlay: showingCuts ? null : { assetId, ranges: removalRanges } })}><Scissors /> {showingCuts ? "Hide cuts" : "Show cuts"}</Button>
                    )}
                    <Button size="xs" variant="ghost" onClick={() => { set({ previewDoc: null, previewMessageId: null, cutOverlay: null }); m.reject.mutate(msg.id); }}><X /> Reject</Button>
                  </div>
                )}
              </div>
            ) : null}
            {msg.tool_calls?.length > 0 && (
              <details className="mt-1.5 text-[11px] text-fg-subtle">
                <summary className="cursor-pointer">{msg.tool_calls.length} tool call{msg.tool_calls.length > 1 ? "s" : ""}</summary>
                <ul className="mt-1 space-y-0.5">{(msg.tool_calls as { name: string }[]).map((t, i) => <li key={i} className="text-mono">{t.name}</li>)}</ul>
              </details>
            )}
            <div className="mt-1 text-[10px] text-fg-subtle">{relativeTime(msg.created_at)}</div>
          </>
        )}
      </div>
    </div>
  );
}
