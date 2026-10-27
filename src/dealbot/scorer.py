"""Decide whether a deal is real, and how good it is.

Everything here is derived from data we hold. The signals it emits are the only
facts the composer is allowed to turn into urgency lines.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from dealbot.config import Config
from dealbot.models import KIND_OFFER, RawDeal, Verdict

DAY = 86400
PREV_PRICE_MIN_AGE = 20 * 3600  # "yesterday's price" must be at least this old
PREV_DROP_MIN_PCT = 5.0
NEAR_LOW_TOLERANCE = 1.05  # within 5% of the lowest tracked price
BELOW_MEDIAN_FACTOR = 0.75  # or at least 25% below the 30-day median
MIN_DROP_FACTOR = 0.95  # a near-low price must also be 5%+ below the 30-day median
REPOST_MIN_DROP = 0.90  # a re-post needs a further 10% drop


@dataclass
class HistoryStats:
    points: int
    days: float  # how long we have been tracking this product
    min_price: Optional[int]
    median_30d: Optional[int]
    prev_price: Optional[int]  # most recent price recorded >= ~20h ago


def compute_stats(history: List[Tuple[int, int]], now: int) -> HistoryStats:
    """`history` is (timestamp, price) oldest first, excluding the current observation."""
    if not history:
        return HistoryStats(0, 0.0, None, None, None)
    prices = [p for _, p in history]
    recent = [p for ts, p in history if ts >= now - 30 * DAY]
    prev = [p for ts, p in history if ts <= now - PREV_PRICE_MIN_AGE]
    return HistoryStats(
        points=len(history),
        days=(now - history[0][0]) / DAY,
        min_price=min(prices),
        median_30d=int(statistics.median(recent)) if recent else None,
        prev_price=prev[-1] if prev else None,
    )


def _offer_points(raw: RawDeal) -> int:
    return (5 if raw.coupon else 0) + (5 if raw.bank_offer else 0)


def evaluate(raw: RawDeal, stats: HistoryStats, last_posted: Optional[Dict[str, Any]],
             cfg: Config, now: int) -> Verdict:
    if raw.in_stock is False:
        return Verdict(False, "out_of_stock")
    if raw.expires_at is not None and raw.expires_at <= now:
        return Verdict(False, "expired")

    if raw.kind == KIND_OFFER:
        score = 30 + _offer_points(raw)
        if raw.expires_at is not None and raw.expires_at - now <= 48 * 3600:
            score += 10
        return Verdict(True, score=min(score, 100), verified=False,
                       signals={"expires_at": raw.expires_at})

    price = raw.price
    if not price or price <= 0:
        return Verdict(False, "no_price")

    if last_posted is not None and last_posted.get("price"):
        if price > int(last_posted["price"]) * REPOST_MIN_DROP:
            return Verdict(False, "recently_posted")

    signals: Dict[str, Any] = {"expires_at": raw.expires_at}
    verified = stats.points >= cfg.min_history_points and stats.days >= cfg.min_history_days

    if verified and stats.min_price is not None:
        low = price <= stats.min_price
        near_low = price <= stats.min_price * NEAR_LOW_TOLERANCE
        median = stats.median_30d
        below_median = bool(median) and price <= median * BELOW_MEDIAN_FACTOR
        meaningful_drop = bool(median) and price <= median * MIN_DROP_FACTOR
        # A flat-priced product is always "near its low"; require a real drop as well.
        if not ((near_low and meaningful_drop) or below_median):
            return Verdict(False, "not_a_real_deal")

        drop_pct = (median - price) / median * 100 if median and median > price else 0.0
        prev_drop = 0
        if stats.prev_price and stats.prev_price > price:
            if (stats.prev_price - price) / stats.prev_price * 100 >= PREV_DROP_MIN_PCT:
                prev_drop = stats.prev_price - price

        score = min(40.0, drop_pct) + (30 if low else 15 if near_low else 0)
        score += 15 if prev_drop else 0
        score += _offer_points(raw)
        signals.update(
            verified=True,
            window_days=min(int(stats.days), 90),
            low_in_window=low,
            typical_price=median,
            prev_price=stats.prev_price if prev_drop else None,
            drop_from_prev=prev_drop or None,
        )
        return Verdict(True, score=min(int(score), 100), verified=True, signals=signals)

    # Not enough history to verify: rely on the listed MRP, flagged as unverified.
    listed = 0.0
    if raw.mrp and raw.mrp > price:
        listed = (raw.mrp - price) / raw.mrp * 100
    if listed < cfg.min_unverified_discount:
        return Verdict(False, "weak_discount")
    score = min(60.0, listed * 0.9) + _offer_points(raw)
    signals.update(verified=False, listed_discount_pct=int(listed))
    return Verdict(True, score=min(int(score), 100), verified=False, signals=signals)
