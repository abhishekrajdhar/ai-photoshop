"use client";
import { useEffect, useRef } from "react";
import { Film } from "lucide-react";
import { EmptyState } from "@/components/ui/misc";
import { useAssets } from "@/lib/assets";
import { useEditorStore } from "@/stores/editor";

/** Preview: plays a selected asset's proxy. Timeline-synchronized playback arrives with the timeline module. */
export function PreviewPanel({ projectId }: { projectId: string }) {
  const source = useEditorStore((s) => s.previewSource);
  const { data: assets } = useAssets(projectId);
  const videoRef = useRef<HTMLVideoElement>(null);
  const asset = source.kind === "asset" ? assets?.find((a) => a.id === source.assetId) : undefined;
  useEffect(() => {
    videoRef.current?.load();
  }, [asset?.id]);
  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-0 flex-1 items-center justify-center p-4">
        {asset && asset.status === "ready" ? (
          asset.media_type === "image" ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={asset.stream_url} alt={asset.filename} className="max-h-full max-w-full rounded-md object-contain shadow-2xl" />
          ) : (
            <video ref={videoRef} controls className="max-h-full max-w-full rounded-md bg-black shadow-2xl" preload="metadata">
              <source src={asset.stream_url} />
            </video>
          )
        ) : (
          <EmptyState icon={<Film />} title="Preview" description="Select a clip in the Media panel to preview it. The timeline player takes over once you have clips on the timeline." />
        )}
      </div>
    </div>
  );
}
