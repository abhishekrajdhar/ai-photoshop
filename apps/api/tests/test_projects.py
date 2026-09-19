from httpx import AsyncClient


async def test_project_crud_and_authorization(
    auth_client: AsyncClient, other_client: AsyncClient, project_payload: dict
) -> None:
    res = await auth_client.post("/api/projects", json=project_payload)
    assert res.status_code == 201, res.text
    project = res.json()
    assert project["settings"]["target_platform"] == "youtube"
    pid = project["id"]

    res = await auth_client.get("/api/projects")
    assert res.json()["total"] == 1

    # Other users cannot see, modify, or delete it
    assert (await other_client.get(f"/api/projects/{pid}")).status_code == 403
    assert (
        await other_client.patch(f"/api/projects/{pid}", json={"name": "hack"})
    ).status_code == 403
    assert (await other_client.delete(f"/api/projects/{pid}")).status_code == 403

    res = await auth_client.patch(
        f"/api/projects/{pid}", json={"name": "Renamed", "settings": {"target_platform": "tiktok"}}
    )
    assert res.json()["name"] == "Renamed" and res.json()["settings"]["target_platform"] == "tiktok"

    res = await auth_client.post(f"/api/projects/{pid}/duplicate")
    assert res.status_code == 201 and res.json()["name"] == "Renamed (copy)"

    res = await auth_client.post(f"/api/projects/{pid}/archive")
    assert res.json()["status"] == "archived"
    assert (await auth_client.get("/api/projects")).json()["total"] == 1  # copy only
    assert (await auth_client.get("/api/projects?include_archived=true")).json()["total"] == 2

    assert (await auth_client.delete(f"/api/projects/{pid}")).status_code == 200
    assert (await auth_client.get(f"/api/projects/{pid}")).status_code == 404


async def test_new_project_has_primary_timeline(
    auth_client: AsyncClient, project_payload: dict
) -> None:
    res = await auth_client.post("/api/projects", json=project_payload)
    pid = res.json()["id"]
    res = await auth_client.get(f"/api/projects/{pid}/timeline")
    assert res.status_code == 200, res.text
    doc = res.json()["document"]
    assert [t["id"] for t in doc["tracks"]] == ["V1", "V2", "A1", "A2", "C1"]


async def test_timeline_versions_undo_redo_restore(
    auth_client: AsyncClient, project_payload: dict
) -> None:
    pid = (await auth_client.post("/api/projects", json=project_payload)).json()["id"]
    state = (await auth_client.get(f"/api/projects/{pid}/timeline")).json()
    doc = state["document"]
    # Manually add a clip via PUT (simulates a user edit)
    doc["tracks"][0]["clips"].append(
        {
            "kind": "video",
            "name": "c",
            "asset_id": "a",
            "timeline_start": 0,
            "duration": 10,
            "source_in": 0,
            "source_out": 10,
        }
    )
    res = await auth_client.put(
        f"/api/projects/{pid}/timeline", json={"document": doc, "label": "Add clip"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["version"]["version"] == 2 and res.json()["can_undo"]

    res = await auth_client.post(
        f"/api/projects/{pid}/timeline/operations",
        json={
            "operations": [{"type": "remove_segment", "asset_id": "a", "start": 2, "end": 4}],
            "label": "cut",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["duration_before"] == 10 and body["duration_after"] == 8
    assert body["state"]["version"]["operation_count"] == 1

    res = await auth_client.post(f"/api/projects/{pid}/timeline/undo")
    assert res.json()["version"]["version"] == 2 and res.json()["can_redo"]
    res = await auth_client.post(f"/api/projects/{pid}/timeline/redo")
    assert res.json()["version"]["version"] == 3

    versions = (await auth_client.get(f"/api/projects/{pid}/timeline/versions")).json()
    assert [v["version"] for v in versions] == [1, 2, 3]
    v1 = versions[0]["id"]
    res = await auth_client.post(f"/api/projects/{pid}/timeline/versions/{v1}/restore")
    assert res.json()["version"]["version"] == 4 and res.json()["version"]["duration"] == 0
    cmp = (
        await auth_client.get(
            f"/api/projects/{pid}/timeline/versions/{versions[1]['id']}/compare/{versions[2]['id']}"
        )
    ).json()
    assert cmp["duration_delta"] == -2
