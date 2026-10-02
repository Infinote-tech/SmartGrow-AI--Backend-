from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_sensor_data_repository
from app.api.v1.insert import insert_document
from app.models.sensor_data import SensorDataCreate, SensorDataPublic
from app.models.user import UserInDB
from app.repositories.sensor_data_repository import SensorDataRepository

router = APIRouter(prefix="/sensor-data", tags=["Sensor Data"])


@router.post("", response_model=SensorDataPublic, status_code=201)
async def create_sensor_data(
    payload: SensorDataCreate,
    repo: Annotated[SensorDataRepository, Depends(get_sensor_data_repository)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """One reading from an ESP32 for a tray. Insert-only: stored in the `sensor_data` collection with a generated `sensor_data_id`."""
    document = await insert_document(repo, payload, id_field="sensor_data_id", timestamp_field="timestamp")
    return SensorDataPublic(**document.model_dump())
