"""Shared insert-only plumbing for the data-collection endpoints."""
import uuid

from pydantic import BaseModel

from app.models.common import GenericDocument, utcnow
from app.repositories.base import BaseRepository


async def insert_document(
    repo: BaseRepository[GenericDocument],
    payload: BaseModel,
    id_field: str,
    timestamp_field: str | None,
) -> GenericDocument:
    """Store the validated payload with a generated business id and server-side timestamps.

    `timestamp_field` is taken from the client when it sent one (e.g. an ESP32 reading time),
    otherwise it is set to now (UTC).
    """
    now = utcnow().isoformat()
    document = payload.model_dump(mode="json")
    document[id_field] = uuid.uuid4().hex
    if timestamp_field:
        document[timestamp_field] = document.get(timestamp_field) or now
    document["created_at"] = now
    return await repo.create(document)
