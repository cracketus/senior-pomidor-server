from functools import lru_cache

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
    grafana_cloud_export_enabled: bool = False
    grafana_cloud_remote_write_url: str | None = Field(default=None)
    grafana_cloud_instance_id: str | None = Field(default=None)
    grafana_cloud_api_token: str | None = Field(default=None)
    grafana_cloud_export_interval_seconds: int = 60
    grafana_cloud_export_lookback_minutes: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
