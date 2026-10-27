from datetime import datetime

from conftest import DAY, NOW, make_raw, seed_history
from dealbot.db import STATUS_APPROVED, STATUS_EXPIRED, STATUS_POSTED, STATUS_REJECTED
from dealbot.india import IST
from dealbot.pipeline import Pipeline


class Source:
    name = "test"

    def __init__(self, *raws):
        self.raws = list(raws)

    def fetch(self):
        return self.raws


class Broken:
    name = "broken"

    def fetch(self):
        raise RuntimeError("boom")


def callback(update_id, deal_id, action="ap", user=1):
    return {"update_id": update_id, "callback_query": {
        "id": f"cb{update_id}", "from": {"id": user}, "data": f"{action}:{deal_id}"}}


def sent(tg, chat=None):
    return [m for m in tg.outbox if m["method"] in ("sendMessage", "sendPhoto")
            and (chat is None or m["chat_id"] == chat)]


def good_deal(repo, **overrides):
    raw = make_raw(**overrides)
    seed_history(repo, raw, [18499, 18299, 17999, 18199, 18499, 17999, 18299, 18199])
    return raw


def test_candidate_goes_to_review_chat_not_the_channel(cfg, repo, tg):
    raw = good_deal(repo)
    stats = Pipeline(cfg, repo, tg, [Source(raw)], clock=lambda: NOW).run()
    assert stats["queued"] == 1 and stats["posted"] == 0
    assert len(sent(tg, "1")) == 1 and sent(tg, "@chan") == []
    card = sent(tg, "1")[0]
    assert card["reply_markup"]["inline_keyboard"][0][0]["callback_data"].startswith("ap:")


def test_approve_publishes_with_our_affiliate_link(cfg, repo, tg):
    raw = good_deal(repo, url="https://www.amazon.in/dp/B0TEST0001?tag=thief-21")
    pipe = Pipeline(cfg, repo, tg, [Source(raw)], clock=lambda: NOW)
    pipe.run()
    deal = repo.deals_by_status("pending_review")[0]
    tg.queued_updates = [callback(10, deal["id"])]
    stats = pipe.run()
    assert stats["reviewed"] == 1 and stats["posted"] == 1
    post = sent(tg, "@chan")[0]
    assert "tag=test-21" in post["text"] and "thief" not in post["text"]
    assert post["reply_markup"]["inline_keyboard"][0][0]["url"] == deal["link"]
    assert repo.get_deal(deal["id"])["status"] == STATUS_POSTED


def test_reject_and_unauthorised_taps(cfg, repo, tg):
    raw = good_deal(repo)
    pipe = Pipeline(cfg, repo, tg, [Source(raw)], clock=lambda: NOW)
    pipe.run()
    deal_id = repo.deals_by_status("pending_review")[0]["id"]

    tg.queued_updates = [callback(10, deal_id, "ap", user=999)]  # not a reviewer
    assert pipe.run()["reviewed"] == 0
    assert repo.get_deal(deal_id)["status"] == "pending_review"

    tg.queued_updates = [callback(11, deal_id, "rj")]
    pipe.run()
    assert repo.get_deal(deal_id)["status"] == STATUS_REJECTED
    assert sent(tg, "@chan") == []


def test_update_offset_is_persisted_so_taps_are_not_replayed(cfg, repo, tg):
    raw = good_deal(repo)
    pipe = Pipeline(cfg, repo, tg, [Source(raw)], clock=lambda: NOW)
    pipe.run()
    deal_id = repo.deals_by_status("pending_review")[0]["id"]
    tg.queued_updates = [callback(10, deal_id)]
    pipe.run()
    assert repo.get_kv("tg_update_offset") == "11"
    tg.queued_updates = [callback(10, deal_id)]  # Telegram redelivers an old update
    assert pipe.run()["reviewed"] == 0


def test_no_duplicate_cards_while_a_deal_is_open(cfg, repo, tg):
    raw = good_deal(repo)
    pipe = Pipeline(cfg, repo, tg, [Source(raw)], clock=lambda: NOW)
    pipe.run()
    assert pipe.run()["queued"] == 0
    assert len(sent(tg, "1")) == 1


def test_quiet_hours_hold_approved_deals(cfg, repo, tg):
    night = int(datetime(2026, 10, 27, 3, 0, tzinfo=IST).timestamp())
    raw = good_deal(repo)
    pipe = Pipeline(cfg, repo, tg, [Source(raw)], clock=lambda: night)
    pipe.run()
    deal = repo.deals_by_status("pending_review")[0]
    repo.update_deal(deal["id"], status=STATUS_APPROVED)
    assert pipe.run()["posted"] == 0 and sent(tg, "@chan") == []
    pipe.clock = lambda: night + 5 * 3600  # 08:00 IST
    assert pipe.run()["posted"] == 1


def test_untagged_link_is_never_published(cfg, repo, tg):
    raw = good_deal(repo)
    pipe = Pipeline(cfg, repo, tg, [Source(raw)], clock=lambda: NOW)
    pipe.run()
    deal = repo.deals_by_status("pending_review")[0]
    repo.db.query("UPDATE deals SET status = 'approved', link = %s WHERE id = %s",
                  ("https://www.amazon.in/dp/B0TEST0001", deal["id"]))
    assert pipe.run()["posted"] == 0
    assert repo.get_deal(deal["id"])["status"] == STATUS_REJECTED and sent(tg, "@chan") == []


def test_post_limits_per_run_and_per_day(cfg, repo, tg):
    cfg.max_posts_per_run, cfg.max_posts_per_day = 2, 3
    raws = []
    for i in range(5):
        raws.append(good_deal(repo, store_product_id=f"B0TEST000{i}",
                              url=f"https://www.amazon.in/dp/B0TEST000{i}"))
    pipe = Pipeline(cfg, repo, tg, [Source(*raws)], clock=lambda: NOW)
    pipe.run()
    for d in repo.deals_by_status("pending_review"):
        repo.update_deal(d["id"], status=STATUS_APPROVED)
    assert pipe.run()["posted"] == 2
    assert pipe.run()["posted"] == 1  # daily cap of 3 reached
    assert pipe.run()["posted"] == 0


def test_expired_offer_post_is_edited_to_ended(cfg, repo, tg):
    raw = good_deal(repo, expires_at=NOW + 3600)
    pipe = Pipeline(cfg, repo, tg, [Source(raw)], clock=lambda: NOW)
    pipe.run()
    deal = repo.deals_by_status("pending_review")[0]
    tg.queued_updates = [callback(10, deal["id"])]
    pipe.run()
    tg.outbox.clear()
    pipe.clock = lambda: NOW + 2 * 3600
    assert pipe.run()["expired"] == 1
    edit = [m for m in tg.outbox if m["method"] == "editMessageText"][0]
    assert "DEAL KHATAM" in edit["text"] and edit["chat_id"] == "@chan"
    assert repo.get_deal(deal["id"])["status"] == STATUS_EXPIRED


def test_stale_pending_deals_are_dropped(cfg, repo, tg):
    raw = good_deal(repo)
    pipe = Pipeline(cfg, repo, tg, [Source(raw)], clock=lambda: NOW)
    pipe.run()
    pipe.clock = lambda: NOW + 9 * 3600
    assert pipe.run()["stale"] == 1


def test_a_broken_collector_does_not_stop_the_others(cfg, repo, tg):
    raw = good_deal(repo)
    stats = Pipeline(cfg, repo, tg, [Broken(), Source(raw)], clock=lambda: NOW).run()
    assert stats["queued"] == 1


def test_untaggable_store_is_skipped(cfg, repo, tg):
    raw = make_raw(store="ajio", url="https://www.ajio.com/x", price=500, mrp=2000)
    assert Pipeline(cfg, repo, tg, [Source(raw)], clock=lambda: NOW).run()["queued"] == 0


def test_price_history_is_not_bloated(cfg, repo):
    pid = repo.upsert_product(make_raw(), NOW)
    assert repo.record_price(pid, 100, None, NOW)
    assert not repo.record_price(pid, 100, None, NOW + 900)  # unchanged, 15 min later
    assert repo.record_price(pid, 95, None, NOW + 1800)  # changed
    assert repo.record_price(pid, 95, None, NOW + 1800 + 7 * 3600)  # unchanged but old row
    assert len(repo.price_history(pid, NOW + DAY)) == 3


def test_drip_posts_one_deal_per_interval(cfg, repo, tg):
    cfg.post_interval_minutes = 5
    raws = [good_deal(repo, store_product_id=f"B0TEST000{i}", url=f"https://www.amazon.in/dp/B0TEST000{i}")
            for i in range(3)]
    pipe = Pipeline(cfg, repo, tg, [Source(*raws)], clock=lambda: NOW)
    pipe.run()
    for d in repo.deals_by_status("pending_review"):
        repo.update_deal(d["id"], status=STATUS_APPROVED)

    assert pipe.run()["posted"] == 1  # first one goes straight out
    pipe.clock = lambda: NOW + 60
    assert pipe.run()["posted"] == 0  # too soon
    pipe.clock = lambda: NOW + 250  # cron fired a little early: within the 60s slack
    assert pipe.run()["posted"] == 1
    pipe.clock = lambda: NOW + 250 + 299
    assert pipe.run()["posted"] == 1  # slack again, and the third deal goes out
    assert len(sent(tg, "@chan")) == 3


def test_without_an_interval_all_approved_deals_post_up_to_the_run_cap(cfg, repo, tg):
    cfg.max_posts_per_run = 2
    raws = [good_deal(repo, store_product_id=f"B0TEST000{i}", url=f"https://www.amazon.in/dp/B0TEST000{i}")
            for i in range(3)]
    pipe = Pipeline(cfg, repo, tg, [Source(*raws)], clock=lambda: NOW)
    pipe.run()
    for d in repo.deals_by_status("pending_review"):
        repo.update_deal(d["id"], status=STATUS_APPROVED)
    assert pipe.run()["posted"] == 2
