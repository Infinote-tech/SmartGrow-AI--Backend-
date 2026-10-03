"""
Single shared Motor (async MongoDB) client for the whole app.
Collections are exposed as simple properties so repositories don't each
re-derive collection names.
"""
import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ConnectionFailure

from app.core.config import settings

logger = logging.getLogger(__name__)


class MongoDatabase:
    client: AsyncIOMotorClient | None = None
    db: AsyncIOMotorDatabase | None = None

    def connect(self) -> None:
        self.client = AsyncIOMotorClient(settings.mongo_uri, tz_aware=True)
        self.db = self.client[settings.mongo_db_name]

    def close(self) -> None:
        if self.client:
            self.client.close()

    def get_db(self) -> AsyncIOMotorDatabase:
        if self.db is None:
            self.connect()
        return self.db


mongo = MongoDatabase()


def get_database() -> AsyncIOMotorDatabase:
    """FastAPI dependency: yields the active Mongo database handle."""
    return mongo.get_db()


# (collection, keys, unique) -- idempotent: create_index is a no-op when the index already exists.
INDEXES: list[tuple[str, list[tuple[str, int]], bool]] = [
    ("sensor_data", [("tray_id", 1), ("timestamp", -1)], False),
    ("irrigation_logs", [("tray_id", 1), ("timestamp", -1)], False),
    ("irrigation_logs", [("irrigation_id", 1)], True),
    ("model_outputs", [("tray_id", 1), ("timestamp", -1)], False),
    ("model_outputs", [("output_id", 1)], True),
    ("model_outputs", [("model_name", 1), ("timestamp", -1)], False),
    ("fault_events", [("tray_id", 1), ("fault_status", 1)], False),
    ("fault_events", [("fault_id", 1)], True),
    ("thresholds", [("seed_type", 1), ("media_type", 1), ("growth_stage", 1), ("parameter", 1)], False),
    ("crop_batches", [("batch_id", 1)], True),
    ("crop_batches", [("tray_id", 1), ("planting_date", -1)], False),
]


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create the query/uniqueness indexes. Never raises: a failed index is logged, not fatal.

    If MongoDB is unreachable the remaining indexes are skipped (one timeout, not one per index).
    """
    for collection, keys, unique in INDEXES:
        try:
            await db[collection].create_index(keys, unique=unique)
        except ConnectionFailure:
            logger.warning("MongoDB is unreachable; skipping index creation (will retry on next start)")
            return
        except Exception:  # noqa: BLE001 - e.g. duplicate legacy data blocking a unique index
            logger.exception("Could not create index %s on %s", keys, collection)
