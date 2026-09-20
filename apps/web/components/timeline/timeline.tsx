"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Flag, Magnet, Minus, Plus, Redo2, Scissors, Trash2, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/misc";
import { Slider } from "@/components/ui/slider";
import { Tip } from "@/components/ui/tooltip";
import { ClipView } from "@/components/timeline/clip-view";
import { Ruler } from "@/components/timeline/ruler";
import { TrackHeader, trackHeight } from "@/components/timeline/track-header";
import { useTimelineActions } from "@/components/timeline/use-timeline-actions";
import { clipEnd, docDuration, findClip, moveClipLocal, snapPoints, snapTo, trimClipLocal } from "@/lib/timeline-engine";
import type { Clip, TimelineDocument, Track } from "@/lib/types";
import { cn, formatTime } from "@/lib/utils";
import { useEditorStore } from "@/stores/editor";

const HEADER_W = 150;
const MIN_ZOOM = 4;
const MAX_ZOOM = 400;

export function Timeline({ projectId }: { projectId: string }) {
  const actions = useTimelineActions(projectId);
  const { doc: serverDoc, state, assetById } = actions;
  const { playhead, zoom, snapping, selectedClipIds, set, selectClip, setPlayhead } = useEditorStore();
  const [workingDoc, setWorkingDoc] = useState<TimelineDocument | null>(null);
  const doc = workingDoc ?? serverDoc;
  const lanesRef = useRef<HTMLDivElement>(null);
  const [viewportW, setViewportW] = useState(800);
  const fps = doc?.settings.fps ?? 30;

  useEffect(() => {
    const el = lanesRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setViewportW(el.clientWidth));
    ro.observe(el);
    setViewportW(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const duration = doc ? docDuration(doc) : 0;
  const contentW = Math.max(viewportW, (duration + 20) * zoom);

  const xToTime = useCallback(
    (clientX: number) => {
      const el = lanesRef.current;
      if (!el) return 0;
      const rect = el.getBoundingClientRect();
      return Math.max(0, (clientX - rect.left + el.scrollLeft) / zoom);
    },
    [zoom],
  );

  /* ── scrubbing ─────────────────────────────────────────────────────────── */
  const startScrub = useCallback(
    (e: React.MouseEvent) => {
      if (e.button !== 0) return;
      e.preventDefault();
      set({ playing: false, previewSource: { kind: "timeline" } });
      const move = (ev: MouseEvent) => setPlayhead(xToTime(ev.clientX));
      move(e.nativeEvent);
      const up = () => {
        window.removeEventListener("mousemove", move);
        window.removeEventListener("mouseup", up);
      };
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
    },
    [set, setPlayhead, xToTime],
  );

  /* ── clip drag / trim ──────────────────────────────────────────────────── */
  const onClipMouseDown = useCallback(
    (e: React.MouseEvent, clip: Clip, mode: "move" | "trim-in" | "trim-out") => {
      if (!serverDoc) return;
      e.preventDefault();
      e.stopPropagation();
      if (mode === "move") {
        if (!selectedClipIds.includes(clip.id)) selectClip(clip.id, e.metaKey || e.ctrlKey || e.shiftKey);
      } else {
        selectClip(clip.id);
      }
      const startX = e.clientX;
      const startY = e.clientY;
      const origin = { start: clip.timeline_start, end: clipEnd(clip) };
      const media = clip.asset_id ? assetById.get(clip.asset_id)?.metadata?.duration ?? undefined : undefined;
      const points = snapPoints(serverDoc, new Set([clip.id, clip.linked_clip_id ?? ""]));
      let latest: TimelineDocument | null = null;
      let moved = false;
      let targetTrackId: string | undefined;
      const trackAtY = (y: number): Track | undefined => {
        const el = lanesRef.current;
        if (!el) return undefined;
        let offset = el.getBoundingClientRect().top + 28 - el.scrollTop; // ruler height
        for (const t of serverDoc.tracks) {
          const h = trackHeight(t.kind);
          if (y >= offset && y < offset + h) return t;
          offset += h;
        }
        return undefined;
      };
      const onMove = (ev: MouseEvent) => {
        const dx = (ev.clientX - startX) / zoom;
        if (!moved && Math.abs(ev.clientX - startX) < 3 && Math.abs(ev.clientY - startY) < 3) return;
        moved = true;
        set({ drag: { kind: mode, clipId: clip.id } });
        const tol = (snapping && !ev.altKey ? 8 : 0) / zoom;
        if (mode === "move") {
          let ns = Math.max(0, origin.start + dx);
          if (tol) {
            const s1 = snapTo(ns, points, tol);
            const s2 = snapTo(ns + clip.duration, points, tol) - clip.duration;
            ns = Math.abs(s1 - ns) <= Math.abs(s2 - ns) ? s1 : s2;
          }
          const t = trackAtY(ev.clientY);
          const found = findClip(serverDoc, clip.id);
          targetTrackId = t && found && t.kind === found.track.kind && !t.locked ? t.id : undefined;
          latest = moveClipLocal(serverDoc, clip.id, ns, targetTrackId);
        } else if (mode === "trim-in") {
          let v = origin.start + dx;
          if (tol) v = snapTo(v, points, tol);
          v = snapTo(v, [playhead], tol);
          latest = trimClipLocal(serverDoc, clip.id, "in", v, media);
        } else {
          let v = origin.end + dx;
          if (tol) v = snapTo(v, points, tol);
          v = snapTo(v, [playhead], tol);
          latest = trimClipLocal(serverDoc, clip.id, "out", v, media);
        }
        setWorkingDoc(latest);
      };
      const onUp = () => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        set({ drag: null });
        if (moved && latest) {
          const f = findClip(latest, clip.id);
          if (f) {
            if (mode === "move") void actions.moveClip(clip.id, f.clip.timeline_start, targetTrackId);
            else void actions.trimClip(clip.id, mode === "trim-in" ? "in" : "out", mode === "trim-in" ? f.clip.timeline_start : clipEnd(f.clip));
          }
        }
        // keep the optimistic doc until the server document arrives
        setTimeout(() => setWorkingDoc(null), 0);
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    [actions, assetById, playhead, selectClip, selectedClipIds, serverDoc, set, snapping, zoom],
  );

  /* ── asset drop ────────────────────────────────────────────────────────── */
  const [dropHint, setDropHint] = useState<{ trackId: string; t: number } | null>(null);
  const trackForDrop = (y: number): Track | undefined => {
    const el = lanesRef.current;
    if (!el || !doc) return undefined;
    let offset = el.getBoundingClientRect().top + 28 - el.scrollTop;
    for (const t of doc.tracks) {
      const h = trackHeight(t.kind);
      if (y >= offset && y < offset + h) return t;
      offset += h;
    }
    return undefined;
  };

  /* ── shortcuts ─────────────────────────────────────────────────────────── */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      const st = useEditorStore.getState();
      const mod = e.metaKey || e.ctrlKey;
      if (e.code === "Space" || e.key === " ") {
        e.preventDefault();
        // A focused button would also fire a click on keyup → double toggle.
        if (target && target.tagName === "BUTTON") target.blur();
        st.togglePlay();
      } else if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) void actions.redo();
        else void actions.undo();
      } else if (e.key.toLowerCase() === "s" && !mod) {
        e.preventDefault();
        void actions.split(st.playhead, st.selectedClipIds.length ? st.selectedClipIds : undefined);
      } else if (e.key === "Delete" || e.key === "Backspace") {
        if (st.selectedClipIds.length) {
          e.preventDefault();
          void actions.deleteClips(st.selectedClipIds, !e.shiftKey);
        }
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        const step = e.shiftKey ? 1 : 1 / fps;
        st.setPlayhead(st.playhead + (e.key === "ArrowLeft" ? -step : step));
        st.set({ playing: false });
      } else if (e.key === "Home") {
        st.setPlayhead(0);
      } else if (e.key === "End") {
        st.setPlayhead(duration);
      } else if (e.key === "=" || e.key === "+") {
        st.set({ zoom: Math.min(MAX_ZOOM, st.zoom * 1.25) });
      } else if (e.key === "-") {
        st.set({ zoom: Math.max(MIN_ZOOM, st.zoom / 1.25) });
      } else if (e.key.toLowerCase() === "m" && !mod) {
        void actions.addMarker(st.playhead);
      } else if (e.key === "Escape") {
        st.selectClip(null);
      } else if (mod && e.key.toLowerCase() === "a") {
        e.preventDefault();
        if (doc) st.set({ selectedClipIds: doc.tracks.flatMap((t) => t.clips.map((c) => c.id)) });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [actions, doc, duration, fps]);

  /* ── zoom with ctrl+wheel, keep playhead visible while playing ─────────── */
  const onWheel = (e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const el = lanesRef.current;
      if (!el) return;
      const t = xToTime(e.clientX);
      const nz = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
      set({ zoom: nz });
      requestAnimationFrame(() => {
        el.scrollLeft = t * nz - (e.clientX - el.getBoundingClientRect().left);
      });
    }
  };
  const playing = useEditorStore((s) => s.playing);
  useEffect(() => {
    const el = lanesRef.current;
    if (!el || !playing) return;
    const x = playhead * zoom;
    if (x < el.scrollLeft || x > el.scrollLeft + el.clientWidth - 40) el.scrollLeft = Math.max(0, x - 80);
  }, [playhead, playing, zoom]);

  const clipCount = useMemo(() => doc?.tracks.reduce((n, t) => n + t.clips.length, 0) ?? 0, [doc]);
  const selectedClips = selectedClipIds;

  if (!doc) return <div className="flex h-full items-center justify-center text-[12px] text-fg-subtle">Loading timeline…</div>;

  return (
    <div className="flex h-full flex-col" onWheel={onWheel}>
      {/* toolbar */}
      <div className="flex h-9 shrink-0 items-center gap-1 border-b border-border px-2">
        <span className="mr-2 text-[11px] font-semibold uppercase tracking-wider text-fg-muted">Timeline · {doc.name}</span>
        <Tip label={<>Undo <Kbd>⌘Z</Kbd></>}><Button variant="ghost" size="icon-sm" disabled={!state?.can_undo} onClick={() => actions.undo()}><Undo2 /></Button></Tip>
        <Tip label={<>Redo <Kbd>⌘⇧Z</Kbd></>}><Button variant="ghost" size="icon-sm" disabled={!state?.can_redo} onClick={() => actions.redo()}><Redo2 /></Button></Tip>
        <div className="mx-1 h-4 w-px bg-border" />
        <Tip label={<>Split at playhead <Kbd>S</Kbd></>}><Button variant="ghost" size="icon-sm" onClick={() => actions.split(playhead, selectedClips.length ? selectedClips : undefined)}><Scissors /></Button></Tip>
        <Tip label={<>Ripple delete <Kbd>⌫</Kbd></>}><Button variant="ghost" size="icon-sm" disabled={!selectedClips.length} onClick={() => actions.deleteClips(selectedClips, true)}><Trash2 /></Button></Tip>
        <Tip label={<>Add marker <Kbd>M</Kbd></>}><Button variant="ghost" size="icon-sm" onClick={() => actions.addMarker(playhead)}><Flag /></Button></Tip>
        <Tip label="Snapping"><Button variant="ghost" size="icon-sm" className={cn(snapping && "text-accent")} onClick={() => set({ snapping: !snapping })}><Magnet /></Button></Tip>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-mono text-[11px] text-fg-muted">{formatTime(playhead, { frames: true, fps })} / {formatTime(duration, { frames: true, fps })}</span>
          <span className="text-[10.5px] text-fg-subtle">{clipCount} clips · v{state?.version.version}</span>
          <Button variant="ghost" size="icon-xs" onClick={() => set({ zoom: Math.max(MIN_ZOOM, zoom / 1.25) })}><Minus /></Button>
          <Slider className="w-24" min={Math.log(MIN_ZOOM)} max={Math.log(MAX_ZOOM)} step={0.01} value={[Math.log(zoom)]} onValueChange={([v]) => set({ zoom: Math.exp(v ?? Math.log(40)) })} />
          <Button variant="ghost" size="icon-xs" onClick={() => set({ zoom: Math.min(MAX_ZOOM, zoom * 1.25) })}><Plus /></Button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* headers */}
        <div className="shrink-0 overflow-hidden border-r border-border" style={{ width: HEADER_W }}>
          <div className="h-7 border-b border-border bg-panel-2" />
          {doc.tracks.map((t) => (
            <TrackHeader key={t.id} track={t} onChange={(patch) => actions.updateTrack(t.id, patch)} />
          ))}
        </div>
        {/* lanes */}
        <div
          ref={lanesRef}
          className="relative min-w-0 flex-1 overflow-auto"
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes("application/x-cutpilot-asset")) {
              e.preventDefault();
              e.dataTransfer.dropEffect = "copy";
              const t = trackForDrop(e.clientY);
              setDropHint(t ? { trackId: t.id, t: xToTime(e.clientX) } : null);
            }
          }}
          onDragLeave={() => setDropHint(null)}
          onDrop={(e) => {
            const id = e.dataTransfer.getData("application/x-cutpilot-asset");
            setDropHint(null);
            if (!id) return;
            e.preventDefault();
            const asset = assetById.get(id);
            const t = trackForDrop(e.clientY);
            if (asset) void actions.addAssetClip(asset, snapping ? snapTo(xToTime(e.clientX), snapPoints(doc), 8 / zoom) : xToTime(e.clientX), t?.id);
          }}
        >
          <div style={{ width: contentW }} className="relative">
            <div className="sticky top-0 z-20">
              <Ruler width={contentW} zoom={zoom} fps={fps} markers={doc.markers} onSeek={setPlayhead} onScrubStart={startScrub} onMarkerClick={(m) => { setPlayhead(m.time); set({ selectedMarkerId: m.id }); }} />
            </div>
            {doc.tracks.map((track) => (
              <div
                key={track.id}
                className={cn("relative border-b border-border/70", track.kind === "video" ? "bg-[#0e0f15]" : track.kind === "audio" ? "bg-[#0d1210]" : "bg-[#101014]", dropHint?.trackId === track.id && "bg-accent/10")}
                style={{ height: trackHeight(track.kind) }}
                onMouseDown={(e) => {
                  if (e.button !== 0) return;
                  selectClip(null);
                  startScrub(e);
                }}
              >
                {track.clips.map((clip) => (
                  <ClipView
                    key={clip.id}
                    clip={clip}
                    track={track}
                    zoom={zoom}
                    height={trackHeight(track.kind)}
                    selected={selectedClips.includes(clip.id)}
                    asset={clip.asset_id ? assetById.get(clip.asset_id) : undefined}
                    playhead={playhead}
                    onMouseDown={onClipMouseDown}
                    onSplit={(c) => actions.split(playhead, [c.id])}
                    onDelete={(c, ripple) => actions.deleteClips([c.id], ripple)}
                    onToggleMute={(c) => actions.updateClip(c.id, { muted: !c.muted }, c.muted ? "Unmute clip" : "Mute clip")}
                    onUnlink={(c) => actions.updateClip(c.id, { linked_clip_id: null }, "Unlink clip")}
                    onSpeed={(c, speed) => actions.applyOps([{ type: "speed_change", source_clip_id: c.id, time_ref: "timeline", params: { speed } }], `Speed ${speed}×`)}
                    onTransition={(c, kind) => actions.updateClip(c.id, { transition_out: { type: kind, duration: kind === "cut" ? 0 : 0.5 } }, kind === "cut" ? "Remove transition" : `Add ${kind}`)}
                    onAddZoom={(c) => actions.applyOps([{ type: "zoom", source_clip_id: c.id, time_ref: "timeline", timestamp: Math.max(c.timeline_start, playhead), duration: 2, scale: 1.12 }], "Add zoom")}
                  />
                ))}
                {dropHint?.trackId === track.id && <div className="pointer-events-none absolute top-0 h-full w-px bg-accent" style={{ left: dropHint.t * zoom }} />}
              </div>
            ))}
            {/* playhead */}
            <div className="pointer-events-none absolute top-0 z-30 h-full w-px bg-danger" style={{ left: playhead * zoom }}>
              <div className="absolute -left-[5px] top-0 size-0 border-x-[5px] border-t-[7px] border-x-transparent border-t-danger" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
