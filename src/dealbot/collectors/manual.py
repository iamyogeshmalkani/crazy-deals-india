"""Hand-picked deals from a JSON file, run through the same scoring/review pipeline.

Useful on day one, before any API access is approved: look up a product yourself,
add its URL and current price, and let the bot handle history, scoring, tagging,
review, and posting. Format: see data/sample_deals.json.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dealbot.links import detect_store, extract_asin
from dealbot.models import RawDeal, stable_id


def _expires(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return int(datetime.fromisoformat(str(value)).timestamp())  # e.g. 2026-10-28T23:59:00+05:30


def parse_items(items: List[Dict[str, Any]], source: str) -> List[RawDeal]:
    deals: List[RawDeal] = []
    for item in items:
        url = item.get("url", "")
        store = item.get("store") or detect_store(url)
        if not store or not item.get("title") or not url:
            continue
        product_id = item.get("id") or (extract_asin(url) if store == "amazon" else None) \
            or stable_id(store, url)
        deals.append(RawDeal(
            store=store, source=source, store_product_id=str(product_id), title=item["title"],
            url=url, price=item.get("price"), mrp=item.get("mrp"), image=item.get("image"),
            category=item.get("category"), coupon=item.get("coupon"),
            bank_offer=item.get("bank_offer"), expires_at=_expires(item.get("expires_at")),
            in_stock=item.get("in_stock"),
        ))
    return deals


class ManualCollector:
    def __init__(self, path: str):
        self.path = Path(path)
        self.name = "manual"

    def fetch(self) -> List[RawDeal]:
        if not self.path.is_file():
            return []
        return parse_items(json.loads(self.path.read_text()), self.name)
