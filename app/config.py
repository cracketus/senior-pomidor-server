import tempfile
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./senior_pomidor.db"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_prefix: str = "senior-pomidor"
    photo_storage_dir: str = "data/photos"
    photo_max_bytes: int = 25 * 1024 * 1024
    photo_upload_token: str | None = Field(default=None)
    telemetry_upload_token: str | None = Field(default=None)
    api_docs_enabled: bool = True
    mqtt_username: str | None = Field(default=None)
    mqtt_password: str | None = Field(default=None)
    worker_health_file: str = str(Path(tempfile.gettempdir()) / "senior-pomidor-worker-health.json")
    grafana_cloud_export_enabled: bool = False
    grafana_cloud_remote_write_url: str | None = Field(default=None)
    grafana_cloud_instance_id: str | None = Field(default=None)
    grafana_cloud_api_token: str | None = Field(default=None)
    grafana_cloud_export_interval_seconds: int = 60
    grafana_cloud_export_lookback_minutes: int = 10
    state_estimator_enabled: bool = True
    state_estimator_timezone: str = "Europe/Vienna"
    state_estimator_private_log_dir: str = "data/private"
    state_estimator_public_log_dir: str = "data/public"
    state_estimator_replay_enabled: bool = False
    state_estimator_config_path: str = "config/state_estimator_v1.yaml"
    assistant_provider: str | None = None
    openai_api_key: str | None = Field(default=None)
    assistant_realtime_model: str = "gpt-realtime"
    assistant_realtime_voice: str = "marin"
    assistant_session_ttl_seconds: int = Field(default=600, ge=10, le=7200)
    assistant_provider_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    assistant_bearer_token: str | None = Field(default=None)
    assistant_rate_limit_requests: int = Field(default=60, ge=1, le=10_000)
    assistant_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
