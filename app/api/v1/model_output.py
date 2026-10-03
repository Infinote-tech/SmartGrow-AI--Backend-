from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_model_output_repository
from app.api.v1.insert import insert_document
from app.models.model_output import ModelOutputCreate, ModelOutputPublic
from app.models.user import UserInDB
from app.repositories.model_output_repository import ModelOutputRepository

router = APIRouter(prefix="/model-outputs", tags=["Model Output"])


@router.post("", response_model=ModelOutputPublic, status_code=201, summary="Store an AI/ML model result")
async def create_model_output(
    payload: ModelOutputCreate,
    repo: Annotated[ModelOutputRepository, Depends(get_model_output_repository)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """Store the result of any model (growth, anomaly, irrigation, ...). Models 1-3 write their own rows through their
    endpoints; use this one for results computed elsewhere, e.g. on-device TinyML. All Model 1-3 fields are optional
    (moisture in % VWC, volume in mL). Insert-only: stored in `model_outputs` with a generated `output_id`.
    """
    document = await insert_document(repo, payload, id_field="output_id", timestamp_field="timestamp")
    return ModelOutputPublic(**document.model_dump())
