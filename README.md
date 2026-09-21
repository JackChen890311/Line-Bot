# LINE Echo Bot (FastAPI + uv)

Simple OOP echo bot using `line-bot-sdk` v3. Replies with the same text it receives.

## Layout

```text
.
├── line_bot/
│   ├── __init__.py
│   ├── app.py      # LineBotApp (FastAPI factory, routes)
│   ├── bot.py      # EchoBot (SDK wrapper + echo logic)
│   └── config.py   # Settings (pydantic-settings, .env)
├── tests/
├── main.py         # entry point (ASGI `app` + `uv run main.py`)
├── .env.example
└── pyproject.toml  # uv-managed
```

## Prerequisites

- [uv](https://docs.astral.sh/uv/) installed
- LINE Developers → Messaging API channel (get secret + access token)

## Setup

```bash
cp .env.example .env   # then edit values
uv sync                # create .venv + install deps
```

## Run

```bash
uv run main.py
# or with reload:
uv run uvicorn main:app --reload --port 8000
```

Health check: `GET http://localhost:8000/`

## LINE webhook

1. Expose local server (e.g. `ngrok http 8000`).
2. In LINE Developers → Messaging API → Webhook URL, set `https://<public>/callback`.
3. Send a text message to the bot → it echoes back.

## Test

```bash
uv run pytest -q
```

## Env vars

| Name | Required | Description |
|---|---|---|
| `LINE_CHANNEL_SECRET` | yes | Channel secret (signature verification) |
| `LINE_CHANNEL_ACCESS_TOKEN` | yes | Channel access token (reply API) |
| `PORT` | no | Default `8000` |
