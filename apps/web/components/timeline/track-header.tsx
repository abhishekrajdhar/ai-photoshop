"use client";
import { Eye, EyeOff, Lock, LockOpen, Volume2, VolumeX } from "lucide-react";
import { Tip } from "@/components/ui/tooltip";
import type { Track } from "@/lib/types";
import { cn } from "@/lib/utils";

export const TRACK_COLORS: Record<Track["kind"], string> = {
  video: "var(--color-track-video)",
  audio: "var(--color-track-audio)",
  caption: "var(--color-track-caption)",
  overlay: "var(--color-track-overlay)",
};

export function trackHeight(kind: Track["kind"]): number {
  return kind === "video" ? 56 : kind === "audio" ? 44 : 30;
}

export function TrackHeader({ track, onChange }: { track: Track; onChange: (patch: Partial<Track>) => void }) {
  const Btn = ({ on, onIcon, offIcon, label, patch }: { on: boolean; onIcon: React.ReactNode; offIcon: React.ReactNode; label: string; patch: Partial<Track> }) => (
    <Tip label={label}>
      <button className={cn("rounded-sm p-0.5 text-fg-subtle hover:text-fg [&_svg]:size-3", on && "text-warning")} onClick={() => onChange(patch)}>
        {on ? onIcon : offIcon}
      </button>
    </Tip>
  );
  return (
    <div className="flex items-center gap-1 border-b border-border bg-panel px-1.5" style={{ height: trackHeight(track.kind) }}>
      <div className="h-[70%] w-[3px] rounded-full" style={{ background: TRACK_COLORS[track.kind] }} />
      <div className="min-w-0 flex-1 truncate text-[11px] font-medium text-fg-muted">{track.name}</div>
      {(track.kind === "audio" || track.kind === "video") && (
        <Btn on={track.muted} onIcon={<VolumeX />} offIcon={<Volume2 />} label={track.muted ? "Unmute track" : "Mute track (audio)"} patch={{ muted: !track.muted }} />
      )}
      {track.kind !== "audio" && <Btn on={track.hidden} onIcon={<EyeOff />} offIcon={<Eye />} label={track.hidden ? "Show track" : "Hide track"} patch={{ hidden: !track.hidden }} />}
      <Btn on={track.locked} onIcon={<Lock />} offIcon={<LockOpen />} label={track.locked ? "Unlock track" : "Lock track"} patch={{ locked: !track.locked }} />
    </div>
  );
}
