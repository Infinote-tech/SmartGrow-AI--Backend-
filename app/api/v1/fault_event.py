from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_fault_event_repository, get_response_deviation_service
from app.api.v1.insert import insert_document
from app.models.fault_event import FaultEventCreate, FaultEventPublic
from app.models.ml import FaultResolveRequest
from app.models.user import UserInDB
from app.repositories.fault_event_repository import FaultEventRepository
from app.services.response_deviation_service import ResponseDeviationService

router = APIRouter(prefix="/fault-events", tags=["Fault Event"])


@router.post("", response_model=FaultEventPublic, status_code=201, summary="Store a fault event")
async def create_fault_event(
    payload: FaultEventCreate,
    repo: Annotated[FaultEventRepository, Depends(get_fault_event_repository)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """Store a detected fault and what was done about it. Model 2 creates `response_anomaly` events automatically; use
    this endpoint for faults detected elsewhere (threshold or TinyML on the ESP32) and for labelled fault-injection
    experiments (`injected = true`). Close one with `PATCH /fault-events/{fault_id}/resolve`. Stored in
    `fault_events` with a generated `fault_id`.
    """
    document = await insert_document(repo, payload, id_field="fault_id", timestamp_field="timestamp")
    return FaultEventPublic(**document.model_dump())


@router.patch(
    "/{fault_id}/resolve",
    response_model=FaultEventPublic,
    summary="Mark a fault event as resolved",
)
async def resolve_fault_event(
    fault_id: str,
    payload: FaultResolveRequest,
    service: Annotated[ResponseDeviationService, Depends(get_response_deviation_service)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """Set `fault_status = resolved` and `resolved_at = now`, with the reason and (optionally) the recovery taken.

    The only update path on `fault_events`. 404 for an unknown `fault_id`, 409 if it is already resolved.
    """
    document = await service.resolve(fault_id, payload)
    return FaultEventPublic(**document.model_dump())
