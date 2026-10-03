from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_threshold_repository
from app.api.v1.insert import insert_document
from app.models.threshold import ThresholdCreate, ThresholdPublic
from app.models.user import UserInDB
from app.repositories.threshold_repository import ThresholdRepository

router = APIRouter(prefix="/thresholds", tags=["Threshold"])


@router.post("", response_model=ThresholdPublic, status_code=201, summary="Store a threshold row")
async def create_threshold(
    payload: ThresholdCreate,
    repo: Annotated[ThresholdRepository, Depends(get_threshold_repository)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """Store the optimal / warning / critical range of one parameter for a seed + media + growth stage. The Adaptive
    Irrigation Policy reads the latest effective `soil_moisture` row (% VWC); without one it falls back to the
    configured defaults. Insert a new row (with a later `effective_from`) to change a range - rows are never edited.
    Stored in `thresholds` with a generated `threshold_id`.
    """
    document = await insert_document(repo, payload, id_field="threshold_id", timestamp_field="updated_at")
    return ThresholdPublic(**document.model_dump())
