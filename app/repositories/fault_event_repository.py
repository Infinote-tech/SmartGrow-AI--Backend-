from app.models.common import GenericDocument
from app.repositories.base import BaseRepository


class FaultEventRepository(BaseRepository[GenericDocument]):
    collection_name = "fault_events"
    model = GenericDocument
