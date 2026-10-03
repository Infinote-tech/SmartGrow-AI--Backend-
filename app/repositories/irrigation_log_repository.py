from app.models.common import GenericDocument
from app.repositories.base import BaseRepository


class IrrigationLogRepository(BaseRepository[GenericDocument]):
    collection_name = "irrigation_logs"
    model = GenericDocument
    id_field = "irrigation_id"
