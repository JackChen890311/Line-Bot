from fastapi.testclient import TestClient

from line_bot.app import create_app
from line_bot.config import Settings


def _settings() -> Settings:
    return Settings(
        line_channel_secret="test-secret",
        line_channel_access_token="test-token",
    )


def test_health_check():
    client = TestClient(create_app(_settings()))
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_callback_rejects_bad_signature():
    client = TestClient(create_app(_settings()))
    r = client.post("/callback", content="{}", headers={"X-Line-Signature": "bad"})
    # line-bot-sdk raises InvalidSignatureError -> our app maps to 400 or 403
    assert r.status_code in (400, 403)
