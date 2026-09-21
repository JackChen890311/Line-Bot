"""Entry point: `uv run main.py` or `uv run uvicorn main:app --reload`."""

import logging

import uvicorn

from line_bot.app import LineBotApp
from line_bot.config import Settings

logging.basicConfig(level=logging.INFO)

settings = Settings()
line_bot_app = LineBotApp(settings)
app = line_bot_app.get_app()


def main() -> None:
    if not settings.is_configured:
        logging.warning(
            "LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN not set. "
            "Copy .env.example to .env first. Server will still start for health checks."
        )
    uvicorn.run(app, host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
