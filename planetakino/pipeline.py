"""Full fetch pipeline: listing → detail for each new/stale movie → persist → export."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from .config import BASE_URL, CINEMAS, DB_PATH, DETAIL_CACHE_DAYS, EXPORT_PATH
from .db.store import Store
from .http import HttpClient
from .parser.detail import parse_detail
from .parser.listing import ListingMovie, parse_listing, parse_schedule

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _should_refetch_detail(existing_row, cache_days: int) -> bool:
    if existing_row is None or not existing_row["detail_fetched_at"]:
        return True
    try:
        when = datetime.fromisoformat(existing_row["detail_fetched_at"])
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - when > timedelta(days=cache_days)


def fetch_cinema(cinema_key: str = "odesa_kotovsky",
                 http: Optional[HttpClient] = None,
                 store: Optional[Store] = None,
                 detail_cache_days: int = DETAIL_CACHE_DAYS) -> dict:
    cinema = CINEMAS[cinema_key]
    slug = cinema["slug"]
    own_http = http is None
    own_store = store is None
    http = http or HttpClient()
    store = store or Store(DB_PATH)

    report = {"cinema": cinema_key, "sections": {}, "errors": []}

    try:
        sections = [
            ("now", f"{BASE_URL}/schedule/?cinema={slug}", parse_schedule),
            ("soon", f"{BASE_URL}/coming-soon/?cinema={slug}", parse_listing),
        ]

        all_listing: list[ListingMovie] = []
        for section, url, parser_fn in sections:
            started = _now_iso()
            html = http.get_html(url)
            if not html:
                report["errors"].append(f"{section}: no HTML")
                store.log_fetch(slug, section, None, 0, "no HTML", started)
                continue
            movies = parser_fn(html, section=section)
            store.log_fetch(slug, section, 200, len(movies), None, started)
            report["sections"][section] = len(movies)
            all_listing.extend(movies)
            log.info("listing[%s] found %d movies", section, len(movies))

        seen_ids = {m.movie_id: m for m in all_listing}

        # Detail enrichment
        enriched = 0
        for movie_id, listing in seen_ids.items():
            existing = store.get_movie(slug, movie_id)
            if not _should_refetch_detail(existing, detail_cache_days):
                # Refresh section/poster/pre-premiere from listing only
                payload = _merge_listing_with_existing(listing, existing)
                store.upsert_movie(slug, payload)
                continue

            detail_html = http.get_html(listing.url)
            detail = parse_detail(detail_html) if detail_html else None
            if detail:
                enriched += 1
            payload = _merge_listing_with_detail(listing, detail)
            store.upsert_movie(slug, payload)

        report["enriched"] = enriched
        report["total"] = len(seen_ids)
    finally:
        if own_http:
            http.close()
        if own_store:
            store.close()

    return report


def _merge_listing_with_existing(listing: ListingMovie, existing) -> dict:
    return {
        "movie_id": listing.movie_id,
        "slug": listing.slug,
        "url": listing.url,
        "section": listing.section,
        "title_uk": existing["title_uk"] or listing.title_uk,
        "title_original": existing["title_original"],
        "description": existing["description"],
        "premiere_date": existing["premiere_date"],
        "duration_min": existing["duration_min"],
        "age_rating": existing["age_rating"],
        "genres": json.loads(existing["genres_json"] or "[]"),
        "formats": listing.formats or json.loads(existing["formats_json"] or "[]"),
        "is_pre_premiere": bool(listing.is_pre_premiere or existing["is_pre_premiere"]),
        "poster_url": listing.poster_url or existing["poster_url"],
        "trailer_url": existing["trailer_url"],
        "detail_fetched_at": existing["detail_fetched_at"],
    }


def _merge_listing_with_detail(listing: ListingMovie, detail) -> dict:
    return {
        "movie_id": listing.movie_id,
        "slug": listing.slug,
        "url": listing.url,
        "section": listing.section,
        "title_uk": (detail.title_uk if detail else None) or listing.title_uk,
        "title_original": detail.title_original if detail else None,
        "description": detail.description if detail else None,
        "premiere_date": detail.premiere_date.isoformat() if (detail and detail.premiere_date) else None,
        "duration_min": detail.duration_min if detail else None,
        "age_rating": detail.age_rating if detail else None,
        "genres": detail.genres if detail else [],
        "formats": listing.formats,
        "is_pre_premiere": listing.is_pre_premiere,
        "poster_url": (detail.poster_url if detail else None) or listing.poster_url,
        "trailer_url": detail.trailer_url if detail else None,
        "detail_fetched_at": _now_iso() if detail else None,
    }


def export_json(cinema_key: str = "odesa_kotovsky",
                path: Path = EXPORT_PATH,
                store: Optional[Store] = None) -> Path:
    own = store is None
    store = store or Store(DB_PATH)
    try:
        cinema = CINEMAS[cinema_key]
        rows = store.all_movies(cinema["slug"])
        movies = [_row_to_dict(r) for r in rows]
        payload = {
            "generated_at": _now_iso(),
            "cinema": {"key": cinema_key, **cinema},
            "counts": {
                "total": len(movies),
                "now": sum(1 for m in movies if m["section"] == "now"),
                "soon": sum(1 for m in movies if m["section"] == "soon"),
                "pre_premiere": sum(1 for m in movies if m["is_pre_premiere"]),
            },
            "movies": movies,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        if own:
            store.close()
    return path


def _row_to_dict(row) -> dict:
    return {
        "movie_id": row["movie_id"],
        "slug": row["slug"],
        "url": row["url"],
        "section": row["section"],
        "title_uk": row["title_uk"],
        "title_original": row["title_original"],
        "description": row["description"],
        "premiere_date": row["premiere_date"],
        "duration_min": row["duration_min"],
        "age_rating": row["age_rating"],
        "genres": json.loads(row["genres_json"] or "[]"),
        "formats": json.loads(row["formats_json"] or "[]"),
        "is_pre_premiere": bool(row["is_pre_premiere"]),
        "poster_url": row["poster_url"],
        "trailer_url": row["trailer_url"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "detail_fetched_at": row["detail_fetched_at"],
    }
