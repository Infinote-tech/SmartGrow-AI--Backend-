from app.models.common import GenericDocument
from app.repositories.base import BaseRepository


class TrayStatusRepository(BaseRepository[GenericDocument]):
    collection_name = "tray_status"
    model = GenericDocument
    id_field = "tray_status_id"
