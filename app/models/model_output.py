"""One AI/ML model result for a tray."""
from datetime import date, datetime

from pydantic import BaseModel, Field


class ModelOutputCreate(BaseModel):
    timestamp: datetime | None = None
    tray_id: str = Field(min_length=1, max_length=120)
    model_name: str = Field(min_length=1, max_length=120)
    model_version: str | None = None
    growth_prediction: str | None = None
    stress_probability: float | None = None
    anomaly_score: float | None = None
    sensor_health_score: float | None = None
    predicted_soil_moisture: float | None = None
    predicted_harvest_date: date | None = None
    predicted_yield: float | None = None
    irrigation_recommendation: str | None = None
    recommended_action: str | None = None
    recommendation_confidence: float | None = None
    recommendation_reason: str | None = None


class ModelOutputPublic(ModelOutputCreate):
    output_id: str
    created_at: str
