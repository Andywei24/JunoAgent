"""Runtime settings, resolved from environment variables.

`.env` is loaded if present. Adding a new setting should always involve:
1. add a field here with a typed default,
2. mention it in `.env.example`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_env: str = Field(default="dev", alias="APP_ENV")
    app_name: str = Field(default="juno-brain", alias="APP_NAME")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")  # "json" or "console"

    # HTTP
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    # Database
    database_url: str = Field(
        default="postgresql+psycopg://juno:juno@localhost:5432/juno_brain",
        alias="DATABASE_URL",
    )

    # Dev user placeholder (auth proper lands in a later stage)
    dev_user_id: str = Field(default="user_dev", alias="DEV_USER_ID")
    dev_user_email: str = Field(default="dev@local", alias="DEV_USER_EMAIL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
