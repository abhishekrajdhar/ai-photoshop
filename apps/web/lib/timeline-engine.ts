/**
 * Client-side timeline helpers. Mirrors the server engine's time model:
 *  - clips reference an asset by source range [source_in, source_out) at `speed`
 *  - timeline_start/duration place the clip on the sequence
 * Local edits (drag/trim) mutate a copy of the document which is then saved as a new version.
 */
import type { Clip, Marker, TimelineDocument, Track } from "@/lib/types";

export const EPS = 1e-4;

export function docDuration(doc: TimelineDocument): number {
  let end = 0;
  for (const t of doc.tracks) for (const c of t.clips) end = Math.max(end, c.timeline_start + c.duration);
  return end;
}

export function clipEnd(c: Clip): number {
  return c.timeline_start + c.duration;
}

export function timelineToSource(c: Clip, t: number): number {
  return c.source_in + (t - c.timeline_start) * c.speed;
}

export function sourceToTimeline(c: Clip, s: number): number {
  return c.timeline_start + (s - c.source_in) / c.speed;
}

export function clipAt(track: Track, t: number): Clip | undefined {
  return track.clips.find((c) => c.timeline_start <= t && t < clipEnd(c));
}

export function sortedClips(track: Track): Clip[] {
  return [...track.clips].sort((a, b) => a.timeline_start - b.timeline_start);
}

export function findClip(doc: TimelineDocument, clipId: string): { track: Track; clip: Clip } | undefined {
  for (const track of doc.tracks) {
    const clip = track.clips.find((c) => c.id === clipId);
    if (clip) return { track, clip };
  }
  return undefined;
}

export function tracksOfKind(doc: TimelineDocument, kind: Track["kind"]): Track[] {
  return doc.tracks.filter((t) => t.kind === kind).sort((a, b) => a.index - b.index);
}

/** What should be visible / audible at timeline time t. */
export interface Playback {
  video: { clip: Clip; sourceTime: number } | null; // top-most visible video-track clip
  base: { clip: Clip; sourceTime: number } | null; // primary track clip (for audio when linked)
  overlays: { clip: Clip; sourceTime: number }[]; // overlay-track clips (text/images)
  audio: { clip: Clip; sourceTime: number }[]; // independent audio clips (music etc.)
  captions: Clip[];
  zoom: { scale: number; x: number; y: number } | null;
}

export function playbackAt(doc: TimelineDocument, t: number): Playback {
  const videoTracks = tracksOfKind(doc, "video").filter((tr) => !tr.hidden);
  let video: Playback["video"] = null;
  let base: Playback["base"] = null;
  for (let i = videoTracks.length - 1; i >= 0; i--) {
    const c = clipAt(videoTracks[i]!, t);
    if (c && c.asset_id && !video) video = { clip: c, sourceTime: timelineToSource(c, t) };
  }
  const primary = videoTracks[0];
  if (primary) {
    const c = clipAt(primary, t);
    if (c) base = { clip: c, sourceTime: timelineToSource(c, t) };
  }
  const overlays: Playback["overlays"] = [];
  for (const tr of tracksOfKind(doc, "overlay")) {
    if (tr.hidden) continue;
    for (const c of tr.clips) if (c.timeline_start <= t && t < clipEnd(c)) overlays.push({ clip: c, sourceTime: timelineToSource(c, t) });
  }
  const audio: Playback["audio"] = [];
  for (const tr of tracksOfKind(doc, "audio")) {
    if (tr.muted) continue;
    for (const c of tr.clips) {
      if (c.muted || !c.asset_id) continue;
      if (c.timeline_start <= t && t < clipEnd(c)) audio.push({ clip: c, sourceTime: timelineToSource(c, t) });
    }
  }
  const captions: Clip[] = [];
  for (const tr of tracksOfKind(doc, "caption")) {
    if (tr.hidden) continue;
    for (const c of tr.clips) if (c.timeline_start <= t && t < clipEnd(c)) captions.push(c);
  }
  let zoom: Playback["zoom"] = null;
  const zc = video?.clip ?? base?.clip;
  if (zc) {
    for (const fx of zc.effects) {
      if (fx.type !== "zoom" || !fx.enabled) continue;
      const s = zc.timeline_start + (fx.start ?? 0);
      const d = fx.duration ?? zc.duration;
      if (t >= s && t < s + d) {
        const scale = Number(fx.params.scale ?? 1.12);
        const p = Math.min(1, (t - s) / Math.min(0.4, d)); // quick ease-in for the preview
        zoom = { scale: 1 + (scale - 1) * p, x: Number(fx.params.x ?? 0.5), y: Number(fx.params.y ?? 0.5) };
      }
    }
  }
  return { video, base, overlays, audio, captions, zoom };
}

/** Next timeline time (> t) where the playback composition changes — used to schedule source switches. */
export function nextBoundary(doc: TimelineDocument, t: number): number | null {
  let best: number | null = null;
  for (const tr of doc.tracks) {
    for (const c of tr.clips) {
      for (const b of [c.timeline_start, clipEnd(c)]) {
        if (b > t + EPS && (best === null || b < best)) best = b;
      }
    }
  }
  return best;
}

export function snapPoints(doc: TimelineDocument, exclude: Set<string> = new Set()): number[] {
  const pts = new Set<number>([0]);
  for (const tr of doc.tracks) for (const c of tr.clips) if (!exclude.has(c.id)) { pts.add(c.timeline_start); pts.add(clipEnd(c)); }
  for (const m of doc.markers) pts.add(m.time);
  return [...pts].sort((a, b) => a - b);
}

export function snapTo(value: number, points: number[], tolerance: number): number {
  let best = value;
  let bestDist = tolerance;
  for (const p of points) {
    const d = Math.abs(p - value);
    if (d < bestDist) { best = p; bestDist = d; }
  }
  return best;
}

/* ── local (optimistic) document edits ───────────────────────────────────── */

export function cloneDoc(doc: TimelineDocument): TimelineDocument {
  return JSON.parse(JSON.stringify(doc)) as TimelineDocument;
}

/** Move a clip (and its linked clip) to a new start; pushes overlapping clips on the target track right. */
export function moveClipLocal(doc: TimelineDocument, clipId: string, newStart: number, targetTrackId?: string): TimelineDocument {
  const next = cloneDoc(doc);
  const found = findClip(next, clipId);
  if (!found) return doc;
  const { track, clip } = found;
  const delta = Math.max(0, newStart) - clip.timeline_start;
  const target = targetTrackId ? next.tracks.find((t) => t.id === targetTrackId) : undefined;
  if (target && target.id !== track.id) {
    if (target.kind !== track.kind) return doc;
    track.clips = track.clips.filter((c) => c.id !== clip.id);
    target.clips.push(clip);
  }
  clip.timeline_start = round(clip.timeline_start + delta);
  resolveOverlaps(target ?? track, clip);
  if (clip.linked_clip_id) {
    const linked = findClip(next, clip.linked_clip_id);
    if (linked && linkedAligned(doc, clipId, linked.clip.id)) {
      linked.clip.timeline_start = round(Math.max(0, linked.clip.timeline_start + delta));
      resolveOverlaps(linked.track, linked.clip);
    }
  }
  return next;
}

function resolveOverlaps(track: Track, moved: Clip): void {
  for (const other of sortedClips(track)) {
    if (other.id === moved.id) continue;
    const overlap = other.timeline_start < clipEnd(moved) && clipEnd(other) > moved.timeline_start;
    if (overlap) other.timeline_start = round(clipEnd(moved));
  }
}

/** Trim a clip edge. `side` in: new start (keeps end); out: new end (keeps start). Bounded by source media. */
export function trimClipLocal(doc: TimelineDocument, clipId: string, side: "in" | "out", value: number, mediaDuration?: number): TimelineDocument {
  const next = cloneDoc(doc);
  const found = findClip(next, clipId);
  if (!found) return doc;
  const { clip } = found;
  const apply = (c: Clip) => {
    const hasSource = !!c.asset_id && (c.kind === "video" || c.kind === "audio" || c.kind === "broll" || c.kind === "music") && !c.loop;
    if (side === "in") {
      const minStart = hasSource ? c.timeline_start - c.source_in / c.speed : 0;
      const v = Math.min(Math.max(value, Math.max(0, minStart)), clipEnd(c) - 0.05);
      const delta = v - c.timeline_start;
      if (hasSource) c.source_in = round(c.source_in + delta * c.speed);
      c.timeline_start = round(v);
      c.duration = round(c.duration - delta);
    } else {
      const maxEnd = hasSource && mediaDuration != null ? c.timeline_start + (mediaDuration - c.source_in) / c.speed : Infinity;
      const v = Math.max(Math.min(value, maxEnd), c.timeline_start + 0.05);
      c.duration = round(v - c.timeline_start);
      if (hasSource) c.source_out = round(c.source_in + c.duration * c.speed);
      else c.source_out = round(c.duration);
    }
  };
  apply(clip);
  if (clip.linked_clip_id) {
    const linked = findClip(next, clip.linked_clip_id);
    // Only follow the link when the partner is actually aligned with this clip (defensive against stale links).
    if (linked && linkedAligned(doc, clipId, linked.clip.id)) apply(linked.clip);
  }
  return next;
}

function linkedAligned(doc: TimelineDocument, aId: string, bId: string): boolean {
  const a = findClip(doc, aId)?.clip;
  const b = findClip(doc, bId)?.clip;
  if (!a || !b) return false;
  return Math.abs(a.timeline_start - b.timeline_start) < 0.02 && Math.abs(a.duration - b.duration) < 0.02;
}

export function addClipLocal(doc: TimelineDocument, trackId: string, clip: Clip): TimelineDocument {
  const next = cloneDoc(doc);
  const track = next.tracks.find((t) => t.id === trackId);
  if (!track) return doc;
  track.clips.push(clip);
  resolveOverlaps(track, clip);
  return next;
}

export function updateClipLocal(doc: TimelineDocument, clipId: string, patch: Partial<Clip>): TimelineDocument {
  const next = cloneDoc(doc);
  const found = findClip(next, clipId);
  if (!found) return doc;
  Object.assign(found.clip, patch);
  return next;
}

export function updateTrackLocal(doc: TimelineDocument, trackId: string, patch: Partial<Track>): TimelineDocument {
  const next = cloneDoc(doc);
  const track = next.tracks.find((t) => t.id === trackId);
  if (!track) return doc;
  Object.assign(track, patch);
  return next;
}

export function addMarkerLocal(doc: TimelineDocument, marker: Marker): TimelineDocument {
  const next = cloneDoc(doc);
  next.markers.push(marker);
  return next;
}

export function removeMarkerLocal(doc: TimelineDocument, markerId: string): TimelineDocument {
  const next = cloneDoc(doc);
  next.markers = next.markers.filter((m) => m.id !== markerId);
  return next;
}

export function newId(prefix: string): string {
  return `${prefix}_${Math.random().toString(16).slice(2, 14)}`;
}

export function makeClip(partial: Partial<Clip> & Pick<Clip, "kind">): Clip {
  return {
    id: newId("clip"),
    name: "",
    asset_id: null,
    timeline_start: 0,
    duration: 0,
    source_in: 0,
    source_out: 0,
    speed: 1,
    gain_db: 0,
    muted: false,
    text: null,
    words: null,
    style: {},
    position: null,
    effects: [],
    transition_in: { type: "cut", duration: 0 },
    transition_out: { type: "cut", duration: 0 },
    linked_clip_id: null,
    loop: false,
    fade_in: 0,
    fade_out: 0,
    ducking: false,
    meta: {},
    ...partial,
  };
}

/** Source ranges of an asset that are currently present on video/audio tracks (for transcript "removed" styling). */
export function presentSourceRanges(doc: TimelineDocument, assetId: string): [number, number][] {
  const ranges: [number, number][] = [];
  for (const tr of doc.tracks) {
    if (tr.kind !== "video" && tr.kind !== "audio") continue;
    for (const c of tr.clips) if (c.asset_id === assetId) ranges.push([c.source_in, c.source_out]);
  }
  return ranges.sort((a, b) => a[0] - b[0]);
}

export function isSourceTimePresent(ranges: [number, number][], s: number): boolean {
  for (const [a, b] of ranges) if (s >= a - EPS && s < b + EPS) return true;
  return false;
}

/** Map a source time of an asset to the timeline (first clip containing it). */
export function sourceTimeToTimeline(doc: TimelineDocument, assetId: string, s: number): number | null {
  for (const tr of tracksOfKind(doc, "video").concat(tracksOfKind(doc, "audio"))) {
    for (const c of tr.clips) {
      if (c.asset_id === assetId && s >= c.source_in - EPS && s < c.source_out + EPS) return sourceToTimeline(c, s);
    }
  }
  return null;
}

export function round(v: number): number {
  return Math.round(v * 1e6) / 1e6;
}
