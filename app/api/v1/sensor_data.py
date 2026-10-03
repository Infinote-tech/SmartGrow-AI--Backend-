from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_sensor_data_repository
from app.api.v1.insert import insert_document
from app.models.sensor_data import SensorDataCreate, SensorDataPublic
from app.models.user import UserInDB
from app.repositories.sensor_data_repository import SensorDataRepository

router = APIRouter(prefix="/sensor-data", tags=["Sensor Data"])


@router.post("", response_model=SensorDataPublic, status_code=201, summary="Store one ESP32 sensor reading")
async def create_sensor_data(
    payload: SensorDataCreate,
    repo: Annotated[SensorDataRepository, Depends(get_sensor_data_repository)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """Store one sensor reading for a tray: air temperature (°C), humidity (% RH), media moisture (% VWC, calibrated,
    never raw ADC), light (lux), reservoir level and flow (L/min). Sent by the ESP32 (or a gateway) every sampling
    interval. Model 1 and Model 3 read the latest reading per tray as their input. Insert-only: stored in the
    `sensor_data` collection with a generated `sensor_data_id`.
    """
    document = await insert_document(repo, payload, id_field="sensor_data_id", timestamp_field="timestamp")
    return SensorDataPublic(**document.model_dump())
