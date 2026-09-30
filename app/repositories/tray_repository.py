from app.models.tray import TrayEntryInDB
from app.repositories.base import BaseRepository


class TrayRepository(BaseRepository[TrayEntryInDB]):
    collection_name = "tray_entries"
    model = TrayEntryInDB
