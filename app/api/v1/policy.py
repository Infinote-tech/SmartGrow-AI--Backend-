from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_irrigation_policy_service
from app.core.exceptions import NotFoundError
from app.models.model_output import ModelOutputPublic
from app.models.user import UserInDB
from app.services.irrigation_policy_service import IrrigationPolicyService

router = APIRouter(prefix="/policy", tags=["Policy"])


@router.post(
    "/trays/{tray_id}/decide",
    response_model=ModelOutputPublic,
    status_code=201,
    summary="Run the adaptive irrigation policy for a tray (Model 3)",
)
async def decide(
    tray_id: str,
    service: Annotated[IrrigationPolicyService, Depends(get_irrigation_policy_service)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """Model 3: decide whether to irrigate the tray now and with how much water.

    Checks, in order: active faults (-> `hold_and_inspect`), minimum interval and daily volume limits (-> `wait`),
    the drying forecast (-> `wait` if the tray stays in the band), then simulates the candidate volumes through
    Model 1 and picks the smallest volume that reaches the target band. The result is stored as a `model_outputs` row
    (`model_name = adaptive_irrigation_policy`, `model_version = policy-v0`) with the full `candidate_evaluations`.
    **Recommendation only**: no hardware is actuated and no irrigation log is created.
    Returns 404 if the tray has no sensor data and 422 if the latest reading is older than 2 h.
    """
    document = await service.decide(tray_id)
    return ModelOutputPublic(**document.model_dump())


@router.get(
    "/trays/{tray_id}/latest",
    response_model=ModelOutputPublic,
    summary="Latest policy recommendation for a tray",
)
async def latest(
    tray_id: str,
    service: Annotated[IrrigationPolicyService, Depends(get_irrigation_policy_service)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """The most recent `adaptive_irrigation_policy` output stored for the tray. 404 if none exists yet."""
    document = await service.latest(tray_id)
    if document is None:
        raise NotFoundError("Policy decision for tray", tray_id)
    return ModelOutputPublic(**document.model_dump())
