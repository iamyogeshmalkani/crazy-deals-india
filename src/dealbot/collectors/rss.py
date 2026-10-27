"""Generic RSS collector for deal feeds.

Prices are scraped from rupee amounts in the title/description (best effort), so
every RSS deal is unverified and goes through human review. Only items whose link
points straight at a store we can tag are kept; redirect/short links are skipped
because we cannot swap in our affiliate identity.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import List, Optional
from urllib.parse import urlparse

import httpx

from dealbot.links import detect_store, extract_asin
from dealbot.models import RawDeal, stable_id

_RUPEE_RE = re.compile(r"(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_MEDIA = "{http://search.yahoo.com/mrss/}content"


def extract_prices(text: str) -> List[int]:
    values = []
    for match in _RUPEE_RE.finditer(text):
        try:
            values.append(int(float(match.group(1).replace(",", ""))))
        except ValueError:
            continue
    return [v for v in values if v > 0]


def _item_image(item: ET.Element) -> Optional[str]:
    enclosure = item.find("enclosure")
    if enclosure is not None and (enclosure.get("type") or "").startswith("image"):
        return enclosure.get("url")
    media = item.find(_MEDIA)
    return media.get("url") if media is not None else None


def parse_feed(xml_text: str, source: str) -> List[RawDeal]:
    deals: List[RawDeal] = []
    root = ET.fromstring(xml_text)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = _TAG_RE.sub(" ", item.findtext("description") or "").strip()
        store = detect_store(link)
        if not title or not store:
            continue
        if store == "amazon":
            product_id = extract_asin(link)
            if not product_id:
                continue
        else:
            parsed = urlparse(link)
            product_id = stable_id(parsed.netloc, parsed.path)

        prices = extract_prices(title) or extract_prices(description)
        price = min(prices) if prices else None
        mrp = max(prices) if len(prices) > 1 and max(prices) > min(prices) else None
        deals.append(RawDeal(
            store=store, source=source, store_product_id=product_id, title=title, url=link,
            price=price, mrp=mrp, image=_item_image(item),
            description=description[:200] or None,
        ))
    return deals


class RssCollector:
    def __init__(self, url: str, client: Optional[httpx.Client] = None):
        self.url = url
        self.name = f"rss:{urlparse(url).hostname}"
        self._client = client or httpx.Client(timeout=30, follow_redirects=True)

    def fetch(self) -> List[RawDeal]:
        resp = self._client.get(self.url, headers={"User-Agent": "dealbot/0.1"})
        resp.raise_for_status()
        return parse_feed(resp.text, self.name)
