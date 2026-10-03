"""
Trained Crop-Water Response model (`gbr-q-<UTC date>`).

Three quantile GradientBoostingRegressors (alpha 0.1 / 0.5 / 0.9) predict the moisture *change* (% points) for an
irrigation event. Categorical features are one-hot encoded (unknown categories ignored), numerics are median-imputed.
`tray_id` is a categorical feature so every tray learns its own offset (its "fingerprint").
"""
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from app.ml.water_response.features import CATEGORICAL_FEATURES, FEATURE_COLUMNS, NUMERIC_FEATURES
from app.ml.water_response.prediction import Prediction, finalize

QUANTILES = {"q10": 0.1, "q50": 0.5, "q90": 0.9}
CONFIDENCE_INTERVAL_SCALE = 30.0  # % points: an interval this wide or wider gives the minimum confidence


def features_to_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Rows of feature dicts -> DataFrame with None converted to NaN, so imputers see proper missing values."""
    frame = pd.DataFrame(rows, columns=FEATURE_COLUMNS)
    for column in CATEGORICAL_FEATURES:
        frame[column] = frame[column].map(lambda v: np.nan if v is None or v != v else str(v)).astype(object)
    for column in NUMERIC_FEATURES:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _pipeline(alpha: float) -> Pipeline:
    preprocess = ColumnTransformer(
        [
            (
                "cat",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="constant", fill_value="unknown")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                CATEGORICAL_FEATURES,
            ),
            ("num", SimpleImputer(strategy="median"), NUMERIC_FEATURES),
        ]
    )
    model = GradientBoostingRegressor(
        loss="quantile",
        alpha=alpha,
        n_estimators=150,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.8,
        random_state=0,
    )
    return Pipeline([("preprocess", preprocess), ("model", model)])


def _fit_all(frame: pd.DataFrame, target: np.ndarray) -> dict[str, Pipeline]:
    return {name: _pipeline(alpha).fit(frame, target) for name, alpha in QUANTILES.items()}


def _predict_changes(models: dict[str, Pipeline], frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    q10, q50, q90 = (models[name].predict(frame) for name in ("q10", "q50", "q90"))
    return np.minimum(q10, q50), q50, np.maximum(q90, q50)


def train_model(
    rows: list[dict[str, Any]], groups: list[str], test_size: float = 0.2, random_state: int = 42
) -> tuple[dict[str, Any], dict[str, float]]:
    """Fit the quantile models on `rows` (feature dicts + `actual_response`) and return (artifact, metrics).

    The held-out split is grouped (all rows of a batch/date stay together) -- never a random row split -- so the
    reported metrics are not inflated by near-duplicate neighbouring events. The saved models are refit on all rows.
    """
    if len(set(groups)) < 2:
        raise ValueError("Need at least 2 distinct groups (batches or dates) for a grouped train/test split")
    frame = features_to_frame(rows)
    target = np.array([float(r["actual_response"]) for r in rows])

    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
    train_idx, test_idx = next(splitter.split(frame, target, groups=groups))
    eval_models = _fit_all(frame.iloc[train_idx], target[train_idx])
    lower, median, upper = _predict_changes(eval_models, frame.iloc[test_idx])
    actual = target[test_idx]
    metrics = {
        "mae": float(np.mean(np.abs(actual - median))),
        "rmse": float(np.sqrt(np.mean((actual - median) ** 2))),
        "interval_coverage": float(np.mean((actual >= lower) & (actual <= upper))),
        "n_train": int(len(train_idx)),
        "n_test": int(len(test_idx)),
    }

    models = _fit_all(frame, target)
    stamps = [r["timestamp"] for r in rows if r.get("timestamp") is not None]
    data_range = {
        "first_event": min(stamps).isoformat() if stamps else None,
        "last_event": max(stamps).isoformat() if stamps else None,
        "pre_moisture_min": float(frame["pre_irrigation_moisture"].min()),
        "pre_moisture_max": float(frame["pre_irrigation_moisture"].max()),
        "volume_min_ml": float(frame["water_volume"].min()),
        "volume_max_ml": float(frame["water_volume"].max()),
    }
    artifact = {
        "models": models,
        "feature_columns": FEATURE_COLUMNS,
        "model_version": f"gbr-q-{datetime.now(UTC).date().isoformat()}",
        "trained_at": datetime.now(UTC).isoformat(),
        "n_rows": len(rows),
        "metrics": metrics,
        "data_range": data_range,
    }
    return artifact, metrics


def save_artifact(artifact: dict[str, Any], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, path)


def load_artifact(path: str | Path) -> dict[str, Any]:
    return joblib.load(path)


class TrainedWaterResponseModel:
    def __init__(self, artifact: dict[str, Any]):
        self.artifact = artifact
        self.model_version: str = artifact["model_version"]

    def predict(self, features: dict[str, Any]) -> Prediction:
        pre = features.get("pre_irrigation_moisture")
        if pre is None or features.get("water_volume") is None:
            raise ValueError("pre_irrigation_moisture and water_volume are required")
        frame = features_to_frame([features])
        lower, median, upper = (float(v[0]) for v in _predict_changes(self.artifact["models"], frame))
        prediction = finalize(
            pre_moisture=pre,
            median_after=pre + median,
            lower_after=pre + lower,
            upper_after=pre + upper,
            confidence=0.0,
            model_version=self.model_version,
        )
        confidence = float(np.clip(1.0 - (prediction.upper - prediction.lower) / CONFIDENCE_INTERVAL_SCALE, 0.05, 0.95))
        return Prediction(
            expected_change=prediction.expected_change,
            expected_after=prediction.expected_after,
            lower=prediction.lower,
            upper=prediction.upper,
            confidence=confidence,
            model_version=self.model_version,
        )
