"""Road distance and driving time between points.

With internet: the real road route from an OSRM routing service (public OpenStreetMap router by default, or the
company's own), kept on this PC so each route is fetched once. Without: the straight line times a detour factor
calibrated on real road distances between the big cities, and truck speeds (city streets vs highway)."""

from __future__ import annotations

import json
import threading
from datetime import datetime

from stockcompass.db import Database

from . import geo, net

DEFAULT_ROUTER = "https://router.project-osrm.org"
_mem: dict[str, dict] = {}
_mem_lock = threading.Lock()


def _k(pts: list[tuple[float, float]]) -> str:
    return ";".join(f"{p[0]:.4f},{p[1]:.4f}" for p in pts)


def speeds(db: Database) -> dict:
    s = db.setting("logistics") or {}
    return dict(city_kmh=float(s.get("city_kmh") or 22), highway_kmh=float(s.get("highway_kmh") or 60),
                truck_factor=float(s.get("truck_factor") or 1.25))


def estimate_leg(a, b, sp: dict) -> dict:
    straight = geo.haversine(a, b)
    km = straight * geo.road_factor(a, b)
    city = min(km, 12.0 if km > 40 else km)          # the first and last kilometres are city streets
    hours = city / sp["city_kmh"] + max(0.0, km - city) / sp["highway_kmh"]
    return dict(km=km, minutes=hours * 60, source="estimate", geometry=[[a[0], a[1]], [b[0], b[1]]])


def _osrm(base: str, pts: list, sp: dict) -> dict | None:
    coords = ";".join(f"{p[1]:.5f},{p[0]:.5f}" for p in pts)
    js = net.fetch_json(f"{base.rstrip('/')}/route/v1/driving/{coords}?overview=simplified&geometries=geojson&steps=false", timeout=10)
    if not js or js.get("code") != "Ok" or not js.get("routes"):
        return None
    r = js["routes"][0]
    geom = [[c[1], c[0]] for c in (r.get("geometry") or {}).get("coordinates", [])]
    legs = [dict(km=l["distance"] / 1000, minutes=l["duration"] / 60 * sp["truck_factor"]) for l in r.get("legs", [])]
    return dict(km=r["distance"] / 1000, minutes=r["duration"] / 60 * sp["truck_factor"], source="road route",
                geometry=geom, legs=legs)


def route(db: Database, pts: list[tuple[float, float]], online: bool | None = None) -> dict:
    """km, minutes (truck), geometry [[lat, lng]…] and legs for a path through the points, in order."""
    pts = [(float(p[0]), float(p[1])) for p in pts if p]
    sp = speeds(db)
    if len(pts) < 2:
        return dict(km=0.0, minutes=0.0, source="estimate", geometry=[list(p) for p in pts], legs=[])
    key = _k(pts)
    with _mem_lock:
        if key in _mem:
            return _mem[key]
    hit = db.q("SELECT km, minutes, geometry, source FROM route_cache WHERE key=?", [key])
    if hit:
        km, mins, g, src = hit[0]
        d = json.loads(g or "{}")
        out = dict(km=km, minutes=mins * sp["truck_factor"] / (d.get("tf") or sp["truck_factor"]), source=src,
                   geometry=d.get("g") or [], legs=d.get("legs") or [])
        with _mem_lock:
            _mem[key] = out
        return out
    cfg = db.setting("logistics") or {}
    if online is None:
        online = cfg.get("online", True)
    got = _osrm(cfg.get("router") or DEFAULT_ROUTER, pts, sp) if online else None
    if got:
        db.execute("INSERT OR REPLACE INTO route_cache VALUES (?,?,?,?,?,?)",
                   [key, got["km"], got["minutes"], json.dumps(dict(g=got["geometry"], legs=got["legs"], tf=sp["truck_factor"])),
                    got["source"], datetime.now()])
        with _mem_lock:
            _mem[key] = got
        return got
    legs = [estimate_leg(pts[i], pts[i + 1], sp) for i in range(len(pts) - 1)]
    out = dict(km=sum(l["km"] for l in legs), minutes=sum(l["minutes"] for l in legs), source="estimate",
               geometry=[list(p) for p in pts], legs=[dict(km=l["km"], minutes=l["minutes"]) for l in legs])
    return out            # estimates are not stored: the real route is tried again next time


def leg(db: Database, a, b, online: bool | None = None) -> dict:
    return route(db, [a, b], online)


def order_stops(db: Database, start, stops: list, back: bool = False, online: bool | None = False) -> list[int]:
    """Visit order for the stops (indexes): nearest next, then 2-opt swaps. Uses estimates so it is instant."""
    n = len(stops)
    if n <= 1:
        return list(range(n))
    sp = speeds(db)
    pts = [start] + list(stops)
    d = [[0.0 if i == j else estimate_leg(pts[i], pts[j], sp)["km"] for j in range(n + 1)] for i in range(n + 1)]
    todo, cur, order = set(range(1, n + 1)), 0, []
    while todo:
        nxt = min(todo, key=lambda j: d[cur][j])
        order.append(nxt)
        todo.remove(nxt)
        cur = nxt

    def length(o):
        path = [0] + o + ([0] if back else [])
        return sum(d[path[i]][path[i + 1]] for i in range(len(path) - 1))

    improved = True
    while improved:
        improved = False
        for i in range(n - 1):
            for j in range(i + 1, n):
                cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                if length(cand) + 1e-9 < length(order):
                    order, improved = cand, True
    return [o - 1 for o in order]


def clear_memory():
    with _mem_lock:
        _mem.clear()
