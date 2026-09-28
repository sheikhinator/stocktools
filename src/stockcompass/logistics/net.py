"""Internet for the map (tiles, road routes, addresses, fuel prices): optional, polite and never blocking.

Everything fetched is kept on this PC, so each thing is fetched once. When a service does not answer it is left
alone for a while and the map falls back to its own estimates; nothing ever waits long."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from stockcompass import __version__

UA = f"StockCompass/{__version__} (Carrefour Pakistan stock tool; desktop)"
_down: dict[str, float] = {}           # host -> time until which it is not tried again
_lock = threading.Lock()
_last: dict[str, float] = {}           # host -> last request time (one request a second for public services)
POLITE = {"nominatim.openstreetmap.org": 1.1}
OFFLINE = False                        # tests and "work offline" switch it off


def host_of(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc


def available(url: str) -> bool:
    return not OFFLINE and _down.get(host_of(url), 0) < time.time()


def mark_down(url: str, seconds: float = 120):
    _down[host_of(url)] = time.time() + seconds


def fetch(url: str, timeout: float = 8.0, headers: dict | None = None, data: bytes | None = None) -> bytes | None:
    """The body, or None when offline / the service fails (then it is skipped for two minutes)."""
    if not available(url):
        return None
    h = host_of(url)
    gap = POLITE.get(h)
    if gap:
        with _lock:
            wait = _last.get(h, 0) + gap - time.time()
            if wait > 0:
                time.sleep(min(wait, gap))
            _last[h] = time.time()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "*/*", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status >= 400:
                raise OSError(r.status)
            return r.read()
    except urllib.error.HTTPError as e:          # the service answered: only this request failed
        if e.code in (429, 503):
            mark_down(url, 60)
        return None
    except Exception:                            # no connection: leave the service alone for a while
        mark_down(url)
        return None


def fetch_json(url: str, timeout: float = 8.0, headers: dict | None = None):
    b = fetch(url, timeout, {"Accept": "application/json", **(headers or {})})
    if b is None:
        return None
    try:
        return json.loads(b.decode("utf-8", "replace"))
    except ValueError:
        return None


def final_url(url: str, timeout: float = 6.0) -> str | None:
    """Where a short link (maps.app.goo.gl/…) leads."""
    if not available(url):
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.geturl()
    except Exception:
        return None
