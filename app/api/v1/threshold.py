from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_threshold_repository
from app.api.v1.insert import insert_document
from app.models.threshold import ThresholdCreate, ThresholdPublic
from app.models.user import UserInDB
from app.repositories.threshold_repository import ThresholdRepository

router = APIRouter(prefix="/thresholds", tags=["Threshold"])


@router.post("", response_model=ThresholdPublic, status_code=201)
async def create_threshold(
    payload: ThresholdCreate,
    repo: Annotated[ThresholdRepository, Depends(get_threshold_repository)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """Optimal / warning / critical range for one parameter of a seed + media + growth stage. Insert-only: stored in the `thresholds` collection with a generated `threshold_id`."""
    document = await insert_document(repo, payload, id_field="threshold_id", timestamp_field="updated_at")
    return ThresholdPublic(**document.model_dump())
