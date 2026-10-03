"""A hardware health snapshot reported by an ESP32."""
from datetime import datetime

from pydantic import BaseModel, Field


class HardwareStatusCreate(BaseModel):
    timestamp: datetime | None = Field(default=None, description="When the snapshot was taken (UTC). Defaults to now.")
    esp32_id: str = Field(min_length=1, max_length=120, description="Controller reporting the status.")
    overall_system_status: str | None = Field(default=None, description="Overall health, e.g. ok / degraded / fault.")
    solenoid_1_status: str | None = Field(default=None, description="Valve 1 state, e.g. open / closed / fault.")
    solenoid_2_status: str | None = Field(default=None, description="Valve 2 state.")
    solenoid_3_status: str | None = Field(default=None, description="Valve 3 state.")
    fan_status: str | None = Field(default=None, description="Fan state, e.g. on / off / fault.")
    motor_status: str | None = Field(default=None, description="Motor state.")
    water_pump_status: str | None = Field(default=None, description="Pump state.")
    power_status: str | None = Field(default=None, description="Power supply state.")
    connectivity_status: str | None = Field(default=None, description="Network link state, e.g. online / offline.")


class HardwareStatusPublic(HardwareStatusCreate):
    hardware_status_id: str = Field(description="Generated id of this snapshot.")
    created_at: datetime = Field(description="When the server stored the row (UTC).")
