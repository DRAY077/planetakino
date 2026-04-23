from datetime import date

from planetakino.extractors.date_uk import (
    format_uk_day_month,
    parse_iso_date,
    parse_uk_day_month,
)
from planetakino.extractors.duration import (
    format_uk_duration,
    parse_iso_duration,
    parse_uk_duration,
)


class TestParseUkDayMonth:
    def test_plain(self):
        assert parse_uk_day_month("30 квітня", today=date(2026, 4, 23)) == date(2026, 4, 30)

    def test_with_prefix(self):
        assert parse_uk_day_month("У кіно з 2 травня", today=date(2026, 4, 23)) == date(2026, 5, 2)

    def test_rolls_to_next_year_when_past(self):
        assert parse_uk_day_month("10 січня", today=date(2026, 12, 1)) == date(2027, 1, 10)

    def test_keeps_year_near_today(self):
        assert parse_uk_day_month("20 квітня", today=date(2026, 4, 23)) == date(2026, 4, 20)

    def test_invalid_returns_none(self):
        assert parse_uk_day_month("скоро", today=date(2026, 4, 23)) is None
        assert parse_uk_day_month("", today=date(2026, 4, 23)) is None
        assert parse_uk_day_month("32 квітня", today=date(2026, 4, 23)) is None

    def test_case_insensitive(self):
        assert parse_uk_day_month("30 КВІТНЯ", today=date(2026, 4, 23)) == date(2026, 4, 30)


class TestParseIsoDate:
    def test_iso(self):
        assert parse_iso_date("2026-04-30") == date(2026, 4, 30)

    def test_iso_in_text(self):
        assert parse_iso_date("Premiere: 2026-05-07 02:00") == date(2026, 5, 7)

    def test_none(self):
        assert parse_iso_date("") is None
        assert parse_iso_date("nope") is None


class TestFormatUkDayMonth:
    def test_format(self):
        assert format_uk_day_month(date(2026, 4, 30)) == "30 квітня"
        assert format_uk_day_month(date(2026, 5, 2)) == "2 травня"


class TestParseUkDuration:
    def test_hours_only(self):
        assert parse_uk_duration("2 год") == 120

    def test_hours_and_minutes(self):
        assert parse_uk_duration("1 год 48 хв") == 108

    def test_minutes_only(self):
        assert parse_uk_duration("90 хв") == 90

    def test_with_html_whitespace(self):
        assert parse_uk_duration("  2 год  ") == 120

    def test_empty(self):
        assert parse_uk_duration("") is None
        assert parse_uk_duration("нічого") is None


class TestParseIsoDuration:
    def test_hm(self):
        assert parse_iso_duration("PT1H44M") == 104

    def test_h_only(self):
        assert parse_iso_duration("PT2H") == 120

    def test_m_only(self):
        assert parse_iso_duration("PT90M") == 90

    def test_invalid(self):
        assert parse_iso_duration("") is None
        assert parse_iso_duration("1h44m") is None


class TestFormatUkDuration:
    def test_format(self):
        assert format_uk_duration(120) == "2 год"
        assert format_uk_duration(108) == "1 год 48 хв"
        assert format_uk_duration(90) == "1 год 30 хв"
