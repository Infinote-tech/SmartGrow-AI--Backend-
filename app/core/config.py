"""
Centralised application settings, loaded from environment variables / .env.
Using pydantic-settings means every value is validated at startup instead of
failing later with a cryptic KeyError.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", protected_namespaces=()
    )

    app_name: str = "SmartGrow AI Backend"
    environment: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "smartgrow_db"

    jwt_secret_key: str = "insecure-dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    rate_limit_default: str = "100/minute"
    rate_limit_login: str = "5/minute"

    cors_origins: str = "http://localhost:3000"

    # --- Model 1: Crop-Water Response -------------------------------------------------
    water_response_model_path: str = "app/ml/artifacts/water_response.joblib"
    water_response_min_training_rows: int = 30
    cocopeat_saturation_moisture: float = 70.0  # % VWC, baseline model cap
    baseline_moisture_gain_per_100ml: float = 8.0  # % points per 100 mL at 0% pre-moisture
    default_post_measure_delay_s: int = 900  # seconds the post-irrigation reading waits after the valve closes

    # --- Model 2: Response-Deviation / Fault -------------------------------------------
    deviation_min_tolerance: float = 3.0  # % points, floor for normalisation
    deviation_anomaly_z: float = 1.0  # |z| above this = response anomaly
    deviation_critical_z: float = 2.5  # |z| above this = critical severity
    no_flow_threshold_lpm: float = 0.05  # L/min, below this the pump delivered nothing
    intermittent_flow_cv: float = 0.5  # flow coefficient of variation above this = intermittent
    min_meaningful_change: float = 1.0  # % points, below this the moisture did not respond
    fault_classifier_path: str = "app/ml/artifacts/fault_classifier.joblib"

    # --- Model 3: Adaptive Irrigation Policy -------------------------------------------
    policy_candidate_volumes_ml: list[float] = [0, 50, 100, 150, 200]
    policy_horizon_minutes: int = 60
    policy_drying_lookback_hours: float = 3.0
    policy_target_margin: float = 2.0  # % points above optimal_min
    policy_min_interval_minutes: int = 60
    policy_max_daily_volume_ml: float = 1000
    policy_fault_gate_confidence: float = 0.6
    policy_exploration_rate: float = 0.0  # set >0 only during data-collection experiments
    policy_default_optimal_min: float = 45.0  # % VWC, used only when no threshold row exists
    policy_default_optimal_max: float = 65.0
    policy_scheduler_enabled: bool = False
    policy_scheduler_interval_minutes: int = 15
    policy_scheduler_tray_ids: str = ""  # comma separated

    @property
    def policy_scheduler_tray_list(self) -> list[str]:
        return [t.strip() for t in self.policy_scheduler_tray_ids.split(",") if t.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
