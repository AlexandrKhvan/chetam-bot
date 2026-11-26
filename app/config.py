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
    database_path: Path = Field(default=Path("data/chetam.db"), alias="DATABASE_PATH")
    webapp_url: str = Field(default="", alias="WEBAPP_URL")

    default_timezone: str = Field(default="Asia/Yekaterinburg", alias="DEFAULT_TIMEZONE")
    default_evening_plan_time: str = Field(default="21:00", alias="DEFAULT_EVENING_PLAN_TIME")
    default_morning_digest_time: str = Field(default="08:00", alias="DEFAULT_MORNING_DIGEST_TIME")

    vision_provider: Literal["none", "gemini", "openai", "bedrock"] = Field(
        default="none", alias="VISION_PROVIDER"
    )
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    aws_region: str = Field(default="ap-southeast-2", alias="AWS_REGION")
    bedrock_model_id: str = Field(
        default="apac.amazon.nova-lite-v1:0", alias="BEDROCK_MODEL_ID"
    )
    s3_backup_bucket: str = Field(default="", alias="S3_BACKUP_BUCKET")
    s3_backup_prefix: str = Field(default="backups/chetam", alias="S3_BACKUP_PREFIX")
    local_backup_dir: Path = Field(default=Path("data/backups"), alias="LOCAL_BACKUP_DIR")

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
        if self.vision_provider == "bedrock":
            return True
        return False

    @property
    def has_voice_configured(self) -> bool:
        if self.gemini_api_key.strip():
            return True
        if self.openai_api_key.strip():
            return True
        return False


def load_settings() -> Settings:
    return Settings()
