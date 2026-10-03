import pytest

from tests.helpers import log_irrigation, post

# baseline-v0 for pre = 40 % VWC and 100 mL:  gain = 8 * 1 * (30 / 70) = 3.4286  ->  expected_after = 43.4286
EXPECTED_CHANGE = 8.0 * (30 / 70)


@pytest.mark.asyncio
async def test_response_computes_actual_response_and_deviation(client, auth_headers):
    log = await log_irrigation(client, auth_headers)
    result = await post(
        client, auth_headers, f"/irrigation-logs/{log['irrigation_id']}/response",
        {"post_irrigation_moisture": 46.0, "avg_flow_rate": 1.2, "flow_cv": 0.1}, expect=200,
    )
    stored = result["irrigation_log"]
    assert stored["post_irrigation_moisture"] == 46.0
    assert stored["actual_response"] == pytest.approx(6.0)
    assert stored["expected_response"] == pytest.approx(EXPECTED_CHANGE)
    assert stored["response_deviation"] == pytest.approx(6.0 - EXPECTED_CHANGE)
    assert stored["post_measured_after_s"] == 900  # default_post_measure_delay_s
    assert stored["avg_flow_rate"] == 1.2 and stored["flow_cv"] == 0.1
    assert stored["model_output_id"] == result["model_output"]["output_id"]  # Model 1 was called and linked


@pytest.mark.asyncio
async def test_response_updates_the_linked_model_output(client, auth_headers, test_db):
    log = await log_irrigation(client, auth_headers)
    result = await post(
        client, auth_headers, f"/irrigation-logs/{log['irrigation_id']}/response",
        {"post_irrigation_moisture": 46.0, "post_measured_after_s": 600}, expect=200,
    )
    output = result["model_output"]
    assert output["model_name"] == "crop_water_response"
    assert output["irrigation_id"] == log["irrigation_id"]
    assert output["actual_moisture_after_irrigation"] == 46.0
    assert output["response_error"] == pytest.approx(46.0 - (40 + EXPECTED_CHANGE))
    assert 0.0 <= output["water_response_score"] <= 1.0
    assert result["irrigation_log"]["post_measured_after_s"] == 600

    stored = await test_db["model_outputs"].find_one({"output_id": output["output_id"]})
    assert stored["irrigation_id"] == log["irrigation_id"]


@pytest.mark.asyncio
async def test_a_perfect_response_scores_one(client, auth_headers):
    log = await log_irrigation(client, auth_headers)
    result = await post(
        client, auth_headers, f"/irrigation-logs/{log['irrigation_id']}/response",
        {"post_irrigation_moisture": 40 + EXPECTED_CHANGE}, expect=200,
    )
    assert result["model_output"]["water_response_score"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_existing_model_output_is_used_as_the_expectation(client, auth_headers):
    prediction = await post(
        client, auth_headers, "/ml/water-response/predict",
        {"tray_id": "tray-1", "water_volume": 100, "pre_irrigation_moisture": 40.0},
    )
    log = await log_irrigation(client, auth_headers, model_output_id=prediction["output_id"])
    result = await post(
        client, auth_headers, f"/irrigation-logs/{log['irrigation_id']}/response",
        {"post_irrigation_moisture": 44.0}, expect=200,
    )
    assert result["model_output"]["output_id"] == prediction["output_id"]  # reused, not recomputed
    assert result["irrigation_log"]["expected_response"] == pytest.approx(prediction["expected_moisture_change"])
    assert result["model_output"]["irrigation_id"] == log["irrigation_id"]


@pytest.mark.asyncio
async def test_unknown_irrigation_id_is_404(client, auth_headers):
    response = await client.post(
        "/api/v1/irrigation-logs/does-not-exist/response", json={"post_irrigation_moisture": 50}, headers=auth_headers
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_missing_pre_irrigation_moisture_is_422(client, auth_headers):
    log = await post(client, auth_headers, "/irrigation-logs", {"tray_id": "tray-1", "water_volume": 100})
    response = await client.post(
        f"/api/v1/irrigation-logs/{log['irrigation_id']}/response",
        json={"post_irrigation_moisture": 50}, headers=auth_headers,
    )
    assert response.status_code == 422
    assert "pre_irrigation_moisture" in response.json()["detail"]


@pytest.mark.asyncio
async def test_missing_volume_is_422(client, auth_headers):
    log = await post(client, auth_headers, "/irrigation-logs", {"tray_id": "tray-1", "pre_irrigation_moisture": 40})
    response = await client.post(
        f"/api/v1/irrigation-logs/{log['irrigation_id']}/response",
        json={"post_irrigation_moisture": 50}, headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_moisture_must_be_a_percentage(client, auth_headers):
    log = await log_irrigation(client, auth_headers)
    response = await client.post(
        f"/api/v1/irrigation-logs/{log['irrigation_id']}/response",
        json={"post_irrigation_moisture": 120}, headers=auth_headers,
    )
    assert response.status_code == 422
