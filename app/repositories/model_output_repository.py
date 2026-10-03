from app.models.common import GenericDocument
from app.repositories.base import BaseRepository


class ModelOutputRepository(BaseRepository[GenericDocument]):
    collection_name = "model_outputs"
    model = GenericDocument
    id_field = "output_id"
