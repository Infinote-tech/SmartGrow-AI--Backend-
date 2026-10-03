"""One reading from an ESP32 for a tray."""
from datetime import datetime

from pydantic import BaseModel, Field


class SensorDataCreate(BaseModel):
    timestamp: datetime | None = Field(
        default=None, description="When the reading was taken (UTC). Defaults to the server time if omitted."
    )
    esp32_id: str = Field(min_length=1, max_length=120, description="Controller that produced the reading.")
    tray_id: str = Field(min_length=1, max_length=120, description="Tray the reading belongs to.")
    seed_type: str | None = Field(default=None, description="Seed grown in the tray, e.g. radish.")
    media_type: str | None = Field(default=None, description="Growing media, e.g. cocopeat.")
    temperature: float | None = Field(default=None, description="Air temperature, °C.")
    humidity: float | None = Field(default=None, description="Relative humidity, % RH.")
    soil_moisture: float | None = Field(
        default=None,
        description="Media moisture, % volumetric water content (0-100), already calibrated (never raw ADC).",
    )
    light_intensity: float | None = Field(default=None, description="Light level, lux.")
    water_level: float | None = Field(default=None, description="Reservoir level (recommended: % of tank capacity).")
    water_flow_rate: float | None = Field(default=None, description="Instantaneous water flow, L/min.")


class SensorDataPublic(SensorDataCreate):
    sensor_data_id: str = Field(description="Generated id of this reading.")
    created_at: datetime = Field(description="When the server stored the row (UTC).")
