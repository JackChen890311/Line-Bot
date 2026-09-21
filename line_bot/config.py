"""Typed configuration for the LINE bot.

Loads from environment variables / `.env` file.
Required:
    LINE_CHANNEL_SECRET
    LINE_CHANNEL_ACCESS_TOKEN
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    line_channel_secret: str = ""
    line_channel_access_token: str = ""
    port: int = 8000

    @property
    def is_configured(self) -> bool:
        return bool(self.line_channel_secret and self.line_channel_access_token)
