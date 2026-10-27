import pytest

from dealbot.config import Config
from dealbot.links import UntaggedLinkError, detect_store, extract_asin, is_tagged, tag_url


def test_amazon_link_is_rebuilt_with_only_our_tag(cfg):
    dirty = "https://www.amazon.in/Some-Title/dp/B0ABCDE123/ref=sr_1_1?tag=someone-else-21&th=1"
    assert tag_url("amazon", dirty, cfg) == "https://www.amazon.in/dp/B0ABCDE123?tag=test-21"


def test_amazon_needs_tag_and_asin():
    with pytest.raises(UntaggedLinkError):
        tag_url("amazon", "https://www.amazon.in/dp/B0ABCDE123", Config())
    with pytest.raises(UntaggedLinkError):
        tag_url("amazon", "https://www.amazon.in/s?k=phones", Config(amazon_tag="x-21"))


def test_flipkart_replaces_foreign_affid(cfg):
    url = "https://www.flipkart.com/p/item?pid=ABC&affid=thief&affExtParam1=z"
    tagged = tag_url("flipkart", url, cfg)
    assert "affid=testaff" in tagged and "thief" not in tagged and "pid=ABC" in tagged


def test_other_stores_use_network_template_or_are_refused():
    cfg = Config(wrap_templates={"myntra": "https://net.example/go?id=7&url={url}"})
    wrapped = tag_url("myntra", "https://www.myntra.com/shirt?a=1", cfg)
    assert wrapped.startswith("https://net.example/go?id=7&url=https%3A%2F%2Fwww.myntra.com")
    with pytest.raises(UntaggedLinkError):
        tag_url("ajio", "https://www.ajio.com/x", cfg)


def test_is_tagged(cfg):
    assert is_tagged("https://www.amazon.in/dp/B0ABCDE123?tag=test-21", cfg)
    assert not is_tagged("https://www.amazon.in/dp/B0ABCDE123", cfg)
    assert not is_tagged("https://www.amazon.in/dp/B0ABCDE123?tag=other-21", cfg)
    assert is_tagged("https://www.flipkart.com/p?affid=testaff", cfg)
    assert not is_tagged("https://www.flipkart.com/p", cfg)
    wrapped = Config(wrap_templates={"myntra": "https://net.example/go?id=7&url={url}"})
    assert is_tagged("https://net.example/go?id=7&url=abc", wrapped)
    assert not is_tagged("https://www.myntra.com/shirt", wrapped)


def test_store_and_asin_detection():
    assert detect_store("https://www.amazon.in/dp/B0ABCDE123") == "amazon"
    assert detect_store("https://dl.flipkart.com/s/abc") == "flipkart"
    assert detect_store("https://bit.ly/xyz") is None
    assert extract_asin("https://www.amazon.in/gp/product/B0ABCDE123?x=1") == "B0ABCDE123"
    assert extract_asin("https://www.amazon.in/s?k=x") is None
