"""Parse a deal that a reviewer sends to the bot in a private Telegram chat.

Format (the first line is all that is required, plus a title if the link has none):

    https://www.amazon.in/Some-Product-Name/dp/B0XXXXXXXX  14999  24999
    title: Samsung Galaxy M35 5G (8GB/128GB)      <- only if the link has no product name
    coupon: SAVE100
    bank: Extra 1500 off with HDFC cards
    category: Mobiles
    ends: 2026-10-28 23:59                        <- IST, only if the offer really ends

The numbers after the link are the price you see now and, optionally, the struck-through MRP.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, Optional
from urllib.parse import unquote, urlparse

from dealbot.india import IST
from dealbot.links import detect_store, extract_asin
from dealbot.models import RawDeal

HELP = (
    "Send me an Amazon.in deal like this:\n\n"
    "https://www.amazon.in/Product-Name/dp/B0XXXXXXXX 14999 24999\n"
    "coupon: SAVE100\n"
    "bank: Extra 1500 off with HDFC cards\n"
    "ends: 2026-10-28 23:59\n\n"
    "After the link: the price you see now, then the struck-through MRP (optional).\n"
    "The other lines are optional. Add 'title: ...' if the link has no product name, "
    "and 'category: ...' for a hashtag. 'ends:' is in IST and only for offers that really end.\n"
    "I'll check it and send you a card to approve or reject. Nothing goes to the channel until you approve."
)

_URL_RE = re.compile(r"https?://\S+")
_NUMBER_RE = re.compile(r"^₹?\s*(\d[\d,]*)(?:\.\d+)?$")
_FIELDS = {"title", "coupon", "bank", "category", "ends"}


class IntakeError(Exception):
    """A message that cannot become a deal; the text is safe to show the sender."""


def looks_like_deal(text: str) -> bool:
    lowered = text.lower()
    return lowered.lstrip().startswith("/deal") or ("amazon" in lowered and "http" in lowered)


def _title_from_url(url: str) -> Optional[str]:
    parts = [p for p in urlparse(url).path.split("/") if p]
    for i, part in enumerate(parts):
        if part in ("dp", "product") and i > 0 and parts[i - 1] not in ("gp", "exec", "obidos"):
            slug = unquote(parts[i - 1]).replace("-", " ").strip()
            return slug or None
    return None


def parse_deal_message(text: str) -> RawDeal:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        raise IntakeError(HELP)
    first = re.sub(r"^/deal\S*\s*", "", lines[0], flags=re.IGNORECASE)

    match = _URL_RE.search(first)
    if not match:
        raise IntakeError("I can't find a link in that message.\n\n" + HELP)
    url = match.group(0).rstrip(".,)")
    if detect_store(url) != "amazon":
        raise IntakeError("Only Amazon.in links are supported for now.")
    asin = extract_asin(url)
    if not asin:
        raise IntakeError("I can't read the product code from that link. Send the full amazon.in "
                          "product link (short amzn.to links can't be read).")

    numbers = []
    for token in (first[: match.start()] + " " + first[match.end():]).split():
        m = _NUMBER_RE.match(token)
        if m:
            numbers.append(int(m.group(1).replace(",", "")))
    if not numbers:
        raise IntakeError("Add the price you see on Amazon right now after the link, "
                          "for example: <link> 14999 24999")
    price = numbers[0]
    mrp = numbers[1] if len(numbers) > 1 else None
    if price <= 0:
        raise IntakeError("The price must be more than zero.")
    if mrp is not None and mrp < price:
        raise IntakeError(f"The MRP (₹{mrp}) is lower than the price (₹{price}). Did you swap them?")

    fields: Dict[str, str] = {}
    for line in lines[1:]:
        key, sep, value = line.partition(":")
        if sep and key.strip().lower() in _FIELDS and value.strip():
            fields[key.strip().lower()] = value.strip()

    title = fields.get("title") or _title_from_url(url)
    if not title:
        raise IntakeError("That link has no product name. Add a line like "
                          "'title: Samsung Galaxy M35 5G (8GB/128GB)'.")

    expires_at = None
    if "ends" in fields:
        try:
            expires_at = int(datetime.strptime(fields["ends"], "%Y-%m-%d %H:%M")
                             .replace(tzinfo=IST).timestamp())
        except ValueError:
            raise IntakeError("I can't read the 'ends:' time. Use IST like 'ends: 2026-10-28 23:59'.")

    return RawDeal(
        store="amazon", source="telegram", store_product_id=asin, title=title, url=url,
        price=price, mrp=mrp, category=fields.get("category"), coupon=fields.get("coupon"),
        bank_offer=fields.get("bank"), expires_at=expires_at,
    )
