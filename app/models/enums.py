"""Shared enumerations used by the irrigation-loop models (Crop-Water Response, Response-Deviation, Policy)."""
from typing import Literal

GrowthStage = Literal["germination", "blackout", "early_growth", "active_growth", "pre_harvest"]

FaultHypothesis = Literal[
    "pump_tank_blockage",  # no flow, no moisture change
    "distribution_sensor_media",  # normal flow, no moisture change
    "leakage_or_sensor",  # normal flow, excessive moisture change
    "valve_tubing_system",  # intermittent flow, irregular response
    "normal",  # normal flow, expected change
    "unknown",
]

FlowClass = Literal["no_flow", "normal", "intermittent"]
ResponseClass = Literal["no_change", "below_expected", "expected", "excessive"]
PolicyDecision = Literal["irrigate", "wait", "hold_and_inspect"]
