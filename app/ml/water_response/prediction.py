"""The result type shared by the baseline and the trained Crop-Water Response models."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Prediction:
    """Expected moisture after irrigation. All moisture values are % VWC (0-100); change is in % points."""

    expected_change: float
    expected_after: float
    lower: float
    upper: float
    confidence: float  # 0-1
    model_version: str


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def finalize(
    pre_moisture: float,
    median_after: float,
    lower_after: float,
    upper_after: float,
    confidence: float,
    model_version: str,
) -> Prediction:
    """Clamp everything to [0, 100] and enforce lower <= median <= upper."""
    median = clamp(median_after)
    lower = min(clamp(lower_after), median)
    upper = max(clamp(upper_after), median)
    return Prediction(
        expected_change=median - pre_moisture,
        expected_after=median,
        lower=lower,
        upper=upper,
        confidence=confidence,
        model_version=model_version,
    )
