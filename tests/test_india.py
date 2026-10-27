from datetime import datetime

from conftest import NOW
from dealbot.india import IST, format_deadline, format_inr, ist_day_start, is_quiet_hours


def test_inr_uses_indian_grouping():
    assert format_inr(0) == "₹0"
    assert format_inr(999) == "₹999"
    assert format_inr(1299) == "₹1,299"
    assert format_inr(24999) == "₹24,999"
    assert format_inr(149999) == "₹1,49,999"
    assert format_inr(1234567) == "₹12,34,567"
    assert format_inr(10000000) == "₹1,00,00,000"


def test_quiet_hours():
    at = lambda h: int(datetime(2026, 10, 27, h, 30, tzinfo=IST).timestamp())
    assert is_quiet_hours(at(0), 0, 7)
    assert is_quiet_hours(at(6), 0, 7)
    assert not is_quiet_hours(at(7), 0, 7)
    assert not is_quiet_hours(at(23), 0, 7)
    assert is_quiet_hours(at(23), 23, 6)  # window wrapping midnight
    assert is_quiet_hours(at(2), 23, 6)


def test_ist_day_start():
    assert ist_day_start(NOW) == int(datetime(2026, 10, 27, 0, 0, tzinfo=IST).timestamp())


def test_deadline_is_built_from_the_real_expiry():
    assert format_deadline(NOW + 600, NOW) == "sirf 10 min bache"
    assert format_deadline(NOW + 9 * 3600, NOW) == "aaj 11:00 PM tak"
    assert format_deadline(NOW + 20 * 3600, NOW) == "kal 10:00 AM tak"
    assert format_deadline(NOW + 5 * 86400, NOW) == "1 Nov tak"
    assert format_deadline(NOW + 9 * 3600, NOW, "en") == "today till 11:00 PM"
