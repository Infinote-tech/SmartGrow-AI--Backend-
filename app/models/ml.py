"""Request / result models for the Crop-Water Response, Response-Deviation and Adaptive Irrigation Policy endpoints."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import FaultHypothesis, FlowClass, GrowthStage, ResponseClass
from app.models.fault_event import FaultEventPublic
from app.models.irrigation_log import IrrigationLogPublic
from app.models.model_output import ModelOutputPublic


class WaterResponsePredictRequest(BaseModel):
    """Ask Model 1 how much the moisture of a tray will rise for a given irrigation volume."""

    tray_id: str = Field(min_length=1, max_length=120, description="Tray to predict for. Also a learned feature.")
    water_volume: float = Field(ge=0, description="Planned irrigation volume, mL.")
    batch_id: str | None = Field(
        default=None, description="Crop batch (batch_id). Defaults to the tray's active batch (not yet harvested)."
    )
    seed_type: str | None = Field(default=None, description="Overrides the batch's seed type.")
    media_type: str | None = Field(default=None, description="Overrides the batch's media type.")
    growth_stage: GrowthStage | None = Field(
        default=None, description="Overrides the stage derived from days after sowing."
    )
    pre_irrigation_moisture: float | None = Field(
        default=None, ge=0, le=100, description="Moisture now, % VWC (0-100). Defaults to the tray's latest reading."
    )
    temperature: float | None = Field(default=None, description="Air temperature, °C. Defaults to the latest reading.")
    humidity: float | None = Field(default=None, description="Relative humidity, % RH. Defaults to the latest reading.")
    light_intensity: float | None = Field(default=None, description="Light, lux. Defaults to the latest reading.")
    timestamp: datetime | None = Field(
        default=None, description="Event time (UTC); features are built as of this time. Defaults to now."
    )


class ResponseLinkRequest(BaseModel):
    """The measured result of an irrigation event, sent after the settling delay."""

    post_irrigation_moisture: float = Field(
        ge=0, le=100, description="Moisture measured after the valve closed, % VWC (0-100), calibrated."
    )
    post_measured_after_s: int | None = Field(
        default=None, ge=0, description="Settling delay used before this reading, seconds. Defaults to the server setting."
    )
    avg_flow_rate: float | None = Field(default=None, ge=0, description="Mean flow during the event, L/min.")
    flow_cv: float | None = Field(
        default=None, ge=0, description="Coefficient of variation of the flow during the event, unitless."
    )
    water_volume: float | None = Field(default=None, ge=0, description="Measured volume delivered, mL.")


class DeviationEvaluateRequest(BaseModel):
    irrigation_id: str = Field(min_length=1, description="Irrigation event (with a linked response) to evaluate.")


class DeviationResult(BaseModel):
    """What Model 2 concluded about one irrigation event."""

    irrigation_id: str
    tray_id: str
    response_deviation: float = Field(description="actual - expected moisture change, % points.")
    half_interval: float = Field(description="Normalising half-width of the expected interval, % points.")
    z: float = Field(description="response_deviation / half_interval, unitless.")
    is_anomaly: bool = Field(description="|z| above DEVIATION_ANOMALY_Z.")
    severity: str = Field(description="critical when |z| exceeds DEVIATION_CRITICAL_Z, otherwise warning.")
    flow_class: FlowClass
    response_class: ResponseClass
    fault_hypothesis: FaultHypothesis
    fault_confidence: float = Field(ge=0, le=1)
    diagnostic_action: str | None = None
    recovery_action: str | None = None
    detected_by: str = Field(description="rule (rules-v0) or model (trained classifier).")
    fault_event: FaultEventPublic | None = Field(
        default=None, description="Created only when the response is anomalous and the hypothesis is not normal."
    )
    model_output_id: str = Field(description="output_id of the response_deviation row that records this evaluation.")


class ResponseLinkResult(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    irrigation_log: IrrigationLogPublic
    model_output: ModelOutputPublic = Field(description="The Model 1 expectation this response was compared with.")
    deviation: DeviationResult


class FaultResolveRequest(BaseModel):
    resolution_reason: str = Field(min_length=1, description="Why the fault is considered resolved.")
    recovery_action: str | None = Field(default=None, description="What was done to recover.")
    recovery_success: bool | None = Field(default=None, description="Whether the recovery worked.")
