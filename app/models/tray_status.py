"""A snapshot of the three trays' status, seed types and media types."""
from datetime import datetime

from pydantic import BaseModel, Field


class TrayStatusCreate(BaseModel):
    timestamp: datetime | None = Field(default=None, description="When the snapshot was taken (UTC). Defaults to now.")
    tray_1_status: str | None = Field(default=None, description="Tray 1 state, e.g. active / empty / harvested.")
    tray_2_status: str | None = Field(default=None, description="Tray 2 state.")
    tray_3_status: str | None = Field(default=None, description="Tray 3 state.")
    tray_1_seed_type: str | None = Field(default=None, description="Seed in tray 1.")
    tray_2_seed_type: str | None = Field(default=None, description="Seed in tray 2.")
    tray_3_seed_type: str | None = Field(default=None, description="Seed in tray 3.")
    tray_1_media_type: str | None = Field(default=None, description="Growing media in tray 1.")
    tray_2_media_type: str | None = Field(default=None, description="Growing media in tray 2.")
    tray_3_media_type: str | None = Field(default=None, description="Growing media in tray 3.")


class TrayStatusPublic(TrayStatusCreate):
    tray_status_id: str = Field(description="Generated id of this snapshot.")
    created_at: datetime = Field(description="When the server stored the row (UTC).")
