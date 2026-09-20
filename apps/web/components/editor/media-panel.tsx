"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useDropzone } from "react-dropzone";
import { AlertTriangle, CheckCircle2, Film, FileAudio, Image as ImageIcon, Loader2, Music, RotateCcw, Trash2, Upload, X, Clapperboard, Pencil } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Badge, EmptyState, Progress, Skeleton } from "@/components/ui/misc";
import { Tip } from "@/components/ui/tooltip";
import { useAssetActions, useAssets } from "@/lib/assets";
import type { MediaAsset } from "@/lib/types";
import { cn, formatBytes, formatDuration } from "@/lib/utils";
import { useEditorStore } from "@/stores/editor";
import { useUploadsStore } from "@/stores/uploads";
import { useJobsStore } from "@/stores/jobs";

const ACCEPT = { "video/*": [".mp4", ".mov", ".webm", ".mkv"], "audio/*": [".wav", ".mp3", ".m4a"], "image/*": [".jpg", ".jpeg", ".png", ".webp"] };

function KindIcon({ asset }: { asset: MediaAsset }) {
  if (asset.kind === "music") return <Music className="size-4" />;
  if (asset.media_type === "audio") return <FileAudio className="size-4" />;
  if (asset.media_type === "image") return <ImageIcon className="size-4" />;
  return <Film className="size-4" />;
}

export function MediaPanel({ projectId }: { projectId: string }) {
  const { data: assets, isLoading } = useAssets(projectId);
  const enqueue = useUploadsStore((s) => s.enqueue);
  const uploadItems = useUploadsStore((s) => s.items);
  const uploads = useMemo(() => Object.values(uploadItems).filter((i) => i.projectId === projectId), [uploadItems, projectId]);
  const onDrop = useCallback((files: File[]) => enqueue(projectId, files), [enqueue, projectId]);
  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({ onDrop, accept: ACCEPT, noClick: true, noKeyboard: true });

  // Mark uploads done/failed when their asset flips state.
  const onAssetReady = useUploadsStore((s) => s.onAssetReady);
  const onAssetFailed = useUploadsStore((s) => s.onAssetFailed);
  useEffect(() => {
    for (const a of assets ?? []) {
      if (a.status === "ready") onAssetReady(a.id);
      if (a.status === "failed") onAssetFailed(a.id, a.error ?? "Processing failed");
    }
  }, [assets, onAssetReady, onAssetFailed]);

  const visibleUploads = uploads.filter((u) => u.status !== "done");
  const grouped = useMemo(() => {
    const list = assets ?? [];
    return {
      footage: list.filter((a) => a.kind === "original" && a.status !== "duplicate"),
      broll: list.filter((a) => a.kind === "broll" || a.kind === "image"),
      music: list.filter((a) => a.kind === "music"),
      renders: list.filter((a) => a.kind === "render" || a.kind === "export"),
      duplicates: list.filter((a) => a.status === "duplicate"),
    };
  }, [assets]);

  return (
    <div {...getRootProps()} className="relative flex h-full flex-col">
      <input {...getInputProps()} />
      <div className="panel-header justify-between">
        <span>Media</span>
        <Button variant="ghost" size="xs" onClick={open}><Upload /> Import</Button>
      </div>
      {isDragActive && (
        <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center border-2 border-dashed border-accent bg-accent/10 text-[13px] font-medium text-accent">
          Drop files to upload
        </div>
      )}
      <div className="flex-1 overflow-y-auto">
        {visibleUploads.length > 0 && (
          <div className="border-b border-border p-2">
            <div className="mb-1 flex items-center justify-between px-1 text-[11px] uppercase tracking-wider text-fg-subtle">
              <span>Uploads</span>
              <button className="hover:text-fg" onClick={() => useUploadsStore.getState().clearFinished()}>Clear</button>
            </div>
            {visibleUploads.map((u) => (
              <UploadRow key={u.id} id={u.id} />
            ))}
          </div>
        )}
        {isLoading ? (
          <div className="grid grid-cols-2 gap-2 p-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="aspect-video" />)}</div>
        ) : (assets?.length ?? 0) === 0 && visibleUploads.length === 0 ? (
          <EmptyState
            icon={<Upload />}
            title="No media yet"
            description="Drag footage here, or import MP4, MOV, WebM, MKV, WAV, MP3, M4A, JPEG, PNG or WebP."
            action={<Button size="sm" onClick={open}><Upload /> Import media</Button>}
          />
        ) : (
          <>
            <AssetGroup title="Footage" assets={grouped.footage} projectId={projectId} />
            <AssetGroup title="B-roll & images" assets={grouped.broll} projectId={projectId} />
            <AssetGroup title="Music & audio" assets={grouped.music} projectId={projectId} />
            <AssetGroup title="Renders" assets={grouped.renders} projectId={projectId} />
            <AssetGroup title="Skipped duplicates" assets={grouped.duplicates} projectId={projectId} />
          </>
        )}
      </div>
    </div>
  );
}

function UploadRow({ id }: { id: string }) {
  const item = useUploadsStore((s) => s.items[id]);
  const cancel = useUploadsStore((s) => s.cancel);
  const retry = useUploadsStore((s) => s.retry);
  const dismiss = useUploadsStore((s) => s.dismiss);
  const job = useJobsStore((s) => (item?.jobId ? s.jobs[item.jobId] : undefined));
  if (!item) return null;
  const processing = item.status === "processing";
  const pct = processing ? Math.round((job?.progress ?? 0) * 100) : Math.round(item.progress * 100);
  return (
    <div className="mb-1 rounded-md border border-border bg-panel-2 p-2">
      <div className="flex items-center gap-2">
        {item.status === "error" ? <AlertTriangle className="size-3.5 text-danger" /> : item.status === "duplicate" ? <CheckCircle2 className="size-3.5 text-warning" /> : <Loader2 className="size-3.5 animate-spin text-accent" />}
        <span className="min-w-0 flex-1 truncate text-[12px]">{item.file.name}</span>
        {item.status === "uploading" || item.status === "queued" ? (
          <Button variant="ghost" size="icon-xs" onClick={() => cancel(id)}><X /></Button>
        ) : item.status === "error" || item.status === "cancelled" ? (
          <>
            <Button variant="ghost" size="icon-xs" onClick={() => retry(id)}><RotateCcw /></Button>
            <Button variant="ghost" size="icon-xs" onClick={() => dismiss(id)}><X /></Button>
          </>
        ) : (
          <Button variant="ghost" size="icon-xs" onClick={() => dismiss(id)}><X /></Button>
        )}
      </div>
      {(item.status === "uploading" || processing || item.status === "queued") && <Progress className="mt-1.5" value={pct} />}
      <div className="mt-1 text-[11px] text-fg-subtle">
        {item.status === "queued" && "Waiting…"}
        {item.status === "uploading" && `Uploading ${formatBytes(item.sent)} of ${formatBytes(item.file.size)} · ${pct}%`}
        {processing && (job?.message || "Processing…")}
        {item.status === "duplicate" && "Already in this project — skipped"}
        {item.status === "error" && (item.error ?? "Upload failed")}
        {item.status === "cancelled" && "Cancelled"}
      </div>
    </div>
  );
}

function AssetGroup({ title, assets, projectId }: { title: string; assets: MediaAsset[]; projectId: string }) {
  if (assets.length === 0) return null;
  return (
    <div className="p-2">
      <div className="mb-1.5 px-1 text-[11px] uppercase tracking-wider text-fg-subtle">{title} · {assets.length}</div>
      <div className="grid grid-cols-2 gap-2">
        {assets.map((a) => (
          <AssetCard key={a.id} asset={a} projectId={projectId} />
        ))}
      </div>
    </div>
  );
}

function AssetCard({ asset, projectId }: { asset: MediaAsset; projectId: string }) {
  const { remove, update } = useAssetActions(projectId);
  const selected = useEditorStore((s) => s.selectedAssetId === asset.id);
  const setEditor = useEditorStore((s) => s.set);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(asset.filename);
  const ready = asset.status === "ready";
  const dur = asset.metadata?.duration;
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <div
          draggable={ready}
          onDragStart={(e) => {
            e.dataTransfer.setData("application/x-cutpilot-asset", asset.id);
            e.dataTransfer.effectAllowed = "copy";
          }}
          onClick={() => setEditor({ selectedAssetId: asset.id, previewSource: { kind: "asset", assetId: asset.id }, rightTab: "inspector" })}
          onDoubleClick={() => setEditor({ previewSource: { kind: "asset", assetId: asset.id } })}
          className={cn(
            "group cursor-pointer overflow-hidden rounded-md border bg-panel-2 transition-colors hover:border-border-strong",
            selected ? "border-accent" : "border-border",
          )}
        >
          <div className="relative aspect-video bg-black/40">
            {asset.thumbnail_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={asset.thumbnail_url} alt="" className="size-full object-cover" loading="lazy" />
            ) : (
              <div className="flex size-full items-center justify-center text-fg-subtle"><KindIcon asset={asset} /></div>
            )}
            {dur != null && asset.media_type !== "image" && <span className="absolute bottom-1 right-1 rounded-sm bg-black/70 px-1 text-mono text-[10px]">{formatDuration(dur)}</span>}
            {asset.status === "processing" || asset.status === "pending" ? (
              <span className="absolute left-1 top-1"><Badge variant="info"><Loader2 className="mr-1 size-2.5 animate-spin" />Processing</Badge></span>
            ) : asset.status === "failed" ? (
              <span className="absolute left-1 top-1"><Badge variant="danger">Failed</Badge></span>
            ) : asset.status === "duplicate" ? (
              <span className="absolute left-1 top-1"><Badge variant="warning">Duplicate</Badge></span>
            ) : null}
            {asset.role && <span className="absolute right-1 top-1"><Badge variant="secondary">{asset.role}</Badge></span>}
          </div>
          <div className="px-1.5 py-1">
            <div className="truncate text-[11.5px]" title={asset.filename}>{asset.filename}</div>
            <div className="truncate text-[10.5px] text-fg-subtle">
              {asset.metadata?.width ? `${asset.metadata.width}×${asset.metadata.height} · ` : ""}
              {asset.metadata?.fps ? `${asset.metadata.fps} fps · ` : ""}
              {formatBytes(asset.size_bytes)}
            </div>
          </div>
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onSelect={() => setEditor({ previewSource: { kind: "asset", assetId: asset.id } })}><Film /> Preview</ContextMenuItem>
        <ContextMenuItem onSelect={() => setRenaming(true)}><Pencil /> Rename</ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem onSelect={() => update.mutate({ id: asset.id, kind: "original" })}><Clapperboard /> Use as footage</ContextMenuItem>
        <ContextMenuItem onSelect={() => update.mutate({ id: asset.id, kind: asset.media_type === "image" ? "image" : "broll" })}><ImageIcon /> Use as B-roll</ContextMenuItem>
        {asset.media_type === "audio" && <ContextMenuItem onSelect={() => update.mutate({ id: asset.id, kind: "music" })}><Music /> Use as music</ContextMenuItem>}
        <ContextMenuItem onSelect={() => { const r = window.prompt("Camera / role label (e.g. cam_a)", asset.role ?? ""); if (r !== null) update.mutate({ id: asset.id, role: r }); }}>Set camera role…</ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem destructive onSelect={() => remove.mutate(asset.id, { onSuccess: () => toast.success("Asset deleted") })}><Trash2 /> Delete</ContextMenuItem>
      </ContextMenuContent>
      <Dialog open={renaming} onOpenChange={setRenaming}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>Rename asset</DialogTitle></DialogHeader>
          <form onSubmit={(e) => { e.preventDefault(); update.mutate({ id: asset.id, filename: name }, { onSuccess: () => setRenaming(false) }); }}>
            <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setRenaming(false)}>Cancel</Button>
              <Button type="submit" loading={update.isPending}>Save</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </ContextMenu>
  );
}

export function AssetTip({ label, children }: { label: string; children: React.ReactNode }) {
  return <Tip label={label}>{children}</Tip>;
}
