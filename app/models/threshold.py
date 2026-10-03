"""Optimal / warning / critical range for one parameter of a seed + media + growth stage."""
from datetime import datetime

from pydantic import BaseModel, Field


class ThresholdCreate(BaseModel):
    seed_type: str = Field(min_length=1, max_length=120, description="Seed the range applies to.")
    media_type: str = Field(min_length=1, max_length=120, description="Growing media the range applies to.")
    growth_stage: str = Field(
        min_length=1,
        max_length=120,
        description="germination / blackout / early_growth / active_growth / pre_harvest.",
    )
    parameter: str = Field(
        min_length=1,
        max_length=120,
        description=(
            "What is bounded, e.g. soil_moisture (% VWC), temperature (°C), humidity (% RH), light_intensity (lux). "
            "The Adaptive Irrigation Policy reads parameter = soil_moisture."
        ),
    )
    optimal_min: float | None = Field(default=None, description="Lower bound of the optimal band (parameter unit).")
    optimal_max: float | None = Field(default=None, description="Upper bound of the optimal band (parameter unit).")
    warning_min: float | None = Field(default=None, description="Below this the parameter is in warning.")
    warning_max: float | None = Field(default=None, description="Above this the parameter is in warning.")
    critical_min: float | None = Field(default=None, description="Below this the parameter is critical.")
    critical_max: float | None = Field(default=None, description="Above this the parameter is critical.")
    threshold_version: str | None = Field(default=None, description="Free-text version label, e.g. v1.")
    effective_from: datetime | None = Field(
        default=None, description="When this row starts to apply (UTC). The latest effective row wins."
    )


class ThresholdPublic(ThresholdCreate):
    threshold_id: str = Field(description="Generated id of this threshold row.")
    updated_at: datetime = Field(description="When the server stored the row (UTC).")
    created_at: datetime = Field(description="When the server stored the row (UTC).")
