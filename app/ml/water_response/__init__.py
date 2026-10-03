"""
Model 1 -- Crop-Water Response.

Predicts how much a tray's media moisture (% VWC) will rise for a given irrigation volume (mL), with a
prediction interval. Until a trained artifact exists, a transparent physics-style baseline is used
(`baseline-v0`); `scripts/train_water_response.py` produces `gbr-q-<date>` quantile models that the
registry then picks up automatically.
"""
