from langchain_core.messages import AIMessage, HumanMessage

from line_bot.agent import (
    QUOTA_MESSAGE,
    AgentRunner,
    extract_text,
    is_rate_limit_error,
    normalize_model_slug,
)


class FakeAgent:
    """Minimal stand-in for a compiled agent graph."""

    def __init__(self, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.calls: list[str] = []

    def invoke(self, input):
        text = input["messages"][0]["content"]
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return {"messages": [HumanMessage(content=text), AIMessage(content=self.reply)]}


def test_normalize_model_slug():
    assert normalize_model_slug("openrouter:qwen/foo:free") == "qwen/foo:free"
    assert normalize_model_slug("  qwen/foo:free  ") == "qwen/foo:free"


def test_is_rate_limit_error():
    assert is_rate_limit_error(Exception("Error code: 429 - slow down")) is True
    assert is_rate_limit_error(Exception("rate limit exceeded")) is True
    assert is_rate_limit_error(ValueError("bad input")) is False


def test_extract_text_str_and_blocks():
    assert extract_text({"messages": [AIMessage(content=" hi  ")]}) == "hi"
    assert (
        extract_text({"messages": [AIMessage(content=[{"type": "text", "text": "a"}, {"type": "x"}])]})
        == "a"
    )
    assert extract_text({"messages": []}) == ""


def test_primary_ok_no_fallback_call():
    primary, fallback = FakeAgent(reply="p"), FakeAgent(reply="f")
    assert AgentRunner(primary, fallback).run("hi") == "p"
    assert fallback.calls == []


def test_primary_429_uses_fallback():
    primary = FakeAgent(error=Exception("Error code: 429"))
    fallback = FakeAgent(reply="f")
    assert AgentRunner(primary, fallback).run("hi") == "f"


def test_all_429_returns_quota_message():
    runner = AgentRunner(FakeAgent(error=Exception("429")), FakeAgent(error=Exception("quota")))
    assert runner.run("hi") == QUOTA_MESSAGE


def test_unexpected_error_raises():
    runner = AgentRunner(FakeAgent(error=ValueError("boom")), fallback=None)
    try:
        runner.run("hi")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_from_settings_builds_without_network():
    from line_bot.config import Settings

    runner = AgentRunner.from_settings(
        Settings(line_channel_secret="s", line_channel_access_token="t", openrouter_api_key="k")
    )
    assert runner.primary is not None
    assert runner.fallback is not None


def test_from_settings_empty_fallback_is_none():
    from line_bot.config import Settings

    runner = AgentRunner.from_settings(
        Settings(
            line_channel_secret="s",
            line_channel_access_token="t",
            openrouter_api_key="k",
            llm_fallback_model="",
        )
    )
    assert runner.fallback is None
