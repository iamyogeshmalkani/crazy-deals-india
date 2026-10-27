"""Affiliate link tagging. Every outbound link must pass through here.

The publisher refuses to send a link that `is_tagged` rejects, so an untagged
link can never earn nothing silently.
"""

from __future__ import annotations

import re
from typing import Dict, Optional
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

from dealbot.config import Config

_ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d|exec/obidos/ASIN)/([A-Z0-9]{10})(?:[/?]|$)")


class UntaggedLinkError(Exception):
    """Raised when no affiliate identity is configured for a store."""


def detect_store(url: str) -> Optional[str]:
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("amazon.in") or host in ("amzn.in", "amzn.to"):
        return "amazon"
    if host.endswith("flipkart.com") or host.endswith("fkrt.it") or host.endswith("fkrt.cc"):
        return "flipkart"
    if host.endswith("myntra.com"):
        return "myntra"
    if host.endswith("ajio.com"):
        return "ajio"
    if host.endswith("croma.com"):
        return "croma"
    return None


def extract_asin(url: str) -> Optional[str]:
    match = _ASIN_RE.search(urlparse(url).path + "/")
    return match.group(1) if match else None


def tag_url(store: str, url: str, cfg: Config) -> str:
    """Return the affiliate version of `url` for `store`, or raise UntaggedLinkError.

    Existing affiliate parameters from the source are removed, so another
    publisher's tag can never leak into our posts.
    """
    if store == "amazon":
        if not cfg.amazon_tag:
            raise UntaggedLinkError("AMAZON_TAG is not set")
        asin = extract_asin(url)
        if not asin:
            raise UntaggedLinkError(f"cannot find an ASIN in {url}")
        return f"https://www.amazon.in/dp/{asin}?{urlencode({'tag': cfg.amazon_tag})}"

    if store == "flipkart":
        if cfg.flipkart_affid:
            parts = urlparse(url)
            query = {
                k: v
                for k, v in parse_qs(parts.query, keep_blank_values=True).items()
                if not k.lower().startswith("aff")
            }
            query["affid"] = [cfg.flipkart_affid]
            return urlunparse(parts._replace(query=urlencode(query, doseq=True)))

    template = cfg.wrap_templates.get(store)
    if template:
        return template.replace("{url}", quote(url, safe=""))

    raise UntaggedLinkError(f"no affiliate identity configured for store '{store}'")


def is_tagged(url: str, cfg: Config) -> bool:
    """True only if `url` carries one of our affiliate identities."""
    parts = urlparse(url)
    query: Dict[str, list] = parse_qs(parts.query)
    store = detect_store(url)
    if store == "amazon":
        return bool(cfg.amazon_tag) and query.get("tag") == [cfg.amazon_tag]
    if store == "flipkart":
        return bool(cfg.flipkart_affid) and query.get("affid") == [cfg.flipkart_affid]
    for template in cfg.wrap_templates.values():
        prefix = template.split("{url}", 1)[0]
        if prefix and url.startswith(prefix):
            return True
    return False
