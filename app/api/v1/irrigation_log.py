from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_irrigation_log_repository, get_response_linker
from app.api.v1.insert import insert_document
from app.models.irrigation_log import IrrigationLogCreate, IrrigationLogPublic
from app.models.ml import ResponseLinkRequest, ResponseLinkResult
from app.models.user import UserInDB
from app.repositories.irrigation_log_repository import IrrigationLogRepository
from app.services.response_linker import ResponseLinker

router = APIRouter(prefix="/irrigation-logs", tags=["Irrigation Log"])


@router.post("", response_model=IrrigationLogPublic, status_code=201, summary="Log an irrigation event")
async def create_irrigation_log(
    payload: IrrigationLogCreate,
    repo: Annotated[IrrigationLogRepository, Depends(get_irrigation_log_repository)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """Log one irrigation event: when, which valve, how long (s), how much water (mL), why, and the moisture before (%
    VWC). Link it to a crop batch and, optionally, to the model output that recommended it. After the settling delay,
    report the measured result with `POST /irrigation-logs/{irrigation_id}/response`. Stored in `irrigation_logs`
    with a generated `irrigation_id`.
    """
    document = await insert_document(repo, payload, id_field="irrigation_id", timestamp_field="timestamp")
    return IrrigationLogPublic(**document.model_dump())


@router.post(
    "/{irrigation_id}/response",
    response_model=ResponseLinkResult,
    summary="Record the measured moisture response of an irrigation event",
)
async def link_response(
    irrigation_id: str,
    payload: ResponseLinkRequest,
    linker: Annotated[ResponseLinker, Depends(get_response_linker)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """Send the post-irrigation moisture (and measured flow) for an event that already has `pre_irrigation_moisture`.

    The server computes `actual_response = post - pre`, takes Model 1's expectation (from `model_output_id`, or by calling
    Model 1 now and storing the new output id on the log), sets `expected_response` and `response_deviation`, updates the
    linked `model_outputs` row (`actual_moisture_after_irrigation`, `response_error`, `water_response_score`) and runs
    the Response-Deviation model. This is the only way an irrigation log is updated.
    Returns 404 for an unknown `irrigation_id` and 422 when `pre_irrigation_moisture` is missing.
    """
    return await linker.link(irrigation_id, payload)
