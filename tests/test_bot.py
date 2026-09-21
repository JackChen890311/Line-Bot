from line_bot.bot import EchoBot
from line_bot.config import Settings


def _settings(**kwargs) -> Settings:
    base = {
        "line_channel_secret": "test-secret",
        "line_channel_access_token": "test-token",
    }
    base.update(kwargs)
    return Settings(**base)


def test_build_echo_messages_returns_same_text():
    messages = EchoBot.build_echo_messages("hello")
    assert len(messages) == 1
    assert messages[0].text == "hello"


def test_build_echo_messages_empty_string():
    messages = EchoBot.build_echo_messages("")
    assert messages[0].text == ""


def test_empty_whitelist_allows_all():
    bot = EchoBot(_settings())
    assert bot.is_sender_allowed("Uanyone") is True
    assert bot.is_sender_allowed(None) is True


def test_whitelist_allows_listed_user_only():
    bot = EchoBot(_settings(line_allowed_user_ids="Uaaa, Ubbb"))
    assert bot.is_sender_allowed("Uaaa") is True
    assert bot.is_sender_allowed("Ubbb") is True
    assert bot.is_sender_allowed("U stranger ") is False
    assert bot.is_sender_allowed(None) is False
