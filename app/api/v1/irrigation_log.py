from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_irrigation_log_repository
from app.api.v1.insert import insert_document
from app.models.irrigation_log import IrrigationLogCreate, IrrigationLogPublic
from app.models.user import UserInDB
from app.repositories.irrigation_log_repository import IrrigationLogRepository

router = APIRouter(prefix="/irrigation-logs", tags=["Irrigation Log"])


@router.post("", response_model=IrrigationLogPublic, status_code=201)
async def create_irrigation_log(
    payload: IrrigationLogCreate,
    repo: Annotated[IrrigationLogRepository, Depends(get_irrigation_log_repository)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """One irrigation event. Insert-only: stored in the `irrigation_logs` collection with a generated `irrigation_id`."""
    document = await insert_document(repo, payload, id_field="irrigation_id", timestamp_field="timestamp")
    return IrrigationLogPublic(**document.model_dump())
