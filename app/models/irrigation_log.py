"""One irrigation event, including the measured moisture response."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import GrowthStage


class IrrigationLogCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    timestamp: datetime | None = Field(default=None, description="When irrigation started (UTC). Defaults to now.")
    tray_id: str = Field(min_length=1, max_length=120, description="Tray that was irrigated.")
    solenoid_id: str | None = Field(default=None, description="Valve that was opened.")
    pump_status: str | None = Field(default=None, description="Pump state during the event, e.g. on / off.")
    irrigation_duration: float | None = Field(default=None, description="How long water was delivered, seconds.")
    water_consumed: float | None = Field(default=None, description="Water used, mL (legacy field; prefer water_volume).")
    trigger_type: str | None = Field(default=None, description="What started the event, e.g. auto / manual / schedule.")
    trigger_reason: str | None = Field(default=None, description="Why it was started.")
    ai_recommended: bool | None = Field(default=None, description="Whether the AI policy recommended this irrigation.")
    actual_action: str | None = Field(default=None, description="What was actually done.")

    batch_id: str | None = Field(default=None, description="batch_id of the crop batch in this tray.")
    model_output_id: str | None = Field(
        default=None,
        description="output_id of the Model 3 decision / Model 1 prediction that produced this event.",
    )
    growth_stage: GrowthStage | None = Field(default=None, description="Growth stage at irrigation time.")
    pre_irrigation_moisture: float | None = Field(
        default=None, ge=0, le=100, description="Moisture immediately before irrigation, % VWC (0-100), calibrated."
    )
    post_irrigation_moisture: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Moisture measured post_measured_after_s seconds after the valve closed, % VWC (0-100).",
    )
    post_measured_after_s: int | None = Field(
        default=None, ge=0, description="Settling delay used for the post reading, seconds."
    )
    water_volume: float | None = Field(
        default=None, ge=0, description="Measured volume delivered, mL (from flow-pulse counting)."
    )
    avg_flow_rate: float | None = Field(default=None, ge=0, description="Mean flow during the event, L/min.")
    flow_cv: float | None = Field(
        default=None,
        ge=0,
        description="Coefficient of variation of flow during the event, unitless (intermittency indicator).",
    )
    expected_response: float | None = Field(
        default=None, description="Model 1 expected moisture change, % points. Filled by the response endpoint."
    )
    actual_response: float | None = Field(
        default=None,
        description=(
            "post_irrigation_moisture - pre_irrigation_moisture, % points. "
            "Server-computed by the response endpoint."
        ),
    )
    response_deviation: float | None = Field(
        default=None,
        description="actual_response - expected_response, % points. Server-computed by the response endpoint.",
    )


class IrrigationLogPublic(IrrigationLogCreate):
    irrigation_id: str = Field(description="Generated id of this event.")
    created_at: datetime = Field(description="When the server stored the row (UTC).")
