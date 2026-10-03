from app.models.common import GenericDocument
from app.repositories.base import BaseRepository


class SensorDataRepository(BaseRepository[GenericDocument]):
    collection_name = "sensor_data"
    model = GenericDocument
    id_field = "sensor_data_id"
