"""Promotions, category view, sleeping stock, store-to-store transfers (IST) and the supplier view."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from stockcompass.db import Database

from . import sales as SA
from .core import memo, L, Scope, as_of, dp_items, ids_sql, latest_imports, oos_items, prices, zero_stock_daily

VAT = 1.18


# ------------------------------------------------------------------------------------------------
# Promotions (leaflet / theme workbook)
# ------------------------------------------------------------------------------------------------

def themes(db: Database) -> list[dict]:
    return db.qd("""SELECT theme, any_value(theme_name) theme_name, any_value(theme_type) theme_type,
                           min(date_from) date_from, max(date_to) date_to, count(DISTINCT item) items,
                           count(DISTINCT store) stores, max(import_id) import_id
                    FROM leaflet_item GROUP BY theme ORDER BY date_from DESC NULLS LAST""")


def promo(db: Database, scope: Scope, theme: str) -> dict:
    w, p = scope.store_sql("l.store")
    wi, pi = scope.item_sql()
    rows = db.qd(f"""SELECT l.*, i.description, i.section, sec.name section_name, s.name store_name
                    FROM leaflet_item l LEFT JOIN items i USING (item) LEFT JOIN sections sec ON sec.code=i.section
                    LEFT JOIN stores s ON s.code=l.store
                    WHERE l.theme=? AND l.import_id=(SELECT max(import_id) FROM leaflet_item WHERE theme=?)
                    AND {w} AND {wi}""", [theme, theme] + p + pi)
    if not rows:
        return {}
    for r in rows:
        r["zero"] = (r["stock_qty"] or 0) <= 0
        r["on_order"] = (r["on_order_qty"] or 0) > 0
        r["below_cost"] = bool(r["pp"] and r["sp"] and r["sp"] < r["pp"])
        r["issue"] = ("Priced below cost" if r["below_cost"] else
                      ("Out of stock, not on order" if r["zero"] and not r["on_order"] else
                       ("Out of stock, on order" if r["zero"] else "OK")))
    by_store = defaultdict(list)
    for r in rows:
        by_store[r["store"]].append(r)
    ready = [dict(store=k, store_name=v[0]["store_name"], items=len(v),
                  ready=sum(1 for r in v if not r["zero"]) / len(v) * 100,
                  zero_not_ordered=sum(1 for r in v if r["zero"] and not r["on_order"])) for k, v in by_store.items()]
    ready.sort(key=lambda x: x["ready"])
    d0 = min((r["date_from"] for r in rows if r["date_from"]), default=None)
    d1 = max((r["date_to"] for r in rows if r["date_to"]), default=None)
    sales = None
    if d0 and d1:
        items = list({r["item"] for r in rows})
        if items:
            ph = ",".join("?" * len(items))
            sales = db.one(f"""SELECT sum(sales) FROM sales_item WHERE item IN ({ph}) AND date_from >= ? AND date_to <= ?""",
                           items + [d0, d1])
    n = len(rows)
    return dict(rows=sorted(rows, key=lambda r: (r["issue"] == "OK", r["on_order"], r["store"])), by_store=ready,
                items=len({r["item"] for r in rows}), stores=len(by_store), lines=n,
                ready=sum(1 for r in rows if not r["zero"]) / n * 100,
                zero_pct=sum(1 for r in rows if r["zero"]) / n * 100,
                zero_not_ordered=sum(1 for r in rows if r["zero"] and not r["on_order"]),
                below_cost=len({r["item"] for r in rows if r["below_cost"]}), date_from=d0, date_to=d1,
                running=bool(d1 and d1 >= date.today()), promo_sales=sales)


# ------------------------------------------------------------------------------------------------
# Category view: one row per section
# ------------------------------------------------------------------------------------------------
ROLE_NAMES = {"traffic": ("Traffic builder", "ٹریفک"), "profit": ("Profit maker", "منافع"),
              "dest": ("Destination", "منزل"), "occ": ("Occasional", "کبھی کبھار")}


@memo
def category(db: Database, scope: Scope, period: str) -> list[dict]:
    sc = Scope(stores=scope.stores, formats=scope.formats, dept=scope.dept, region=scope.region)
    rows, info = SA.block_rows(db, sc, period)
    if not rows:
        return []
    days = {"DAY": 1, "WTD": 7, "MTD": max(1, info["date"].day), "YTD": info["date"].timetuple().tm_yday}.get(period, 30)
    secs = SA._agg(rows, "section", "section_name")
    tot = sum(s["sales"] for s in secs) or 1
    # zero stock % per section (month to date) and DP stock per section
    zs = defaultdict(lambda: [0.0, 0.0])
    for r in db.qd("""SELECT z.section, sum(z.zero_items) z, sum(z.total_items) t FROM zs_daily z
                      WHERE z.level='section' AND NOT coalesce(z.suspect, false)
                      AND (CAST(? AS DATE) IS NULL OR z.day <= CAST(? AS DATE))
                      AND z.day >= date_trunc('month', (SELECT max(day) FROM zs_daily WHERE (CAST(? AS DATE) IS NULL OR day <= CAST(? AS DATE)))) GROUP BY 1""",
                     [as_of()] * 4):
        zs[r["section"]] = [r["z"], r["t"]]
    dp = defaultdict(float)
    for r in dp_items(db, sc):
        dp[r["section"]] += r["value"] or 0
    tail = defaultdict(list)
    item_sales = db.qd("""SELECT i.section, s.item, sum(s.sales) v FROM sales_item s JOIN items i USING (item)
                          GROUP BY 1, 2""")
    for r in item_sales:
        if r["v"]:
            tail[r["section"]].append(r["v"])
    out = []
    for s in secs:
        k = s["key"]
        share = s["sales"] / tot
        m = s["margin"] if s["margin"] is not None else 0
        role = "traffic" if m < 6 and share > 0.05 else ("profit" if m >= 15 and share < 0.05 else
                                                         ("dest" if share >= 0.08 else "occ"))
        gm = (s["sales"] * m / 100) / s["stock_value"] * (365 / days) if s["stock_value"] else None
        z, t_ = zs.get(k, [0, 0])
        vals = sorted(tail.get(k, []), reverse=True)
        n80 = 0
        if vals:
            acc, total = 0.0, sum(vals)
            for v in vals:
                acc += v
                n80 += 1
                if acc >= 0.8 * total:
                    break
        out.append(dict(s, role=role, role_name=L(*ROLE_NAMES[role]), gmroi=gm,
                        zero_pct=z / t_ * 100 if t_ else None, dp_value=dp.get(k) or None,
                        tail=f"{n80} of {len(vals)}" if vals else None,
                        tail_pct=n80 / len(vals) * 100 if vals else None))
    return out


# ------------------------------------------------------------------------------------------------
# Sleeping stock: stock on hand with no sale for 30 days (CG) / 60 days (non-food)
# ------------------------------------------------------------------------------------------------

@memo
def sleeping(db: Database, scope: Scope) -> tuple[list[dict], str]:
    rt = latest_imports(db, "gima_realtime")
    if not rt:
        return [], L("Needs a GIMA RealTime file (stock on hand) for the store.", "جیما ریئل ٹائم فائل درکار ہے۔")
    cg_days = int(db.setting("sleeping_days_cg") or 30)
    nf_days = int(db.setting("sleeping_days_nonfood") or 60)
    w, p = scope.store_sql("s.store")
    wi, pi = scope.item_sql()
    stock = db.qd(f"""SELECT s.store, s.item, s.qty, s.cost, s.price, s.status, s.snap_date, i.description, i.dept,
                             i.section, sec.name section_name, st.name store_name, sup.name supplier_name
                      FROM stock_item s LEFT JOIN items i USING (item) LEFT JOIN sections sec ON sec.code=i.section
                      LEFT JOIN stores st ON st.code=s.store LEFT JOIN suppliers sup ON sup.code=i.supplier
                      WHERE s.import_id IN {ids_sql([i for i, _, _ in rt])} AND s.qty > 0
                      AND coalesce(s.status,'AC')='AC' AND {w} AND {wi}""", p + pi)
    if not stock:
        return [], ""
    # benchmark coverage per store: union of imported periods
    cover = defaultdict(set)
    for st, a, b in db.q("SELECT store, min(date_from), max(date_to) FROM sales_item GROUP BY store, import_id"):
        if a and b:
            d = a
            while d <= b:
                cover[st].add(d)
                d += timedelta(days=1)
    sold = {(s, i) for s, i in db.q("SELECT DISTINCT store, item FROM sales_item WHERE qty > 0")}
    last_out = {(s, i): d for s, i, d in db.q("SELECT store, item, max(last_out) FROM zero_item GROUP BY 1, 2")}
    out, missing = [], set()
    for r in stock:
        need = cg_days if r["dept"] in ("01", None, "") else nf_days
        snap = r["snap_date"] or date.today()
        window = {snap - timedelta(days=k) for k in range(need)}
        covered = len(window & cover.get(r["store"], set()))
        if covered < need * 0.9:
            missing.add(r["store"])
            continue
        if (r["store"], r["item"]) in sold:
            continue
        r["days_rule"] = need
        r["value"] = (r["qty"] or 0) * (r["cost"] or 0)
        r["last_sale"] = last_out.get((r["store"], r["item"]))
        out.append(r)
    note = ""
    if missing:
        note = L(f"Stores without benchmark sales covering the last {cg_days}/{nf_days} days were skipped: "
                 f"{', '.join(sorted(missing))}. Import daily or monthly benchmark files for them.",
                 "کچھ اسٹورز کے لیے بینچ مارک سیلز کافی دنوں کی نہیں۔")
    return sorted(out, key=lambda r: -r["value"]), note


# ------------------------------------------------------------------------------------------------
# Move stock between stores (IST)
# ------------------------------------------------------------------------------------------------

@memo
def ist(db: Database, scope: Scope) -> list[dict]:
    """Source: aged (DP) stock, or sleeping stock, in one store. Destination: the same item out of stock in
    another store where it normally sells (DLYAVG > 0). Same region first. Qty = up to 30 days of sales."""
    region = {c: r for c, r in db.q("SELECT code, region FROM stores")}
    fmt = {c: f for c, f in db.q("SELECT code, format FROM stores")}
    names = {c: n for c, n in db.q("SELECT code, name FROM stores")}
    sources = defaultdict(list)
    for r in dp_items(db, Scope()):
        if (r["qty"] or 0) > 0:
            sources[r["item"]].append(dict(store=r["store"], qty=r["qty"], why="Aged (DP)", value=r["value"] or 0,
                                           cost=r["cost"]))
    sl, _ = sleeping(db, Scope())
    for r in sl:
        sources[r["item"]].append(dict(store=r["store"], qty=r["qty"], why="Not selling", value=r["value"], cost=r["cost"]))
    out = []
    for d in oos_items(db, Scope()):
        if not (d["dlyavg"] or 0) > 0 or d["item"] not in sources:
            continue
        if scope.stores and d["store"] not in scope.stores and not any(s["store"] in scope.stores for s in sources[d["item"]]):
            continue
        cands = [s for s in sources[d["item"]] if s["store"] != d["store"]
                 and (fmt.get(s["store"]) == "M") == (fmt.get(d["store"]) == "M")]
        if not cands:
            continue
        cands.sort(key=lambda s: (region.get(s["store"]) != region.get(d["store"]), -s["qty"]))
        s = cands[0]
        qty = min(s["qty"], max(1, round(d["dlyavg"] * 30)))
        out.append(dict(item=d["item"], description=d["description"], section_name=d["section_name"],
                        from_store=names.get(s["store"], s["store"]), to_store=names.get(d["store"], d["store"]),
                        qty=qty, why=s["why"], sells_per_day=d["dlyavg"],
                        value=qty * (s["cost"] or 0), same_region=region.get(s["store"]) == region.get(d["store"]),
                        lost_per_day=d["lost_per_day"]))
    return sorted(out, key=lambda r: -(r["value"] or 0))


# ------------------------------------------------------------------------------------------------
# Supplier view
# ------------------------------------------------------------------------------------------------

def supplier(db: Database, code: str, scope: Scope, period: str | None) -> dict:
    name = db.one("SELECT name FROM suppliers WHERE code=?", [code], code)
    out = dict(code=code, name=name)
    if period:
        rows = [r for r in SA.fss_rows(db, scope, period) if r["supplier"] == code]
        if rows:
            g = SA._fss_group(rows, "supplier", "supplier_name")[0]
            out["sales"] = g
            out["families"] = SA._fss_group(rows, "family", "family_name")
    out["oos"] = [r for r in oos_items(db, scope) if r["supplier"] == code]
    lpos = db.qd("""SELECT l.*, s.name store_name FROM lpo l LEFT JOIN stores s ON s.code=l.store
                    WHERE l.supplier=? AND l.import_id IN (SELECT max(import_id) FROM imports WHERE report_type='lpo_list'
                    GROUP BY stores)""", [code])
    snap = max((r["lpo_date"] for r in lpos if r["lpo_date"]), default=None)
    for r in lpos:
        r["late_days"] = (snap - r["delivery_date"]).days if (snap and r["delivery_date"] and r["status"] == "EM"
                                                             and not r["deleted"] and r["delivery_date"] < snap) else 0
    out["lpo"] = lpos
    valid = [r for r in lpos if not r["deleted"]]
    out["received_pct"] = (sum(r["grn_value"] or 0 for r in valid) / sum(r["value"] or 0 for r in valid) * 100
                           if valid and sum(r["value"] or 0 for r in valid) else None)
    out["purge_pct"] = sum(1 for r in lpos if r["deleted"]) / len(lpos) * 100 if lpos else None
    out["dp"] = [r for r in dp_items(db, scope) if r["supplier"] == code]
    return out
