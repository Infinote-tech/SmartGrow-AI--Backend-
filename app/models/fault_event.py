"""A detected fault or abnormal condition and what the system did about it."""
from datetime import datetime

from pydantic import BaseModel, Field


class FaultEventCreate(BaseModel):
    timestamp: datetime | None = None
    esp32_id: str = Field(min_length=1, max_length=120, description="Controller that detected the fault")
    tray_id: str | None = Field(default=None, description="Affected tray, if applicable")
    fault_type: str = Field(min_length=1, max_length=120)
    fault_source: str | None = Field(default=None, description="sensor / pump / valve / fan / power / communication")
    severity: str = Field(min_length=1, max_length=40, description="warning / critical")
    sensor_value: float | None = Field(default=None, description="Value that caused detection")
    expected_min: float | None = None
    expected_max: float | None = None
    anomaly_score: float | None = Field(default=None, description="TinyML anomaly score")
    fault_probability: float | None = Field(default=None, description="Model's estimated probability")
    detected_by: str | None = Field(default=None, description="threshold / tinyml / rule")
    recommended_action: str | None = None
    automatic_action: str | None = Field(default=None, description="What the system actually did")
    fault_status: str = Field(default="active", description="active / resolved")
    resolved_at: datetime | None = None
    resolution_reason: str | None = None


class FaultEventPublic(FaultEventCreate):
    fault_id: str
    created_at: str
