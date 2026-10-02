from app.models.common import GenericDocument
from app.repositories.base import BaseRepository


class CropBatchRepository(BaseRepository[GenericDocument]):
    collection_name = "crop_batches"
    model = GenericDocument
