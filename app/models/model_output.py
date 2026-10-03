"""One AI/ML model result for a tray (Crop-Water Response, Response-Deviation, Adaptive Irrigation Policy, ...)."""
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import GrowthStage


class ModelOutputCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    timestamp: datetime | None = Field(default=None, description="When the output was produced (UTC). Defaults to now.")
    tray_id: str = Field(min_length=1, max_length=120, description="Tray the output is about.")
    model_name: str = Field(
        min_length=1,
        max_length=120,
        description="crop_water_response / response_deviation / adaptive_irrigation_policy / your own model.",
    )
    model_version: str | None = Field(
        default=None, description="e.g. baseline-v0, gbr-q-2026-10-02, rules-v0, policy-v0."
    )
    growth_prediction: str | None = Field(default=None, description="Growth prediction label (growth model).")
    stress_probability: float | None = Field(default=None, description="Probability of crop stress, 0-1.")
    anomaly_score: float | None = Field(default=None, description="Anomaly score (Response-Deviation: |z|, unitless).")
    sensor_health_score: float | None = Field(default=None, description="Sensor health, 0-1.")
    predicted_soil_moisture: float | None = Field(
        default=None, description="Predicted moisture, % VWC. Model 1 stores the expected post-irrigation value here."
    )
    predicted_harvest_date: date | None = Field(default=None, description="Predicted harvest date (YYYY-MM-DD).")
    predicted_yield: float | None = Field(
        default=None, description="Predicted yield (use a consistent unit, e.g. grams)."
    )
    irrigation_recommendation: str | None = Field(
        default=None, description="Model 3: irrigate / wait / hold_and_inspect."
    )
    recommended_action: str | None = Field(default=None, description="Human-readable action.")
    recommendation_confidence: float | None = Field(default=None, description="Confidence in the recommendation, 0-1.")
    recommendation_reason: str | None = Field(
        default=None, description="Why; Model 3 uses semicolon-separated reason codes."
    )

    batch_id: str | None = Field(default=None, description="batch_id of the linked crop batch.")
    irrigation_id: str | None = Field(
        default=None, description="irrigation_id of the linked irrigation event, once known."
    )
    growth_stage: GrowthStage | None = Field(default=None, description="Growth stage used for the prediction.")
    input_features: dict[str, Any] | None = Field(
        default=None, description="Exact feature vector used (reproducibility). Units as in the feature names."
    )
    expected_moisture_change: float | None = Field(
        default=None, description="Model 1 median moisture change, % points."
    )
    expected_moisture_after_irrigation: float | None = Field(
        default=None, ge=0, le=100, description="Model 1 median post-irrigation moisture, % VWC (0-100)."
    )
    expected_moisture_lower: float | None = Field(
        default=None, ge=0, le=100, description="Lower bound of the prediction interval (10th percentile), % VWC."
    )
    expected_moisture_upper: float | None = Field(
        default=None, ge=0, le=100, description="Upper bound of the prediction interval (90th percentile), % VWC."
    )
    actual_moisture_after_irrigation: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Measured post-irrigation moisture, % VWC. Filled when the response is linked.",
    )
    response_error: float | None = Field(
        default=None, description="actual - expected moisture after irrigation, % points."
    )
    response_confidence: float | None = Field(default=None, ge=0, le=1, description="Model 1 confidence, 0-1.")
    water_response_score: float | None = Field(
        default=None, ge=0, le=1, description="How well the actual response matched the expectation, 0-1."
    )
    decision_volume_ml: float | None = Field(default=None, ge=0, description="Volume chosen by Model 3, mL.")
    candidate_evaluations: list[dict[str, Any]] | None = Field(
        default=None,
        description="Model 3: per candidate volume (mL): expected after / lower / upper (% VWC), accepted, reason.",
    )


class ModelOutputPublic(ModelOutputCreate):
    output_id: str = Field(description="Generated id of this output. Used to link irrigation logs.")
    created_at: datetime = Field(description="When the server stored the row (UTC).")
