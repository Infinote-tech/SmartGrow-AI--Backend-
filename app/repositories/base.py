"""
Generic async repository wrapping a single Mongo collection.

Concrete repositories subclass this and add domain-specific queries; the
common create/get/list/update/delete plumbing lives here exactly once.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class BaseRepository(Generic[ModelT]):
    collection_name: str
    model: type[ModelT]
    id_field: str | None = None  # business id field (e.g. irrigation_id) used by the *_business_id helpers

    def __init__(self, db: AsyncIOMotorDatabase):
        self._collection: AsyncIOMotorCollection = db[self.collection_name]

    @staticmethod
    def _to_object_id(id_str: str) -> ObjectId | None:
        return ObjectId(id_str) if ObjectId.is_valid(id_str) else None

    async def create(self, document: dict[str, Any]) -> ModelT:
        result = await self._collection.insert_one(document)
        created = await self._collection.find_one({"_id": result.inserted_id})
        return self.model(**created)

    async def get_by_id(self, id_str: str) -> ModelT | None:
        oid = self._to_object_id(id_str)
        if oid is None:
            return None
        doc = await self._collection.find_one({"_id": oid})
        return self.model(**doc) if doc else None

    async def find_one(self, query: dict[str, Any]) -> ModelT | None:
        doc = await self._collection.find_one(query)
        return self.model(**doc) if doc else None

    async def list(self, query: dict[str, Any] | None = None, skip: int = 0, limit: int = 50) -> list[ModelT]:
        cursor = self._collection.find(query or {}).sort("_id", -1).skip(skip).limit(limit)
        return [self.model(**doc) async for doc in cursor]

    async def update(self, id_str: str, updates: dict[str, Any]) -> ModelT | None:
        oid = self._to_object_id(id_str)
        if oid is None or not updates:
            return await self.get_by_id(id_str)
        await self._collection.update_one({"_id": oid}, {"$set": updates})
        return await self.get_by_id(id_str)

    async def delete(self, id_str: str) -> bool:
        oid = self._to_object_id(id_str)
        if oid is None:
            return False
        result = await self._collection.delete_one({"_id": oid})
        return result.deleted_count == 1

    async def count(self, query: dict[str, Any] | None = None) -> int:
        return await self._collection.count_documents(query or {})

    # --- business-id / time-window helpers (used by the ML services) -------------------------

    async def find_by_business_id(self, value: str) -> ModelT | None:
        """Look a document up by its generated business id (e.g. irrigation_id), not the Mongo _id."""
        return await self.find_one({self.id_field: value})

    async def update_by_business_id(self, value: str, updates: dict[str, Any]) -> ModelT | None:
        """Targeted $set on the document with this business id. Returns the updated document."""
        if updates:
            await self._collection.update_one({self.id_field: value}, {"$set": updates})
        return await self.find_by_business_id(value)

    async def latest_for_tray(
        self,
        tray_id: str,
        *,
        extra_query: dict[str, Any] | None = None,
        at_or_before: datetime | None = None,
        sort_field: str = "timestamp",
    ) -> ModelT | None:
        """Newest document for a tray (optionally only at/before a time and matching extra filters)."""
        query: dict[str, Any] = {"tray_id": tray_id, **(extra_query or {})}
        if at_or_before is not None:
            query[sort_field] = {"$lte": at_or_before}
        cursor = self._collection.find(query).sort(sort_field, -1).limit(1)
        async for doc in cursor:
            return self.model(**doc)
        return None

    async def list_for_tray_since(
        self,
        tray_id: str,
        since: datetime,
        until: datetime | None = None,
        *,
        limit: int = 1000,
        sort_field: str = "timestamp",
    ) -> list[ModelT]:
        """Documents for a tray with since <= timestamp < until, newest first."""
        window: dict[str, Any] = {"$gte": since}
        if until is not None:
            window["$lt"] = until
        cursor = self._collection.find({"tray_id": tray_id, sort_field: window}).sort(sort_field, -1).limit(limit)
        return [self.model(**doc) async for doc in cursor]
