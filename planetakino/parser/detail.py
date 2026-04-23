"""Parse a single movie's detail page.

Primary source: JSON-LD Movie schema (server-rendered, clean).
Fallback: scrape DOM for premiere-date strings not present in JSON-LD.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from bs4 import BeautifulSoup

from ..extractors.date_uk import parse_iso_date, parse_uk_day_month
from ..extractors.duration import parse_iso_duration

_AGE_RE = re.compile(r"\b(\d{1,2}\+|PG|Все)\b")


@dataclass
class MovieDetail:
    title_uk: Optional[str] = None
    title_original: Optional[str] = None
    description: Optional[str] = None
    duration_min: Optional[int] = None
    premiere_date: Optional[date] = None
    premiere_date_raw: Optional[str] = None
    age_rating: Optional[str] = None
    genres: List[str] = None
    poster_url: Optional[str] = None
    trailer_url: Optional[str] = None

    def __post_init__(self) -> None:
        if self.genres is None:
            self.genres = []


def _load_jsonld_movie(soup: BeautifulSoup) -> Optional[dict]:
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if isinstance(item, dict) and item.get("@type") == "Movie":
                return item
    return None


def _find_premiere_uk_string(soup: BeautifulSoup) -> Optional[str]:
    """Look for 'У кіно з <date>' or 'прем'єра <date>' text anywhere on the page."""
    text = soup.get_text(" ", strip=True)
    for pat in (
        r"(?:У\s+кіно\s+з|Прем[’']?єра)\s+(\d{1,2}\s+\S+)",
        r"(\d{1,2}\s+(?:січня|лютого|березня|квітня|травня|червня|липня|серпня|вересня|жовтня|листопада|грудня))",
    ):
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def parse_detail(html: str) -> MovieDetail:
    soup = BeautifulSoup(html, "html.parser")
    detail = MovieDetail()

    ld = _load_jsonld_movie(soup)
    if ld:
        detail.title_uk = (ld.get("name") or "").strip() or None
        detail.title_original = (ld.get("alternativeHeadline") or "").strip() or None
        detail.description = (ld.get("description") or "").strip() or None
        detail.duration_min = parse_iso_duration(ld.get("duration", ""))
        iso_date = ld.get("dateCreated") or ld.get("datePublished")
        if iso_date:
            detail.premiere_date = parse_iso_date(iso_date)
        genre = ld.get("genre")
        if isinstance(genre, list):
            detail.genres = [g.strip() for g in genre if g]
        elif isinstance(genre, str):
            detail.genres = [g.strip() for g in genre.split(",") if g.strip()]
        image = ld.get("image")
        if isinstance(image, list) and image:
            detail.poster_url = image[0]
        elif isinstance(image, str):
            detail.poster_url = image
        trailer = ld.get("trailer")
        if isinstance(trailer, dict):
            detail.trailer_url = trailer.get("embedUrl") or trailer.get("url")

    raw_date = _find_premiere_uk_string(soup)
    if raw_date:
        detail.premiere_date_raw = raw_date
        if not detail.premiere_date:
            detail.premiere_date = parse_uk_day_month(raw_date)

    if not detail.age_rating:
        for og in soup.find_all("meta"):
            content = og.get("content") or ""
            m = _AGE_RE.search(content)
            if m:
                detail.age_rating = m.group(1)
                break

    return detail
