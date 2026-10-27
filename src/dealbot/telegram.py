"""Minimal Telegram Bot API client (sync) with rate limiting and a dry-run mode."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

CAPTION_LIMIT = 1024
# Telegram allows roughly 20 messages/minute into one channel.
MIN_SECONDS_BETWEEN_SENDS = 3.2


class TelegramError(Exception):
    pass


@dataclass
class Sent:
    message_id: int
    kind: str  # "photo" | "text"


Button = Dict[str, str]
Keyboard = List[List[Button]]


class Telegram:
    def __init__(self, token: str, dry_run: bool = False,
                 min_interval: float = MIN_SECONDS_BETWEEN_SENDS):
        self.token = token
        self.dry_run = dry_run
        self.min_interval = min_interval
        self._client = None if dry_run else httpx.Client(timeout=30)
        self._last_send: Dict[str, float] = {}
        # Dry-run bookkeeping (also used by tests).
        self.outbox: List[Dict[str, Any]] = []
        self.queued_updates: List[Dict[str, Any]] = []
        self._next_id = 1000

    # --- transport ---------------------------------------------------------

    def call(self, method: str, payload: Dict[str, Any]) -> Any:
        if self.dry_run:
            self.outbox.append({"method": method, **payload})
            return {"message_id": self._fake_id()} if method.startswith("send") else True

        url = f"https://api.telegram.org/bot{self.token}/{method}"
        for attempt in range(3):
            resp = self._client.post(url, json=payload)
            data = resp.json()
            if data.get("ok"):
                return data["result"]
            if resp.status_code == 429:
                time.sleep(int(data.get("parameters", {}).get("retry_after", 5)) + 1)
                continue
            raise TelegramError(f"{method} failed: {data.get('description', resp.text)}")
        raise TelegramError(f"{method} failed after retries (rate limited)")

    def _fake_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _throttle(self, chat_id: str) -> None:
        if self.dry_run or self.min_interval <= 0:
            return
        wait = self._last_send.get(chat_id, 0.0) + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_send[chat_id] = time.monotonic()

    # --- sending -----------------------------------------------------------

    def send(self, chat_id: str, text: str, image: Optional[str] = None,
             keyboard: Optional[Keyboard] = None) -> Sent:
        self._throttle(chat_id)
        markup = {"inline_keyboard": keyboard} if keyboard else None

        if image and len(text) <= CAPTION_LIMIT:
            payload: Dict[str, Any] = {"chat_id": chat_id, "photo": image, "caption": text,
                                       "parse_mode": "HTML"}
            if markup:
                payload["reply_markup"] = markup
            try:
                result = self.call("sendPhoto", payload)
                return Sent(int(result["message_id"]), "photo")
            except TelegramError:
                pass  # Telegram could not fetch the image; fall back to plain text.

        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                   "link_preview_options": {"is_disabled": True}}
        if markup:
            payload["reply_markup"] = markup
        result = self.call("sendMessage", payload)
        return Sent(int(result["message_id"]), "text")

    def edit(self, chat_id: str, message_id: int, kind: str, text: str,
             keyboard: Optional[Keyboard] = None) -> None:
        """Replace a message's text/caption. An empty keyboard removes the buttons."""
        payload: Dict[str, Any] = {"chat_id": chat_id, "message_id": message_id,
                                   "parse_mode": "HTML",
                                   "reply_markup": {"inline_keyboard": keyboard or []}}
        if kind == "photo":
            payload["caption"] = text
            self.call("editMessageCaption", payload)
        else:
            payload["text"] = text
            payload["link_preview_options"] = {"is_disabled": True}
            self.call("editMessageText", payload)

    def set_keyboard(self, chat_id: str, message_id: int, keyboard: Keyboard) -> None:
        self.call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id,
                                             "reply_markup": {"inline_keyboard": keyboard}})

    def answer_callback(self, callback_id: str, text: str) -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def get_updates(self, offset: int) -> List[Dict[str, Any]]:
        if self.dry_run:
            updates, self.queued_updates = self.queued_updates, []
            return [u for u in updates if u["update_id"] >= offset]
        return self.call("getUpdates", {"offset": offset, "timeout": 0,
                                        "allowed_updates": ["callback_query", "message"]})
