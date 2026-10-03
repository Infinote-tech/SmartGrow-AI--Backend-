"""
Connects Model 1 to Model 2.

After an irrigation event, the device reports the post-irrigation moisture. This service stores it on the log,
computes the actual response and its deviation from Model 1's expectation, updates the linked `model_outputs`
row, and runs the Response-Deviation model. It is the only update path on `irrigation_logs` and `model_outputs`
(besides fault resolution on `fault_events`).
"""
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import settings
from app.core.exceptions import NotFoundError, UnprocessableError
from app.ml.water_response.scoring import water_response_score
from app.models.irrigation_log import IrrigationLogPublic
from app.models.ml import ResponseLinkRequest, ResponseLinkResult
from app.models.model_output import ModelOutputPublic
from app.repositories.irrigation_log_repository import IrrigationLogRepository
from app.repositories.model_output_repository import ModelOutputRepository
from app.services.response_deviation_service import ResponseDeviationService
from app.services.water_response_service import WaterResponseService


class ResponseLinker:
    def __init__(
        self,
        irrigation_repo: IrrigationLogRepository,
        output_repo: ModelOutputRepository,
        water_service: WaterResponseService,
        deviation_service: ResponseDeviationService,
    ):
        self.irrigation_repo = irrigation_repo
        self.output_repo = output_repo
        self.water_service = water_service
        self.deviation_service = deviation_service

    @classmethod
    def from_db(cls, db: AsyncIOMotorDatabase) -> "ResponseLinker":
        return cls(
            IrrigationLogRepository(db),
            ModelOutputRepository(db),
            WaterResponseService.from_db(db),
            ResponseDeviationService.from_db(db),
        )

    async def link(self, irrigation_id: str, payload: ResponseLinkRequest) -> ResponseLinkResult:
        log_doc = await self.irrigation_repo.find_by_business_id(irrigation_id)
        if log_doc is None:
            raise NotFoundError("Irrigation log", irrigation_id)
        log = log_doc.model_dump()
        pre = log.get("pre_irrigation_moisture")
        if pre is None:
            raise UnprocessableError("The irrigation log has no pre_irrigation_moisture, so no response can be computed")

        post = payload.post_irrigation_moisture
        updates: dict = {
            "post_irrigation_moisture": post,
            "post_measured_after_s": (
                payload.post_measured_after_s
                if payload.post_measured_after_s is not None
                else log.get("post_measured_after_s") or settings.default_post_measure_delay_s
            ),
        }
        for name in ("avg_flow_rate", "flow_cv", "water_volume"):
            value = getattr(payload, name)
            if value is not None:
                updates[name] = value
        actual_response = post - pre
        updates["actual_response"] = actual_response

        # Resolve the expectation: the linked output if it carries one, otherwise ask Model 1 now.
        output = None
        if log.get("model_output_id"):
            output = await self.output_repo.find_by_business_id(log["model_output_id"])
            if output is None:
                raise NotFoundError("Model output", log["model_output_id"])
        if output is None or output.model_dump().get("expected_moisture_after_irrigation") is None:
            volume = updates.get("water_volume") or log.get("water_volume") or log.get("water_consumed")
            if volume is None:
                raise UnprocessableError("water_volume is required to compute the expected response")
            features, context = await self.water_service.resolve_features(
                log["tray_id"],
                water_volume=volume,
                batch_id=log.get("batch_id"),
                growth_stage=log.get("growth_stage"),
                pre_irrigation_moisture=pre,
                avg_flow_rate=updates.get("avg_flow_rate", log.get("avg_flow_rate")),
                timestamp=log.get("timestamp"),
            )
            prediction = self.water_service.predict_from_features(features)
            output = await self.water_service.store_prediction(log["tray_id"], features, prediction, context)
            updates["model_output_id"] = output.model_dump()["output_id"]

        out = output.model_dump()
        expected_after = out["expected_moisture_after_irrigation"]
        expected_change = (
            out["expected_moisture_change"] if out.get("expected_moisture_change") is not None else expected_after - pre
        )
        updates["expected_response"] = expected_change
        updates["response_deviation"] = actual_response - expected_change
        await self.irrigation_repo.update_by_business_id(irrigation_id, updates)

        response_error = post - expected_after
        await self.output_repo.update_by_business_id(
            out["output_id"],
            {
                "irrigation_id": irrigation_id,
                "actual_moisture_after_irrigation": post,
                "response_error": response_error,
                "water_response_score": water_response_score(
                    response_error,
                    out.get("expected_moisture_lower"),
                    out.get("expected_moisture_upper"),
                    settings.deviation_min_tolerance,
                ),
            },
        )

        deviation = await self.deviation_service.evaluate(irrigation_id)
        log_after = await self.irrigation_repo.find_by_business_id(irrigation_id)
        output_after = await self.output_repo.find_by_business_id(out["output_id"])
        return ResponseLinkResult(
            irrigation_log=IrrigationLogPublic(**log_after.model_dump()),
            model_output=ModelOutputPublic(**output_after.model_dump()),
            deviation=deviation,
        )
