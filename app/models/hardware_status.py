"""A hardware health snapshot reported by an ESP32."""
from datetime import datetime

from pydantic import BaseModel, Field


class HardwareStatusCreate(BaseModel):
    timestamp: datetime | None = None
    esp32_id: str = Field(min_length=1, max_length=120)
    overall_system_status: str | None = None
    solenoid_1_status: str | None = None
    solenoid_2_status: str | None = None
    solenoid_3_status: str | None = None
    fan_status: str | None = None
    motor_status: str | None = None
    water_pump_status: str | None = None
    power_status: str | None = None
    connectivity_status: str | None = None


class HardwareStatusPublic(HardwareStatusCreate):
    hardware_status_id: str
    created_at: str
