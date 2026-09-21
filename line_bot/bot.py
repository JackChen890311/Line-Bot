"""OOP wrapper around line-bot-sdk v3 for an echo bot."""

from __future__ import annotations

import logging

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from line_bot.config import Settings

logger = logging.getLogger(__name__)


class EchoBot:
    """Encapsulates LINE SDK configuration, webhook handling, and echo logic."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.configuration = Configuration(access_token=settings.line_channel_access_token)
        self.handler = WebhookHandler(settings.line_channel_secret)
        self._register_handlers()

    # -- pure business logic (easy to unit test, no network) --
    @staticmethod
    def build_echo_messages(text: str) -> list[TextMessage]:
        """Return the reply message(s) for a given inbound text."""
        return [TextMessage(text=text)]

    # -- LINE API interaction --
    def reply_text(self, reply_token: str, text: str) -> None:
        """Send an echo reply via the Messaging API."""
        with ApiClient(self.configuration) as api_client:
            api = MessagingApi(api_client)
            api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=self.build_echo_messages(text),
                )
            )

    def handle_webhook(self, body: str, signature: str) -> None:
        """Verify signature and dispatch to registered handlers. Raises on bad signature."""
        self.handler.handle(body, signature)

    # -- internal wiring --
    def _register_handlers(self) -> None:
        @self.handler.add(MessageEvent, message=TextMessageContent)
        def _handle_text_message(event: MessageEvent) -> None:
            assert isinstance(event.message, TextMessageContent)
            logger.info("Echoing message: %s", event.message.text)
            self.reply_text(event.reply_token, event.message.text)
