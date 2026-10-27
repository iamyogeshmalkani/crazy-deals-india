import pytest

from conftest import NOW, make_raw, seed_history
from dealbot.india import IST
from dealbot.intake import IntakeError, looks_like_deal, parse_deal_message
from dealbot.pipeline import Pipeline

URL = "https://www.amazon.in/Samsung-Galaxy-M35-5G/dp/B0ABCDE123?tag=other-21&ref_=x"


def test_parses_price_mrp_and_optional_lines():
    raw = parse_deal_message(
        f"{URL} ₹14,999 24999\ncoupon: SAVE100\nbank: Extra 1500 off with HDFC\n"
        "category: Mobiles\nends: 2026-10-28 23:59")
    assert (raw.store, raw.store_product_id, raw.price, raw.mrp) == ("amazon", "B0ABCDE123", 14999, 24999)
    assert raw.title == "Samsung Galaxy M35 5G"
    assert (raw.coupon, raw.bank_offer, raw.category) == ("SAVE100", "Extra 1500 off with HDFC", "Mobiles")
    from datetime import datetime
    assert raw.expires_at == int(datetime(2026, 10, 28, 23, 59, tzinfo=IST).timestamp())


def test_deal_command_prefix_and_price_only():
    raw = parse_deal_message(f"/deal {URL} 999")
    assert raw.price == 999 and raw.mrp is None and raw.expires_at is None


def test_title_line_overrides_and_fills_in_when_link_has_no_name():
    raw = parse_deal_message("https://www.amazon.in/dp/B0ABCDE123 500\ntitle: My Product")
    assert raw.title == "My Product"
    with pytest.raises(IntakeError, match="no product name"):
        parse_deal_message("https://www.amazon.in/dp/B0ABCDE123 500")


@pytest.mark.parametrize("text, expected", [
    ("hello there", "can't find a link"),
    (f"{URL}", "price you see"),
    (f"{URL} 500 400", "swap them"),
    ("https://www.flipkart.com/p/item 500", "Only Amazon.in"),
    ("https://amzn.to/3abcdef 500", "short amzn.to links"),
    ("https://www.amazon.in/s?k=phones 500", "product code"),
    (f"{URL} 500\nends: tomorrow", "ends:"),
])
def test_bad_input_gets_a_plain_explanation(text, expected):
    with pytest.raises(IntakeError, match=expected):
        parse_deal_message(text)


def test_looks_like_deal():
    assert looks_like_deal(f"{URL} 500") and looks_like_deal("/deal anything")
    assert not looks_like_deal("hello") and not looks_like_deal("https://example.com/x")


# --- through the pipeline ---------------------------------------------------

def message(update_id, text, user=1, chat_type="private"):
    return {"update_id": update_id, "message": {
        "from": {"id": user}, "chat": {"id": user, "type": chat_type}, "text": text}}


def dms(tg):
    return [m for m in tg.outbox if m["method"] == "sendMessage" and m["chat_id"] == "1"]


class NoSource:
    name = "none"

    def fetch(self):
        return []


def test_reviewer_message_becomes_a_review_card(cfg, repo, tg):
    pipe = Pipeline(cfg, repo, tg, [NoSource()], clock=lambda: NOW)
    tg.queued_updates = [message(10, f"{URL} 799 1999")]
    stats = pipe.run()
    assert stats["reviewed"] == 1
    card, reply = dms(tg)
    assert "tag=test-21" in card["text"] and "other-21" not in card["text"]
    assert card["reply_markup"]["inline_keyboard"][0][0]["callback_data"].startswith("ap:")
    assert "Tap Approve" in reply["text"]
    assert len(repo.deals_by_status("pending_review")) == 1


def test_weak_discount_is_explained_and_price_is_still_recorded(cfg, repo, tg):
    pipe = Pipeline(cfg, repo, tg, [NoSource()], clock=lambda: NOW)
    tg.queued_updates = [message(10, f"{URL} 1800 2000")]
    pipe.run()
    (reply,) = dms(tg)
    assert "10% off the MRP is not enough" in reply["text"] and "35%" in reply["text"]
    assert repo.deals_by_status("pending_review") == []
    pid = repo.db.query("SELECT id FROM products")[0]["id"]
    assert [p for _, p in repo.price_history(pid, NOW)] == [1800]  # history keeps building


def test_resending_the_same_product_does_not_duplicate(cfg, repo, tg):
    pipe = Pipeline(cfg, repo, tg, [NoSource()], clock=lambda: NOW)
    tg.queued_updates = [message(10, f"{URL} 799 1999")]
    pipe.run()
    tg.outbox.clear()
    tg.queued_updates = [message(11, f"{URL} 799 1999")]
    assert pipe.run()["reviewed"] == 0
    assert "already waiting" in dms(tg)[0]["text"]
    assert len(repo.deals_by_status("pending_review")) == 1


def test_strangers_and_group_chats_are_ignored(cfg, repo, tg):
    pipe = Pipeline(cfg, repo, tg, [NoSource()], clock=lambda: NOW)
    tg.queued_updates = [message(10, f"{URL} 799 1999", user=999),
                         message(11, f"{URL} 799 1999", chat_type="supergroup"),
                         message(12, "/start", user=999)]
    pipe.run()
    assert dms(tg) == [] and tg.outbox == []
    assert repo.deals_by_status("pending_review") == []


def test_start_shows_help_and_plain_chat_is_ignored(cfg, repo, tg):
    pipe = Pipeline(cfg, repo, tg, [NoSource()], clock=lambda: NOW)
    tg.queued_updates = [message(10, "hello"), message(11, "/start")]
    pipe.run()
    (reply,) = dms(tg)
    assert "Send me an Amazon.in deal" in reply["text"]


def test_a_deal_with_history_is_verified_when_sent_in_chat(cfg, repo, tg):
    raw = make_raw(store_product_id="B0ABCDE123", url="https://www.amazon.in/dp/B0ABCDE123")
    seed_history(repo, raw, [18499, 18299, 17999, 18199, 18499, 17999, 18299, 18199])
    pipe = Pipeline(cfg, repo, tg, [NoSource()], clock=lambda: NOW)
    tg.queued_updates = [message(10, f"{URL} 14999 24999")]
    pipe.run()
    card = dms(tg)[0]
    assert "verified" in card["text"] and "Pichhle 20 din me sabse kam daam" in card["text"]
