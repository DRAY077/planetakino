import os
import sys
from pathlib import Path

BASE_URL = "https://planetakino.ua"


def _user_data_dir(app_name: str) -> Path:
    """Return the OS-appropriate user-data directory.

    When frozen (bundled app), user-writable state must not live inside the
    .app bundle — Gatekeeper mounts notarized apps read-only. Dev mode keeps
    everything in the repo's ``data/`` for easy inspection.
    """
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent.parent / "data"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / app_name
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / app_name

# Only slugs that are *verified* by live probing. cinema-9-uk is confirmed
# against the production site. Others are discovered at runtime via the
# cinema selector on planetakino.ua (see planetakino/discover.py) and
# persisted to data/settings.json['discovered_cinemas']. Until discovered,
# the UI shows the primary cinema only in the ГЛОБАЛЬНО tab.
CINEMAS = {
    "odesa_kotovsky": {
        "slug": "cinema-9-uk",
        "title_uk": "Одеса (City Center Котовський)",
        "city": "Одеса",
        "primary": True,
        "verified": True,
    },
}

DEFAULT_CINEMA = "odesa_kotovsky"

HTTP_TIMEOUT = 20
HTTP_RETRIES = 3
HTTP_BACKOFF = 2.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

APP_NAME = "Planeta Kino Dashboard"
APP_VERSION = "0.2.0"
APP_BUILD_DATE = "2026-04-23"

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = _user_data_dir(APP_NAME)
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "planetakino.db"
EXPORT_PATH = DATA_DIR / "movies.json"
SETTINGS_PATH = DATA_DIR / "settings.json"
DCP_STATE_PATH = DATA_DIR / "dcp_state.json"

DETAIL_CACHE_DAYS = 7

DEFAULT_SETTINGS = {
    "active_cinema": DEFAULT_CINEMA,
    "theme": "dark",
    "grid_size": 4,
    "language": "uk",
    "auto_refresh_min": 60,
    "notifications": True,
    "detail_cache_days": DETAIL_CACHE_DAYS,
    "sort_by": "premiere_date",
    "sort_dir": "asc",
    "dcp_enabled": False,
    "dcp_reader_path": "",
    "discovered_cinemas": [],
}
