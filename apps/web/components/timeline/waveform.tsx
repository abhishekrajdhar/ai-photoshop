"use client";
import { useEffect, useRef } from "react";
import { useWaveform } from "@/lib/waveforms";

interface Props {
  assetId: string | null;
  sourceIn: number;
  sourceOut: number;
  width: number;
  height: number;
  color?: string;
  muted?: boolean;
}

/** Canvas waveform for a clip's visible source range. Peaks come from the precomputed asset waveform. */
export function Waveform({ assetId, sourceIn, sourceOut, width, height, color = "rgba(255,255,255,0.55)", muted }: Props) {
  const { data } = useWaveform(assetId, width > 8);
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !data || width <= 0 || height <= 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);
    const { peaks, sample_rate } = data;
    const first = Math.max(0, Math.floor(sourceIn * sample_rate));
    const last = Math.min(peaks.length, Math.ceil(sourceOut * sample_rate));
    const n = Math.max(1, last - first);
    const step = n / width;
    ctx.fillStyle = muted ? "rgba(255,255,255,0.2)" : color;
    const mid = height / 2;
    for (let x = 0; x < width; x++) {
      const a = first + Math.floor(x * step);
      const b = Math.max(a + 1, first + Math.floor((x + 1) * step));
      let peak = 0;
      for (let i = a; i < b && i < peaks.length; i++) peak = Math.max(peak, peaks[i] ?? 0);
      const h = Math.max(1, peak * (height - 2));
      ctx.fillRect(x, mid - h / 2, 1, h);
    }
  }, [data, sourceIn, sourceOut, width, height, color, muted]);
  return <canvas ref={ref} style={{ width, height }} className="pointer-events-none absolute inset-0" />;
}
