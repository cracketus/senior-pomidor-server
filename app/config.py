import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

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
    daily_story_node_id: str = "pi-001"
    daily_story_schedule_time: str = "09:00"
    daily_story_timezone: str = "Europe/Vienna"
    daily_story_lookback_hours: float = 24.0
    daily_story_poll_interval_seconds: int = 60
    daily_story_max_attempts: int = 3
    daily_story_retry_delay_minutes: int = 15
    daily_story_stale_after_minutes: int = 15
    daily_story_system_prompt_path: str = "config/daily_story/system.txt"
    daily_story_user_prompt_path: str = "config/daily_story/user.txt"
    daily_story_max_context_chars: int = 16_000
    daily_story_ollama_host: str = "http://localhost:11434"
    daily_story_ollama_model: str = "llama3.2:3b"
    daily_story_ollama_timeout_seconds: float = 120.0
    daily_story_ollama_keep_alive: str = "0"
    daily_story_ollama_request_retries: int = 3
    daily_story_ollama_options_json: dict[str, Any] = Field(
        default_factory=lambda: {
            "temperature": 0.4,
            "top_p": 0.9,
            "top_k": 40,
            "num_ctx": 4096,
            "num_predict": 120,
            "repeat_penalty": 1.1,
            "seed": 42,
        }
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
