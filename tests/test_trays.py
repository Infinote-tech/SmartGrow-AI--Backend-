import pytest


@pytest.mark.asyncio
async def test_create_tray_entry_stores_user_id(client, auth_headers, test_db):
    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    resp = await client.post(
        "/api/v1/trays",
        json={
            "seed_type": "radish",
            "substrate_type": "cocopeat",
            "tray_number": 3,
            "date": "2026-09-29",
            "time": "08:30:00",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["user_id"] == me["id"]
    assert (body["seed_type"], body["substrate_type"], body["tray_number"]) == ("radish", "cocopeat", 3)
    assert (body["date"], body["time"]) == ("2026-09-29", "08:30:00")

    stored = await test_db["tray_entries"].find_one({})
    assert stored["user_id"] == me["id"]


@pytest.mark.asyncio
async def test_date_and_time_default_to_now(client, auth_headers):
    resp = await client.post(
        "/api/v1/trays",
        json={"seed_type": "pea", "substrate_type": "peat", "tray_number": 1},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["date"] and resp.json()["time"]


@pytest.mark.asyncio
async def test_each_entry_is_stored_separately(client, auth_headers, test_db):
    payload = {"seed_type": "pea", "substrate_type": "peat", "tray_number": 1}
    await client.post("/api/v1/trays", json=payload, headers=auth_headers)
    await client.post("/api/v1/trays", json=payload, headers=auth_headers)
    assert await test_db["tray_entries"].count_documents({}) == 2


@pytest.mark.asyncio
async def test_create_tray_entry_requires_auth(client):
    resp = await client.post("/api/v1/trays", json={"seed_type": "a", "substrate_type": "b", "tray_number": 1})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_removed_endpoints_are_gone(client, auth_headers):
    for path in ["/api/v1/users", "/api/v1/sensors/ingest", "/api/v1/analytics/tray-summary", "/api/v1/agent/chat"]:
        assert (await client.get(path, headers=auth_headers)).status_code == 404
    assert (await client.get("/api/v1/trays", headers=auth_headers)).status_code == 405
