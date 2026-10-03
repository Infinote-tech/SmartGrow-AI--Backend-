import random
from datetime import timedelta

import pytest

from app.core.config import settings
from app.services.irrigation_policy_service import IrrigationPolicyService, drying_slope_per_minute
from app.services.scheduler import run_policy_cycle
from tests.helpers import now_utc, post, seed_tray

# baseline-v0 at pre = 35 % VWC:  gain(v) = 8 * (v / 100) * (35 / 70) = 0.04 * v   (median after = 35 + 0.04 v,
# interval +/- 3).  With optimal_min = 38 and margin 2 the target is 40, so 150 mL (41) and 200 mL (43) are accepted
# and 100 mL (39) is not.
DRY = 35.0
BAND = {"optimal_min": 38, "optimal_max": 75, "critical_max": 90}


async def decide(client, headers, tray_id="tray-1", expect=201):
    response = await client.post(f"/api/v1/policy/trays/{tray_id}/decide", headers=headers)
    assert response.status_code == expect, response.text
    return response.json()


# ------------------------------------------------------------------ decisions


@pytest.mark.asyncio
async def test_active_high_confidence_fault_holds_and_inspects(client, auth_headers):
    await seed_tray(client, auth_headers, moisture=DRY, threshold=BAND)
    await post(
        client, auth_headers, "/fault-events",
        {"esp32_id": "e", "tray_id": "tray-1", "fault_type": "response_anomaly", "severity": "critical",
         "fault_status": "active", "fault_hypothesis": "pump_tank_blockage", "fault_confidence": 0.9},
    )
    out = await decide(client, auth_headers)
    assert out["irrigation_recommendation"] == "hold_and_inspect"
    assert out["decision_volume_ml"] == 0
    assert "active_fault(pump_tank_blockage)" in out["recommendation_reason"]
    assert out["recommendation_confidence"] == 0.9


@pytest.mark.asyncio
async def test_low_confidence_or_resolved_faults_do_not_block(client, auth_headers):
    await seed_tray(client, auth_headers, moisture=DRY, threshold=BAND)
    base = {"esp32_id": "e", "tray_id": "tray-1", "fault_type": "t", "severity": "warning"}
    await post(client, auth_headers, "/fault-events", {**base, "fault_confidence": 0.3})
    await post(client, auth_headers, "/fault-events", {**base, "fault_confidence": 0.95, "fault_status": "resolved"})
    out = await decide(client, auth_headers)
    assert out["irrigation_recommendation"] == "irrigate"


@pytest.mark.asyncio
async def test_recent_irrigation_means_wait(client, auth_headers):
    await seed_tray(client, auth_headers, moisture=DRY, threshold=BAND)
    await post(
        client, auth_headers, "/irrigation-logs",
        {"tray_id": "tray-1", "water_volume": 100, "timestamp": (now_utc() - timedelta(minutes=10)).isoformat()},
    )
    out = await decide(client, auth_headers)
    assert out["irrigation_recommendation"] == "wait"
    assert "min_interval_not_elapsed" in out["recommendation_reason"]
    assert out["decision_volume_ml"] == 0


@pytest.mark.asyncio
async def test_daily_volume_limit_means_wait(client, auth_headers):
    await seed_tray(client, auth_headers, moisture=DRY, threshold=BAND)
    await post(
        client, auth_headers, "/irrigation-logs",
        {"tray_id": "tray-1", "water_volume": settings.policy_max_daily_volume_ml,
         "timestamp": (now_utc() - timedelta(hours=5)).isoformat()},
    )
    out = await decide(client, auth_headers)
    assert out["irrigation_recommendation"] == "wait"
    assert "daily_volume_limit_reached" in out["recommendation_reason"]


@pytest.mark.asyncio
async def test_forecast_above_the_band_means_wait(client, auth_headers):
    await seed_tray(client, auth_headers, moisture=60.0, threshold=BAND)  # 60 >= 38 + 2
    out = await decide(client, auth_headers)
    assert out["irrigation_recommendation"] == "wait"
    assert "forecast_within_band" in out["recommendation_reason"]
    assert out["candidate_evaluations"] is None


@pytest.mark.asyncio
async def test_a_fast_drying_tray_is_irrigated_even_if_it_is_currently_in_band(client, auth_headers):
    # 50 -> 45 -> 40 over 2 h with a 60 min horizon: forecast = 40 - 2.5 * ... below the 40 target
    await seed_tray(client, auth_headers, moisture=None, threshold=BAND)
    for minutes_ago, value in [(120, 50.0), (60, 45.0), (5, 41.0)]:
        await post(
            client, auth_headers, "/sensor-data",
            {"esp32_id": "e", "tray_id": "tray-1", "soil_moisture": value,
             "timestamp": (now_utc() - timedelta(minutes=minutes_ago)).isoformat()},
        )
    out = await decide(client, auth_headers)
    assert out["input_features"]["drying_slope_per_min"] < 0
    assert out["input_features"]["forecast_moisture"] < 40
    assert out["irrigation_recommendation"] == "irrigate"


@pytest.mark.asyncio
async def test_dry_tray_with_thresholds_gets_the_smallest_accepted_volume(client, auth_headers):
    batch = await seed_tray(client, auth_headers, moisture=DRY, threshold=BAND)
    out = await decide(client, auth_headers)
    assert out["irrigation_recommendation"] == "irrigate"
    assert out["decision_volume_ml"] == 150
    assert out["recommended_action"] == "Irrigate tray tray-1 with 150 mL"
    assert out["model_name"] == "adaptive_irrigation_policy" and out["model_version"] == "policy-v0"
    assert out["batch_id"] == batch["batch_id"] and out["growth_stage"] == "early_growth"
    assert "default_thresholds_used" not in out["recommendation_reason"]
    assert out["expected_moisture_after_irrigation"] == pytest.approx(41.0)
    assert out["expected_moisture_lower"] < out["expected_moisture_after_irrigation"] < out["expected_moisture_upper"]
    assert out["expected_moisture_change"] == pytest.approx(6.0)
    assert out["recommendation_confidence"] == pytest.approx(0.3)  # baseline model confidence, real thresholds

    evaluations = out["candidate_evaluations"]
    assert [c["volume_ml"] for c in evaluations] == [50, 100, 150, 200]  # 0 mL is not a candidate
    assert [c["accepted"] for c in evaluations] == [False, False, True, True]
    assert evaluations[0]["reason"] == "below_target" and evaluations[2]["reason"] == "accepted"
    assert out["input_features"]["optimal_min"] == 38


@pytest.mark.asyncio
async def test_candidates_that_overshoot_the_band_are_rejected(client, auth_headers, monkeypatch):
    await seed_tray(client, auth_headers, moisture=DRY, threshold={"optimal_min": 38, "optimal_max": 44})
    out = await decide(client, auth_headers)  # 200 mL: upper = 43 + 3 = 46 > 44
    by_volume = {c["volume_ml"]: c for c in out["candidate_evaluations"]}
    assert by_volume[200]["accepted"] is False and "exceeds_optimal_max" in by_volume[200]["reason"]
    assert out["decision_volume_ml"] == 150


@pytest.mark.asyncio
async def test_missing_thresholds_use_defaults_and_halve_confidence(client, auth_headers, monkeypatch):
    # defaults 45 / 65 -> target 47; at 40 % a 300 mL dose reaches 50.3 (upper 55.4) and is accepted
    monkeypatch.setattr(settings, "policy_candidate_volumes_ml", [0, 300])
    await seed_tray(client, auth_headers, moisture=40.0, threshold=None)
    out = await decide(client, auth_headers)
    assert out["irrigation_recommendation"] == "irrigate" and out["decision_volume_ml"] == 300
    assert "default_thresholds_used" in out["recommendation_reason"]
    assert out["recommendation_confidence"] == pytest.approx(0.3 * 0.5)
    assert out["input_features"]["default_thresholds_used"] is True


@pytest.mark.asyncio
async def test_no_accepted_candidate_falls_back_to_the_closest_to_the_midpoint(client, auth_headers):
    await seed_tray(client, auth_headers, moisture=20.0, threshold={"optimal_min": 60, "optimal_max": 75})
    out = await decide(client, auth_headers)
    assert out["irrigation_recommendation"] == "irrigate"
    assert "no_accepted_candidate_fallback" in out["recommendation_reason"]
    assert all(not c["accepted"] for c in out["candidate_evaluations"])
    assert out["decision_volume_ml"] == 200  # biggest dose lands closest to the 67.5 midpoint


@pytest.mark.asyncio
async def test_no_safe_candidate_holds_and_inspects(client, auth_headers):
    # every candidate's upper bound is above critical_max
    await seed_tray(
        client, auth_headers, moisture=DRY, threshold={"optimal_min": 60, "optimal_max": 75, "critical_max": 30}
    )
    out = await decide(client, auth_headers)
    assert out["irrigation_recommendation"] == "hold_and_inspect"
    assert "no_safe_candidate" in out["recommendation_reason"]
    assert out["candidate_evaluations"]


@pytest.mark.asyncio
async def test_policy_never_writes_irrigation_logs(client, auth_headers, test_db):
    await seed_tray(client, auth_headers, moisture=DRY, threshold=BAND)
    before = await test_db["irrigation_logs"].count_documents({})
    await decide(client, auth_headers)
    assert await test_db["irrigation_logs"].count_documents({}) == before == 0


# ------------------------------------------------------------------ exploration (injectable RNG)


@pytest.mark.asyncio
async def test_exploration_only_picks_accepted_candidates(client, auth_headers, test_db, monkeypatch):
    await seed_tray(client, auth_headers, moisture=DRY, threshold=BAND)
    monkeypatch.setattr(settings, "policy_exploration_rate", 1.0)
    chosen = set()
    for seed in range(12):
        service = IrrigationPolicyService.from_db(test_db, rng=random.Random(seed))
        out = (await service.decide("tray-1")).model_dump()
        assert "exploration" in out["recommendation_reason"]
        chosen.add(out["decision_volume_ml"])
    assert chosen <= {150, 200}  # never 50 or 100, which are not accepted
    assert chosen == {150, 200}  # and both accepted options are explored


@pytest.mark.asyncio
async def test_exploration_is_off_by_default(client, auth_headers, test_db):
    await seed_tray(client, auth_headers, moisture=DRY, threshold=BAND)
    service = IrrigationPolicyService.from_db(test_db, rng=random.Random(1))
    out = (await service.decide("tray-1")).model_dump()
    assert "exploration" not in out["recommendation_reason"]
    assert out["decision_volume_ml"] == 150


# ------------------------------------------------------------------ state errors, latest, scheduler


@pytest.mark.asyncio
async def test_no_sensor_data_is_404_and_stale_data_is_422(client, auth_headers):
    await decide(client, auth_headers, tray_id="ghost", expect=404)
    await seed_tray(client, auth_headers, tray_id="stale", moisture=DRY, reading_age_minutes=180)
    response = await client.post("/api/v1/policy/trays/stale/decide", headers=auth_headers)
    assert response.status_code == 422 and "stale" in response.json()["detail"]


@pytest.mark.asyncio
async def test_latest_returns_the_most_recent_policy_output(client, auth_headers):
    await seed_tray(client, auth_headers, moisture=DRY, threshold=BAND)
    missing = await client.get("/api/v1/policy/trays/tray-1/latest", headers=auth_headers)
    assert missing.status_code == 404

    first = await decide(client, auth_headers)
    # other model outputs for the tray must not shadow the policy output
    await post(client, auth_headers, "/model-outputs", {"tray_id": "tray-1", "model_name": "growth_model"})
    latest = await client.get("/api/v1/policy/trays/tray-1/latest", headers=auth_headers)
    assert latest.status_code == 200
    assert latest.json()["output_id"] == first["output_id"]

    second = await decide(client, auth_headers)
    latest = await client.get("/api/v1/policy/trays/tray-1/latest", headers=auth_headers)
    assert latest.json()["output_id"] == second["output_id"]


@pytest.mark.asyncio
async def test_policy_cycle_continues_after_a_failing_tray(client, auth_headers, test_db):
    await seed_tray(client, auth_headers, moisture=DRY, threshold=BAND)
    outcome = await run_policy_cycle(["no-such-tray", "tray-1"], db=test_db)
    assert outcome["tray-1"] == "ok"
    assert outcome["no-such-tray"] != "ok"
    assert await test_db["model_outputs"].count_documents({"model_name": "adaptive_irrigation_policy"}) == 1


def test_scheduler_is_disabled_by_default():
    from app.services.scheduler import start_scheduler

    assert settings.policy_scheduler_enabled is False
    assert start_scheduler() is None


def test_drying_slope():
    t0 = now_utc()
    points = [(t0, 50.0), (t0 + timedelta(minutes=30), 45.0), (t0 + timedelta(minutes=60), 40.0)]
    assert drying_slope_per_minute(points) == pytest.approx(-10 / 60)
    assert drying_slope_per_minute(points[:2]) == 0.0  # needs at least three readings
