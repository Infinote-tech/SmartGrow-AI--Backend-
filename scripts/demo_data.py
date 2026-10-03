"""
Deterministic demo dataset for the SmartGrow AI dashboard and for seeding a dev database.

Simulates one week (2026-09-26 .. 2026-10-02, UTC) of three trays running the closed irrigation loop:
sensor readings every 2 h, irrigation events chosen by the policy, the measured response, Model 2 evaluations and
the fault events they raise. Values are produced with the real project code (baseline formula, Model 2 rules, scores)
so the sample data behaves like data the API would store. It is **demo data, not measurements**.

    from scripts.demo_data import build_demo_dataset
    data = build_demo_dataset()      # {"sensor_data": [...], "irrigation_logs": [...], ...}

Units: moisture % VWC, volume mL, flow L/min, durations seconds, temperature C, humidity % RH, light lux.
"""
import random
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import Settings  # noqa: E402
from app.ml.response_deviation import rules  # noqa: E402
from app.ml.water_response.baseline import BaselineWaterResponseModel  # noqa: E402
from app.ml.water_response.features import derive_growth_stage  # noqa: E402
from app.ml.water_response.scoring import half_interval, water_response_score  # noqa: E402

CFG = Settings(_env_file=None, fault_classifier_path="/nonexistent/fault_classifier.joblib")
START = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
HOURS = 7 * 24
TRAINED_FROM = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)  # from here the "trained" Model 1 replaces baseline-v0
TRAINED_VERSION = "gbr-q-2026-09-30"
ESP32 = "esp32-01"
POST_DELAY_S = 900
MARGIN = CFG.policy_target_margin
CANDIDATES = [50, 100, 150, 200]

# tray -> (seed, media, planted, decay %/h, optimal band, warning band, critical band, min interval h, media gain factor)
TRAYS = {
    "tray-1": dict(seed="radish", media="cocopeat", planted=date(2026, 9, 24), decay=0.35, opt=(55, 75),
                   warn=(45, 85), crit=(35, 90), interval_h=8, gain=1.0, start=63.0),
    "tray-2": dict(seed="mustard", media="compost", planted=date(2026, 9, 23), decay=0.30, opt=(50, 70),
                   warn=(40, 80), crit=(30, 85), interval_h=8, gain=0.9, start=58.0),
    "tray-3": dict(seed="green gram", media="tissue paper", planted=date(2026, 9, 25), decay=0.50, opt=(60, 80),
                   warn=(50, 90), crit=(40, 95), interval_h=6, gain=1.25, start=68.0),
}

# (tray, hour of day offset from START in hours) -> scripted fault
FAULTS = {
    ("tray-2", 3 * 24 + 14): ("no_flow", 2.5),  # 29 Sep 14:00, resolved 16:30
    ("tray-3", 4 * 24 + 9): ("excessive", None),  # 30 Sep 09:00, resolved the next day
    ("tray-1", 5 * 24 + 7): ("intermittent", None),  # 01 Oct 07:00, still active
    ("tray-2", 6 * 24 + 6): ("distribution", None),  # 02 Oct 06:00, still active
}
RESOLUTIONS = {
    ("tray-2", 3 * 24 + 14): ("Cleared the inlet line", "Flushed inlet line and refilled reservoir", True),
    ("tray-3", 4 * 24 + 9): ("Moved the sensor away from the drip point", "Reduced next volume; re-seated sensor", True),
}
RESOLVE_AFTER_H = {("tray-2", 3 * 24 + 14): 2.5, ("tray-3", 4 * 24 + 9): 26.0}

TRUE_GAIN = 10.5  # % points per 100 mL at 0 % moisture: the 'physical' response (the baseline assumes 8)
PLANT_BASE = BaselineWaterResponseModel(CFG.cocopeat_saturation_moisture, CFG.baseline_moisture_gain_per_100ml)


def build_demo_dataset(seed: int = 7) -> dict[str, list[dict]]:
    rng = random.Random(seed)

    def uid() -> str:
        return f"{rng.getrandbits(128):032x}"

    batches = {tid: uid() for tid in TRAYS}
    data: dict[str, list[dict]] = {k: [] for k in (
        "sensor_data", "irrigation_logs", "model_outputs", "fault_events", "hardware_status", "crop_batches",
        "thresholds", "trays")}

    for tid, t in TRAYS.items():
        data["trays"].append({"tray_id": tid, "tray_name": tid.replace("-", " ").title(), "seed_type": t["seed"],
                              "media_type": t["media"], "optimal_min": float(t["opt"][0]), "optimal_max": float(t["opt"][1])})
        data["crop_batches"].append({
            "batch_id": batches[tid], "tray_id": tid, "seed_type": t["seed"], "media_type": t["media"],
            "planting_date": t["planted"].isoformat(),
            "expected_harvest_date": (t["planted"] + timedelta(days=11)).isoformat(), "harvest_date": None,
            "seed_quantity": {"tray-1": 25.0, "tray-2": 20.0, "tray-3": 30.0}[tid], "batch_status": "growing",
        })
        for stage in ("germination", "blackout", "early_growth", "active_growth", "pre_harvest"):
            data["thresholds"].append({
                "threshold_id": uid(), "seed_type": t["seed"], "media_type": t["media"], "growth_stage": stage,
                "parameter": "soil_moisture", "optimal_min": t["opt"][0], "optimal_max": t["opt"][1],
                "warning_min": t["warn"][0], "warning_max": t["warn"][1], "critical_min": t["crit"][0],
                "critical_max": t["crit"][1], "threshold_version": "v1",
                "effective_from": datetime(2026, 9, 24, tzinfo=UTC),
            })

    moisture = {tid: t["start"] for tid, t in TRAYS.items()}
    last_irrigation: dict[str, datetime | None] = {tid: None for tid in TRAYS}
    active_fault: dict[str, dict | None] = {tid: None for tid in TRAYS}
    water_level = 92.0

    def expectation(version: str, tray: dict, pre: float, volume: float) -> dict:
        if version == "baseline-v0":
            p = PLANT_BASE.predict({"pre_irrigation_moisture": pre, "water_volume": volume})
            return dict(change=p.expected_change, after=p.expected_after, lower=p.lower, upper=p.upper,
                        confidence=p.confidence)
        headroom = max(70.0 - pre, 0.0)
        change = TRUE_GAIN * tray["gain"] * (volume / 100.0) * headroom / 70.0 * 1.03
        after = min(pre + change, 100.0)
        return dict(change=after - pre, after=after, lower=max(after - 2.5, 0.0), upper=min(after + 2.5, 100.0),
                    confidence=round(0.78 + rng.random() * 0.08, 3))

    def resolve_fault_rows(now: datetime) -> None:
        for fault in data["fault_events"]:
            key = fault.pop("_key")
            fault["_key"] = key
            hours = RESOLVE_AFTER_H.get(key)
            if hours is None or fault["fault_status"] == "resolved":
                continue
            if now >= fault["timestamp"] + timedelta(hours=hours):
                reason, recovery, ok = RESOLUTIONS[key]
                fault.update(fault_status="resolved", resolved_at=fault["timestamp"] + timedelta(hours=hours),
                             resolution_reason=reason, recovery_action=recovery, recovery_success=ok)
                if active_fault[key[0]] is fault:
                    active_fault[key[0]] = None

    for h in range(HOURS):
        now = START + timedelta(hours=h)
        resolve_fault_rows(now)
        hour_of_day = now.hour
        daylight = 6 <= hour_of_day < 20
        temperature = 24.0 + 3.0 * __import__("math").sin(2 * 3.14159 * (hour_of_day - 8) / 24) + rng.gauss(0, 0.3)
        humidity = 62.0 - 8.0 * __import__("math").sin(2 * 3.14159 * (hour_of_day - 8) / 24) + rng.gauss(0, 1.0)
        light = rng.uniform(9000, 13500) if daylight else 0.0

        for tid, t in TRAYS.items():
            m = moisture[tid]
            days = (now.date() - t["planted"]).days
            stage = derive_growth_stage(days)

            # --- sensor reading every 2 hours (taken before any irrigation in this hour) -------------------
            if h % 2 == 0:
                data["sensor_data"].append({
                    "sensor_data_id": uid(), "timestamp": now + timedelta(minutes=rng.randint(0, 4)),
                    "esp32_id": ESP32, "tray_id": tid, "seed_type": t["seed"], "media_type": t["media"],
                    "temperature": round(temperature + rng.gauss(0, 0.2), 1),
                    "humidity": round(humidity + rng.gauss(0, 0.8), 1),
                    "soil_moisture": round(m + rng.gauss(0, 0.3), 1), "light_intensity": round(light),
                    "water_level": round(water_level, 1), "water_flow_rate": 0.0,
                })

            # --- decide: scripted fault, or due because the tray is drying out -------------------------------
            scripted = FAULTS.get((tid, h))
            since = (now - last_irrigation[tid]).total_seconds() / 3600 if last_irrigation[tid] else 99
            due = m <= t["opt"][0] + MARGIN and since >= t["interval_h"]
            blocked = active_fault[tid] is not None  # an active fault gates the policy
            version = TRAINED_VERSION if now >= TRAINED_FROM else "baseline-v0"

            if not (scripted or due):
                if hour_of_day % 6 == 0:  # policy runs every so often and says "wait" / "hold"
                    hold = blocked
                    data["model_outputs"].append(_policy_row(
                        uid(), now + timedelta(minutes=2), tid, batches[tid], stage,
                        "hold_and_inspect" if hold else "wait", 0.0, 0.9, None,
                        f"active_fault({active_fault[tid]['fault_hypothesis']})" if hold else
                        (f"forecast_within_band({m:.1f}>={t['opt'][0] + MARGIN:.1f})" if m > t["opt"][0] + MARGIN
                         else f"min_interval_not_elapsed({since:.0f}<{t['interval_h'] * 60}min)"), None))
                moisture[tid] = max(m - t["decay"] * (1 + (temperature - 25) * 0.03) + rng.gauss(0, 0.08), 20.0)
                continue

            # --- irrigation --------------------------------------------------------------------------------------
            target = t["opt"][0] + MARGIN
            volume = CANDIDATES[-1]
            for v in CANDIDATES:
                if scripted is None and expectation(version, t, m, v)["after"] >= target:
                    volume = v
                    break
            exp = expectation(version, t, m, volume)
            manual = blocked or (scripted is None and rng.random() < 0.12)
            ts = now + timedelta(minutes=rng.randint(1, 20))
            policy_id, crop_id = uid(), None

            # physical truth
            headroom = max(70.0 - m, 0.0)
            true_gain = TRUE_GAIN * t["gain"] * (volume / 100.0) * headroom / 70.0 * max(rng.gauss(1.0, 0.1), 0.6)
            flow, cv = round(rng.gauss(1.2, 0.07), 2), round(abs(rng.gauss(0.07, 0.025)), 2)
            actual = true_gain
            fault_kind = scripted[0] if scripted else None
            if fault_kind == "no_flow":
                flow, cv, actual = 0.0, 0.0, 0.2
            elif fault_kind == "excessive":
                actual = true_gain * 3.4 + 6.0
            elif fault_kind == "intermittent":
                flow, cv, actual = 0.7, 0.9, 0.5
            elif fault_kind == "distribution":
                actual = 0.4
            post = min(m + actual, 95.0)
            actual = post - m

            expected_change = exp["change"]
            deviation = actual - expected_change
            half = half_interval(exp["lower"], exp["upper"], CFG.deviation_min_tolerance)
            z = deviation / half
            score = water_response_score(post - exp["after"], exp["lower"], exp["upper"], CFG.deviation_min_tolerance)
            duration = round(volume / (flow * 1000 / 60), 1) if flow > 0 else 60.0

            if not manual:  # the controller followed the policy's recommendation
                data["model_outputs"].append({
                    **_policy_row(policy_id, ts - timedelta(minutes=3), tid, batches[tid], stage, "irrigate",
                                  float(volume), round(exp["confidence"], 3), exp, "moisture_below_target", volume),
                    "irrigation_id": None, "actual_moisture_after_irrigation": round(post, 2),
                    "response_error": round(post - exp["after"], 2), "water_response_score": round(score, 3),
                })
                link_id = policy_id
            else:  # a grower irrigated by hand; Model 1 was called when the response was linked
                crop_id = uid()
                data["model_outputs"].append(_response_row(crop_id, ts, tid, batches[tid], stage, version, exp, m,
                                                           volume, post, score))
                link_id = crop_id

            irrigation_id = uid()
            for row in data["model_outputs"]:
                if row["output_id"] == link_id:
                    row["irrigation_id"] = irrigation_id
            data["irrigation_logs"].append({
                "irrigation_id": irrigation_id, "timestamp": ts, "tray_id": tid, "batch_id": batches[tid],
                "solenoid_id": str(1 + list(TRAYS).index(tid)), "pump_status": "on", "irrigation_duration": duration,
                "water_consumed": float(volume), "trigger_type": "manual" if manual else "auto",
                "trigger_reason": "grower check" if manual else "moisture below target",
                "ai_recommended": not manual, "actual_action": "irrigated", "growth_stage": stage,
                "pre_irrigation_moisture": round(m, 2), "post_irrigation_moisture": round(post, 2),
                "post_measured_after_s": POST_DELAY_S, "water_volume": float(volume), "avg_flow_rate": flow,
                "flow_cv": cv, "expected_response": round(expected_change, 3), "actual_response": round(actual, 3),
                "response_deviation": round(deviation, 3), "model_output_id": link_id,
            })

            # --- Model 2 ------------------------------------------------------------------------------------------------
            result = rules.classify(avg_flow_rate=flow, flow_cv=cv, actual_response=actual, expected_response=expected_change,
                                    response_deviation=deviation, post_moisture=post, lower=exp["lower"], upper=exp["upper"],
                                    z=z, cfg=CFG)
            is_anomaly = abs(z) > CFG.deviation_anomaly_z
            severity = "critical" if abs(z) > CFG.deviation_critical_z else "warning"
            eval_ts = ts + timedelta(seconds=POST_DELAY_S + 20)
            data["model_outputs"].append({
                **_blank_output(uid(), eval_ts, tid, batches[tid], stage), "model_name": "response_deviation",
                "model_version": rules.RULES_VERSION, "irrigation_id": irrigation_id,
                "anomaly_score": round(abs(z), 3), "recommendation_confidence": round(result.fault_confidence, 3),
                "recommended_action": result.diagnostic_action or "No action needed",
                "recommendation_reason": f"hypothesis={result.fault_hypothesis}; flow={result.flow_class}; "
                                         f"response={result.response_class}; z={z:.2f}; anomaly={is_anomaly}",
            })
            if is_anomaly and result.fault_hypothesis != "normal":
                fault = {
                    "fault_id": uid(), "timestamp": eval_ts, "esp32_id": ESP32, "tray_id": tid,
                    "fault_type": "response_anomaly",
                    "fault_source": {"pump_tank_blockage": "pump", "distribution_sensor_media": "sensor",
                                     "leakage_or_sensor": "sensor", "valve_tubing_system": "valve"}.get(result.fault_hypothesis, "unknown"),
                    "severity": severity, "sensor_value": round(post, 2), "expected_min": round(exp["lower"], 2),
                    "expected_max": round(exp["upper"], 2), "anomaly_score": round(abs(z), 3),
                    "fault_probability": round(result.fault_confidence, 3), "detected_by": result.detected_by,
                    "recommended_action": result.diagnostic_action, "automatic_action": "irrigation paused for tray",
                    "fault_status": "active", "resolved_at": None, "resolution_reason": None,
                    "irrigation_id": irrigation_id, "response_deviation": round(deviation, 3),
                    "fault_hypothesis": result.fault_hypothesis, "fault_confidence": round(result.fault_confidence, 3),
                    "flow_class": result.flow_class, "response_class": result.response_class,
                    "diagnostic_action": result.diagnostic_action, "recovery_action": result.recovery_action,
                    "recovery_success": None, "injected": False, "_key": (tid, h),
                }
                data["fault_events"].append(fault)
                active_fault[tid] = fault

            last_irrigation[tid] = ts
            water_level -= volume / 400.0
            if water_level < 45:
                water_level = 95.0
            moisture[tid] = post

        # --- hardware snapshot every 6 hours -----------------------------------------------------------------------------
        if hour_of_day % 6 == 0:
            degraded_pump = START + timedelta(hours=3 * 24 + 14) <= now < START + timedelta(hours=3 * 24 + 17)
            valve_fault = now >= START + timedelta(hours=5 * 24 + 7)
            offline = now == START + timedelta(hours=2 * 24 + 18)
            data["hardware_status"].append({
                "hardware_status_id": uid(), "timestamp": now + timedelta(minutes=1), "esp32_id": ESP32,
                "overall_system_status": "degraded" if (degraded_pump or valve_fault or offline) else "ok",
                "solenoid_1_status": "fault" if valve_fault else "closed", "solenoid_2_status": "closed",
                "solenoid_3_status": "closed", "fan_status": "on" if daylight else "off", "motor_status": "off",
                "water_pump_status": "fault" if degraded_pump else "off", "power_status": "ok",
                "connectivity_status": "offline" if offline else "online",
            })

    for fault in data["fault_events"]:
        fault.pop("_key", None)
    data["model_outputs"].sort(key=lambda r: r["timestamp"])
    data["irrigation_logs"].sort(key=lambda r: r["timestamp"])
    data["fault_events"].sort(key=lambda r: r["timestamp"])
    return data


def _blank_output(output_id: str, ts: datetime, tray: str, batch: str, stage: str | None) -> dict:
    return {
        "output_id": output_id, "timestamp": ts, "tray_id": tray, "model_name": None, "model_version": None,
        "irrigation_recommendation": None, "decision_volume_ml": None, "recommendation_confidence": None,
        "recommended_action": None, "recommendation_reason": None, "expected_moisture_change": None,
        "expected_moisture_after_irrigation": None, "expected_moisture_lower": None, "expected_moisture_upper": None,
        "actual_moisture_after_irrigation": None, "response_error": None, "response_confidence": None,
        "water_response_score": None, "anomaly_score": None, "irrigation_id": None, "batch_id": batch,
        "growth_stage": stage,
    }


def _policy_row(output_id, ts, tray, batch, stage, decision, volume, confidence, exp, reason, chosen_volume) -> dict:
    row = _blank_output(output_id, ts, tray, batch, stage)
    row.update(
        model_name="adaptive_irrigation_policy", model_version="policy-v0", irrigation_recommendation=decision,
        decision_volume_ml=volume, recommendation_confidence=confidence, recommendation_reason=reason,
        recommended_action=(f"Irrigate tray {tray} with {volume:g} mL" if decision == "irrigate" else
                            f"Wait: do not irrigate tray {tray} now" if decision == "wait" else
                            f"Hold irrigation for tray {tray} and inspect"),
    )
    if exp:
        row.update(expected_moisture_change=round(exp["change"], 3), expected_moisture_after_irrigation=round(exp["after"], 2),
                   expected_moisture_lower=round(exp["lower"], 2), expected_moisture_upper=round(exp["upper"], 2),
                   response_confidence=round(exp["confidence"], 3))
    return row


def _response_row(output_id, ts, tray, batch, stage, version, exp, pre, volume, post, score) -> dict:
    row = _blank_output(output_id, ts, tray, batch, stage)
    row.update(
        model_name="crop_water_response", model_version=version,
        expected_moisture_change=round(exp["change"], 3), expected_moisture_after_irrigation=round(exp["after"], 2),
        expected_moisture_lower=round(exp["lower"], 2), expected_moisture_upper=round(exp["upper"], 2),
        response_confidence=round(exp["confidence"], 3), actual_moisture_after_irrigation=round(post, 2),
        response_error=round(post - exp["after"], 2), water_response_score=round(score, 3),
    )
    return row


if __name__ == "__main__":
    dataset = build_demo_dataset()
    for name, rows in dataset.items():
        print(f"{name:16s} {len(rows):4d} rows")
