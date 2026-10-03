"""Chooses the Crop-Water Response model: the trained artifact if it exists, otherwise the transparent baseline."""
import logging
from pathlib import Path

from app.core.config import settings
from app.ml.water_response.baseline import BaselineWaterResponseModel
from app.ml.water_response.trained import TrainedWaterResponseModel, load_artifact

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_cache: dict[str, tuple[float, TrainedWaterResponseModel]] = {}


def resolve_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def get_model(path: str | None = None) -> BaselineWaterResponseModel | TrainedWaterResponseModel:
    """Trained model if the artifact file exists (reloaded when the file changes), else the baseline."""
    artifact_path = resolve_path(path or settings.water_response_model_path)
    if artifact_path.is_file():
        key = str(artifact_path)
        mtime = artifact_path.stat().st_mtime
        cached = _cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            model = TrainedWaterResponseModel(load_artifact(artifact_path))
            _cache[key] = (mtime, model)
            return model
        except Exception:  # noqa: BLE001 - a corrupt artifact must not take irrigation advice down
            logger.exception("Could not load %s; falling back to the baseline model", artifact_path)
    return BaselineWaterResponseModel(
        saturation=settings.cocopeat_saturation_moisture,
        gain_per_100ml=settings.baseline_moisture_gain_per_100ml,
    )
