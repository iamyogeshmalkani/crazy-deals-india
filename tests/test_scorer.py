from conftest import DAY, NOW, make_raw, seed_history
from dealbot.models import KIND_OFFER
from dealbot.scorer import HistoryStats, compute_stats, evaluate

NO_HISTORY = HistoryStats(0, 0.0, None, None, None)


def stats_for(repo, raw, prices, days=20):
    pid = seed_history(repo, raw, prices, days)
    return compute_stats(repo.price_history(pid, NOW), NOW)


def test_real_drop_with_history_is_verified_and_low(repo, cfg):
    raw = make_raw(price=14999)
    stats = stats_for(repo, raw, [18499, 18299, 17999, 18199, 18499, 17999, 18299, 18199])
    v = evaluate(raw, stats, None, cfg, NOW)
    assert v.ok and v.verified
    assert v.signals["low_in_window"] and v.signals["window_days"] == 20
    assert v.signals["typical_price"] > 18000


def test_flat_priced_product_with_inflated_mrp_is_rejected(repo, cfg):
    raw = make_raw(price=2000, mrp=4000)
    stats = stats_for(repo, raw, [2000, 2000, 1999, 2000, 2000, 2050, 2000, 2000])
    assert evaluate(raw, stats, None, cfg, NOW).reason == "not_a_real_deal"


def test_price_above_recent_levels_is_rejected(repo, cfg):
    raw = make_raw(price=17500)
    stats = stats_for(repo, raw, [15000, 15200, 15000, 15100, 15000, 15200, 15000])
    assert not evaluate(raw, stats, None, cfg, NOW).ok


def test_unverified_requires_a_big_listed_discount(cfg):
    big = evaluate(make_raw(price=799, mrp=1999), NO_HISTORY, None, cfg, NOW)
    assert big.ok and not big.verified and big.signals["listed_discount_pct"] == 60
    small = evaluate(make_raw(price=999, mrp=1099), NO_HISTORY, None, cfg, NOW)
    assert small.reason == "weak_discount"
    assert evaluate(make_raw(price=999, mrp=None), NO_HISTORY, None, cfg, NOW).reason == "weak_discount"


def test_too_little_history_stays_unverified(repo, cfg):
    raw = make_raw(price=700, mrp=2000)
    stats = stats_for(repo, raw, [1000, 1000, 1000], days=10)  # only 3 points
    v = evaluate(raw, stats, None, cfg, NOW)
    assert v.ok and not v.verified


def test_out_of_stock_and_expired_are_rejected(cfg):
    assert evaluate(make_raw(in_stock=False), NO_HISTORY, None, cfg, NOW).reason == "out_of_stock"
    assert evaluate(make_raw(expires_at=NOW - 1), NO_HISTORY, None, cfg, NOW).reason == "expired"


def test_repost_needs_a_further_ten_percent_drop(cfg):
    raw = make_raw(price=799, mrp=1999)
    assert evaluate(raw, NO_HISTORY, {"price": 820, "posted_at": NOW - DAY}, cfg, NOW).reason == "recently_posted"
    assert evaluate(raw, NO_HISTORY, {"price": 999, "posted_at": NOW - DAY}, cfg, NOW).ok


def test_offers_score_higher_when_expiry_is_near(cfg):
    base = make_raw(kind=KIND_OFFER, price=None, mrp=None)
    soon = make_raw(kind=KIND_OFFER, price=None, mrp=None, expires_at=NOW + 3600)
    assert evaluate(soon, NO_HISTORY, None, cfg, NOW).score > evaluate(base, NO_HISTORY, None, cfg, NOW).score


def test_prev_price_is_the_last_price_at_least_20h_old(repo):
    raw = make_raw()
    pid = repo.upsert_product(raw, NOW - 10 * DAY)
    repo.record_price(pid, 1000, None, NOW - 5 * DAY)
    repo.record_price(pid, 900, None, NOW - 2 * 3600)  # too recent to count as "yesterday"
    stats = compute_stats(repo.price_history(pid, NOW), NOW)
    assert stats.prev_price == 1000 and stats.min_price == 900
