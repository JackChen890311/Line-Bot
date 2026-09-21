"""FastAPI application factory for the LINE echo bot."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Header, HTTPException, Request
from linebot.v3.exceptions import InvalidSignatureError

from line_bot.bot import EchoBot
from line_bot.config import Settings

logger = logging.getLogger(__name__)


class LineBotApp:
    """Owns Settings + EchoBot + FastAPI app and wires routes."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.bot = EchoBot(self.settings)
        self.app = FastAPI(title="line-bot (echo)")
        self._register_routes()

    def _register_routes(self) -> None:
        app = self.app
        bot = self.bot

        @app.get("/")
        async def health() -> dict[str, str]:
            return {"status": "ok"}

        @app.post("/callback")
        async def callback(
            request: Request,
            x_line_signature: str = Header(default=""),
        ) -> dict[str, str]:
            body = (await request.body()).decode("utf-8")
            logger.info("Webhook body: %s", body)
            try:
                bot.handle_webhook(body, x_line_signature)
            except InvalidSignatureError:
                logger.warning("Invalid X-Line-Signature")
                raise HTTPException(status_code=400, detail="Invalid signature")
            return {"status": "ok"}

    def get_app(self) -> FastAPI:
        return self.app


def create_app(settings: Settings | None = None) -> FastAPI:
    """Functional shortcut used by ASGI servers and tests."""
    return LineBotApp(settings).get_app()
