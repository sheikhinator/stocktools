"""The data library: everything imported is kept on this PC, by report, store and date.

- STEPS: the guided setup. Each step is one report: where to get it, how often, what it unlocks, and its status
  (how many stores and which dates are already saved). The Order Advisor lists the steps it needs the same way.
- library(): every report type with the dates saved, the stores covered and the rows kept.
- coverage(): store x report grid with the latest date each store has (so a district manager sees who sent what).
"""

from __future__ import annotations

from datetime import date

from stockcompass.db import Database
from stockcompass.importer.spec import REGISTRY

# key, title, report types, where to get it, how often, what it unlocks, per store?, essential?
STEPS = [
    dict(key="stock", title="Stock on hand, per store", types=["gima_realtime"],
         where="GIMA → RealTime stock report, all items of one store (export to Excel). One file per store.",
         when="Daily, and always before ordering", per_store=True, essential=True,
         unlocks=["Stock health", "Order Advisor", "IST suggestions", "Negative stock", "Not selling"]),
    dict(key="sales_items", title="Item sales (how fast items sell)", types=["gima_benchmark"],
         where="GIMA → Benchmark report, item × store, for the last 4 weeks (longer is better).",
         when="Weekly", per_store=False, essential=True,
         unlocks=["Order Advisor quantities", "Not selling", "ABC classes", "Item sales"]),
    dict(key="zero_items", title="Zero stock items with reasons", types=["gima_zero_stock"],
         where="GIMA → zero stock sheet (items at zero with reason, open order, last sale, daily average).",
         when="Daily", per_store=False, essential=True,
         unlocks=["Out of stock", "Not on order", "Lost sales", "Order Advisor open orders"]),
    dict(key="orders", title="Purchase orders (LPO list)", types=["lpo_list"],
         where="GIMA → LPO list for the last 60–90 days (all statuses).",
         when="Daily or weekly", per_store=False, essential=True,
         unlocks=["Late orders", "Supplier lead times", "Order Advisor lead time", "Duplicate orders"]),
    dict(key="zero_bc", title="Zero stock % (BC)", types=["bo_zero_summary"],
         where="BO → 500-30-15 zero stock summary, month to date.",
         when="Daily", per_store=False, essential=True, unlocks=["Zero stock %", "BC scorecard", "Store ranking"]),
    dict(key="dp", title="Aged (DP) stock", types=["dp_master"],
         where="DP workbook from the BC / finance team (master data tab, item level).",
         when="Monthly (or when sent)", per_store=False, essential=True,
         unlocks=["Aged stock", "DP provision", "Items ageing into DP", "Order Advisor stop rules"]),
    dict(key="sales", title="Sales vs budget and last year", types=["bo_11b", "bo_store_net_sales"],
         where="BO → 11b (section tab) or 200-10-05 store net sales.",
         when="Daily", per_store=False, essential=True, unlocks=["Sales", "Budget gap", "Store ranking"]),
    dict(key="sales_fss", title="Sales by family and supplier", types=["bo_11f", "bo_family_sales"],
         where="BO → 11f (store tab) and family sales year on year.",
         when="Weekly", per_store=False, essential=False, unlocks=["Families", "Suppliers", "Bulk (B2B)"]),
    dict(key="leaflet", title="Leaflet / promotion items", types=["leaflet_theme"],
         where="Leaflet workbook from the marketing / category team.",
         when="For every leaflet", per_store=False, essential=False,
         unlocks=["Promotions", "Leaflet readiness", "Order Advisor promo uplift"]),
    dict(key="negative", title="Negative stock", types=["gima_negative_stock"],
         where="GIMA → negative stock sheet.", when="Daily", per_store=False, essential=False,
         unlocks=["Negative stock with cause"]),
    dict(key="bc", title="BC scorecard", types=["bc_scorecard", "blocked_007"],
         where="BC workbook from the BC team (scorecard tab and blocked 007 tab).",
         when="Weekly", per_store=False, essential=False, unlocks=["BC scorecard", "Blocked stock"]),
    # files the Order Advisor will use once head office shares them: the importer keeps them as tables meanwhile
    dict(key="lpo_lines", title="Open orders by item (LPO lines)", types=[],
         where="Coming: GIMA open-order lines per item and store (qty ordered / received). Ask head office for the report.",
         when="Daily", per_store=False, essential=False, future=True,
         unlocks=["Exact on-order quantity per item (today the zero stock sheet gives it for out-of-stock items)"]),
    dict(key="sales_weeks", title="Weekly sales history (8–12 weeks)", types=[],
         where="Coming: Benchmark by week, or a weekly item sales extract. Each Benchmark you import is kept, so history also builds up by itself.",
         when="Weekly", per_store=False, essential=False, future=True,
         unlocks=["Safety stock from real sales swings", "Promotion uplift", "Trends"]),
]

ADVISOR_STEPS = ["stock", "sales_items", "zero_items", "orders", "dp", "leaflet", "lpo_lines", "sales_weeks"]

GROUP = {"gima_realtime": "Stock", "gima_negative_stock": "Stock", "blocked_007": "Stock", "bo_stock_days": "Stock",
         "bo_stock_movement": "Stock", "gima_zero_stock": "Availability", "bo_zero_summary": "Availability",
         "bo_leaflet_zero": "Availability", "gima_benchmark": "Sales", "bo_11b": "Sales", "bo_11f": "Sales",
         "bo_family_sales": "Sales", "bo_store_net_sales": "Sales", "lpo_list": "Orders", "bo_variance_lines": "Orders",
         "leaflet_theme": "Promotions", "bc_scorecard": "BC"}


def _group(rt: str) -> str:
    if rt.startswith("dp_"):
        return "Aged stock (DP)"
    if rt.startswith("bc_"):
        return "BC"
    return GROUP.get(rt, "Other")


def library(db: Database) -> list[dict]:
    """Every report kept on this PC: dates saved, stores covered, rows."""
    rows = db.qd("""SELECT report_type, count(*) imports, sum("rows") n_rows, min(snapshot_date) first_d, max(snapshot_date) last_d,
                           count(DISTINCT snapshot_date) n_days, max(imported_at) imported_last
                    FROM imports WHERE status='ok' GROUP BY 1""")
    stores_by = {}
    for rt, st in db.q("SELECT report_type, string_agg(coalesce(stores,''), ',') FROM imports WHERE status='ok' GROUP BY 1"):
        stores_by[rt] = sorted({s for s in (st or "").split(",") if s})
    dates_by = {}
    for rt, d, n in db.q("""SELECT report_type, snapshot_date, count(*) FROM imports WHERE status='ok' AND snapshot_date IS NOT NULL
                            GROUP BY 1, 2 ORDER BY 2 DESC"""):
        dates_by.setdefault(rt, []).append(dict(d=str(d), n=n))
    today = date.today()
    out = []
    for r in rows:
        rt = r["report_type"]
        last = r["last_d"]
        out.append(dict(key=rt, name=REGISTRY[rt].name if rt in REGISTRY else rt, group=_group(rt), imports=r["imports"],
                        rows=int(r["n_rows"] or 0), first=str(r["first_d"]) if r["first_d"] else None,
                        last=str(last) if last else None, days=r["n_days"],
                        age=(today - last).days if last else None, stores=stores_by.get(rt, []),
                        dates=dates_by.get(rt, [])[:60]))
    out.sort(key=lambda x: (x["group"], x["name"]))
    return out


def coverage(db: Database) -> dict:
    """Store x report: the latest date each store has, for the per-store reports."""
    types = ["gima_realtime", "gima_zero_stock", "gima_negative_stock", "dp_master", "gima_benchmark", "lpo_list", "leaflet_theme"]
    stores = db.store_list()
    latest: dict[tuple, date] = {}
    for rt, st, d in db.q(f"""SELECT report_type, coalesce(stores,''), max(snapshot_date) FROM imports
                              WHERE status='ok' AND report_type IN ({",".join("?" * len(types))}) GROUP BY 1, 2""", types):
        for s in (st or "").split(","):
            if s and d and (latest.get((rt, s)) is None or d > latest[(rt, s)]):
                latest[(rt, s)] = d
    today = date.today()
    return dict(cols=[dict(k=t, n=REGISTRY[t].name if t in REGISTRY else t) for t in types],
                rows=[dict(store=s["code"], name=s["name"], format=s["format"],
                           cells={t: (dict(d=str(latest[(t, s["code"])]), age=(today - latest[(t, s["code"])]).days)
                                      if (t, s["code"]) in latest else None) for t in types}) for s in stores])


def steps(db: Database, only: list[str] | None = None) -> list[dict]:
    """The guided setup with each step's status on this PC."""
    lib = {x["key"]: x for x in library(db)}
    n_stores = len(db.store_list())
    today = date.today()
    out = []
    for i, st in enumerate(STEPS, 1):
        if only and st["key"] not in only:
            continue
        have = [lib[t] for t in st["types"] if t in lib]
        last = max((h["last"] for h in have if h["last"]), default=None)
        stores = sorted({s for h in have for s in h["stores"]})
        age = (today - date.fromisoformat(last)).days if last else None
        if st.get("future"):
            status, note = "future", "Share this file when you have it; the importer already keeps unknown tables."
        elif not have:
            status, note = "missing", "Not added yet."
        elif age is not None and age > (35 if st["key"] in ("dp", "bc") else 8):
            status, note = "stale", f"Latest is {age} days old."
        elif st["per_store"] and n_stores and len(stores) < n_stores:
            status, note = "partial", f"{len(stores)} of {n_stores} stores."
        else:
            status, note = "done", f"Latest {last}" + (f" · {len(stores)} stores" if stores else "")
        out.append(dict(**{k: v for k, v in st.items() if k != "types"}, n=i, types=st["types"],
                        hint=REGISTRY[st["types"][0]].name if st["types"] and st["types"][0] in REGISTRY else st["title"],
                        status=status, note=note, last=last, age=age, stores=len(stores), total_stores=n_stores,
                        dates=sorted({d["d"] for h in have for d in h["dates"]}, reverse=True)[:30]))
    return out
