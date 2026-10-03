from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_crop_batch_repository, get_current_user
from app.api.v1.insert import insert_document
from app.models.crop_batch import CropBatchCreate, CropBatchPublic
from app.models.user import UserInDB
from app.repositories.crop_batch_repository import CropBatchRepository

router = APIRouter(prefix="/crop-batches", tags=["Crop Batch"])


@router.post("", response_model=CropBatchPublic, status_code=201, summary="Register a planted batch")
async def create_crop_batch(
    payload: CropBatchCreate,
    repo: Annotated[CropBatchRepository, Depends(get_crop_batch_repository)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """Register one planted batch (seed, media, planting date, tray). The growth stage used by the models is derived
    from the days after `planting_date`, and the batch without a `harvest_date` is the tray's active batch. Stored in
    `crop_batches` with a generated `batch_id`.
    """
    document = await insert_document(repo, payload, id_field="batch_id", timestamp_field=None)
    return CropBatchPublic(**document.model_dump())
