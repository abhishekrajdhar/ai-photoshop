"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Film, Maximize2, Pause, Play, SkipBack, SkipForward, StepBack, StepForward, Volume2, VolumeX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState, Kbd } from "@/components/ui/misc";
import { Slider } from "@/components/ui/slider";
import { Tip } from "@/components/ui/tooltip";
import { useAssets } from "@/lib/assets";
import { useTimeline } from "@/lib/timeline";
import { clipEnd, docDuration, nextBoundary, playbackAt, type Playback } from "@/lib/timeline-engine";
import type { Clip, MediaAsset, TimelineDocument } from "@/lib/types";
import { cn, formatTime } from "@/lib/utils";
import { useEditorStore } from "@/stores/editor";

/**
 * Timeline player. The playhead is the clock; the visible <video> is driven to the source time of
 * the clip under the playhead, switching sources at clip boundaries (two elements, double-buffered).
 * Audio-only clips (music, unlinked audio) use their own <audio> elements.
 */
export function PreviewPanel({ projectId }: { projectId: string }) {
  const { data: assets } = useAssets(projectId);
  const timelineId = useEditorStore((s) => s.timelineId);
  const { data: state } = useTimeline(projectId, timelineId);
  const source = useEditorStore((s) => s.previewSource);
  const previewDoc = useEditorStore((s) => s.previewDoc);
  const asset = source.kind === "asset" ? assets?.find((a) => a.id === source.assetId) : undefined;
  const assetById = useMemo(() => new Map((assets ?? []).map((a) => [a.id, a])), [assets]);
  return (
    <div className="flex h-full flex-col">
      {asset && asset.status === "ready" ? (
        <AssetPreview asset={asset} />
      ) : previewDoc || state ? (
        <TimelinePlayer doc={previewDoc ?? state!.document} assetById={assetById} />
      ) : (
        <EmptyState icon={<Film />} title="Preview" />
      )}
    </div>
  );
}

function AssetPreview({ asset }: { asset: MediaAsset }) {
  const set = useEditorStore((s) => s.set);
  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-0 flex-1 items-center justify-center p-4">
        {asset.media_type === "image" ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={asset.stream_url} alt={asset.filename} className="max-h-full max-w-full rounded-md object-contain shadow-2xl" />
        ) : (
          <video key={asset.id} controls autoPlay className="max-h-full max-w-full rounded-md bg-black shadow-2xl" src={asset.stream_url} />
        )}
      </div>
      <div className="flex h-9 items-center justify-between border-t border-border px-3 text-[11.5px] text-fg-muted">
        <span>Source preview · {asset.filename}</span>
        <Button variant="ghost" size="xs" onClick={() => set({ previewSource: { kind: "timeline" } })}>Back to timeline</Button>
      </div>
    </div>
  );
}

function TimelinePlayer({ doc, assetById }: { doc: TimelineDocument; assetById: Map<string, MediaAsset> }) {
  const { playhead, playing, playbackRate, volume, muted, set } = useEditorStore();
  const containerRef = useRef<HTMLDivElement>(null);
  const videoRefs = [useRef<HTMLVideoElement>(null), useRef<HTMLVideoElement>(null)];
  const audioRefs = useRef<Map<string, HTMLAudioElement>>(new Map());
  const [active, setActive] = useState(0); // which video element is visible
  const activeClipId = useRef<string | null>(null);
  const duration = docDuration(doc);
  const playback: Playback = useMemo(() => playbackAt(doc, playhead), [doc, playhead]);
  const fps = doc.settings.fps || 30;

  const streamUrl = useCallback((clip: Clip) => (clip.asset_id ? assetById.get(clip.asset_id)?.stream_url ?? null : null), [assetById]);

  /* Drive the visible video element to the current playhead. */
  const sync = useCallback(
    (t: number, force = false) => {
      const pb = playbackAt(doc, t);
      const cur = pb.video;
      const el = videoRefs[active]!.current;
      if (!el) return;
      if (!cur) {
        if (activeClipId.current !== null) {
          activeClipId.current = null;
          el.pause();
        }
        return;
      }
      const url = streamUrl(cur.clip);
      if (!url) return;
      if (activeClipId.current !== cur.clip.id || force) {
        // Switch source: use the other buffer if it's already loaded with this clip's asset.
        const other = videoRefs[1 - active]!.current;
        let target = el;
        if (other && other.dataset.assetId === cur.clip.asset_id && other.readyState >= 2) {
          target = other;
          setActive(1 - active);
        }
        if (target.dataset.assetId !== cur.clip.asset_id) {
          target.src = url;
          target.dataset.assetId = cur.clip.asset_id ?? "";
          target.load();
          // currentTime set before metadata arrives is dropped: re-seek to the live playhead on load.
          target.addEventListener(
            "loadedmetadata",
            () => {
              const live = playbackAt(doc, useEditorStore.getState().playhead).video;
              if (live && live.clip.asset_id === target.dataset.assetId) {
                target.currentTime = live.sourceTime;
                if (useEditorStore.getState().playing) void target.play().catch(() => undefined);
              }
            },
            { once: true },
          );
        }
        target.playbackRate = playbackRate * cur.clip.speed;
        target.muted = muted || cur.clip.muted || !(pb.base && pb.base.clip.id === cur.clip.id) && !cur.clip.linked_clip_id;
        activeClipId.current = cur.clip.id;
        target.currentTime = cur.sourceTime;
        if (playing) void target.play().catch(() => undefined);
        // Preload the next clip's asset in the spare buffer
        const nb = nextBoundary(doc, t);
        if (nb !== null && other && target !== other) {
          const nxt = playbackAt(doc, nb + 0.001).video;
          if (nxt && nxt.clip.asset_id && other.dataset.assetId !== nxt.clip.asset_id) {
            const u = streamUrl(nxt.clip);
            if (u) {
              other.src = u;
              other.dataset.assetId = nxt.clip.asset_id;
              other.load();
              other.currentTime = nxt.sourceTime;
            }
          }
        }
      } else if (!playing || Math.abs(el.currentTime - cur.sourceTime) > 0.25) {
        el.currentTime = cur.sourceTime;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [doc, active, playing, playbackRate, muted, streamUrl],
  );

  /* Playback clock: rAF loop advancing the playhead from the active video's currentTime. */
  useEffect(() => {
    if (!playing) {
      videoRefs.forEach((r) => r.current?.pause());
      audioRefs.current.forEach((a) => a.pause());
      sync(playhead, false);
      return;
    }
    let raf = 0;
    let last = performance.now();
    let t = useEditorStore.getState().playhead;
    if (t >= duration - 0.02) t = 0;
    sync(t, true);
    const step = (now: number) => {
      const dt = ((now - last) / 1000) * playbackRate;
      last = now;
      const pb = playbackAt(doc, t);
      const el = videoRefs[active]!.current;
      if (pb.video && el && activeClipId.current === pb.video.clip.id && el.readyState >= 2 && !el.paused) {
        // video is the clock while a clip is playing
        t = pb.video.clip.timeline_start + (el.currentTime - pb.video.clip.source_in) / pb.video.clip.speed;
      } else {
        t += dt;
      }
      if (pb.video && el && el.paused && el.readyState >= 2) void el.play().catch(() => undefined);
      // clip boundary reached → switch
      if (pb.video && t >= clipEnd(pb.video.clip) - 0.02) {
        t = clipEnd(pb.video.clip);
        sync(t + 0.001, true);
      } else if (!pb.video) {
        const nb = nextBoundary(doc, t);
        if (nb !== null && t >= nb - 0.02) {
          t = nb;
          sync(t + 0.001, true);
        }
      }
      if (t >= duration) {
        set({ playing: false, playhead: duration });
        return;
      }
      useEditorStore.setState({ playhead: t });
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, doc, playbackRate, active]);

  /* Seek while paused */
  useEffect(() => {
    if (!playing) sync(playhead, false);
  }, [playhead, playing, sync]);

  /* Independent audio clips (music etc.) */
  useEffect(() => {
    const wanted = new Map<string, { clip: Clip; sourceTime: number }>();
    for (const a of playback.audio) {
      if (playback.base && a.clip.linked_clip_id === playback.base.clip.id) continue; // linked audio plays through the video element
      if (playback.video && a.clip.asset_id === playback.video.clip.asset_id && a.clip.linked_clip_id) continue;
      wanted.set(a.clip.id, a);
    }
    for (const [id, el] of audioRefs.current) {
      if (!wanted.has(id)) {
        el.pause();
        el.remove();
        audioRefs.current.delete(id);
      }
    }
    for (const [id, { clip, sourceTime }] of wanted) {
      let el = audioRefs.current.get(id);
      const url = streamUrl(clip);
      if (!url) continue;
      if (!el) {
        el = document.createElement("audio");
        el.src = url;
        el.preload = "auto";
        el.loop = clip.loop;
        audioRefs.current.set(id, el);
      }
      const gain = Math.pow(10, clip.gain_db / 20) * (clip.ducking && playback.base ? 0.35 : 1);
      el.volume = Math.max(0, Math.min(1, volume * gain));
      el.muted = muted || clip.muted;
      el.playbackRate = playbackRate;
      const srcT = clip.loop ? ((sourceTime - clip.source_in) % Math.max(0.1, clip.source_out - clip.source_in)) + clip.source_in : sourceTime;
      if (Math.abs(el.currentTime - srcT) > 0.3) el.currentTime = srcT;
      if (playing && el.paused) void el.play().catch(() => undefined);
      if (!playing) el.pause();
    }
  }, [playback, playing, volume, muted, playbackRate, streamUrl]);

  useEffect(() => {
    videoRefs.forEach((r) => {
      if (r.current) r.current.volume = volume;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [volume]);

  const aspect = doc.settings.width / doc.settings.height;
  const reframe = doc.settings.reframe;
  const sourceAspect = playback.video?.clip.asset_id ? (() => { const m = assetById.get(playback.video!.clip.asset_id!)?.metadata; return m?.width && m?.height ? m.width / m.height : 16 / 9; })() : 16 / 9;
  const activeCaption = playback.captions[0];
  const captionStyle = doc.settings.caption_style;
  const wordHighlight = activeCaption?.words?.find((w) => playhead - activeCaption.timeline_start >= w.start && playhead - activeCaption.timeline_start < w.end);

  return (
    <div className="flex h-full flex-col">
      <div ref={containerRef} data-preview-root className="flex min-h-0 flex-1 items-center justify-center p-3">
        <div className="relative max-h-full max-w-full overflow-hidden rounded-md bg-black shadow-2xl [container-type:inline-size]" style={{ aspectRatio: `${aspect}`, height: "100%", maxWidth: "100%" }}>
          {[0, 1].map((i) => (
            <video
              key={i}
              ref={videoRefs[i]}
              playsInline
              preload="auto"
              className={cn("absolute inset-0 size-full", i === active ? "opacity-100" : "opacity-0")}
              style={{
                objectFit: reframe ? "cover" : "contain",
                transform: i === active && playback.zoom ? `scale(${playback.zoom.scale})` : undefined,
                transformOrigin: playback.zoom ? `${playback.zoom.x * 100}% ${playback.zoom.y * 100}%` : "center",
                transition: "transform 80ms linear",
                objectPosition: reframe && reframe.keyframes?.length ? `${(reframe.keyframes[0]?.x ?? 0.5) * 100}% 50%` : "center",
              }}
            />
          ))}
          {!playback.video && <div className="absolute inset-0 flex items-center justify-center text-[12px] text-fg-subtle">{duration === 0 ? "Drop media on the timeline to start" : "Gap"}</div>}
          {playback.overlays.map(({ clip }) => {
            const pos = clip.position ?? { x: 0.5, y: 0.15, w: 0.8, h: 0.1 };
            const a = clip.asset_id ? assetById.get(clip.asset_id) : undefined;
            return (
              <div key={clip.id} className="absolute flex items-center justify-center" style={{ left: `${(pos.x - pos.w / 2) * 100}%`, top: `${(pos.y - pos.h / 2) * 100}%`, width: `${pos.w * 100}%`, height: `${pos.h * 100}%` }}>
                {clip.kind === "text" ? (
                  <span className="text-center font-semibold text-white drop-shadow-[0_2px_4px_rgba(0,0,0,.8)]" style={{ fontSize: `${(Number(clip.style.font_size ?? 48) / doc.settings.width) * 100}cqw` }}>{clip.text}</span>
                ) : a?.thumbnail_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={a.stream_url} alt="" className="size-full object-contain" />
                ) : null}
              </div>
            );
          })}
          {activeCaption && (
            <div className={cn("pointer-events-none absolute left-0 right-0 flex px-[6%]", captionStyle.position === "top" ? "top-[8%]" : captionStyle.position === "center" ? "top-1/2 -translate-y-1/2" : "bottom-[8%]", captionStyle.alignment === "left" ? "justify-start" : captionStyle.alignment === "right" ? "justify-end" : "justify-center")}>
              <span
                className="rounded px-2 py-1 text-center font-semibold leading-tight"
                style={{ fontSize: `${(captionStyle.font_size / doc.settings.width) * 100}cqw`, lineHeight: 1.25, color: captionStyle.color, background: captionStyle.background ?? "transparent", textShadow: `0 0 ${captionStyle.outline}px ${captionStyle.outline_color}, 0 0 ${captionStyle.outline * 2}px ${captionStyle.outline_color}`, textTransform: captionStyle.uppercase ? "uppercase" : undefined, fontFamily: captionStyle.font }}
              >
                {activeCaption.words?.length
                  ? activeCaption.words.map((w, i) => (
                      <span key={i} style={{ color: w === wordHighlight ? captionStyle.highlight_color : undefined }}>{w.text} </span>
                    ))
                  : activeCaption.text}
              </span>
            </div>
          )}
          {reframe && <div className="absolute right-1 top-1 rounded-sm bg-black/60 px-1 text-[9.5px] text-fg-muted">{doc.settings.aspect_ratio} · {reframe.mode === "track" ? "subject tracking" : "center"} · source {sourceAspect.toFixed(2)}</div>}
        </div>
      </div>
      <PlayerControls duration={duration} fps={fps} />
    </div>
  );
}

function PlayerControls({ duration, fps }: { duration: number; fps: number }) {
  const { playhead, playing, playbackRate, volume, muted, set, setPlayhead, togglePlay } = useEditorStore();
  const rates = [0.5, 1, 1.5, 2];
  return (
    <div className="flex h-10 shrink-0 items-center gap-1 border-t border-border px-2">
      <Tip label="Go to start (Home)"><Button variant="ghost" size="icon-sm" onClick={() => setPlayhead(0)}><SkipBack /></Button></Tip>
      <Tip label="Previous frame (←)"><Button variant="ghost" size="icon-sm" onClick={() => { set({ playing: false }); setPlayhead(playhead - 1 / fps); }}><StepBack /></Button></Tip>
      <Tip label={<>Play / pause <Kbd>Space</Kbd></>}><Button variant={playing ? "secondary" : "default"} size="icon-sm" onClick={togglePlay}>{playing ? <Pause /> : <Play />}</Button></Tip>
      <Tip label="Next frame (→)"><Button variant="ghost" size="icon-sm" onClick={() => { set({ playing: false }); setPlayhead(playhead + 1 / fps); }}><StepForward /></Button></Tip>
      <Tip label="Go to end (End)"><Button variant="ghost" size="icon-sm" onClick={() => setPlayhead(duration)}><SkipForward /></Button></Tip>
      <span className="ml-2 text-mono text-[11px] text-fg-muted">{formatTime(playhead, { frames: true, fps })} <span className="text-fg-subtle">/ {formatTime(duration, { frames: true, fps })}</span></span>
      <Slider className="mx-3 flex-1" min={0} max={Math.max(duration, 0.01)} step={1 / fps} value={[Math.min(playhead, duration)]} onValueChange={([v]) => { set({ playing: false }); setPlayhead(v ?? 0); }} />
      <select className="h-6 rounded-sm border border-border bg-panel-2 px-1 text-[11px]" value={playbackRate} onChange={(e) => set({ playbackRate: Number(e.target.value) })}>
        {rates.map((r) => <option key={r} value={r}>{r}×</option>)}
      </select>
      <Button variant="ghost" size="icon-sm" onClick={() => set({ muted: !muted })}>{muted || volume === 0 ? <VolumeX /> : <Volume2 />}</Button>
      <Slider className="w-16" min={0} max={1} step={0.01} value={[muted ? 0 : volume]} onValueChange={([v]) => set({ volume: v ?? 1, muted: false })} />
      <Tip label="Fullscreen"><Button variant="ghost" size="icon-sm" onClick={() => document.querySelector<HTMLElement>("[data-preview-root]")?.requestFullscreen?.()}><Maximize2 /></Button></Tip>
    </div>
  );
}
