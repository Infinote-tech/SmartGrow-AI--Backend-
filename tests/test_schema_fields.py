import pytest

from tests.helpers import post


@pytest.mark.asyncio
async def test_irrigation_log_accepts_and_returns_new_fields(client, auth_headers):
    payload = {
        "tray_id": "tray-1",
        "batch_id": "b1",
        "model_output_id": "o1",
        "growth_stage": "early_growth",
        "pre_irrigation_moisture": 42.5,
        "post_irrigation_moisture": 47.0,
        "post_measured_after_s": 900,
        "water_volume": 100,
        "avg_flow_rate": 1.1,
        "flow_cv": 0.2,
        "expected_response": 4.0,
        "actual_response": 4.5,
        "response_deviation": 0.5,
    }
    body = await post(client, auth_headers, "/irrigation-logs", payload)
    for key, value in payload.items():
        assert body[key] == value
    assert body["irrigation_id"]


@pytest.mark.asyncio
async def test_model_output_accepts_and_returns_new_fields(client, auth_headers):
    payload = {
        "tray_id": "tray-1",
        "model_name": "crop_water_response",
        "batch_id": "b1",
        "irrigation_id": "i1",
        "growth_stage": "blackout",
        "input_features": {"pre_irrigation_moisture": 40.0, "tray_id": "tray-1"},
        "expected_moisture_change": 4.0,
        "expected_moisture_after_irrigation": 44.0,
        "expected_moisture_lower": 41.0,
        "expected_moisture_upper": 47.0,
        "actual_moisture_after_irrigation": 45.0,
        "response_error": 1.0,
        "response_confidence": 0.7,
        "water_response_score": 0.8,
        "decision_volume_ml": 150,
        "candidate_evaluations": [{"volume_ml": 150, "accepted": True}],
    }
    body = await post(client, auth_headers, "/model-outputs", payload)
    for key, value in payload.items():
        assert body[key] == value


@pytest.mark.asyncio
async def test_fault_event_accepts_new_fields_and_injected_defaults_false(client, auth_headers):
    base = {"esp32_id": "esp32-01", "fault_type": "response_anomaly", "severity": "warning"}
    default = await post(client, auth_headers, "/fault-events", base)
    assert default["injected"] is False

    payload = {
        **base,
        "irrigation_id": "i1",
        "response_deviation": -6.5,
        "fault_hypothesis": "pump_tank_blockage",
        "fault_confidence": 0.8,
        "flow_class": "no_flow",
        "response_class": "no_change",
        "diagnostic_action": "Check reservoir level",
        "recovery_action": "Refill",
        "recovery_success": True,
        "injected": True,
    }
    body = await post(client, auth_headers, "/fault-events", payload)
    for key, value in payload.items():
        assert body[key] == value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,payload",
    [
        ("/irrigation-logs", {"tray_id": "t", "pre_irrigation_moisture": 120}),
        ("/irrigation-logs", {"tray_id": "t", "post_irrigation_moisture": -1}),
        ("/irrigation-logs", {"tray_id": "t", "water_volume": -5}),
        ("/irrigation-logs", {"tray_id": "t", "avg_flow_rate": -0.1}),
        ("/irrigation-logs", {"tray_id": "t", "post_measured_after_s": -1}),
        ("/irrigation-logs", {"tray_id": "t", "growth_stage": "flowering"}),
        ("/model-outputs", {"tray_id": "t", "model_name": "m", "expected_moisture_after_irrigation": 120}),
        ("/model-outputs", {"tray_id": "t", "model_name": "m", "response_confidence": 1.5}),
        ("/model-outputs", {"tray_id": "t", "model_name": "m", "decision_volume_ml": -1}),
        ("/fault-events", {"esp32_id": "e", "fault_type": "t", "severity": "w", "fault_hypothesis": "gremlins"}),
        ("/fault-events", {"esp32_id": "e", "fault_type": "t", "severity": "w", "fault_confidence": 2}),
    ],
)
async def test_out_of_range_values_rejected(client, auth_headers, path, payload):
    response = await client.post(f"/api/v1{path}", json=payload, headers=auth_headers)
    assert response.status_code == 422


NEW_ENDPOINTS = [
    ("post", "/ml/water-response/predict", {"tray_id": "t", "water_volume": 100}),
    ("post", "/ml/response-deviation/evaluate", {"irrigation_id": "x"}),
    ("post", "/irrigation-logs/x/response", {"post_irrigation_moisture": 50}),
    ("patch", "/fault-events/x/resolve", {"resolution_reason": "done"}),
    ("post", "/policy/trays/t/decide", None),
    ("get", "/policy/trays/t/latest", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", NEW_ENDPOINTS)
async def test_new_endpoints_require_auth(client, method, path, body):
    response = await client.request(method.upper(), f"/api/v1{path}", json=body)
    assert response.status_code == 401
