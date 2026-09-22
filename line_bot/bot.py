"""OOP wrapper around line-bot-sdk v3.

Fast webhook intake (spawn background thread, return immediately) plus a
pending-answer relay for generations that outlive the LINE reply token:

- generation finishes within slow_threshold_seconds -> reply directly
- otherwise -> consume the token with an ask-again notice, keep generating,
  write the answer to PendingStore; the user fetches it with the fetch
  keyword (or by re-asking) without re-running generation.
"""

from __future__ import annotations

import logging
import threading
import time

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    ShowLoadingAnimationRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from line_bot.config import Settings
from line_bot.store import HistoryLog, PendingStore

logger = logging.getLogger(__name__)

# In-memory dedupe window for webhook event IDs (LINE may redeliver).
_SEEN_TTL_SECONDS = 3600


class EchoBot:
    """Encapsulates LINE SDK config, webhook intake, and reply pipeline."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.configuration = Configuration(access_token=settings.line_channel_access_token)
        self.handler = WebhookHandler(settings.line_channel_secret)
        self.history = HistoryLog(settings.data_dir)
        self.pending = PendingStore(settings.data_dir)
        self._seen_ids: dict[str, float] = {}
        self._seen_lock = threading.Lock()
        self._register_handlers()

    # -- pure business logic (easy to unit test, no network) --
    @staticmethod
    def build_echo_messages(text: str) -> list[TextMessage]:
        """Return the reply message(s) for a given inbound text."""
        return [TextMessage(text=text)]

    # -- generation (Phase 1 stub; Phase 2 swaps in the LLM agent) --
    def generate_reply(self, user_id: str | None, text: str) -> str:
        """Produce the answer text. May be slow; callers race it against the token TTL."""
        if self.settings.debug_slow_seconds > 0:
            time.sleep(self.settings.debug_slow_seconds)
        return "你說：" + text

    # -- LINE API interaction --
    def reply_text(self, reply_token: str, text: str) -> None:
        """Send a reply via the Messaging API."""
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

    def is_sender_allowed(self, user_id: str | None) -> bool:
        """Delegate to settings whitelist."""
        return self.settings.is_user_allowed(user_id)

    # -- internal wiring --
    def _register_handlers(self) -> None:
        @self.handler.add(MessageEvent, message=TextMessageContent)
        def _handle_text_message(event: MessageEvent) -> None:
            assert isinstance(event.message, TextMessageContent)
            user_id = getattr(event.source, "user_id", None)
            text = event.message.text
            self.history.append(user_id, "user", text)
            if not self.is_sender_allowed(user_id):
                logger.warning("Ignoring message from non-whitelisted user: %s", user_id)
                self.history.append(user_id, "system", "blocked: not whitelisted")
                return
            if self._is_duplicate(event.webhook_event_id):
                logger.info("Skipping duplicate event: %s", event.webhook_event_id)
                return
            # Return to the webhook route immediately; do the work in the background
            # so LINE gets its 200 fast and never redelivers.
            threading.Thread(
                target=self._process_in_background,
                args=(user_id, event.reply_token, text),
                daemon=True,
            ).start()

    def _is_duplicate(self, event_id: str | None) -> bool:
        if not event_id:
            return False
        now = time.time()
        with self._seen_lock:
            for seen_id, ts in list(self._seen_ids.items()):
                if now - ts > _SEEN_TTL_SECONDS:
                    del self._seen_ids[seen_id]
            if event_id in self._seen_ids:
                return True
            self._seen_ids[event_id] = now
            return False

    def _process_in_background(self, user_id: str | None, reply_token: str, text: str) -> None:
        try:
            self._process(user_id, reply_token, text)
        except Exception:
            logger.exception("Background processing failed")

    def _process(self, user_id: str | None, reply_token: str, text: str) -> None:
        keyword = self.settings.fetch_keyword
        pend = self.pending.read(user_id)

        # 1) Fetch a ready answer without re-running generation.
        if pend and pend.get("status") == "ready" and (text == keyword or text == pend.get("question")):
            answer = pend["answer"]
            logger.info("Serving pending answer from file")
            if self._send_reply(reply_token, user_id, answer):
                self.pending.clear(user_id)
            return

        # 2) Still thinking and user asks for it -> tell them to wait.
        if pend and pend.get("status") == "thinking" and text == keyword:
            self._send_reply(reply_token, user_id, "還在想，再等一下下")
            return

        # 3) New question (overwrites any stale pending slot).
        logger.info("User: %s", text)
        self.pending.save_thinking(user_id, text)
        self._show_loading(user_id)
        answer, timed_out = self._generate_with_timeout(user_id, text)

        if not timed_out:
            if answer is None:  # generation raised
                self._send_reply(reply_token, user_id, "出錯了，再試一次")
                self.pending.clear(user_id)
                return
            if self._send_reply(reply_token, user_id, answer):
                self.pending.clear(user_id)
            return

        # 4) Slow path: burn the token on an ask-again notice, keep working,
        #    and park the answer in the pending file.
        notice = f"還在想，傳「{keyword}」或再問一次，我會把答案給你"
        logger.info("Generation slow, sending ask-again notice")
        self._send_reply(reply_token, user_id, notice)
        # NOTE: the worker thread keeps running; when it lands, _finish_slow_save
        # writes the answer guarded by compare-and-set (see PendingStore.save_ready).

    def _generate_with_timeout(self, user_id: str | None, text: str) -> tuple[str | None, bool]:
        """Run generation in a worker; return (answer, timed_out).

        On timeout the worker is left running and its result is parked via
        _finish_slow_save. answer=None (not timed out) means generation raised.
        """
        box: dict[str, str] = {}

        def _run() -> None:
            try:
                box["answer"] = self.generate_reply(user_id, text)
            except Exception as e:  # noqa: BLE001 - parked for the caller to handle
                box["error"] = repr(e)

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        worker.join(timeout=self.settings.slow_threshold_seconds)

        if "answer" in box:
            return box["answer"], False
        if "error" in box:
            logger.exception("Generation failed: %s", box["error"])
            return None, False

        # Timed out: wait for the worker in yet another daemon so _process can
        # return promptly, then park the answer (guarded against overwrites).
        threading.Thread(target=self._finish_slow_save, args=(worker, box, user_id, text), daemon=True).start()
        return None, True

    def _finish_slow_save(self, worker: threading.Thread, box: dict[str, str], user_id: str | None, text: str) -> None:
        worker.join()
        if "answer" not in box:
            logger.error("Slow generation failed, nothing to park: %s", box.get("error"))
            self.pending.clear(user_id)
            return
        answer = box["answer"]
        logger.info("Bot (parked): %s", answer)
        self.history.append(user_id, "bot", answer)
        self.pending.save_ready(user_id, text, answer)

    def _send_reply(self, reply_token: str, user_id: str | None, text: str) -> bool:
        """Best-effort reply. Returns False instead of raising on API errors."""
        try:
            self.reply_text(reply_token, text)
        except Exception:
            logger.exception("reply_message failed")
            return False
        logger.info("Bot: %s", text)
        self.history.append(user_id, "bot", text)
        return True

    def _show_loading(self, user_id: str | None) -> None:
        """Best-effort typing indicator (DM chats only)."""
        if not user_id or not user_id.startswith("U"):
            return
        seconds = int(self.settings.slow_threshold_seconds)
        seconds = max(5, min(60, seconds - (seconds % 5) or 5))
        try:
            with ApiClient(self.configuration) as api_client:
                MessagingApi(api_client).show_loading_animation(
                    ShowLoadingAnimationRequest(chat_id=user_id, loading_seconds=seconds)
                )
        except Exception:
            logger.debug("show_loading_animation failed", exc_info=True)
