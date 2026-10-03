"""
Test fixtures.

Uses mongomock-motor to fake Motor's async API entirely in-memory, so the
test suite needs no real MongoDB instance for unit-style tests. CI also runs
a real Mongo service container (see .github/workflows/ci.yml) so this can be
swapped for an integration-style run against real Mongo if desired.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.core import database as database_module
from app.core.config import settings
from app.core.rate_limit import limiter
from app.main import app


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Rate-limit storage is process-wide (in-memory), so without this, tests
    that log in repeatedly trip the 5/minute login limit and start failing
    each other via shared state instead of on their own merits."""
    limiter.reset()
    yield


@pytest.fixture(autouse=True)
def isolate_model_artifacts(tmp_path, monkeypatch):
    """Point both model artifacts at empty temp paths so tests never pick up a model trained on a dev machine."""
    monkeypatch.setattr(settings, "water_response_model_path", str(tmp_path / "water_response.joblib"))
    monkeypatch.setattr(settings, "fault_classifier_path", str(tmp_path / "fault_classifier.joblib"))


@pytest_asyncio.fixture
async def test_db():
    client = AsyncMongoMockClient()
    db = client["smartgrow_test_db"]
    database_module.mongo.client = client
    database_module.mongo.db = db
    yield db


@pytest_asyncio.fixture
async def client(test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def registered_user(client):
    payload = {
        "email": "grower@example.com",
        "password": "supersecret123",
        "full_name": "Test Grower",
        "role": "grower",
    }
    await client.post("/api/v1/auth/register", json=payload)
    return payload


@pytest_asyncio.fixture
async def auth_headers(client, registered_user):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": registered_user["email"], "password": registered_user["password"]},
    )
    tokens = response.json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}
