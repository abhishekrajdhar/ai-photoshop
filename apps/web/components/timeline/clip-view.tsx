"use client";
import { memo } from "react";
import { Captions, Image as ImageIcon, Link2, Music, ZoomIn, Type, Volume2, VolumeX, Scissors, Trash2, Unlink, Gauge, Blend, ArrowRightLeft } from "lucide-react";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuShortcut, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Waveform } from "@/components/timeline/waveform";
import type { Clip, MediaAsset, Track } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  clip: Clip;
  track: Track;
  zoom: number;
  height: number;
  selected: boolean;
  asset?: MediaAsset;
  playhead: number;
  onMouseDown: (e: React.MouseEvent, clip: Clip, mode: "move" | "trim-in" | "trim-out") => void;
  onSplit: (clip: Clip) => void;
  onDelete: (clip: Clip, ripple: boolean) => void;
  onToggleMute: (clip: Clip) => void;
  onUnlink: (clip: Clip) => void;
  onSpeed: (clip: Clip, speed: number) => void;
  onTransition: (clip: Clip, kind: "crossfade" | "fade_black" | "cut") => void;
  onAddZoom: (clip: Clip) => void;
}

const KIND_BG: Record<Clip["kind"], string> = {
  video: "bg-track-video/25 border-track-video/60",
  audio: "bg-track-audio/20 border-track-audio/60",
  image: "bg-track-broll/25 border-track-broll/60",
  broll: "bg-track-broll/25 border-track-broll/60",
  caption: "bg-track-caption/20 border-track-caption/60",
  text: "bg-track-overlay/25 border-track-overlay/60",
  music: "bg-track-music/25 border-track-music/60",
};

export const ClipView = memo(function ClipView({ clip, track, zoom, height, selected, asset, playhead, onMouseDown, onSplit, onDelete, onToggleMute, onUnlink, onSpeed, onTransition, onAddZoom }: Props) {
  const left = clip.timeline_start * zoom;
  const width = Math.max(2, clip.duration * zoom);
  const underPlayhead = playhead >= clip.timeline_start && playhead < clip.timeline_start + clip.duration;
  const showWave = (clip.kind === "audio" || clip.kind === "music" || (clip.kind === "video" && track.kind === "audio")) && !!clip.asset_id;
  const thumb = clip.kind === "video" || clip.kind === "broll" || clip.kind === "image" ? asset?.thumbnail_url : undefined;
  const Icon = clip.kind === "music" ? Music : clip.kind === "caption" ? Captions : clip.kind === "text" ? Type : clip.kind === "image" || clip.kind === "broll" ? ImageIcon : null;
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <div
          data-clip-id={clip.id}
          className={cn(
            "absolute top-1 overflow-hidden rounded-md border text-[11px] transition-shadow",
            KIND_BG[clip.kind],
            selected ? "z-10 ring-2 ring-fg/90 shadow-lg" : "hover:brightness-110",
            clip.muted && "opacity-60",
            track.locked && "cursor-not-allowed opacity-70",
          )}
          style={{ left, width, height: height - 8, cursor: track.locked ? undefined : "grab" }}
          onMouseDown={(e) => {
            if (e.button !== 0 || track.locked) return;
            const rect = e.currentTarget.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const mode = width > 24 && x < 8 ? "trim-in" : width > 24 && x > width - 8 ? "trim-out" : "move";
            onMouseDown(e, clip, mode);
          }}
        >
          {thumb && (
            <div className="absolute inset-0 opacity-30" style={{ backgroundImage: `url(${thumb})`, backgroundSize: "auto 100%", backgroundRepeat: "repeat-x" }} />
          )}
          {showWave && <Waveform assetId={clip.asset_id} sourceIn={clip.source_in} sourceOut={clip.source_out} width={width} height={height - 8} muted={clip.muted} color={clip.kind === "music" ? "rgba(216,180,254,0.7)" : "rgba(134,239,172,0.7)"} />}
          <div className="pointer-events-none relative flex h-full flex-col justify-between p-1">
            <div className="flex items-center gap-1 truncate font-medium">
              {Icon && <Icon className="size-3 shrink-0 opacity-80" />}
              {clip.muted && <VolumeX className="size-3 shrink-0 text-warning" />}
              {clip.linked_clip_id && track.kind === "audio" && <Link2 className="size-2.5 shrink-0 opacity-60" />}
              <span className="truncate">{clip.kind === "caption" || clip.kind === "text" ? clip.text : clip.name || clip.kind}</span>
              {clip.speed !== 1 && <span className="ml-auto rounded-sm bg-black/40 px-1 text-[9.5px]">{clip.speed}×</span>}
            </div>
            {clip.effects.length > 0 && (
              <div className="relative h-3">
                {clip.effects.map((fx) => (
                  <span key={fx.id} className="absolute -translate-x-1/2 rounded-sm bg-black/60 px-0.5 text-[9px] text-fg-muted" style={{ left: (fx.start ?? 0) * zoom }} title={fx.type}>
                    {fx.type === "zoom" ? <ZoomIn className="inline size-2.5" /> : fx.type.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            )}
          </div>
          {clip.transition_in.type !== "cut" && <div className="absolute left-0 top-0 h-full w-[10px] bg-gradient-to-r from-white/40 to-transparent" title={`${clip.transition_in.type} in`} />}
          {clip.transition_out.type !== "cut" && <div className="absolute right-0 top-0 h-full w-[10px] bg-gradient-to-l from-white/40 to-transparent" title={`${clip.transition_out.type} out`} />}
          {(clip.fade_in > 0 || clip.fade_out > 0) && track.kind === "audio" && (
            <>
              {clip.fade_in > 0 && <div className="absolute left-0 top-0 h-full border-t border-white/50" style={{ width: clip.fade_in * zoom, background: "linear-gradient(to right, rgba(0,0,0,.35), transparent)" }} />}
              {clip.fade_out > 0 && <div className="absolute right-0 top-0 h-full border-t border-white/50" style={{ width: clip.fade_out * zoom, background: "linear-gradient(to left, rgba(0,0,0,.35), transparent)" }} />}
            </>
          )}
          {width > 24 && !track.locked && (
            <>
              <div className="absolute left-0 top-0 h-full w-2 cursor-ew-resize opacity-0 hover:opacity-100" style={{ background: "rgba(255,255,255,0.35)" }} />
              <div className="absolute right-0 top-0 h-full w-2 cursor-ew-resize opacity-0 hover:opacity-100" style={{ background: "rgba(255,255,255,0.35)" }} />
            </>
          )}
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem disabled={!underPlayhead} onSelect={() => onSplit(clip)}><Scissors /> Split at playhead <ContextMenuShortcut>S</ContextMenuShortcut></ContextMenuItem>
        <ContextMenuItem onSelect={() => onDelete(clip, true)}><Trash2 /> Ripple delete <ContextMenuShortcut>⌫</ContextMenuShortcut></ContextMenuItem>
        <ContextMenuItem onSelect={() => onDelete(clip, false)}><Trash2 /> Delete (leave gap) <ContextMenuShortcut>⇧⌫</ContextMenuShortcut></ContextMenuItem>
        <ContextMenuSeparator />
        {(track.kind === "audio" || clip.kind === "video") && <ContextMenuItem onSelect={() => onToggleMute(clip)}>{clip.muted ? <Volume2 /> : <VolumeX />} {clip.muted ? "Unmute" : "Mute"}</ContextMenuItem>}
        {clip.linked_clip_id && <ContextMenuItem onSelect={() => onUnlink(clip)}><Unlink /> Unlink audio/video</ContextMenuItem>}
        {(clip.kind === "video" || clip.kind === "broll") && <ContextMenuItem onSelect={() => onAddZoom(clip)}><ZoomIn /> Add zoom at playhead</ContextMenuItem>}
        {(clip.kind === "video" || clip.kind === "audio") && (
          <>
            <ContextMenuSeparator />
            {[1, 1.25, 1.5, 2].map((s) => (
              <ContextMenuItem key={s} onSelect={() => onSpeed(clip, s)}><Gauge /> Speed {s}× {clip.speed === s && "✓"}</ContextMenuItem>
            ))}
          </>
        )}
        {track.kind === "video" && (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem onSelect={() => onTransition(clip, "crossfade")}><Blend /> Crossfade out</ContextMenuItem>
            <ContextMenuItem onSelect={() => onTransition(clip, "fade_black")}><ArrowRightLeft /> Fade to black out</ContextMenuItem>
            {clip.transition_out.type !== "cut" && <ContextMenuItem onSelect={() => onTransition(clip, "cut")}>Remove transition</ContextMenuItem>}
          </>
        )}
      </ContextMenuContent>
    </ContextMenu>
  );
});
