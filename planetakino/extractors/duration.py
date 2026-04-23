import re
from typing import Optional

_HOURS_RE = re.compile(r"(\d+)\s*год", re.IGNORECASE)
_MINUTES_RE = re.compile(r"(\d+)\s*хв", re.IGNORECASE)
_ISO_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?")


def parse_uk_duration(text: str) -> Optional[int]:
    """Parse '2 год', '1 год 48 хв', '90 хв' → minutes."""
    if not text:
        return None
    h = _HOURS_RE.search(text)
    mm = _MINUTES_RE.search(text)
    if not h and not mm:
        return None
    hours = int(h.group(1)) if h else 0
    minutes = int(mm.group(1)) if mm else 0
    total = hours * 60 + minutes
    return total or None


def parse_iso_duration(text: str) -> Optional[int]:
    """Parse 'PT1H44M' ISO 8601 → minutes."""
    if not text:
        return None
    m = _ISO_RE.fullmatch(text.strip())
    if not m:
        return None
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    total = hours * 60 + minutes
    return total or None


def format_uk_duration(minutes: int) -> str:
    if minutes <= 0:
        return ""
    h, m = divmod(minutes, 60)
    parts = []
    if h:
        parts.append(f"{h} год")
    if m:
        parts.append(f"{m} хв")
    return " ".join(parts)
