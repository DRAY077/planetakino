"""Native app entry point: wraps web/index.html in a PyWebView window.

Run ``python3 app.py`` in dev. For production builds PyInstaller bundles this
file as the entry; see ``build/planetakino.spec``.

Linux fallback
--------------
PyWebView on Linux needs either GTK (``python3-gi`` + WebKit2) or Qt
(``qtpy`` + ``PyQt5`` + ``PyQtWebEngine``). If neither is available the app
automatically falls back to **browser mode**: a local HTTP server serves
``web/`` + ``data/movies.json`` on 127.0.0.1 and the default browser is
launched. The JS bridge isn't available in that mode, but the UI degrades
gracefully (fetch fallback + localStorage).

Force browser mode explicitly with ``python3 app.py --browser``.
"""
from __future__ import annotations

import argparse
import http.server
import logging
import os
import socket
import socketserver
import sys
import threading
import webbrowser
from functools import partial
from pathlib import Path

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


def _find_free_port(preferred: int = 8765) -> int:
    """Return an open TCP port, preferring ``preferred`` but falling back to OS-assigned."""
    for port in (preferred, preferred + 1, preferred + 2):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_browser_handler(web_dir: Path, data_dir: Path):
    """SimpleHTTPRequestHandler that maps /movies.json → data/movies.json.

    Everything else is served from ``web/`` so the page can fetch its own
    manifest, service worker, and icons normally.
    """
    class Handler(http.server.SimpleHTTPRequestHandler):
        def translate_path(self, path):  # type: ignore[override]
            # Strip query + fragment, normalise.
            clean = path.split("?", 1)[0].split("#", 1)[0]
            if clean in ("/movies.json", "/data/movies.json"):
                return str(data_dir / "movies.json")
            # Everything else out of web/
            rel = clean.lstrip("/")
            if not rel or rel.endswith("/"):
                rel = (rel + "index.html") if rel else "index.html"
            return str(web_dir / rel)

        def log_message(self, format, *args):  # quieter than default
            logging.getLogger("http").debug("%s - %s", self.address_string(), format % args)

    return Handler


def run_browser_mode(log: logging.Logger) -> int:
    """Serve web/ + data/movies.json over localhost and open the default browser."""
    web_dir = _resource_dir() / "web"
    data_dir = DATA_DIR
    if not (web_dir / "index.html").exists():
        log.error("frontend missing: %s", web_dir / "index.html")
        return 1

    port = _find_free_port(8765)
    handler_cls = _make_browser_handler(web_dir, data_dir)

    # ThreadingTCPServer so the SW fetch + data fetch don't block each other.
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    httpd = Server(("127.0.0.1", port), handler_cls)
    url = f"http://127.0.0.1:{port}/"
    log.info("Browser mode: serving %s → %s", web_dir, url)
    log.info("Data: /movies.json → %s", data_dir / "movies.json")

    server_thread = threading.Thread(target=httpd.serve_forever, name="pk-http", daemon=True)
    server_thread.start()

    try:
        webbrowser.open(url, new=2)
    except Exception:
        log.exception("failed to open browser; open %s manually", url)

    print(f"\n  Planeta Kino Dashboard\n  → {url}\n  Ctrl-C to stop.\n")
    try:
        server_thread.join()
    except KeyboardInterrupt:
        log.info("shutting down http server")
        httpd.shutdown()
    return 0


def run_webview_mode(log: logging.Logger) -> int:
    """Native window via PyWebView. Raises WebViewException on Linux without GTK/Qt."""
    import webview  # imported lazily so --browser works even if pywebview is broken

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

    def _post_start() -> None:
        try:
            api.start_auto_refresh()
        except Exception:
            log.exception("auto-refresh start failed")

    threading.Timer(2.0, _post_start).start()

    debug = os.environ.get("PLANETAKINO_DEBUG") == "1"
    webview.start(debug=debug, gui=None)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} native/browser launcher")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Force browser mode (local HTTP + default browser). Use on Linux "
             "without PyQt/GTK, or when you prefer a real browser.",
    )
    args = parser.parse_args()

    _configure_logging()
    log = logging.getLogger("app")
    log.info("%s %s starting", APP_NAME, APP_VERSION)

    _seed_export_if_missing()

    if args.browser:
        return run_browser_mode(log)

    try:
        return run_webview_mode(log)
    except Exception as err:
        # PyWebView raises WebViewException on Linux if neither GTK nor Qt is
        # installed. Fall back to the browser so the user still sees something.
        msg = str(err)
        needs_fallback = (
            err.__class__.__name__ == "WebViewException"
            or "QT or GTK" in msg
            or "GTK cannot be loaded" in msg
            or "pywebview" in msg.lower()
        )
        if needs_fallback:
            log.warning("PyWebView unavailable (%s); falling back to browser mode.", err)
            log.warning(
                "For a native window on Linux install Qt:\n"
                "  pip install qtpy PyQt5 PyQtWebEngine\n"
                "or GTK system packages (Debian/Ubuntu):\n"
                "  sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.1"
            )
            return run_browser_mode(log)
        raise


if __name__ == "__main__":
    sys.exit(main())
