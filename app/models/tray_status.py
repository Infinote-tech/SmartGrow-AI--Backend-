"""A snapshot of the three trays' status, seed types and media types."""
from datetime import datetime

from pydantic import BaseModel


class TrayStatusCreate(BaseModel):
    timestamp: datetime | None = None
    tray_1_status: str | None = None
    tray_2_status: str | None = None
    tray_3_status: str | None = None
    tray_1_seed_type: str | None = None
    tray_2_seed_type: str | None = None
    tray_3_seed_type: str | None = None
    tray_1_media_type: str | None = None
    tray_2_media_type: str | None = None
    tray_3_media_type: str | None = None


class TrayStatusPublic(TrayStatusCreate):
    tray_status_id: str
    created_at: str
