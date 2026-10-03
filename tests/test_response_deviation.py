import joblib
import pytest

from app.core.config import settings
from app.ml.response_deviation import rules
from scripts import train_fault_classifier
from tests.helpers import log_irrigation, post

# Baseline-v0, pre = 40 % VWC, 300 mL:  gain = 8 * 3 * (30 / 70) = 10.29  ->  expected_after = 50.29,
# interval = 50.29 -/+ 5.14 = [45.14, 55.43], half_interval = 5.14.
PRE, VOLUME = 40.0, 300.0


async def link(client, headers, post_moisture, **flow):
    log = await log_irrigation(client, headers, pre_irrigation_moisture=PRE, water_volume=VOLUME)
    result = await post(
        client, headers, f"/irrigation-logs/{log['irrigation_id']}/response",
        {"post_irrigation_moisture": post_moisture, **flow}, expect=200,
    )
    return log["irrigation_id"], result["deviation"]


# ------------------------------------------------------------------ the 6.3 mapping table, row by row (pure rules)


def classify(flow, response_kwargs, z=-2.0, avg=None, cv=None, deviation=-8.0):
    return rules.classify(
        avg_flow_rate=avg, flow_cv=cv, expected_response=10.0, response_deviation=deviation, z=z, **response_kwargs
    )


NO_CHANGE = {"actual_response": 0.2, "post_moisture": 40.2, "lower": 45.0, "upper": 55.0}
BELOW = {"actual_response": 3.0, "post_moisture": 43.0, "lower": 45.0, "upper": 55.0}
EXPECTED = {"actual_response": 10.0, "post_moisture": 50.0, "lower": 45.0, "upper": 55.0}
EXCESSIVE = {"actual_response": 22.0, "post_moisture": 62.0, "lower": 45.0, "upper": 55.0}


@pytest.mark.parametrize(
    "avg,cv,response,flow_class,response_class,hypothesis",
    [
        (0.0, 0.0, NO_CHANGE, "no_flow", "no_change", "pump_tank_blockage"),
        (0.0, 0.0, BELOW, "no_flow", "below_expected", "pump_tank_blockage"),
        (1.2, 0.1, NO_CHANGE, "normal", "no_change", "distribution_sensor_media"),
        (1.2, 0.1, EXCESSIVE, "normal", "excessive", "leakage_or_sensor"),
        (1.0, 0.9, NO_CHANGE, "intermittent", "no_change", "valve_tubing_system"),
        (1.0, 0.9, BELOW, "intermittent", "below_expected", "valve_tubing_system"),
        (1.0, 0.9, EXCESSIVE, "intermittent", "excessive", "valve_tubing_system"),
        (1.2, 0.1, EXPECTED, "normal", "expected", "normal"),
        # "other combinations" -> unknown
        (1.2, 0.1, BELOW, "normal", "below_expected", "unknown"),
        (0.0, 0.0, EXCESSIVE, "no_flow", "excessive", "unknown"),
        (0.0, 0.0, EXPECTED, "no_flow", "expected", "unknown"),
        (1.0, 0.9, EXPECTED, "intermittent", "expected", "unknown"),
    ],
)
def test_mapping_table(avg, cv, response, flow_class, response_class, hypothesis):
    result = classify(None, response, avg=avg, cv=cv)
    assert (result.flow_class, result.response_class, result.fault_hypothesis) == (flow_class, response_class, hypothesis)
    assert result.detected_by == "rule"
    diagnostic, recovery = rules.ACTIONS[hypothesis]
    assert (result.diagnostic_action, result.recovery_action) == (diagnostic, recovery)


def test_flow_data_missing_means_normal_flow_with_lower_confidence():
    present = classify(None, NO_CHANGE, avg=1.2, cv=0.1)
    missing = classify(None, NO_CHANGE, avg=None, cv=None)
    assert missing.flow_class == "normal" and missing.flow_data_missing
    assert missing.fault_confidence == pytest.approx(present.fault_confidence - 0.2)


@pytest.mark.parametrize(
    "z,expected",
    [(-1.5, 0.7), (-3.0, 0.8)],
)
def test_confidence_rule(z, expected):
    assert classify(None, NO_CHANGE, z=z, avg=0.0, cv=0.0).fault_confidence == pytest.approx(expected)


def test_unknown_gets_low_confidence_and_confidence_is_clipped():
    assert classify(None, EXPECTED, avg=0.0, cv=0.0).fault_confidence == pytest.approx(0.3)
    assert classify(None, NO_CHANGE, z=-9, avg=0.0, cv=0.0).fault_confidence <= 0.9


# ------------------------------------------------------------------ end to end through the API


@pytest.mark.asyncio
async def test_no_flow_no_change_raises_a_pump_fault(client, auth_headers, test_db):
    _, dev = await link(client, auth_headers, PRE, avg_flow_rate=0.0, flow_cv=0.0)
    assert dev["flow_class"] == "no_flow" and dev["response_class"] == "no_change"
    assert dev["fault_hypothesis"] == "pump_tank_blockage"
    assert dev["is_anomaly"] and dev["z"] == pytest.approx(-2.0, abs=0.01)
    assert dev["severity"] == "warning"  # |z| = 2.0 is below the critical 2.5
    assert dev["detected_by"] == "rule"

    fault = dev["fault_event"]
    assert fault["fault_status"] == "active" and fault["fault_type"] == "response_anomaly"
    assert fault["fault_source"] == "pump"
    assert fault["fault_hypothesis"] == "pump_tank_blockage"
    assert fault["injected"] is False
    assert fault["sensor_value"] == PRE
    assert fault["expected_min"] < fault["expected_max"]
    assert fault["anomaly_score"] == pytest.approx(2.0, abs=0.01)
    assert fault["fault_probability"] == fault["fault_confidence"]
    assert fault["diagnostic_action"] == rules.ACTIONS["pump_tank_blockage"][0]
    assert fault["esp32_id"] == "unknown"  # no sensor data for this tray
    assert await test_db["fault_events"].count_documents({}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "post_moisture,flow,hypothesis,source",
    [
        (40.5, {"avg_flow_rate": 1.5, "flow_cv": 0.1}, "distribution_sensor_media", "sensor"),
        (62.0, {"avg_flow_rate": 1.5, "flow_cv": 0.1}, "leakage_or_sensor", "sensor"),
        (40.2, {"avg_flow_rate": 1.0, "flow_cv": 0.9}, "valve_tubing_system", "valve"),
        (43.0, {"avg_flow_rate": 0.0, "flow_cv": 0.0}, "pump_tank_blockage", "pump"),
        (62.0, {"avg_flow_rate": 0.0, "flow_cv": 0.0}, "unknown", "unknown"),
    ],
)
async def test_anomalous_responses_create_the_matching_fault(client, auth_headers, post_moisture, flow, hypothesis, source):
    _, dev = await link(client, auth_headers, post_moisture, **flow)
    assert dev["is_anomaly"]
    assert dev["fault_hypothesis"] == hypothesis
    assert dev["fault_event"]["fault_source"] == source


@pytest.mark.asyncio
async def test_expected_response_is_normal_and_creates_no_fault(client, auth_headers, test_db):
    _, dev = await link(client, auth_headers, 50.3, avg_flow_rate=1.5, flow_cv=0.1)
    assert dev["fault_hypothesis"] == "normal"
    assert dev["is_anomaly"] is False
    assert dev["fault_event"] is None
    assert await test_db["fault_events"].count_documents({}) == 0
    assert dev["diagnostic_action"] is None


@pytest.mark.asyncio
async def test_a_non_anomalous_deviation_creates_no_fault_even_with_a_fault_looking_class(client, auth_headers, test_db):
    # tiny volume: expected change ~0.7 %, measured 0.2 % -> classed "no_change" but |z| = 0.2/3 stays under 1
    log = await log_irrigation(client, auth_headers, pre_irrigation_moisture=PRE, water_volume=20.0)
    result = await post(
        client, auth_headers, f"/irrigation-logs/{log['irrigation_id']}/response",
        {"post_irrigation_moisture": PRE + 0.2, "avg_flow_rate": 1.5, "flow_cv": 0.1}, expect=200,
    )
    assert result["deviation"]["is_anomaly"] is False
    assert result["deviation"]["fault_event"] is None
    assert await test_db["fault_events"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_severity_escalates_above_the_critical_z(client, auth_headers, monkeypatch):
    _, warning = await link(client, auth_headers, PRE, avg_flow_rate=0.0, flow_cv=0.0)
    assert warning["severity"] == "warning"
    monkeypatch.setattr(settings, "deviation_critical_z", 1.5)
    _, critical = await link(client, auth_headers, PRE, avg_flow_rate=0.0, flow_cv=0.0)
    assert critical["severity"] == "critical"
    assert critical["fault_event"]["severity"] == "critical"
    assert critical["fault_confidence"] == pytest.approx(warning["fault_confidence"] + 0.1)


@pytest.mark.asyncio
async def test_missing_flow_data_lowers_confidence(client, auth_headers):
    _, with_flow = await link(client, auth_headers, PRE, avg_flow_rate=1.5, flow_cv=0.1)
    _, without_flow = await link(client, auth_headers, PRE)
    assert with_flow["fault_hypothesis"] == without_flow["fault_hypothesis"] == "distribution_sensor_media"
    assert without_flow["fault_confidence"] == pytest.approx(with_flow["fault_confidence"] - 0.2)


@pytest.mark.asyncio
async def test_evaluation_is_recorded_as_a_model_output(client, auth_headers, test_db):
    irrigation_id, dev = await link(client, auth_headers, PRE, avg_flow_rate=0.0, flow_cv=0.0)
    stored = await test_db["model_outputs"].find_one({"output_id": dev["model_output_id"]})
    assert stored["model_name"] == "response_deviation"
    assert stored["model_version"] == "rules-v0"
    assert stored["irrigation_id"] == irrigation_id
    assert stored["anomaly_score"] == pytest.approx(abs(dev["z"]))
    assert "pump_tank_blockage" in stored["recommendation_reason"]
    assert stored["recommended_action"] == rules.ACTIONS["pump_tank_blockage"][0]


@pytest.mark.asyncio
async def test_evaluate_endpoint_reruns_the_model(client, auth_headers):
    irrigation_id, first = await link(client, auth_headers, PRE, avg_flow_rate=0.0, flow_cv=0.0)
    again = await post(client, auth_headers, "/ml/response-deviation/evaluate", {"irrigation_id": irrigation_id}, expect=200)
    assert again["fault_hypothesis"] == first["fault_hypothesis"]
    assert again["z"] == pytest.approx(first["z"])


@pytest.mark.asyncio
async def test_evaluate_errors(client, auth_headers):
    unknown = await client.post(
        "/api/v1/ml/response-deviation/evaluate", json={"irrigation_id": "nope"}, headers=auth_headers
    )
    assert unknown.status_code == 404
    log = await log_irrigation(client, auth_headers)  # response never linked
    unlinked = await client.post(
        "/api/v1/ml/response-deviation/evaluate", json={"irrigation_id": log["irrigation_id"]}, headers=auth_headers
    )
    assert unlinked.status_code == 422


# ------------------------------------------------------------------ resolve endpoint


@pytest.mark.asyncio
async def test_resolve_sets_status_and_resolved_at(client, auth_headers, test_db):
    _, dev = await link(client, auth_headers, PRE, avg_flow_rate=0.0, flow_cv=0.0)
    fault_id = dev["fault_event"]["fault_id"]
    response = await client.patch(
        f"/api/v1/fault-events/{fault_id}/resolve",
        json={"resolution_reason": "Cleared the inlet line", "recovery_action": "Flushed", "recovery_success": True},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["fault_status"] == "resolved"
    assert body["resolved_at"] and body["resolution_reason"] == "Cleared the inlet line"
    assert body["recovery_action"] == "Flushed" and body["recovery_success"] is True

    stored = await test_db["fault_events"].find_one({"fault_id": fault_id})
    assert stored["fault_status"] == "resolved" and stored["resolved_at"] is not None


@pytest.mark.asyncio
async def test_resolve_errors(client, auth_headers):
    missing = await client.patch(
        "/api/v1/fault-events/nope/resolve", json={"resolution_reason": "x"}, headers=auth_headers
    )
    assert missing.status_code == 404
    _, dev = await link(client, auth_headers, PRE, avg_flow_rate=0.0, flow_cv=0.0)
    path = f"/api/v1/fault-events/{dev['fault_event']['fault_id']}/resolve"
    assert (await client.patch(path, json={"resolution_reason": "x"}, headers=auth_headers)).status_code == 200
    assert (await client.patch(path, json={"resolution_reason": "again"}, headers=auth_headers)).status_code == 409
    assert (await client.patch(path, json={}, headers=auth_headers)).status_code == 422


# ------------------------------------------------------------------ learned classifier hook


def examples(per_class=12):
    X, y = [], []
    for i in range(per_class):
        X.append(rules.classifier_features("no_flow", 0.0, 0.0, 0.1 * (i % 3), 10.0, -9.9, -2.0))
        y.append("pump_tank_blockage")
        X.append(rules.classifier_features("intermittent", 1.0, 0.9, 0.5 * (i % 3), 10.0, -9.5, -1.9))
        y.append("valve_tubing_system")
    return X, y


def test_classifier_training_refuses_too_few_examples_per_class():
    X, y = examples(per_class=9)
    with pytest.raises(ValueError, match="at least 10"):
        train_fault_classifier.train(X, y)


def test_classifier_training_refuses_a_single_class():
    X, y = examples()
    keep = [i for i, label in enumerate(y) if label == "pump_tank_blockage"]
    with pytest.raises(ValueError, match="at least 2"):
        train_fault_classifier.train([X[i] for i in keep], [y[i] for i in keep])


def test_trained_classifier_is_preferred_over_the_rules(tmp_path, monkeypatch):
    path = tmp_path / "clf.joblib"
    monkeypatch.setattr(settings, "fault_classifier_path", str(path))
    assert classify(None, NO_CHANGE, avg=0.0, cv=0.0, deviation=-9.9).detected_by == "rule"

    joblib.dump(train_fault_classifier.train(*examples()), path)
    result = classify(None, NO_CHANGE, avg=0.0, cv=0.0, deviation=-9.9)  # a vector like the training examples
    assert result.detected_by == "model"
    assert result.fault_hypothesis == "pump_tank_blockage"
    assert 0.1 <= result.fault_confidence <= 0.95
    assert result.diagnostic_action == rules.ACTIONS["pump_tank_blockage"][0]


@pytest.mark.asyncio
async def test_event_is_marked_detected_by_model_when_classifier_exists(client, auth_headers, tmp_path, monkeypatch):
    path = tmp_path / "clf.joblib"
    monkeypatch.setattr(settings, "fault_classifier_path", str(path))
    joblib.dump(train_fault_classifier.train(*examples()), path)
    _, dev = await link(client, auth_headers, PRE, avg_flow_rate=0.0, flow_cv=0.0)
    assert dev["detected_by"] == "model"
    assert dev["fault_event"]["detected_by"] == "model"
