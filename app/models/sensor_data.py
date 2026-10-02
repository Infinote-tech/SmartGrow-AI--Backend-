"""One reading from an ESP32 for a tray."""
from datetime import datetime

from pydantic import BaseModel, Field


class SensorDataCreate(BaseModel):
    timestamp: datetime | None = None
    esp32_id: str = Field(min_length=1, max_length=120)
    tray_id: str = Field(min_length=1, max_length=120)
    seed_type: str | None = None
    media_type: str | None = None
    temperature: float | None = None
    humidity: float | None = None
    soil_moisture: float | None = None
    light_intensity: float | None = None
    water_level: float | None = None
    water_flow_rate: float | None = None


class SensorDataPublic(SensorDataCreate):
    sensor_data_id: str
    created_at: str
