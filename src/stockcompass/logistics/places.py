"""Where everything is: stores, suppliers, warehouses (DCs) and any other point, kept on this PC.

Stores start at approximate points (their mall / area, or the city) and are marked "approximate" until someone
places the pin exactly. Suppliers get a location from a file (address / city / coordinates columns), a pasted
Google Maps link or coordinates, a city, a click on the map, or an address search when the PC is online."""

from __future__ import annotations

import json
import re
from datetime import datetime

from stockcompass.db import Database

from . import geo, net

KINDS = {"store": "Store", "supplier": "Supplier", "dc": "Warehouse / DC", "other": "Other place"}


def _stored(db: Database) -> dict[tuple[str, str], dict]:
    return {(r["kind"], r["code"]): r for r in db.qd("SELECT * FROM places")}


def all_places(db: Database, with_suppliers: bool = True) -> list[dict]:
    """Every point on the map. Stores always appear (approximate until confirmed)."""
    saved = _stored(db)
    out = []
    stores = db.store_list()
    by_code = {s["code"]: s for s in stores}
    for s in stores:
        p = saved.get(("store", s["code"]))
        if p and p["lat"] is not None:
            out.append(dict(kind="store", code=s["code"], name=s["name"], lat=p["lat"], lng=p["lng"], address=p["address"],
                            city=p["city"] or s["city"], source=p["source"], exact=bool(p["confirmed"]), format=s["format"]))
            continue
        pt, how = geo.STORE_POINTS.get(s["code"]), "area of the mall"
        if not pt and s.get("parent") and s["parent"] in by_code:        # a Myli sits inside its host store
            host = saved.get(("store", s["parent"]))
            pt = (host["lat"], host["lng"]) if host and host["lat"] is not None else geo.STORE_POINTS.get(s["parent"])
            how = "inside its host store"
        if not pt:
            pt, how = geo.city_point(s.get("city") or s["name"]), "city centre"
        if pt:
            out.append(dict(kind="store", code=s["code"], name=s["name"], lat=pt[0], lng=pt[1], address="", city=s["city"],
                            source=f"approximate ({how})", exact=False, format=s["format"], parent=s.get("parent")))
    dc = dc_store(db)
    for p in out:                      # the distribution centre is a store (Fortress): its pin carries the DC mark
        if p["code"] == dc:
            p["dc"] = True
    names = {c: n for c, n in db.q("SELECT code, name FROM suppliers")} if with_suppliers else {}
    for (kind, code), p in saved.items():
        if kind == "store" or p["lat"] is None:
            continue
        out.append(dict(kind=kind, code=code, name=p["name"] or names.get(code) or code, lat=p["lat"], lng=p["lng"],
                        address=p["address"], city=p["city"], source=p["source"], exact=bool(p["confirmed"])))
    return out


def dc_store(db: Database) -> str:
    """GIMA code of the store that is the distribution centre (Fortress, 500, unless changed in the map settings)."""
    return str((db.setting("logistics") or {}).get("dc_store") or "500")


def point(db: Database, kind: str, code: str) -> dict | None:
    for p in all_places(db, with_suppliers=False):
        if p["kind"] == kind and p["code"] == code:
            return p
    return None


def points(db: Database) -> dict[tuple[str, str], dict]:
    return {(p["kind"], p["code"]): p for p in all_places(db)}


def set_place(db: Database, kind: str, code: str, lat: float | None, lng: float | None, name: str = "", address: str = "",
              city: str = "", source: str = "you", confirmed: bool = True, keep_better: bool = False) -> dict:
    """Save a location. keep_better: a file must not overwrite a pin someone placed by hand."""
    kind = kind if kind in KINDS else "other"
    code = str(code or "").strip() or re.sub(r"\W+", "-", name.lower()).strip("-")[:40]
    if not code:
        raise ValueError("A place needs a code or a name.")
    cur = db.qd("SELECT * FROM places WHERE kind=? AND code=?", [kind, code])
    if cur and keep_better and cur[0]["confirmed"] and cur[0]["source"] == "you":
        return cur[0]
    if lat is not None and not (-90 <= float(lat) <= 90 and -180 <= float(lng) <= 180):
        raise ValueError("Those coordinates are not on the map.")
    if not city and lat is not None:
        city = geo.nearest_city((float(lat), float(lng)))
    old = cur[0] if cur else {}
    db.execute("INSERT OR REPLACE INTO places VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               [kind, code, name or old.get("name") or "", lat, lng, address or old.get("address") or "", city or old.get("city") or "",
                source, bool(confirmed), datetime.now(), old.get("notes")])
    return dict(kind=kind, code=code, name=name, lat=lat, lng=lng, address=address, city=city, source=source, exact=confirmed)


def delete_place(db: Database, kind: str, code: str):
    db.execute("DELETE FROM places WHERE kind=? AND code=?", [kind, code])


def geocode(db: Database, text: str, online: bool = True) -> dict | None:
    """An address, link or city -> {lat, lng, how, exact}. Coordinates and links first, then the address search
    (online, remembered), then the city (offline)."""
    s = (text or "").strip()
    if not s:
        return None
    p = geo.parse_coords(s)
    if p:
        return dict(lat=p[0], lng=p[1], how="coordinates", exact=True)
    if online and re.match(r"https?://(maps\.app\.goo\.gl|goo\.gl/maps|g\.co/kgs)/", s):
        u = net.final_url(s)
        p = geo.parse_coords(u or "")
        if p:
            return dict(lat=p[0], lng=p[1], how="map link", exact=True)
    key = re.sub(r"\s+", " ", s.upper())[:200]
    hit = db.learned("geocode").get(key)
    if hit:
        try:
            return json.loads(hit)
        except ValueError:
            pass
    if online:
        q = s if re.search(r"pakistan", s, re.I) else s + ", Pakistan"
        url = "https://nominatim.openstreetmap.org/search?" + net.urllib.parse.urlencode(
            dict(q=q, format="json", limit=1, countrycodes="pk"))
        js = net.fetch_json(url, timeout=8)
        if js:
            r = js[0]
            ans = dict(lat=float(r["lat"]), lng=float(r["lon"]), how="address search", exact=True,
                       found=r.get("display_name", "")[:200])
            db.learn("geocode", key, json.dumps(ans))
            return ans
    c = geo.city_of(s)
    if c:
        la, lo, _ = geo.CITIES[c]
        return dict(lat=la, lng=lo, how=f"city centre of {c} (approximate)", exact=False, city=c)
    return None


def learn_from_rows(db: Database, rows: list[dict]) -> int:
    """Locations found in an imported file (store / supplier with coordinates, address or city)."""
    n = 0
    for r in rows:
        lat, lng = r.get("lat"), r.get("lng")
        exact = lat is not None and lng is not None
        if not exact:
            got = None
            if r.get("address") or r.get("city"):
                p = geo.parse_coords(r.get("address") or "")
                if p:
                    got = dict(lat=p[0], lng=p[1], exact=True)
                else:
                    c = geo.city_of(" ".join(filter(None, [r.get("address"), r.get("city")])))
                    if c:
                        got = dict(lat=geo.CITIES[c][0], lng=geo.CITIES[c][1], exact=False)
            if not got or (r["kind"] == "store" and not got["exact"]):
                continue                    # a city alone is worse than the store points we already have
            lat, lng, exact = got["lat"], got["lng"], got["exact"]
        try:
            set_place(db, r["kind"], r["code"], float(lat), float(lng), name=r.get("name") or "", address=r.get("address") or "",
                      city=r.get("city") or "", source="imported file" if exact else "imported file (city only)",
                      confirmed=exact, keep_better=True)
            n += 1
        except (ValueError, TypeError):
            continue
    return n
