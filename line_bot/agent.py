"""LLM agent runner: primary OpenRouter model + fallback + quota messaging.

Model choice is a plain slug in Settings (LLM_MODEL), so switching providers
(e.g. to Gemini) is a one-line .env change. Phase 2 ships with no tools;
memory-file and web-search tools land in later phases.

Implementation note: talks to OpenRouter's OpenAI-compatible
``/chat/completions`` endpoint directly via ``httpx`` (stdlib + httpx only).
This keeps the Raspberry Pi 2 install light: the previous
``langchain``/``langgraph`` stack pulled ``langsmith`` -> ``zstandard``,
which ships no ``armv7l`` wheels, forcing a C build from sdist on the Pi.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from line_bot.config import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是使用者的個人助理，用繁體中文回覆。"
    "回覆要簡潔，適合在 LINE 上閱讀；非必要不超過幾百字。"
)

QUOTA_MESSAGE = "今天的免費額度用完了，明天再聊吧"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 120.0


def normalize_model_slug(slug: str) -> str:
    """Accept both bare slugs and the 'openrouter:' prefix form."""
    return slug.removeprefix("openrouter:").strip()


def is_rate_limit_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return "429" in text or "rate limit" in text or "rate_limit" in text or "quota" in text


def _content_to_text(content: Any) -> str:
    """Normalize str | text-blocks | misc objects to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                t = block.get("text", "")
                if isinstance(t, str) and t:
                    # Accept OpenAI-style {"type": "text", "text": ...} and
                    # anything else carrying a text field.
                    parts.append(t)
            elif isinstance(block, str):
                parts.append(block)
            else:
                t = getattr(block, "text", None)
                if isinstance(t, str) and t:
                    parts.append(t)
        return "".join(parts).strip()
    text = getattr(content, "text", None)
    if isinstance(text, str):
        return text.strip()
    return str(content).strip()


def extract_text(result: dict[str, Any]) -> str:
    """Last non-empty assistant message content (str or text blocks).

    Accepts both the lightweight ``{"role": ..., "content": ...}`` dicts
    produced by :class:`OpenRouterChat` and ``AIMessage``-like objects
    (``.content`` + ``AIMessage`` class name) used by older fakes/tests.
    Human/user/system messages are skipped.
    """
    for msg in reversed(result.get("messages", [])):
        if isinstance(msg, dict):
            role = str(msg.get("role", msg.get("type", "assistant"))).lower()
            if role in ("human", "user", "system", "tool"):
                continue
            text = _content_to_text(msg.get("content"))
        else:
            cls_name = msg.__class__.__name__
            role = str(getattr(msg, "role", getattr(msg, "type", "")) or "").lower()
            if cls_name not in ("AIMessage", "AssistantMessage") and role in ("human", "user", "system", "tool"):
                continue
            if cls_name not in ("AIMessage", "AssistantMessage"):
                # Unknown object type: only accept it if it looks like an
                # assistant message (or has no role marker, for back-compat
                # with AIMessage fakes that only set .content).
                if role not in ("", "assistant", "ai", "model", "aimessage"):
                    continue
            text = _content_to_text(getattr(msg, "content", None))
        if text:
            return text
    return ""


def _last_user_text(input: dict[str, Any]) -> str:
    """Pull the last user content from an invoke() payload."""
    messages = input.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, dict):
            role = str(msg.get("role", "")).lower()
            if role in ("", "user", "human"):
                t = _content_to_text(msg.get("content"))
                if t:
                    return t
        else:
            t = _content_to_text(getattr(msg, "content", None))
            if t:
                return t
    return ""


class OpenRouterChat:
    """Minimal OpenAI-compatible chat client for OpenRouter.

    Exposes ``invoke({"messages": [{"role": "user", "content": ...}]})``
    returning ``{"messages": [{"role": "assistant", "content": ...}]}``
    so :class:`AgentRunner` logic stays transport-agnostic and unit
    tests can keep using ``FakeAgent`` stand-ins.
    """

    def __init__(self, model: str, api_key: str, client: httpx.Client | None = None) -> None:
        self.model = model
        self.api_key = api_key
        self._client = client

    def invoke(self, input: dict[str, Any]) -> dict[str, Any]:
        text = _last_user_text(input)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/line-bot",
            "X-Title": "line-bot",
        }
        if self._client is not None:
            resp = self._client.post(OPENROUTER_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        else:
            with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                resp = client.post(OPENROUTER_URL, json=payload, headers=headers)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Re-raise with the status code in the message so
            # is_rate_limit_error() can classify 429/quota errors.
            raise RuntimeError(f"OpenRouter HTTP {e.response.status_code}: {e.response.text[:500]}") from e
        try:
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"OpenRouter bad JSON: {resp.text[:500]}") from e
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"OpenRouter unexpected response: {str(data)[:500]}") from e
        answer = _content_to_text(content)
        if not answer:
            raise RuntimeError("empty OpenRouter response")
        return {"messages": [{"role": "assistant", "content": answer}]}


class AgentRunner:
    """Runs the agent; falls back on errors, answers in plain words on quota errors.

    Agents are injected (objects with ``invoke``) so tests can use fakes; use
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
            return OpenRouterChat(model=slug, api_key=settings.openrouter_api_key or "")

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
