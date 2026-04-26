from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/macro_release_scanner",
        alias="DATABASE_URL",
    )

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    api_write_token: str = Field(default="", alias="API_WRITE_TOKEN")

    kalshi_base_url: str = Field(default="https://api.elections.kalshi.com/trade-api/v2", alias="KALSHI_BASE_URL")
    bls_base_url: str = Field(default="https://www.bls.gov", alias="BLS_BASE_URL")
    bea_base_url: str = Field(default="https://www.bea.gov", alias="BEA_BASE_URL")
    fed_base_url: str = Field(default="https://www.federalreserve.gov", alias="FED_BASE_URL")

    display_timezone: str = Field(default="Asia/Tokyo", alias="DISPLAY_TIMEZONE")
    poll_interval_seconds: int = Field(default=5, alias="POLL_INTERVAL_SECONDS")
    active_release_window_minutes: int = Field(default=180, alias="ACTIVE_RELEASE_WINDOW_MINUTES")
    skip_remote_schedule_ingestion: bool = Field(default=False, alias="SKIP_REMOTE_SCHEDULE_INGESTION")
    request_timeout_seconds: float = Field(default=10.0, alias="REQUEST_TIMEOUT_SECONDS")
    max_retries: int = Field(default=3, alias="MAX_RETRIES")
    backoff_base_seconds: float = Field(default=0.5, alias="BACKOFF_BASE_SECONDS")

    monitoring_enabled: bool = Field(default=True, alias="MONITORING_ENABLED")
    monitoring_interval_seconds: int = Field(default=60, alias="MONITORING_INTERVAL_SECONDS")
    monitoring_telegram_chat_id: str = Field(default="", alias="MONITORING_TELEGRAM_CHAT_ID")
    monitoring_alert_cooldown_critical_seconds: int = Field(
        default=900, alias="MONITORING_ALERT_COOLDOWN_CRITICAL_SECONDS"
    )
    monitoring_actual_missing_grace_seconds: int = Field(
        default=300, alias="MONITORING_ACTUAL_MISSING_GRACE_SECONDS"
    )
    monitoring_no_signal_grace_seconds: int = Field(default=600, alias="MONITORING_NO_SIGNAL_GRACE_SECONDS")
    monitoring_signal_burst_threshold: int = Field(default=30, alias="MONITORING_SIGNAL_BURST_THRESHOLD")
    monitoring_signal_burst_market_threshold: int = Field(
        default=5, alias="MONITORING_SIGNAL_BURST_MARKET_THRESHOLD"
    )
    monitoring_notification_failure_burst_threshold: int = Field(
        default=3, alias="MONITORING_NOTIFICATION_FAILURE_BURST_THRESHOLD"
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: str | None) -> str:
        if value is None or str(value).strip() == "":
            return "postgresql+asyncpg://postgres:postgres@localhost:5432/macro_release_scanner"
        return str(value).strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
