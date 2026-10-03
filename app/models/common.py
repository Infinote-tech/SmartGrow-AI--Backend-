"""
Shared Mongo/Pydantic plumbing.

PyObjectId lets Pydantic v2 models accept and (de)serialise MongoDB's
ObjectId as a plain string, so API responses never leak a raw bson type.
"""
from datetime import datetime, timezone
from typing import Annotated, Any

from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def _validate_object_id(value: Any) -> str:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, str) and ObjectId.is_valid(value):
        return value
    raise ValueError("Invalid ObjectId")


PyObjectId = Annotated[str, BeforeValidator(_validate_object_id)]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """Return `value` as a timezone-aware UTC datetime. Naive values are assumed to already be UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# Fields stored as BSON datetimes (UTC) in every collection that has them.
DATETIME_FIELDS = ("timestamp", "created_at", "resolved_at", "effective_from", "updated_at")


class MongoBaseModel(BaseModel):
    """Base for documents read back out of Mongo: adds `id` mapped from `_id`."""

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: PyObjectId = Field(alias="_id")


class GenericDocument(MongoBaseModel):
    """A stored document whose fields are defined by its request model (insert-only collections)."""

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True, extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _datetimes_to_utc(cls, data: Any) -> Any:
        # MongoDB returns naive datetimes (UTC); make them timezone-aware so they serialise with an offset.
        if isinstance(data, dict):
            for name in DATETIME_FIELDS:
                if isinstance(data.get(name), datetime):
                    data[name] = as_utc(data[name])
        return data
