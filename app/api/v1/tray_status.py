from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_tray_status_repository
from app.api.v1.insert import insert_document
from app.models.tray_status import TrayStatusCreate, TrayStatusPublic
from app.models.user import UserInDB
from app.repositories.tray_status_repository import TrayStatusRepository

router = APIRouter(prefix="/tray-status", tags=["Tray Status"])


@router.post("", response_model=TrayStatusPublic, status_code=201, summary="Store a snapshot of all three trays")
async def create_tray_status(
    payload: TrayStatusCreate,
    repo: Annotated[TrayStatusRepository, Depends(get_tray_status_repository)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """Store the status, seed type and media type of trays 1-3 at one moment, for crop management dashboards.
    Insert-only: stored in `tray_status` with a generated `tray_status_id`.
    """
    document = await insert_document(repo, payload, id_field="tray_status_id", timestamp_field="timestamp")
    return TrayStatusPublic(**document.model_dump())
