from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_model_output_repository
from app.api.v1.insert import insert_document
from app.models.model_output import ModelOutputCreate, ModelOutputPublic
from app.models.user import UserInDB
from app.repositories.model_output_repository import ModelOutputRepository

router = APIRouter(prefix="/model-outputs", tags=["Model Output"])


@router.post("", response_model=ModelOutputPublic, status_code=201)
async def create_model_output(
    payload: ModelOutputCreate,
    repo: Annotated[ModelOutputRepository, Depends(get_model_output_repository)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """One AI/ML model result for a tray. Insert-only: stored in the `model_outputs` collection with a generated `output_id`."""
    document = await insert_document(repo, payload, id_field="output_id", timestamp_field="timestamp")
    return ModelOutputPublic(**document.model_dump())
