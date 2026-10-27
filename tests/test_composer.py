from conftest import NOW, make_raw
from dealbot.composer import compose
from dealbot.models import KIND_OFFER, Verdict

LINK = "https://www.amazon.in/dp/B0TEST0001?tag=test-21"


def verified(**signals) -> Verdict:
    base = {"verified": True, "window_days": 12, "low_in_window": True, "typical_price": 18000}
    base.update(signals)
    return Verdict(True, score=70, verified=True, signals=base)


def test_history_claim_uses_actual_tracked_days_not_a_fixed_90():
    text = compose(make_raw(), verified(window_days=12), LINK, "hi", NOW).channel_text
    assert "Pichhle 12 din me sabse kam daam" in text
    assert "90" not in text


def test_no_signal_means_no_urgency_line():
    unverified = Verdict(True, score=40, verified=False, signals={"listed_discount_pct": 60})
    text = compose(make_raw(price=799, mrp=1999), unverified, LINK, "hi", NOW).channel_text
    assert "⏰" not in text and "📉" not in text and "🏆" not in text
    assert "MRP se 60% off" in text


def test_expiry_creates_deadline_only_when_within_two_days():
    soon = compose(make_raw(expires_at=NOW + 9 * 3600), verified(), LINK, "hi", NOW).channel_text
    assert "⏰ Offer: aaj 11:00 PM tak" in soon
    far = compose(make_raw(expires_at=NOW + 5 * 86400), verified(), LINK, "hi", NOW).channel_text
    assert "⏰" not in far


def test_price_drop_line_comes_from_real_previous_price():
    sig = verified(prev_price=1449, drop_from_prev=150)
    text = compose(make_raw(price=1299, mrp=4999), sig, LINK, "hi", NOW).channel_text
    assert "Kal ₹1,449 tha, ab ₹1,299 — ₹150 gir gaya" in text


def test_every_post_carries_disclosure_and_the_tagged_link():
    for lang in ("hi", "en"):
        text = compose(make_raw(), verified(), LINK, lang, NOW).channel_text
        assert "Affiliate link" in text and LINK in text


def test_amazon_posts_carry_the_associate_statement_and_others_do_not():
    amazon = compose(make_raw(), verified(), LINK, "hi", NOW).channel_text
    assert "As an Amazon Associate I earn from qualifying purchases." in amazon
    flipkart = compose(make_raw(store="flipkart"), verified(), LINK, "hi", NOW).channel_text
    assert "Amazon Associate" not in flipkart


def test_titles_are_html_escaped():
    text = compose(make_raw(title="A <b>&</b> B"), verified(), LINK, "en", NOW).channel_text
    assert "A &lt;b&gt;&amp;&lt;/b&gt; B" in text


def test_review_card_flags_unverified_deals_but_channel_text_does_not():
    unverified = Verdict(True, score=40, verified=False, signals={})
    out = compose(make_raw(), unverified, LINK, "hi", NOW)
    assert "unverified" in out.review_text and "REVIEW" not in out.channel_text


def test_offer_post_and_expired_text():
    raw = make_raw(kind=KIND_OFFER, price=None, mrp=None, title="Big Saving Days",
                   description="Up to 70% off", expires_at=NOW + 3600)
    out = compose(raw, Verdict(True, score=40, signals={}), LINK, "en", NOW)
    assert "OFFER ALERT" in out.channel_text and "⏰ Offer: today till 3:00 PM" in out.channel_text
    assert "<s>Big Saving Days</s>" in out.expired_text and LINK not in out.expired_text
