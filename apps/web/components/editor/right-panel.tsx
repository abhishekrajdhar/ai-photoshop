"use client";
import { Bot, Download, History, SlidersHorizontal } from "lucide-react";
import { EmptyState } from "@/components/ui/misc";
import { useAssets } from "@/lib/assets";
import type { RightTab } from "@/stores/editor";
import { useEditorStore } from "@/stores/editor";
import { formatBytes, formatDuration } from "@/lib/utils";

export function RightPanel({ projectId, tab }: { projectId: string; tab: RightTab }) {
  const selectedAssetId = useEditorStore((s) => s.selectedAssetId);
  const { data: assets } = useAssets(projectId);
  const asset = assets?.find((a) => a.id === selectedAssetId);
  if (tab === "inspector") {
    if (!asset) return <EmptyState icon={<SlidersHorizontal />} title="Inspector" description="Select a media asset or timeline clip to see its properties." />;
    const m = asset.metadata;
    const rows: [string, string][] = [
      ["File", asset.filename],
      ["Type", `${asset.media_type} · ${asset.mime_type}`],
      ["Size", formatBytes(asset.size_bytes)],
      ["Status", asset.status],
      ...(m ? ([
        ["Duration", m.duration != null ? formatDuration(m.duration) : "–"],
        ["Resolution", m.width ? `${m.width} × ${m.height}` : "–"],
        ["Frame rate", m.fps ? `${m.fps} fps` : "–"],
        ["Video codec", m.video_codec ?? "–"],
        ["Audio", m.audio_codec ? `${m.audio_codec} · ${m.audio_channels ?? "?"} ch · ${m.sample_rate ?? "?"} Hz` : "none"],
        ["Bitrate", m.bitrate ? `${Math.round(m.bitrate / 1000)} kb/s` : "–"],
        ["Container", m.container ?? "–"],
      ] as [string, string][]) : []),
      ["Hash", asset.content_hash ? asset.content_hash.slice(0, 16) + "…" : "–"],
    ];
    return (
      <div className="p-3">
        <div className="mb-2 text-[11px] uppercase tracking-wider text-fg-subtle">Asset</div>
        <dl className="space-y-1.5 text-[12px]">
          {rows.map(([k, v]) => (
            <div key={k} className="grid grid-cols-[90px_1fr] gap-2">
              <dt className="text-fg-muted">{k}</dt>
              <dd className="truncate" title={v}>{v}</dd>
            </div>
          ))}
        </dl>
        {asset.error && <div className="mt-3 rounded-md border border-danger/30 bg-danger/10 p-2 text-[12px] text-danger">{asset.error}</div>}
      </div>
    );
  }
  if (tab === "versions") return <EmptyState icon={<History />} title="Edit history" description="Versions appear here as you and the AI edit." />;
  if (tab === "export") return <EmptyState icon={<Download />} title="Export" description="Render presets are available once the timeline has clips." />;
  return <EmptyState icon={<Bot />} title="AI editor" description="Ask for edits in plain language once your footage is transcribed." />;
}
