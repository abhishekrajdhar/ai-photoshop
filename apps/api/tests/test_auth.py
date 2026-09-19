import pytest
from httpx import AsyncClient


async def test_register_login_me(client: AsyncClient) -> None:
    res = await client.post(
        "/api/auth/register", json={"email": "u@example.com", "password": "password123"}
    )
    assert res.status_code == 201
    body = res.json()
    assert body["user"]["email"] == "u@example.com"
    assert "cutpilot_access" in res.cookies

    dup = await client.post(
        "/api/auth/register", json={"email": "u@example.com", "password": "password123"}
    )
    assert dup.status_code == 409

    bad = await client.post("/api/auth/login", json={"email": "u@example.com", "password": "wrong"})
    assert bad.status_code == 401

    ok = await client.post(
        "/api/auth/login", json={"email": "U@example.com", "password": "password123"}
    )
    assert ok.status_code == 200
    me = await client.get(
        "/api/auth/me", headers={"authorization": f"Bearer {ok.json()['access_token']}"}
    )
    assert me.status_code == 200 and me.json()["email"] == "u@example.com"


async def test_cookie_auth_requires_csrf_header(client: AsyncClient) -> None:
    await client.post(
        "/api/auth/register", json={"email": "c@example.com", "password": "password123"}
    )
    # Cookie is set; a mutating request without the CSRF header must be rejected
    client.headers.pop("x-requested-with")
    res = await client.post("/api/projects", json={"name": "x"})
    assert res.status_code == 403
    res = await client.post(
        "/api/projects", json={"name": "x"}, headers={"x-requested-with": "fetch"}
    )
    assert res.status_code == 201


async def test_password_reset_flow(client: AsyncClient) -> None:
    await client.post(
        "/api/auth/register", json={"email": "r@example.com", "password": "password123"}
    )
    res = await client.post("/api/auth/password-reset/request", json={"email": "r@example.com"})
    token = res.json()["dev_reset_token"]
    assert token
    res = await client.post(
        "/api/auth/password-reset/confirm", json={"token": token, "password": "newpassword1"}
    )
    assert res.status_code == 200
    res = await client.post(
        "/api/auth/login", json={"email": "r@example.com", "password": "newpassword1"}
    )
    assert res.status_code == 200
    # token cannot be reused
    res = await client.post(
        "/api/auth/password-reset/confirm", json={"token": token, "password": "another123"}
    )
    assert res.status_code == 422


@pytest.mark.parametrize("path", ["/api/projects", "/api/jobs", "/api/auth/me"])
async def test_private_routes_require_auth(client: AsyncClient, path: str) -> None:
    res = await client.get(path)
    assert res.status_code == 401
