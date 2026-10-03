from app.models.common import GenericDocument
from app.repositories.base import BaseRepository


class HardwareStatusRepository(BaseRepository[GenericDocument]):
    collection_name = "hardware_status"
    model = GenericDocument
    id_field = "hardware_status_id"
