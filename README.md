# LINE Bot

Simple LINE bot using `line-bot-sdk` v3. Runs on my raspberry pi 2 model B using ngrok.

## Layout

```text
.
├── line_bot/
│   ├── __init__.py
│   ├── app.py      # LineBotApp (FastAPI factory, routes)
│   ├── bot.py      # EchoBot (webhook intake + background reply pipeline)
│   ├── config.py   # Settings (pydantic-settings, .env)
│   └── store.py    # HistoryLog + PendingStore (local file persistence)
├── data/           # gitignored: history/*.jsonl, pending/*.json
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
| `LINE_ALLOWED_USER_IDS` | no | Comma-separated LINE user IDs; empty = allow all |
| `PORT` | no | Default `8000` |
| `DATA_DIR` | no | Local storage dir; default `./data` |
| `SLOW_THRESHOLD_SECONDS` | no | Wait before ask-again notice; default `25` |
| `FETCH_KEYWORD` | no | Keyword to fetch a parked answer; default `繼續` |
| `DEBUG_SLOW_SECONDS` | no | Artificial generation delay for testing; default `0` |

## Whitelist

Set `LINE_ALLOWED_USER_IDS` to your own LINE user ID so the bot only replies to you:

```bash
LINE_ALLOWED_USER_IDS=Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

To find your user ID, temporarily leave the whitelist empty, send the bot a message,
and check the server logs / webhook event JSON (`source.userId`).

## Slow-reply relay (reply token expiry)

The LINE reply token expires ~30s after the event. The bot handles slow
generations without the Push API:

1. Webhook returns 200 immediately; generation runs in a background thread.
2. Answer ready within `SLOW_THRESHOLD_SECONDS` → replied directly.
3. Otherwise the token is spent on an ask-again notice
   (`還在想，傳「繼續」或再問一次`), generation continues, and the answer is
   parked in `data/pending/<user>.json`.
4. Send `繼續` (or re-ask the same question) → the parked answer is replied
   from file, no regeneration. A new question overwrites the pending slot.

Every inbound/outbound message is appended to `data/history/<user>.jsonl`
(audit trail only — never loaded into prompts). Test the slow path with
`DEBUG_SLOW_SECONDS=30`.
