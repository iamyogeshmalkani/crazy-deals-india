from datetime import datetime

import httpx

from conftest import NOW
from dealbot.collectors.flipkart import FlipkartOffersCollector, parse_offers
from dealbot.collectors.manual import parse_items
from dealbot.collectors.rss import extract_prices, parse_feed
from dealbot.india import IST
from dealbot.models import KIND_OFFER

FLIPKART_PAYLOAD = {"allOffersList": [
    {"title": "Up to 60% off on Fashion", "description": "Big sale", "category": "fashion",
     "url": "https://dl.flipkart.com/dl/fashion-sale?x=1", "startTime": 1761500000000,
     "endTime": (NOW + 3600) * 1000, "availability": "LIVE",
     "imageUrls": [{"url": "https://img/low.jpg", "resolutionType": "low"},
                   {"url": "https://img/mid.jpg", "resolutionType": "mid"}]},
    {"title": "Sold out offer", "url": "https://dl.flipkart.com/dl/gone", "availability": "OOS"},
    {"title": "", "url": "https://dl.flipkart.com/dl/untitled"},
]}


def test_flipkart_offers_parse():
    deals = parse_offers(FLIPKART_PAYLOAD, "allOffersList", "flipkart_offers")
    assert len(deals) == 2
    first = deals[0]
    assert first.kind == KIND_OFFER and first.price is None
    assert first.expires_at == NOW + 3600  # milliseconds converted to seconds
    assert first.image == "https://img/mid.jpg" and first.in_stock is True
    assert deals[1].in_stock is False and deals[1].expires_at is None


def test_flipkart_collector_sends_auth_headers_and_reads_both_feeds():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers["Fk-Affiliate-Id"],
                     request.headers["Fk-Affiliate-Token"]))
        body = FLIPKART_PAYLOAD if "/all/" in request.url.path else {"dotdList": [
            {"title": "Deal of the day", "url": "https://dl.flipkart.com/dl/dotd",
             "availability": "LIVE"}]}
        return httpx.Response(200, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    deals = FlipkartOffersCollector("aff", "tok", client).fetch()
    assert [p for p, _, _ in seen] == ["/affiliate/offers/v1/all/json", "/affiliate/offers/v1/dotd/json"]
    assert all(i == "aff" and t == "tok" for _, i, t in seen)
    assert len(deals) == 3


RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Samsung M35 5G at ₹14,999 (MRP ₹24,999)</title>
 <link>https://www.amazon.in/dp/B0ABCDE123?tag=other-21</link>
 <description>&lt;p&gt;Great phone&lt;/p&gt;</description>
 <enclosure url="https://img/x.jpg" type="image/jpeg"/></item>
<item><title>Shoes Rs. 799</title><link>https://bit.ly/redirect</link></item>
<item><title>Kurta ₹499 </title><link>https://www.myntra.com/kurta/123</link></item>
</channel></rss>"""


def test_rss_keeps_taggable_store_links_only_and_extracts_prices():
    deals = parse_feed(RSS, "rss:test")
    assert [d.store for d in deals] == ["amazon", "myntra"]
    phone = deals[0]
    assert (phone.price, phone.mrp, phone.store_product_id) == (14999, 24999, "B0ABCDE123")
    assert phone.image == "https://img/x.jpg" and phone.description == "Great phone"
    assert (deals[1].price, deals[1].mrp) == (499, None)


def test_extract_prices_handles_formats():
    assert extract_prices("₹1,299 or Rs. 999 or INR 2499.50") == [1299, 999, 2499]
    assert extract_prices("no price here") == []


def test_manual_items_detect_store_and_asin():
    deals = parse_items([
        {"title": "A", "url": "https://www.amazon.in/dp/B0ABCDE123", "price": 100, "mrp": 200,
         "expires_at": "2026-10-28T23:59:00+05:30"},
        {"title": "no url"},
    ], "manual")
    assert len(deals) == 1
    assert deals[0].store == "amazon" and deals[0].store_product_id == "B0ABCDE123"
    assert deals[0].expires_at == int(datetime(2026, 10, 28, 23, 59, tzinfo=IST).timestamp())
