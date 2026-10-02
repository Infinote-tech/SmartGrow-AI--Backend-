"""Optimal / warning / critical range for one parameter of a seed + media + growth stage."""
from datetime import datetime

from pydantic import BaseModel, Field


class ThresholdCreate(BaseModel):
    seed_type: str = Field(min_length=1, max_length=120)
    media_type: str = Field(min_length=1, max_length=120)
    growth_stage: str = Field(min_length=1, max_length=120)
    parameter: str = Field(min_length=1, max_length=120)
    optimal_min: float | None = None
    optimal_max: float | None = None
    warning_min: float | None = None
    warning_max: float | None = None
    critical_min: float | None = None
    critical_max: float | None = None
    threshold_version: str | None = None
    effective_from: datetime | None = None


class ThresholdPublic(ThresholdCreate):
    threshold_id: str
    updated_at: datetime
    created_at: str
