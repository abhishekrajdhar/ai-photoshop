"""Upload validation, ffprobe metadata, and the end-to-end upload pipeline (Celery eager mode)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from httpx import AsyncClient

from cutpilot.core.errors import ValidationFailed
from cutpilot.media.ffmpeg import ffprobe
from cutpilot.media.validation import sniff_media_family, validate_upload_request
from tests.media_fixtures import make_test_audio, make_test_image, make_test_video


def test_validate_upload_request_rules() -> None:
    assert validate_upload_request("clip.MP4", "video/mp4", 100) == (".mp4", "video")
    assert validate_upload_request("song.m4a", "application/octet-stream", 100) == (".m4a", "audio")
    with pytest.raises(ValidationFailed):
        validate_upload_request("script.exe", "application/octet-stream", 100)
    with pytest.raises(ValidationFailed):
        validate_upload_request("clip.mp4", "text/html", 100)
    with pytest.raises(ValidationFailed):
        validate_upload_request("clip.mp4", "video/mp4", 0)
    with pytest.raises(ValidationFailed):
        validate_upload_request("clip.mp4", "video/mp4", 10**13)


def test_sniff_media_family(tmp_path: Path) -> None:
    video = make_test_video(tmp_path / "v.mp4", duration=1)
    assert sniff_media_family(video.read_bytes()[:64]) == "video"
    audio = make_test_audio(tmp_path / "a.wav", duration=1)
    assert sniff_media_family(audio.read_bytes()[:64]) == "audio"
    image = make_test_image(tmp_path / "i.png")
    assert sniff_media_family(image.read_bytes()[:64]) == "image"
    assert sniff_media_family(b"<html>") is None


def test_ffprobe_metadata(tmp_path: Path) -> None:
    video = make_test_video(tmp_path / "v.mp4", duration=2, width=320, height=180, fps=25)
    info = ffprobe(video)
    assert info.has_video and info.has_audio
    assert (info.width, info.height) == (320, 180)
    assert info.fps == 25.0
    assert 1.9 <= info.duration <= 2.2
    assert info.video_codec == "h264" and info.audio_codec == "aac"
    assert info.sample_rate == 44100


async def _upload(
    client: AsyncClient, pid: str, path: Path, *, mime: str = "video/mp4", chunk: int | None = None
) -> dict:
    data = path.read_bytes()
    init = await client.post(
        f"/api/projects/{pid}/uploads",
        json={"filename": path.name, "mime_type": mime, "size_bytes": len(data)},
    )
    assert init.status_code == 201, init.text
    body = init.json()
    if body["duplicate_of"]:
        return body
    uid, size = body["upload_id"], body["chunk_size"]
    for i in range(body["total_chunks"]):
        res = await client.put(
            f"/api/projects/{pid}/uploads/{uid}/chunks/{i}",
            content=data[i * size : (i + 1) * size],
            headers={"content-type": "application/octet-stream"},
        )
        assert res.status_code == 200, res.text
    done = await client.post(f"/api/projects/{pid}/uploads/{uid}/complete")
    assert done.status_code == 200, done.text
    return done.json()


async def test_upload_pipeline_generates_derivatives_and_timeline(
    auth_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cutpilot.core import config

    # Small chunk size to exercise multi-chunk assembly.
    monkeypatch.setattr(config.get_settings(), "upload_chunk_size", 64 * 1024)
    pid = (await auth_client.post("/api/projects", json={"name": "media"})).json()["id"]
    video = make_test_video(tmp_path / "talk.mp4", duration=3)
    result = await _upload(auth_client, pid, video)
    asset = result["asset"]
    assert asset["status"] == "ready", asset
    assert asset["metadata"]["duration"] >= 2.9
    assert (
        asset["proxy_asset_id"]
        and asset["audio_asset_id"]
        and asset["thumbnail_url"]
        and asset["waveform_url"]
    )

    job = (await auth_client.get(f"/api/jobs/{result['job_id']}")).json()
    assert job["status"] == "COMPLETED" and job["progress"] == 1.0

    # Streams
    res = await auth_client.get(
        f"/api/assets/{asset['id']}/stream", headers={"range": "bytes=0-99"}
    )
    assert res.status_code == 206 and len(res.content) == 100
    assert (await auth_client.get(f"/api/assets/{asset['id']}/thumbnail")).headers[
        "content-type"
    ] == "image/jpeg"
    wf = (await auth_client.get(f"/api/assets/{asset['id']}/waveform")).json()
    assert wf["sample_rate"] == 20 and len(wf["peaks"]) >= 55

    # Timeline now contains the clip on V1 + A1
    tl = (await auth_client.get(f"/api/projects/{pid}/timeline")).json()
    doc = tl["document"]
    assert tl["version"]["version"] == 2 and tl["version"]["source"] == "system"
    assert doc["tracks"][0]["clips"][0]["asset_id"] == asset["id"]
    assert doc["tracks"][2]["clips"][0]["linked_clip_id"] == doc["tracks"][0]["clips"][0]["id"]
    assert doc["settings"]["width"] == 320

    # Listing + duplicate detection (server-side, by content hash)
    items = (await auth_client.get(f"/api/projects/{pid}/assets")).json()
    assert len(items) == 1
    dup = await _upload(auth_client, pid, video)
    assert (
        dup["asset"]["status"] == "duplicate"
        and dup["asset"]["extra"]["duplicate_of"] == asset["id"]
    )

    # Client-side hash short-circuits the upload entirely
    h = hashlib.sha256(video.read_bytes()).hexdigest()
    init = await auth_client.post(
        f"/api/projects/{pid}/uploads",
        json={
            "filename": "again.mp4",
            "mime_type": "video/mp4",
            "size_bytes": video.stat().st_size,
            "client_hash": h,
        },
    )
    assert init.json()["duplicate_of"]["id"] == asset["id"]


async def test_upload_rejects_wrong_content(auth_client: AsyncClient, tmp_path: Path) -> None:
    pid = (await auth_client.post("/api/projects", json={"name": "media"})).json()["id"]
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"<html>not a video</html>" * 10)
    result = await _upload(auth_client, pid, fake)
    asset = (await auth_client.get(f"/api/assets/{result['asset']['id']}")).json()
    assert (
        asset["status"] == "failed"
        or (await auth_client.get(f"/api/jobs/{result['job_id']}")).json()["status"] == "FAILED"
    )


async def test_asset_authorization(
    auth_client: AsyncClient, other_client: AsyncClient, tmp_path: Path
) -> None:
    pid = (await auth_client.post("/api/projects", json={"name": "media"})).json()["id"]
    image = make_test_image(tmp_path / "pic.png")
    result = await _upload(auth_client, pid, image, mime="image/png")
    aid = result["asset"]["id"]
    assert (await other_client.get(f"/api/assets/{aid}")).status_code == 403
    assert (await other_client.get(f"/api/assets/{aid}/stream")).status_code == 403
    assert (await other_client.delete(f"/api/assets/{aid}")).status_code == 403
    assert (await auth_client.delete(f"/api/assets/{aid}")).status_code == 200
    assert (await auth_client.get(f"/api/assets/{aid}")).status_code == 404


async def test_parallel_chunk_uploads_do_not_lose_receipts(
    auth_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from cutpilot.core import config

    monkeypatch.setattr(config.get_settings(), "upload_chunk_size", 32 * 1024)
    pid = (await auth_client.post("/api/projects", json={"name": "parallel"})).json()["id"]
    data = make_test_video(tmp_path / "p.mp4", duration=3).read_bytes()
    init = (
        await auth_client.post(
            f"/api/projects/{pid}/uploads",
            json={"filename": "p.mp4", "mime_type": "video/mp4", "size_bytes": len(data)},
        )
    ).json()
    uid, size, total = init["upload_id"], init["chunk_size"], init["total_chunks"]
    assert total >= 3

    async def put(i: int):  # type: ignore[no-untyped-def]
        return await auth_client.put(
            f"/api/projects/{pid}/uploads/{uid}/chunks/{i}",
            content=data[i * size : (i + 1) * size],
            headers={"content-type": "application/octet-stream"},
        )

    results = await asyncio.gather(*(put(i) for i in range(total)))
    assert all(r.status_code == 200 for r in results)
    status = (await auth_client.get(f"/api/projects/{pid}/uploads/{uid}")).json()
    assert status["received_chunks"] == list(range(total))
    done = await auth_client.post(f"/api/projects/{pid}/uploads/{uid}/complete")
    assert done.status_code == 200, done.text
    assert done.json()["asset"]["status"] == "ready"


async def test_complete_reports_missing_chunks(
    auth_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cutpilot.core import config

    monkeypatch.setattr(config.get_settings(), "upload_chunk_size", 32 * 1024)
    pid = (await auth_client.post("/api/projects", json={"name": "missing"})).json()["id"]
    data = make_test_video(tmp_path / "m.mp4", duration=3).read_bytes()
    init = (
        await auth_client.post(
            f"/api/projects/{pid}/uploads",
            json={"filename": "m.mp4", "mime_type": "video/mp4", "size_bytes": len(data)},
        )
    ).json()
    uid, size, total = init["upload_id"], init["chunk_size"], init["total_chunks"]
    for i in range(total):
        if i == 1:
            continue
        await auth_client.put(
            f"/api/projects/{pid}/uploads/{uid}/chunks/{i}",
            content=data[i * size : (i + 1) * size],
            headers={"content-type": "application/octet-stream"},
        )
    res = await auth_client.post(f"/api/projects/{pid}/uploads/{uid}/complete")
    assert res.status_code == 422 and res.json()["error"]["details"]["missing_chunks"] == [1]
    await auth_client.put(
        f"/api/projects/{pid}/uploads/{uid}/chunks/1",
        content=data[size : 2 * size],
        headers={"content-type": "application/octet-stream"},
    )
    assert (
        await auth_client.post(f"/api/projects/{pid}/uploads/{uid}/complete")
    ).status_code == 200
