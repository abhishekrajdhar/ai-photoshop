"""Unit tests for the deterministic timeline engine (no media, no LLM)."""

import pytest

from cutpilot.timeline.engine import (
    add_source_clip,
    apply_operations,
    remove_timeline_range,
    split_clip,
)
from cutpilot.timeline.model import TimelineDocument, merge_ranges
from cutpilot.timeline.operations import EditDecisionList, EditOperation


def make_doc(duration: float = 60.0) -> TimelineDocument:
    doc = TimelineDocument.empty(timeline_id="tl")
    add_source_clip(
        doc,
        asset_id="asset",
        name="talk",
        duration=duration,
        has_video=True,
        has_audio=True,
        fps=30,
        width=1920,
        height=1080,
    )
    return doc


def test_merge_ranges() -> None:
    assert merge_ranges([(5, 8), (7, 9), (12, 13), (13, 14)]) == [(5.0, 9.0), (12.0, 14.0)]
    assert merge_ranges([]) == []


def test_split_clip_preserves_source_mapping() -> None:
    doc = make_doc()
    clip = doc.primary_video_track().clips[0]
    left, right = split_clip(clip, 10.0)  # type: ignore[misc]
    assert (left.timeline_start, left.duration, left.source_out) == (0.0, 10.0, 10.0)
    assert (right.timeline_start, right.duration, right.source_in) == (10.0, 50.0, 10.0)


def test_remove_range_ripples_all_tracks() -> None:
    doc = make_doc()
    removed = remove_timeline_range(doc, 5.0, 8.0)
    assert removed == 3.0
    assert doc.duration() == 57.0
    for track_id in ("V1", "A1"):
        clips = doc.track(track_id).sorted_clips()
        assert [(c.timeline_start, c.duration) for c in clips] == [(0.0, 5.0), (5.0, 52.0)]
        assert clips[1].source_in == 8.0


def test_remove_segments_in_source_time_and_cut_merging() -> None:
    doc = make_doc()
    ops = [
        EditOperation(
            type="remove_segment",
            asset_id="asset",
            start=5,
            end=8,
            reason="silence",
            source="ai",
            confidence=0.9,
        ),
        EditOperation(
            type="remove_segment", asset_id="asset", start=7, end=10
        ),  # overlaps → merged
        EditOperation(type="remove_segment", asset_id="asset", start=17, end=20),
    ]
    result = apply_operations(doc, ops)
    assert not result.rejected
    assert result.document.duration() == pytest.approx(52.0)
    clips = result.document.primary_video_track().sorted_clips()
    assert [(c.source_in, c.source_out) for c in clips] == [(0.0, 5.0), (10.0, 17.0), (20.0, 60.0)]
    # Original document is untouched (non-destructive)
    assert doc.duration() == 60.0


def test_silence_removal_batch_after_prior_cut_maps_source_time_correctly() -> None:
    doc = make_doc()
    first = apply_operations(
        doc, [EditOperation(type="remove_segment", asset_id="asset", start=0, end=10)]
    ).document
    ops = [
        EditOperation(
            type="silence_removal",
            asset_id="asset",
            segments=[{"start": 30, "end": 31}, {"start": 50, "end": 52}],
        )
    ]
    result = apply_operations(first, ops)
    assert result.document.duration() == pytest.approx(47.0)
    clips = result.document.primary_video_track().sorted_clips()
    assert [(c.source_in, c.source_out) for c in clips] == [
        (10.0, 30.0),
        (31.0, 50.0),
        (52.0, 60.0),
    ]


def test_caption_and_zoom_are_placed_in_timeline_time() -> None:
    doc = make_doc()
    ops = [
        EditOperation(type="remove_segment", asset_id="asset", start=5, end=8),
        EditOperation(type="caption", asset_id="asset", start=21, end=25, text="Hello world"),
        EditOperation(type="zoom", asset_id="asset", timestamp=30, duration=3, scale=1.1),
    ]
    result = apply_operations(doc, ops)
    caption = result.document.caption_track().clips[0]
    assert (caption.timeline_start, caption.duration) == (18.0, 4.0)
    video = result.document.primary_video_track().sorted_clips()[-1]
    zoom = video.effects[0]
    assert zoom.type == "zoom" and zoom.params["scale"] == 1.1
    assert video.timeline_start + (zoom.start or 0) == pytest.approx(27.0)


def test_split_trim_delete_merge_roundtrip() -> None:
    doc = make_doc()
    doc = apply_operations(
        doc, [EditOperation(type="split", time_ref="timeline", timestamp=20.0)]
    ).document
    v = doc.primary_video_track().sorted_clips()
    assert len(v) == 2 and v[1].source_in == 20.0
    # Merge back
    doc = apply_operations(
        doc, [EditOperation(type="merge", params={"clip_ids": [v[0].id, v[1].id]})]
    ).document
    v = doc.primary_video_track().sorted_clips()
    assert len(v) == 1 and v[0].duration == 60.0
    # Trim out point with ripple
    doc = apply_operations(
        doc,
        [
            EditOperation(
                type="trim",
                source_clip_id=v[0].id,
                time_ref="timeline",
                params={"side": "out", "timeline_end": 40.0},
            )
        ],
    ).document
    assert doc.duration() == 40.0
    # Delete
    doc = apply_operations(
        doc,
        [EditOperation(type="delete_clip", source_clip_id=doc.primary_video_track().clips[0].id)],
    ).document
    assert doc.primary_video_track().clips == []
    assert doc.primary_audio_track().clips == []  # linked audio removed


def test_speed_change_reflows_following_clips() -> None:
    doc = make_doc()
    result = apply_operations(
        doc,
        [
            EditOperation(
                type="speed_change", asset_id="asset", start=10, end=20, params={"speed": 2.0}
            )
        ],
    )
    assert not result.rejected
    assert result.document.duration() == pytest.approx(55.0)


def test_invalid_operation_is_rejected_not_fatal() -> None:
    doc = make_doc()
    ops = [
        EditOperation(type="delete_clip", source_clip_id="missing"),
        EditOperation(type="remove_segment", asset_id="asset", start=1, end=2),
    ]
    result = apply_operations(doc, ops)
    assert len(result.rejected) == 1 and len(result.applied) == 1
    assert result.document.duration() == 59.0


def test_operation_schema_validation() -> None:
    with pytest.raises(ValueError):
        EditOperation(type="caption", start=1, end=2)  # missing text
    with pytest.raises(ValueError):
        EditOperation(type="remove_segment", start=5, end=2)
    with pytest.raises(ValueError):
        EditOperation(type="zoom", scale=9.0, timestamp=1)
    edl = EditDecisionList.model_validate(
        {
            "summary": "x",
            "operations": [{"type": "remove_segment", "start": 1, "end": 2, "asset_id": "a"}],
        }
    )
    assert edl.operations[0].id.startswith("op_")
    with pytest.raises(ValueError):
        EditDecisionList.model_validate({"operations": [{"type": "explode", "start": 1}]})


def test_reframe_updates_sequence_format() -> None:
    doc = make_doc()
    result = apply_operations(doc, [EditOperation(type="reframe", params={"aspect_ratio": "9:16"})])
    assert (result.document.settings.width, result.document.settings.height) == (1080, 1920)
    assert result.document.settings.reframe["mode"] == "track"
