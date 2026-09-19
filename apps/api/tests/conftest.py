"""Test fixtures: in-memory SQLite database, app client, authenticated user."""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator

os.environ.setdefault("APP_ENV", "test")
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp_db.name}"
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret"
os.environ["LOCAL_STORAGE_ROOT"] = tempfile.mkdtemp(prefix="cutpilot-storage-")
os.environ["WORK_DIR"] = tempfile.mkdtemp(prefix="cutpilot-work-")
os.environ["STORAGE_PROVIDER"] = "local"
os.environ["OPENAI_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import cutpilot.db.models  # noqa: F401
from cutpilot.db.base import Base
from cutpilot.db.session import get_async_engine
from cutpilot.main import app


@pytest_asyncio.fixture(autouse=True)
async def _db_schema() -> AsyncIterator[None]:
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"x-requested-with": "tests"}
    ) as c:
        yield c


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient) -> AsyncClient:
    res = await client.post(
        "/api/auth/register",
        json={"email": "alice@example.com", "password": "password123", "display_name": "Alice"},
    )
    assert res.status_code == 201, res.text
    client.headers["authorization"] = f"Bearer {res.json()['access_token']}"
    return client


@pytest_asyncio.fixture
async def other_client(auth_client: AsyncClient) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"x-requested-with": "tests"}
    ) as c:
        res = await c.post(
            "/api/auth/register", json={"email": "bob@example.com", "password": "password123"}
        )
        assert res.status_code == 201
        c.headers["authorization"] = f"Bearer {res.json()['access_token']}"
        yield c


@pytest.fixture
def project_payload() -> dict[str, object]:
    return {"name": "Test project", "description": "demo"}
