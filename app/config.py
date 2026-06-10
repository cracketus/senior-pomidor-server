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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
