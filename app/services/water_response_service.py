"""
Model 1 service: gathers the context of a tray (batch, latest sensors, recent irrigations), builds the feature
vector, asks the registry's model for the expected post-irrigation moisture, and stores the result as a
`model_outputs` row (`model_name = "crop_water_response"`).
"""
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.v1.insert import insert_document
from app.core.exceptions import NotFoundError, UnprocessableError
from app.ml.water_response.features import build_features
from app.ml.water_response.prediction import Prediction
from app.ml.water_response.registry import get_model
from app.models.common import GenericDocument, as_utc, utcnow
from app.models.model_output import ModelOutputCreate
from app.repositories.crop_batch_repository import CropBatchRepository
from app.repositories.irrigation_log_repository import IrrigationLogRepository
from app.repositories.model_output_repository import ModelOutputRepository
from app.repositories.sensor_data_repository import SensorDataRepository

MODEL_NAME = "crop_water_response"
HISTORY_DAYS = 7  # how far back prior irrigations are fetched (features only use the last 24 h plus "hours since last")


class WaterResponseService:
    def __init__(
        self,
        sensor_repo: SensorDataRepository,
        irrigation_repo: IrrigationLogRepository,
        batch_repo: CropBatchRepository,
        output_repo: ModelOutputRepository,
        model_provider: Callable[[], Any] = get_model,
    ):
        self.sensor_repo = sensor_repo
        self.irrigation_repo = irrigation_repo
        self.batch_repo = batch_repo
        self.output_repo = output_repo
        self.model_provider = model_provider

    @classmethod
    def from_db(cls, db: AsyncIOMotorDatabase) -> "WaterResponseService":
        return cls(
            SensorDataRepository(db), IrrigationLogRepository(db), CropBatchRepository(db), ModelOutputRepository(db)
        )

    async def resolve_features(
        self,
        tray_id: str,
        *,
        water_volume: float,
        batch_id: str | None = None,
        seed_type: str | None = None,
        media_type: str | None = None,
        growth_stage: str | None = None,
        pre_irrigation_moisture: float | None = None,
        temperature: float | None = None,
        humidity: float | None = None,
        light_intensity: float | None = None,
        avg_flow_rate: float | None = None,
        timestamp: datetime | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Build the feature vector for `tray_id` as of `timestamp`.

        Returns (features, context) where context holds the resolved `event_time`, `batch_id` and `growth_stage`.
        Raises NotFoundError for an unknown batch_id and UnprocessableError when no moisture can be determined.
        """
        event_time = as_utc(timestamp) if timestamp else utcnow()

        batch: dict[str, Any] | None = None
        if batch_id:
            found = await self.batch_repo.find_by_business_id(batch_id)
            if found is None:
                raise NotFoundError("Crop batch", batch_id)
            batch = found.model_dump()
        else:
            active = await self.batch_repo.active_for_tray(tray_id, event_time.date())
            batch = active.model_dump() if active else None

        sensor_doc = await self.sensor_repo.latest_for_tray(tray_id, at_or_before=event_time)
        sensor = sensor_doc.model_dump() if sensor_doc else {}

        pre = pre_irrigation_moisture if pre_irrigation_moisture is not None else sensor.get("soil_moisture")
        if pre is None:
            raise UnprocessableError(
                f"No moisture available for tray '{tray_id}': send pre_irrigation_moisture or post a sensor reading first"
            )

        planting_date = date.fromisoformat(batch["planting_date"]) if batch and batch.get("planting_date") else None
        prior = await self.irrigation_repo.list_for_tray_since(
            tray_id, event_time - timedelta(days=HISTORY_DAYS), until=event_time
        )
        features = build_features(
            tray_id=tray_id,
            event_time=event_time,
            water_volume=water_volume,
            pre_irrigation_moisture=pre,
            seed_type=seed_type or (batch or {}).get("seed_type") or sensor.get("seed_type"),
            media_type=media_type or (batch or {}).get("media_type") or sensor.get("media_type"),
            growth_stage=growth_stage,
            avg_flow_rate=avg_flow_rate,
            temperature=temperature if temperature is not None else sensor.get("temperature"),
            humidity=humidity if humidity is not None else sensor.get("humidity"),
            light_intensity=light_intensity if light_intensity is not None else sensor.get("light_intensity"),
            planting_date=planting_date,
            prior_irrigations=[doc.model_dump() for doc in prior],
        )
        context = {
            "event_time": event_time,
            "batch_id": (batch or {}).get("batch_id") or batch_id,
            "growth_stage": features["growth_stage"],
        }
        return features, context

    def predict_from_features(self, features: dict[str, Any]) -> Prediction:
        """Run the current model (trained artifact or baseline) without storing anything."""
        return self.model_provider().predict(features)

    async def store_prediction(
        self, tray_id: str, features: dict[str, Any], prediction: Prediction, context: dict[str, Any]
    ) -> GenericDocument:
        payload = ModelOutputCreate(
            timestamp=context["event_time"],
            tray_id=tray_id,
            model_name=MODEL_NAME,
            model_version=prediction.model_version,
            batch_id=context.get("batch_id"),
            growth_stage=context.get("growth_stage"),
            input_features=features,
            expected_moisture_change=prediction.expected_change,
            expected_moisture_after_irrigation=prediction.expected_after,
            expected_moisture_lower=prediction.lower,
            expected_moisture_upper=prediction.upper,
            response_confidence=prediction.confidence,
            predicted_soil_moisture=prediction.expected_after,
        )
        return await insert_document(self.output_repo, payload, id_field="output_id", timestamp_field="timestamp")

    async def predict(self, tray_id: str, *, water_volume: float, **context_args: Any) -> GenericDocument:
        features, context = await self.resolve_features(tray_id, water_volume=water_volume, **context_args)
        prediction = self.predict_from_features(features)
        return await self.store_prediction(tray_id, features, prediction, context)
