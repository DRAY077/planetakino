import logging
import time
from typing import Optional

import requests

from .config import HTTP_BACKOFF, HTTP_RETRIES, HTTP_TIMEOUT, USER_AGENT

log = logging.getLogger(__name__)


class HttpClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.8,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

    def get_html(self, url: str) -> Optional[str]:
        last_err: Optional[Exception] = None
        for attempt in range(1, HTTP_RETRIES + 1):
            try:
                resp = self._session.get(url, timeout=HTTP_TIMEOUT)
                if resp.status_code == 200 and resp.text:
                    return resp.text
                log.warning("GET %s → HTTP %s (attempt %s)", url, resp.status_code, attempt)
            except requests.RequestException as e:
                last_err = e
                log.warning("GET %s failed (attempt %s): %s", url, attempt, e, exc_info=True)
            if attempt < HTTP_RETRIES:
                time.sleep(HTTP_BACKOFF * attempt)
        if last_err:
            log.error("GET %s giving up: %s", url, last_err)
        return None

    def close(self) -> None:
        self._session.close()
