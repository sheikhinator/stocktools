"""All numbers shown on screen come from here. Each function returns plain rows plus the explanation
of how the number was made (formula with the real values, source report, and date)."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from stockcompass.db import Database
from stockcompass.i18n import lang
from stockcompass.master.seed import BC_INDICATORS, OOS_REASON_GROUPS


def L(en: str, ur: str) -> str:
    """Pick the sentence for the current language."""
    return ur if lang() == "ur" else en

VAT = 1.18


@dataclass
class Scope:
    stores: list[str] | None = None      # None = all active stores
    formats: list[str] | None = None     # H / S / M
    dept: str | None = None
    section: str | None = None

    def store_sql(self, col: str = "store") -> tuple[str, list]:
        parts, params = [], []
        if self.stores:
            parts.append(f"{col} IN ({','.join('?' * len(self.stores))})")
            params += list(self.stores)
        if self.formats:
            parts.append(f"{col} IN (SELECT code FROM stores WHERE format IN ({','.join('?' * len(self.formats))}))")
            params += list(self.formats)
        return (" AND ".join(parts) or "TRUE"), params

    def item_sql(self, alias: str = "i") -> tuple[str, list]:
        parts, params = [], []
        if self.dept:
            parts.append(f"{alias}.dept = ?")
            params.append(self.dept)
        if self.section:
            parts.append(f"{alias}.section = ?")
            params.append(self.section)
        return (" AND ".join(parts) or "TRUE"), params

    def label(self, db: Database) -> str:
        bits = []
        if self.stores:
            names = [db.one("SELECT name FROM stores WHERE code=?", [s], s) for s in self.stores[:3]]
            bits.append(", ".join(names) + ("…" if len(self.stores) > 3 else ""))
        elif self.formats:
            bits.append("/".join({"H": "Hypermarkets", "S": "Supermarkets", "M": "Mylis"}[f] for f in self.formats))
        else:
            bits.append("All stores")
        if self.section:
            bits.append(db.one("SELECT name FROM sections WHERE code=?", [self.section], self.section))
        elif self.dept:
            bits.append(db.one("SELECT name FROM departments WHERE code=?", [self.dept], self.dept))
        return " · ".join(bits)


@dataclass
class Explain:
    title: str
    definition: str
    formula: str = ""
    source: str = ""
    as_of: str = ""


@dataclass
class Kpi:
    key: str
    label: str
    value: float | None
    fmt: str                          # pct | pkr | int | days
    sub: str = ""
    status: str = ""                  # good | warn | bad | ""
    target: float | None = None
    explain: Explain | None = None
    goto: str = ""                    # page/tab to open on click
    spark: list[float] = field(default_factory=list)
    chip: str = ""                    # status label; defaults to on target / watch / off target


# ------------------------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------------------------

def latest_imports(db: Database, report_type: str, scope: Scope | None = None) -> list[tuple[int, date, str]]:
    """Latest import per store for a report type: [(import_id, snapshot_date, stores)]."""
    rows = db.q("SELECT import_id, snapshot_date, coalesce(stores,'') FROM imports WHERE report_type=? AND status='ok' "
                "ORDER BY snapshot_date DESC NULLS LAST, import_id DESC", [report_type])
    covered: set[str] = set()
    out = []
    for iid, d, st in rows:
        sts = set(filter(None, st.split(",")))
        if not sts or not sts.issubset(covered):
            out.append((iid, d, st))
            covered |= sts
    return out


def ids_sql(ids: list[int]) -> str:
    return "(" + ",".join(str(int(i)) for i in ids) + ")" if ids else "(NULL)"


def reason_group(reason: str) -> str:
    r = (reason or "").upper()
    for g, keys in OOS_REASON_GROUPS:
        if any(k in r for k in keys):
            return g
    return "other" if r else "none"


REASON_ACTION = {
    "supplier": ("Supplier did not deliver", "Chase the supplier / buyer", "سپلائر نے ڈیلیور نہیں کیا"),
    "schedule": ("No ordering schedule set", "Set the ordering schedule in GIMA", "آرڈرنگ شیڈول سیٹ نہیں"),
    "reorder": ("Only one order done", "Place a new order now", "صرف ایک آرڈر ہوا"),
    "not_ordered": ("Nobody ordered for a month+", "Order now or delist", "ایک ماہ سے آرڈر نہیں ہوا"),
    "new_item": ("New item, waiting for first delivery", "Follow up the first delivery", "نیا آئٹم"),
    "other": ("Other reason", "Check the item", "دیگر وجہ"),
    "none": ("No reason given", "Check the item", "کوئی وجہ نہیں"),
}


def prices(db: Database) -> dict[tuple[str, str], tuple[float | None, float | None]]:
    """(store, item) -> (price without tax, cost) from the latest RealTime per store."""
    ids = [i for i, _, _ in latest_imports(db, "gima_realtime")]
    out = {}
    if ids:
        for st, it, p, c in db.q(f"SELECT store, item, price, cost FROM stock_item WHERE import_id IN {ids_sql(ids)}"):
            out[(st, it)] = ((p / VAT) if p else None, c)
    return out


def item_price_any(db: Database) -> dict[str, float]:
    """item -> typical price without tax (any store), from RealTime, then sales, then leaflet, then DP."""
    out: dict[str, float] = {}
    for it, p in db.q("SELECT item, sales/qty FROM (SELECT item, sum(sales) sales, sum(qty) qty FROM sales_item "
                      "GROUP BY item) WHERE qty > 0"):
        out[it] = p
    for it, p in db.q("SELECT item, median(sp)/1.18 FROM leaflet_item WHERE sp > 0 GROUP BY item"):
        out.setdefault(it, p)
    for it, p in db.q("SELECT item, median(price)/1.18 FROM dp_item WHERE price > 0 GROUP BY item"):
        out.setdefault(it, p)
    for it, p in db.q("SELECT item, median(price)/1.18 FROM stock_item WHERE price > 0 GROUP BY item"):
        out[it] = p
    return out


def fmt_pkr(v: float | None) -> str:
    if v is None:
        return "–"
    a = abs(v)
    if a >= 1e9:
        s = f"{v / 1e9:.2f}B"
    elif a >= 1e6:
        s = f"{v / 1e6:.1f}M"
    elif a >= 1e3:
        s = f"{v / 1e3:.0f}K"
    else:
        s = f"{v:.0f}"
    return "PKR " + s


# ------------------------------------------------------------------------------------------------
# Zero stock (BC definition: closing stock <= 0, negative included)
# ------------------------------------------------------------------------------------------------

def zero_stock_daily(db: Database, scope: Scope) -> list[dict]:
    """Per store per day: total items and zero items. Uses the store-level rows, or sums the department
    rows when only those were imported. Suspect days (failed stock loads) are marked."""
    ids = [i for i, _, _ in latest_imports(db, "bo_zero_summary")]
    if not ids:
        return []
    w, p = scope.store_sql()
    lvl_filter = "TRUE"
    lp = []
    if scope.section:
        lvl_filter, lp = "level='section' AND section=?", [scope.section]
    elif scope.dept:
        lvl_filter, lp = "level='dept' AND dept=?", [scope.dept]
    rows = db.qd(f"""
        WITH x AS (SELECT * FROM zs_daily WHERE import_id IN {ids_sql(ids)} AND {w} AND {lvl_filter}),
        lv AS (SELECT CASE WHEN count(*) FILTER (WHERE level='store')>0 AND ? THEN 'store'
                           WHEN count(*) FILTER (WHERE level='dept')>0 THEN 'dept' ELSE 'section' END AS use FROM x)
        SELECT store, day, sum(total_items) total, sum(zero_items) zero, bool_or(coalesce(suspect,false)) suspect
        FROM x, lv WHERE level = lv.use GROUP BY store, day ORDER BY day, store""",
                 p + lp + [not (scope.dept or scope.section)])
    return rows


def zero_stock_summary(db: Database, scope: Scope) -> dict:
    rows = zero_stock_daily(db, scope)
    if not rows:
        return {}
    good = [r for r in rows if not r["suspect"] and r["total"]]
    days = sorted({r["day"] for r in good})
    last = days[-1]
    month_start = last.replace(day=1)
    by_day = defaultdict(lambda: [0.0, 0.0])
    for r in good:
        by_day[r["day"]][0] += r["zero"] or 0
        by_day[r["day"]][1] += r["total"] or 0
    trend = [(d, by_day[d][0] / by_day[d][1] * 100 if by_day[d][1] else None) for d in days]
    mtd = [r for r in good if r["day"] >= month_start]
    mz, mt = sum(r["zero"] for r in mtd), sum(r["total"] for r in mtd)
    lz, lt = by_day[last]
    per_store = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for r in mtd:
        per_store[r["store"]][0] += r["zero"]
        per_store[r["store"]][1] += r["total"]
        if r["day"] == last:
            per_store[r["store"]][2] += r["zero"]
            per_store[r["store"]][3] += r["total"]
    stores = []
    for st, (z, t, dz, dt) in per_store.items():
        stores.append(dict(store=st, mtd_pct=z / t * 100 if t else None, day_pct=dz / dt * 100 if dt else None,
                           zero_today=dz, items_today=dt, zero_item_days=z, item_days=t))
    stores.sort(key=lambda x: -(x["mtd_pct"] or 0))
    return dict(last_day=last, month_start=month_start, day_pct=lz / lt * 100 if lt else None, mtd_pct=mz / mt * 100 if mt else None,
                mtd_zero=mz, mtd_total=mt, day_zero=lz, day_total=lt, trend=trend, stores=stores,
                suspect_days=sum(1 for r in rows if r["suspect"]))


# ------------------------------------------------------------------------------------------------
# Out-of-stock item list (GIMA zero stock sheet)
# ------------------------------------------------------------------------------------------------

def oos_items(db: Database, scope: Scope) -> list[dict]:
    ids = [i for i, _, _ in latest_imports(db, "gima_zero_stock")]
    if not ids:
        return []
    w, p = scope.store_sql("z.store")
    wi, pi = scope.item_sql()
    rows = db.qd(f"""
        SELECT z.*, i.description, i.dept, i.section, i.family, s.name AS store_name, sup.name AS supplier_name,
               sec.name AS section_name
        FROM zero_item z LEFT JOIN items i USING (item) LEFT JOIN stores s ON s.code = z.store
        LEFT JOIN suppliers sup ON sup.code = z.supplier LEFT JOIN sections sec ON sec.code = i.section
        WHERE z.import_id IN {ids_sql(ids)} AND {w} AND {wi}""", p + pi)
    pr = prices(db)
    anyp = item_price_any(db)
    leaflet = {(s, i) for s, i in db.q("SELECT DISTINCT store, item FROM leaflet_item")}
    for r in rows:
        price = (pr.get((r["store"], r["item"])) or (None, None))[0] or anyp.get(r["item"])
        r["price_ex_tax"] = price
        r["lost_per_day"] = (r["dlyavg"] or 0) * (price or 0)
        days = min(r["days_out"] or 0, 365)
        r["lost_to_date"] = r["lost_per_day"] * days
        g = reason_group(r["reason"])
        r["reason_group"] = g
        r["action"] = REASON_ACTION[g][1] if r["open_lpo"] else (
            "Order now: nothing on order" if g not in ("supplier",) else "Chase supplier and re-order")
        r["on_order"] = bool(r["open_lpo"])
        r["late"] = bool(r["on_order"] and r["delivery_date"] and r["snap_date"] and r["delivery_date"] < r["snap_date"])
        r["leaflet"] = (r["store"], r["item"]) in leaflet or (r["promo"] or "").upper() in ("Y", "YES")
        r["priority"] = (0 if not r["on_order"] else 2) - (1 if r["leaflet"] else 0) - (r["lost_per_day"] > 0) * 0.5
    rows.sort(key=lambda r: (r["priority"], -(r["lost_per_day"] or 0)))
    return rows


# ------------------------------------------------------------------------------------------------
# Negative stock (with cause by status)
# ------------------------------------------------------------------------------------------------
NEG_CAUSE = {
    "NI": ("Item is set up as 'not part of inventory' but sells at the till", "Ask the item setup team to make it an "
           "inventory item, then correct the stock", "آئٹم انوینٹری میں شامل نہیں"),
    "NC": ("Blocked item still scanning at the till", "Count it; check it is not sold under the wrong code; "
           "then correct or write off", "بلاک آئٹم اب بھی بک رہا ہے"),
    "AC": ("Receiving or counting error on an active item", "Recount and check recent deliveries (GRN)",
           "وصولی یا گنتی کی غلطی"),
    "AG": ("Aged item with negative stock", "Recount and correct", "ایجڈ آئٹم"),
}


def negative_items(db: Database, scope: Scope) -> list[dict]:
    w, p = scope.store_sql("n.store")
    wi, pi = scope.item_sql()
    ids = [i for i, _, _ in latest_imports(db, "gima_negative_stock")]
    rows = []
    if ids:
        rows = db.qd(f"""SELECT n.store, n.item, n.qty, n.status, n.snap_date, i.description, i.dept, i.section,
                           s.name store_name FROM negative_item n LEFT JOIN items i USING (item)
                           LEFT JOIN stores s ON s.code=n.store WHERE n.import_id IN {ids_sql(ids)} AND {w} AND {wi}""", p + pi)
    have = {(r["store"]) for r in rows}
    rt = [i for i, _, _ in latest_imports(db, "gima_realtime")]
    if rt:
        extra = db.qd(f"""SELECT n.store, n.item, n.qty, n.status, n.snap_date, i.description, i.dept, i.section,
                           s.name store_name FROM stock_item n LEFT JOIN items i USING (item)
                           LEFT JOIN stores s ON s.code=n.store
                           WHERE n.import_id IN {ids_sql(rt)} AND n.qty < 0 AND {w} AND {wi}""", p + pi)
        rows += [r for r in extra if r["store"] not in have]
    pr = prices(db)
    for r in rows:
        cost = (pr.get((r["store"], r["item"])) or (None, None))[1]
        r["value"] = (r["qty"] or 0) * (cost or 0)
        cause = NEG_CAUSE.get((r["status"] or "").upper(), ("Unknown status", "Recount and correct", ""))
        r["cause"], r["action"] = cause[0], cause[1]
    rows.sort(key=lambda r: r["qty"] or 0)
    return rows


# ------------------------------------------------------------------------------------------------
# DP / aged stock
# ------------------------------------------------------------------------------------------------

def dp_rule_table(db: Database) -> dict[str, list[tuple[int, float]]]:
    t = defaultdict(list)
    for k, fd, pct in db.q("SELECT rule_key, from_day, pct FROM dp_rules ORDER BY rule_key, from_day"):
        t[k].append((fd, pct))
    return t


def next_step(rules, dept: str, sec: str, age: int | None) -> tuple[int | None, float | None]:
    """Days until the provision % steps up, and the new %."""
    steps = rules.get(f"{dept}:{sec}") or rules.get(dept) or []
    if age is None:
        return None, None
    for fd, pct in steps:
        if fd > age:
            return fd - age, pct
    return None, None


def season_hold(season: str, today: date) -> bool:
    if not season:
        return False
    m = today.month
    if season[0] == "W":
        return m in (8, 9, 10, 11)      # winter stock: hold it for the coming season
    if season[0] == "S":
        return m in (2, 3, 4, 5)
    return False


def dp_items(db: Database, scope: Scope, today: date | None = None) -> list[dict]:
    ids = [i for i, _, _ in latest_imports(db, "dp_master")]
    if not ids:
        return []
    today = today or date.today()
    w, p = scope.store_sql("d.store")
    wi, pi = scope.item_sql()
    rows = db.qd(f"""SELECT d.*, i.description, i.dept, i.section, i.supplier, i.season, s.name store_name,
                        sec.name section_name, sup.name supplier_name
                     FROM dp_item d LEFT JOIN items i USING (item) LEFT JOIN stores s ON s.code=d.store
                     LEFT JOIN sections sec ON sec.code=i.section LEFT JOIN suppliers sup ON sup.code=i.supplier
                     WHERE d.import_id IN {ids_sql(ids)} AND {w} AND {wi}""", p + pi)
    rules = dp_rule_table(db)
    # where does each item sell? (qty per day by store from sales imports)
    sells = defaultdict(dict)
    for st, it, q, days in db.q("""SELECT store, item, sum(qty), sum(datediff('day', date_from, date_to) + 1)
                                    FROM sales_item GROUP BY store, item HAVING sum(qty) > 0"""):
        sells[it][st] = q / max(days or 1, 1)
    sup_count = Counter(r["supplier"] for r in rows if r["supplier"])
    for r in rows:
        d_next, p_next = next_step(rules, r["dept"] or "", r["section"] or "", r["age_days"])
        r["days_to_next"] = d_next
        r["next_pct"] = p_next
        r["extra_provision"] = (r["value"] or 0) * ((p_next or 0) - (r["prov_pct"] or 0)) / 100 if p_next else 0
        price_ex = (r["price"] or 0) / VAT
        others = {st: v for st, v in sells.get(r["item"], {}).items() if st != r["store"]}
        if season_hold(r["season"] or "", today):
            route, why = "Hold for season", f"{r['season']} item: sell at full price in season"
        elif others:
            best = max(others, key=others.get)
            route, why = "Move to another store (IST)", f"Sells {others[best]:.1f}/day at {best}"
        elif price_ex and r["cost"] and price_ex < r["cost"] * 0.6 and (r["rot"] or 999) >= 999:
            route, why = ("Return to supplier (RTS)" if sup_count[r["supplier"]] >= 3 else "Write off",
                          "Already priced far below cost and still not selling")
        elif price_ex and r["cost"] and price_ex > r["cost"]:
            route, why = "Markdown", "Margin allows a price cut"
        elif sup_count[r["supplier"]] >= 3:
            route, why = "Return to supplier (RTS)", f"{sup_count[r['supplier']]} DP items from this supplier: one conversation"
        else:
            route, why = "Write off", "No store sells it and no margin left"
        r["route"], r["route_why"] = route, why
    rows.sort(key=lambda r: -(r["value"] or 0))
    return rows


# ------------------------------------------------------------------------------------------------
# Orders
# ------------------------------------------------------------------------------------------------

def lpo_rows(db: Database, scope: Scope) -> tuple[list[dict], date | None]:
    ids = [i for i, _, _ in latest_imports(db, "lpo_list")]
    if not ids:
        return [], None
    snap = db.one(f"SELECT max(snapshot_date) FROM imports WHERE import_id IN {ids_sql(ids)}")
    w, p = scope.store_sql("l.store")
    rows = db.qd(f"""SELECT l.*, s.name store_name, sup.name supplier_name FROM lpo l LEFT JOIN stores s ON s.code=l.store
                     LEFT JOIN suppliers sup ON sup.code=l.supplier WHERE l.import_id IN {ids_sql(ids)} AND {w}""", p)
    for r in rows:
        r["late_days"] = (snap - r["delivery_date"]).days if (snap and r["delivery_date"] and r["status"] == "EM"
                                                             and not r["deleted"] and r["delivery_date"] < snap) else 0
        r["received_pct"] = (r["grn_value"] / r["value"] * 100) if r["value"] and r["grn_value"] is not None else None
    return rows, snap


def purge_by_store(rows: list[dict]) -> list[dict]:
    agg = defaultdict(lambda: dict(n=0, purged=0, value=0.0, grn=0.0, late=0))
    for r in rows:
        a = agg[r["store"]]
        a["n"] += 1
        a["purged"] += 1 if r["deleted"] else 0
        if not r["deleted"]:
            a["value"] += r["value"] or 0
            a["grn"] += r["grn_value"] or 0
        a["late"] += 1 if r["late_days"] else 0
    out = []
    for st, a in agg.items():
        out.append(dict(store=st, lpos=a["n"], purged=a["purged"], purge_pct=a["purged"] / a["n"] * 100 if a["n"] else None,
                        received_value_pct=a["grn"] / a["value"] * 100 if a["value"] else None, late=a["late"]))
    return sorted(out, key=lambda x: -(x["purge_pct"] or 0))


# ------------------------------------------------------------------------------------------------
# Leaflet
# ------------------------------------------------------------------------------------------------

def leaflet_rows(db: Database, scope: Scope) -> list[dict]:
    w, p = scope.store_sql("l.store")
    wi, pi = scope.item_sql()
    rows = db.qd(f"""SELECT l.*, i.description, i.dept, i.section, s.name store_name FROM leaflet_item l
                     LEFT JOIN items i USING (item) LEFT JOIN stores s ON s.code=l.store
                     WHERE l.import_id IN (SELECT max(import_id) FROM imports WHERE report_type='leaflet_theme'
                                           GROUP BY stores) AND {w} AND {wi}""", p + pi)
    for r in rows:
        r["zero"] = (r["stock_qty"] or 0) <= 0
        r["on_order"] = (r["on_order_qty"] or 0) > 0
        r["below_cost"] = bool(r["pp"] and r["sp"] and r["sp"] < r["pp"])
    rows.sort(key=lambda r: (not r["zero"], r["on_order"], r["store"]))
    return rows


# ------------------------------------------------------------------------------------------------
# BC scorecard
# ------------------------------------------------------------------------------------------------
IND = {i["key"]: i for i in BC_INDICATORS}


def scorecard(db: Database) -> dict:
    iid = db.one("SELECT import_id FROM imports WHERE report_type='bc_scorecard' AND status='ok' "
                 "ORDER BY snapshot_date DESC, import_id DESC LIMIT 1")
    if not iid:
        return {}
    meta = db.qd("SELECT snapshot_date, file_name FROM imports WHERE import_id=?", [iid])[0]
    vals = db.qd("SELECT b.*, s.format, s.name store_name FROM bc_value b JOIN stores s ON s.code=b.store "
                 "WHERE import_id=?", [iid])
    targets = {(k, f): (t, lo) for k, f, t, lo in db.q("SELECT indicator, format, target, lower_better FROM bc_targets")}
    zs = zero_stock_summary(db, Scope())
    ours = {s["store"]: s["mtd_pct"] for s in zs.get("stores", [])} if zs else {}
    cells = []
    official = {v["store"]: v["value"] for v in vals if v["indicator"] == "_greens"}
    for v in vals:
        k = v["indicator"]
        if k.startswith("_"):
            continue
        t, lo = targets.get((k, v["format"]), (None, IND.get(k, {}).get("lo", True)))
        st = ""
        if v["value"] is not None and t is not None:
            st = "good" if ((v["value"] <= t) if lo else (v["value"] >= t)) else "bad"
        ourv = ours.get(v["store"]) if k == "zero_stock" else None
        cells.append(dict(store=v["store"], store_name=v["store_name"], format=v["format"], indicator=k,
                          label=IND.get(k, {}).get("label", v["label"]), value=v["value"], raw=v["raw"], target=t,
                          lower_better=lo, status=st, ours=ourv, period=v["period"]))
    greens = Counter(c["store"] for c in cells if c["status"] == "good")
    measured = Counter(c["store"] for c in cells if c["status"])
    order = [i["key"] for i in BC_INDICATORS]
    diff = {st: (official[st], greens.get(st, 0)) for st in official if official[st] != greens.get(st, 0)}
    return dict(import_id=iid, as_of=meta["snapshot_date"], file=meta["file_name"], cells=cells, greens=greens,
                measured=measured, order=order, official=official, greens_diff=diff)


# ------------------------------------------------------------------------------------------------
# Overview: KPIs and generated insights
# ------------------------------------------------------------------------------------------------

def overview(db: Database, scope: Scope) -> tuple[list[Kpi], list[dict]]:
    kpis: list[Kpi] = []
    insights: list[dict] = []
    target_zs = db.one("SELECT min(target) FROM bc_targets WHERE indicator='zero_stock'", default=12.0)
    zs = zero_stock_summary(db, scope)
    if zs:
        st = "good" if zs["mtd_pct"] <= target_zs else ("warn" if zs["mtd_pct"] <= target_zs * 1.25 else "bad")
        kpis.append(Kpi("zero_stock", "Zero stock % (month to date)", zs["mtd_pct"], "pct",
                        sub=L(f"Today {zs['day_pct']:.1f}% · target ≤{target_zs:g}%", f"آج {zs['day_pct']:.1f}% · ہدف ≤{target_zs:g}%"), status=st, target=target_zs,
                        goto="stock:zero", spark=[v for _, v in zs["trend"] if v is not None],
                        explain=Explain("Zero stock %", "Share of ranged items with closing stock of zero or below "
                                        "(negative included), added up over every day of the month.",
                                        f"{zs['mtd_zero']:,.0f} zero item-days ÷ {zs['mtd_total']:,.0f} item-days = "
                                        f"{zs['mtd_pct']:.2f}%", "BO 500-30-15 zero stock summary",
                                        f"{zs['month_start']:%d %b} – {zs['last_day']:%d %b %Y}"
                                        + (f" · {zs['suspect_days']} broken day(s) left out" if zs['suspect_days'] else ""))))
    oos = oos_items(db, scope)
    if oos:
        not_ord = [r for r in oos if not r["on_order"]]
        lost_day = sum(r["lost_per_day"] for r in oos)
        snap = max((r["snap_date"] for r in oos if r["snap_date"]), default=None)
        kpis.append(Kpi("not_on_order", "Out of stock, not on order", len(not_ord), "int",
                        sub=L(f"of {len(oos):,} out-of-stock items", f"کل {len(oos):,} آؤٹ آف اسٹاک آئٹمز میں سے"), status="bad" if not_ord else "good",
                        chip=L("✕ order these first", "✕ پہلے انہیں آرڈر کریں") if not_ord else "",
                        goto="stock:oos",
                        explain=Explain("Out of stock, not on order", "Items at zero stock with no open purchase order. "
                                        "Nothing is on the way, so these are the most urgent.",
                                        f"{len(oos):,} zero-stock items − {len(oos) - len(not_ord):,} with an open LPO = {len(not_ord):,}",
                                        "GIMA zero stock sheet", f"as of {snap:%d %b %Y}" if snap else "")))
        priced = sum(1 for r in oos if r["price_ex_tax"])
        kpis.append(Kpi("lost_sales", "Sales lost per day", lost_day if priced else None, "pkr",
                        sub=(L(f"{fmt_pkr(sum(r['lost_to_date'] for r in oos))} since they went out",
                               f"جب سے آؤٹ ہوئے {fmt_pkr(sum(r['lost_to_date'] for r in oos))}") if priced else
                             L("Add a GIMA RealTime or Benchmark file to put a price on this",
                               "قیمت کے لیے جیما ریئل ٹائم یا بینچ مارک فائل شامل کریں")),
                        status="bad" if lost_day else "",
                        goto="stock:oos",
                        explain=Explain("Lost sales", "What out-of-stock items would normally sell: average daily sales "
                                        "(DLYAVG) × price without tax. 'Since they went out' multiplies by the days since "
                                        "the last sale (capped at a year).",
                                        f"Σ DLYAVG × price ÷ 1.18 = {fmt_pkr(lost_day)} per day",
                                        "GIMA zero stock sheet + RealTime prices", f"as of {snap:%d %b %Y}" if snap else "")))
        by_group = Counter(r["reason_group"] for r in oos)
        top = by_group.most_common(1)[0]
        insights.append(dict(level="bad" if not_ord else "info", goto="stock:oos",
                             title=L(f"{len(not_ord):,} out-of-stock items have nothing on order",
                                     f"{len(not_ord):,} آؤٹ آف اسٹاک آئٹمز کا کوئی آرڈر نہیں"),
                             text=L(f"They lose about {fmt_pkr(sum(r['lost_per_day'] for r in not_ord))} a day. Biggest "
                                    f"cause: {REASON_ACTION[top[0]][0].lower()} ({top[1]:,} items).",
                                    f"روزانہ تقریباً {fmt_pkr(sum(r['lost_per_day'] for r in not_ord))} کا نقصان۔ سب سے بڑی وجہ: "
                                    f"{REASON_ACTION[top[0]][2]} ({top[1]:,} آئٹمز)۔")))
        lf = [r for r in not_ord if r["leaflet"]]
        if lf:
            insights.append(dict(level="bad", goto="stock:oos", title=L(f"{len(lf)} leaflet / promo items are out of stock and not on order",
                                         f"{len(lf)} لیفلیٹ / پروموشن آئٹمز آؤٹ آف اسٹاک ہیں اور آرڈر نہیں"),
                                 text=L("Every day they stay out loses promotion sales. Order these first.",
                                        "ہر دن پروموشن سیلز ضائع ہوتی ہیں۔ پہلے انہیں آرڈر کریں۔")))
    neg = negative_items(db, scope)
    if neg:
        c = Counter((r["status"] or "?") for r in neg)
        kpis.append(Kpi("negative", "Negative stock items", len(neg), "int",
                        sub=", ".join(f"{k} {v}" for k, v in c.most_common(3)), status="warn", goto="stock:neg",
                        explain=Explain("Negative stock", "Items where the system shows less than zero in stock. Each "
                                        "status points to a different fix: NI = item setup, NC = blocked item still "
                                        "selling, AC = receiving or counting error.", f"{len(neg):,} items with stock < 0",
                                        "GIMA negative stock sheet (or RealTime)", "")))
        if c.get("NI"):
            insights.append(dict(level="warn", goto="stock:neg", title=L(f"{c['NI']} items sell at the till but are not inventory items (NI)",
                                         f"{c['NI']} آئٹمز کاؤنٹر پر بکتے ہیں مگر انوینٹری میں شامل نہیں (NI)"),
                                 text=L("Their stock goes negative. This is an item setup job for head office, not the store.",
                                        "ان کا اسٹاک منفی ہو جاتا ہے۔ یہ ہیڈ آفس میں آئٹم سیٹ اپ کا کام ہے، اسٹور کا نہیں۔")))
    dp = dp_items(db, scope)
    if dp:
        tv = sum(r["value"] or 0 for r in dp)
        tp = sum(r["provision"] or 0 for r in dp)
        soon = [r for r in dp if r["days_to_next"] is not None and r["days_to_next"] <= 30]
        extra = sum(r["extra_provision"] for r in soon)
        kpis.append(Kpi("dp_stock", "Aged (DP) stock", tv, "pkr", sub=L(f"DP provision {fmt_pkr(tp)}", f"DP پروویژن {fmt_pkr(tp)}"), status="warn",
                        goto="stock:dp",
                        explain=Explain("Aged (DP) stock", "Stock older than its department's ageing threshold "
                                        "(FMCG 1 year, LHH 6 months, HHH and Textile 3 months), at cost. DP provision "
                                        "is the amount finance sets aside because it may sell below cost.",
                                        f"Σ qty × cost = {fmt_pkr(tv)}; Σ provision = {fmt_pkr(tp)} ({tp / tv * 100 if tv else 0:.0f}%)",
                                        "DP master data", "")))
        if soon:
            insights.append(dict(level="warn", goto="stock:dp",
                                 title=L(f"{len(soon)} DP items move to a higher provision step within 30 days",
                                         f"{len(soon)} DP آئٹمز 30 دن میں اگلے پروویژن مرحلے میں جائیں گے"),
                                 text=L(f"Clearing them now avoids about {fmt_pkr(extra)} of extra provision.",
                                        f"ابھی نکالنے سے تقریباً {fmt_pkr(extra)} اضافی پروویژن بچ جائے گی۔")))
        hold = [r for r in dp if r["route"] == "Hold for season"]
        if hold:
            insights.append(dict(level="info", goto="stock:dp", title=L(f"{len(hold)} seasonal DP items: hold, don't mark down",
                                         f"{len(hold)} سیزنل DP آئٹمز: قیمت کم نہ کریں، سیزن کا انتظار کریں"),
                                 text=L(f"{fmt_pkr(sum(r['value'] or 0 for r in hold))} of winter stock can sell at full price in season.",
                                        f"{fmt_pkr(sum(r['value'] or 0 for r in hold))} کا سردیوں کا اسٹاک سیزن میں پوری قیمت پر بک سکتا ہے۔")))
    lpo, snap = lpo_rows(db, scope)
    if lpo:
        late = [r for r in lpo if r["late_days"]]
        kpis.append(Kpi("late_lpo", "Late orders", len(late), "int",
                        sub=L(f"{fmt_pkr(sum(r['value'] or 0 for r in late))} not delivered", f"{fmt_pkr(sum(r['value'] or 0 for r in late))} موصول نہیں"), status="warn" if late else "good",
                        goto="orders:late",
                        explain=Explain("Late orders", "Purchase orders still 'EM' (not received) after their delivery date.",
                                        f"{len(late)} of {len(lpo)} orders", "LPO list",
                                        f"as of {snap:%d %b %Y}" if snap else "")))
    sc = scorecard(db)
    if sc:
        g = sum(sc["official"].values()) if sc["official"] else sum(sc["greens"].values())
        m = sum(sc["measured"].values())
        kpis.append(Kpi("bc_greens", "BC targets met", g, "int", sub=L(f"of {m} measured · as of {sc['as_of']:%d %b}", f"کل {m} میں سے · {sc['as_of']:%d-%m}"),
                        status="good" if m and g / m >= 0.6 else "warn", goto="score",
                        explain=Explain("BC targets met", "Number of store × indicator cells that meet the BC team's target.",
                                        f"{g} green of {m} cells with a target", "BC workbook scorecard",
                                        f"as of {sc['as_of']:%d %b %Y}")))
    # data-quality findings from the latest imports become insights too
    for lvl, code, msg in db.q("""SELECT f.level, f.code, f.message FROM findings f JOIN imports i USING (import_id)
                                  WHERE f.code IN ('zero_jump','range_cut','bad_snapshot','copied_value','below_cost',
                                  'duplicate_orders') ORDER BY i.imported_at DESC LIMIT 6"""):
        insights.append(dict(level="warn", goto="health", title={
            "zero_jump": "Sudden jump in zero stock", "range_cut": "Zero stock improved by delisting",
            "bad_snapshot": "Broken stock loads found", "copied_value": "Possible error in the BC workbook",
            "below_cost": "Leaflet items priced below cost", "duplicate_orders": "Possible duplicate orders"}[code],
            text=msg))
    return kpis, insights


def data_status(db: Database) -> list[dict]:
    return db.qd("""SELECT report_type, max(snapshot_date) latest, count(*) imports, sum("rows") n_rows,
                           string_agg(DISTINCT stores, ',') stores
                    FROM imports WHERE status='ok' GROUP BY report_type ORDER BY latest DESC""")


def item_360(db: Database, item: str) -> dict:
    it = db.qd("SELECT i.*, s.name supplier_name, sec.name section_name FROM items i LEFT JOIN suppliers s "
               "ON s.code=i.supplier LEFT JOIN sections sec ON sec.code=i.section WHERE item=?", [item])
    rt = [i for i, _, _ in latest_imports(db, "gima_realtime")]
    stock = db.qd(f"SELECT store, qty, cost, price, status, snap_date FROM stock_item WHERE item=? AND import_id IN "
                  f"{ids_sql(rt)} ORDER BY store", [item]) if rt else []
    zero = db.qd("SELECT store, snap_date, days_out, dlyavg, reason, open_lpo, delivery_date FROM zero_item "
                 "WHERE item=? ORDER BY snap_date DESC", [item])
    sales = db.qd("SELECT store, date_from, date_to, sales, qty, margin, stock FROM sales_item WHERE item=? "
                  "ORDER BY date_to DESC, store", [item])
    dp = db.qd("SELECT store, snap_date, qty, value, age_days, provision, prov_pct, bucket FROM dp_item WHERE item=? "
               "ORDER BY snap_date DESC, store", [item])
    neg = db.qd("SELECT store, snap_date, qty, status FROM negative_item WHERE item=? ORDER BY snap_date DESC", [item])
    leaf = db.qd("SELECT store, theme, theme_name, stock_qty, status, on_order_qty, pp, sp FROM leaflet_item WHERE item=?", [item])
    return dict(item=it[0] if it else {"item": item}, stock=stock, zero=zero, sales=sales, dp=dp, negative=neg, leaflet=leaf)
