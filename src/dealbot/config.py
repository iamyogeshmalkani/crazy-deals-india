"""Runtime configuration, read from environment variables (and an optional .env file)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader. Existing environment variables win."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    return int(raw) if raw else default


def _list(raw: str) -> List[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Config:
    database_url: str = ""
    bot_token: str = ""
    channel_id: str = ""
    review_chat_id: str = ""
    reviewer_ids: List[int] = field(default_factory=list)

    amazon_tag: str = ""
    flipkart_affid: str = ""
    flipkart_token: str = ""
    wrap_templates: Dict[str, str] = field(default_factory=dict)

    rss_feeds: List[str] = field(default_factory=list)
    manual_deals_file: str = ""

    lang: str = "hi"
    min_score: int = 30
    auto_approve_score: int = 101
    max_posts_per_day: int = 30
    max_posts_per_run: int = 4
    max_review_cards_per_run: int = 8
    review_ttl_hours: int = 8
    quiet_start_hour: int = 0
    quiet_end_hour: int = 7
    dry_run: bool = False

    # Scoring policy
    min_history_points: int = 6
    min_history_days: int = 3
    min_unverified_discount: int = 35
    repost_cooldown_days: int = 7

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Config":
        env = os.environ if env is None else env
        wrap_raw = env.get("AFFILIATE_WRAP_JSON", "").strip()
        review_chat = env.get("TELEGRAM_REVIEW_CHAT_ID", "").strip()
        reviewers = [int(x) for x in _list(env.get("TELEGRAM_REVIEWER_IDS", ""))]
        if not reviewers and review_chat.lstrip("-").isdigit() and not review_chat.startswith("-"):
            reviewers = [int(review_chat)]  # private chat id == user id
        return cls(
            database_url=env.get("DATABASE_URL", "").strip(),
            bot_token=env.get("TELEGRAM_BOT_TOKEN", "").strip(),
            channel_id=env.get("TELEGRAM_CHANNEL_ID", "").strip(),
            review_chat_id=review_chat,
            reviewer_ids=reviewers,
            amazon_tag=env.get("AMAZON_TAG", "").strip(),
            flipkart_affid=env.get("FLIPKART_AFFID", "").strip(),
            flipkart_token=env.get("FLIPKART_TOKEN", "").strip(),
            wrap_templates=json.loads(wrap_raw) if wrap_raw else {},
            rss_feeds=_list(env.get("RSS_FEEDS", "")),
            manual_deals_file=env.get("MANUAL_DEALS_FILE", "").strip(),
            lang=env.get("MSG_LANG", "hi").strip() or "hi",
            min_score=_int(env, "MIN_SCORE", 30),
            auto_approve_score=_int(env, "AUTO_APPROVE_SCORE", 101),
            max_posts_per_day=_int(env, "MAX_POSTS_PER_DAY", 30),
            max_posts_per_run=_int(env, "MAX_POSTS_PER_RUN", 4),
            max_review_cards_per_run=_int(env, "MAX_REVIEW_CARDS_PER_RUN", 8),
            review_ttl_hours=_int(env, "REVIEW_TTL_HOURS", 8),
            quiet_start_hour=_int(env, "QUIET_START_HOUR", 0),
            quiet_end_hour=_int(env, "QUIET_END_HOUR", 7),
            dry_run=env.get("DRY_RUN", "0").strip().lower() in ("1", "true", "yes"),
        )
