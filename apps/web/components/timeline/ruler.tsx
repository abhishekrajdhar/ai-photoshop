"use client";
import { useMemo } from "react";
import { formatTime } from "@/lib/utils";
import type { Marker } from "@/lib/types";
import { Flag } from "lucide-react";

interface Props {
  width: number;
  zoom: number; // px per second
  fps: number;
  markers: Marker[];
  onSeek: (t: number) => void;
  onMarkerClick: (m: Marker) => void;
  onScrubStart: (e: React.MouseEvent) => void;
}

export function Ruler({ width, zoom, fps, markers, onMarkerClick, onScrubStart }: Props) {
  const ticks = useMemo(() => {
    // pick a major interval that yields ~80-160px spacing
    const candidates = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
    const major = candidates.find((c) => c * zoom >= 80) ?? 600;
    const minor = major / (major >= 1 ? 5 : 2);
    const out: { t: number; major: boolean }[] = [];
    const total = width / zoom;
    for (let t = 0; t <= total; t += minor) {
      const isMajor = Math.abs(t / major - Math.round(t / major)) < 1e-6;
      out.push({ t: Math.round(t * 1000) / 1000, major: isMajor });
    }
    return out;
  }, [width, zoom]);
  return (
    <div className="relative h-7 cursor-col-resize select-none border-b border-border bg-panel-2" style={{ width }} onMouseDown={onScrubStart}>
      {ticks.map(({ t, major }) => (
        <div key={t} className="absolute bottom-0" style={{ left: t * zoom }}>
          <div className={major ? "h-3 w-px bg-fg-subtle" : "h-1.5 w-px bg-border-strong"} />
          {major && <div className="absolute bottom-3.5 left-1 whitespace-nowrap text-mono text-[9.5px] text-fg-subtle">{formatTime(t, { frames: zoom > 200, fps })}</div>}
        </div>
      ))}
      {markers.map((m) => (
        <button
          key={m.id}
          className="absolute top-0.5 -translate-x-1/2 text-[10px]"
          style={{ left: m.time * zoom, color: m.kind === "broll_suggestion" ? "#06b6d4" : m.kind === "chapter" ? "#f5b53f" : m.color }}
          title={m.label || m.kind}
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            onMarkerClick(m);
          }}
        >
          <Flag className="size-3 fill-current" />
        </button>
      ))}
    </div>
  );
}
