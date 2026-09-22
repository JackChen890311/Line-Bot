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
    AGENT_ENABLED          (use LLM agent instead of echo stub; default true)
    OPENROUTER_API_KEY     (required when AGENT_ENABLED=true)
    LLM_MODEL              (primary model slug; default Qwen 3 Next 80B free)
    LLM_FALLBACK_MODEL     (fallback on 429/errors; default openrouter/free router)
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
    agent_enabled: bool = True
    openrouter_api_key: str = ""
    llm_model: str = "qwen/qwen3-next-80b-a3b-instruct:free"
    llm_fallback_model: str = "openrouter/free"

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
