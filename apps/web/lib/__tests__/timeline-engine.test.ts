import { describe, expect, it } from "vitest";
import { addClipLocal, docDuration, makeClip, moveClipLocal, nextBoundary, playbackAt, presentSourceRanges, snapTo, sourceTimeToTimeline, trimClipLocal } from "@/lib/timeline-engine";
import type { TimelineDocument } from "@/lib/types";

function doc(): TimelineDocument {
  const v = makeClip({ id: "v1", kind: "video", asset_id: "a", timeline_start: 0, duration: 10, source_in: 5, source_out: 15 });
  const a = makeClip({ id: "a1", kind: "audio", asset_id: "a", timeline_start: 0, duration: 10, source_in: 5, source_out: 15, linked_clip_id: "v1" });
  v.linked_clip_id = "a1";
  const v2 = makeClip({ id: "v2", kind: "video", asset_id: "b", timeline_start: 10, duration: 5, source_in: 0, source_out: 5 });
  return {
    schema_version: 1, timeline_id: "t", name: "Main", markers: [], meta: {},
    settings: { width: 1920, height: 1080, fps: 30, aspect_ratio: "16:9", background: "#000", sample_rate: 48000, caption_style: {} as never, audio: {}, reframe: null },
    tracks: [
      { id: "V1", kind: "video", name: "V1", index: 0, muted: false, locked: false, hidden: false, clips: [v, v2] },
      { id: "V2", kind: "video", name: "V2", index: 1, muted: false, locked: false, hidden: false, clips: [] },
      { id: "A1", kind: "audio", name: "A1", index: 2, muted: false, locked: false, hidden: false, clips: [a] },
      { id: "C1", kind: "caption", name: "C", index: 3, muted: false, locked: false, hidden: false, clips: [makeClip({ id: "c1", kind: "caption", timeline_start: 2, duration: 2, text: "hi" })] },
    ],
  };
}

describe("timeline engine", () => {
  it("maps timeline time to source time and finds boundaries", () => {
    const d = doc();
    const p = playbackAt(d, 3);
    expect(p.video?.clip.id).toBe("v1");
    expect(p.video?.sourceTime).toBe(8);
    expect(p.captions.map((c) => c.id)).toEqual(["c1"]);
    expect(nextBoundary(d, 3)).toBe(4); // caption end
    expect(nextBoundary(d, 9.9)).toBe(10);
    expect(docDuration(d)).toBe(15);
    expect(playbackAt(d, 12).video?.clip.id).toBe("v2");
  });

  it("moves a clip together with its linked audio and resolves overlaps", () => {
    const moved = moveClipLocal(doc(), "v1", 2);
    const v1 = moved.tracks[0]!.clips.find((c) => c.id === "v1")!;
    const a1 = moved.tracks[2]!.clips.find((c) => c.id === "a1")!;
    expect(v1.timeline_start).toBe(2);
    expect(a1.timeline_start).toBe(2);
    const v2 = moved.tracks[0]!.clips.find((c) => c.id === "v2")!;
    expect(v2.timeline_start).toBe(12); // pushed right
  });

  it("trims edges while keeping source mapping and media bounds", () => {
    let d = trimClipLocal(doc(), "v1", "in", 2);
    let v1 = d.tracks[0]!.clips.find((c) => c.id === "v1")!;
    expect([v1.timeline_start, v1.duration, v1.source_in]).toEqual([2, 8, 7]);
    d = trimClipLocal(d, "v1", "out", 30, 20); // media is 20 s → max end = 2 + (20-7) = 15
    v1 = d.tracks[0]!.clips.find((c) => c.id === "v1")!;
    expect(v1.duration).toBe(13);
    expect(v1.source_out).toBe(20);
    d = trimClipLocal(d, "v1", "in", -5); // bounded by timeline 0 (source 7 - 2 s = 5)
    v1 = d.tracks[0]!.clips.find((c) => c.id === "v1")!;
    expect([v1.timeline_start, v1.source_in]).toEqual([0, 5]);
    d = trimClipLocal(d, "v1", "in", -5);
    v1 = d.tracks[0]!.clips.find((c) => c.id === "v1")!;
    expect(v1.source_in).toBe(5); // no further movement possible
  });

  it("adds clips and snaps", () => {
    const d = addClipLocal(doc(), "V2", makeClip({ kind: "broll", asset_id: "c", timeline_start: 4, duration: 3, source_out: 3 }));
    expect(d.tracks[1]!.clips).toHaveLength(1);
    expect(snapTo(9.8, [0, 10, 15], 0.5)).toBe(10);
    expect(snapTo(7, [0, 10, 15], 0.5)).toBe(7);
  });

  it("reports present source ranges for transcript styling", () => {
    const r = presentSourceRanges(doc(), "a");
    expect(r).toEqual([[5, 15], [5, 15]]);
    expect(sourceTimeToTimeline(doc(), "a", 7)).toBe(2);
    expect(sourceTimeToTimeline(doc(), "a", 20)).toBeNull();
  });
});
