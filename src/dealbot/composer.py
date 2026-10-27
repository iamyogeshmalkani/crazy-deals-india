"""Turn a scored deal into Telegram HTML messages.

FOMO policy: every urgency or scarcity line is generated from a real signal in
`Verdict.signals` or from the source data. If there is no signal, the post simply
has no urgency line. Nothing is ever invented.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from dealbot.india import format_deadline, format_inr
from dealbot.models import KIND_OFFER, RawDeal, Verdict

URGENCY_WINDOW = 48 * 3600  # only mention an expiry that is within two days

# Required on Amazon Associates properties; shown on every post that links to Amazon.
AMAZON_ASSOCIATE_STATEMENT = "As an Amazon Associate I earn from qualifying purchases."


@dataclass
class Composed:
    channel_text: str
    review_text: str
    expired_text: str


_T = {
    "hi": {
        "deal": "LOOT DEAL",
        "offer": "OFFER ALERT",
        "buy": "🛒 Abhi kharido",
        "buy_link": "Yahan se kharido",
        "coupon": "Coupon",
        "typical_pct": "aam daam se {pct}% kam",
        "mrp_pct": "MRP se {pct}% off",
        "low": "🏆 Pichhle {days} din me sabse kam daam",
        "near_low": "📊 Pichhle {days} din ke sabse kam daam ke bahut kareeb",
        "typical": "📊 Aam daam: {price}",
        "drop": "📉 Kal {prev} tha, ab {now} — {diff} gir gaya",
        "deadline": "⏰ Offer: {when}",
        "disclosure": "ℹ️ Affiliate link: aapko koi extra kharch nahi, humein commission mil sakta hai. "
                      "Daam post ke samay ke hain, badal sakte hain.",
        "ended": "❌ <b>DEAL KHATAM</b>",
        "ended_hint": "Agli deal ke liye channel dekhte rehna 🔔",
    },
    "en": {
        "deal": "HOT DEAL",
        "offer": "OFFER ALERT",
        "buy": "🛒 Buy now",
        "buy_link": "Buy here",
        "coupon": "Coupon",
        "typical_pct": "{pct}% below usual price",
        "mrp_pct": "{pct}% off MRP",
        "low": "🏆 Lowest price in {days} days of tracking",
        "near_low": "📊 Close to the lowest price in {days} days",
        "typical": "📊 Usual price: {price}",
        "drop": "📉 Was {prev} yesterday, now {now} — down {diff}",
        "deadline": "⏰ Offer: {when}",
        "disclosure": "ℹ️ Affiliate link: no extra cost to you, we may earn a commission. "
                      "Price as of posting time; it can change.",
        "ended": "❌ <b>DEAL ENDED</b>",
        "ended_hint": "Stay tuned for the next one 🔔",
    },
}


def buy_label(lang: str) -> str:
    return _T.get(lang, _T["hi"])["buy"]


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _hashtag(category: Optional[str]) -> str:
    if not category:
        return ""
    tag = re.sub(r"[^0-9A-Za-z]", "", category.title())
    return f" | #{tag}" if tag else ""


def _pct(part: float, whole: float) -> int:
    return int(round(part / whole * 100)) if whole else 0


def _urgency_line(raw: RawDeal, signals: Dict[str, Any], now: int, t: Dict[str, str],
                  lang: str) -> Optional[str]:
    """At most one urgency line, picked from real signals in priority order."""
    if raw.expires_at and 0 < raw.expires_at - now <= URGENCY_WINDOW:
        return t["deadline"].format(when=format_deadline(raw.expires_at, now, lang))
    prev, diff = signals.get("prev_price"), signals.get("drop_from_prev")
    if prev and diff and raw.price:
        return t["drop"].format(prev=format_inr(prev), now=format_inr(raw.price),
                                diff=format_inr(diff))
    return None


def _price_line(raw: RawDeal, signals: Dict[str, Any], t: Dict[str, str]) -> str:
    line = f"💰 <b>{format_inr(raw.price or 0)}</b>"
    if raw.mrp and raw.price and raw.mrp > raw.price:
        line += f" <s>{format_inr(raw.mrp)}</s>"
    typical = signals.get("typical_price")
    if signals.get("verified") and typical and raw.price and typical > raw.price:
        pct = _pct(typical - raw.price, typical)
        if pct >= 1:
            line += " (" + t["typical_pct"].format(pct=pct) + ")"
    elif raw.mrp and raw.price and raw.mrp > raw.price:
        pct = _pct(raw.mrp - raw.price, raw.mrp)
        if pct >= 1:
            line += " (" + t["mrp_pct"].format(pct=pct) + ")"
    return line


def _history_lines(raw: RawDeal, signals: Dict[str, Any], t: Dict[str, str]) -> list:
    if not signals.get("verified"):
        return []
    lines = []
    days = signals.get("window_days") or 0
    if signals.get("low_in_window"):
        lines.append(t["low"].format(days=days))
    else:
        lines.append(t["near_low"].format(days=days))
    typical = signals.get("typical_price")
    if typical and raw.price and typical > raw.price:
        lines.append(t["typical"].format(price=format_inr(typical)))
    return lines


def compose(raw: RawDeal, verdict: Verdict, link: str, lang: str, now: int) -> Composed:
    t = _T.get(lang, _T["hi"])
    def esc(text: str) -> str:
        return html.escape(text, quote=False)  # Telegram HTML needs only & < >

    signals = verdict.signals
    tag = _hashtag(raw.category)
    safe_link = html.escape(link, quote=True)

    lines = []
    if raw.kind == KIND_OFFER:
        lines.append(f"🎁 <b>{t['offer']}</b>{tag}")
        lines.append("")
        lines.append(f"<b>{esc(_short(raw.title, 90))}</b>")
        if raw.description:
            lines.append(esc(_short(raw.description, 160)))
        if raw.expires_at and 0 < raw.expires_at - now <= URGENCY_WINDOW:
            lines.append("")
            lines.append(t["deadline"].format(when=format_deadline(raw.expires_at, now, lang)))
    else:
        lines.append(f"🔥 <b>{t['deal']}</b>{tag}")
        lines.append("")
        lines.append(f"<b>{esc(_short(raw.title, 90))}</b>")
        lines.append("")
        lines.append(_price_line(raw, signals, t))
        lines.extend(_history_lines(raw, signals, t))
        if raw.coupon:
            lines.append(f"🎟️ {t['coupon']}: <code>{esc(raw.coupon)}</code>")
        if raw.bank_offer:
            lines.append(f"🏦 {esc(_short(raw.bank_offer, 100))}")
        urgency = _urgency_line(raw, signals, now, t, lang)
        if urgency:
            lines.append(urgency)

    lines.append("")
    lines.append(f'🛒 <a href="{safe_link}">{t["buy_link"]}</a>')
    disclosure = t["disclosure"]
    if raw.store == "amazon":
        disclosure = f"{disclosure} {AMAZON_ASSOCIATE_STATEMENT}"
    lines.append("")
    lines.append(f"<i>{disclosure}</i>")
    channel_text = "\n".join(lines)

    status = "verified ✅" if verdict.verified else "unverified ⚠️ (no price history)"
    review_text = (
        f"{channel_text}\n\n🧪 <i>REVIEW • score {verdict.score} • {status} • {esc(raw.store)}"
        f" • via {esc(raw.source)}</i>"
    )
    expired_text = (
        f"{t['ended']}\n\n<s>{esc(_short(raw.title, 90))}</s>\n\n{t['ended_hint']}"
    )
    return Composed(channel_text, review_text, expired_text)
