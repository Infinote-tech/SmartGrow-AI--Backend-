from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_hardware_status_repository
from app.api.v1.insert import insert_document
from app.models.hardware_status import HardwareStatusCreate, HardwareStatusPublic
from app.models.user import UserInDB
from app.repositories.hardware_status_repository import HardwareStatusRepository

router = APIRouter(prefix="/hardware-status", tags=["Hardware Status"])


@router.post("", response_model=HardwareStatusPublic, status_code=201)
async def create_hardware_status(
    payload: HardwareStatusCreate,
    repo: Annotated[HardwareStatusRepository, Depends(get_hardware_status_repository)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """A hardware health snapshot reported by an ESP32. Insert-only: stored in the `hardware_status` collection with a generated `hardware_status_id`."""
    document = await insert_document(repo, payload, id_field="hardware_status_id", timestamp_field="timestamp")
    return HardwareStatusPublic(**document.model_dump())
