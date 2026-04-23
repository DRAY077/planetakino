"""Integration hook for the sibling ``dcp_ftp_reader`` project.

The DCP reader monitors cinema FTP servers for Digital Cinema Packages (DCP)
and KDM keys. This module reads its SQLite output in read-only mode and maps
each DCP row to a Planeta Kino movie by normalized title.

Mapping strategy:
- Both sources expose a UK title. We normalize (casefold, strip punctuation,
  strip trailing annotations like "(IMAX)") and match on that.
- Status derives from fields in ``dcp_servers.db``:
    - ``arrived_at``       → the DCP file arrived on the FTP server
    - ``kdm_received``     → the key arrived (or ``keys_not_required`` is set)
    - ``download_done``    → local cache is complete
- Returns a list of records keyed by ``movie_id`` so the frontend can attach a
  DCP column to each movie card.

If the reader DB or config is missing we simply return empty — the UI still
works, the DCP column just shows "N/A" for every row.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

from .config import DCP_STATE_PATH

log = logging.getLogger(__name__)


@dataclass
class DcpRecord:
    title_norm: str
    title_display: str
    arrived_at: Optional[str]
    kdm_received_at: Optional[str]
    keys_not_required: bool
    download_done: bool
    server_host: Optional[str]
    notes: Optional[str]

    @property
    def status(self) -> str:
        if self.keys_not_required:
            return "no_keys_needed"
        if self.kdm_received_at and self.download_done:
            return "ready"
        if self.kdm_received_at:
            return "key_ready"
        if self.arrived_at:
            return "waiting_key"
        return "pending"


_STRIP_RE = re.compile(r"[\s\-\:\.,!?'\"«»“”‘’()\[\]]+")
_ANNOT_RE = re.compile(r"\b(imax|3d|2d|re['’]?lux|cinetech\+?|4dx|ultra\s?hd)\b", re.IGNORECASE)
_PREMIERE_RE = re.compile(r"допрем['’‛ʼ]?єрн\w*\s*показ", re.IGNORECASE)


def normalize_title(text: str) -> str:
    if not text:
        return ""
    t = _PREMIERE_RE.sub(" ", text)
    t = _ANNOT_RE.sub(" ", t)
    t = _STRIP_RE.sub(" ", t).strip().casefold()
    return t


def _discover_reader_db(reader_path: str) -> Optional[Path]:
    """Locate the DCP reader SQLite file from a user-supplied directory path."""
    if not reader_path:
        return None
    p = Path(reader_path).expanduser()
    if p.is_file():
        return p
    if p.is_dir():
        for name in ("dcp_servers.db", "dcp.db", "dcp_reader.db"):
            candidate = p / name
            if candidate.exists():
                return candidate
    return None


def _introspect_columns(cx: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row[1] for row in cx.execute(f"PRAGMA table_info({table})")}
    except sqlite3.OperationalError:
        return set()


def load_dcp_records(reader_path: str) -> list[DcpRecord]:
    """Return records from the DCP reader DB, tolerating schema drift.

    The sibling project's schema has shifted over versions, so we introspect
    columns at read time and substitute NULL for anything missing.
    """
    db = _discover_reader_db(reader_path)
    if db is None:
        return []

    try:
        cx = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cx.row_factory = sqlite3.Row
    except sqlite3.Error:
        log.warning("dcp: cannot open %s read-only", db, exc_info=True)
        return []

    try:
        tables = {r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        # Prefer a single consolidated table; fall back to common alternatives.
        target = next((t for t in ("dcps", "dcp_records", "films", "movies") if t in tables), None)
        if target is None:
            return []
        cols = _introspect_columns(cx, target)

        def col(name: str, fallbacks: Iterable[str] = ()) -> str:
            for candidate in (name, *fallbacks):
                if candidate in cols:
                    return candidate
            return "NULL"

        select_sql = f"""
            SELECT
                {col('title_uk',      ('title', 'name_uk', 'name'))}               AS title_uk,
                {col('arrived_at',    ('dcp_arrived_at', 'ftp_seen_at'))}          AS arrived_at,
                {col('kdm_received',  ('kdm_received_at', 'key_received_at'))}     AS kdm_received_at,
                {col('keys_not_required', ('no_keys', 'no_kdm'))}                  AS keys_not_required,
                {col('download_done', ('downloaded', 'cached'))}                   AS download_done,
                {col('server_host',   ('host', 'server'))}                         AS server_host,
                {col('notes',         ('comment',))}                                AS notes
            FROM {target}
        """
        out: list[DcpRecord] = []
        for row in cx.execute(select_sql):
            title = row["title_uk"] or ""
            out.append(DcpRecord(
                title_norm=normalize_title(title),
                title_display=title,
                arrived_at=row["arrived_at"],
                kdm_received_at=row["kdm_received_at"],
                keys_not_required=bool(row["keys_not_required"]),
                download_done=bool(row["download_done"]),
                server_host=row["server_host"],
                notes=row["notes"],
            ))
        return out
    except sqlite3.Error:
        log.warning("dcp: query failed", exc_info=True)
        return []
    finally:
        cx.close()


def attach_dcp_to_movies(movies: list[dict], reader_path: str) -> dict:
    """Return a dict ``{movie_id: dcp_dict}``. Non-destructive — caller merges."""
    records = load_dcp_records(reader_path)
    if not records:
        return {}

    by_norm = {r.title_norm: r for r in records if r.title_norm}
    out = {}
    for m in movies:
        t_norm = normalize_title(m.get("title_uk") or "")
        t_orig = normalize_title(m.get("title_original") or "")
        rec = by_norm.get(t_norm) or by_norm.get(t_orig)
        if rec:
            out[m["movie_id"]] = {
                **asdict(rec),
                "status": rec.status,
            }
    return out


def save_dcp_state(state: dict) -> None:
    DCP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    import json
    DCP_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
