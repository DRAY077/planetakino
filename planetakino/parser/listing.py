"""Parse movie listings from planetakino.ua (both 'Now Showing' and 'Coming Soon').

The listing DOM only gives us: id, slug, Ukrainian title, poster URL.
Everything else (duration, original title, premiere date, age rating) is
fetched later from each movie's detail page via JSON-LD.

Pre-premiere flag and format tags (3D/IMAX) are detected by searching
the raw HTML around each card — they appear as plain text strings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from bs4 import BeautifulSoup, Tag

PRE_PREMIERE_TITLE_RE = re.compile(r"ДОПРЕМ['’‛ʼ]?ЄР", re.IGNORECASE)
FORMAT_TOKENS = ("IMAX", "3D", "RE'LUX", "RE’LUX", "Cinetech+", "4DX")


@dataclass
class ListingMovie:
    movie_id: str
    slug: str
    url: str
    title_uk: str
    poster_url: Optional[str]
    is_pre_premiere: bool = False
    formats: List[str] = field(default_factory=list)
    section: str = ""


def _poster_url(card: Tag) -> Optional[str]:
    source = card.find("source")
    if source and source.get("srcset"):
        return source["srcset"].split(",")[0].strip().split(" ")[0]
    img = card.find("img")
    if img:
        return img.get("src") or img.get("data-src")
    return None


def _title(card: Tag) -> str:
    img = card.find("img")
    if img and img.get("alt"):
        return img["alt"].strip()
    return ""


def _detect_flags(card_html: str, title: str) -> tuple[bool, List[str]]:
    # ДОПРЕМ'ЄРА lives in Nuxt state, not in SSR HTML — but pre-premiere movies
    # reliably have "ДОПРЕМ'ЄРНИЙ ПОКАЗ" in their Ukrainian title.
    is_pre = bool(PRE_PREMIERE_TITLE_RE.search(title or ""))
    formats = [tok for tok in FORMAT_TOKENS if tok in card_html]
    formats = sorted(set(formats), key=formats.index)
    return is_pre, formats


def parse_listing(html: str, section: str) -> List[ListingMovie]:
    """Extract all movie cards from a 'coming soon' listing page.

    Selector: <a data-component-name="BaseMovieCardItem">.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select('a[data-component-name="BaseMovieCardItem"]')
    seen: dict[str, ListingMovie] = {}

    for card in cards:
        movie_id = card.get("id") or ""
        href = card.get("href") or ""
        if not movie_id or not href:
            continue
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        card_html = str(card)
        title_uk = _title(card)
        is_pre, formats = _detect_flags(card_html, title_uk)

        movie = ListingMovie(
            movie_id=movie_id,
            slug=slug,
            url=f"https://planetakino.ua{href}" if href.startswith("/") else href,
            title_uk=title_uk,
            poster_url=_poster_url(card),
            is_pre_premiere=is_pre,
            formats=formats,
            section=section,
        )
        seen[movie_id] = movie

    return list(seen.values())


def parse_schedule(html: str, section: str = "now") -> List[ListingMovie]:
    """Extract movies from /schedule/ page.

    Each movie is wrapped in <div data-component-name="MovieWithSessionsCard">.
    Contains multiple <a href="/movie/..."> (mobile + desktop variants) —
    we dedupe by movie_id (the Base64 id attribute on the outer <a>).
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select('div[data-component-name="MovieWithSessionsCard"]')
    seen: dict[str, ListingMovie] = {}

    for card in cards:
        link = card.find("a", id=True, href=True)
        if not link:
            # Some variants place id on a child <a>; pick any id-bearing link
            link = next((a for a in card.find_all("a", href=True) if a.get("id")), None)
        if not link:
            # As last resort, take the first /movie/ link and synthesise an id from slug
            any_link = card.find("a", href=True)
            if not any_link:
                continue
            href = any_link["href"]
            slug = href.rstrip("/").rsplit("/", 1)[-1]
            movie_id = f"slug:{slug}"
        else:
            movie_id = link["id"]
            href = link["href"]
            slug = href.rstrip("/").rsplit("/", 1)[-1]

        if movie_id in seen:
            continue

        title_uk = _title(card)
        card_html = str(card)
        is_pre, formats = _detect_flags(card_html, title_uk)

        seen[movie_id] = ListingMovie(
            movie_id=movie_id,
            slug=slug,
            url=f"https://planetakino.ua{href}" if href.startswith("/") else href,
            title_uk=title_uk,
            poster_url=_poster_url(card),
            is_pre_premiere=is_pre,
            formats=formats,
            section=section,
        )

    return list(seen.values())
