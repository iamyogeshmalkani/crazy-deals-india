from __future__ import annotations

import os
from datetime import datetime

import pytest

from dealbot.config import Config
from dealbot.db import Db, Repo
from dealbot.india import IST
from dealbot.models import RawDeal
from dealbot.telegram import Telegram

# 2026-10-27 14:00 IST, a Tuesday afternoon (outside quiet hours).
NOW = int(datetime(2026, 10, 27, 14, 0, tzinfo=IST).timestamp())
DAY = 86400


@pytest.fixture
def cfg() -> Config:
    return Config(amazon_tag="test-21", flipkart_affid="testaff", channel_id="@chan",
                  review_chat_id="1", reviewer_ids=[1], lang="hi")


@pytest.fixture
def repo() -> Repo:
    """In-memory SQLite by default; set TEST_DATABASE_URL to run the suite on Postgres."""
    url = os.environ.get("TEST_DATABASE_URL", ":memory:")
    db = Db(url)
    if db.is_postgres:
        db.query("DROP TABLE IF EXISTS kv, deals, price_history, products CASCADE")
    r = Repo(db)
    r.init()
    yield r
    db.close()


@pytest.fixture
def tg() -> Telegram:
    return Telegram("", dry_run=True, min_interval=0)


def make_raw(**overrides) -> RawDeal:
    base = dict(store="amazon", source="test", store_product_id="B0TEST0001", title="Test Phone",
                url="https://www.amazon.in/dp/B0TEST0001", price=14999, mrp=24999,
                category="Mobiles")
    base.update(overrides)
    return RawDeal(**base)


def seed_history(repo: Repo, raw: RawDeal, prices, days: int = 20, now: int = NOW) -> int:
    """Insert `prices` evenly across the past `days`, newest at least 25h old."""
    pid = repo.upsert_product(raw, now - days * DAY)
    step = (days * DAY - 25 * 3600) / max(len(prices) - 1, 1)
    for i, price in enumerate(prices):
        repo.record_price(pid, price, raw.mrp, now - 25 * 3600 - int((len(prices) - 1 - i) * step))
    return pid
