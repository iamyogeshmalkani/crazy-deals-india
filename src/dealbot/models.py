"""Core data types shared across collectors, scorer, composer, and publisher."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

KIND_PRICE = "price"  # we know the current price
KIND_OFFER = "offer"  # a store offer/coupon page without a product price


@dataclass
class RawDeal:
    """A deal as reported by a source, before scoring. Prices are whole rupees."""

    store: str  # amazon | flipkart | myntra | ...
    source: str  # collector name
    store_product_id: str
    title: str
    url: str
    kind: str = KIND_PRICE
    price: Optional[int] = None
    mrp: Optional[int] = None
    image: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    coupon: Optional[str] = None
    bank_offer: Optional[str] = None
    expires_at: Optional[int] = None  # unix seconds
    in_stock: Optional[bool] = None


@dataclass
class Verdict:
    ok: bool
    reason: str = ""
    score: int = 0
    verified: bool = False
    signals: Dict[str, Any] = field(default_factory=dict)


def stable_id(*parts: str) -> str:
    """Short stable id for sources that don't give a product id."""
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
