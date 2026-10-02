from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_fault_event_repository
from app.api.v1.insert import insert_document
from app.models.fault_event import FaultEventCreate, FaultEventPublic
from app.models.user import UserInDB
from app.repositories.fault_event_repository import FaultEventRepository

router = APIRouter(prefix="/fault-events", tags=["Fault Event"])


@router.post("", response_model=FaultEventPublic, status_code=201)
async def create_fault_event(
    payload: FaultEventCreate,
    repo: Annotated[FaultEventRepository, Depends(get_fault_event_repository)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """A detected fault and the action taken. Insert-only: stored in the `fault_events` collection with a generated `fault_id`."""
    document = await insert_document(repo, payload, id_field="fault_id", timestamp_field="timestamp")
    return FaultEventPublic(**document.model_dump())
