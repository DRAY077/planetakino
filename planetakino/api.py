"""PyWebView ↔ JavaScript bridge.

Each public method on :class:`Api` becomes callable from the frontend as
``window.pywebview.api.<name>(...)``. Keep return values JSON-serializable
(dicts / lists / primitives), and keep methods idempotent where possible so
the frontend can retry safely.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import dcp_bridge
from .config import (
    APP_BUILD_DATE,
    APP_NAME,
    APP_VERSION,
    CINEMAS,
    DATA_DIR,
    DB_PATH,
    EXPORT_PATH,
)
from .db.store import Store
from .pipeline import export_json, fetch_cinema
from .settings import Settings

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Api:
    """Methods exposed to the WebView frontend.

    All mutations write through to the Store so the SQLite file stays the
    source of truth — the JSON export is only a convenience for the frontend
    when running outside the native app shell.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or Settings()
        self._fetch_lock = threading.Lock()
        self._started_at = time.time()
        self._last_fetch_at: Optional[str] = None
        self._last_fetch_report: Optional[dict] = None
        self._auto_refresh_thread: Optional[threading.Thread] = None
        self._auto_refresh_stop = threading.Event()
        self._window = None  # set from app.py after window creation

    # ------------------------------------------------------------------ lifecycle
    def bind_window(self, window) -> None:
        self._window = window

    # ------------------------------------------------------------------ meta
    def app_info(self) -> dict:
        return {
            "name": APP_NAME,
            "version": APP_VERSION,
            "build_date": APP_BUILD_DATE,
            "data_dir": str(DATA_DIR),
            "db_path": str(DB_PATH),
            "export_path": str(EXPORT_PATH),
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "started_at": datetime.fromtimestamp(self._started_at, tz=timezone.utc).isoformat(timespec="seconds"),
            "uptime_sec": int(time.time() - self._started_at),
            "last_fetch_at": self._last_fetch_at,
        }

    # ------------------------------------------------------------------ data
    def list_movies(self, cinema_key: Optional[str] = None) -> dict:
        """Return current movies plus DCP status if configured.

        Shape matches the JSON export so the web frontend can share parsers.
        """
        settings = self._settings.all()
        cinema_key = cinema_key or settings["active_cinema"]
        if cinema_key not in CINEMAS:
            return {"error": f"unknown cinema: {cinema_key}"}

        cinema = CINEMAS[cinema_key]
        store = Store(DB_PATH)
        try:
            rows = store.all_movies(cinema["slug"])
            movies = [_row_to_dict(r) for r in rows]
        finally:
            store.close()

        dcp_map = {}
        if settings.get("dcp_enabled") and settings.get("dcp_reader_path"):
            dcp_map = dcp_bridge.attach_dcp_to_movies(movies, settings["dcp_reader_path"])

        for m in movies:
            m["dcp"] = dcp_map.get(m["movie_id"])

        return {
            "generated_at": _now_iso(),
            "cinema": {"key": cinema_key, **cinema},
            "counts": {
                "total": len(movies),
                "now": sum(1 for m in movies if m["section"] == "now"),
                "soon": sum(1 for m in movies if m["section"] == "soon"),
                "pre_premiere": sum(1 for m in movies if m["is_pre_premiere"]),
                "with_dcp": sum(1 for m in movies if m.get("dcp")),
            },
            "movies": movies,
            "settings": settings,
            "meta": self.app_info(),
        }

    def refresh(self, cinema_key: Optional[str] = None, force_detail: bool = False) -> dict:
        """Trigger a full fetch + export cycle. Safe to call concurrently (serialized)."""
        settings = self._settings.all()
        cinema_key = cinema_key or settings["active_cinema"]
        cache_days = 0 if force_detail else int(settings.get("detail_cache_days", 7))
        with self._fetch_lock:
            try:
                report = fetch_cinema(cinema_key, detail_cache_days=cache_days)
                export_json(cinema_key)
                self._last_fetch_at = _now_iso()
                self._last_fetch_report = report
                return {"ok": True, "report": report, "at": self._last_fetch_at}
            except Exception as exc:
                log.exception("refresh failed")
                return {"ok": False, "error": str(exc)}

    def refresh_week(self, cinema_key: Optional[str] = None) -> dict:
        """Same as refresh() but always forces detail re-fetch — used for "ОНОВИТИ ТИЖДЕНЬ"."""
        return self.refresh(cinema_key, force_detail=True)

    def delete_movie(self, movie_id: str, cinema_key: Optional[str] = None) -> dict:
        settings = self._settings.all()
        cinema_key = cinema_key or settings["active_cinema"]
        cinema = CINEMAS.get(cinema_key)
        if cinema is None:
            return {"ok": False, "error": "unknown cinema"}

        store = Store(DB_PATH)
        try:
            cur = store._conn.execute(
                "DELETE FROM movies WHERE cinema_slug = ? AND movie_id = ?",
                (cinema["slug"], movie_id),
            )
            deleted = cur.rowcount
        finally:
            store.close()
        export_json(cinema_key)
        return {"ok": True, "deleted": deleted}

    def refresh_movie(self, movie_id: str, cinema_key: Optional[str] = None) -> dict:
        """Re-fetch a single movie's detail page (bypasses cache)."""
        from .http import HttpClient
        from .parser.detail import parse_detail

        settings = self._settings.all()
        cinema_key = cinema_key or settings["active_cinema"]
        cinema = CINEMAS.get(cinema_key)
        if cinema is None:
            return {"ok": False, "error": "unknown cinema"}

        store = Store(DB_PATH)
        try:
            row = store.get_movie(cinema["slug"], movie_id)
            if row is None:
                return {"ok": False, "error": "movie not found"}
            url = row["url"]
            http = HttpClient()
            try:
                html = http.get_html(url)
            finally:
                http.close()
            if not html:
                return {"ok": False, "error": "no HTML"}
            detail = parse_detail(html)
            if detail is None:
                return {"ok": False, "error": "no JSON-LD found"}
            # Update watched fields
            payload = _row_to_dict(row)
            payload.update({
                "title_original": detail.title_original or payload.get("title_original"),
                "description":    detail.description or payload.get("description"),
                "duration_min":   detail.duration_min or payload.get("duration_min"),
                "age_rating":     detail.age_rating or payload.get("age_rating"),
                "genres":         detail.genres or payload.get("genres") or [],
                "poster_url":     detail.poster_url or payload.get("poster_url"),
                "trailer_url":    detail.trailer_url or payload.get("trailer_url"),
                "premiere_date":  detail.premiere_date.isoformat() if detail.premiere_date else payload.get("premiere_date"),
                "detail_fetched_at": _now_iso(),
            })
            store.upsert_movie(cinema["slug"], payload)
        finally:
            store.close()
        export_json(cinema_key)
        return {"ok": True, "movie_id": movie_id}

    def movie_snapshots(self, movie_id: str, cinema_key: Optional[str] = None) -> list[dict]:
        settings = self._settings.all()
        cinema_key = cinema_key or settings["active_cinema"]
        cinema = CINEMAS.get(cinema_key)
        if cinema is None:
            return []
        store = Store(DB_PATH)
        try:
            rows = store._conn.execute(
                "SELECT captured_at, payload_json FROM snapshots "
                "WHERE cinema_slug = ? AND movie_id = ? ORDER BY captured_at DESC LIMIT 40",
                (cinema["slug"], movie_id),
            ).fetchall()
            return [{"captured_at": r["captured_at"], "payload": json.loads(r["payload_json"])} for r in rows]
        finally:
            store.close()

    def fetch_log(self, limit: int = 50) -> list[dict]:
        store = Store(DB_PATH)
        try:
            rows = store._conn.execute(
                "SELECT * FROM fetch_log ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            store.close()

    # ------------------------------------------------------------------ settings
    def get_settings(self) -> dict:
        return self._settings.all()

    def update_settings(self, changes: dict) -> dict:
        updated = self._settings.update(changes or {})
        # If auto-refresh interval changed, restart loop
        if "auto_refresh_min" in changes:
            self._restart_auto_refresh()
        return updated

    def list_cinemas(self) -> list[dict]:
        return [{"key": k, **v} for k, v in CINEMAS.items()]

    # ------------------------------------------------------------------ actions
    def open_external(self, url: str) -> dict:
        if not url or not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "invalid url"}
        try:
            webbrowser.open(url, new=2)
            return {"ok": True}
        except Exception as exc:
            log.exception("open_external failed")
            return {"ok": False, "error": str(exc)}

    def open_in_editor(self, path: str) -> dict:
        """Open a file in the system's default editor (used by the SUBLIME button)."""
        target = Path(path) if path else DATA_DIR
        if not target.exists():
            return {"ok": False, "error": f"path missing: {target}"}
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            elif sys.platform == "win32":
                os.startfile(str(target))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(target)])
            return {"ok": True, "path": str(target)}
        except Exception as exc:
            log.exception("open_in_editor failed")
            return {"ok": False, "error": str(exc)}

    def reveal_in_finder(self, path: str) -> dict:
        target = Path(path) if path else DATA_DIR
        if not target.exists():
            return {"ok": False, "error": "path missing"}
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(target)])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target.parent)])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------ export
    def export(self, fmt: str = "json", cinema_key: Optional[str] = None) -> dict:
        settings = self._settings.all()
        cinema_key = cinema_key or settings["active_cinema"]
        cinema = CINEMAS.get(cinema_key)
        if cinema is None:
            return {"ok": False, "error": "unknown cinema"}

        store = Store(DB_PATH)
        try:
            rows = store.all_movies(cinema["slug"])
            movies = [_row_to_dict(r) for r in rows]
        finally:
            store.close()

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = DATA_DIR / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)

        if fmt == "json":
            path = out_dir / f"movies_{cinema_key}_{stamp}.json"
            path.write_text(json.dumps(movies, ensure_ascii=False, indent=2), encoding="utf-8")
        elif fmt == "csv":
            path = out_dir / f"movies_{cinema_key}_{stamp}.csv"
            buf = io.StringIO()
            if movies:
                fields = ["movie_id", "title_uk", "title_original", "section", "premiere_date",
                          "duration_min", "age_rating", "is_pre_premiere", "url"]
                w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                for m in movies:
                    w.writerow({k: m.get(k, "") for k in fields})
            path.write_text(buf.getvalue(), encoding="utf-8")
        elif fmt == "md":
            path = out_dir / f"movies_{cinema_key}_{stamp}.md"
            lines = [f"# {cinema['title_uk']}  —  {_now_iso()}", ""]
            for section in ("now", "soon"):
                subset = [m for m in movies if m["section"] == section]
                label = "Вже в кіно" if section == "now" else "Скоро"
                lines.append(f"## {label} ({len(subset)})\n")
                for m in subset:
                    lines.append(f"- **{m['title_uk']}** ({m.get('title_original') or '—'})"
                                 f" — {m.get('premiere_date') or '—'},"
                                 f" {m.get('duration_min') or '?'} хв")
                lines.append("")
            path.write_text("\n".join(lines), encoding="utf-8")
        else:
            return {"ok": False, "error": f"unsupported format: {fmt}"}

        return {"ok": True, "path": str(path), "size": path.stat().st_size}

    def generate_report(self, cinema_key: Optional[str] = None) -> dict:
        """Produce a dense Markdown report — used by the "ЗВІТ" button."""
        settings = self._settings.all()
        cinema_key = cinema_key or settings["active_cinema"]
        cinema = CINEMAS.get(cinema_key)
        if cinema is None:
            return {"ok": False, "error": "unknown cinema"}

        store = Store(DB_PATH)
        try:
            rows = store.all_movies(cinema["slug"])
            movies = [_row_to_dict(r) for r in rows]
            fetch_rows = store._conn.execute(
                "SELECT * FROM fetch_log WHERE cinema_slug = ? ORDER BY started_at DESC LIMIT 20",
                (cinema["slug"],),
            ).fetchall()
            snap_count = store._conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE cinema_slug = ?", (cinema["slug"],)
            ).fetchone()[0]
        finally:
            store.close()

        dcp_map = {}
        if settings.get("dcp_enabled") and settings.get("dcp_reader_path"):
            dcp_map = dcp_bridge.attach_dcp_to_movies(movies, settings["dcp_reader_path"])

        lines = [
            f"# Звіт — {cinema['title_uk']}",
            f"_Згенеровано: {_now_iso()}_",
            "",
            "## Підсумок",
            f"- Всього фільмів: **{len(movies)}**",
            f"- Вже в кіно: **{sum(1 for m in movies if m['section']=='now')}**",
            f"- Скоро в кіно: **{sum(1 for m in movies if m['section']=='soon')}**",
            f"- Допрем'єрних: **{sum(1 for m in movies if m['is_pre_premiere'])}**",
            f"- З DCP-статусом: **{len(dcp_map)}**",
            f"- Snapshots у БД: **{snap_count}**",
            "",
            "## Останні fetch-и",
        ]
        for r in fetch_rows:
            lines.append(f"- `{r['started_at']}` · {r['section']} · HTTP {r['http_status']}"
                         f" · знайдено {r['items_found']}"
                         + (f" · ⚠️ {r['error']}" if r['error'] else ""))

        lines.extend(["", "## Деталі фільмів"])
        for m in sorted(movies, key=lambda x: (x["section"], x.get("premiere_date") or "")):
            dcp = dcp_map.get(m["movie_id"])
            dcp_str = f" · DCP: {dcp['status']}" if dcp else ""
            lines.append(
                f"- [{m['section'].upper()}] **{m['title_uk']}**"
                f" · {m.get('title_original') or '—'}"
                f" · {m.get('premiere_date') or '—'}"
                f" · {m.get('duration_min') or '?'} хв"
                f"{dcp_str}"
            )

        out_dir = DATA_DIR / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"report_{cinema_key}_{stamp}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return {"ok": True, "path": str(path), "size": path.stat().st_size}

    # ------------------------------------------------------------------ auto-refresh
    def start_auto_refresh(self) -> dict:
        self._restart_auto_refresh()
        return {"ok": True}

    def stop_auto_refresh(self) -> dict:
        self._auto_refresh_stop.set()
        return {"ok": True}

    def _restart_auto_refresh(self) -> None:
        self._auto_refresh_stop.set()
        if self._auto_refresh_thread and self._auto_refresh_thread.is_alive():
            self._auto_refresh_thread.join(timeout=0.5)
        interval_min = int(self._settings.get("auto_refresh_min", 60) or 0)
        if interval_min <= 0:
            return
        self._auto_refresh_stop = threading.Event()
        t = threading.Thread(target=self._auto_refresh_loop, args=(interval_min,), daemon=True)
        self._auto_refresh_thread = t
        t.start()

    def _auto_refresh_loop(self, interval_min: int) -> None:
        # First tick after full interval — we assume UI already has data.
        while not self._auto_refresh_stop.wait(interval_min * 60):
            try:
                self.refresh()
                if self._window is not None:
                    self._window.evaluate_js("window.__onAutoRefresh && window.__onAutoRefresh()")
            except Exception:
                log.exception("auto-refresh tick failed")

    # ------------------------------------------------------------------ DCP
    def dcp_probe(self, reader_path: str) -> dict:
        """Validate a DCP reader path and return a summary count."""
        records = dcp_bridge.load_dcp_records(reader_path)
        return {
            "ok": True,
            "count": len(records),
            "sample": [r.title_display for r in records[:5]],
        }

    def dcp_status(self) -> dict:
        settings = self._settings.all()
        if not settings.get("dcp_enabled"):
            return {"enabled": False}
        records = dcp_bridge.load_dcp_records(settings.get("dcp_reader_path") or "")
        return {
            "enabled": True,
            "reader_path": settings.get("dcp_reader_path"),
            "count": len(records),
            "ready":         sum(1 for r in records if r.status == "ready"),
            "key_ready":     sum(1 for r in records if r.status == "key_ready"),
            "waiting_key":   sum(1 for r in records if r.status == "waiting_key"),
            "no_keys_needed": sum(1 for r in records if r.status == "no_keys_needed"),
            "pending":       sum(1 for r in records if r.status == "pending"),
        }


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
