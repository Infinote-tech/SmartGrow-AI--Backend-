"""Small scoring helpers shared by the response linker (Model 1) and the deviation model (Model 2)."""


def half_interval(lower: float | None, upper: float | None, min_tolerance: float) -> float:
    """Half the prediction-interval width in % points, floored at `min_tolerance`."""
    width_half = (upper - lower) / 2.0 if lower is not None and upper is not None else 0.0
    return max(width_half, min_tolerance)


def water_response_score(
    response_error: float, lower: float | None, upper: float | None, min_tolerance: float
) -> float:
    """1.0 = the moisture landed exactly on the expectation, 0.0 = off by a full half-interval or more.

    score = clip(1 - |error| / max(half_interval, min_tolerance), 0, 1)
    """
    score = 1.0 - abs(response_error) / half_interval(lower, upper, min_tolerance)
    return max(0.0, min(1.0, score))
