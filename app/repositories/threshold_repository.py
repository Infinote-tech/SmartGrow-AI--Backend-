from datetime import datetime

from app.models.common import GenericDocument
from app.repositories.base import BaseRepository


class ThresholdRepository(BaseRepository[GenericDocument]):
    collection_name = "thresholds"
    model = GenericDocument
    id_field = "threshold_id"

    async def latest_matching(
        self, seed_type: str, media_type: str, growth_stage: str, parameter: str, at: datetime
    ) -> GenericDocument | None:
        """Newest threshold row for this seed + media + stage + parameter that is already effective at `at`."""
        query = {
            "seed_type": seed_type,
            "media_type": media_type,
            "growth_stage": growth_stage,
            "parameter": parameter,
            "$or": [{"effective_from": None}, {"effective_from": {"$lte": at}}],
        }
        async for doc in self._collection.find(query).sort([("effective_from", -1), ("_id", -1)]).limit(1):
            return self.model(**doc)
        return None
