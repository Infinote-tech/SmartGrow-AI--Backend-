from datetime import datetime

import pytest

SAMPLES = {
    "sensor-data": (
        "sensor_data",
        "sensor_data_id",
        {
            "esp32_id": "esp32-01",
            "tray_id": "tray-1",
            "seed_type": "radish",
            "media_type": "cocopeat",
            "temperature": 25.4,
            "humidity": 62.0,
            "soil_moisture": 66.5,
            "light_intensity": 11000,
            "water_level": 80,
            "water_flow_rate": 1.2,
        },
    ),
    "model-outputs": (
        "model_outputs",
        "output_id",
        {
            "tray_id": "tray-1",
            "model_name": "growth-lstm",
            "model_version": "0.1",
            "growth_prediction": "on_track",
            "stress_probability": 0.12,
            "anomaly_score": 0.03,
            "sensor_health_score": 0.97,
            "predicted_soil_moisture": 64.0,
            "predicted_harvest_date": "2026-10-10",
            "predicted_yield": 245.5,
            "irrigation_recommendation": "water_small_dose",
            "recommended_action": "irrigate",
            "recommendation_confidence": 0.88,
            "recommendation_reason": "moisture below dry line",
        },
    ),
    "hardware-status": (
        "hardware_status",
        "hardware_status_id",
        {
            "esp32_id": "esp32-01",
            "overall_system_status": "ok",
            "solenoid_1_status": "closed",
            "solenoid_2_status": "closed",
            "solenoid_3_status": "open",
            "fan_status": "on",
            "motor_status": "off",
            "water_pump_status": "off",
            "power_status": "ok",
            "connectivity_status": "online",
        },
    ),
    "tray-status": (
        "tray_status",
        "tray_status_id",
        {
            "tray_1_status": "active",
            "tray_2_status": "active",
            "tray_3_status": "empty",
            "tray_1_seed_type": "radish",
            "tray_2_seed_type": "mustard",
            "tray_1_media_type": "cocopeat",
            "tray_2_media_type": "compost",
        },
    ),
    "thresholds": (
        "thresholds",
        "threshold_id",
        {
            "seed_type": "radish",
            "media_type": "cocopeat",
            "growth_stage": "germination",
            "parameter": "soil_moisture",
            "optimal_min": 55,
            "optimal_max": 75,
            "warning_min": 45,
            "warning_max": 85,
            "critical_min": 35,
            "critical_max": 90,
            "threshold_version": "v1",
            "effective_from": "2026-10-01T00:00:00Z",
        },
    ),
    "irrigation-logs": (
        "irrigation_logs",
        "irrigation_id",
        {
            "tray_id": "tray-1",
            "solenoid_id": "1",
            "pump_status": "on",
            "irrigation_duration": 8,
            "water_consumed": 40.5,
            "trigger_type": "auto",
            "trigger_reason": "moisture below dry line",
            "ai_recommended": True,
            "actual_action": "irrigated",
        },
    ),
    "fault-events": (
        "fault_events",
        "fault_id",
        {
            "esp32_id": "esp32-01",
            "tray_id": "tray-2",
            "fault_type": "soil_moisture_sensor_stuck",
            "fault_source": "sensor",
            "severity": "critical",
            "sensor_value": 0.0,
            "expected_min": 35,
            "expected_max": 90,
            "anomaly_score": 0.91,
            "fault_probability": 0.87,
            "detected_by": "tinyml",
            "recommended_action": "inspect sensor",
            "automatic_action": "irrigation paused",
            "fault_status": "active",
        },
    ),
    "crop-batches": (
        "crop_batches",
        "batch_id",
        {
            "seed_type": "radish",
            "media_type": "cocopeat",
            "planting_date": "2026-09-30",
            "expected_harvest_date": "2026-10-10",
            "seed_quantity": 25,
            "tray_id": "tray-1",
            "batch_status": "growing",
        },
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", list(SAMPLES))
async def test_insert_stores_document_with_generated_id(client, auth_headers, test_db, path):
    collection, id_field, payload = SAMPLES[path]
    resp = await client.post(f"/api/v1/{path}", json=payload, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body[id_field] and body["created_at"]
    for key, value in payload.items():
        if not key.endswith(("_date", "_from")) and not isinstance(value, float | int):
            assert body[key] == value

    stored = await test_db[collection].find_one({id_field: body[id_field]})
    assert stored is not None
    assert isinstance(stored["created_at"], datetime)  # stored as a BSON datetime, not a string
    assert datetime.fromisoformat(body["created_at"].replace("Z", "+00:00")).replace(tzinfo=None) == stored["created_at"]


@pytest.mark.asyncio
async def test_sensor_timestamp_defaults_and_can_be_supplied(client, auth_headers, test_db):
    base = SAMPLES["sensor-data"][2]
    auto = (await client.post("/api/v1/sensor-data", json=base, headers=auth_headers)).json()
    assert auto["timestamp"]
    given = (
        await client.post(
            "/api/v1/sensor-data", json={**base, "timestamp": "2026-10-01T06:00:00Z"}, headers=auth_headers
        )
    ).json()
    assert given["timestamp"].startswith("2026-10-01T06:00:00")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", list(SAMPLES))
async def test_insert_requires_auth(client, path):
    resp = await client.post(f"/api/v1/{path}", json=SAMPLES[path][2])
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_required_fields_validated(client, auth_headers):
    resp = await client.post("/api/v1/sensor-data", json={"seed_type": "radish"}, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("path", list(SAMPLES))
async def test_only_insert_is_exposed(client, auth_headers, path):
    assert (await client.get(f"/api/v1/{path}", headers=auth_headers)).status_code == 405
    assert (await client.delete(f"/api/v1/{path}/abc", headers=auth_headers)).status_code == 404


@pytest.mark.asyncio
async def test_old_tray_entry_endpoint_removed(client, auth_headers):
    resp = await client.post(
        "/api/v1/trays", json={"seed_type": "a", "substrate_type": "b", "tray_number": 1}, headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_timestamps_stored_as_utc_datetimes(client, auth_headers, test_db):
    base = SAMPLES["sensor-data"][2]
    # an offset timestamp is converted to UTC, a naive one is treated as UTC
    await client.post("/api/v1/sensor-data", json={**base, "timestamp": "2026-10-01T08:00:00+02:00"}, headers=auth_headers)
    await client.post("/api/v1/sensor-data", json={**base, "timestamp": "2026-10-01T06:00:00"}, headers=auth_headers)
    stamps = [d["timestamp"] async for d in test_db["sensor_data"].find({})]
    assert all(isinstance(t, datetime) for t in stamps)
    assert stamps[0] == stamps[1] == datetime(2026, 10, 1, 6, 0, 0)

    threshold = SAMPLES["thresholds"][2]
    await client.post("/api/v1/thresholds", json=threshold, headers=auth_headers)
    stored = await test_db["thresholds"].find_one({})
    assert isinstance(stored["effective_from"], datetime) and isinstance(stored["updated_at"], datetime)
