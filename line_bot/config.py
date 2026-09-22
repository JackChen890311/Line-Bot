"""Typed configuration for the LINE bot.

Loads from environment variables / `.env` file.
Required:
    LINE_CHANNEL_SECRET
    LINE_CHANNEL_ACCESS_TOKEN
Optional:
    LINE_ALLOWED_USER_IDS  (comma-separated LINE user IDs; empty = allow all)
    DATA_DIR               (local storage for history/pending; default ./data)
    SLOW_THRESHOLD_SECONDS (background wait before ask-again notice; default 25)
    FETCH_KEYWORD          (keyword to fetch a pending answer; default 繼續)
    DEBUG_SLOW_SECONDS     (artificial generation delay for testing; default 0)
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    line_channel_secret: str = ""
    line_channel_access_token: str = ""
    line_allowed_user_ids: str = ""
    port: int = 8000
    data_dir: str = "./data"
    slow_threshold_seconds: float = 25.0
    fetch_keyword: str = "繼續"
    debug_slow_seconds: float = 0.0

    @property
    def is_configured(self) -> bool:
        return bool(self.line_channel_secret and self.line_channel_access_token)

    @property
    def allowed_user_ids(self) -> set[str]:
        """Parse comma-separated whitelist. Empty set means no restriction."""
        return {uid.strip() for uid in self.line_allowed_user_ids.split(",") if uid.strip()}

    def is_user_allowed(self, user_id: str | None) -> bool:
        """Empty whitelist = allow all (backward compatible). Otherwise enforce."""
        allowed = self.allowed_user_ids
        if not allowed:
            return True
        return bool(user_id) and user_id in allowed
