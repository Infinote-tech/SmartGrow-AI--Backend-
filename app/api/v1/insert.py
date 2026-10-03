"""Shared insert-only plumbing for the data-collection endpoints."""
import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.common import DATETIME_FIELDS, GenericDocument, as_utc, utcnow
from app.repositories.base import BaseRepository


async def insert_document(
    repo: BaseRepository[GenericDocument],
    payload: BaseModel,
    id_field: str,
    timestamp_field: str | None,
) -> GenericDocument:
    """Store the validated payload with a generated business id and server-side timestamps.

    `timestamp_field` is taken from the client when it sent one (e.g. an ESP32 reading time),
    otherwise it is set to now (UTC). Datetime fields (`timestamp`, `created_at`, `resolved_at`,
    `effective_from`, `updated_at`) are stored as timezone-aware UTC BSON datetimes; naive client
    datetimes are treated as UTC.
    """
    now = utcnow()
    document = payload.model_dump(mode="json")
    for name in DATETIME_FIELDS:
        value = getattr(payload, name, None)
        if isinstance(value, datetime):
            document[name] = as_utc(value)
    document[id_field] = uuid.uuid4().hex
    if timestamp_field:
        document[timestamp_field] = document.get(timestamp_field) or now
    document["created_at"] = now
    return await repo.create(document)
