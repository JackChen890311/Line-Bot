"""LLM agent runner: primary OpenRouter model + fallback + quota messaging.

Model choice is a plain slug in Settings (LLM_MODEL), so switching providers
(e.g. to Gemini) is a one-line .env change. Phase 2 ships with no tools;
memory-file and web-search tools land in later phases.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents import create_agent
from langchain_openrouter import ChatOpenRouter

from line_bot.config import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是使用者的個人助理，用繁體中文回覆。"
    "回覆要簡潔，適合在 LINE 上閱讀；非必要不超過幾百字。"
)

QUOTA_MESSAGE = "今天的免費額度用完了，明天再聊吧"


def normalize_model_slug(slug: str) -> str:
    """Accept both bare slugs and the 'openrouter:' prefix form."""
    return slug.removeprefix("openrouter:").strip()


def is_rate_limit_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return "429" in text or "rate limit" in text or "rate_limit" in text or "quota" in text


def extract_text(result: dict[str, Any]) -> str:
    """Last non-empty AIMessage content (str or text blocks)."""
    for msg in reversed(result.get("messages", [])):
        if msg.__class__.__name__ != "AIMessage":
            continue
        content = msg.content
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            text = "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ).strip()
            if text:
                return text
    return ""


class AgentRunner:
    """Runs the agent; falls back on errors, answers in plain words on quota errors.

    Agents are injected (compiled graphs) so tests can use fakes; use
    from_settings() for the real OpenRouter-backed pair.
    """

    def __init__(self, primary: Any, fallback: Any | None = None) -> None:
        self.primary = primary
        self.fallback = fallback

    @classmethod
    def from_settings(cls, settings: Settings) -> "AgentRunner":
        def _build(slug: str) -> Any | None:
            slug = normalize_model_slug(slug)
            if not slug:
                return None
            model = ChatOpenRouter(model=slug, api_key=settings.openrouter_api_key or None)
            return create_agent(model, tools=[], system_prompt=SYSTEM_PROMPT)

        return cls(_build(settings.llm_model), _build(settings.llm_fallback_model))

    def run(self, text: str) -> str:
        """Return the answer, or QUOTA_MESSAGE, or raise on unexpected errors."""
        try:
            answer = extract_text(self.primary.invoke({"messages": [{"role": "user", "content": text}]}))
            if answer:
                return answer
            raise RuntimeError("empty agent response")
        except Exception as e:  # noqa: BLE001 - classified below
            logger.warning("Primary model failed: %r", e)
            if self.fallback is not None:
                try:
                    answer = extract_text(self.fallback.invoke({"messages": [{"role": "user", "content": text}]}))
                    if answer:
                        logger.info("Fallback model served the request")
                        return answer
                    e = RuntimeError("empty fallback response")
                except Exception as fe:  # noqa: BLE001 - classified below
                    logger.warning("Fallback model failed: %r", fe)
                    e = fe
            if is_rate_limit_error(e):
                return QUOTA_MESSAGE
            raise
