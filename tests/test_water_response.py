import random
import sys
from datetime import UTC, datetime, timedelta

import mongomock
import pytest

from app.core.config import settings
from app.ml.water_response import registry
from app.ml.water_response.baseline import BaselineWaterResponseModel
from app.ml.water_response.features import FEATURE_COLUMNS, build_features, derive_growth_stage
from app.ml.water_response.trained import TrainedWaterResponseModel, save_artifact, train_model
from scripts import train_water_response
from tests.helpers import log_irrigation, now_utc, post, seed_tray


def baseline() -> BaselineWaterResponseModel:
    return BaselineWaterResponseModel(saturation=70.0, gain_per_100ml=8.0)


def predict(model, pre, volume):
    return model.predict({"pre_irrigation_moisture": pre, "water_volume": volume})


# ------------------------------------------------------------------ baseline


def test_baseline_gain_shrinks_as_pre_moisture_approaches_saturation():
    model = baseline()
    gains = [predict(model, pre, 100).expected_change for pre in (10, 30, 50, 65)]
    assert gains == sorted(gains, reverse=True)
    assert gains[0] > gains[-1] > 0


def test_baseline_never_exceeds_saturation():
    model = baseline()
    for pre in (0, 30, 60, 69):
        for volume in (50, 200, 5000):
            assert predict(model, pre, volume).expected_after <= 70.0


def test_baseline_zero_volume_means_no_change():
    prediction = predict(baseline(), 40, 0)
    assert prediction.expected_change == 0
    assert prediction.expected_after == 40


def test_baseline_interval_contains_expectation_and_stays_in_range():
    for pre, volume in [(0, 0), (40, 100), (69, 300), (10, 5000)]:
        p = predict(baseline(), pre, volume)
        assert 0 <= p.lower <= p.expected_after <= p.upper <= 100
        assert p.confidence == 0.3
        assert p.model_version == "baseline-v0"


def test_baseline_matches_the_documented_formula():
    p = predict(baseline(), 40, 100)
    gain = 8.0 * 1.0 * (30 / 70)
    assert p.expected_after == pytest.approx(40 + gain)
    assert p.lower == pytest.approx(40 + gain - 3.0)
    assert p.upper == pytest.approx(40 + gain + 3.0)


def test_baseline_requires_moisture_and_volume():
    with pytest.raises(ValueError):
        baseline().predict({"pre_irrigation_moisture": None, "water_volume": 100})


# ------------------------------------------------------------------ features


@pytest.mark.parametrize(
    "day,stage",
    [(0, "germination"), (2, "germination"), (3, "blackout"), (4, "blackout"), (5, "early_growth"), (7, "early_growth"),
     (8, "active_growth"), (11, "active_growth"), (12, "pre_harvest"), (30, "pre_harvest")],
)
def test_growth_stage_derivation(day, stage):
    assert derive_growth_stage(day) == stage


def test_growth_stage_unknown_without_planting_date():
    assert derive_growth_stage(None) is None
    assert derive_growth_stage(-1) is None


def test_features_only_use_the_past():
    event = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    prior = [
        {"timestamp": event - timedelta(hours=2), "water_volume": 100},
        {"timestamp": event - timedelta(hours=30), "water_consumed": 80},  # outside 24 h
        {"timestamp": event + timedelta(hours=1), "water_volume": 999},  # future: ignored
    ]
    f = build_features(
        tray_id="t", event_time=event, water_volume=100, pre_irrigation_moisture=40, prior_irrigations=prior
    )
    assert f["hours_since_last_irrigation"] == pytest.approx(2.0)
    assert f["volume_last_24h_ml"] == 100
    assert f["irrigations_last_24h"] == 1
    assert set(FEATURE_COLUMNS) == set(f)


# ------------------------------------------------------------------ endpoint (baseline)


@pytest.mark.asyncio
async def test_predict_endpoint_stores_baseline_output(client, auth_headers, test_db):
    batch = await seed_tray(client, auth_headers, moisture=40.0)
    body = await post(
        client, auth_headers, "/ml/water-response/predict", {"tray_id": "tray-1", "water_volume": 100}
    )
    assert body["model_name"] == "crop_water_response"
    assert body["model_version"] == "baseline-v0"
    assert body["batch_id"] == batch["batch_id"]
    assert body["growth_stage"] == "early_growth"
    assert body["input_features"]["pre_irrigation_moisture"] == 40.0  # resolved from the latest reading
    assert body["input_features"]["seed_type"] == "radish"
    assert body["expected_moisture_lower"] <= body["expected_moisture_after_irrigation"] <= body["expected_moisture_upper"]
    assert body["predicted_soil_moisture"] == body["expected_moisture_after_irrigation"]
    assert body["response_confidence"] == 0.3

    stored = await test_db["model_outputs"].find_one({"output_id": body["output_id"]})
    assert stored["model_name"] == "crop_water_response"
    assert isinstance(stored["created_at"], datetime)


@pytest.mark.asyncio
async def test_predict_endpoint_422_without_any_moisture(client, auth_headers):
    response = await client.post(
        "/api/v1/ml/water-response/predict", json={"tray_id": "empty-tray", "water_volume": 100}, headers=auth_headers
    )
    assert response.status_code == 422
    assert "moisture" in response.json()["detail"]


@pytest.mark.asyncio
async def test_predict_endpoint_accepts_overrides_and_unknown_batch_is_404(client, auth_headers):
    body = await post(
        client,
        auth_headers,
        "/ml/water-response/predict",
        {"tray_id": "t9", "water_volume": 50, "pre_irrigation_moisture": 30, "growth_stage": "blackout",
         "seed_type": "pea", "media_type": "compost"},
    )
    assert body["growth_stage"] == "blackout"
    assert body["input_features"]["seed_type"] == "pea"

    missing = await client.post(
        "/api/v1/ml/water-response/predict",
        json={"tray_id": "t9", "water_volume": 50, "pre_irrigation_moisture": 30, "batch_id": "nope"},
        headers=auth_headers,
    )
    assert missing.status_code == 404


# ------------------------------------------------------------------ trained model


def synthetic_rows(n_batches=10, per_batch=6, seed=0):
    rng = random.Random(seed)
    rows, groups = [], []
    for b in range(n_batches):
        for _ in range(per_batch):
            pre = rng.uniform(20, 55)
            volume = rng.choice([50, 100, 150, 200])
            change = 0.06 * volume * (1 - pre / 70) + rng.gauss(0, 0.5)
            rows.append(
                {**build_tray_features(pre, volume, f"tray-{b % 3}"), "actual_response": change, "timestamp": now_utc()}
            )
            groups.append(f"batch-{b}")
    return rows, groups


def build_tray_features(pre, volume, tray):
    return build_features(
        tray_id=tray,
        event_time=now_utc(),
        water_volume=volume,
        pre_irrigation_moisture=pre,
        seed_type="radish",
        media_type="cocopeat",
        growth_stage="early_growth",
        temperature=25.0,
        humidity=60.0,
        light_intensity=10000,
    )


def test_train_model_reports_metrics_and_saves_artifact(tmp_path):
    rows, groups = synthetic_rows()
    artifact, metrics = train_model(rows, groups)
    assert artifact["model_version"].startswith("gbr-q-")
    assert artifact["n_rows"] == len(rows)
    assert {"mae", "rmse", "interval_coverage"} <= set(metrics)
    assert metrics["mae"] < 3.0  # learned something from clean synthetic data
    assert set(artifact["feature_columns"]) == set(FEATURE_COLUMNS)

    path = tmp_path / "wr.joblib"
    save_artifact(artifact, path)
    assert path.is_file()


def test_train_model_needs_at_least_two_groups():
    rows, _ = synthetic_rows(n_batches=1)
    with pytest.raises(ValueError, match="2 distinct groups"):
        train_model(rows, ["only-one"] * len(rows))


def test_registry_loads_trained_artifact_when_present(tmp_path, monkeypatch):
    path = tmp_path / "wr.joblib"
    monkeypatch.setattr(settings, "water_response_model_path", str(path))
    assert isinstance(registry.get_model(), BaselineWaterResponseModel)  # nothing there yet

    artifact, _ = train_model(*synthetic_rows())
    save_artifact(artifact, path)
    model = registry.get_model()
    assert isinstance(model, TrainedWaterResponseModel)
    assert model.model_version.startswith("gbr-q-")

    p = model.predict(build_tray_features(30, 100, "tray-1"))
    assert 0 <= p.lower <= p.expected_after <= p.upper <= 100
    assert 0.05 <= p.confidence <= 0.95
    assert p.model_version == model.model_version


def test_registry_falls_back_to_baseline_for_a_corrupt_artifact(tmp_path, monkeypatch):
    path = tmp_path / "bad.joblib"
    path.write_bytes(b"not a joblib file")
    monkeypatch.setattr(settings, "water_response_model_path", str(path))
    assert isinstance(registry.get_model(), BaselineWaterResponseModel)


@pytest.mark.asyncio
async def test_endpoint_uses_trained_model_once_artifact_exists(client, auth_headers, tmp_path, monkeypatch):
    path = tmp_path / "wr.joblib"
    save_artifact(train_model(*synthetic_rows())[0], path)
    monkeypatch.setattr(settings, "water_response_model_path", str(path))
    await seed_tray(client, auth_headers, moisture=35.0)
    body = await post(client, auth_headers, "/ml/water-response/predict", {"tray_id": "tray-1", "water_volume": 100})
    assert body["model_version"].startswith("gbr-q-")


# ------------------------------------------------------------------ training script


def mongo_with_events(n_events: int, faulty: int = 0):
    db = mongomock.MongoClient()["smartgrow_test"]
    base = now_utc() - timedelta(days=30)
    db.crop_batches.insert_one(
        {"batch_id": "b1", "tray_id": "tray-1", "seed_type": "radish", "media_type": "cocopeat",
         "planting_date": (base.date()).isoformat(), "harvest_date": None}
    )
    for i in range(n_events):
        when = base + timedelta(hours=6 * i)
        db.irrigation_logs.insert_one(
            {"irrigation_id": f"i{i}", "tray_id": "tray-1", "batch_id": f"b{i % 5}", "timestamp": when,
             "pre_irrigation_moisture": 35.0 + (i % 7), "post_irrigation_moisture": 40.0 + (i % 7),
             "water_volume": 100.0}
        )
    for i in range(faulty):
        db.fault_events.insert_one(
            {"fault_id": f"f{i}", "irrigation_id": f"i{i}", "fault_hypothesis": "pump_tank_blockage", "injected": False}
        )
    return db


def test_training_rows_exclude_faulty_events_and_use_past_only():
    db = mongo_with_events(10, faulty=3)
    rows, groups = train_water_response.build_training_rows(db)
    assert len(rows) == 7 and len(groups) == 7
    assert all(row["actual_response"] == 5.0 for row in rows)
    # first usable event is i3: history is i0..i2 (6 h apart, faulty ones still count as history), never i4+
    assert rows[0]["hours_since_last_irrigation"] == pytest.approx(6.0)
    assert rows[0]["irrigations_last_24h"] == 3


def test_training_script_refuses_below_minimum_rows(monkeypatch, capsys):
    db = mongo_with_events(settings.water_response_min_training_rows - 1)
    monkeypatch.setattr(train_water_response, "MongoClient", lambda *a, **k: {settings.mongo_db_name: db})
    monkeypatch.setattr(sys, "argv", ["train_water_response.py", "--dry-run"])
    assert train_water_response.main() == 1
    assert "Refusing to train" in capsys.readouterr().err


def test_training_script_trains_with_enough_rows(monkeypatch, capsys, tmp_path):
    db = mongo_with_events(settings.water_response_min_training_rows + 10)
    monkeypatch.setattr(train_water_response, "MongoClient", lambda *a, **k: {settings.mongo_db_name: db})
    out = tmp_path / "out.joblib"
    monkeypatch.setattr(sys, "argv", ["train_water_response.py", "--out", str(out)])
    assert train_water_response.main() == 0
    assert out.is_file()
    assert "Interval coverage" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_log_helper_roundtrip(client, auth_headers):
    log = await log_irrigation(client, auth_headers)
    assert log["irrigation_id"]
