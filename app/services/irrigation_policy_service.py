"""
Model 3 -- Adaptive Irrigation Policy (`policy-v0`).

`decide(tray_id)` looks at the tray's current state and records an irrigation *recommendation* as a `model_outputs`
row (`model_name = "adaptive_irrigation_policy"`). It never actuates hardware and never writes `irrigation_logs`.

Order of evaluation
  1. state        latest sensor reading (must be < 2 h old), active batch, growth stage, recent irrigations, active faults
  2. thresholds   `thresholds` row for seed + media + growth stage + soil_moisture (else configured defaults)
  3. fault gate   an active fault with confidence >= POLICY_FAULT_GATE_CONFIDENCE  -> hold_and_inspect
  4. hard limits  minimum interval since the last irrigation / daily volume cap     -> wait
  5. forecast     drying slope (interim linear model) x horizon; still inside the band -> wait
  6. candidates   simulate every candidate volume through Model 1; accept those that reach the target band
  7. selection    smallest accepted volume; fallback closest to the band midpoint; else hold_and_inspect
  8. exploration  (optional) a random *accepted* candidate, for data-collection experiments only

Units: moisture % VWC / % points, volume mL, slope % per minute, intervals minutes.
"""
import logging
import random
from datetime import date, datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.v1.insert import insert_document
from app.core.config import settings
from app.core.exceptions import NotFoundError, UnprocessableError
from app.ml.water_response.features import derive_growth_stage
from app.models.common import GenericDocument, as_utc, utcnow
from app.models.model_output import ModelOutputCreate
from app.repositories.crop_batch_repository import CropBatchRepository
from app.repositories.fault_event_repository import FaultEventRepository
from app.repositories.irrigation_log_repository import IrrigationLogRepository
from app.repositories.model_output_repository import ModelOutputRepository
from app.repositories.sensor_data_repository import SensorDataRepository
from app.repositories.threshold_repository import ThresholdRepository
from app.services.water_response_service import WaterResponseService

logger = logging.getLogger(__name__)

MODEL_NAME = "adaptive_irrigation_policy"
MODEL_VERSION = "policy-v0"
STALE_AFTER = timedelta(hours=2)
RULE_CONFIDENCE = 0.9  # confidence of wait / hold decisions, which are rule-based


def _volume_ml(irrigation: dict[str, Any]) -> float:
    return float(irrigation.get("water_volume") or irrigation.get("water_consumed") or 0.0)


def drying_slope_per_minute(readings: list[tuple[datetime, float]]) -> float:
    """Least-squares slope of moisture (% VWC per minute) over (time, moisture) readings; 0 with < 3 readings.

    INTERIM: a straight line through recent readings. Replace with a learned drying model once enough
    non-irrigation intervals have been collected.
    """
    if len(readings) < 3:
        return 0.0
    readings = sorted(readings)
    t0 = readings[0][0]
    xs = [(t - t0).total_seconds() / 60.0 for t, _ in readings]
    ys = [v for _, v in readings]
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    variance = sum((x - mean_x) ** 2 for x in xs)
    if variance == 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / variance


class IrrigationPolicyService:
    def __init__(
        self,
        sensor_repo: SensorDataRepository,
        irrigation_repo: IrrigationLogRepository,
        fault_repo: FaultEventRepository,
        batch_repo: CropBatchRepository,
        threshold_repo: ThresholdRepository,
        output_repo: ModelOutputRepository,
        water_service: WaterResponseService,
        rng: random.Random | None = None,
    ):
        self.sensor_repo = sensor_repo
        self.irrigation_repo = irrigation_repo
        self.fault_repo = fault_repo
        self.batch_repo = batch_repo
        self.threshold_repo = threshold_repo
        self.output_repo = output_repo
        self.water_service = water_service
        self.rng = rng or random.Random()

    @classmethod
    def from_db(cls, db: AsyncIOMotorDatabase, rng: random.Random | None = None) -> "IrrigationPolicyService":
        return cls(
            SensorDataRepository(db),
            IrrigationLogRepository(db),
            FaultEventRepository(db),
            CropBatchRepository(db),
            ThresholdRepository(db),
            ModelOutputRepository(db),
            WaterResponseService.from_db(db),
            rng,
        )

    # ------------------------------------------------------------------ public API

    async def latest(self, tray_id: str) -> GenericDocument | None:
        return await self.output_repo.latest_for_tray(tray_id, extra_query={"model_name": MODEL_NAME})

    async def decide(self, tray_id: str, now: datetime | None = None) -> GenericDocument:
        now = as_utc(now) if now else utcnow()

        # 1. state ----------------------------------------------------------------------------
        sensor_doc = await self.sensor_repo.latest_for_tray(tray_id, at_or_before=now)
        if sensor_doc is None:
            raise NotFoundError("Sensor data for tray", tray_id)
        sensor = sensor_doc.model_dump()
        if as_utc(sensor["timestamp"]) < now - STALE_AFTER:
            raise UnprocessableError(f"Latest sensor reading for tray '{tray_id}' is older than 2 h (state is stale)")
        current = sensor.get("soil_moisture")
        if current is None:
            raise UnprocessableError(f"Latest sensor reading for tray '{tray_id}' has no soil_moisture")

        batch_doc = await self.batch_repo.active_for_tray(tray_id, now.date())
        batch = batch_doc.model_dump() if batch_doc else None
        planting_date = date.fromisoformat(batch["planting_date"]) if batch and batch.get("planting_date") else None
        growth_stage = derive_growth_stage((now.date() - planting_date).days if planting_date else None)
        seed_type = (batch or {}).get("seed_type") or sensor.get("seed_type")
        media_type = (batch or {}).get("media_type") or sensor.get("media_type")
        batch_id = (batch or {}).get("batch_id")

        recent = [
            doc.model_dump()
            for doc in await self.irrigation_repo.list_for_tray_since(tray_id, now - timedelta(hours=24))
            if as_utc(doc.model_dump()["timestamp"]) <= now
        ]
        last_irrigation_at = as_utc(recent[0]["timestamp"]) if recent else None  # list is newest first
        minutes_since_last = (now - last_irrigation_at).total_seconds() / 60.0 if last_irrigation_at else None
        volume_24h = sum(_volume_ml(row) for row in recent)

        # 2. thresholds -------------------------------------------------------------------------
        threshold = None
        if seed_type and media_type and growth_stage:
            found = await self.threshold_repo.latest_matching(seed_type, media_type, growth_stage, "soil_moisture", now)
            threshold = found.model_dump() if found else None
        optimal_min = (threshold or {}).get("optimal_min")
        optimal_max = (threshold or {}).get("optimal_max")
        defaults_used = optimal_min is None or optimal_max is None
        if defaults_used:
            optimal_min, optimal_max = settings.policy_default_optimal_min, settings.policy_default_optimal_max
        critical_max = (threshold or {}).get("critical_max")

        state: dict[str, Any] = {
            "current_moisture": current,
            "optimal_min": optimal_min,
            "optimal_max": optimal_max,
            "critical_max": critical_max,
            "minutes_since_last_irrigation": minutes_since_last,
            "volume_last_24h_ml": volume_24h,
            "default_thresholds_used": defaults_used,
        }
        base_reasons = ["default_thresholds_used"] if defaults_used else []

        def finish(decision: str, reasons: list[str], **extra: Any):
            return self._persist(
                tray_id, now, batch_id, growth_stage, decision, reasons + base_reasons, state, **extra
            )

        # 3. fault gate -----------------------------------------------------------------------------
        for fault in await self.fault_repo.active_for_tray(tray_id):
            data = fault.model_dump()
            confidence = data.get("fault_confidence")
            if confidence is None:
                confidence = data.get("fault_probability")
            if confidence is not None and confidence >= settings.policy_fault_gate_confidence:
                state["blocking_fault_id"] = data.get("fault_id")
                return await finish("hold_and_inspect", [f"active_fault({data.get('fault_hypothesis') or data.get('fault_type')})"])

        # 4. hard limits ----------------------------------------------------------------------------
        if minutes_since_last is not None and minutes_since_last < settings.policy_min_interval_minutes:
            return await finish(
                "wait", [f"min_interval_not_elapsed({minutes_since_last:.0f}<{settings.policy_min_interval_minutes}min)"]
            )
        if volume_24h >= settings.policy_max_daily_volume_ml:
            return await finish("wait", [f"daily_volume_limit_reached({volume_24h:.0f}mL)"])

        # 5. drying forecast (interim) ---------------------------------------------------------------
        window_start = now - timedelta(hours=settings.policy_drying_lookback_hours)
        if last_irrigation_at and last_irrigation_at > window_start:
            window_start = last_irrigation_at  # moisture jumped at irrigation: only trend what happened after it
        readings = [
            (as_utc(doc.model_dump()["timestamp"]), doc.model_dump()["soil_moisture"])
            for doc in await self.sensor_repo.list_for_tray_since(
                tray_id, window_start, until=now + timedelta(seconds=1)
            )
            if doc.model_dump().get("soil_moisture") is not None
        ]
        slope = drying_slope_per_minute(readings)
        forecast = current + slope * settings.policy_horizon_minutes
        state.update({"drying_slope_per_min": slope, "forecast_moisture": forecast})
        target = optimal_min + settings.policy_target_margin
        if forecast >= target:
            return await finish("wait", [f"forecast_within_band({forecast:.1f}>={target:.1f})"])

        # 6. candidate simulation ---------------------------------------------------------------------
        features, context = await self.water_service.resolve_features(
            tray_id,
            water_volume=0.0,
            batch_id=batch_id,
            pre_irrigation_moisture=current,
            timestamp=now,
        )
        state["model_features"] = features
        evaluations: list[dict[str, Any]] = []
        for volume in settings.policy_candidate_volumes_ml:
            if volume <= 0:
                continue
            prediction = self.water_service.predict_from_features({**features, "water_volume": volume})
            reasons: list[str] = []
            if prediction.expected_after < target:
                reasons.append("below_target")
            if prediction.upper > optimal_max:
                reasons.append("exceeds_optimal_max")
            if volume_24h + volume > settings.policy_max_daily_volume_ml:
                reasons.append("daily_limit")
            evaluations.append(
                {
                    "volume_ml": volume,
                    "expected_after": prediction.expected_after,
                    "lower": prediction.lower,
                    "upper": prediction.upper,
                    "response_confidence": prediction.confidence,
                    "model_version": prediction.model_version,
                    "accepted": not reasons,
                    "reason": "accepted" if not reasons else ",".join(reasons),
                }
            )

        # 7. selection ------------------------------------------------------------------------------------
        accepted = [c for c in evaluations if c["accepted"]]
        reasons = ["moisture_below_target"]
        if accepted:
            chosen = min(accepted, key=lambda c: c["volume_ml"])
        else:
            midpoint = (optimal_min + optimal_max) / 2.0
            eligible = [
                c
                for c in evaluations
                if volume_24h + c["volume_ml"] <= settings.policy_max_daily_volume_ml
                and (critical_max is None or c["upper"] <= critical_max)
            ]
            if not eligible:
                return await finish("hold_and_inspect", ["no_safe_candidate"], candidates=evaluations)
            chosen = min(eligible, key=lambda c: abs(c["expected_after"] - midpoint))
            reasons.append("no_accepted_candidate_fallback")

        # 8. exploration (data-collection experiments only; never an unaccepted candidate) ----------------------
        if accepted and settings.policy_exploration_rate > 0 and self.rng.random() < settings.policy_exploration_rate:
            chosen = self.rng.choice(accepted)
            reasons.append("exploration")

        confidence = chosen["response_confidence"] * (0.5 if defaults_used else 1.0)
        return await finish("irrigate", reasons, candidates=evaluations, chosen=chosen, confidence=confidence)

    # ------------------------------------------------------------------ persistence

    async def _persist(
        self,
        tray_id: str,
        now: datetime,
        batch_id: str | None,
        growth_stage: str | None,
        decision: str,
        reasons: list[str],
        state: dict[str, Any],
        *,
        candidates: list[dict[str, Any]] | None = None,
        chosen: dict[str, Any] | None = None,
        confidence: float | None = None,
    ) -> GenericDocument:
        if decision == "irrigate" and chosen is not None:
            volume = chosen["volume_ml"]
            action = f"Irrigate tray {tray_id} with {volume:g} mL"
        elif decision == "wait":
            volume, action = 0.0, f"Wait: do not irrigate tray {tray_id} now"
        else:
            volume, action = 0.0, f"Hold irrigation for tray {tray_id} and inspect"
        payload = ModelOutputCreate(
            timestamp=now,
            tray_id=tray_id,
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
            batch_id=batch_id,
            growth_stage=growth_stage,
            irrigation_recommendation=decision,
            decision_volume_ml=volume,
            recommended_action=action,
            recommendation_confidence=confidence if confidence is not None else RULE_CONFIDENCE,
            recommendation_reason="; ".join(reasons),
            candidate_evaluations=candidates,
            input_features=state,
            expected_moisture_after_irrigation=chosen["expected_after"] if chosen else None,
            expected_moisture_lower=chosen["lower"] if chosen else None,
            expected_moisture_upper=chosen["upper"] if chosen else None,
            expected_moisture_change=(chosen["expected_after"] - state["current_moisture"]) if chosen else None,
            response_confidence=chosen["response_confidence"] if chosen else None,
        )
        return await insert_document(self.output_repo, payload, id_field="output_id", timestamp_field="timestamp")
