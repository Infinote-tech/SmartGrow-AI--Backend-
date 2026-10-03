"""One planted batch, for traceability."""
from datetime import date, datetime

from pydantic import BaseModel, Field


class CropBatchCreate(BaseModel):
    seed_type: str = Field(min_length=1, max_length=120, description="Seed planted.")
    media_type: str = Field(min_length=1, max_length=120, description="Growing media used.")
    planting_date: date = Field(
        description="Sowing date (YYYY-MM-DD). The growth stage is derived from the days after this date."
    )
    expected_harvest_date: date | None = Field(default=None, description="Planned harvest date (YYYY-MM-DD).")
    harvest_date: date | None = Field(
        default=None, description="Actual harvest date (YYYY-MM-DD). Batches without it count as active."
    )
    seed_quantity: float | None = Field(default=None, description="Seed sown (use a consistent unit, e.g. grams).")
    tray_id: str = Field(min_length=1, max_length=120, description="Tray the batch is grown in.")
    batch_status: str | None = Field(default=None, description="e.g. planted / growing / harvested / failed.")


class CropBatchPublic(CropBatchCreate):
    batch_id: str = Field(description="Generated id of this batch. Used to link irrigation logs and model outputs.")
    created_at: datetime = Field(description="When the server stored the row (UTC).")
