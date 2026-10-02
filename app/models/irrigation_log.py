"""One irrigation event."""
from datetime import datetime

from pydantic import BaseModel, Field


class IrrigationLogCreate(BaseModel):
    timestamp: datetime | None = None
    tray_id: str = Field(min_length=1, max_length=120)
    solenoid_id: str | None = None
    pump_status: str | None = None
    irrigation_duration: float | None = None
    water_consumed: float | None = None
    trigger_type: str | None = None
    trigger_reason: str | None = None
    ai_recommended: bool | None = None
    actual_action: str | None = None


class IrrigationLogPublic(IrrigationLogCreate):
    irrigation_id: str
    created_at: str
