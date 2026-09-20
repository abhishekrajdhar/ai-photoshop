"use client";
import { useCallback, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import { useAssets } from "@/lib/assets";
import { timelineKey, useTimeline, useTimelineMutations } from "@/lib/timeline";
import { addClipLocal, addMarkerLocal, clipEnd, findClip, makeClip, moveClipLocal, newId, removeMarkerLocal, tracksOfKind, trimClipLocal, updateClipLocal, updateTrackLocal } from "@/lib/timeline-engine";
import type { Clip, EditOperation, MediaAsset, TimelineDocument, TimelineState, Track } from "@/lib/types";
import { useEditorStore } from "@/stores/editor";

/** Every timeline edit goes through here → new server-side version (undo/redo are version pointers). */
export function useTimelineActions(projectId: string) {
  const timelineId = useEditorStore((s) => s.timelineId);
  const { data: state } = useTimeline(projectId, timelineId);
  const { data: assets } = useAssets(projectId);
  const mutations = useTimelineMutations(projectId, timelineId);
  const qc = useQueryClient();
  const doc = state?.document;

  const onError = useCallback((e: unknown) => toast.error(e instanceof ApiError ? e.message : "Edit failed"), []);

  const applyOps = useCallback(
    (operations: EditOperation[], label: string) => {
      if (!operations.length) return;
      return mutations.applyOps.mutateAsync({ operations: operations.map((o) => ({ source: "user", ...o })), label, source: "user" }).catch(onError);
    },
    [mutations.applyOps, onError],
  );

  const saveDoc = useCallback(
    (document: TimelineDocument, label: string) => {
      // Optimistic: show the new document immediately, server assigns the version.
      const key = timelineKey(projectId, timelineId);
      const prev = qc.getQueryData<TimelineState>(key);
      if (prev) qc.setQueryData(key, { ...prev, document });
      return mutations.save.mutateAsync({ document, label }).catch((e) => {
        if (prev) qc.setQueryData(key, prev);
        onError(e);
      });
    },
    [mutations.save, onError, projectId, qc, timelineId],
  );

  const assetById = useMemo(() => new Map((assets ?? []).map((a) => [a.id, a])), [assets]);

  const split = useCallback(
    (at: number, clipIds?: string[]) => {
      if (!doc) return;
      const targets = clipIds?.length ? clipIds : undefined;
      const ops: EditOperation[] = targets
        ? targets.map((id) => ({ type: "split", source_clip_id: id, time_ref: "timeline", timestamp: at }))
        : [{ type: "split", time_ref: "timeline", timestamp: at }];
      // Only split if something is under the playhead
      const anything = doc.tracks.some((t) => t.clips.some((c) => (!targets || targets.includes(c.id)) && c.timeline_start < at && at < clipEnd(c)));
      if (!anything) return;
      return applyOps(ops, "Split");
    },
    [applyOps, doc],
  );

  const deleteClips = useCallback(
    (clipIds: string[], ripple: boolean) => {
      if (!clipIds.length) return;
      const ops: EditOperation[] = clipIds.map((id) => ({ type: "delete_clip", source_clip_id: id, params: { ripple, ripple_all: ripple } }));
      useEditorStore.getState().selectClip(null);
      return applyOps(ops, ripple ? "Ripple delete" : "Delete clip");
    },
    [applyOps],
  );

  const removeRange = useCallback(
    (start: number, end: number, label = "Remove range") => applyOps([{ type: "remove_segment", time_ref: "timeline", start, end }], label),
    [applyOps],
  );

  const removeSourceRanges = useCallback(
    (assetId: string, segments: { start: number; end: number }[], label: string) =>
      applyOps([{ type: "remove_segment", asset_id: assetId, time_ref: "source", segments, start: segments[0]?.start ?? 0, end: segments[segments.length - 1]?.end ?? 0, reason: label }], label),
    [applyOps],
  );

  const moveClip = useCallback((clipId: string, newStart: number, targetTrackId?: string) => doc && saveDoc(moveClipLocal(doc, clipId, newStart, targetTrackId), "Move clip"), [doc, saveDoc]);

  const trimClip = useCallback(
    (clipId: string, side: "in" | "out", value: number) => {
      if (!doc) return;
      const found = findClip(doc, clipId);
      const media = found?.clip.asset_id ? assetById.get(found.clip.asset_id)?.metadata?.duration ?? undefined : undefined;
      return saveDoc(trimClipLocal(doc, clipId, side, value, media), "Trim clip");
    },
    [assetById, doc, saveDoc],
  );

  const addAssetClip = useCallback(
    (asset: MediaAsset, at: number, trackId?: string) => {
      if (!doc || asset.status !== "ready") return;
      const duration = asset.metadata?.duration ?? (asset.media_type === "image" ? 5 : 0);
      if (duration <= 0) return;
      let next = doc;
      const videoTracks = tracksOfKind(doc, "video");
      const audioTracks = tracksOfKind(doc, "audio");
      const hasVideo = asset.media_type === "video" || asset.media_type === "image";
      const hasAudio = asset.media_type === "audio" || (asset.media_type === "video" && !!asset.metadata?.audio_codec);
      const targetTrack = trackId ? doc.tracks.find((t) => t.id === trackId) : undefined;
      const videoTrack = targetTrack?.kind === "video" ? targetTrack : videoTracks[0];
      const audioTrack = targetTrack?.kind === "audio" ? targetTrack : audioTracks[Math.min(videoTracks.indexOf(videoTrack!), audioTracks.length - 1)] ?? audioTracks[0];
      const base = { asset_id: asset.id, name: asset.filename, timeline_start: Math.max(0, at), duration, source_in: 0, source_out: duration };
      let videoClip: Clip | null = null;
      if (hasVideo && videoTrack) {
        videoClip = makeClip({ ...base, kind: asset.kind === "broll" ? "broll" : asset.media_type === "image" ? "image" : "video", muted: asset.kind === "broll" });
        next = addClipLocal(next, videoTrack.id, videoClip);
      }
      if (hasAudio && audioTrack && !(asset.kind === "broll")) {
        const audioClip = makeClip({ ...base, kind: asset.kind === "music" ? "music" : "audio", linked_clip_id: videoClip?.id ?? null, loop: false, gain_db: asset.kind === "music" ? -18 : 0, ducking: asset.kind === "music", fade_in: asset.kind === "music" ? 1 : 0, fade_out: asset.kind === "music" ? 2 : 0 });
        if (videoClip) {
          const found = findClip(next, videoClip.id);
          if (found) found.clip.linked_clip_id = audioClip.id;
        }
        next = addClipLocal(next, audioTrack.id, audioClip);
      }
      return saveDoc(next, `Add ${asset.filename}`);
    },
    [doc, saveDoc],
  );

  const updateClip = useCallback((clipId: string, patch: Partial<Clip>, label = "Edit clip") => doc && saveDoc(updateClipLocal(doc, clipId, patch), label), [doc, saveDoc]);
  const updateTrack = useCallback((trackId: string, patch: Partial<Track>) => doc && saveDoc(updateTrackLocal(doc, trackId, patch), "Track settings"), [doc, saveDoc]);
  const addMarker = useCallback((time: number, label = "") => doc && saveDoc(addMarkerLocal(doc, { id: newId("mk"), time, label, color: "#7C3AED", kind: "marker", meta: {} }), "Add marker"), [doc, saveDoc]);
  const removeMarker = useCallback((id: string) => doc && saveDoc(removeMarkerLocal(doc, id), "Remove marker"), [doc, saveDoc]);
  const undo = useCallback(() => mutations.undo.mutateAsync().catch(onError), [mutations.undo, onError]);
  const redo = useCallback(() => mutations.redo.mutateAsync().catch(onError), [mutations.redo, onError]);
  const restore = useCallback((versionId: string) => mutations.restore.mutateAsync(versionId).catch(onError), [mutations.restore, onError]);

  return { state, doc, assets, assetById, applyOps, saveDoc, split, deleteClips, removeRange, removeSourceRanges, moveClip, trimClip, addAssetClip, updateClip, updateTrack, addMarker, removeMarker, undo, redo, restore, busy: mutations.applyOps.isPending || mutations.save.isPending };
}

export type TimelineActions = ReturnType<typeof useTimelineActions>;
