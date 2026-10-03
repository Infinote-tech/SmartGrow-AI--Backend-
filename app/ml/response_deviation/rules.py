"""
Stage B of the Response-Deviation model: classify the flow pattern and the moisture response, then map the pair
to a fault hypothesis (`rules-v0`).

| flow class   | response class              | fault_hypothesis            |
|--------------|-----------------------------|-----------------------------|
| no_flow      | no_change / below_expected  | pump_tank_blockage          |
| normal       | no_change                   | distribution_sensor_media   |
| normal       | excessive                   | leakage_or_sensor           |
| intermittent | any except expected         | valve_tubing_system         |
| normal       | expected                    | normal                      |
| anything else|                             | unknown                     |

If a trained classifier artifact exists (see scripts/train_fault_classifier.py) it is preferred and the result is
marked `detected_by = "model"`; otherwise `detected_by = "rule"`.

Units: moisture % VWC / % points, flow L/min, flow_cv unitless.
"""
import logging
from dataclasses import dataclass
from typing import Any

import joblib
import numpy as np

from app.core.config import Settings, settings
from app.ml.water_response.registry import resolve_path

logger = logging.getLogger(__name__)

RULES_VERSION = "rules-v0"

# hypothesis -> (diagnostic_action, recovery_action)
ACTIONS: dict[str, tuple[str | None, str | None]] = {
    "pump_tank_blockage": (
        "Check reservoir level, pump power and inlet line",
        "Pause irrigation for tray; refill or clear blockage",
    ),
    "distribution_sensor_media": (
        "Check emitter placement, sensor contact with media, media dryness/hydrophobicity",
        "Re-seat sensor; inspect distribution; manual watering check",
    ),
    "leakage_or_sensor": (
        "Check for pooling, leaks near sensor, sensor drift",
        "Reduce next volume; inspect tray drainage",
    ),
    "valve_tubing_system": (
        "Check solenoid operation, tubing kinks, air in line",
        "Cycle valve; inspect tubing",
    ),
    "normal": (None, None),
    "unknown": ("Manual inspection", None),
}

FLOW_CLASS_CODES = {"no_flow": 0, "normal": 1, "intermittent": 2}
MISSING = -1.0  # sentinel for a missing feature in the learned classifier


@dataclass(frozen=True)
class Classification:
    flow_class: str
    response_class: str
    fault_hypothesis: str
    fault_confidence: float
    diagnostic_action: str | None
    recovery_action: str | None
    detected_by: str  # "rule" or "model"
    flow_data_missing: bool


def classify_flow(avg_flow_rate: float | None, flow_cv: float | None, cfg: Settings = settings) -> tuple[str, bool]:
    """Return (flow_class, flow_data_missing)."""
    if avg_flow_rate is not None and avg_flow_rate < cfg.no_flow_threshold_lpm:
        return "no_flow", False
    if flow_cv is not None and flow_cv > cfg.intermittent_flow_cv:
        return "intermittent", False
    return "normal", avg_flow_rate is None and flow_cv is None


def classify_response(
    actual_response: float,
    post_moisture: float,
    lower: float | None,
    upper: float | None,
    cfg: Settings = settings,
) -> str:
    if actual_response < cfg.min_meaningful_change:
        return "no_change"
    if upper is not None and post_moisture > upper:
        return "excessive"
    if lower is not None and post_moisture < lower:
        return "below_expected"
    return "expected"


def rule_hypothesis(flow_class: str, response_class: str) -> str:
    if flow_class == "no_flow" and response_class in ("no_change", "below_expected"):
        return "pump_tank_blockage"
    if flow_class == "normal" and response_class == "no_change":
        return "distribution_sensor_media"
    if flow_class == "normal" and response_class == "excessive":
        return "leakage_or_sensor"
    if flow_class == "intermittent" and response_class != "expected":
        return "valve_tubing_system"
    if flow_class == "normal" and response_class == "expected":
        return "normal"
    return "unknown"


def classifier_features(
    flow_class: str,
    avg_flow_rate: float | None,
    flow_cv: float | None,
    actual_response: float,
    expected_response: float | None,
    response_deviation: float | None,
    z: float,
) -> list[float]:
    """Feature vector of the learned classifier (shared with scripts/train_fault_classifier.py)."""

    def val(x: float | None) -> float:
        return MISSING if x is None else float(x)

    return [
        float(FLOW_CLASS_CODES[flow_class]),
        val(avg_flow_rate),
        val(flow_cv),
        float(actual_response),
        val(expected_response),
        val(response_deviation),
        float(z),
    ]


_classifier_cache: dict[str, tuple[float, Any]] = {}


def load_classifier(cfg: Settings = settings) -> Any | None:
    """The trained fault classifier artifact, or None when it does not exist (or cannot be loaded)."""
    path = resolve_path(cfg.fault_classifier_path)
    if not path.is_file():
        return None
    mtime = path.stat().st_mtime
    cached = _classifier_cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        artifact = joblib.load(path)
    except Exception:  # noqa: BLE001
        logger.exception("Could not load fault classifier %s; using rules", path)
        return None
    _classifier_cache[str(path)] = (mtime, artifact)
    return artifact


def classify(
    *,
    avg_flow_rate: float | None,
    flow_cv: float | None,
    actual_response: float,
    expected_response: float | None,
    response_deviation: float | None,
    post_moisture: float,
    lower: float | None,
    upper: float | None,
    z: float,
    cfg: Settings = settings,
) -> Classification:
    flow_class, flow_missing = classify_flow(avg_flow_rate, flow_cv, cfg)
    response_class = classify_response(actual_response, post_moisture, lower, upper, cfg)

    artifact = load_classifier(cfg)
    if artifact is not None:
        vector = np.array(
            [
                classifier_features(
                    flow_class, avg_flow_rate, flow_cv, actual_response, expected_response, response_deviation, z
                )
            ]
        )
        probabilities = artifact["pipeline"].predict_proba(vector)[0]
        best = int(np.argmax(probabilities))
        hypothesis = str(artifact["pipeline"].classes_[best])
        confidence = float(np.clip(probabilities[best], 0.1, 0.95))
        detected_by = "model"
    else:
        hypothesis = rule_hypothesis(flow_class, response_class)
        confidence = 0.3 if hypothesis == "unknown" else 0.7
        if abs(z) > cfg.deviation_critical_z:
            confidence += 0.1
        if flow_missing:
            confidence -= 0.2
        confidence = float(np.clip(confidence, 0.1, 0.9))
        detected_by = "rule"

    diagnostic, recovery = ACTIONS[hypothesis]
    return Classification(
        flow_class=flow_class,
        response_class=response_class,
        fault_hypothesis=hypothesis,
        fault_confidence=confidence,
        diagnostic_action=diagnostic,
        recovery_action=recovery,
        detected_by=detected_by,
        flow_data_missing=flow_missing,
    )
