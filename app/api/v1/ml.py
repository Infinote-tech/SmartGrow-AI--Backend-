from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_response_deviation_service, get_water_response_service
from app.models.ml import DeviationEvaluateRequest, DeviationResult, WaterResponsePredictRequest
from app.models.model_output import ModelOutputPublic
from app.models.user import UserInDB
from app.services.response_deviation_service import ResponseDeviationService
from app.services.water_response_service import WaterResponseService

router = APIRouter(prefix="/ml")


@router.post(
    "/water-response/predict",
    response_model=ModelOutputPublic,
    status_code=201,
    tags=["ML: Crop-Water Response"],
    summary="Predict the moisture response to an irrigation volume (Model 1)",
)
async def predict_water_response(
    payload: WaterResponsePredictRequest,
    service: Annotated[WaterResponseService, Depends(get_water_response_service)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """Model 1: how much will the media moisture (% VWC) rise if `water_volume` mL is delivered to the tray?

    Context that is not sent (moisture, temperature, humidity, light, batch, seed, media, growth stage) is resolved from
    the tray's latest `sensor_data` and active `crop_batches` row. The answer is the median expected moisture after
    irrigation plus a 10th-90th percentile interval and a confidence, stored as a `model_outputs` row
    (`model_name = crop_water_response`). Uses the trained model when its artifact exists, otherwise `baseline-v0`.
    Returns 422 if no moisture can be determined.
    """
    data = payload.model_dump(exclude={"tray_id", "water_volume"})
    document = await service.predict(payload.tray_id, water_volume=payload.water_volume, **data)
    return ModelOutputPublic(**document.model_dump())


@router.post(
    "/response-deviation/evaluate",
    response_model=DeviationResult,
    tags=["ML: Response Deviation"],
    summary="Evaluate an irrigation response for faults (Model 2)",
)
async def evaluate_response_deviation(
    payload: DeviationEvaluateRequest,
    service: Annotated[ResponseDeviationService, Depends(get_response_deviation_service)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    """Model 2: compare the measured moisture response of an irrigation event with Model 1's expectation.

    Stage A normalises the deviation by the prediction interval (`z`). Stage B explains an anomalous response from
    the flow pattern and the response class (`rules-v0`, or a trained classifier if present). When the response is
    anomalous and the cause is not `normal`, an active `fault_events` row is created. Also records a
    `response_deviation` row in `model_outputs`. The event must already have its response linked
    (`POST /irrigation-logs/{irrigation_id}/response`, which calls this automatically).
    """
    return await service.evaluate(payload.irrigation_id)
