from app.models.common import utcnow
from app.models.tray import TrayEntryCreate, TrayEntryInDB
from app.repositories.tray_repository import TrayRepository


class TrayService:
    def __init__(self, tray_repo: TrayRepository):
        self.tray_repo = tray_repo

    async def create_entry(self, payload: TrayEntryCreate, user_id: str) -> TrayEntryInDB:
        now = utcnow()
        entry_date = payload.date or now.date()
        entry_time = payload.time or now.time().replace(microsecond=0)
        document = {
            "user_id": user_id,
            "seed_type": payload.seed_type,
            "substrate_type": payload.substrate_type,
            "tray_number": payload.tray_number,
            "date": entry_date.isoformat(),
            "time": entry_time.isoformat(),
            "created_at": now.isoformat(),
        }
        return await self.tray_repo.create(document)
