"""Vehicles, fuel prices and what a trip costs (fuel + driver/helper time + fixed cost per trip)."""

from __future__ import annotations

import html
import re
from datetime import date

from stockcompass.db import Database

from . import net

# Typical Pakistani delivery vehicles. Everything is editable in the map's Costs & vehicles panel.
DEFAULT_VEHICLES = [
    dict(key="pickup", name="Pickup (Suzuki Ravi / loader)", cap_kg=800, cap_m3=4, cap_cartons=120, km_per_l=11, fuel="petrol",
         crew_cost_hr=450, fixed_trip=500),
    dict(key="shehzore", name="Shehzore / 2-ton truck", cap_kg=2000, cap_m3=11, cap_cartons=300, km_per_l=8, fuel="diesel",
         crew_cost_hr=600, fixed_trip=800),
    dict(key="mazda", name="Mazda 6-wheeler (5 ton)", cap_kg=5000, cap_m3=22, cap_cartons=650, km_per_l=6, fuel="diesel",
         crew_cost_hr=750, fixed_trip=1500),
    dict(key="container20", name="20 ft container truck", cap_kg=12000, cap_m3=33, cap_cartons=1000, km_per_l=4, fuel="diesel",
         crew_cost_hr=900, fixed_trip=3000),
    dict(key="trailer40", name="40 ft trailer", cap_kg=25000, cap_m3=67, cap_cartons=2000, km_per_l=3, fuel="diesel",
         crew_cost_hr=1000, fixed_trip=5000),
]
DEFAULT_FUEL = dict(petrol=265.0, diesel=275.0, as_of=None, source="default (please update)")
DEFAULTS = dict(dc_store="500", dc_vehicle_city="mazda", dc_vehicle_intercity="container20", online=True, router="", city_kmh=22, highway_kmh=60, truck_factor=1.25, stop_minutes=45,
                carton_m3=0.04, max_cost_pct=8.0, working_hours=10)


def settings(db: Database) -> dict:
    s = {**DEFAULTS, **(db.setting("logistics") or {})}
    s["vehicles"] = s.get("vehicles") or DEFAULT_VEHICLES
    s["fuel"] = {**DEFAULT_FUEL, **(s.get("fuel") or {})}
    return s


def save_settings(db: Database, changes: dict) -> dict:
    cur = {**(db.setting("logistics") or {})}
    for k, v in (changes or {}).items():
        if k == "fuel":
            cur["fuel"] = {**(cur.get("fuel") or {}), **v}
        elif k in DEFAULTS or k == "vehicles":
            cur[k] = v
    db.set_setting("logistics", cur)
    from . import routing
    routing.clear_memory()
    return settings(db)


def vehicle(db: Database, key: str | None) -> dict:
    vs = settings(db)["vehicles"]
    return next((v for v in vs if v["key"] == key), vs[1] if len(vs) > 1 else vs[0])


def trip_cost(db: Database, km: float, minutes: float, veh: dict, stops: int = 1, cfg: dict | None = None) -> dict:
    cfg = cfg or settings(db)
    price = float(cfg["fuel"].get(veh.get("fuel") or "diesel") or 0)
    litres = km / max(0.5, float(veh.get("km_per_l") or 5))
    hours = (minutes + stops * float(cfg.get("stop_minutes") or 45)) / 60
    fuel_pkr = litres * price
    crew = hours * float(veh.get("crew_cost_hr") or 0)
    total = fuel_pkr + crew + float(veh.get("fixed_trip") or 0)
    return dict(km=km, minutes=minutes, hours=hours, litres=litres, fuel_price=price, fuel_pkr=fuel_pkr, crew_pkr=crew,
                fixed_pkr=float(veh.get("fixed_trip") or 0), total=total, per_km=total / km if km else None,
                days=max(1, -(-hours // float(cfg.get("working_hours") or 10))) if hours else 0)


def pick_vehicle(db: Database, cartons: float, cfg: dict | None = None) -> tuple[dict, int]:
    """The smallest vehicle that carries the load in one trip; else the biggest, with the number of trips."""
    vs = sorted((cfg or settings(db))["vehicles"], key=lambda v: v.get("cap_cartons") or 0)
    for v in vs:
        if cartons <= (v.get("cap_cartons") or 0):
            return v, 1
    big = vs[-1]
    return big, int(-(-cartons // max(1, big.get("cap_cartons") or 1)))


# ------------------------------------------------------------------------------------------------ fuel prices
FUEL_SOURCES = ["https://psopk.com/en/product-and-services/product-prices/pol"]


def _text(b: bytes) -> str:
    s = b.decode("utf-8", "replace")
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", s, flags=re.S | re.I)
    return html.unescape(re.sub(r"<[^>]+>", " ", s))


def parse_prices(text: str) -> dict:
    out = {}
    for key, rx in (("petrol", r"(?:Motor\s*(?:Spirit|Gasoline)|Petrol|PMG|Super)"), ("diesel", r"(?:High\s*Speed\s*Diesel|HSD|Diesel)")):
        for m in re.finditer(rx + r"[^0-9]{0,160}?(\d{3}(?:[.,]\d{1,2})?)", text, re.I):
            v = float(m.group(1).replace(",", "."))
            if 120 <= v <= 700:
                out[key] = v
                break
    return out


def fetch_fuel(db: Database) -> dict:
    """Latest pump prices from the web; keeps the current ones when nothing can be read."""
    for url in FUEL_SOURCES:
        b = net.fetch(url, timeout=10)
        if not b:
            continue
        got = parse_prices(_text(b))
        if got:
            save_settings(db, {"fuel": {**got, "as_of": date.today().isoformat(), "source": net.host_of(url)}})
            return dict(ok=True, **settings(db)["fuel"])
    return dict(ok=False, error="Could not read the latest prices (no internet, or the price page changed). Type them in instead.",
                **settings(db)["fuel"])
