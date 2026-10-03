"""
Feature building for the Crop-Water Response model.

Pure functions over plain dicts so the API service and the offline training script build *identical*
features. Everything is computed "as of" the event time -- no future data leaks into a feature.

Units: moisture % VWC (0-100), volume mL, flow L/min, temperature °C, humidity % RH, light lux, time hours/days.
"""
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from app.models.common import as_utc

CATEGORICAL_FEATURES = ["seed_type", "media_type", "growth_stage", "tray_id"]
NUMERIC_FEATURES = [
    "pre_irrigation_moisture",
    "water_volume",
    "avg_flow_rate",
    "temperature",
    "humidity",
    "light_intensity",
    "hours_since_last_irrigation",
    "volume_last_24h_ml",
    "irrigations_last_24h",
    "days_after_sowing",
]
FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERIC_FEATURES

# (last day inclusive, stage); anything later is pre_harvest. Configurable by editing this table.
GROWTH_STAGE_BY_DAY: list[tuple[int, str]] = [
    (2, "germination"),
    (4, "blackout"),
    (7, "early_growth"),
    (11, "active_growth"),
]
LAST_STAGE = "pre_harvest"


def derive_growth_stage(days_after_sowing: int | None) -> str | None:
    """Day 0-2 germination, 3-4 blackout, 5-7 early_growth, 8-11 active_growth, >=12 pre_harvest."""
    if days_after_sowing is None or days_after_sowing < 0:
        return None
    for last_day, stage in GROWTH_STAGE_BY_DAY:
        if days_after_sowing <= last_day:
            return stage
    return LAST_STAGE


def days_after_sowing(planting_date: date | None, event_time: datetime) -> int | None:
    if planting_date is None:
        return None
    return (as_utc(event_time).date() - planting_date).days


def _volume_ml(irrigation: Mapping[str, Any]) -> float:
    return float(irrigation.get("water_volume") or irrigation.get("water_consumed") or 0.0)


def build_features(
    *,
    tray_id: str,
    event_time: datetime,
    water_volume: float | None,
    pre_irrigation_moisture: float | None,
    seed_type: str | None = None,
    media_type: str | None = None,
    growth_stage: str | None = None,
    avg_flow_rate: float | None = None,
    temperature: float | None = None,
    humidity: float | None = None,
    light_intensity: float | None = None,
    planting_date: date | None = None,
    prior_irrigations: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the model feature vector for one (possible) irrigation event.

    `prior_irrigations` are earlier irrigation_logs rows of the same tray (dicts with `timestamp` and
    `water_volume`/`water_consumed`); rows at or after `event_time` are ignored.
    """
    event_time = as_utc(event_time)
    prior = [row for row in prior_irrigations if row.get("timestamp") and as_utc(row["timestamp"]) < event_time]
    hours_since_last = None
    if prior:
        latest = max(as_utc(row["timestamp"]) for row in prior)
        hours_since_last = (event_time - latest).total_seconds() / 3600.0
    window_start = event_time - timedelta(hours=24)
    last_24h = [row for row in prior if as_utc(row["timestamp"]) >= window_start]

    days = days_after_sowing(planting_date, event_time)
    return {
        "seed_type": seed_type,
        "media_type": media_type,
        "growth_stage": growth_stage or derive_growth_stage(days),
        "tray_id": tray_id,
        "pre_irrigation_moisture": pre_irrigation_moisture,
        "water_volume": water_volume,
        "avg_flow_rate": avg_flow_rate,
        "temperature": temperature,
        "humidity": humidity,
        "light_intensity": light_intensity,
        "hours_since_last_irrigation": hours_since_last,
        "volume_last_24h_ml": sum(_volume_ml(row) for row in last_24h),
        "irrigations_last_24h": len(last_24h),
        "days_after_sowing": days,
    }
