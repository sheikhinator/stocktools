"""Analyse: any measure by any dimension, with a second dimension for a matrix, filters, totals and shares.

Every measure belongs to a *fact* (the rows it is added up from). A fact knows which dimensions its rows carry, so
"DP provision by supplier" works while "zero stock % by supplier" says plainly that the BO summary has no supplier.
Ratios (vs budget %, margin %, zero stock %, received %) are always recomputed from the summed base values, for rows,
totals and "Others" alike; printed percentages are never added up.
"""

from __future__ import annotations

from collections import defaultdict

from stockcompass.analytics import core as A
from stockcompass.analytics import extra as X
from stockcompass.analytics import sales as SA
from stockcompass.analytics.core import Scope

FMT_NAMES = {"H": "Hypermarket", "S": "Supermarket", "M": "Myli"}

DIMS = [  # key, label, group
    ("store", "Store", "Where"), ("format", "Format", "Where"), ("region", "Region", "Where"),
    ("dept", "Department", "Range"), ("section", "Section", "Range"), ("family", "Family", "Range"),
    ("supplier", "Supplier", "Range"), ("item", "Item", "Range"),
    ("day", "Day", "Time"),
    ("reason", "GIMA out-of-stock reason", "Detail"), ("bucket", "Ageing bucket", "Detail"),
    ("cause", "Negative stock cause", "Detail"), ("theme", "Promotion / leaflet", "Detail"),
    ("order_type", "Order type", "Detail"),
]
DIM_LABEL = {k: l for k, l, _ in DIMS}
WHERE = {"store", "format", "region"}


def _n(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _ratio(a, b, scale=100.0, minus=0.0):
    return (a / b - minus) * scale if b else None


# ------------------------------------------------------------------------------------------------ measures
# key: (label, fact, kind, formula over the summed fields, help)
MEASURES: dict[str, tuple] = {
    "sales": ("Net sales", "sales", "pkr", lambda s: s["sales"], "Net sales in PKR for the period (BO 11b / net sales, else BO 11f, else GIMA benchmark)."),
    "budget": ("Budget", "sales", "pkr", lambda s: s["budget"] or None, "Sales budget for the period (BO 11b / net sales only)."),
    "vs_budget": ("vs budget %", "sales", "sg", lambda s: _ratio(s["sales_b"], s["budget"], 100, 1), "Sales against budget, recomputed from PKR."),
    "gap_budget": ("Gap to budget", "sales", "pkr", lambda s: (s["sales_b"] - s["budget"]) if s["budget"] else None, "PKR above (+) or below (−) budget."),
    "ly": ("Last year", "sales", "pkr", lambda s: s["ly"] or None, "Sales of the same period last year."),
    "growth": ("Growth vs LY %", "sales", "sg", lambda s: _ratio(s["sales_l"], s["ly"], 100, 1), "Growth against last year, recomputed from PKR."),
    "margin_pct": ("Front margin %", "sales", "pct", lambda s: _ratio(s["margin"], s["sales_m"]), "Front margin (before back margin) as % of sales."),
    "margin": ("Front margin", "sales", "pkr", lambda s: s["margin"] if s["sales_m"] else None, "Front margin in PKR."),
    "qty": ("Units sold", "sales", "int", lambda s: s["qty"] or None, "Units sold in the period."),
    "b2b": ("Bulk (B2B) sales", "sales", "pkr", lambda s: s["b2b"] if s["has_b2b"] else None, "B2B sales (BO 11f only)."),
    "sales_stock": ("Stock value (sales report)", "sales", "pkr", lambda s: s["stock"] or None, "Stock value printed in the sales report."),
    "zero_pct": ("Zero stock % (MTD)", "zero", "pct", lambda s: _ratio(s["zero"], s["total"]), "BC zero stock: item-days with closing stock ≤ 0 over all item-days, month to date."),
    "zero_days": ("Zero stock item-days", "zero", "int", lambda s: s["zero"], "Item-days at zero stock, month to date."),
    "oos": ("Out-of-stock items", "oos", "int", lambda s: s["n"], "Items at zero stock today (GIMA zero stock sheet)."),
    "not_on_order": ("Out of stock, not on order", "oos", "int", lambda s: s["noorder"], "Out-of-stock items with no open order: top priority."),
    "oos_promo": ("Promo / leaflet items out", "oos", "int", lambda s: s["promo"], "Out-of-stock items that are on promotion or in the leaflet."),
    "lost_day": ("Sales lost / day", "oos", "pkr", lambda s: s["lost"], "Daily average sales × price of items out of stock."),
    "lost_to_date": ("Sales lost since out", "oos", "pkr", lambda s: s["lost_td"], "Lost sales since each item went out of stock."),
    "neg_items": ("Negative stock items", "negative", "int", lambda s: s["n"], "Items with stock below zero."),
    "neg_value": ("Negative stock value", "negative", "pkr", lambda s: s["value"], "Cost value of negative stock."),
    "dp_value": ("Aged (DP) stock", "dp", "pkr", lambda s: s["value"], "Cost value of aged (DP) stock."),
    "dp_prov": ("DP provision", "dp", "pkr", lambda s: s["prov"], "Provision booked on aged stock."),
    "dp_extra": ("Extra provision in 30 days", "dp", "pkr", lambda s: s["extra"], "Provision that will be added when items age into the next bucket within 30 days."),
    "dp_items": ("Aged (DP) items", "dp", "int", lambda s: s["n"], "Item × store lines with aged stock."),
    "lpo_value": ("Orders value", "lpo", "pkr", lambda s: s["value"], "Value of LPOs in the LPO list."),
    "lpo_count": ("Orders", "lpo", "int", lambda s: s["n"], "Number of LPOs."),
    "late_count": ("Late orders", "lpo", "int", lambda s: s["late"], "Orders past their delivery date and not received."),
    "late_value": ("Late orders value", "lpo", "pkr", lambda s: s["late_value"], "Value of late orders."),
    "received_pct": ("Received % (value)", "lpo", "pct", lambda s: _ratio(s["grn"], s["value"]), "GRN value over ordered value."),
    "leaf_items": ("Leaflet items", "leaflet", "int", lambda s: s["n"], "Item × store lines in the leaflet / promotion."),
    "leaf_zero": ("Leaflet items at zero", "leaflet", "int", lambda s: s["zero"], "Leaflet lines with zero stock."),
    "leaf_zero_pct": ("Leaflet zero stock %", "leaflet", "pct", lambda s: _ratio(s["zero"], s["n"]), "Share of leaflet lines at zero stock."),
    "sleep_value": ("Stock not selling", "sleeping", "pkr", lambda s: s["value"], "Cost value of stock with no sales for the sleeping threshold (CG 30 d, Non-Food 60 d)."),
    "sleep_items": ("Items not selling", "sleeping", "int", lambda s: s["n"], "Items not selling."),
}

GROUPS = [("Sales", ["sales", "budget", "vs_budget", "gap_budget", "ly", "growth", "margin_pct", "margin", "qty", "b2b", "sales_stock"]),
          ("Availability", ["zero_pct", "zero_days", "oos", "not_on_order", "oos_promo", "lost_day", "lost_to_date"]),
          ("Stock", ["neg_items", "neg_value", "dp_value", "dp_prov", "dp_extra", "dp_items", "sleep_value", "sleep_items"]),
          ("Orders", ["lpo_value", "lpo_count", "late_count", "late_value", "received_pct"]),
          ("Promotions", ["leaf_items", "leaf_zero", "leaf_zero_pct"])]

PRESETS = [
    dict(n="Sales vs budget by store", dim="store", m=["sales", "budget", "vs_budget", "gap_budget", "margin_pct"]),
    dict(n="Sales by department × format", dim="dept", dim2="format", m=["sales"]),
    dict(n="Growth by section", dim="section", m=["sales", "ly", "growth", "margin_pct"]),
    dict(n="Zero stock % store × department", dim="store", dim2="dept", m=["zero_pct"]),
    dict(n="Lost sales by supplier", dim="supplier", m=["lost_day", "oos", "not_on_order"]),
    dict(n="Aged stock by store × ageing bucket", dim="store", dim2="bucket", m=["dp_value"]),
    dict(n="DP provision by supplier", dim="supplier", m=["dp_value", "dp_prov", "dp_extra"]),
    dict(n="Late orders by supplier", dim="supplier", m=["late_count", "late_value", "received_pct"]),
    dict(n="Out of stock by GIMA reason", dim="reason", m=["oos", "not_on_order", "lost_day"]),
    dict(n="Zero stock % by day", dim="day", m=["zero_pct", "zero_days"], chart="line"),
    dict(n="Store scorecard", dim="store", m=["sales", "vs_budget", "zero_pct", "not_on_order", "lost_day", "dp_prov", "late_count"]),
]


# ------------------------------------------------------------------------------------------------ facts
class Facts:
    """Loads the rows of each fact once per request, already cut to the scope, with every dimension filled in."""

    def __init__(self, api, ctx: dict, sc: Scope):
        self.api, self.db, self.ctx, self.sc = api, api.db, ctx, sc
        st = self.db.qd("SELECT code, format, region FROM stores")
        self.fmt = {r["code"]: r["format"] for r in st}
        self.reg = {r["code"]: r["region"] for r in st}
        self.sec_dept = {c: d for c, d in self.db.q("SELECT code, dept FROM sections")}
        self._cache: dict = {}

    def _fill(self, r: dict) -> dict:
        s = r.get("store")
        if s:
            r.setdefault("format", self.fmt.get(s))
            r.setdefault("region", self.reg.get(s))
        if not r.get("dept") and r.get("section"):
            r["dept"] = self.sec_dept.get(r["section"])
        return r

    def load(self, fact: str, need: set[str]) -> tuple[list[dict], set[str], str]:
        key = (fact, frozenset(need) if fact in ("sales", "zero") else None)
        if key not in self._cache:
            if fact.startswith("ds:"):
                from stockcompass.analytics import datasets as D
                rows, dims, name = D.facts(self.db, fact[3:], self.sc)
                self._cache[key] = ([self._fill(r) for r in rows], dims, f"{name} (imported data)")
            else:
                self._cache[key] = getattr(self, "f_" + fact)(need)
        return self._cache[key]

    # sales picks the most detailed source that has the dimensions asked for
    def f_sales(self, need):
        period = self.api.period(self.ctx)
        if not period:
            return [], set(), ""
        tried = []
        rows, info = SA.block_rows(self.db, self.sc, period)
        if rows:
            lvl = info.get("level") or ""
            dims = {"dept"} | ({"section"} if "section" in lvl else set()) | (WHERE if not lvl.startswith("country") else set())
            if need <= dims:
                out = []
                for r in rows:
                    s, b, ly, m = _n(r["sales"]), _n(r["budget"]), r["ly_sales"], r["margin_pct"]
                    out.append(self._fill(dict(store=r["store"], dept=r["dept"], section=r["section"] if "section" in lvl else None,
                                               f=dict(sales=s, budget=b, sales_b=s if b else 0, ly=_n(ly), sales_l=s if ly else 0,
                                                      margin=s * m / 100 if m is not None else 0, sales_m=s if m is not None else 0,
                                                      qty=_n(r["qty"]), b2b=0, has_b2b=0, stock=_n(r["stock_value"])))))
                return out, dims, f"BO {info.get('source', '')} ({period}, {info.get('date')})"
            tried.append("BO 11b")
        f = SA.fss_rows(self.db, self.sc, period)
        if f:
            dims = {"dept", "section", "family", "supplier"} | (WHERE if any(r["store"] for r in f) else set())
            if need <= dims:
                out = []
                for r in f:
                    s, ly, m = _n(r["sales_cy"]), r["sales_ly"], r["margin_pct"]
                    out.append(self._fill(dict(store=r["store"], dept=r["dept"], section=r["section"], family=r["family"], supplier=r["supplier"],
                                               f=dict(sales=s, budget=0, sales_b=0, ly=_n(ly), sales_l=s if ly else 0,
                                                      margin=s * m / 100 if m is not None else 0, sales_m=s if m is not None else 0,
                                                      qty=_n(r["qty_cy"]), b2b=_n(r["b2b_cy"]), has_b2b=1, stock=_n(r["stock_value"])))))
                return out, dims, f"BO 11f ({period}, {r['date_to']})"
        ids = [r[0] for r in self.db.q("SELECT max(import_id) FROM imports WHERE report_type='gima_benchmark' AND status='ok' GROUP BY stores")]
        if ids:
            w, p = self.sc.store_sql("s.store")
            wi, pi = self.sc.item_sql()
            rows = self.db.qd(f"""SELECT s.store, s.item, i.dept, i.section, i.family, i.supplier, sum(s.sales) sales, sum(s.qty) qty,
                                         sum(s.margin) margin FROM sales_item s LEFT JOIN items i USING (item)
                                  WHERE s.import_id IN {A.ids_sql(ids)} AND {w} AND {wi} GROUP BY ALL""", p + pi)
            out = [self._fill(dict(store=r["store"], item=r["item"], dept=r["dept"], section=r["section"], family=r["family"], supplier=r["supplier"],
                                   f=dict(sales=_n(r["sales"]), budget=0, sales_b=0, ly=0, sales_l=0, margin=_n(r["margin"]),
                                          sales_m=_n(r["sales"]) if r["margin"] is not None else 0, qty=_n(r["qty"]), b2b=0, has_b2b=0, stock=0)))
                   for r in rows]
            return out, WHERE | {"dept", "section", "family", "supplier", "item"}, "GIMA benchmark (item sales)"
        return [], set(), ""

    def f_zero(self, need):
        ids = [i for i, _, _ in A.latest_imports(self.db, "bo_zero_summary")]
        if not ids:
            return [], set(), ""
        have = {r[0] for r in self.db.q(f"SELECT DISTINCT level FROM zs_daily WHERE import_id IN {A.ids_sql(ids)}")}
        level = "section" if ("section" in need or self.sc.section) else "dept" if ("dept" in need or self.sc.dept) else ("store" if "store" in have else "dept")
        if level not in have:
            level = next((lv for lv in ("dept", "section", "store") if lv in have), None)
        w, p = self.sc.store_sql()
        wh, pp = [w], list(p)
        if self.sc.section:
            wh.append("section=?")
            pp.append(self.sc.section)
        elif self.sc.dept and level != "store":
            d, dp = self.sc.dept_sql("dept")
            wh.append(d)
            pp += dp
        rows = self.db.qd(f"""SELECT store, dept, section, day, sum(zero_items) z, sum(total_items) t FROM zs_daily
                              WHERE import_id IN {A.ids_sql(ids)} AND level=? AND NOT coalesce(suspect,false)
                              AND day >= date_trunc('month', (SELECT max(day) FROM zs_daily WHERE import_id IN {A.ids_sql(ids)}))
                              AND {' AND '.join(wh)} GROUP BY ALL""", [level] + pp)
        dims = WHERE | {"day"} | ({"dept"} if level in ("dept", "section") else set()) | ({"section"} if level == "section" else set())
        out = [self._fill(dict(store=r["store"], dept=r["dept"] if level != "store" else None, section=r["section"] if level == "section" else None,
                               day=str(r["day"]), f=dict(zero=_n(r["z"]), total=_n(r["t"])))) for r in rows]
        return out, dims, "BO 500-30-15 zero stock summary (month to date)"

    def f_oos(self, need):
        rows = A.oos_items(self.db, self.sc)
        out = [self._fill(dict(store=r["store"], dept=r.get("dept"), section=r.get("section"), family=r.get("family"), supplier=r.get("supplier"),
                               item=r["item"], reason=r.get("reason_group") or r.get("reason"), _d=r.get("description"), _sn=r.get("supplier_name"),
                               f=dict(n=1, noorder=0 if r["on_order"] else 1, promo=1 if (r.get("leaflet") or r.get("promo")) else 0,
                                      lost=_n(r.get("lost_per_day")), lost_td=_n(r.get("lost_to_date"))))) for r in rows]
        return out, WHERE | {"dept", "section", "family", "supplier", "item", "reason"}, "GIMA zero stock sheet (today)"

    def f_negative(self, need):
        rows = A.negative_items(self.db, self.sc)
        out = [self._fill(dict(store=r["store"], dept=r.get("dept"), section=r.get("section"), item=r["item"], cause=r.get("cause"),
                               _d=r.get("description"), f=dict(n=1, value=abs(_n(r.get("value"))), qty=_n(r.get("qty"))))) for r in rows]
        return out, WHERE | {"dept", "section", "item", "cause"}, "GIMA negative stock sheet"

    def f_dp(self, need):
        rows = A.dp_items(self.db, self.sc)
        out = [self._fill(dict(store=r["store"], dept=r.get("dept"), section=r.get("section"), supplier=r.get("supplier"), item=r["item"],
                               bucket=r.get("bucket"), _d=r.get("description"), _sn=r.get("supplier_name"),
                               f=dict(n=1, value=_n(r["value"]), prov=_n(r["provision"]),
                                      extra=_n(r["extra_provision"]) if r["days_to_next"] is not None and r["days_to_next"] <= 30 else 0)))
               for r in rows]
        return out, WHERE | {"dept", "section", "supplier", "item", "bucket"}, "DP master data"

    def f_lpo(self, need):
        rows, _ = A.lpo_rows(self.db, self.sc)
        out = [self._fill(dict(store=r["store"], dept=r.get("dept"), section=r.get("section"), supplier=r.get("supplier"),
                               order_type=r.get("order_type"), _sn=r.get("supplier_name"),
                               f=dict(n=1, value=_n(r["value"]), grn=_n(r.get("grn_value")), late=1 if r["late_days"] else 0,
                                      late_value=_n(r["value"]) if r["late_days"] else 0))) for r in rows]
        return out, WHERE | {"dept", "section", "supplier", "order_type"}, "LPO list"

    def f_leaflet(self, need):
        rows = A.leaflet_rows(self.db, self.sc)
        out = [self._fill(dict(store=r["store"], dept=r.get("dept"), section=r.get("section"), item=r["item"], theme=r.get("theme_name") or r.get("theme"),
                               _d=r.get("description"), f=dict(n=1, zero=1 if r["zero"] else 0))) for r in rows]
        return out, WHERE | {"dept", "section", "item", "theme"}, "Leaflet workbook"

    def f_sleeping(self, need):
        rows = X.sleeping(self.db, self.sc)[0]
        out = [self._fill(dict(store=r.get("store"), dept=r.get("dept"), section=r.get("section"), item=r.get("item"),
                               _d=r.get("description"), f=dict(n=1, value=_n(r.get("value"))))) for r in rows]
        return out, WHERE | {"dept", "section", "item"}, "RealTime + benchmark"


# ------------------------------------------------------------------------------------------------ the cube
def _sum(rows: list[dict]) -> dict:
    s: dict = defaultdict(float)
    for r in rows:
        for k, v in r["f"].items():
            s[k] += v
    return s


def _match(r: dict, filters: dict) -> bool:
    for d, vals in filters.items():
        if vals and str(r.get(d)) not in vals:
            return False
    return True


def cube(api, ctx: dict, dim: str = "store", dim2: str | None = None, measures: list | None = None, filters: dict | None = None,
         top: int = 0, sort: str | None = None, desc: bool = True) -> dict:
    from .api import Names
    MS = all_measures(api.db)
    measures = [m for m in (measures or ["sales"]) if m in MS] or ["sales"]
    dim = dim if dim in DIM_LABEL else "store"
    dim2 = dim2 if dim2 in DIM_LABEL and dim2 != dim else None
    if dim2:
        measures = measures[:1]
    filters = {k: [str(x) for x in v] for k, v in (filters or {}).items() if k in DIM_LABEL and v}
    sc = api.scope(ctx)
    facts = Facts(api, ctx, sc)
    need = {dim} | ({dim2} if dim2 else set()) | set(filters)
    names = Names(api.db)
    out_rows: dict = {}
    col_keys: dict = {}
    totals, col_tot, notes, sources = {}, defaultdict(dict), [], {}
    cells: dict = defaultdict(dict)
    labels: dict = {}

    def label(d, k, r):
        if (d, k) in labels:
            return labels[(d, k)]
        if k in (None, "", "None"):
            v = "(not set)"
        elif d == "format":
            v = FMT_NAMES.get(k, k)
        elif d in ("region", "day", "reason", "bucket", "cause", "theme", "order_type"):
            v = str(k)
        elif d == "item":
            v = f"{k} {r.get('_d') or names.item.get(k) or ''}".strip()
        elif d == "supplier":
            v = names.supplier.get(k) or r.get("_sn") or str(k)
        else:
            v = names.name(d, k, r)
        labels[(d, k)] = v
        return v

    by_fact = defaultdict(list)
    for m in measures:
        by_fact[MS[m][1]].append(m)
    shown_share = measures[0]
    grp_sums: dict = {}
    for fact, ms in by_fact.items():
        rows, dims, src = facts.load(fact, need)
        missing = need - dims
        if missing and rows:
            notes.append(f"{', '.join(MS[m][0] for m in ms)}: not available by {', '.join(DIM_LABEL[d].lower() for d in sorted(missing))} "
                         f"({src or 'no data'} has no such detail).")
            continue
        if not rows:
            notes.append(f"{', '.join(MS[m][0] for m in ms)}: no data loaded.")
            continue
        sources[fact] = src
        rows = [r for r in rows if _match(r, filters)]
        tot = _sum(rows)
        for m in ms:
            totals[m] = MS[m][3](tot)
        g = defaultdict(list)
        for r in rows:
            g[str(r.get(dim))].append(r)
        for k, rs in g.items():
            row = out_rows.setdefault(k, dict(k=None if k == "None" else k, name=label(dim, None if k == "None" else k, rs[0]), v={}))
            s = _sum(rs)
            grp_sums[(fact, k)] = rs
            for m in ms:
                row["v"][m] = MS[m][3](s)
            if dim2:
                g2 = defaultdict(list)
                for r in rs:
                    g2[str(r.get(dim2))].append(r)
                for k2, rs2 in g2.items():
                    col_keys.setdefault(k2, label(dim2, None if k2 == "None" else k2, rs2[0]))
                    cells[k][k2] = MS[ms[0]][3](_sum(rs2))
        if dim2:
            g2 = defaultdict(list)
            for r in rows:
                g2[str(r.get(dim2))].append(r)
            for k2, rs2 in g2.items():
                col_tot[k2] = MS[ms[0]][3](_sum(rs2))

    # a group with no out-of-stock / DP / late lines has zero of them, not "unknown"
    # (not for stores: a store missing from a sheet may simply not be in that report)
    zero_ok = [] if dim in ("store", "day") else [m for m in measures if MS[m][1] in sources and MS[m][1] != "sales" and MS[m][2] in ("int", "pkr")]
    for r in out_rows.values():
        for m in zero_ok:
            if r["v"].get(m) is None:
                r["v"][m] = 0.0
    first = measures[0]
    kind0 = MS[first][2]
    rows_out = list(out_rows.values())
    skey = sort if sort in measures else first
    rows_out.sort(key=lambda r: (r["v"].get(skey) is None, -(r["v"].get(skey) or 0) if desc else (r["v"].get(skey) or 0)))
    if dim == "day":
        rows_out.sort(key=lambda r: r["k"] or "")
    additive = kind0 in ("pkr", "int")
    tot0 = totals.get(first)
    for i, r in enumerate(rows_out, 1):
        r["rank"] = i
        v = r["v"].get(first)
        r["share"] = (v / tot0 * 100) if additive and tot0 and v is not None else None
    others = None
    rest = []
    if top and len(rows_out) > top and dim != "day":
        rest = rows_out[top:]
        rows_out = rows_out[:top]
    if dim == "item":            # names only for the rows shown that do not carry a description already
        ks = [r["k"] for r in rows_out if r["k"] and r["name"] == r["k"]]
        if ks:
            desc_of = {c: d for c, d in api.db.q(
                "SELECT item, description FROM items WHERE item IN (SELECT * FROM (VALUES " + ",".join("(?)" for _ in ks[:3000]) + "))",
                ks[:3000])} if len(ks) <= 400 else {c: d for c, d in api.db.q("SELECT item, description FROM items")}
            for r in rows_out:
                if desc_of.get(r["k"]) and r["name"] == r["k"]:
                    r["name"] = f"{r['k']} {desc_of[r['k']]}"
    if rest:
        ov = {}
        for m in measures:
            fact = MS[m][1]
            rs = [x for r in rest for x in grp_sums.get((fact, str(r["k"])), [])]
            ov[m] = MS[m][3](_sum(rs)) if rs else None
        others = dict(k="__others", name=f"Others ({len(rest)})", v=ov, rank=None,
                      share=(ov.get(first) / tot0 * 100) if additive and tot0 and ov.get(first) is not None else None)
        if dim2:
            fact = MS[first][1]
            rs = [x for r in rest for x in grp_sums.get((fact, str(r["k"])), [])]
            g2 = defaultdict(list)
            for x in rs:
                g2[str(x.get(dim2))].append(x)
            cells["__others"] = {k2: MS[first][3](_sum(v)) for k2, v in g2.items()}
    cols = []
    if dim2:
        order = sorted(col_keys, key=lambda k: (k if dim2 == "day" else -(col_tot.get(k) or 0)))
        cols = [dict(k=k, name=col_keys[k], total=col_tot.get(k)) for k in order]
        for r in rows_out + ([others] if others else []):
            r["cells"] = {k: cells.get(str(r["k"]), {}).get(k) for k in order}
    vals = [r["v"].get(first) for r in rows_out if r["v"].get(first) is not None]
    stats = dict(count=len(out_rows), min=min(vals) if vals else None, max=max(vals) if vals else None,
                 avg=sum(vals) / len(vals) if vals else None)
    return dict(dim=dim, dim_label=DIM_LABEL[dim], dim2=dim2, dim2_label=DIM_LABEL.get(dim2), measures=[
        dict(k=m, l=MS[m][0], kind=MS[m][2], help=MS[m][4]) for m in measures],
        rows=rows_out, others=others, totals=totals, cols=cols, stats=stats, notes=notes,
        sources=sorted(set(sources.values())), scope=sc.label(api.db), filters=filters, top=top, sort=skey, desc=desc)


def options(api, ctx: dict, dim: str, measure: str | None = None, q: str = "", limit: int = 400) -> dict:
    """Values a dimension can be filtered on (from the fact of the chosen measure, else the master data)."""
    db = api.db
    from .api import Names
    names = Names(db)
    if dim == "store":
        vals = [(s["code"], f"{s['code']} {s['name']}") for s in db.store_list()]
    elif dim == "format":
        vals = list(FMT_NAMES.items())
    elif dim == "region":
        vals = [(r[0], r[0]) for r in db.q("SELECT DISTINCT region FROM stores WHERE region IS NOT NULL ORDER BY 1")]
    elif dim == "dept":
        vals = [(c, n) for c, n in db.q("SELECT code, name FROM departments ORDER BY code")]
    elif dim == "section":
        vals = [(c, f"S{c} {n}") for c, n in db.q("SELECT code, name FROM sections ORDER BY code")]
    else:
        fact = all_measures(db).get(measure or "", (None, "oos"))[1]
        f = Facts(api, ctx, api.scope(ctx))
        rows, dims, _ = f.load(fact, {dim})
        if dim not in dims:
            for alt in ("oos", "dp", "lpo", "leaflet", "negative", "sales"):
                rows, dims, _ = f.load(alt, {dim})
                if dim in dims and rows:
                    break
        seen = {}
        for r in rows:
            k = r.get(dim)
            if k not in (None, "") and k not in seen:
                seen[k] = (f"{k} {r.get('_d') or ''}".strip() if dim == "item" else
                           (names.supplier.get(k) or r.get("_sn") or k) if dim == "supplier" else
                           names.name(dim, k, r) if dim == "family" else str(k))
        vals = sorted(seen.items(), key=lambda x: str(x[1]))
    ql = (q or "").lower()
    vals = [dict(k=str(k), n=str(n)) for k, n in vals if not ql or ql in f"{k} {n}".lower()]
    return dict(dim=dim, values=vals[:limit], more=len(vals) > limit)


def all_measures(db) -> dict:
    """Built-in measures plus one for every amount in the imported datasets."""
    from stockcompass.analytics import datasets as D
    try:
        extra, _ = D.measures_for_analyse(db)
    except Exception:
        extra = {}
    return {**MEASURES, **extra}


def meta(db=None) -> dict:
    groups = list(GROUPS)
    ms = MEASURES
    if db is not None:
        from stockcompass.analytics import datasets as D
        try:
            extra, g2 = D.measures_for_analyse(db)
            ms = {**MEASURES, **extra}
            groups += g2
        except Exception:
            pass
    return dict(dims=[dict(k=k, l=l, g=g) for k, l, g in DIMS],
                groups=[dict(n=n, m=[dict(k=m, l=ms[m][0], kind=ms[m][2], help=ms[m][4], fact=ms[m][1]) for m in mm])
                        for n, mm in groups],
                presets=PRESETS)
