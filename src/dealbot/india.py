"""India-specific formatting and time helpers (INR grouping, IST)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")


def format_inr(amount: int) -> str:
    """Format rupees with Indian digit grouping: 149999 -> ₹1,49,999."""
    n = int(round(amount))
    sign = "-" if n < 0 else ""
    digits = str(abs(n))
    if len(digits) <= 3:
        return f"{sign}₹{digits}"
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{sign}₹{','.join(groups + [tail])}"


def to_ist(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, IST)


def is_quiet_hours(now_ts: int, start_hour: int, end_hour: int) -> bool:
    """True when IST hour is in [start_hour, end_hour). Handles wrap past midnight."""
    hour = to_ist(now_ts).hour
    if start_hour <= end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def ist_day_start(now_ts: int) -> int:
    local = to_ist(now_ts)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp())


def _clock(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def format_deadline(expires_ts: int, now_ts: int, lang: str = "hi") -> str:
    """Human deadline such as 'aaj 11:59 PM tak'. Built only from the real expiry time."""
    remaining = expires_ts - now_ts
    exp = to_ist(expires_ts)
    now = to_ist(now_ts)
    if 0 < remaining < 3600:
        minutes = max(1, remaining // 60)
        return f"sirf {minutes} min bache" if lang == "hi" else f"only {minutes} min left"
    day_gap = (exp.date() - now.date()).days
    clock = _clock(exp)
    if day_gap == 0:
        return f"aaj {clock} tak" if lang == "hi" else f"today till {clock}"
    if day_gap == 1:
        return f"kal {clock} tak" if lang == "hi" else f"tomorrow till {clock}"
    date = f"{exp.day} {exp.strftime('%b')}"
    return f"{date} tak" if lang == "hi" else f"till {date}"
