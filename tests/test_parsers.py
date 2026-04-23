from pathlib import Path

import pytest

from planetakino.parser.detail import parse_detail
from planetakino.parser.listing import parse_listing, parse_schedule

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def coming_soon_html():
    return (FIX / "coming_soon_odesa.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def schedule_html():
    return (FIX / "schedule_odesa.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def detail_html():
    return (FIX / "detail_sample.html").read_text(encoding="utf-8")


class TestListing:
    def test_coming_soon_finds_movies(self, coming_soon_html):
        movies = parse_listing(coming_soon_html, section="soon")
        assert len(movies) >= 5, f"expected several coming-soon movies, got {len(movies)}"

    def test_coming_soon_fields_populated(self, coming_soon_html):
        movies = parse_listing(coming_soon_html, section="soon")
        first = movies[0]
        assert first.movie_id.startswith("Z2lkOi8vbW92aWUv")
        assert first.slug
        assert first.url.startswith("https://planetakino.ua/movie/")
        assert first.title_uk
        assert first.poster_url and first.poster_url.startswith("https://")
        assert first.section == "soon"

    def test_no_duplicate_ids(self, coming_soon_html):
        movies = parse_listing(coming_soon_html, section="soon")
        ids = [m.movie_id for m in movies]
        assert len(ids) == len(set(ids))

    def test_pre_premiere_detected(self, coming_soon_html):
        movies = parse_listing(coming_soon_html, section="soon")
        pre = [m for m in movies if m.is_pre_premiere]
        assert pre, "expected at least one ДОПРЕМ'ЄРА movie in coming-soon section"

    def test_schedule_parses_now_showing(self, schedule_html):
        movies = parse_schedule(schedule_html, section="now")
        assert len(movies) >= 5
        for m in movies:
            assert m.section == "now"
            assert m.title_uk
            assert m.poster_url
            assert m.slug


class TestDetail:
    def test_jsonld_fields(self, detail_html):
        d = parse_detail(detail_html)
        assert d.title_uk
        assert d.duration_min and d.duration_min > 0
        assert d.premiere_date is not None
        assert d.poster_url and d.poster_url.startswith("http")

    def test_original_title_present(self, detail_html):
        d = parse_detail(detail_html)
        assert d.title_original, "alternativeHeadline should give original title"
