from app.models.common import GenericDocument
from app.repositories.base import BaseRepository


class ThresholdRepository(BaseRepository[GenericDocument]):
    collection_name = "thresholds"
    model = GenericDocument
