"""
Transparent bootstrap model (`baseline-v0`), used whenever no trained artifact exists.

    headroom        = max(saturation - pre, 0)
    gain            = gain_per_100ml * (water_volume / 100) * (headroom / saturation)
    expected_after  = min(pre + gain, saturation)            (never below `pre` if pre is already above saturation)
    expected_change = expected_after - pre
    lower / upper   = expected_after -/+ max(3.0, 0.5 * gain), clamped to [0, 100]
    confidence      = 0.3   (fixed: signals "not learned from data")

Units: moisture % VWC, volume mL, gain % points. Calibrate `saturation` and `gain_per_100ml` from your sensors
(settings COCOPEAT_SATURATION_MOISTURE and BASELINE_MOISTURE_GAIN_PER_100ML); the defaults are placeholders.
"""
from typing import Any

from app.ml.water_response.prediction import Prediction, finalize

MODEL_VERSION = "baseline-v0"
BASELINE_CONFIDENCE = 0.3
MIN_HALF_INTERVAL = 3.0


class BaselineWaterResponseModel:
    model_version = MODEL_VERSION

    def __init__(self, saturation: float, gain_per_100ml: float):
        self.saturation = saturation
        self.gain_per_100ml = gain_per_100ml

    def predict(self, features: dict[str, Any]) -> Prediction:
        pre = features.get("pre_irrigation_moisture")
        volume = features.get("water_volume")
        if pre is None or volume is None:
            raise ValueError("pre_irrigation_moisture and water_volume are required")
        headroom = max(self.saturation - pre, 0.0)
        gain = self.gain_per_100ml * (volume / 100.0) * (headroom / self.saturation)
        expected_after = min(pre + gain, max(self.saturation, pre))
        half = max(MIN_HALF_INTERVAL, 0.5 * gain)
        return finalize(
            pre_moisture=pre,
            median_after=expected_after,
            lower_after=expected_after - half,
            upper_after=expected_after + half,
            confidence=BASELINE_CONFIDENCE,
            model_version=MODEL_VERSION,
        )
