from datetime import date

from app.models.common import GenericDocument
from app.repositories.base import BaseRepository


class CropBatchRepository(BaseRepository[GenericDocument]):
    collection_name = "crop_batches"
    model = GenericDocument
    id_field = "batch_id"

    async def active_for_tray(self, tray_id: str, on_date: date) -> GenericDocument | None:
        """Latest batch planted on/before `on_date` in this tray that has not been harvested yet."""
        query = {"tray_id": tray_id, "harvest_date": None, "planting_date": {"$lte": on_date.isoformat()}}
        async for doc in self._collection.find(query).sort("planting_date", -1).limit(1):
            return self.model(**doc)
        return None
