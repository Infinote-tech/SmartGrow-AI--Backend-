"""
Shared Mongo/Pydantic plumbing.

PyObjectId lets Pydantic v2 models accept and (de)serialise MongoDB's
ObjectId as a plain string, so API responses never leak a raw bson type.
"""
from datetime import UTC, datetime
from typing import Annotated, Any

from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _validate_object_id(value: Any) -> str:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, str) and ObjectId.is_valid(value):
        return value
    raise ValueError("Invalid ObjectId")


PyObjectId = Annotated[str, BeforeValidator(_validate_object_id)]


def utcnow() -> datetime:
    return datetime.now(UTC)


class MongoBaseModel(BaseModel):
    """Base for documents read back out of Mongo: adds `id` mapped from `_id`."""

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: PyObjectId = Field(alias="_id")


class GenericDocument(MongoBaseModel):
    """A stored document whose fields are defined by its request model (insert-only collections)."""

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True, extra="allow")
