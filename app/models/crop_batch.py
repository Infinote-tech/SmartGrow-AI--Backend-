"""One planted batch, for traceability."""
from datetime import date

from pydantic import BaseModel, Field


class CropBatchCreate(BaseModel):
    seed_type: str = Field(min_length=1, max_length=120)
    media_type: str = Field(min_length=1, max_length=120)
    planting_date: date
    expected_harvest_date: date | None = None
    harvest_date: date | None = None
    seed_quantity: float | None = None
    tray_id: str = Field(min_length=1, max_length=120)
    batch_status: str | None = None


class CropBatchPublic(CropBatchCreate):
    batch_id: str
    created_at: str
