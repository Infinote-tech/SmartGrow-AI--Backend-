"""Small helpers shared by the model tests."""
from datetime import UTC, date, datetime, timedelta


def now_utc() -> datetime:
    return datetime.now(UTC)


async def post(client, headers, path: str, payload: dict | None = None, expect: int = 201) -> dict:
    response = await client.post(f"/api/v1{path}", json=payload, headers=headers)
    assert response.status_code == expect, response.text
    return response.json()


async def seed_tray(
    client,
    headers,
    *,
    tray_id: str = "tray-1",
    moisture: float | None = 40.0,
    planted_days_ago: int = 5,
    reading_age_minutes: float = 10,
    threshold: dict | None = None,
) -> dict:
    """Create an active batch, one fresh sensor reading and (optionally) a soil_moisture threshold row."""
    planting_date = (now_utc().date() - timedelta(days=planted_days_ago)).isoformat()
    batch = await post(
        client,
        headers,
        "/crop-batches",
        {"seed_type": "radish", "media_type": "cocopeat", "planting_date": planting_date, "tray_id": tray_id},
    )
    if moisture is not None:
        await post(
            client,
            headers,
            "/sensor-data",
            {
                "esp32_id": "esp32-01",
                "tray_id": tray_id,
                "temperature": 25.0,
                "humidity": 60.0,
                "light_intensity": 10000,
                "soil_moisture": moisture,
                "timestamp": (now_utc() - timedelta(minutes=reading_age_minutes)).isoformat(),
            },
        )
    if threshold is not None:
        await post(
            client,
            headers,
            "/thresholds",
            {
                "seed_type": "radish",
                "media_type": "cocopeat",
                "growth_stage": "early_growth",
                "parameter": "soil_moisture",
                **threshold,
            },
        )
    return batch


async def log_irrigation(client, headers, **fields) -> dict:
    payload = {"tray_id": "tray-1", "pre_irrigation_moisture": 40.0, "water_volume": 100.0, **fields}
    return await post(client, headers, "/irrigation-logs", payload)


def days_ago(n: int) -> date:
    return now_utc().date() - timedelta(days=n)
