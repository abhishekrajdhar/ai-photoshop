"""Interchange exports: OpenTimelineIO JSON, CMX3600 EDL, and FCPXML (basic)."""

from __future__ import annotations

from xml.sax.saxutils import escape

import opentimelineio as otio

from cutpilot.timeline.model import TimelineDocument


def _rt(seconds: float, fps: float) -> otio.opentime.RationalTime:
    return otio.opentime.RationalTime(round(seconds * fps), fps)


def to_otio(
    doc: TimelineDocument, asset_names: dict[str, str], asset_paths: dict[str, str] | None = None
) -> str:
    fps = float(doc.settings.fps or 30)
    timeline = otio.schema.Timeline(name=doc.name)
    timeline.metadata["cutpilot"] = {
        "timeline_id": doc.timeline_id,
        "settings": doc.settings.model_dump(mode="json"),
    }
    for track in doc.tracks:
        if track.kind not in ("video", "audio", "overlay", "caption"):
            continue
        kind = otio.schema.TrackKind.Audio if track.kind == "audio" else otio.schema.TrackKind.Video
        ot = otio.schema.Track(name=track.name, kind=kind)
        ot.metadata["cutpilot"] = {
            "id": track.id,
            "kind": track.kind,
            "muted": track.muted,
            "locked": track.locked,
            "hidden": track.hidden,
        }
        t = 0.0
        for clip in track.sorted_clips():
            if clip.timeline_start > t + 1e-6:
                ot.append(
                    otio.schema.Gap(
                        source_range=otio.opentime.TimeRange(
                            _rt(0, fps), _rt(clip.timeline_start - t, fps)
                        )
                    )
                )
            if clip.asset_id:
                ref = otio.schema.ExternalReference(
                    target_url=(asset_paths or {}).get(
                        clip.asset_id, asset_names.get(clip.asset_id, clip.asset_id)
                    )
                )
                oc = otio.schema.Clip(
                    name=clip.name or asset_names.get(clip.asset_id, clip.kind),
                    media_reference=ref,
                    source_range=otio.opentime.TimeRange(
                        _rt(clip.source_in, fps), _rt(clip.duration * clip.speed, fps)
                    ),
                )
            else:
                oc = otio.schema.Clip(
                    name=clip.text or clip.name or clip.kind,
                    media_reference=otio.schema.MissingReference(),
                    source_range=otio.opentime.TimeRange(_rt(0, fps), _rt(clip.duration, fps)),
                )
            oc.metadata["cutpilot"] = clip.model_dump(mode="json")
            if clip.speed != 1.0:
                oc.effects.append(otio.schema.LinearTimeWarp(time_scalar=clip.speed))
            ot.append(oc)
            t = clip.timeline_end
        timeline.tracks.append(ot)
    for m in doc.markers:
        timeline.tracks.markers.append(
            otio.schema.Marker(
                name=m.label or m.kind,
                marked_range=otio.opentime.TimeRange(_rt(m.time, fps), _rt(0, fps)),
                color=otio.schema.MarkerColor.PURPLE,
            )
        )
    return otio.adapters.write_to_string(timeline, "otio_json")


def _tc(seconds: float, fps: float) -> str:
    frames = round(seconds * fps)
    f = round(fps)
    h, rem = divmod(frames, 3600 * f)
    m, rem = divmod(rem, 60 * f)
    s, fr = divmod(rem, f)
    return f"{h:02d}:{m:02d}:{s:02d}:{fr:02d}"


def to_edl(doc: TimelineDocument, asset_names: dict[str, str]) -> str:
    """CMX3600 EDL of the primary video track (with matching audio when linked)."""
    fps = float(doc.settings.fps or 30)
    lines = [f"TITLE: {doc.name}", "FCM: NON-DROP FRAME", ""]
    n = 1
    for clip in doc.primary_video_track().sorted_clips():
        name = asset_names.get(clip.asset_id or "", clip.name or "CLIP")
        reel = "".join(ch for ch in name.upper() if ch.isalnum())[:8] or "AX"
        src_in, src_out = clip.source_in, clip.source_in + clip.duration * clip.speed
        rec_in, rec_out = clip.timeline_start, clip.timeline_end
        channel = "V" if not clip.linked_clip_id else "B"
        lines.append(
            f"{n:03d}  {reel:<8} {channel:<5} C        {_tc(src_in, fps)} {_tc(src_out, fps)} {_tc(rec_in, fps)} {_tc(rec_out, fps)}"
        )
        lines.append(f"* FROM CLIP NAME: {name}")
        if clip.speed != 1.0:
            lines.append(
                f"M2   {reel:<8}       {clip.speed * fps:06.1f}                {_tc(src_in, fps)}"
            )
        n += 1
    return "\n".join(lines) + "\n"


def to_fcpxml(
    doc: TimelineDocument, asset_names: dict[str, str], asset_paths: dict[str, str] | None = None
) -> str:
    """Minimal FCPXML 1.9: one sequence, primary video (with audio) on the spine, other tracks as connected clips."""
    fps = float(doc.settings.fps or 30)
    fd = f"{100}/{round(fps * 100)}s" if not float(fps).is_integer() else f"1/{int(fps)}s"

    def t(seconds: float) -> str:
        return (
            f"{round(seconds * fps)}/{int(fps)}s"
            if float(fps).is_integer()
            else f"{round(seconds * 6000)}/6000s"
        )

    assets = {}
    for _, clip in doc.all_clips():
        if clip.asset_id and clip.asset_id not in assets:
            assets[clip.asset_id] = f"r{len(assets) + 2}"
    fmt = f'<format id="r1" name="FFVideoFormat{doc.settings.height}p{round(fps)}" frameDuration="{fd}" width="{doc.settings.width}" height="{doc.settings.height}"/>'
    res = [fmt]
    for aid, rid in assets.items():
        src = (asset_paths or {}).get(aid, asset_names.get(aid, aid))
        res.append(
            f'<asset id="{rid}" name="{escape(asset_names.get(aid, aid))}" src="file://{escape(src)}" start="0s" hasVideo="1" hasAudio="1" format="r1"/>'
        )
    spine: list[str] = []
    primary = doc.primary_video_track()
    t_cursor = 0.0
    for clip in primary.sorted_clips():
        if clip.timeline_start > t_cursor + 1e-6:
            spine.append(
                f'<gap name="Gap" offset="{t(t_cursor)}" duration="{t(clip.timeline_start - t_cursor)}"/>'
            )
        rid = assets.get(clip.asset_id or "", "r2")
        spine.append(
            f'<asset-clip ref="{rid}" name="{escape(clip.name or "clip")}" offset="{t(clip.timeline_start)}" start="{t(clip.source_in)}" duration="{t(clip.duration)}" format="r1"/>'
        )
        t_cursor = clip.timeline_end
    connected: list[str] = []
    for track in doc.tracks:
        if track is primary:
            continue
        for lane_i, clip in enumerate(track.sorted_clips(), start=1):
            lane = (doc.tracks.index(track) + 1) * (1 if track.kind != "audio" else -1)
            if (
                clip.asset_id
                and clip.asset_id in assets
                and not (track.kind == "audio" and clip.linked_clip_id)
            ):
                connected.append(
                    f'<asset-clip ref="{assets[clip.asset_id]}" lane="{lane}" name="{escape(clip.name or clip.kind)}" offset="{t(clip.timeline_start)}" start="{t(clip.source_in)}" duration="{t(clip.duration)}" format="r1"/>'
                )
            elif clip.text:
                connected.append(
                    f'<title lane="{lane}" name="{escape(clip.text[:40])}" offset="{t(clip.timeline_start)}" duration="{t(clip.duration)}"><text><text-style ref="ts1">{escape(clip.text)}</text-style></text></title>'
                )
            _ = lane_i
    body = "\n".join(spine) + ("\n" + "\n".join(connected) if connected else "")
    total = doc.duration()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.9">
  <resources>
    {chr(10).join(res)}
    <effect id="ts1" name="Basic Title" uid=".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti"/>
  </resources>
  <library>
    <event name="{escape(doc.name)}">
      <project name="{escape(doc.name)}">
        <sequence format="r1" duration="{t(total)}" tcStart="0s" tcFormat="NDF">
          <spine>
{body}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""


def caption_filename(base: str, fmt: str) -> str:
    stem = base.rsplit(".", 1)[0] if "." in base else base
    return f"{stem}.{fmt}"
