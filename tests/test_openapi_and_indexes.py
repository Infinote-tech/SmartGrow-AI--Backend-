import pytest

from app.core.database import INDEXES, ensure_indexes
from app.main import app


@pytest.mark.asyncio
async def test_ensure_indexes_is_idempotent_and_creates_the_unique_ids(test_db):
    await ensure_indexes(test_db)
    await ensure_indexes(test_db)  # second run must not fail
    for collection in ("irrigation_logs", "model_outputs", "fault_events", "crop_batches"):
        names = (await test_db[collection].index_information()).keys()
        assert len(names) > 1  # _id plus ours
    assert any(unique for _, _, unique in INDEXES)


@pytest.mark.asyncio
async def test_a_failing_index_does_not_break_startup(test_db, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("index build failed")

    monkeypatch.setattr(type(test_db["sensor_data"]), "create_index", boom, raising=False)
    await ensure_indexes(test_db)  # logs, does not raise


def test_every_endpoint_is_documented_in_swagger():
    spec = app.openapi()
    declared_tags = {t["name"] for t in spec["tags"]}
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            assert operation.get("summary"), f"{method.upper()} {path} has no summary"
            if path.startswith("/api/v1") and "/auth/" not in path:
                assert operation.get("description"), f"{method.upper()} {path} has no description"
            assert set(operation.get("tags", [])) <= declared_tags | {"Health"}, f"{path} uses an undeclared tag"


def test_new_endpoints_are_present_in_swagger():
    paths = app.openapi()["paths"]
    for path, method in [
        ("/api/v1/ml/water-response/predict", "post"),
        ("/api/v1/irrigation-logs/{irrigation_id}/response", "post"),
        ("/api/v1/ml/response-deviation/evaluate", "post"),
        ("/api/v1/fault-events/{fault_id}/resolve", "patch"),
        ("/api/v1/policy/trays/{tray_id}/decide", "post"),
        ("/api/v1/policy/trays/{tray_id}/latest", "get"),
    ]:
        assert method in paths[path]


def test_field_descriptions_state_their_units():
    schemas = app.openapi()["components"]["schemas"]
    log = schemas["IrrigationLogCreate"]["properties"]
    assert "% VWC" in log["pre_irrigation_moisture"]["description"]
    assert "mL" in log["water_volume"]["description"]
    assert "L/min" in log["avg_flow_rate"]["description"]
    assert "seconds" in log["post_measured_after_s"]["description"]
    sensor = schemas["SensorDataCreate"]["properties"]
    assert "°C" in sensor["temperature"]["description"]
    assert "% RH" in sensor["humidity"]["description"]
    assert "lux" in sensor["light_intensity"]["description"]
