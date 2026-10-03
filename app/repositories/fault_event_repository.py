from app.models.common import GenericDocument
from app.repositories.base import BaseRepository


class FaultEventRepository(BaseRepository[GenericDocument]):
    collection_name = "fault_events"
    model = GenericDocument
    id_field = "fault_id"

    async def active_for_tray(self, tray_id: str) -> list[GenericDocument]:
        cursor = self._collection.find({"tray_id": tray_id, "fault_status": "active"}).sort("_id", -1)
        return [self.model(**doc) async for doc in cursor]
