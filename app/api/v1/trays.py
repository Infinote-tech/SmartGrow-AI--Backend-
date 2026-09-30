from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_tray_service
from app.models.tray import TrayEntryCreate, TrayEntryPublic
from app.models.user import UserInDB
from app.services.tray_service import TrayService

router = APIRouter(prefix="/trays", tags=["Trays"])


@router.post("", response_model=TrayEntryPublic, status_code=201)
async def create_tray_entry(
    payload: TrayEntryCreate,
    tray_service: Annotated[TrayService, Depends(get_tray_service)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """Store one tray input entry for the logged-in user.

    Saved with the user's id (taken from the access token), seed type, substrate
    type, tray number, date and time. `date`/`time` default to the current UTC
    date/time when omitted.
    """
    entry = await tray_service.create_entry(payload, user_id=current_user.id)
    return TrayEntryPublic(**entry.model_dump())
