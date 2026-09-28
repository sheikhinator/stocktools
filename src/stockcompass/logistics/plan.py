"""What the map shows and plans: store health on the map, suppliers and their open orders on the road, and the
transfer (IST) plan built from the Order Advisor, grouped into vehicle runs with km, time, fuel and cost."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from stockcompass.analytics import core as A
from stockcompass.analytics.core import Scope
from stockcompass.db import Database

from . import costs as C
from . import geo, places as P, routing as R


def _cartons(qty: float, pcb: float, cfg: dict) -> float:
    pcb = float(pcb or 0)
    return qty / pcb if pcb > 1 else qty / float(cfg.get("units_per_carton") or 12)


# ------------------------------------------------------------------------------------------------ transfers (IST)
def transfers(db: Database, dept: str | None = None, section: str | None = None, vehicles: dict | None = None,
              exclude: list | None = None, online: bool | None = None, advice: dict | None = None) -> dict:
    """Every transfer the Order Advisor suggests, grouped per sending store and destination city into runs.
    vehicles: {run_id: vehicle key} to override the automatic choice; exclude: run ids or 'from>to' pairs left out."""
    from stockcompass.analytics import orders as O
    cfg = C.settings(db)
    adv = advice or O.advise(db, None, None, dept, section, None, limit=100000)
    pts = P.points(db)
    names = {s["code"]: s["name"] for s in db.store_list()}
    exclude = set(exclude or [])
    pairs: dict = {}
    for l in adv["lines"]:
        if not l.get("ist_qty") or not l.get("ist_from"):
            continue
        k = f"{l['ist_from']}>{l['store']}"
        p = pairs.setdefault(k, dict(key=k, src=l["ist_from"], dst=l["store"], lines=0, units=0.0, cartons=0.0, value=0.0,
                                     risk=0.0, aged=0, items=[]))
        q = float(l["ist_qty"])
        p["lines"] += 1
        p["units"] += q
        p["cartons"] += _cartons(q, l.get("pcb"), cfg)
        p["value"] += q * float(l.get("cost") or 0)
        p["risk"] += float(l.get("lost_risk") or 0)
        p["aged"] += 1 if "aged" in (l.get("reason") or "") else 0
        if len(p["items"]) < 400:
            p["items"].append(dict(item=l["item"], description=l.get("description"), qty=q, value=q * float(l.get("cost") or 0)))
    runs = []
    groups = defaultdict(list)
    for p in pairs.values():
        if p["key"] in exclude:
            continue
        a, b = pts.get(("store", p["src"])), pts.get(("store", p["dst"]))
        if not a or not b:
            continue
        p["dst_city"] = b.get("city") or geo.nearest_city((b["lat"], b["lng"]))
        groups[(p["src"], p["dst_city"])].append(p)
    for (src, city), ps in sorted(groups.items()):
        rid = f"{src}:{city}"
        if rid in exclude:
            continue
        a = pts[("store", src)]
        start = (a["lat"], a["lng"])
        stops = [(pts[("store", p["dst"])]["lat"], pts[("store", p["dst"])]["lng"]) for p in ps]
        order = R.order_stops(db, start, stops, back=True)
        ps = [ps[i] for i in order]
        path = [start] + [stops[i] for i in order] + [start]
        rt = R.route(db, path, online)
        cartons = sum(p["cartons"] for p in ps)
        auto_v, trips = C.pick_vehicle(db, cartons, cfg)
        v = next((x for x in cfg["vehicles"] if x["key"] == (vehicles or {}).get(rid)), None) or auto_v
        if v is not auto_v:
            trips = max(1, int(-(-cartons // max(1, v.get("cap_cartons") or 1))))
        c = C.trip_cost(db, rt["km"] * trips, rt["minutes"] * trips, v, stops=len(ps) * trips, cfg=cfg)
        value = sum(p["value"] for p in ps)
        pct = c["total"] / value * 100 if value else None
        runs.append(dict(id=rid, src=src, src_name=names.get(src, src), city=city, vehicle=v["key"], vehicle_name=v["name"],
                         auto_vehicle=auto_v["key"], trips=trips, cartons=cartons, units=sum(p["units"] for p in ps),
                         lines=sum(p["lines"] for p in ps), value=value, risk=sum(p["risk"] for p in ps),
                         aged=sum(p["aged"] for p in ps), fill=cartons / max(1, (v.get("cap_cartons") or 1) * trips) * 100,
                         route_source=rt["source"], geometry=rt["geometry"],
                         stops=[dict(store=p["dst"], name=names.get(p["dst"], p["dst"]), key=p["key"], lines=p["lines"],
                                     units=p["units"], cartons=p["cartons"], value=p["value"], risk=p["risk"], items=p["items"][:60])
                                for p in ps],
                         cost_pct=pct, worth=pct is not None and pct <= float(cfg["max_cost_pct"]), **c))
    runs.sort(key=lambda r: -(r["value"] or 0))
    tot = dict(runs=len(runs), trips=sum(r["trips"] for r in runs), km=sum(r["km"] for r in runs),
               hours=sum(r["hours"] for r in runs), litres=sum(r["litres"] for r in runs),
               fuel_pkr=sum(r["fuel_pkr"] for r in runs), cost=sum(r["total"] for r in runs),
               value=sum(r["value"] for r in runs), risk=sum(r["risk"] for r in runs),
               not_worth=sum(1 for r in runs if not r["worth"]), excluded=len(exclude))
    tot["cost_pct"] = tot["cost"] / tot["value"] * 100 if tot["value"] else None
    return dict(runs=runs, totals=tot, as_of=adv.get("as_of"), max_cost_pct=cfg["max_cost_pct"], fuel=cfg["fuel"],
                estimated=any(r["route_source"] == "estimate" for r in runs))


# ------------------------------------------------------------------------------------------------ trip calculator
def trip(db: Database, start: dict, stops: list[dict], vehicle_key: str | None = None, back: bool = True,
         optimise: bool = False, cartons: float = 0, value: float = 0, online: bool | None = None) -> dict:
    """start / stops: {lat, lng, name}. Returns route, cost and the stop order used."""
    cfg = C.settings(db)
    s = (float(start["lat"]), float(start["lng"]))
    st = [(float(x["lat"]), float(x["lng"])) for x in stops]
    order = R.order_stops(db, s, st, back) if optimise else list(range(len(st)))
    path = [s] + [st[i] for i in order] + ([s] if back else [])
    rt = R.route(db, path, online)
    if vehicle_key:
        v, trips = C.vehicle(db, vehicle_key), 1
        if cartons and v.get("cap_cartons"):
            trips = max(1, int(-(-cartons // v["cap_cartons"])))
    else:
        v, trips = C.pick_vehicle(db, cartons, cfg)
    c = C.trip_cost(db, rt["km"] * trips, rt["minutes"] * trips, v, stops=len(st) * trips, cfg=cfg)
    names = [start.get("name") or "Start"] + [stops[i].get("name") or f"Stop {i + 1}" for i in order] + ([start.get("name") or "Start"] if back else [])
    legs = [dict(frm=names[i], to=names[i + 1], km=l["km"], minutes=l["minutes"]) for i, l in enumerate(rt.get("legs") or [])]
    return dict(order=order, vehicle=v["key"], vehicle_name=v["name"], trips=trips, geometry=rt["geometry"], source=rt["source"],
                legs=legs, cost_pct=c["total"] / value * 100 if value else None,
                per_carton=c["total"] / cartons if cartons else None, **c)


# ------------------------------------------------------------------------------------------------ layers
def orders_on_road(db: Database, sc: Scope) -> dict:
    """Open orders (issued, not received, not purged) from each supplier to each store, late ones flagged."""
    rows, snap = A.lpo_rows(db, sc)
    pts = P.points(db)
    lines = defaultdict(lambda: dict(n=0, value=0.0, late=0, late_value=0.0, max_late=0, lpos=[]))
    for r in rows:
        if r.get("deleted") or r.get("status") != "EM" or not r.get("supplier"):
            continue
        k = (r["supplier"], r["store"])
        l = lines[k]
        l["n"] += 1
        l["value"] += r["value"] or 0
        if r["late_days"]:
            l["late"] += 1
            l["late_value"] += r["value"] or 0
            l["max_late"] = max(l["max_late"], r["late_days"])
        if len(l["lpos"]) < 30:
            l["lpos"].append(dict(lpo=r["lpo_no"], due=r["delivery_date"], value=r["value"], late=r["late_days"]))
    sup_names = {c: n for c, n in db.q("SELECT code, name FROM suppliers")}
    out, missing = [], defaultdict(lambda: dict(n=0, value=0.0, late=0))
    for (sup, st), l in lines.items():
        a, b = pts.get(("supplier", sup)), pts.get(("store", st))
        if not a:
            m = missing[sup]
            m["n"] += l["n"]
            m["value"] += l["value"]
            m["late"] += l["late"]
            continue
        if not b:
            continue
        leg = R.estimate_leg((a["lat"], a["lng"]), (b["lat"], b["lng"]), R.speeds(db))
        out.append(dict(supplier=sup, supplier_name=sup_names.get(sup, sup), store=st, frm=[a["lat"], a["lng"]], to=[b["lat"], b["lng"]],
                        km=leg["km"], minutes=leg["minutes"], **l))
    miss = sorted([dict(supplier=k, name=sup_names.get(k, k), **v) for k, v in missing.items()], key=lambda x: -x["value"])
    return dict(lines=sorted(out, key=lambda x: -x["value"]), unlocated=miss, as_of=snap,
                open_total=sum(l["n"] for l in lines.values()), open_value=sum(l["value"] for l in lines.values()))


def suppliers(db: Database, sc: Scope) -> list[dict]:
    """Supplier by supplier: where it is, stores served, open / late orders, real lead time and distance."""
    from stockcompass.analytics.orders import supplier_lead_times
    rows, _ = A.lpo_rows(db, sc)
    pts = P.points(db)
    lead = supplier_lead_times(db)
    names = {c: n for c, n in db.q("SELECT code, name FROM suppliers")}
    agg = defaultdict(lambda: dict(orders=0, value=0.0, open=0, late=0, stores=set()))
    for r in rows:
        if not r.get("supplier") or r.get("deleted"):
            continue
        a = agg[r["supplier"]]
        a["orders"] += 1
        a["value"] += r["value"] or 0
        a["open"] += 1 if r.get("status") == "EM" else 0
        a["late"] += 1 if r["late_days"] else 0
        a["stores"].add(r["store"])
    sp = R.speeds(db)
    out = []
    for sup, a in agg.items():
        p = pts.get(("supplier", sup))
        dists = []
        if p:
            for st in a["stores"]:
                b = pts.get(("store", st))
                if b:
                    dists.append(R.estimate_leg((p["lat"], p["lng"]), (b["lat"], b["lng"]), sp)["km"])
        out.append(dict(supplier=sup, name=names.get(sup, sup), located=bool(p), exact=bool(p and p["exact"]),
                        city=(p or {}).get("city"), lat=(p or {}).get("lat"), lng=(p or {}).get("lng"), orders=a["orders"],
                        value=a["value"], open=a["open"], late=a["late"], late_pct=a["late"] / a["orders"] * 100 if a["orders"] else None,
                        stores=len(a["stores"]), lead_days=lead.get(sup), avg_km=sum(dists) / len(dists) if dists else None))
    return sorted(out, key=lambda x: -x["value"])


def store_layer(api, ctx: dict) -> list[dict]:
    """Every store with its key numbers (same engine as Analyse) for colouring the map."""
    from stockcompass.web import explore as E
    ms = ["sales", "vs_budget", "zero_pct", "not_on_order", "lost_day", "dp_value", "late_count"]
    try:
        cb = E.cube(api, {**ctx, "where": "all"}, dim="store", measures=ms)
        vals = {r["k"]: r["v"] for r in cb["rows"]}
    except Exception:
        vals = {}
    out = []
    for p in P.all_places(api.db, with_suppliers=False):
        if p["kind"] == "store":
            out.append({**p, "v": vals.get(p["code"], {})})
    return out


def distance_table(db: Database, codes: list[str] | None = None) -> dict:
    """Store-to-store km and hours (road route when fetched before, else estimate)."""
    pts = [p for p in P.all_places(db, with_suppliers=False) if p["kind"] == "store" and (not codes or p["code"] in codes)]
    sp = R.speeds(db)
    rows = []
    for a in pts:
        row = dict(k=a["code"], name=a["name"], v={})
        for b in pts:
            if a is b:
                continue
            l = R.estimate_leg((a["lat"], a["lng"]), (b["lat"], b["lng"]), sp)
            row["v"][b["code"]] = dict(km=l["km"], h=l["minutes"] / 60)
        rows.append(row)
    return dict(stores=[dict(code=p["code"], name=p["name"]) for p in pts], rows=rows, as_of=date.today().isoformat())
