"""A detected fault or abnormal condition and what the system did about it."""
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import FaultHypothesis, FlowClass, ResponseClass


class FaultEventCreate(BaseModel):
    timestamp: datetime | None = Field(default=None, description="When the fault was detected (UTC). Defaults to now.")
    esp32_id: str = Field(min_length=1, max_length=120, description="Controller that detected the fault.")
    tray_id: str | None = Field(default=None, description="Affected tray, if applicable.")
    fault_type: str = Field(min_length=1, max_length=120, description="Type of fault, e.g. response_anomaly.")
    fault_source: str | None = Field(default=None, description="sensor / pump / valve / fan / power / communication.")
    severity: str = Field(min_length=1, max_length=40, description="warning / critical.")
    sensor_value: float | None = Field(default=None, description="Value that caused detection (parameter unit).")
    expected_min: float | None = Field(default=None, description="Expected lower limit (same unit as sensor_value).")
    expected_max: float | None = Field(default=None, description="Expected upper limit (same unit as sensor_value).")
    anomaly_score: float | None = Field(default=None, description="Anomaly score (TinyML score or |z|), unitless.")
    fault_probability: float | None = Field(default=None, description="Model's estimated probability, 0-1.")
    detected_by: str | None = Field(default=None, description="threshold / tinyml / rule / model.")
    recommended_action: str | None = Field(default=None, description="What should happen.")
    automatic_action: str | None = Field(default=None, description="What the system actually did.")
    fault_status: str = Field(default="active", description="active / resolved.")
    resolved_at: datetime | None = Field(default=None, description="When resolved (UTC).")
    resolution_reason: str | None = Field(default=None, description="Why it was resolved.")

    irrigation_id: str | None = Field(default=None, description="Irrigation event that triggered the evaluation.")
    response_deviation: float | None = Field(
        default=None, description="Deviation that triggered the event, % points (actual - expected moisture change)."
    )
    fault_hypothesis: FaultHypothesis | None = Field(default=None, description="Most likely cause.")
    fault_confidence: float | None = Field(default=None, ge=0, le=1, description="Confidence in the hypothesis, 0-1.")
    flow_class: FlowClass | None = Field(default=None, description="Classified flow pattern.")
    response_class: ResponseClass | None = Field(default=None, description="Classified moisture response.")
    diagnostic_action: str | None = Field(default=None, description="Recommended check for the grower.")
    recovery_action: str | None = Field(default=None, description="Recommended or executed recovery step.")
    recovery_success: bool | None = Field(default=None, description="Outcome of recovery, once known.")
    injected: bool = Field(
        default=False, description="True for deliberate fault-injection experiments (labels for training)."
    )


class FaultEventPublic(FaultEventCreate):
    fault_id: str = Field(description="Generated id of this fault.")
    created_at: datetime = Field(description="When the server stored the row (UTC).")
