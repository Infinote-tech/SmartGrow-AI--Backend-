"""A tray input entry: one logged sowing record submitted by a logged-in user."""
from datetime import date as date_type
from datetime import time as time_type

from pydantic import BaseModel, Field

from app.models.common import MongoBaseModel, PyObjectId, utcnow


class TrayEntryCreate(BaseModel):
    """Body of POST /trays. `user_id` is never accepted here -- it comes from the JWT."""

    seed_type: str = Field(min_length=1, max_length=80, examples=["radish"])
    substrate_type: str = Field(min_length=1, max_length=80, examples=["cocopeat"])
    tray_number: int = Field(ge=1, examples=[1])
    date: date_type | None = Field(default=None, description="YYYY-MM-DD. Defaults to today (UTC).")
    time: time_type | None = Field(default=None, description="HH:MM[:SS]. Defaults to now (UTC).")


class TrayEntryInDB(MongoBaseModel):
    user_id: PyObjectId
    seed_type: str
    substrate_type: str
    tray_number: int
    date: str
    time: str
    created_at: str = Field(default_factory=lambda: utcnow().isoformat())


class TrayEntryPublic(BaseModel):
    id: PyObjectId
    user_id: PyObjectId
    seed_type: str
    substrate_type: str
    tray_number: int
    date: str
    time: str
