"""SQLite storage for planetakino movies.

Schema:
- movies: one row per (cinema_slug, movie_id). Always reflects latest known state.
- snapshots: append-only; one row per fetch where anything changed.
- fetch_log: append-only; one row per fetch cycle.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS movies (
    cinema_slug      TEXT NOT NULL,
    movie_id         TEXT NOT NULL,
    slug             TEXT NOT NULL,
    url              TEXT NOT NULL,
    section          TEXT NOT NULL,
    title_uk         TEXT,
    title_original   TEXT,
    description      TEXT,
    premiere_date    TEXT,
    duration_min     INTEGER,
    age_rating       TEXT,
    genres_json      TEXT,
    formats_json     TEXT,
    is_pre_premiere  INTEGER DEFAULT 0,
    poster_url       TEXT,
    trailer_url      TEXT,
    first_seen_at    TEXT NOT NULL,
    last_seen_at     TEXT NOT NULL,
    detail_fetched_at TEXT,
    PRIMARY KEY (cinema_slug, movie_id)
);

CREATE INDEX IF NOT EXISTS idx_movies_section ON movies(cinema_slug, section);
CREATE INDEX IF NOT EXISTS idx_movies_premiere ON movies(premiere_date);

CREATE TABLE IF NOT EXISTS snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cinema_slug     TEXT NOT NULL,
    movie_id        TEXT NOT NULL,
    captured_at     TEXT NOT NULL,
    payload_json    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fetch_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    cinema_slug   TEXT NOT NULL,
    section       TEXT NOT NULL,
    http_status   INTEGER,
    items_found   INTEGER,
    error         TEXT
);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def tx(self):
        self._conn.execute("BEGIN")
        try:
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def upsert_movie(self, cinema_slug: str, row: dict) -> None:
        now = _utc_now()
        existing = self._conn.execute(
            "SELECT * FROM movies WHERE cinema_slug = ? AND movie_id = ?",
            (cinema_slug, row["movie_id"]),
        ).fetchone()

        data = {
            "cinema_slug": cinema_slug,
            "movie_id": row["movie_id"],
            "slug": row.get("slug", ""),
            "url": row.get("url", ""),
            "section": row.get("section", ""),
            "title_uk": row.get("title_uk"),
            "title_original": row.get("title_original"),
            "description": row.get("description"),
            "premiere_date": row.get("premiere_date"),
            "duration_min": row.get("duration_min"),
            "age_rating": row.get("age_rating"),
            "genres_json": json.dumps(row.get("genres") or [], ensure_ascii=False),
            "formats_json": json.dumps(row.get("formats") or [], ensure_ascii=False),
            "is_pre_premiere": 1 if row.get("is_pre_premiere") else 0,
            "poster_url": row.get("poster_url"),
            "trailer_url": row.get("trailer_url"),
            "detail_fetched_at": row.get("detail_fetched_at"),
        }

        if existing is None:
            data["first_seen_at"] = now
            data["last_seen_at"] = now
            cols = ",".join(data.keys())
            placeholders = ",".join(f":{k}" for k in data)
            self._conn.execute(f"INSERT INTO movies ({cols}) VALUES ({placeholders})", data)
        else:
            data["last_seen_at"] = now
            data["first_seen_at"] = existing["first_seen_at"]
            set_clause = ",".join(f"{k} = :{k}" for k in data if k not in ("cinema_slug", "movie_id"))
            self._conn.execute(
                f"UPDATE movies SET {set_clause} WHERE cinema_slug = :cinema_slug AND movie_id = :movie_id",
                data,
            )

        # Snapshot on any content change
        if existing is None or self._row_changed(existing, data):
            self._conn.execute(
                "INSERT INTO snapshots (cinema_slug, movie_id, captured_at, payload_json) VALUES (?, ?, ?, ?)",
                (cinema_slug, row["movie_id"], now, json.dumps(data, ensure_ascii=False, default=str)),
            )

    @staticmethod
    def _row_changed(existing: sqlite3.Row, new: dict) -> bool:
        watched = ("title_uk", "title_original", "premiere_date", "duration_min",
                   "age_rating", "poster_url", "section", "is_pre_premiere")
        for key in watched:
            if str(existing[key] or "") != str(new.get(key) or ""):
                return True
        return False

    def get_movie(self, cinema_slug: str, movie_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM movies WHERE cinema_slug = ? AND movie_id = ?",
            (cinema_slug, movie_id),
        ).fetchone()

    def all_movies(self, cinema_slug: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM movies WHERE cinema_slug = ? ORDER BY section, premiere_date, title_uk",
            (cinema_slug,),
        ).fetchall()

    def log_fetch(self, cinema_slug: str, section: str, http_status: Optional[int],
                  items_found: int, error: Optional[str], started_at: str) -> None:
        self._conn.execute(
            "INSERT INTO fetch_log (started_at, finished_at, cinema_slug, section, http_status, items_found, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (started_at, _utc_now(), cinema_slug, section, http_status, items_found, error),
        )
