"use client";
import { useQuery } from "@tanstack/react-query";

export interface WaveformData {
  sample_rate: number;
  duration: number;
  peaks: number[];
  rms?: number[];
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";

export function useWaveform(assetId: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ["waveform", assetId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/assets/${assetId}/waveform`, { credentials: "include" });
      if (!res.ok) return null;
      return (await res.json()) as WaveformData;
    },
    enabled: !!assetId && enabled,
    staleTime: Infinity,
  });
}
