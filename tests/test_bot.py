import json
import time

from line_bot.bot import EchoBot
from line_bot.config import Settings


def _settings(**kwargs) -> Settings:
    base = {
        "line_channel_secret": "test-secret",
        "line_channel_access_token": "test-token",
    }
    base.update(kwargs)
    return Settings(**base)


def _bot(tmp_path, **kwargs):
    """EchoBot with network stubbed out; returns (bot, sent list)."""
    bot = EchoBot(_settings(data_dir=str(tmp_path), **kwargs))
    sent: list[tuple[str, str]] = []
    bot.reply_text = lambda token, text: sent.append((token, text))  # noqa: E731
    bot._show_loading = lambda user_id: None  # noqa: E731
    return bot, sent


def _history_roles(tmp_path, user_id="U1") -> list[str]:
    path = tmp_path / "history" / f"{user_id}.jsonl"
    return [json.loads(line)["role"] for line in path.read_text(encoding="utf-8").splitlines()]


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


def test_fast_path_replies_directly(tmp_path):
    bot, sent = _bot(tmp_path)
    # NOTE: the "user" history entry is written by the webhook handler;
    # simulate it here so the audit trail matches the real flow.
    bot.history.append("U1", "user", "hi")
    bot._process("U1", "tok", "hi")

    assert sent == [("tok", "你說：hi")]
    assert bot.pending.read("U1") is None
    assert _history_roles(tmp_path) == ["user", "bot"]


def test_slow_path_parks_answer_and_keyword_fetches_without_regeneration(tmp_path):
    bot, sent = _bot(tmp_path, debug_slow_seconds=0.3, slow_threshold_seconds=0.05)
    calls: list[str] = []
    orig_generate = bot.generate_reply
    bot.generate_reply = lambda user_id, text: (calls.append(text), orig_generate(user_id, text))[1]

    bot._process("U1", "tok1", "hi")

    # Ask-again notice consumed the token; generation parked in the file.
    assert len(sent) == 1 and "繼續" in sent[0][1]
    for _ in range(100):
        pend = bot.pending.read("U1")
        if pend and pend.get("status") == "ready":
            break
        time.sleep(0.05)
    assert pend["answer"] == "你說：hi"
    assert calls == ["hi"]

    # Fetch via keyword: served from file, generation NOT called again.
    bot.generate_reply = lambda user_id, text: (_ for _ in ()).throw(AssertionError("must not regenerate"))
    bot._process("U1", "tok2", "繼續")
    assert sent[-1] == ("tok2", "你說：hi")
    assert bot.pending.read("U1") is None


def test_keyword_while_thinking_asks_to_wait(tmp_path):
    bot, sent = _bot(tmp_path)
    bot.pending.save_thinking("U1", "Q?")
    bot.generate_reply = lambda user_id, text: (_ for _ in ()).throw(AssertionError("must not generate"))

    bot._process("U1", "tok", "繼續")

    assert sent == [("tok", "還在想，再等一下下")]
    assert bot.pending.read("U1")["status"] == "thinking"


def test_new_question_overwrites_stale_pending(tmp_path):
    bot, sent = _bot(tmp_path)
    bot.pending.save_ready("U1", "Q-old", "A-old")

    bot._process("U1", "tok", "Q-new")

    assert sent == [("tok", "你說：Q-new")]
    assert bot.pending.read("U1") is None


def test_generation_error_replies_and_clears(tmp_path):
    bot, sent = _bot(tmp_path)
    bot.generate_reply = lambda user_id, text: (_ for _ in ()).throw(RuntimeError("boom"))

    bot._process("U1", "tok", "hi")

    assert sent == [("tok", "出錯了，再試一次")]
    assert bot.pending.read("U1") is None


def test_is_duplicate():
    bot = EchoBot(_settings())
    assert bot._is_duplicate("e1") is False
    assert bot._is_duplicate("e1") is True
    assert bot._is_duplicate(None) is False


def test_agent_disabled_falls_back_to_echo(tmp_path):
    bot, sent = _bot(tmp_path, agent_enabled=False, openrouter_api_key="k")
    bot._process("U1", "tok", "hi")
    assert sent == [("tok", "你說：hi")]


def test_agent_path_uses_runner(tmp_path):
    bot, sent = _bot(
        tmp_path, agent_enabled=True, openrouter_api_key="k", slow_threshold_seconds=5
    )

    class FakeRunner:
        def run(self, text):
            assert text == "hi"
            return "agent says hi"

    bot._agent_runner = FakeRunner()  # skip real init
    bot._process("U1", "tok", "hi")
    assert sent == [("tok", "agent says hi")]
