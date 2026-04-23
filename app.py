"""Native app entry point: wraps web/index.html in a PyWebView window.

Run ``python3 app.py`` in dev. For production builds PyInstaller bundles this
file as the entry; see ``build/planetakino.spec``.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

import webview

from planetakino.api import Api
from planetakino.config import APP_NAME, APP_VERSION, DATA_DIR, DB_PATH, EXPORT_PATH
from planetakino.pipeline import export_json
from planetakino.settings import Settings


def _resource_dir() -> Path:
    """Return the path to bundled resources (web/, data/).

    When run under PyInstaller the web folder lives inside ``sys._MEIPASS``;
    in dev it sits next to this file.
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent
    return base


def _configure_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_path = DATA_DIR / "app.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )


def _seed_export_if_missing() -> None:
    """Ensure the frontend has *something* to render on first open."""
    if EXPORT_PATH.exists():
        return
    if not DB_PATH.exists():
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text('{"movies": [], "counts": {"total":0}}', encoding="utf-8")
        return
    try:
        export_json()
    except Exception:
        logging.getLogger(__name__).exception("seed export failed")


def main() -> int:
    _configure_logging()
    log = logging.getLogger("app")
    log.info("%s %s starting", APP_NAME, APP_VERSION)

    _seed_export_if_missing()

    settings = Settings()
    api = Api(settings=settings)

    index_html = _resource_dir() / "web" / "index.html"
    if not index_html.exists():
        log.error("frontend missing: %s", index_html)
        return 1

    theme = settings.get("theme", "dark")
    window = webview.create_window(
        title=f"{APP_NAME}",
        url=str(index_html),
        js_api=api,
        width=1440,
        height=900,
        min_size=(1100, 720),
        background_color="#05080f" if theme == "dark" else "#f5f3ef",
        text_select=True,
        confirm_close=False,
    )
    api.bind_window(window)

    # Auto-refresh kicks in after the window loads
    def _post_start() -> None:
        try:
            api.start_auto_refresh()
        except Exception:
            log.exception("auto-refresh start failed")

    threading.Timer(2.0, _post_start).start()

    debug = os.environ.get("PLANETAKINO_DEBUG") == "1"
    webview.start(debug=debug, gui=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
