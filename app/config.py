from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(default="", alias="BOT_TOKEN")
    allowed_user_ids_raw: str = Field(default="", alias="ALLOWED_USER_IDS")
    database_path: Path = Field(default=Path("data/lol_todo.db"), alias="DATABASE_PATH")

    default_timezone: str = Field(default="Asia/Yekaterinburg", alias="DEFAULT_TIMEZONE")
    default_evening_plan_time: str = Field(default="21:00", alias="DEFAULT_EVENING_PLAN_TIME")
    default_morning_digest_time: str = Field(default="08:00", alias="DEFAULT_MORNING_DIGEST_TIME")

    vision_provider: Literal["none", "gemini", "openai"] = Field(
        default="none", alias="VISION_PROVIDER"
    )
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def allowed_user_ids(self) -> set[int]:
        if not self.allowed_user_ids_raw.strip():
            return set()
        result: set[int] = set()
        for part in self.allowed_user_ids_raw.split(","):
            part = part.strip()
            if part.isdigit():
                result.add(int(part))
        return result

    @property
    def has_vision_configured(self) -> bool:
        if self.vision_provider == "gemini" and self.gemini_api_key.strip():
            return True
        if self.vision_provider == "openai" and self.openai_api_key.strip():
            return True
        return False


def load_settings() -> Settings:
    return Settings()
