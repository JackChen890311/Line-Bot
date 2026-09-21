from line_bot.bot import EchoBot


def test_build_echo_messages_returns_same_text():
    messages = EchoBot.build_echo_messages("hello")
    assert len(messages) == 1
    assert messages[0].text == "hello"


def test_build_echo_messages_empty_string():
    messages = EchoBot.build_echo_messages("")
    assert messages[0].text == ""
