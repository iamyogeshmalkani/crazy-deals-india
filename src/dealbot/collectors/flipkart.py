"""Flipkart Affiliate Offer APIs (all offers + deals of the day).

Endpoints and fields per https://affiliate.flipkart.com/api-docs/af_offer_ref.html .
The API is documented as beta and returns offers (title, expiry, stock status),
not product prices, so these become `offer` deals with a real expiry time.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from dealbot.models import KIND_OFFER, RawDeal, stable_id

BASE = "https://affiliate-api.flipkart.net/affiliate/offers/v1"
ENDPOINTS = (("all", "allOffersList"), ("dotd", "dotdList"))
_IMAGE_PREFERENCE = ("mid", "default", "high", "low")


def _epoch_seconds(value: Any) -> Optional[int]:
    """Docs show millisecond Unix times; accept seconds too."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return n // 1000 if n > 10**11 else n


def _pick_image(images: Any) -> Optional[str]:
    if not isinstance(images, list):
        return None
    by_type = {i.get("resolutionType"): i.get("url") for i in images if isinstance(i, dict)}
    for kind in _IMAGE_PREFERENCE:
        if by_type.get(kind):
            return by_type[kind]
    return next((u for u in by_type.values() if u), None)


def parse_offers(payload: Dict[str, Any], list_key: str, source: str) -> List[RawDeal]:
    deals: List[RawDeal] = []
    for item in payload.get(list_key) or []:
        title, url = (item.get("title") or "").strip(), (item.get("url") or "").strip()
        if not title or not url:
            continue
        parsed = urlparse(url)
        deals.append(RawDeal(
            store="flipkart",
            source=source,
            store_product_id=stable_id(parsed.netloc, parsed.path),
            title=title,
            url=url,
            kind=KIND_OFFER,
            image=_pick_image(item.get("imageUrls")),
            category=item.get("category") or None,
            description=(item.get("description") or "").strip() or None,
            expires_at=_epoch_seconds(item.get("endTime")),
            in_stock=None if "availability" not in item else item["availability"] == "LIVE",
        ))
    return deals


class FlipkartOffersCollector:
    name = "flipkart_offers"

    def __init__(self, affiliate_id: str, token: str, client: Optional[httpx.Client] = None):
        self._headers = {"Fk-Affiliate-Id": affiliate_id, "Fk-Affiliate-Token": token}
        self._client = client or httpx.Client(timeout=30)

    def fetch(self) -> List[RawDeal]:
        deals: List[RawDeal] = []
        for path, list_key in ENDPOINTS:
            resp = self._client.get(f"{BASE}/{path}/json", headers=self._headers)
            resp.raise_for_status()
            deals.extend(parse_offers(resp.json(), list_key, self.name))
        return deals
