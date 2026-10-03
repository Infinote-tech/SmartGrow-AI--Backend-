"""
Model 2 service -- Response-Deviation / Fault.

Stage A: z = response_deviation / half_interval, where half_interval comes from Model 1's prediction interval
(floored at DEVIATION_MIN_TOLERANCE). |z| above DEVIATION_ANOMALY_Z means the tray did not respond as expected.
Stage B: rules.classify() explains the anomaly from the flow pattern and the response class.
An anomalous, non-normal result creates an active `fault_events` row.
"""
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.v1.insert import insert_document
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.ml.response_deviation import rules
from app.ml.water_response.scoring import half_interval
from app.models.common import GenericDocument, utcnow
from app.models.fault_event import FaultEventCreate, FaultEventPublic
from app.models.ml import DeviationResult, FaultResolveRequest
from app.models.model_output import ModelOutputCreate
from app.repositories.fault_event_repository import FaultEventRepository
from app.repositories.irrigation_log_repository import IrrigationLogRepository
from app.repositories.model_output_repository import ModelOutputRepository
from app.repositories.sensor_data_repository import SensorDataRepository

MODEL_NAME = "response_deviation"

FAULT_SOURCE_BY_HYPOTHESIS = {
    "pump_tank_blockage": "pump",
    "distribution_sensor_media": "sensor",
    "leakage_or_sensor": "sensor",
    "valve_tubing_system": "valve",
    "unknown": "unknown",
}


class ResponseDeviationService:
    def __init__(
        self,
        irrigation_repo: IrrigationLogRepository,
        output_repo: ModelOutputRepository,
        fault_repo: FaultEventRepository,
        sensor_repo: SensorDataRepository,
    ):
        self.irrigation_repo = irrigation_repo
        self.output_repo = output_repo
        self.fault_repo = fault_repo
        self.sensor_repo = sensor_repo

    @classmethod
    def from_db(cls, db: AsyncIOMotorDatabase) -> "ResponseDeviationService":
        return cls(
            IrrigationLogRepository(db), ModelOutputRepository(db), FaultEventRepository(db), SensorDataRepository(db)
        )

    async def evaluate(self, irrigation_id: str) -> DeviationResult:
        log_doc = await self.irrigation_repo.find_by_business_id(irrigation_id)
        if log_doc is None:
            raise NotFoundError("Irrigation log", irrigation_id)
        log = log_doc.model_dump()
        required = ("pre_irrigation_moisture", "post_irrigation_moisture", "actual_response", "response_deviation")
        if any(log.get(name) is None for name in required):
            raise UnprocessableError(
                "The irrigation response is not linked yet: call POST /irrigation-logs/{irrigation_id}/response first"
            )

        pre = log["pre_irrigation_moisture"]
        post = log["post_irrigation_moisture"]
        expected_response = log.get("expected_response")
        deviation = log["response_deviation"]
        tray_id = log["tray_id"]

        lower = upper = None
        linked = None
        if log.get("model_output_id"):
            linked = await self.output_repo.find_by_business_id(log["model_output_id"])
        if linked is not None and linked.model_dump().get("expected_moisture_lower") is not None:
            out = linked.model_dump()
            lower, upper = out["expected_moisture_lower"], out["expected_moisture_upper"]
        elif expected_response is not None:
            tolerance = settings.deviation_min_tolerance
            lower, upper = pre + expected_response - tolerance, pre + expected_response + tolerance

        half = half_interval(lower, upper, settings.deviation_min_tolerance)
        z = deviation / half
        is_anomaly = abs(z) > settings.deviation_anomaly_z
        severity = "critical" if abs(z) > settings.deviation_critical_z else "warning"

        result = rules.classify(
            avg_flow_rate=log.get("avg_flow_rate"),
            flow_cv=log.get("flow_cv"),
            actual_response=log["actual_response"],
            expected_response=expected_response,
            response_deviation=deviation,
            post_moisture=post,
            lower=lower,
            upper=upper,
            z=z,
        )

        fault_public = None
        if is_anomaly and result.fault_hypothesis != "normal":
            sensor = await self.sensor_repo.latest_for_tray(tray_id)
            esp32_id = (sensor.model_dump().get("esp32_id") if sensor else None) or "unknown"
            fault = await insert_document(
                self.fault_repo,
                FaultEventCreate(
                    esp32_id=esp32_id,
                    tray_id=tray_id,
                    fault_type="response_anomaly",
                    fault_source=FAULT_SOURCE_BY_HYPOTHESIS.get(result.fault_hypothesis, "unknown"),
                    severity=severity,
                    sensor_value=post,
                    expected_min=lower,
                    expected_max=upper,
                    anomaly_score=abs(z),
                    fault_probability=result.fault_confidence,
                    detected_by=result.detected_by,
                    recommended_action=result.diagnostic_action,
                    fault_status="active",
                    irrigation_id=irrigation_id,
                    response_deviation=deviation,
                    fault_hypothesis=result.fault_hypothesis,
                    fault_confidence=result.fault_confidence,
                    flow_class=result.flow_class,
                    response_class=result.response_class,
                    diagnostic_action=result.diagnostic_action,
                    recovery_action=result.recovery_action,
                ),
                id_field="fault_id",
                timestamp_field="timestamp",
            )
            fault_public = FaultEventPublic(**fault.model_dump())

        output = await insert_document(
            self.output_repo,
            ModelOutputCreate(
                tray_id=tray_id,
                model_name=MODEL_NAME,
                model_version=rules.RULES_VERSION if result.detected_by == "rule" else "fault-classifier",
                batch_id=log.get("batch_id"),
                irrigation_id=irrigation_id,
                growth_stage=log.get("growth_stage"),
                anomaly_score=abs(z),
                recommendation_confidence=result.fault_confidence,
                recommended_action=result.diagnostic_action or "No action needed",
                recommendation_reason=(
                    f"hypothesis={result.fault_hypothesis}; flow={result.flow_class}; "
                    f"response={result.response_class}; z={z:.2f}; anomaly={is_anomaly}"
                ),
            ),
            id_field="output_id",
            timestamp_field="timestamp",
        )

        return DeviationResult(
            irrigation_id=irrigation_id,
            tray_id=tray_id,
            response_deviation=deviation,
            half_interval=half,
            z=z,
            is_anomaly=is_anomaly,
            severity=severity,
            flow_class=result.flow_class,
            response_class=result.response_class,
            fault_hypothesis=result.fault_hypothesis,
            fault_confidence=result.fault_confidence,
            diagnostic_action=result.diagnostic_action,
            recovery_action=result.recovery_action,
            detected_by=result.detected_by,
            fault_event=fault_public,
            model_output_id=output.model_dump()["output_id"],
        )

    async def resolve(self, fault_id: str, payload: FaultResolveRequest) -> GenericDocument:
        """Mark an active fault as resolved (the only update path on fault_events)."""
        fault = await self.fault_repo.find_by_business_id(fault_id)
        if fault is None:
            raise NotFoundError("Fault event", fault_id)
        if fault.model_dump().get("fault_status") == "resolved":
            raise ConflictError(f"Fault event '{fault_id}' is already resolved")
        updates = {
            "fault_status": "resolved",
            "resolved_at": utcnow(),
            "resolution_reason": payload.resolution_reason,
        }
        if payload.recovery_action is not None:
            updates["recovery_action"] = payload.recovery_action
        if payload.recovery_success is not None:
            updates["recovery_success"] = payload.recovery_success
        return await self.fault_repo.update_by_business_id(fault_id, updates)
