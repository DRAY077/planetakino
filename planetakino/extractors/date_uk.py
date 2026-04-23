import re
from datetime import date, datetime
from typing import Optional

UK_MONTHS = {
    "січня": 1, "лютого": 2, "березня": 3, "квітня": 4,
    "травня": 5, "червня": 6, "липня": 7, "серпня": 8,
    "вересня": 9, "жовтня": 10, "листопада": 11, "грудня": 12,
}

_DAY_MONTH_RE = re.compile(
    r"(\d{1,2})\s+(" + "|".join(UK_MONTHS.keys()) + r")",
    re.IGNORECASE,
)

_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def parse_uk_day_month(text: str, today: Optional[date] = None) -> Optional[date]:
    """Parse '30 квітня' style strings, picking the correct year.

    If the resulting date is > 30 days in the past relative to `today`,
    roll to next year — premiere dates in listings always point forward.
    """
    if not text:
        return None
    m = _DAY_MONTH_RE.search(text)
    if not m:
        return None
    day = int(m.group(1))
    month = UK_MONTHS[m.group(2).lower()]
    today = today or date.today()
    year = today.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return None
    if (today - candidate).days > 30:
        try:
            candidate = date(year + 1, month, day)
        except ValueError:
            return None
    return candidate


def parse_iso_date(text: str) -> Optional[date]:
    if not text:
        return None
    m = _ISO_RE.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def format_uk_day_month(d: date) -> str:
    reverse = {v: k for k, v in UK_MONTHS.items()}
    return f"{d.day} {reverse[d.month]}"
