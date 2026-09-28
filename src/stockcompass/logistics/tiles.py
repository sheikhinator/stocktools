"""Map tiles (the street map under the pins), kept on this PC.

Each tile is downloaded once from OpenStreetMap (or the tile server set in the map settings) and then served from
disk, so the areas you have looked at keep working without internet. Without any tiles the map still shows the
country outline, cities, stores, suppliers and routes."""

from __future__ import annotations

import base64
import math
import threading
import time

from stockcompass.paths import data_dir

from . import net

DEFAULT_SERVER = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
MAX_ZOOM = 17


def _dir():
    p = data_dir() / "tiles"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _path(z: int, x: int, y: int):
    return _dir() / str(z) / str(x) / f"{y}.png"


def tile(z: int, x: int, y: int, server: str = "", online: bool = True) -> bytes | None:
    z, x, y = int(z), int(x), int(y)
    if not (0 <= z <= MAX_ZOOM and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return None
    p = _path(z, x, y)
    if p.exists():
        try:
            return p.read_bytes()
        except OSError:
            return None
    if not online:
        return None
    b = net.fetch((server or DEFAULT_SERVER).format(z=z, x=x, y=y, s="a"), timeout=6)
    if not b or b[:4] != b"\x89PNG" and b[:3] != b"\xff\xd8\xff":
        return None
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    except OSError:
        pass
    return b


def data_url(b: bytes) -> str:
    mime = "image/jpeg" if b[:3] == b"\xff\xd8\xff" else "image/png"
    return f"data:{mime};base64," + base64.b64encode(b).decode()


def xy(lat: float, lng: float, z: int) -> tuple[int, int]:
    n = 2 ** z
    x = int((lng + 180) / 360 * n)
    r = math.radians(lat)
    y = int((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def cached_count() -> dict:
    n, size = 0, 0
    for p in _dir().rglob("*.png"):
        n += 1
        try:
            size += p.stat().st_size
        except OSError:
            pass
    return dict(tiles=n, mb=round(size / 1e6, 1))


JOB: dict = dict(running=False, done=0, total=0, failed=0, msg="")


def prefetch(points: list[tuple[float, float]], server: str = "", country_zoom: int = 7, city_zoom: int = 13, radius_km: float = 6.0):
    """Keep the map of Pakistan (low zoom) and the streets around each store / supplier for offline use.
    Polite: one tile at a time, a short pause between tiles."""
    if JOB["running"]:
        return JOB
    todo = []
    for z in range(4, country_zoom + 1):
        x0, y0 = xy(37.5, 60.5, z)
        x1, y1 = xy(23.0, 78.0, z)
        todo += [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    for la, lo in points:
        for z in range(max(country_zoom + 1, 9), city_zoom + 1):
            d = radius_km * (1.0 if z >= 12 else 3.0)
            dlat, dlng = d / 111.0, d / (111.0 * math.cos(math.radians(la)))
            x0, y0 = xy(la + dlat, lo - dlng, z)
            x1, y1 = xy(la - dlat, lo + dlng, z)
            todo += [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    todo = sorted(set(todo))[:6000]
    JOB.update(running=True, done=0, total=len(todo), failed=0, msg="")

    def run():
        try:
            for z, x, y in todo:
                if _path(z, x, y).exists():
                    JOB["done"] += 1
                    continue
                if tile(z, x, y, server) is None:
                    JOB["failed"] += 1
                    if JOB["failed"] > 25 and JOB["failed"] > JOB["done"]:
                        JOB["msg"] = "No internet (or the map server refused): stopped. Try again when online."
                        break
                JOB["done"] += 1
                time.sleep(0.05)
        finally:
            JOB["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return JOB
