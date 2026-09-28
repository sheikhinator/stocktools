"""The data service behind the Stock Compass screens.

The screens (web/index.html, the same interface as the v2 demo) ask for data with a method name and a small
context (role, where, department, section, period, compare, language). Everything returned is plain JSON:
KPI cards with their explanation and hover breakdown, chart series, tables, and a generic drill-down that
goes store -> department -> section -> family -> supplier -> item for every number on screen.

No Qt in here, so it can be tested and served to a browser for development.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
import traceback
from collections import OrderedDict, defaultdict
from datetime import date, datetime
from typing import Any, Callable

from stockcompass import __version__
from stockcompass.analytics import core as A
from stockcompass.analytics import extra as X
from stockcompass.analytics import jobs as J
from stockcompass.analytics import sales as SA
from stockcompass.analytics.core import L, Scope, fmt_pkr
from stockcompass.db import Database
from stockcompass.i18n import set_lang
from stockcompass.importer.spec import REGISTRY
from stockcompass.master.seed import BC_INDICATORS

from .export import write_jobs, write_table
from .imports import ImportJobs

LEVELS = ["store", "dept", "section", "family", "supplier", "item"]
LEVEL_NAMES = {"store": ("Store", "اسٹور"), "dept": ("Department", "ڈیپارٹمنٹ"), "section": ("Section", "سیکشن"),
               "family": ("Family", "فیملی"), "supplier": ("Supplier", "سپلائر"), "item": ("Item", "آئٹم"),
               "lpo": ("Order", "آرڈر"), "format": ("Format", "فارمیٹ")}


def jsonable(o: Any):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, set):
        return sorted(o)
    if hasattr(o, "__dict__"):
        return {k: v for k, v in o.__dict__.items() if not k.startswith("_")}
    return str(o)


def dumps(o: Any) -> str:
    return json.dumps(o, default=jsonable, ensure_ascii=False)


# ------------------------------------------------------------------------------------------------
# small payload builders (the screen components take exactly these shapes)
# ------------------------------------------------------------------------------------------------

def kpi(k: A.Kpi, drill: dict | None = None, tip: list[str] | None = None, period: str = "") -> dict:
    return dict(key=k.key, l=k.label, v=k.value, fmt=k.fmt, sub=k.sub, status=k.status, chip=k.chip,
                explain=k.explain.__dict__ if k.explain else None, drill=drill, tip=tip or [], spark=k.spark,
                period=period or (k.explain.as_of if k.explain else ""))


def panel(title: str, body: dict, sub: str = "", pid: str | None = None, span: int = 1) -> dict:
    return dict(type="panel", title=title, sub=sub, body=body, id=pid, span=span)


def _ctx_key(ctx: dict) -> str:
    """The same view gives the same key however the screen spells it (empty fields, defaults, order)."""
    c = {k: v for k, v in (ctx or {}).items() if v not in (None, "", [], {})}
    for k, d in (("where", "all"), ("compare", "budget"), ("lang", "en"), ("role", "ho"), ("period", "MTD")):
        if c.get(k) == d:
            c.pop(k)
    return json.dumps(c, sort_keys=True, default=str)


SEND_ROWS = 1500                 # rows sent to the screen per table; Export writes all of them
FULL_TABLES: "OrderedDict[str, tuple]" = OrderedDict()     # table id -> (cols, all rows) for Export
_RATE = re.compile(r"avg|average|price|cost|days|age|rate|dly|pct|%|share|margin|cover", re.I)


def _table_totals(cols: list[tuple], rows: list[dict]) -> dict:
    """Totals over every row (the screen only receives the first SEND_ROWS): sums for amounts, averages for rates."""
    num = [(k, kind in ("pct", "pct_chip", "pct_neg", "sg", "x") or bool(_RATE.search(f"{k} {label}")))
           for k, label, kind in cols if kind in ("pkr", "money", "int", "num", "pct", "pct_chip", "pct_neg", "sg", "x")]
    sums = {k: 0.0 for k, _ in num}
    counts = {k: 0 for k, _ in num}
    for r in rows:                                    # one pass over the rows for all columns
        for k, _ in num:
            v = r.get(k)
            if v is not None and v is not True and v is not False and type(v) in (int, float):
                sums[k] += v
                counts[k] += 1
    return {k: (sums[k] / counts[k] if rate else sums[k]) for k, rate in num if counts[k]}


def table(tid: str, cols: list[tuple], rows: list[dict], action: dict | None = None, total: bool | None = None,
          page_size: int = 40, color: Callable[[dict], str] | None = None) -> dict:
    """cols: (key, label, kind) with kind text|int|num|pct|pkr|money|date|bool|chip."""
    def one(r):
        rr = {k: r.get(k) for k, _, _ in cols}
        for extra in ("item", "store", "supplier", "section", "dept", "key", "k"):
            if extra in r and extra not in rr:
                rr[extra] = r[extra]
        if color:
            rr["_c"] = color(r)
        return rr
    extra = {}
    if len(rows) > SEND_ROWS:        # a big table: the screen gets the first rows (already in priority order)
        FULL_TABLES[tid] = (cols, rows)
        FULL_TABLES.move_to_end(tid)
        while len(FULL_TABLES) > 30:
            FULL_TABLES.popitem(last=False)
        extra = dict(total_rows=len(rows), totals=_table_totals(cols, rows))
        rows = rows[:SEND_ROWS]
    return dict(type="table", id=tid, cols=[dict(k=k, l=l, kind=kind) for k, l, kind in cols], rows=[one(r) for r in rows],
                action=action, total=total, page_size=page_size, **extra)


def empty(msg: str) -> dict:
    return dict(type="empty", text=msg)


def note(text: str) -> dict:
    return dict(type="note", text=text)


# ------------------------------------------------------------------------------------------------
# names
# ------------------------------------------------------------------------------------------------
class Names:
    def __init__(self, db: Database):
        self.store = {c: n for c, n in db.q("SELECT code, name FROM stores")}
        self.fmt = {c: f for c, f in db.q("SELECT code, format FROM stores")}
        self.dept = {c: (n, nu) for c, n, nu in db.q("SELECT code, name, name_ur FROM departments")}
        self.section = {c: n for c, n in db.q("SELECT code, name FROM sections")}
        self.sec_dept = {c: d for c, d in db.q("SELECT code, dept FROM sections")}
        self.family = {(c, s): n for c, s, n in db.q("SELECT code, section, name FROM families")}
        self.family_any = {c: n for c, s, n in db.q("SELECT code, section, name FROM families")}
        self.supplier = {c: n for c, n in db.q("SELECT code, name FROM suppliers")}
        self.item = {}

    def name(self, lvl: str, k, row: dict | None = None) -> str:
        if k in (None, ""):
            return L("(not set)", "(نامعلوم)")
        if lvl == "store":
            return self.store.get(k, k)
        if lvl == "dept":
            if k == "NF":
                return L("Non-Food", "نان فوڈ")
            d = self.dept.get(k)
            return (L(d[0], d[1]) if d else k)
        if lvl == "section":
            return f"S{k} {self.section.get(k, '')}".strip()
        if lvl == "family":
            sec = (row or {}).get("section")
            return f"{k} {self.family.get((k, sec)) or self.family_any.get(k) or ''}".strip()
        if lvl == "supplier":
            return self.supplier.get(k) or (row or {}).get("supplier_name") or k
        if lvl == "item":
            return f"{k} {(row or {}).get('description') or ''}".strip()
        return str(k)


# ------------------------------------------------------------------------------------------------
# drill-down: every metric knows its rows and how to add them up
# ------------------------------------------------------------------------------------------------

def _count(rs):
    return len(rs)


def _sum(key):
    return lambda rs: sum((r.get(key) or 0) for r in rs)


ROW_METRICS: dict[str, dict] = {
    "not_on_order": dict(label=("Out of stock, not on order", "آؤٹ آف اسٹاک، آرڈر نہیں"), fmt="int",
                         src="GIMA zero stock sheet", levels=["store", "dept", "section", "supplier", "item"],
                         cols=[("count", ("Items", "آئٹمز"), "int", _count),
                               ("lost", ("Lost / day", "روزانہ نقصان"), "pkr", _sum("lost_per_day"))]),
    "oos": dict(label=("Out-of-stock items", "آؤٹ آف اسٹاک آئٹمز"), fmt="int", src="GIMA zero stock sheet",
                levels=["store", "dept", "section", "supplier", "item"],
                cols=[("count", ("Items", "آئٹمز"), "int", _count),
                      ("noorder", ("Not on order", "آرڈر نہیں"), "int", lambda rs: sum(1 for r in rs if not r["on_order"])),
                      ("lost", ("Lost / day", "روزانہ نقصان"), "pkr", _sum("lost_per_day"))]),
    "lost_sales": dict(label=("Sales lost per day", "روزانہ ضائع سیلز"), fmt="pkr", src="GIMA zero stock sheet + prices",
                       levels=["store", "dept", "section", "supplier", "item"],
                       cols=[("lost", ("Lost / day", "روزانہ نقصان"), "pkr", _sum("lost_per_day")),
                             ("lost_to_date", ("Since out", "آؤٹ ہونے سے"), "pkr", _sum("lost_to_date")),
                             ("count", ("Items", "آئٹمز"), "int", _count)]),
    "negative": dict(label=("Negative stock items", "منفی اسٹاک آئٹمز"), fmt="int", src="GIMA negative stock sheet",
                     levels=["store", "dept", "section", "item"],
                     cols=[("count", ("Items", "آئٹمز"), "int", _count), ("qty", ("Units", "یونٹس"), "num", _sum("qty")),
                           ("value", ("Value at cost", "لاگت"), "pkr", _sum("value"))]),
    "dp_stock": dict(label=("Aged (DP) stock", "ایجڈ (DP) اسٹاک"), fmt="pkr", src="DP master data",
                     levels=["store", "dept", "section", "supplier", "item"],
                     cols=[("value", ("DP stock", "DP اسٹاک"), "pkr", _sum("value")),
                           ("provision", ("DP provision", "DP پروویژن"), "pkr", _sum("provision")),
                           ("extra", ("Extra provision in 30 days", "30 دن میں اضافی"), "pkr",
                            lambda rs: sum(r["extra_provision"] for r in rs if r["days_to_next"] is not None and r["days_to_next"] <= 30)),
                           ("count", ("Items", "آئٹمز"), "int", _count)]),
    "late_lpo": dict(label=("Late orders", "تاخیر شدہ آرڈرز"), fmt="int", src="LPO list",
                     levels=["store", "supplier", "lpo"],
                     cols=[("count", ("Orders", "آرڈرز"), "int", _count), ("value", ("Value", "مالیت"), "pkr", _sum("value")),
                           ("days", ("Max days late", "زیادہ سے زیادہ تاخیر"), "int",
                            lambda rs: max((r["late_days"] or 0) for r in rs) if rs else 0)]),
    "leaflet": dict(label=("Leaflet items out of stock", "لیفلیٹ آئٹمز آؤٹ"), fmt="int", src="Leaflet workbook",
                    levels=["store", "section", "item"],
                    cols=[("count", ("Items", "آئٹمز"), "int", _count),
                          ("noorder", ("Not on order", "آرڈر نہیں"), "int", lambda rs: sum(1 for r in rs if not r["on_order"]))]),
    "sleeping": dict(label=("Stock not selling", "نہ بکنے والا اسٹاک"), fmt="pkr", src="RealTime + benchmark",
                     levels=["store", "dept", "section", "item"],
                     cols=[("value", ("Value at cost", "لاگت"), "pkr", _sum("value")), ("count", ("Items", "آئٹمز"), "int", _count)]),
}


class Host:
    """What the window around the screens can do. The Qt window overrides these with real dialogs."""

    def pick_files(self, kind: str = "reports") -> list[str]:
        return []

    def pick_folder(self) -> str | None:
        return None

    def save_path(self, name: str) -> str | None:
        from stockcompass.paths import exports_dir
        return str(exports_dir() / name)

    def open_path(self, path: str) -> None:
        pass

    def open_url(self, url: str) -> None:
        pass


class Api:
    def __init__(self, db: Database, host: Host | None = None):
        self.db = db
        self.host = host or Host()
        self.imp = ImportJobs(db)
        self._agent = None
        self._pages: OrderedDict = OrderedDict()     # finished screens, until the data or a setting changes
        self._pages_lock = threading.Lock()
        self.imp.on_done = self._after_import

    def _after_import(self, results):
        self.prewarm(self.db.setting("view") or {})
        if self._agent is not None:
            self._agent.digest(results)

    _agent_lock = threading.Lock()

    @property
    def agent(self):
        if self._agent is None:
            with self._agent_lock:
                if self._agent is None:
                    from stockcompass.agent.service import AgentService
                    self._agent = AgentService(self)
        return self._agent

    def start_agent(self):
        threading.Thread(target=lambda: self.agent, daemon=True).start()

    # ---------------------------------------------------------------------------------- plumbing
    def dispatch(self, method: str, params: dict | None = None) -> dict:
        params = params or {}
        ctx = params.get("ctx") or {}
        set_lang(ctx.get("lang") or self.db.setting("language") or "en")
        fn = getattr(self, "m_" + method, None)
        if fn is None:
            return {"error": f"Unknown method {method}"}
        d = None
        if ctx.get("as_of"):                 # a past date chosen on screen: everything shows the data as it stood then
            try:
                d = date.fromisoformat(str(ctx["as_of"])[:10])
            except ValueError:
                d = None
        token = A.AS_OF.set(d)
        try:
            return fn(ctx, **{k: v for k, v in params.items() if k != "ctx"})
        except Exception as e:  # the screen shows the error instead of crashing
            return {"error": str(e), "trace": traceback.format_exc()}
        finally:
            A.AS_OF.reset(token)

    def scope(self, ctx: dict) -> Scope:
        sc = Scope()
        w = ctx.get("where") or "all"
        if w.startswith("fmt:"):
            sc.formats = [w[4:]]
        elif w.startswith("reg:"):
            sc.region = w[4:]
        elif w != "all":
            sc.stores = [w]
        sc.dept = ctx.get("dept") or None
        sc.section = ctx.get("section") or None
        if sc.section and not sc.dept:
            sc.dept = self.db.one("SELECT dept FROM sections WHERE code=?", [sc.section])
        return sc

    def period(self, ctx: dict) -> str | None:
        pers = [p for p, _ in SA.periods(self.db)]
        p = ctx.get("period")
        if p in pers:
            return p
        return "MTD" if "MTD" in pers else (pers[0] if pers else None)

    # ---------------------------------------------------------------------------------- boot / settings
    def m_boot(self, ctx):
        db = self.db
        stores = db.store_list()
        return dict(
            version=__version__,
            stores=[dict(code=s["code"], name=s["name"], format=s["format"], region=s["region"], city=s["city"])
                    for s in stores],
            regions=[r[0] for r in db.q("SELECT DISTINCT region FROM stores WHERE active AND region IS NOT NULL ORDER BY 1")],
            depts=[dict(code=c, name=n, name_ur=nu) for c, n, nu in db.q("SELECT code, name, name_ur FROM departments ORDER BY code")],
            sections=[dict(code=c, dept=d, name=n) for c, d, n in db.q("SELECT code, dept, name FROM sections ORDER BY code")],
            periods=[dict(p=p, d=d, n=SA.PERIOD_NAMES.get(p, (p, p))[0], nu=SA.PERIOD_NAMES.get(p, (p, p))[1]) for p, d in SA.periods(db)],
            view=db.setting("view") or {}, lang=db.setting("language") or "en",
            urdu_font=db.setting("urdu_font") or "Noto Nastaliq Urdu",
            has_data=bool(db.one("SELECT count(*) FROM imports WHERE status='ok'")),
            # every date there is data for (newest first): the "As of" choice on screen
            dates=[str(r[0]) for r in db.q("SELECT DISTINCT snapshot_date FROM imports WHERE status='ok' AND snapshot_date IS NOT NULL "
                                           "ORDER BY 1 DESC LIMIT 120")],
            last_import=db.one("SELECT max(imported_at) FROM imports WHERE status='ok'"),
            report_types=[dict(key=k, name=s.name) for k, s in sorted(REGISTRY.items(), key=lambda x: x[1].name)],
        )

    def m_save_view(self, ctx, view: dict):
        self.db.set_setting("view", view)
        if view.get("lang"):
            self.db.set_setting("language", view["lang"])
        return {"ok": True}

    def m_search(self, ctx, q: str):
        q = (q or "").strip()
        if len(q) < 2:
            return {"results": []}
        like = f"%{q.upper()}%"
        items = self.db.qd("SELECT item k, description n FROM items WHERE item LIKE ? OR upper(description) LIKE ? LIMIT 8",
                           [f"{q}%", like])
        sups = self.db.qd("SELECT code k, name n FROM suppliers WHERE code LIKE ? OR upper(name) LIKE ? LIMIT 5",
                          [f"{q}%", like])
        stores = [s for s in self.db.store_list() if q.upper() in (s["name"] + " " + s["code"]).upper()][:5]
        return {"results": [dict(t="item", k=r["k"], n=f"{r['k']} {r['n'] or ''}") for r in items]
                + [dict(t="supplier", k=r["k"], n=r["n"]) for r in sups]
                + [dict(t="store", k=s["code"], n=f"{s['code']} {s['name']}") for s in stores]}

    # ---------------------------------------------------------------------------------- drill
    def _rows_for(self, metric: str, sc: Scope, ctx: dict) -> list[dict]:
        db = self.db
        if metric in ("oos", "lost_sales"):
            return A.oos_items(db, sc)
        if metric == "not_on_order":
            return [r for r in A.oos_items(db, sc) if not r["on_order"]]
        if metric == "negative":
            return A.negative_items(db, sc)
        if metric == "dp_stock":
            return A.dp_items(db, sc)
        if metric == "late_lpo":
            rows, _ = A.lpo_rows(db, sc)
            return [r for r in rows if r["late_days"]]
        if metric == "leaflet":
            return [r for r in A.leaflet_rows(db, sc) if r["zero"]]
        if metric == "sleeping":
            return X.sleeping(db, sc)[0]
        return []

    def _apply_path(self, sc: Scope, path: list[dict]) -> tuple[Scope, dict]:
        """Store / dept / section in the path narrow the scope; family / supplier / item filter rows."""
        sc = Scope(stores=sc.stores, formats=sc.formats, dept=sc.dept, section=sc.section, region=sc.region)
        rowf = {}
        for p in path or []:
            lvl, k = p["lvl"], p["k"]
            if lvl == "store":
                sc.stores, sc.formats, sc.region = [k], None, None
            elif lvl == "dept":
                sc.dept, sc.section = k, None
            elif lvl == "section":
                sc.section = k
                sc.dept = self.db.one("SELECT dept FROM sections WHERE code=?", [k]) or sc.dept
            else:
                rowf[lvl] = k
        return sc, rowf

    def m_drill(self, ctx, metric: str, path: list | None = None, by: str | None = None):
        names = Names(self.db)
        sc, rowf = self._apply_path(self.scope(ctx), path or [])
        if metric == "sales":
            return self._drill_sales(ctx, sc, rowf, path or [], by, names)
        if metric == "zero_stock":
            return self._drill_zero(ctx, sc, path or [], by, names)
        if metric == "bulk":
            return self._drill_bulk(ctx, sc, rowf, path or [], by, names)
        spec = ROW_METRICS.get(metric)
        if not spec:
            return {"error": f"No drill for {metric}"}
        rows = self._rows_for(metric, sc, ctx)
        for lvl, k in rowf.items():
            rows = [r for r in rows if str(r.get(lvl if lvl != "lpo" else "lpo_no")) == str(k)]
        levels = spec["levels"]
        used = {p["lvl"] for p in (path or [])}
        if not by or by in used:
            by = next((l for l in levels if l not in used and not self._fixed(l, sc)), levels[-1])
        groups = defaultdict(list)
        for r in rows:
            key = r.get("lpo_no") if by == "lpo" else r.get(by)
            groups[key].append(r)
        out = []
        for k, rs in groups.items():
            row = dict(k=k, name=names.name(by, k, rs[0]) if by != "lpo" else f"LPO {k}",
                       sub=self._sub(by, rs[0], names))
            for ck, _, _, fn in spec["cols"]:
                row[ck] = fn(rs)
            if by == "item":
                row["item"] = k
            out.append(row)
        first = spec["cols"][0][0]
        out.sort(key=lambda x: -(x[first] or 0))
        total = spec["cols"][0][3](rows)
        nxt = self._next(levels, used | {by}, sc)
        return dict(metric=metric, title=L(*spec["label"]), fmt=spec["fmt"], total=total, by=by,
                    levels=[dict(k=l, n=L(*LEVEL_NAMES[l])) for l in levels], path=path or [], next=nxt,
                    cols=[dict(k="name", l=L(*LEVEL_NAMES[by]), kind="name")]
                    + [dict(k=ck, l=L(*cl), kind=kind) for ck, cl, kind, _ in spec["cols"]],
                    rows=out, source=spec["src"], scope=sc.label(self.db), share_of=first)

    # ---------------------------------------------------------------------------------- analyse (explorer)
    def m_explore_meta(self, ctx):
        from . import explore as E
        return E.meta(self.db)

    def m_explore(self, ctx, dim: str = "store", dim2: str | None = None, measures: list | None = None,
                  filters: dict | None = None, top: int = 0, sort: str | None = None, desc: bool = True):
        from . import explore as E
        top = int(top or 0)
        top = 2000 if top <= 0 or top > 2000 else top      # "All": the first 2,000 rows, the rest summed as Others
        key = ("explore", _ctx_key(ctx), json.dumps([dim, dim2, measures, filters, top, sort, desc], sort_keys=True, default=str),
               self.db.stamp(), date.today())
        with self._pages_lock:
            hit = self._pages.get(key)
        if hit is not None:
            return hit
        out = E.cube(self, ctx, dim, dim2, measures, filters, top, sort, bool(desc))
        with self._pages_lock:
            self._pages[key] = out
            while len(self._pages) > 40:
                self._pages.popitem(last=False)
        return out

    def m_explore_options(self, ctx, dim: str, measure: str | None = None, q: str = ""):
        from . import explore as E
        return E.options(self, ctx, dim, measure, q)

    def _fixed(self, lvl: str, sc: Scope) -> bool:
        return (lvl == "store" and sc.stores and len(sc.stores) == 1) or (lvl == "section" and sc.section) or \
               (lvl == "dept" and sc.dept and sc.dept != "NF")

    def _next(self, levels, used, sc):
        for l in levels:
            if l not in used and not self._fixed(l, sc):
                return l
        return None

    @staticmethod
    def _sub(by, r, names):
        if by == "item":
            return " · ".join(x for x in [names.name("section", r.get("section")) if r.get("section") else "",
                                          r.get("supplier_name") or ""] if x)
        if by == "section":
            return names.name("dept", names.sec_dept.get(r.get("section")))
        if by == "store":
            return {"H": "Hypermarket", "S": "Supermarket", "M": "Myli"}.get(names.fmt.get(r.get("store")), "")
        return ""

    def _drill_zero(self, ctx, sc, path, by, names):
        levels = ["store", "dept", "section", "item"]
        used = {p["lvl"] for p in path}
        if not by or by in used:
            by = self._next(levels, used, sc) or "item"
        if by == "item":
            rows = A.oos_items(self.db, sc)
            out = [dict(k=r["item"], item=r["item"], name=f"{r['item']} {r['description'] or ''}", sub=r["store_name"],
                        days=r["days_out"], reason=r["reason"], on_order=r["on_order"]) for r in rows]
            return dict(metric="zero_stock", title=L("Zero stock %", "زیرو اسٹاک %"), fmt="pct", total=None, by=by,
                        levels=[dict(k=l, n=L(*LEVEL_NAMES[l])) for l in levels], path=path, next=None,
                        cols=[dict(k="name", l=L("Item", "آئٹم"), kind="name"),
                              dict(k="days", l=L("Days since last sale", "آخری سیل کے دن"), kind="int"),
                              dict(k="reason", l=L("GIMA reason", "جیما وجہ"), kind="text"),
                              dict(k="on_order", l=L("On order", "آرڈر میں"), kind="bool")],
                        rows=out, source="GIMA zero stock sheet (items at zero today)", scope=sc.label(self.db),
                        share_of=None)
        ids = [i for i, _, _ in A.latest_imports(self.db, "bo_zero_summary")]
        w, p = sc.store_sql()
        lvl = {"store": "store", "dept": "dept", "section": "section"}[by]
        wh, pp = [w], list(p)
        if sc.section:
            wh.append("section=?")
            pp.append(sc.section)
        elif sc.dept:
            d, dp = sc.dept_sql("dept")
            wh.append(d)
            pp += dp
        level = "section" if (by == "section" or sc.section) else ("dept" if (by == "dept" or sc.dept) else None)
        if level is None:
            have = {r[0] for r in self.db.q(f"SELECT DISTINCT level FROM zs_daily WHERE import_id IN {A.ids_sql(ids)}")}
            level = "store" if "store" in have else "dept"
        rows = self.db.qd(f"""SELECT {lvl} k, sum(zero_items) z, sum(total_items) t FROM zs_daily
                             WHERE import_id IN {A.ids_sql(ids)} AND level=? AND NOT coalesce(suspect,false)
                             AND day >= date_trunc('month', (SELECT max(day) FROM zs_daily WHERE import_id IN {A.ids_sql(ids)}))
                             AND {' AND '.join(wh)} GROUP BY 1""", [level] + pp) if ids else []
        out = []
        for r in rows:
            out.append(dict(k=r["k"], name=names.name(by, r["k"]), sub=self._sub(by, {by: r["k"], "section": r["k"], "store": r["k"]}, names),
                            pct=r["z"] / r["t"] * 100 if r["t"] else None, zero=r["z"], items=r["t"]))
        out.sort(key=lambda x: -(x["pct"] or 0))
        z = sum(r["zero"] for r in out)
        t = sum(r["items"] for r in out)
        return dict(metric="zero_stock", title=L("Zero stock % (month to date)", "زیرو اسٹاک % (ماہ اب تک)"), fmt="pct",
                    total=z / t * 100 if t else None, by=by, levels=[dict(k=l, n=L(*LEVEL_NAMES[l])) for l in levels],
                    path=path, next=self._next(levels, used | {by}, sc),
                    cols=[dict(k="name", l=L(*LEVEL_NAMES[by]), kind="name"), dict(k="pct", l=L("Zero stock %", "زیرو اسٹاک %"), kind="pct"),
                          dict(k="zero", l=L("Zero item-days", "زیرو آئٹم دن"), kind="int"),
                          dict(k="items", l=L("Item-days", "آئٹم دن"), kind="int")],
                    rows=out, source="BO 500-30-15 zero stock summary", scope=sc.label(self.db), share_of=None)

    def _drill_sales(self, ctx, sc, rowf, path, by, names):
        period = self.period(ctx)
        cmp_ = ctx.get("compare") or "budget"
        levels = ["store", "dept", "section", "family", "supplier", "item"]
        used = {p["lvl"] for p in path}
        if not by or by in used:
            by = self._next(levels, used, sc) or "item"
        cmp_label = L("Budget", "بجٹ") if cmp_ == "budget" else L("Last year", "پچھلا سال")
        cols = [dict(k="name", l=L(*LEVEL_NAMES[by]), kind="name"), dict(k="sales", l=L("Net sales", "نیٹ سیلز"), kind="pkr"),
                dict(k="cmp", l=cmp_label, kind="pkr"), dict(k="vs", l=L("vs", "بمقابلہ") + " " + cmp_label.lower(), kind="sg"),
                dict(k="margin", l=L("Front margin", "فرنٹ مارجن"), kind="pct"), dict(k="share", l=L("Share", "حصہ"), kind="pct")]
        out, src = [], ""
        if by in ("store", "dept", "section") and not rowf:
            rows, info = SA.block_rows(self.db, sc, period) if period else ([], {})
            src = f"BO {info.get('source', '')}"
            if rows:
                key = {"store": "store", "dept": "dept", "section": "section"}[by]
                if by == "store" and not any(r["store"] for r in rows):
                    rows = []
                for g in SA._agg(rows, key, {"store": "store_name", "dept": "dept_name", "section": "section_name"}[by]):
                    c = g["budget"] if cmp_ == "budget" else g["ly"]
                    out.append(dict(k=g["key"], name=names.name(by, g["key"]), sub=self._sub(by, {by: g["key"], "section": g["key"], "store": g["key"]}, names),
                                    sales=g["sales"], cmp=c, vs=(g["sales"] / c - 1) * 100 if c else None,
                                    margin=g["margin"], share=g["share"]))
        if by in ("family", "supplier") or (by in ("store", "section") and not out and period):
            f = SA.fss_rows(self.db, sc, period) if period else []
            for lvl, k in rowf.items():
                f = [r for r in f if str(r.get(lvl)) == str(k)]
            src = "BO 11f"
            g = defaultdict(list)
            for r in f:
                g[r.get(by)].append(r)
            tot = sum(r["sales_cy"] or 0 for r in f) or 1
            for k, rs in g.items():
                cy = sum(r["sales_cy"] or 0 for r in rs)
                ly = sum(r["sales_ly"] or 0 for r in rs)
                wm = [r for r in rs if r["margin_pct"] is not None and r["sales_cy"]]
                m = sum(r["margin_pct"] * r["sales_cy"] for r in wm) / sum(r["sales_cy"] for r in wm) if wm else None
                out.append(dict(k=k, name=names.name(by, k, rs[0]), sub=names.name("section", rs[0]["section"]) if by != "section" else "",
                                sales=cy, cmp=ly, vs=(cy / ly - 1) * 100 if ly else None, margin=m, share=cy / tot * 100))
            cols[2]["l"] = L("Last year", "پچھلا سال")
            cols[3]["l"] = L("Growth", "اضافہ")
        if by == "item":
            ids = [r[0] for r in self.db.q("SELECT max(import_id) FROM imports WHERE report_type='gima_benchmark' GROUP BY stores")]
            if ids:
                w, p = sc.store_sql("s.store")
                wi, pi = sc.item_sql()
                extra, ep = [], []
                for lvl, k in rowf.items():
                    if lvl in ("family", "supplier"):
                        extra.append(f"i.{lvl} = ?")
                        ep.append(k)
                rows = self.db.qd(f"""SELECT s.item, i.description, i.section, sum(s.sales) sales, sum(s.margin) margin,
                                        sum(s.qty) qty FROM sales_item s LEFT JOIN items i USING (item)
                                        WHERE s.import_id IN {A.ids_sql(ids)} AND {w} AND {wi} {''.join(' AND ' + e for e in extra)}
                                        GROUP BY ALL ORDER BY sales DESC""", p + pi + ep)
                tot = sum(r["sales"] or 0 for r in rows) or 1
                out = [dict(k=r["item"], item=r["item"], name=f"{r['item']} {r['description'] or ''}",
                            sub=names.name("section", r["section"]), sales=r["sales"], cmp=None, vs=None,
                            margin=r["margin"] / r["sales"] * 100 if r["sales"] else None, share=(r["sales"] or 0) / tot * 100)
                       for r in rows]
                src = "GIMA benchmark"
        out.sort(key=lambda x: -(x["sales"] or 0))
        total = sum(r["sales"] or 0 for r in out)
        return dict(metric="sales", title=L("Net sales", "نیٹ سیلز"), fmt="pkr", total=total, by=by,
                    levels=[dict(k=l, n=L(*LEVEL_NAMES[l])) for l in levels], path=path,
                    next=self._next(levels, used | {by}, sc), cols=cols, rows=out,
                    source=src or L("No sales data at this level yet", "اس سطح پر سیلز ڈیٹا نہیں"),
                    scope=sc.label(self.db), share_of=None)

    def _drill_bulk(self, ctx, sc, rowf, path, by, names):
        period = self.period(ctx)
        levels = ["store", "section", "family", "supplier"]
        used = {p["lvl"] for p in path}
        if not by or by in used:
            by = self._next(levels, used, sc) or "supplier"
        f = SA.fss_rows(self.db, sc, period) if period else []
        for lvl, k in rowf.items():
            f = [r for r in f if str(r.get(lvl)) == str(k)]
        g = defaultdict(list)
        for r in f:
            if r["b2b_cy"]:
                g[r.get(by)].append(r)
        out = []
        for k, rs in g.items():
            b = sum(r["b2b_cy"] or 0 for r in rs)
            m = sum(r["b2b_margin"] or 0 for r in rs)
            out.append(dict(k=k, name=names.name(by, k, rs[0]), b2b=b, margin=m / b * 100 if b else None,
                            ly=sum(r["b2b_ly"] or 0 for r in rs)))
        out.sort(key=lambda x: -x["b2b"])
        return dict(metric="bulk", title=L("Bulk (B2B) sales", "بلک سیلز"), fmt="pkr", total=sum(r["b2b"] for r in out),
                    by=by, levels=[dict(k=l, n=L(*LEVEL_NAMES[l])) for l in levels], path=path,
                    next=self._next(levels, used | {by}, sc),
                    cols=[dict(k="name", l=L(*LEVEL_NAMES[by]), kind="name"), dict(k="b2b", l="B2B", kind="pkr"),
                          dict(k="ly", l=L("Last year", "پچھلا سال"), kind="pkr"),
                          dict(k="margin", l=L("B2B front margin", "بلک مارجن"), kind="pct")],
                    rows=out, source="BO 11f", scope=sc.label(self.db), share_of="b2b")

    def tips(self, ctx, metric: str, n: int = 4) -> list[str]:
        """Hover breakdown for a KPI card: its biggest contributors."""
        try:
            d = self.m_drill(ctx, metric, [], None)
        except Exception:
            return []
        if not d or d.get("error") or not d.get("rows"):
            return []
        c = next((c for c in d["cols"] if c["k"] != "name"), None)
        lines = []
        for r in d["rows"][:n]:
            v = r.get(c["k"]) if c else None
            lines.append(f"{r['name']}: {fmt_val(v, c['kind']) if c else ''}")
        head = L(f"Biggest by {d['levels'][[l['k'] for l in d['levels']].index(d['by'])]['n'].lower()}",
                 "سب سے بڑے")
        return [head] + lines

    # ---------------------------------------------------------------------------------- item / supplier
    def m_item(self, ctx, item: str):
        d = A.item_360(self.db, item)
        it = d["item"]
        names = Names(self.db)
        stock_total = sum(r["qty"] or 0 for r in d["stock"])
        cost = next((r["cost"] for r in d["stock"] if r.get("cost")), None)
        price = next((r["price"] for r in d["stock"] if r.get("price")), None)
        margin = ((price / 1.18 - cost) / (price / 1.18) * 100) if cost and price else None
        rec = []
        zero_st = [r for r in d["zero"] if not r.get("open_lpo")]
        if zero_st:
            rec.append(L(f"Out of stock with nothing on order in {len({r['store'] for r in zero_st})} store(s): order now.",
                         "کچھ اسٹورز میں آؤٹ آف اسٹاک اور آرڈر نہیں: ابھی آرڈر کریں۔"))
        if d["dp"]:
            rec.append(L(f"Aged (DP) in {len({r['store'] for r in d['dp']})} store(s): move, mark down or return.",
                         "ایجڈ (DP): منتقل کریں، قیمت کم کریں یا واپس کریں۔"))
        if d["negative"]:
            rec.append(L("Negative stock somewhere: recount.", "کہیں منفی اسٹاک: دوبارہ گنتی کریں۔"))
        for r in d["stock"]:
            r["store_name"] = names.store.get(r["store"], r["store"])
        for key in ("zero", "sales", "dp", "negative", "leaflet"):
            for r in d[key]:
                r["store_name"] = names.store.get(r["store"], r["store"])
        from stockcompass.analytics import datasets as D
        try:
            other = D.for_key(self.db, "item", str(item), 30)
        except Exception:
            other = []
        return dict(other=other, item=it, section=names.name("section", it.get("section")), supplier_name=it.get("supplier_name"),
                    stock_total=stock_total, cost=cost, price=price, margin=margin, rec=rec or [L("No urgent action.", "کوئی فوری قدم نہیں۔")],
                    stock=d["stock"], zero=d["zero"], sales=d["sales"], dp=d["dp"], negative=d["negative"], leaflet=d["leaflet"])

    def m_supplier(self, ctx, code: str):
        sc = self.scope(ctx)
        d = X.supplier(self.db, code, sc, self.period(ctx))
        kpis, blocks = [], []
        sal = d.get("sales")
        if sal:
            kpis.append(dict(key="s", l=L("Net sales", "نیٹ سیلز"), v=sal["sales_cy"], fmt="pkr",
                             sub=(L(f"{sal['growth']:+.1f}% vs last year", f"پچھلے سال سے {sal['growth']:+.1f}%")
                                  if sal.get("growth") is not None else ""),
                             status="good" if (sal.get("growth") or 0) >= 0 else "crit", drill=dict(m="sales", path=[dict(lvl="supplier", k=code, n=d["name"])])))
            kpis.append(dict(key="m", l=L("Front margin", "فرنٹ مارجن"), v=sal.get("margin"), fmt="pct",
                             status="crit" if (sal.get("margin") or 0) < 0 else ""))
        if d.get("received_pct") is not None:
            kpis.append(dict(key="rcv", l=L("Delivered (value)", "ترسیل (مالیت)"), v=d["received_pct"], fmt="pct",
                             status="good" if d["received_pct"] >= 70 else "crit", chip="≥70%",
                             sub=L(f"{len(d['lpo'])} orders", f"{len(d['lpo'])} آرڈرز")))
        if d.get("purge_pct") is not None:
            kpis.append(dict(key="pur", l=L("Purged orders", "منسوخ آرڈرز"), v=d["purge_pct"], fmt="pct",
                             status="good" if d["purge_pct"] <= 20 else "crit", chip="≤20%"))
        kpis.append(dict(key="oos", l=L("Out of stock items", "آؤٹ آف اسٹاک آئٹمز"), v=len(d["oos"]), fmt="int",
                         status="crit" if any(not r["on_order"] for r in d["oos"]) else ("good" if not d["oos"] else "warn"),
                         sub=L(f"{sum(1 for r in d['oos'] if not r['on_order'])} not on order",
                               f"{sum(1 for r in d['oos'] if not r['on_order'])} آرڈر نہیں")))
        kpis.append(dict(key="dp", l=L("Aged (DP) stock", "ایجڈ (DP) اسٹاک"), v=sum(r["value"] or 0 for r in d["dp"]), fmt="pkr",
                         sub=L(f"provision {fmt_pkr(sum(r['provision'] or 0 for r in d['dp']))}",
                               f"پروویژن {fmt_pkr(sum(r['provision'] or 0 for r in d['dp']))}")))
        if d.get("families"):
            blocks.append(panel(L("Families", "فیملیز"), table("sup_f", [
                ("name", L("Family", "فیملی"), "name"), ("sales_cy", L("Net sales", "نیٹ سیلز"), "money"),
                ("growth", L("Growth", "اضافہ"), "sg"), ("share", L("Share", "حصہ"), "pct"), ("margin", L("Margin", "مارجن"), "pct_neg")],
                d["families"], total=True)))
        if d["oos"]:
            blocks.append(panel(L("Out of stock", "آؤٹ آف اسٹاک"), table("sup_oos", [
                ("description", L("Item", "آئٹم"), "text"), ("store_name", L("Store", "اسٹور"), "text"),
                ("days_out", L("Days out", "دن"), "int"), ("reason_group", L("Why", "کیوں"), "text"),
                ("on_order", L("On order", "آرڈر پر"), "bool"), ("lost_per_day", L("Lost / day", "روزانہ نقصان"), "money")],
                d["oos"], action=dict(kind="item"), color=lambda r: "" if r["on_order"] else "crit")))
        if d["lpo"]:
            blocks.append(panel(L("Orders (LPO)", "آرڈرز"), table("sup_lpo", [
                ("lpo_no", L("LPO", "ایل پی او"), "text"), ("store_name", L("Store", "اسٹور"), "text"),
                ("lpo_date", L("Ordered", "آرڈر"), "date"), ("delivery_date", L("Due", "واجب"), "date"),
                ("status", L("Status", "حالت"), "text"), ("value", L("Value", "مالیت"), "money"),
                ("grn_value", L("Received", "وصول"), "money"), ("late_days", L("Days late", "دن تاخیر"), "int")],
                sorted(d["lpo"], key=lambda r: -(r["late_days"] or 0)), color=lambda r: "crit" if r["late_days"] else ("warn" if r["deleted"] else ""))))
        if d["dp"]:
            blocks.append(panel(L("Aged (DP) stock", "ایجڈ (DP) اسٹاک"), table("sup_dp", [
                ("description", L("Item", "آئٹم"), "text"), ("store_name", L("Store", "اسٹور"), "text"),
                ("age_days", L("Age (days)", "عمر"), "int"), ("value", L("Value", "مالیت"), "money"),
                ("provision", L("Provision", "پروویژن"), "money"), ("route", L("Next step", "اگلا قدم"), "text")],
                sorted(d["dp"], key=lambda r: -(r["value"] or 0)), action=dict(kind="item"), total=True)))
        from stockcompass.analytics import datasets as D
        try:
            for o in D.for_key(self.db, "supplier", str(code), 60):
                blocks.append(panel(o["name"], table(f"sup_ds_{o['key']}", [(c["k"], c["l"], c["kind"]) for c in o["cols"]], o["rows"],
                                                     action=dict(kind="item")), sub=f"imported data · {o['total']:,} rows"))
        except Exception:
            pass
        return dict(code=code, name=d["name"], kpis=kpis, blocks=blocks, scope=sc.label(self.db))

    # ---------------------------------------------------------------------------------- pages
    def m_page(self, ctx, name: str, **kw):
        ctx = {**ctx, **kw}  # tab / theme etc. may come either way
        fn = getattr(self, "p_" + name, None)
        if not fn:
            return {"error": f"No page {name}"}
        key = None
        if name not in ("import", "settings"):          # those change as you use them; everything else is cached
            extra = self.db.one("SELECT coalesce(md5(string_agg(key, ',' ORDER BY key)), '') FROM job_done") if name == "home" else ""
            key = (name, _ctx_key(ctx), self.db.stamp(), date.today(), extra)
            with self._pages_lock:
                hit = self._pages.get(key)
            if hit is not None:
                return hit
        sc = self.scope(ctx)
        out = fn(ctx, sc)
        out.setdefault("scope", sc.label(self.db))
        if key is not None:
            with self._pages_lock:
                self._pages[key] = out
                while len(self._pages) > 40:
                    self._pages.popitem(last=False)
        return out

    def prewarm(self, ctx: dict | None = None):
        """Build the main screens in the background (at start and after an import) so they open instantly."""
        def run():
            v = self.db.setting("view") or {}
            base = {"lang": "en", "role": "ho", "where": "all", "compare": "budget", **(ctx or {})}
            jobs = [(base, "home", None)]
            if v.get("role") in ("sm", "dh", "sec") and v.get("roleStore"):      # the store view you left open
                sv = {**base, "role": v["role"], "where": v["roleStore"]}
                if v["role"] == "dh":
                    sv["dept"] = v.get("roleDept") or "01"
                if v["role"] == "sec":
                    sv["section"] = v.get("roleSec") or ""
                jobs.insert(0, (sv, "home", None))
            jobs += [(base, n, None) for n in ("sales", "stock", "orders", "promos", "category", "score", "health")]
            jobs += [(base, "stock", t) for t in ("zero", "oos", "neg", "sleeping", "dp", "move", "blocked", "leaflet")]
            jobs += [({**base, "role": r}, n, None) for r in ("dm", "cd") for n in ("home", "sales")]
            for c, name, tab in jobs:
                try:
                    self.m_page(dict(c), name, **({"tab": tab} if tab else {}))
                except Exception:
                    pass
        threading.Thread(target=run, daemon=True).start()

    def _kpis_home(self, ctx, sc):
        kp, ins = A.overview(self.db, sc)
        drill_for = {"zero_stock": "zero_stock", "not_on_order": "not_on_order", "lost_sales": "lost_sales",
                     "negative": "negative", "dp_stock": "dp_stock", "late_lpo": "late_lpo"}
        out = []
        per = self.period(ctx)
        if per:
            sk, _ = SA.kpis(self.db, sc, per, ctx.get("compare") or "budget")
            for k in sk:
                if k.key in ("sales", "growth", "margin"):
                    out.append(kpi(k, drill=dict(m="sales"), tip=self.tips(ctx, "sales") if k.key == "sales" else []))
        for k in kp:
            m = drill_for.get(k.key)
            out.append(kpi(k, drill=dict(m=m) if m else (dict(page="score") if k.key == "bc_greens" else None),
                           tip=self.tips(ctx, m) if m else []))
        return out, ins

    def p_home(self, ctx, sc):
        role = ctx.get("role") or "ho"
        kpis, ins = self._kpis_home(ctx, sc)
        if role in ("sm", "dh", "sec"):
            ins = [i for i in ins if i.get("goto") != "health"]
        out = dict(title=L("Good day", "خوش آمدید"), kpis=kpis, insights=ins, blocks=[])
        if role in ("sm", "dh", "sec"):
            js = J.jobs(self.db, sc)
            day = date.today()
            done = {r[0] for r in self.db.q("SELECT key FROM job_done")}
            out["jobs"] = [dict(key=j.key, id=J.job_key(sc, j.key, day), title=j.title, why=j.why, count=j.count,
                                value=j.value, value_label=j.value_label, level=j.level, goto=j.goto,
                                done=J.job_key(sc, j.key, day) in done,
                                table=table("job_" + j.key, [(k, _col(k), kind) for k, kind in j.columns], j.rows,
                                            action=dict(kind="item") if any(k == "item" for k, _ in j.columns) else None))
                           for j in js]
        zs = A.zero_stock_summary(self.db, sc)
        if zs:
            rows = A.zero_stock_daily(self.db, sc)
            fmt = Names(self.db).fmt
            agg = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
            for r in rows:
                if not r["suspect"] and r["total"]:
                    agg[fmt.get(r["store"], "?")][r["day"]][0] += r["zero"]
                    agg[fmt.get(r["store"], "?")][r["day"]][1] += r["total"]
            xs = sorted({d for f in agg.values() for d in f})
            colors = {"H": "var(--s1)", "S": "var(--s2)", "M": "var(--s3)"}
            series = [dict(n=L(*{"H": ("Hypermarkets", "ہائپر"), "S": ("Supermarkets", "سپر"), "M": ("Mylis", "مائلی")}[f]),
                           c=colors[f], v=[(agg[f][d][0] / agg[f][d][1] * 100) if agg[f][d][1] else None for d in xs])
                      for f in ("H", "S", "M") if f in agg]
            target = self.db.one("SELECT min(target) FROM bc_targets WHERE indicator='zero_stock'")
            if target:
                series.append(dict(n=L(f"Target {target:g}%", f"ہدف {target:g}%"), c="var(--good)", dash=True, v=[target] * len(xs)))
            out["blocks"].append(dict(cols=2, panels=[
                panel(L("Zero stock % by day", "روزانہ زیرو اسٹاک %"),
                      dict(type="line", id="h_zs", xs=[d.isoformat() for d in xs], series=series, fmt="pct",
                           drill=dict(m="zero_stock")), sub=f"{zs['month_start']:%d %b} – {zs['last_day']:%d %b}", pid="h_zs"),
                self._heat_panel(ctx, sc)]))
        if role in ("cd", "ho", "dm") and zs:
            names = Names(self.db)
            srows = [dict(store=s["store"], name=names.store.get(s["store"], s["store"]), mtd=s["mtd_pct"], day=s["day_pct"],
                          zero=s["zero_today"], items=s["items_today"]) for s in zs["stores"]]
            target = self.db.one("SELECT min(target) FROM bc_targets WHERE indicator='zero_stock'", default=12)
            out["blocks"].append(dict(cols=1, panels=[panel(
                L("Stores: zero stock % this month", "اسٹورز: اس ماہ زیرو اسٹاک %"),
                table("h_stores", [("name", L("Store", "اسٹور"), "name"), ("mtd", L("Month to date", "ماہ اب تک"), "pct_chip"),
                                   ("day", L("Latest day", "آخری دن"), "pct"), ("zero", L("Zero today", "آج زیرو"), "int"),
                                   ("items", L("Items", "آئٹمز"), "int")], srows, action=dict(kind="focus_store"),
                      color=lambda r: "good" if (r["mtd"] or 0) <= target else ("warn" if (r["mtd"] or 0) <= target * 1.25 else "crit")),
                sub=L("Click a store to focus on it", "اسٹور پر کلک کریں"))]))
        return out

    def _heat_panel(self, ctx, sc):
        ids = [i for i, _, _ in A.latest_imports(self.db, "bo_zero_summary")]
        names = Names(self.db)
        if not ids:
            return panel(L("Zero stock by store and department", "اسٹور اور ڈیپارٹمنٹ"), empty(L("Needs the department tab of the zero stock report", "زیرو اسٹاک رپورٹ کا ڈیپارٹمنٹ ٹیب درکار")))
        w, p = sc.store_sql()
        rows = self.db.qd(f"""SELECT store, dept, sum(zero_items) z, sum(total_items) t FROM zs_daily
                             WHERE import_id IN {A.ids_sql(ids)} AND level='dept' AND NOT coalesce(suspect,false)
                             AND day >= date_trunc('month', (SELECT max(day) FROM zs_daily WHERE import_id IN {A.ids_sql(ids)}))
                             AND {w} GROUP BY 1, 2""", p)
        if not rows:
            return panel(L("Zero stock by store and department", "اسٹور اور ڈیپارٹمنٹ"), empty(L("Needs the department tab of the zero stock report", "ڈیپارٹمنٹ ٹیب درکار")))
        stores = sorted({r["store"] for r in rows}, key=lambda s: names.store.get(s, s))
        depts = sorted({r["dept"] for r in rows})
        cells = {(r["store"], r["dept"]): (r["z"] / r["t"] * 100 if r["t"] else None, r["t"]) for r in rows}
        minn = int(self.db.setting("min_items_for_pct") or 20)
        return panel(L("Zero stock % by store and department", "اسٹور اور ڈیپارٹمنٹ کے حساب سے زیرو اسٹاک %"),
                     dict(type="heat", rows=[dict(k=s, n=names.store.get(s, s)) for s in stores],
                          cols=[dict(k=d, n=names.dept.get(d, (d, d))[0][:3].upper() if d not in ("01", "02", "03", "04", "05")
                                     else {"01": "CG", "02": "FFD", "03": "LHH", "04": "HHH", "05": "TXT"}[d]) for d in depts],
                          cells=[[(cells.get((s, d), (None, 0))[0] if cells.get((s, d), (None, 0))[1] >= minn else None) for d in depts] for s in stores],
                          target=self.db.one("SELECT min(target) FROM bc_targets WHERE indicator='zero_stock'", default=12),
                          drill=dict(m="zero_stock")),
                     sub=L("Month to date · click a cell for its sections and items", "ماہ اب تک · خانے پر کلک کریں"))

    # -- sales
    def p_sales(self, ctx, sc):
        per = self.period(ctx)
        if not per:
            return dict(title=L("Sales", "سیلز"), empty=L("No sales reports imported yet (BO 11b, 11f, family sales or 200-10-05 store net sales).",
                                                         "ابھی سیلز رپورٹس امپورٹ نہیں ہوئیں۔"))
        cmp_ = ctx.get("compare") or "budget"
        kp, ov = SA.kpis(self.db, sc, per, cmp_)
        kd = {"sales": "sales", "growth": "sales", "margin": "sales", "qty": "sales", "b2b": "bulk", "oos_bo": "zero_stock"}
        kpis = [kpi(k, drill=dict(m=kd.get(k.key, "sales")), tip=self.tips(ctx, "sales") if k.key == "sales" else
                    (self.tips(ctx, "bulk") if k.key == "b2b" else [])) for k in kp]
        out = dict(title=L("Sales", "سیلز"), sub=L("How much we sold, against budget and last year, and where it came from.",
                                                  "ہم نے کتنا بیچا، بجٹ اور پچھلے سال کے مقابلے میں۔"), kpis=kpis, blocks=[])
        if not ov:
            out["empty"] = L("No sales rows for this selection.", "اس انتخاب کے لیے سیلز نہیں۔")
            return out
        groups = [g for g in ov.get("by_group", []) if g["sales"] or g["budget"]]
        lvl = ov.get("group_level", "dept")
        cmp_name = L("Budget", "بجٹ") if cmp_ == "budget" else L("Last year", "پچھلا سال")
        names = Names(self.db)
        if groups:
            top = groups[:8]
            bars = dict(type="bar", id="s_bars", cats=[dict(l=names.name(lvl, g["key"]).replace("S0", "S0"), k=g["key"]) for g in top],
                        series=[dict(n=L("Net sales", "نیٹ سیلز"), c="var(--s1)", v=[g["sales"] for g in top]),
                                dict(n=cmp_name, c="var(--s3)", v=[(g["budget"] if cmp_ == "budget" else g["ly"]) or 0 for g in top])],
                        fmt="pkr", drill=dict(m="sales", lvl=lvl))
            base = sum((g["budget"] if cmp_ == "budget" else g["ly"]) or 0 for g in groups)
            items = [dict(l=names.name(lvl, g["key"]), k=g["key"], v=g["sales"] - ((g["budget"] if cmp_ == "budget" else g["ly"]) or 0)) for g in groups[:6]]
            if len(groups) > 6:
                items.append(dict(l=L("Other", "دیگر"), v=sum(g["sales"] - ((g["budget"] if cmp_ == "budget" else g["ly"]) or 0) for g in groups[6:])))
            wf = dict(type="waterfall", id="s_wf", items=items, start=base, end=ov["sales"], labels=[cmp_name, L("Net sales", "نیٹ سیلز")],
                      fmt="pkr", drill=dict(m="sales", lvl=lvl))
            out["blocks"].append(dict(cols=2, panels=[
                panel(L("Sales vs", "سیلز بمقابلہ") + " " + cmp_name.lower(), bars, sub=L(*LEVEL_NAMES[lvl]), pid="s_bars"),
                panel(L("What moved the total", "کل میں تبدیلی کہاں سے"), wf, sub=f"{cmp_name} → {L('actual', 'اصل')}", pid="s_wf")]))
            brows = [dict(k=g["key"], name=names.name(lvl, g["key"]), sales=g["sales"], budget=g["budget"], vsb=g["vs_budget"],
                          ly=g["ly"], growth=g["growth"], share=g["share"], margin=g["margin"], oos=g["oos"],
                          stock_value=g["stock_value"]) for g in groups]
            fam = SA.families(self.db, sc, per)
            pts = [dict(k=f["key"], n=f["name"], x=f["growth"], y=f["margin"], s=f["sales_cy"],
                        drill=dict(m="sales", path=[dict(lvl="section", k=f["key"].split(":")[0], n=f.get("section_name") or ""),
                                                    dict(lvl="family", k=f.get("family") or f["key"].split(":")[-1], n=f["name"])], by="supplier"))
                   for f in fam[:40] if f.get("growth") is not None and f.get("margin") is not None]
            out["blocks"].append(dict(cols=2, panels=[
                panel(L("Breakdown", "تفصیل"),
                      table("s_break", [("name", L(*LEVEL_NAMES[lvl]), "name"), ("sales", L("Net sales", "نیٹ سیلز"), "money"),
                                        ("budget", L("Budget", "بجٹ"), "money"), ("vsb", L("vs budget", "بجٹ کے مقابلے"), "sg"),
                                        ("ly", L("Last year", "پچھلا سال"), "money"), ("growth", L("Growth", "اضافہ"), "sg"),
                                        ("share", L("Share", "حصہ"), "pct"), ("margin", L("Margin", "مارجن"), "pct_neg"),
                                        ("oos", L("OOS % (BO)", "آؤٹ آف اسٹاک %"), "pct")], brows,
                            action=dict(kind="drill", m="sales", lvl=lvl), total=True),
                      sub=L("Click a row to see what is inside", "اندر دیکھنے کے لیے قطار پر کلک کریں")),
                panel(L("Family map: growth vs margin", "فیملی نقشہ"),
                      dict(type="scatter", id="s_sc", pts=pts) if pts else empty(L("Needs BO 11f or family sales", "11 ایف درکار")),
                      sub=L("Bubble size = sales", "دائرے کا سائز = سیلز"), pid="s_sc")]))
        sup = SA.suppliers(self.db, sc, per)
        b2b = SA.b2b_by_store(self.db, sc, per)
        panels = []
        if sup:
            panels.append(panel(L("Suppliers", "سپلائرز"),
                                table("s_sup", [("name", L("Supplier", "سپلائر"), "name"), ("sales_cy", L("This year", "اس سال"), "money"),
                                                ("growth", L("Growth", "اضافہ"), "sg"), ("margin", L("Margin", "مارجن"), "pct_neg"),
                                                ("b2b", "B2B", "money"), ("promo", L("Promo %", "پروموشن %"), "pct")],
                                      [dict(s, supplier=s["key"]) for s in sup], action=dict(kind="supplier")),
                                sub=L("Click for the supplier view", "سپلائر ویو کے لیے کلک کریں")))
        if b2b:
            panels.append(panel(L("Bulk (B2B) by store", "اسٹور کے حساب سے بلک"),
                                dict(type="hbars", fmt="pkr", items=[dict(l=b["name"], v=b["b2b"], x=L(f"Bulk margin {b['b2b_margin']:.1f}%", "بلک مارجن")
                                                                          if b["b2b_margin"] is not None else "",
                                                                          c="var(--crit)" if (b["b2b_margin"] or 0) < 0 else "var(--s2)",
                                                                          drill=dict(m="bulk", path=[dict(lvl="store", k=b["key"], n=b["name"])]))
                                                                     for b in sorted(b2b, key=lambda x: -x["b2b"])]),
                                sub="BO 11f"))
        if panels:
            out["blocks"].append(dict(cols=2 if len(panels) == 2 else 1, panels=panels))
        items = SA.items(self.db, sc)
        lost = SA.lost_lines(self.db, sc, "YTD")
        panels = []
        if items:
            panels.append(panel(L("Items (benchmark)", "آئٹمز"),
                                table("s_items", [("item", L("Item", "آئٹم"), "text"), ("description", L("Description", "تفصیل"), "text"),
                                                  ("sales", L("Net sales", "نیٹ سیلز"), "money"), ("qty", L("Qty", "مقدار"), "num"),
                                                  ("margin_pct", L("Margin", "مارجن"), "pct_neg"), ("abc", "ABC", "text")], items,
                                      action=dict(kind="item"))))
        if lost:
            panels.append(panel(L("Lost since last year", "پچھلے سال کے بعد ختم"),
                                table("s_lost", [("store_name", L("Store", "اسٹور"), "text"), ("family_name", L("Family", "فیملی"), "text"),
                                                 ("supplier_name", L("Supplier", "سپلائر"), "text"), ("sales_ly", L("Sold last year", "پچھلے سال"), "money")],
                                      lost, action=dict(kind="supplier")),
                                sub=L("Sold last year (YTD), nothing this year", "پچھلے سال بکا، اس سال صفر")))
        if panels:
            out["blocks"].append(dict(cols=len(panels), panels=panels))
        return out

    # -- stock
    def p_stock(self, ctx, sc):
        tab = ctx.get("tab") or "oos"
        tabs = [("zero", L("Zero stock", "زیرو اسٹاک")), ("oos", L("Out of stock", "آؤٹ آف اسٹاک")),
                ("neg", L("Negative", "منفی")), ("sleeping", L("Not selling", "نہیں بک رہا")),
                ("dp", L("Aged / DP", "ایجڈ / DP")), ("move", L("Move stock (IST)", "منتقلی (IST)")),
                ("blocked", L("Blocked 007", "بلاک 007")), ("leaflet", L("Leaflet", "لیفلیٹ"))]
        out = dict(title=L("Stock health", "اسٹاک کی صحت"),
                   sub=L("Is the right stock on the shelf, and is aged (DP) stock under control?", "کیا صحیح اسٹاک شیلف پر ہے؟"),
                   tabs=[dict(k=k, n=n) for k, n in tabs], tab=tab, kpis=[], blocks=[])
        getattr(self, "_stock_" + tab)(ctx, sc, out)
        return out

    def _stock_zero(self, ctx, sc, out):
        zs = A.zero_stock_summary(self.db, sc)
        if not zs:
            out["empty"] = L("Import the BO 500-30-15 zero stock summary.", "بی او زیرو اسٹاک سمری امپورٹ کریں۔")
            return
        kp, _ = A.overview(self.db, sc)
        for k in kp:
            if k.key == "zero_stock":
                out["kpis"].append(kpi(k, drill=dict(m="zero_stock"), tip=self.tips(ctx, "zero_stock")))
        names = Names(self.db)
        rows = A.zero_stock_daily(self.db, sc)
        by = defaultdict(dict)
        for r in rows:
            if not r["suspect"] and r["total"]:
                by[r["store"]][r["day"]] = r["zero"] / r["total"] * 100
        xs = sorted({d for s in by.values() for d in s})
        worst = [s["store"] for s in zs["stores"]][:6]
        pal = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)"]
        series = [dict(n=names.store.get(s, s), c=pal[i % 6], v=[by[s].get(d) for d in xs]) for i, s in enumerate(worst)]
        out["blocks"].append(dict(cols=2, panels=[
            panel(L("Worst stores: zero stock % by day", "بدترین اسٹورز: روزانہ زیرو اسٹاک %"),
                  dict(type="line", id="z_line", xs=[d.isoformat() for d in xs], series=series, fmt="pct", drill=dict(m="zero_stock")),
                  pid="z_line"), self._heat_panel(ctx, sc)]))
        srows = [dict(store=s["store"], name=names.store.get(s["store"], s["store"]), mtd=s["mtd_pct"], day=s["day_pct"],
                      zero=s["zero_today"], items=s["items_today"]) for s in zs["stores"]]
        out["blocks"].append(dict(cols=1, panels=[panel(L("Stores", "اسٹورز"), table(
            "z_stores", [("name", L("Store", "اسٹور"), "name"), ("mtd", L("Month to date", "ماہ اب تک"), "pct"),
                         ("day", L("Latest day", "آخری دن"), "pct"), ("zero", L("Zero today", "آج زیرو"), "int"),
                         ("items", L("Items", "آئٹمز"), "int")], srows, action=dict(kind="drill", m="zero_stock", lvl="store")))]))
        if zs.get("suspect_days"):
            out["notes"] = [L(f"{zs['suspect_days']} store-days where the stock load looked broken are left out.",
                              f"{zs['suspect_days']} خراب دن شامل نہیں۔")]

    def _stock_oos(self, ctx, sc, out):
        rows = A.oos_items(self.db, sc)
        if not rows:
            out["empty"] = L("Import the GIMA zero stock sheet (one per store).", "جیما زیرو اسٹاک شیٹ امپورٹ کریں۔")
            return
        kp, _ = A.overview(self.db, sc)
        for k in kp:
            if k.key in ("not_on_order", "lost_sales"):
                m = k.key
                out["kpis"].append(kpi(k, drill=dict(m=m), tip=self.tips(ctx, m)))
        g = defaultdict(list)
        for r in rows:
            g[r["reason_group"]].append(r)
        items = [dict(l=L(A.REASON_ACTION[k][0], A.REASON_ACTION[k][2]), v=len(v), x=L(A.REASON_ACTION[k][1], ""),
                      c="var(--crit)" if k in ("not_ordered", "reorder") else "var(--s1)",
                      drill=dict(m="oos", by="item")) for k, v in sorted(g.items(), key=lambda x: -len(x[1]))]
        out["blocks"].append(dict(cols=2, panels=[
            panel(L("Why items are out of stock", "آئٹمز آؤٹ آف اسٹاک کیوں ہیں"), dict(type="hbars", fmt="int", items=items),
                  sub="GIMA CODDES"),
            panel(L("Not on order by section", "سیکشن کے حساب سے آرڈر نہیں"),
                  dict(type="hbars", fmt="int", items=self._hb_by(rows, "section", lambda rs: sum(1 for r in rs if not r["on_order"]), "not_on_order")))]))
        out["blocks"].append(dict(cols=1, panels=[panel(L("Out-of-stock items: not on order first", "آؤٹ آف اسٹاک آئٹمز"), table(
            "o_items", [("store_name", L("Store", "اسٹور"), "text"), ("item", L("Item", "آئٹم"), "text"),
                        ("description", L("Description", "تفصیل"), "text"), ("section_name", L("Section", "سیکشن"), "text"),
                        ("on_order", L("On order", "آرڈر میں"), "bool"), ("reason", L("GIMA reason", "جیما وجہ"), "text"),
                        ("action", L("What to do", "کیا کریں"), "text"), ("days_out", L("Days out", "دن"), "int"),
                        ("dlyavg", L("Sells/day", "روزانہ"), "num"), ("lost_per_day", L("Lost/day", "نقصان/دن"), "money"),
                        ("supplier_name", L("Supplier", "سپلائر"), "text")], rows, action=dict(kind="item"),
            color=lambda r: "crit" if not r["on_order"] else ("warn" if r["late"] else "")))]))

    def _hb_by(self, rows, lvl, fn, metric):
        names = Names(self.db)
        g = defaultdict(list)
        for r in rows:
            g[r.get(lvl)].append(r)
        items = [dict(l=names.name(lvl, k, rs[0]), v=fn(rs), drill=dict(m=metric, path=[dict(lvl=lvl, k=k, n=names.name(lvl, k, rs[0]))]))
                 for k, rs in g.items()]
        return sorted([i for i in items if i["v"]], key=lambda x: -x["v"])[:12]

    def _stock_neg(self, ctx, sc, out):
        rows = A.negative_items(self.db, sc)
        if not rows:
            out["empty"] = L("Import the GIMA negative stock sheet or RealTime.", "منفی اسٹاک شیٹ امپورٹ کریں۔")
            return
        kp, _ = A.overview(self.db, sc)
        for k in kp:
            if k.key == "negative":
                out["kpis"].append(kpi(k, drill=dict(m="negative"), tip=self.tips(ctx, "negative")))
        g = defaultdict(list)
        for r in rows:
            g[r["status"] or "?"].append(r)
        out["blocks"].append(dict(cols=2, panels=[
            panel(L("Negative stock by cause", "وجہ کے حساب سے منفی اسٹاک"),
                  dict(type="hbars", fmt="int", items=[dict(l=f"{k} · {A.NEG_CAUSE.get(k, ('?',))[0]}", v=len(v), x=A.NEG_CAUSE.get(k, ('', ''))[1],
                                                            drill=dict(m="negative", by="item")) for k, v in g.items()])),
            panel(L("By section", "سیکشن کے حساب سے"), dict(type="hbars", fmt="int", items=self._hb_by(rows, "section", len, "negative")))]))
        out["blocks"].append(dict(cols=1, panels=[panel(L("Negative stock items", "منفی اسٹاک آئٹمز"), table(
            "n_items", [("store_name", L("Store", "اسٹور"), "text"), ("item", L("Item", "آئٹم"), "text"),
                        ("description", L("Description", "تفصیل"), "text"), ("qty", L("Qty", "مقدار"), "num"),
                        ("status", L("Status", "اسٹیٹس"), "text"), ("cause", L("Likely cause", "ممکنہ وجہ"), "text"),
                        ("action", L("What to do", "کیا کریں"), "text"), ("value", L("Value", "مالیت"), "money")], rows,
            action=dict(kind="item")))]))

    def _stock_sleeping(self, ctx, sc, out):
        rows, note_ = X.sleeping(self.db, sc)
        if not rows:
            out["empty"] = note_ or L("Needs GIMA RealTime plus benchmark sales covering 30/60 days.", "ریئل ٹائم اور بینچ مارک درکار۔")
            return
        out["kpis"].append(dict(key="sleep", l=L("Stock not selling", "نہ بکنے والا اسٹاک"), v=sum(r["value"] for r in rows), fmt="pkr",
                                sub=L(f"{len(rows):,} items", f"{len(rows):,} آئٹمز"), drill=dict(m="sleeping"), tip=self.tips(ctx, "sleeping")))
        out["blocks"].append(dict(cols=1, panels=[panel(L("Items with stock and no sale", "اسٹاک مگر کوئی سیل نہیں"), table(
            "sl_items", [("store_name", L("Store", "اسٹور"), "text"), ("item", L("Item", "آئٹم"), "text"),
                         ("description", L("Description", "تفصیل"), "text"), ("section_name", L("Section", "سیکشن"), "text"),
                         ("qty", L("Qty", "مقدار"), "num"), ("value", L("Value", "مالیت"), "money"),
                         ("last_sale", L("Last sale", "آخری سیل"), "date")], rows, action=dict(kind="item")),
            sub=note_ or L("BC rule: CG 30 days, non-food 60 days", "بی سی قاعدہ"))]))

    def _stock_dp(self, ctx, sc, out):
        rows = A.dp_items(self.db, sc)
        if not rows:
            out["empty"] = L("Import the DP workbook (master data sheet).", "ڈی پی ورک بک امپورٹ کریں۔")
            return
        kp, _ = A.overview(self.db, sc)
        for k in kp:
            if k.key == "dp_stock":
                out["kpis"].append(kpi(k, drill=dict(m="dp_stock"), tip=self.tips(ctx, "dp_stock")))
        soon = [r for r in rows if r["days_to_next"] is not None and r["days_to_next"] <= 30]
        out["kpis"].append(dict(key="dp_next", l=L("Provision steps up within 30 days", "30 دن میں پروویژن بڑھے گی"),
                                v=sum(r["extra_provision"] for r in soon), fmt="pkr", status="warn" if soon else "",
                                sub=L(f"{len(soon)} items to clear first", f"{len(soon)} آئٹمز"), drill=dict(m="dp_stock", by="item")))
        order = ["6 Months", "9 Months", "1 Year", "1.5 Year", "2 Years", "Above 2 years"]
        b = defaultdict(float)
        for r in rows:
            b[r["bucket"] or "?"] += r["value"] or 0
        cats = [x for x in order if x in b] + [x for x in b if x not in order]
        ramp = ["var(--a1)", "var(--a2)", "var(--a3)", "var(--a4)", "var(--a5)", "var(--a6)"]
        rt = defaultdict(float)
        for r in rows:
            rt[r["route"]] += r["value"] or 0
        out["blocks"].append(dict(cols=2, panels=[
            panel(L("DP stock by ageing bucket", "ایجنگ بکٹ کے حساب سے DP اسٹاک"),
                  dict(type="hbars", fmt="pkr", items=[dict(l=c, v=b[c], c=ramp[min(i, 5)], drill=dict(m="dp_stock")) for i, c in enumerate(cats)])),
            panel(L("Best next step", "بہترین قدم"),
                  dict(type="hbars", fmt="pkr", items=[dict(l=k, v=v, drill=dict(m="dp_stock", by="item")) for k, v in sorted(rt.items(), key=lambda x: -x[1])]),
                  sub=L("IST → markdown → return to supplier → write-off", "IST → مارک ڈاؤن → واپسی → رائٹ آف"))]))
        out["blocks"].append(dict(cols=1, panels=[panel(L("DP items: biggest value first", "DP آئٹمز"), table(
            "dp_items", [("store_name", L("Store", "اسٹور"), "text"), ("item", L("Item", "آئٹم"), "text"),
                         ("description", L("Description", "تفصیل"), "text"), ("value", L("DP stock", "DP اسٹاک"), "money"),
                         ("age_days", L("Age (days)", "عمر"), "int"), ("bucket", L("Bucket", "بکٹ"), "text"),
                         ("prov_pct", L("Provision %", "پروویژن %"), "pct"), ("provision", L("Provision", "پروویژن"), "money"),
                         ("days_to_next", L("Days to next step", "اگلے مرحلے تک"), "int"),
                         ("extra_provision", L("Extra if not cleared", "اضافی"), "money"), ("route", L("Best next step", "بہترین قدم"), "text"),
                         ("route_why", L("Why", "کیوں"), "text")], rows, action=dict(kind="item"),
            color=lambda r: "warn" if r["days_to_next"] is not None and r["days_to_next"] <= 30 else ""))]))

    def _stock_move(self, ctx, sc, out):
        rows = X.ist(self.db, sc)
        if not rows:
            out["empty"] = L("No transfers found. Needs DP / not-selling stock in one store and the same item out of stock in another.",
                             "کوئی ٹرانسفر نہیں ملا۔")
            return
        out["blocks"].append(dict(cols=1, panels=[panel(L("Move stock between stores (IST)", "اسٹورز کے درمیان منتقلی"), table(
            "ist", [("item", L("Item", "آئٹم"), "text"), ("description", L("Description", "تفصیل"), "text"),
                    ("from_store", L("From", "سے"), "text"), ("to_store", L("To", "کو"), "text"), ("qty", L("Qty", "مقدار"), "num"),
                    ("value", L("Value", "مالیت"), "money"), ("why", L("Why", "کیوں"), "text"),
                    ("sells_per_day", L("Sells/day there", "وہاں روزانہ"), "num")], rows, action=dict(kind="item")),
            sub=L("Quantity = up to 30 days of the receiving store's sales; same region first", "30 دن کی سیلز تک"))]))

    def _stock_blocked(self, ctx, sc, out):
        w, p = sc.store_sql("b.store")
        rows = self.db.qd(f"""SELECT b.*, i.description, s.name store_name FROM blocked_item b LEFT JOIN items i USING (item)
                             LEFT JOIN stores s ON s.code=b.store WHERE b.import_id IN (SELECT max(import_id) FROM imports
                             WHERE report_type='blocked_007' GROUP BY stores) AND {w} ORDER BY value2 DESC NULLS LAST""", p)
        if not rows:
            out["empty"] = L("Import the blocked stock (range 007) report.", "بلاک اسٹاک رپورٹ امپورٹ کریں۔")
            return
        v1, v2 = sum(r["value1"] or 0 for r in rows), sum(r["value2"] or 0 for r in rows)
        out["kpis"].append(dict(key="bl", l=L("Blocked (007) stock", "بلاک اسٹاک"), v=v2, fmt="pkr",
                                sub=L(f"was {fmt_pkr(v1)} · {(1 - v2 / v1) * 100 if v1 else 0:.0f}% cleared", "صاف ہوا")))
        out["blocks"].append(dict(cols=1, panels=[panel(L("Blocked items", "بلاک آئٹمز"), table(
            "bl", [("store_name", L("Store", "اسٹور"), "text"), ("item", L("Item", "آئٹم"), "text"),
                   ("description", L("Description", "تفصیل"), "text"), ("qty1", L("Stock then", "پہلے"), "num"),
                   ("qty2", L("Stock now", "اب"), "num"), ("value2", L("Value now", "مالیت"), "money")], rows, action=dict(kind="item"),
            color=lambda r: "warn" if (r["qty2"] or 0) >= (r["qty1"] or 0) and (r["qty2"] or 0) > 0 else ""),
            sub=L("Amber = not moved at all", "زرد = بالکل نہیں ہلا"))]))

    def _stock_leaflet(self, ctx, sc, out):
        rows = A.leaflet_rows(self.db, sc)
        if not rows:
            out["empty"] = L("Import the leaflet workbook (C&L theme tab).", "لیفلیٹ ورک بک امپورٹ کریں۔")
            return
        out["blocks"].append(dict(cols=1, panels=[panel(L("Leaflet items", "لیفلیٹ آئٹمز"), table(
            "lf", [("store_name", L("Store", "اسٹور"), "text"), ("theme_name", L("Theme", "تھیم"), "text"),
                   ("item", L("Item", "آئٹم"), "text"), ("description", L("Description", "تفصیل"), "text"),
                   ("stock_qty", L("Stock", "اسٹاک"), "num"), ("on_order_qty", L("On order", "آرڈر"), "num"),
                   ("below_cost", L("Below cost", "لاگت سے کم"), "bool")], rows, action=dict(kind="item"),
            color=lambda r: "crit" if r["zero"] and not r["on_order"] else ("warn" if r["below_cost"] else "")))]))

    # -- orders
    def p_orders(self, ctx, sc):
        rows, snap = A.lpo_rows(self.db, sc)
        out = dict(title=L("Orders (LPO)", "آرڈرز"), sub=L("Late deliveries, purged orders and supplier service.",
                                                          "تاخیر، منسوخ آرڈرز اور سپلائر سروس۔"), kpis=[], blocks=[])
        if not rows:
            out["empty"] = L("Import the LPO list (RT LPO tab).", "ایل پی او لسٹ امپورٹ کریں۔")
            return out
        late = [r for r in rows if r["late_days"]]
        kp, _ = A.overview(self.db, sc)
        for k in kp:
            if k.key == "late_lpo":
                out["kpis"].append(kpi(k, drill=dict(m="late_lpo"), tip=self.tips(ctx, "late_lpo")))
        valid = [r for r in rows if not r["deleted"]]
        rec = sum(r["grn_value"] or 0 for r in valid) / (sum(r["value"] or 0 for r in valid) or 1) * 100
        out["kpis"].append(dict(key="recv", l=L("Order value received", "موصول آرڈر مالیت"), v=rec, fmt="pct",
                                status="good" if rec >= 70 else "crit", sub=L("SSL target ≥ 70%", "ہدف ≥ 70%")))
        pur = sum(1 for r in rows if r["deleted"]) / len(rows) * 100
        out["kpis"].append(dict(key="purge", l=L("Purged orders", "منسوخ آرڈرز"), v=pur, fmt="pct", status="good" if pur <= 20 else "crit",
                                sub=L("BC target ≤ 20%", "ہدف ≤ 20%")))
        sup = defaultdict(list)
        for r in rows:
            sup[r["supplier"]].append(r)
        srows = []
        for k, rs in sup.items():
            v = [r for r in rs if not r["deleted"]]
            val = sum(r["value"] or 0 for r in v)
            srows.append(dict(supplier=k, name=rs[0]["supplier_name"] or k, orders=len(rs), value=val,
                              received=sum(r["grn_value"] or 0 for r in v) / val * 100 if val else None,
                              late=sum(1 for r in rs if r["late_days"]), purged=sum(1 for r in rs if r["deleted"])))
        srows.sort(key=lambda r: -r["value"])
        out["blocks"].append(dict(cols=1, panels=[panel(L("Suppliers", "سپلائرز"), table(
            "o_sup", [("name", L("Supplier", "سپلائر"), "name"), ("orders", L("Orders", "آرڈرز"), "int"),
                      ("value", L("Value", "مالیت"), "money"), ("received", L("Received %", "موصول %"), "pct"),
                      ("late", L("Late", "تاخیر"), "int"), ("purged", L("Purged", "منسوخ"), "int")], srows,
            action=dict(kind="supplier"), color=lambda r: "crit" if (r["received"] or 100) < 50 else ""),
            sub=L("Click a supplier for its full view", "سپلائر ویو"))]))
        out["blocks"].append(dict(cols=2, panels=[
            panel(L("Late orders", "تاخیر شدہ آرڈرز"), table(
                "o_late", [("store_name", L("Store", "اسٹور"), "text"), ("lpo_no", "LPO", "text"), ("supplier_name", L("Supplier", "سپلائر"), "text"),
                           ("delivery_date", L("Due", "متوقع"), "date"), ("late_days", L("Days late", "دن تاخیر"), "int"),
                           ("value", L("Value", "مالیت"), "money")], sorted(late, key=lambda r: -(r["value"] or 0)), action=dict(kind="supplier"))),
            panel(L("Purge by store", "اسٹور کے حساب سے پرج"), table(
                "o_purge", [("store", L("Store", "اسٹور"), "text"), ("lpos", L("Orders", "آرڈرز"), "int"), ("purge_pct", L("Purge %", "پرج %"), "pct"),
                            ("received_value_pct", L("Received %", "موصول %"), "pct"), ("late", L("Late", "تاخیر"), "int")],
                A.purge_by_store(rows)))]))
        return out

    # -- promotions
    def p_promos(self, ctx, sc):
        th = X.themes(self.db)
        try:
            from stockcompass.agent import memory as AM
            AM.ensure(self.db)
            known = {x["theme"] for x in th}
            th = th + [dict(theme=u["code"], theme_name=u["name"], date_from=u["date_from"], date_to=u["date_to"], items=len([i for i in (u["items"] or "").split(",") if i.strip()]),
                            user=True, stores_=u["stores"], note=u["note"]) for u in AM.promos(self.db) if u["code"] not in known]
        except Exception:
            pass
        out = dict(title=L("Promotions", "پروموشنز"), sub=L("Is every leaflet and theme item on the shelf, on order and priced to make money?",
                                                           "کیا ہر لیفلیٹ آئٹم شیلف پر ہے؟"), kpis=[], blocks=[])
        if not th:
            out["empty"] = L("Import the leaflet workbook (C&L theme tab).", "لیفلیٹ ورک بک امپورٹ کریں۔")
            return out
        cur = ctx.get("theme") if ctx.get("theme") in [x["theme"] for x in th] else th[0]["theme"]
        out["themes"] = [dict(k=x["theme"], n=x["theme_name"], d0=x["date_from"], d1=x["date_to"], items=x["items"],
                              running=bool(x["date_to"] and x["date_to"] >= date.today())) for x in th]
        out["theme"] = cur
        p = X.promo(self.db, sc, cur)
        cu = next((x for x in th if x["theme"] == cur and x.get("user")), None)
        if cu and not p:
            out["kpis"] = [dict(key="pd", l=L("Promotion period", "مدت"), v=f"{cu['date_from']:%d %b} – {cu['date_to']:%d %b %Y}", fmt="text",
                                sub=L(f"{(cu['date_to'] - cu['date_from']).days + 1} days · stores: {cu.get('stores_') or 'all'}", "")),
                           dict(key="pn", l=L("Logged by", "درج"), v=L("Stock Compass", ""), fmt="text", sub=cu.get("note") or "")]
            out["empty"] = L("This promotion period was logged in Stock Compass. Its items appear here once the leaflet report "
                             "with the same code is imported; ask the Agent to compare sales before, during and after it.", "")
            return out
        if not p:
            out["empty"] = L("No items of this promotion in the selected stores.", "منتخب اسٹورز میں آئٹمز نہیں۔")
            return out
        out["kpis"] = [
            dict(key="ready", l=L("Promo items in stock", "اسٹاک میں پروموشن آئٹمز"), v=p["ready"], fmt="pct",
                 status="good" if p["ready"] >= 95 else ("warn" if p["ready"] >= 88 else "crit"), sub=L("target ≥ 95%", "ہدف ≥ 95%")),
            dict(key="pz", l=L("Zero stock % (promo items)", "زیرو اسٹاک % (پروموشن)"), v=p["zero_pct"], fmt="pct",
                 status="good" if p["zero_pct"] <= 6 else "crit", sub=L("BC target ≤ 6% (hyper)", "بی سی ہدف ≤ 6%")),
            dict(key="pno", l=L("Out of stock, not on order", "آؤٹ آف اسٹاک، آرڈر نہیں"), v=p["zero_not_ordered"], fmt="int",
                 status="crit" if p["zero_not_ordered"] else "good", drill=dict(m="leaflet")),
            dict(key="pbc", l=L("Priced below cost", "لاگت سے کم قیمت"), v=p["below_cost"], fmt="int",
                 status="crit" if p["below_cost"] else "good", sub=L("every sale loses money", "ہر سیل پر نقصان"))]
        if p["promo_sales"]:
            out["kpis"].append(dict(key="psales", l=L("Promo sales so far", "پروموشن سیلز"), v=p["promo_sales"], fmt="pkr"))
        out["blocks"].append(dict(cols=1, panels=[panel(L("Store readiness", "اسٹور کی تیاری"),
                                                        dict(type="hbars", fmt="pct", max=100,
                                                             items=[dict(l=b["store_name"], v=b["ready"],
                                                                         c="var(--good)" if b["ready"] >= 95 else ("var(--warn)" if b["ready"] >= 88 else "var(--crit)"),
                                                                         x=L(f"{b['zero_not_ordered']} out and not ordered", ""),
                                                                         drill=dict(m="leaflet", path=[dict(lvl="store", k=b["store"], n=b["store_name"])]))
                                                                    for b in p["by_store"]]),
                                                        sub=L("Share of this promotion's items in stock", "اسٹاک والے آئٹمز کا حصہ"))]))
        out["blocks"].append(dict(cols=1, panels=[panel(L("Promotion items: problems first", "پروموشن آئٹمز: مسائل پہلے"), table(
            "p_items", [("store_name", L("Store", "اسٹور"), "text"), ("item", L("Item", "آئٹم"), "text"),
                        ("description", L("Description", "تفصیل"), "text"), ("stock_qty", L("Stock", "اسٹاک"), "num"),
                        ("on_order_qty", L("On order", "آرڈر"), "num"), ("issue", L("Problem", "مسئلہ"), "text"),
                        ("pp", L("Cost price", "قیمت خرید"), "money"), ("sp", L("Selling price", "قیمت فروخت"), "money")], p["rows"],
            action=dict(kind="item"), color=lambda r: "crit" if r["issue"] in ("Priced below cost", "Out of stock, not on order") else ("warn" if r["issue"] != "OK" else "")))]))
        return out

    # -- category
    def p_category(self, ctx, sc):
        per = self.period(ctx)
        out = dict(title=L("Category view", "کیٹیگری"), sub=L("Every section's role, return on stock, availability and aged stock.",
                                                             "ہر سیکشن کا کردار اور کارکردگی۔"), kpis=[], blocks=[])
        rows = X.category(self.db, sc, per) if per else []
        if not rows:
            out["empty"] = L("Needs section-level sales (BO 11b section tab or store net sales).", "سیکشن سیلز درکار۔")
            return out
        tot = sum(r["sales"] for r in rows)
        mv = sum(r["sales"] * (r["margin"] or 0) / 100 for r in rows)
        out["kpis"] = [dict(key="cs", l=L("Net sales", "نیٹ سیلز"), v=tot, fmt="pkr", drill=dict(m="sales")),
                       dict(key="cm", l=L("Front margin", "فرنٹ مارجن"), v=mv / tot * 100 if tot else None, fmt="pct"),
                       dict(key="cn", l=L("Sections", "سیکشنز"), v=len(rows), fmt="int")]
        colors = {"traffic": "var(--s2)", "profit": "var(--good)", "dest": "var(--s1)", "occ": "var(--s3)"}
        for r in rows:
            r["section"] = r["key"]
        out["blocks"].append(dict(cols=1, panels=[panel(L("Sections", "سیکشنز"), table(
            "cat", [("name", L("Section", "سیکشن"), "name"), ("role_name", L("Role", "کردار"), "text"),
                    ("sales", L("Net sales", "نیٹ سیلز"), "money"), ("share", L("Share", "حصہ"), "pct"),
                    ("growth", L("Growth", "اضافہ"), "sg"), ("vs_budget", L("vs budget", "بجٹ"), "sg"),
                    ("margin", L("Margin", "مارجن"), "pct_neg"), ("gmroi", "GMROI", "x"), ("zero_pct", L("Zero stock %", "زیرو اسٹاک %"), "pct_chip"),
                    ("dp_value", L("Aged (DP) stock", "ایجڈ اسٹاک"), "money"), ("tail", L("Items for 80% of sales", "80% سیلز"), "text")],
            rows, action=dict(kind="drill", m="sales", lvl="section")),
            sub=L("Traffic = big share, low margin · Profit = small share, margin ≥ 15% · Destination = ≥ 8% of sales",
                  "ٹریفک · منافع · منزل"))]))
        return out

    # -- scorecard
    def p_score(self, ctx, sc):
        s = A.scorecard(self.db)
        out = dict(title=L("BC scorecard", "بی سی اسکور کارڈ"), sub=L("Every BC indicator per store, green when the target is met. Click a cell to see why.",
                                                                     "ہدف پورا ہونے پر سبز۔"), kpis=[], blocks=[])
        if not s:
            out["empty"] = L("Import the BC workbook (summary tab).", "بی سی ورک بک امپورٹ کریں۔")
            return out
        f = ctx.get("fmt") or "H"
        cells = [c for c in s["cells"] if c["format"] == f]
        stores = sorted({(c["store"], c["store_name"]) for c in cells})
        inds = [k for k in s["order"] if any(c["indicator"] == k for c in cells)]
        by = {(c["indicator"], c["store"]): c for c in cells}
        grid = []
        for k in inds:
            c0 = next(c for c in cells if c["indicator"] == k)
            grid.append(dict(k=k, label=c0["label"], target=c0["target"], lo=c0["lower_better"],
                             computed=bool(A.IND.get(k, {}).get("computed")),
                             cells=[dict(v=by[(k, st)]["value"] if (k, st) in by else None,
                                         status=by[(k, st)]["status"] if (k, st) in by else "",
                                         ours=by[(k, st)]["ours"] if (k, st) in by else None,
                                         raw=by[(k, st)]["raw"] if (k, st) in by else "") for st, _ in stores]))
        out["score"] = dict(fmt=f, stores=[dict(k=a, n=b) for a, b in stores], rows=grid,
                            greens=[s["official"].get(a, s["greens"].get(a, 0)) for a, _ in stores],
                            measured=[s["measured"].get(a, 0) for a, _ in stores], as_of=s["as_of"], file=s["file"],
                            diff=s.get("greens_diff") or {})
        return out

    # -- health
    def p_health(self, ctx, sc):
        rows = self.db.qd("""SELECT f.level, f.message, f.count, i.file_name, i.sheet, i.report_type, i.snapshot_date
                             FROM findings f JOIN imports i USING (import_id) WHERE f.code NOT IN ('date_source','columns')
                             ORDER BY CASE f.level WHEN 'error' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END, i.imported_at DESC""")
        out = dict(title=L("Data checks", "ڈیٹا کی جانچ"), sub=L("Everything Stock Compass noticed while reading your files.",
                                                                "فائلیں پڑھتے ہوئے جو کچھ دیکھا۔"), kpis=[], blocks=[])
        if not rows:
            out["empty"] = L("Nothing yet. Import some reports.", "ابھی کچھ نہیں۔")
            return out
        for r in rows:
            r["report"] = REGISTRY[r["report_type"]].name if r["report_type"] in REGISTRY else r["report_type"]
        out["blocks"].append(dict(cols=1, panels=[panel(L("What we found", "کیا ملا"), table(
            "health", [("level", L("Level", "سطح"), "level"), ("message", L("What we found", "کیا ملا"), "text"),
                       ("count", L("Count", "تعداد"), "int"), ("report", L("Report", "رپورٹ"), "text"),
                       ("file_name", L("File", "فائل"), "text"), ("snapshot_date", L("Report date", "تاریخ"), "date")], rows,
            page_size=60))]))
        return out

    # -- import screen data
    def p_import(self, ctx, sc):
        hist = self.db.qd("SELECT import_id, file_name, sheet, report_type, snapshot_date, stores, \"rows\", imported_at, summary "
                          "FROM imports ORDER BY import_id DESC LIMIT 500")
        for h in hist:
            h["report"] = REGISTRY[h["report_type"]].name if h["report_type"] in REGISTRY else h["report_type"]
            h["key"] = h["import_id"]
            st = [x for x in (h["stores"] or "").split(",") if x]
            h["stores"] = ", ".join(st) if len(st) <= 4 else L(f"{len(st)} stores", f"{len(st)} اسٹورز")
        return dict(title=L("Add reports", "رپورٹس شامل کریں"),
                    sub=L("Drop Excel, CSV or text files, or paste data. Stock Compass recognises each sheet and asks only when it is not sure.",
                          "فائلیں ڈالیں؛ اسٹاک کمپاس خود پہچان لے گا۔"),
                    history=table("imports", [("file_name", L("File", "فائل"), "text"), ("sheet", L("Sheet", "شیٹ"), "text"),
                                              ("report", L("Report", "رپورٹ"), "text"), ("snapshot_date", L("Report date", "تاریخ"), "date"),
                                              ("stores", L("Stores", "اسٹورز"), "text"), ("rows", L("Rows", "قطاریں"), "int"),
                                              ("summary", L("Summary", "خلاصہ"), "text")], hist, action=dict(kind="import")))

    def m_delete_imports(self, ctx, import_ids: list):
        return {"ok": True, "deleted": self.db.delete_imports(import_ids or [])}

    def m_delete_import(self, ctx, import_id: int):
        self.db.delete_import(int(import_id))
        return {"ok": True}

    def m_job_done(self, ctx, id: str, done: bool):
        if done:
            self.db.execute("INSERT OR REPLACE INTO job_done VALUES (?,?)", [id, datetime.now()])
        else:
            self.db.execute("DELETE FROM job_done WHERE key=?", [id])
        return {"ok": True}

    # -- settings
    def p_settings(self, ctx, sc):
        db = self.db
        keys = ["sleeping_days_cg", "sleeping_days_nonfood", "low_stock_pcs", "dp_warning_days", "min_items_for_pct",
                "bad_snapshot_drop_pct"]
        labels = {"sleeping_days_cg": L("Not selling, CG (days)", "سی جی (دن)"), "sleeping_days_nonfood": L("Not selling, non-food (days)", "نان فوڈ (دن)"),
                  "low_stock_pcs": L("Low stock under (pcs)", "کم اسٹاک (پیس)"), "dp_warning_days": L("DP early warning (days)", "ڈی پی وارننگ (دن)"),
                  "min_items_for_pct": L("Hide % under (items)", "کم آئٹمز پر % چھپائیں"), "bad_snapshot_drop_pct": L("Broken day: items drop more than (%)", "خراب دن (%)")}
        targets = {(k, f): v for k, f, v in db.q("SELECT indicator, format, target FROM bc_targets")}
        stores = db.store_list(active_only=False)
        unknown = db.qd("SELECT detail FROM findings WHERE code='unknown_store' AND detail IS NOT NULL")
        return dict(title=L("Settings", "سیٹنگز"), sub="",
                    thresholds=[dict(k=k, l=labels[k], v=db.setting(k)) for k in keys],
                    targets=[dict(k=i["key"], l=i["label"], lo=i["lo"], H=targets.get((i["key"], "H")), S=targets.get((i["key"], "S")),
                                  M=targets.get((i["key"], "M"))) for i in BC_INDICATORS],
                    stores=[dict(code=s["code"], name=s["name"], format=s["format"], city=s["city"], region=s["region"],
                                 aliases=", ".join(s["aliases"]), corp=s["corp_codes"]) for s in stores],
                    unknown_names=sorted({n for u in unknown for n in (u["detail"] or "").split("|") if n})[:40],
                    dp_rules=db.qd("SELECT rule_key, from_day, pct, source FROM dp_rules ORDER BY rule_key, from_day"),
                    urdu_font=db.setting("urdu_font") or "Noto Nastaliq Urdu")

    def m_readiness(self, ctx, ai: bool = True):
        """Presentation check: open every screen, drill-down, Analyse view and the AI route the way the app does, and
        report what works and how fast. Also leaves everything warm in the caches."""
        import time as _t
        checks = []

        def run(area, name, fn):
            t0 = _t.time()
            try:
                r = fn()
                err = r.get("error") if isinstance(r, dict) else None
                checks.append(dict(area=area, name=name, ok=not err, ms=round((_t.time() - t0) * 1000), detail=str(err or "")[:200]))
                return r
            except Exception as e:
                checks.append(dict(area=area, name=name, ok=False, ms=round((_t.time() - t0) * 1000), detail=f"{type(e).__name__}: {e}"[:200]))
                return None
        base = {"lang": "en", "compare": "budget", "where": "all", **{k: v for k, v in (ctx or {}).items() if k in ("period", "compare")}}
        names = {"home": "Home", "sales": "Sales", "stock": "Stock health", "orders": "Orders", "promos": "Promotions",
                 "category": "Category", "score": "BC scorecard", "health": "Data checks", "import": "Add reports", "settings": "Settings"}
        for role, label in (("ho", "Head office"), ("dm", "District manager"), ("cd", "Commercial director")):
            for pg, n in names.items():
                if role != "ho" and pg not in ("home", "sales"):
                    continue
                run(f"Screens · {label}", n, lambda pg=pg, role=role: self.m_page({**base, "role": role}, pg))
        for tab in ("zero", "oos", "neg", "sleeping", "dp", "move", "blocked", "leaflet"):
            run("Screens · Stock health tabs", tab, lambda tab=tab: self.m_page({**base, "role": "ho"}, "stock", tab=tab))
        stores = self.db.store_list()
        if stores:
            s0 = stores[0]["code"]
            for role in ("sm", "dh", "sec"):
                run("Screens · Store roles", f"{role} home ({s0})", lambda role=role: self.m_page({**base, "role": role, "where": s0,
                                                                                                    "dept": "01" if role == "dh" else ""}, "home"))
        for m in ("sales", "zero_stock", "oos", "not_on_order", "lost_sales", "negative", "dp_stock", "late_lpo", "leaflet", "sleeping", "bulk"):
            run("Drill-downs", m, lambda m=m: self.m_drill({**base, "role": "ho"}, m, [], None))
        from . import explore as E
        for p in E.PRESETS:
            run("Analyse", p["n"], lambda p=p: self.m_explore({**base, "role": "ho"}, p["dim"], p.get("dim2"), p["m"], {}, 25))
        run("Order advisor", "All stores", lambda: self.m_advisor({**base, "role": "ho"}, "all"))
        it = self.db.one("SELECT item FROM dp_item LIMIT 1") or self.db.one("SELECT item FROM zero_item LIMIT 1")
        if it:
            run("Cards", f"Item {it}", lambda: self.m_item(base, it))
        sup = self.db.one("SELECT i.supplier FROM dp_item d JOIN items i USING (item) WHERE i.supplier IS NOT NULL LIMIT 1") \
            or self.db.one("SELECT code FROM suppliers LIMIT 1")
        if sup:
            run("Cards", f"Supplier {sup}", lambda: self.m_supplier(base, sup))
        if ai:
            svc = self.agent
            route = svc._route(None, "")
            checks.append(dict(area="AI", name="Route", ok=bool(route), ms=0,
                               detail=" → ".join(p.name for p, _ in route[:8]) + (" → " if route else "") + "Stock Compass analysis"))
            run("AI", "First answer", lambda: {"answer": svc.complete("Reply with the single word OK.", max_tokens=20)})
        ok = sum(1 for c in checks if c["ok"])
        return dict(checks=checks, ok=ok, total=len(checks), slowest=sorted(checks, key=lambda c: -c["ms"])[:5])

    def m_save_settings(self, ctx, thresholds: dict | None = None, targets: list | None = None, urdu_font: str | None = None):
        db = self.db
        for k, v in (thresholds or {}).items():
            try:
                db.set_setting(k, int(v))
            except (TypeError, ValueError):
                pass
        lo = {i["key"]: i["lo"] for i in BC_INDICATORS}
        for t_ in targets or []:
            # the screen sends one cell at a time {k, f, v}; older callers send {k, H, S, M}
            cells = [(t_["f"], t_.get("v"))] if "f" in t_ else [(f, t_[f]) for f in "HSM" if f in t_]
            for f, v in cells:
                v = None if v in ("", None) else float(v)
                db.execute("DELETE FROM bc_targets WHERE indicator=? AND format=?", [t_["k"], f])
                db.execute("INSERT INTO bc_targets VALUES (?,?,?,?)", [t_["k"], f, v, lo.get(t_["k"], True)])
        if urdu_font:
            db.set_setting("urdu_font", urdu_font)
        return {"ok": True}

    def m_add_alias(self, ctx, code: str, alias: str):
        if alias and code:
            self.db.execute("INSERT OR REPLACE INTO store_alias VALUES (?,?,?)", [alias.strip().upper(), code, "user"])
        return {"ok": True}


    # ---------------------------------------------------------------------------------- import / export
    def m_import_pick(self, ctx, folder: bool = False):
        self._ai_hook()
        paths = ([self.host.pick_folder()] if folder else self.host.pick_files())
        paths = [p for p in paths if p]
        if paths:
            self.imp.add(paths=paths)
        return self.imp.status()

    # ---------------------------------------------------------------------------------- order advisor
    def m_advisor_meta(self, ctx):
        from stockcompass.analytics import orders as O
        from . import library as LB
        sups = self.db.qd("""SELECT i.supplier AS code, coalesce(max(s.name), i.supplier) AS "name", count(*) AS n FROM items i
                             LEFT JOIN suppliers s ON s.code = i.supplier WHERE i.supplier IS NOT NULL AND i.supplier <> ''
                             GROUP BY i.supplier ORDER BY 2 LIMIT 3000""")
        return dict(steps=LB.steps(self.db, LB.ADVISOR_STEPS), rules=O.rules(self.db), help=O.RULE_HELP, suppliers=sups)

    def m_advisor(self, ctx, store: str | None = None, supplier: str | None = None, dept: str | None = None,
                  section: str | None = None, text: str | None = None, lines: list | None = None):
        """Suggested order (store / supplier / department / section) or a check of a pasted order."""
        from stockcompass.analytics import orders as O
        stores = None if not store or store == "all" else [store]
        proposed = lines or (O.parse_proposed(text, store if store and store != "all" else None) if text else None)
        if text is not None and not proposed:
            return {"error": "No order lines found. Paste item code and quantity (and store) per line, e.g. copied from Excel."}
        if proposed:
            res = self.db.resolver()
            for p in proposed:
                if p["store"] and not self.db.one("SELECT code FROM stores WHERE code=?", [p["store"]]):
                    m = res.resolve(p["store"])
                    p["store"] = m.code if m and m.code else p["store"]
            missing = [p for p in proposed if not p["store"]]
            if missing:
                return {"error": "Choose the store the order is for (or add a Store column to the pasted lines)."}
        out = O.advise(self.db, stores, supplier or None, dept or None, section or None, proposed)
        if not stores and not proposed:           # all stores: a store-by-store summary for the district manager
            by = defaultdict(lambda: dict(order=0, ist=0, stop=0, value=0.0, ist_value=0.0, risk=0.0))
            for l in out["lines"]:
                b = by[l["store"]]
                b["order"] += l["decision"] in ("order", "ist_order")
                b["ist"] += bool(l.get("ist_qty"))
                b["stop"] += l["decision"] == "stop"
                b["value"] += l.get("value") or 0
                b["ist_value"] += (l.get("ist_qty") or 0) * (l.get("cost") or 0)
                b["risk"] += l.get("lost_risk") or 0
            names = Names(self.db)
            out["by_store"] = sorted([dict(store=k, name=names.store.get(k, k), **v) for k, v in by.items()], key=lambda x: -x["value"])
        return out

    def m_advisor_rules(self, ctx, rules: dict):
        from stockcompass.analytics import orders as O
        cur = self.db.setting("order_rules") or {}
        for k, v in (rules or {}).items():
            if k in O.DEFAULT_RULES:
                cur[k] = v
        self.db.set_setting("order_rules", cur)
        return {"rules": O.rules(self.db)}

    # ---------------------------------------------------------------------------------- other data (any imported table)
    def m_data_list(self, ctx):
        from stockcompass.analytics import datasets as D
        from stockcompass.importer.parsers.generic import KINDS, ROLES
        return dict(datasets=D.overview(self.db, self.scope(ctx)), roles=ROLES, kinds=KINDS, scope=self.scope(ctx).label(self.db))

    def m_data_view(self, ctx, key: str, by: str | None = None, where: dict | None = None):
        from stockcompass.analytics import datasets as D
        sc = self.scope(ctx)
        s = D.summary(self.db, key, sc, by)
        if s.get("error"):
            return s
        det = D.detail_rows(self.db, key, sc, 1500, where)
        by_store = []
        if "store" in s["ds"]["has"] and s["ds"]["measures"] and by != "store":
            by_store = D.summary(self.db, key, sc, "store", 200)["rows"]
        imps = self.db.qd(f"""SELECT import_id, file_name, sheet, snapshot_date, stores, "rows", imported_at FROM imports
                              WHERE import_id IN {A.ids_sql(s["ids"])} ORDER BY snapshot_date DESC NULLS LAST""") if s["ids"] else []
        return dict(**{k: v for k, v in s.items() if k != "ids"}, detail=det, by_store=by_store, imports=imps, scope=sc.label(self.db))

    def m_data_column(self, ctx, key: str, name: str, role: str | None = None, kind: str | None = None, label: str | None = None):
        from stockcompass.analytics import datasets as D
        D.set_column(self.db, key, name, role, kind, label)
        return {"ok": True, "note": "Saved: applied to the rows already imported, and to every later file with these columns."}

    def m_data_rename(self, ctx, key: str, name: str):
        from stockcompass.analytics import datasets as D
        D.rename(self.db, key, name)
        return {"ok": True}

    def m_data_hide(self, ctx, key: str, hidden: bool = True):
        from stockcompass.analytics import datasets as D
        D.hide(self.db, key, hidden)
        return {"ok": True}

    def m_data_export(self, ctx, key: str):
        from stockcompass.analytics import datasets as D
        ds = D.get(self.db, key)
        if not ds:
            return {"error": "Unknown dataset"}
        det = D.detail_rows(self.db, key, self.scope(ctx), 1_000_000)
        return self.m_export(ctx, ds["name"][:60], ds["name"], det["cols"], det["rows"])

    # ---------------------------------------------------------------------------------- map & logistics
    def m_map_boot(self, ctx):
        from stockcompass.logistics import costs as C, places as P, plan as PL, tiles as TL
        cfg = C.settings(self.db)
        sups = self.db.qd("""SELECT s.code, s.name FROM suppliers s ORDER BY s.name LIMIT 5000""")
        from stockcompass.logistics.geo import CITIES
        return dict(places=P.all_places(self.db), stores=PL.store_layer(self, ctx), settings=cfg,
                    cities={n: [v[0], v[1]] for n, v in CITIES.items()},
                    suppliers=sups, kinds=P.KINDS, tiles=TL.cached_count(), tile_server=cfg.get("tile_server") or "")

    def m_map_tile(self, ctx, z: int, x: int, y: int):
        from stockcompass.logistics import costs as C, tiles as TL
        cfg = C.settings(self.db)
        b = TL.tile(z, x, y, cfg.get("tile_server") or "", online=bool(cfg.get("online", True)))
        return {"url": TL.data_url(b)} if b else {"none": True}

    def m_map_prefetch(self, ctx, start: bool = True):
        from stockcompass.logistics import costs as C, places as P, tiles as TL
        if start:
            pts = [(p["lat"], p["lng"]) for p in P.all_places(self.db)]
            TL.prefetch(pts, C.settings(self.db).get("tile_server") or "")
        return {**TL.JOB, **TL.cached_count()}

    def m_map_place(self, ctx, kind: str, code: str = "", lat: float | None = None, lng: float | None = None, name: str = "",
                    address: str = "", city: str = "", delete: bool = False):
        from stockcompass.logistics import places as P
        if delete:
            P.delete_place(self.db, kind, code)
            return {"ok": True, "places": P.all_places(self.db)}
        if lat is None and (address or city):
            g = P.geocode(self.db, " ".join(filter(None, [address, city])))
            if not g:
                return {"error": "Could not find that place. Paste a Google Maps link or coordinates, or click on the map."}
            lat, lng = g["lat"], g["lng"]
            src = "you (" + g["how"] + ")"
            p = P.set_place(self.db, kind, code, lat, lng, name, address, city or g.get("city", ""), src, g.get("exact", True))
        else:
            p = P.set_place(self.db, kind, code, lat, lng, name, address, city)
        return {"ok": True, "place": p, "places": P.all_places(self.db)}

    def m_map_locate(self, ctx, text: str):
        from stockcompass.logistics import places as P
        g = P.geocode(self.db, text)
        return g or {"error": "Not found. Paste a Google Maps link, coordinates like 31.52, 74.35, or a city name."}

    def m_map_trip(self, ctx, start: dict, stops: list, vehicle: str | None = None, back: bool = True, optimise: bool = False,
                   cartons: float = 0, value: float = 0):
        from stockcompass.logistics import plan as PL
        if not stops:
            return {"error": "Add at least one stop."}
        return PL.trip(self.db, start, stops, vehicle or None, back, optimise, float(cartons or 0), float(value or 0))

    def m_map_transfers(self, ctx, vehicles: dict | None = None, exclude: list | None = None):
        from stockcompass.logistics import plan as PL
        sc = self.scope(ctx)
        key = ("transfers", sc.dept, sc.section, self.db.stamp(), str(A.AS_OF.get()))
        adv = self._pages.get(key)
        if adv is None:
            from stockcompass.analytics import orders as O
            adv = O.advise(self.db, None, None, sc.dept, sc.section, None, limit=100000)
            with self._pages_lock:
                self._pages[key] = adv
        return PL.transfers(self.db, sc.dept, sc.section, vehicles, exclude, advice=adv)

    def m_map_orders(self, ctx):
        from stockcompass.logistics import plan as PL
        sc = self.scope(ctx)
        return dict(road=PL.orders_on_road(self.db, sc), suppliers=PL.suppliers(self.db, sc))

    def m_map_settings(self, ctx, changes: dict):
        from stockcompass.logistics import costs as C
        return {"settings": C.save_settings(self.db, changes)}

    def m_map_fuel(self, ctx):
        from stockcompass.logistics import costs as C
        return C.fetch_fuel(self.db)

    def m_map_distances(self, ctx):
        from stockcompass.logistics import plan as PL
        return PL.distance_table(self.db)

    # ---------------------------------------------------------------------------------- guided setup / data library
    def m_setup(self, ctx):
        from . import library as LB
        return dict(steps=LB.steps(self.db), library=LB.library(self.db), coverage=LB.coverage(self.db),
                    has_data=bool(self.db.one("SELECT count(*) FROM imports WHERE status='ok'")))

    def m_import_step(self, ctx, key: str, folder: bool = False):
        """Add files for one guided setup step: the importer is told what they are."""
        from . import library as LB
        st = next((x for x in LB.STEPS if x["key"] == key), None)
        self._ai_hook()
        paths = ([self.host.pick_folder()] if folder else self.host.pick_files())
        paths = [p for p in paths if p]
        if paths:
            self.imp.add(paths=paths, hint=(st["title"] + " — " + st["where"]) if st and st["types"] else None)
        return self.imp.status()

    def m_import_add(self, ctx, paths: list | None = None, text: str | None = None):
        self._ai_hook()
        self.imp.add(paths=paths or [], text=text)
        return self.imp.status()

    def _ai_hook(self):
        try:
            self.imp.ai_fn = self.agent.complete if self.agent.ready() else None
        except Exception:
            self.imp.ai_fn = None

    def m_import_status(self, ctx):
        return self.imp.status()

    def m_import_hint(self, ctx, pid: int, hint: str):
        self._ai_hook()
        return self.imp.set_hint(pid, hint)

    def m_import_ai(self, ctx, pid: int | None = None, force: bool = True):
        self._ai_hook()
        return self.imp.ai_check(pid, force)

    def m_import_set(self, ctx, pid: int, si: int, chosen: str | None = None, store: str | None = None,
                     day: str | None = None):
        return self.imp.set(pid, si, chosen=chosen, store=store, day=day)

    def m_import_remove(self, ctx, pid: int):
        return self.imp.remove(pid)

    def m_import_clear(self, ctx):
        return self.imp.clear()

    def m_import_run(self, ctx):
        r = self.imp.run()
        return {**self.imp.status(), **({"missing": r["missing"]} if r.get("missing") else {})}

    def m_export(self, ctx, name: str, title: str = "", cols: list | None = None, rows: list | None = None,
                 table_id: str | None = None):
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in (name or "export")).strip() or "export"
        path = self.host.save_path(f"{safe} {date.today():%Y-%m-%d}.xlsx")
        if not path:
            return {"cancelled": True}
        if table_id and table_id in FULL_TABLES:      # a big table: the screen only had the first rows; write them all
            tcols, trows = FULL_TABLES[table_id]
            wanted = {c["k"] for c in cols or []} or {k for k, _, _ in tcols}
            cols = [dict(k=k, l=l, kind=kind) for k, l, kind in tcols if k in wanted]
            rows = trows
        write_table(path, title or name, cols or [], rows or [], sheet=safe[:31])
        self.host.open_path(path)
        return {"path": path}

    def m_export_jobs(self, ctx):
        sc = self.scope(ctx)
        page = self.p_home({**ctx, "role": ctx.get("role") or "sm"}, sc)
        path = self.host.save_path(f"Action list {date.today():%Y-%m-%d}.xlsx")
        if not path:
            return {"cancelled": True}
        write_jobs(path, page.get("jobs") or [], sc.label(self.db))
        self.host.open_path(path)
        return {"path": path}


    # ---------------------------------------------------------------------------------- agent
    def _who(self, ctx) -> str:
        role = {"cd": "the commercial director", "ho": "the head office category team", "dm": "the district manager", "sm": "the store manager", "dh": "a department head", "sec": "a section manager"}.get(ctx.get("role") or "ho", "head office")
        where = ctx.get("where") or "all"
        return role + ("" if where in ("all", "") else f" (looking at {Names(self.db).store.get(where, where)})")

    def m_agent_config(self, ctx):
        return self.agent.config()

    def m_agent_set_key(self, ctx, provider: str, key: str | None = None, account: str | None = None):
        return self.agent.set_key(provider, key, account)

    def m_agent_prefs(self, ctx, **kw):
        return self.agent.set_prefs(**kw)

    def m_agent_custom_add(self, ctx, name: str, base_url: str, key: str = "", models: str = "", kind: str = "openai"):
        return self.agent.add_custom(name, base_url, key, models, kind)

    def m_agent_custom_remove(self, ctx, provider: str):
        return self.agent.remove_custom(provider)

    def m_agent_test_all(self, ctx, start: bool = True):
        return self.agent.test_all() if start else self.agent.tests

    def m_agent_models(self, ctx, provider: str):
        return self.agent.refresh_models(provider)

    def m_agent_test(self, ctx, provider: str, model: str | None = None):
        return self.agent.test(provider, model)

    def m_agent_upload(self, ctx, name: str, data: str, mime: str = ""):
        return self.agent.upload(name, data, mime)

    def m_agent_upload_path(self, ctx, path: str):
        import base64 as _b64
        p = Path(path)
        if not p.is_file() or p.stat().st_size > 40e6:
            return {"error": "File not found or larger than 40 MB."}
        return self.agent.upload(p.name, _b64.b64encode(p.read_bytes()).decode(), "")

    def m_open_url(self, ctx, url: str):
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            self.host.open_url(url)
        return {"ok": True}

    def m_agent_transcribe(self, ctx, wav: str):
        return self.agent.transcribe(wav)

    def m_agent_send(self, ctx, text: str, chat: str | None = None, attachments: list | None = None, provider: str | None = None,
                     model: str | None = None, effort: str | None = None):
        return self.agent.send(text, chat, attachments, provider, model, effort, ctx=ctx)

    def m_agent_poll(self, ctx, run: str, since: int = 0):
        return self.agent.poll(run, since)

    def m_agent_stop(self, ctx, run: str):
        return self.agent.stop(run)

    def m_agent_approve(self, ctx, run: str, action: str, yes: bool):
        return self.agent.approve(run, action, yes)

    def m_agent_answer(self, ctx, run: str, id: str, answer: str | None = None):
        return self.agent.answer(run, id, answer)

    def m_agent_glossary(self, ctx):
        from stockcompass.agent import memory as AM
        return {"glossary": [dict(g, ts=str(g["ts"])[:16]) for g in AM.glossary(self.db, 1000)]}

    def m_agent_define(self, ctx, term: str, meaning: str):
        from stockcompass.agent import memory as AM
        AM.define(self.db, term, meaning)
        return self.m_agent_glossary(ctx)

    def m_agent_chats(self, ctx):
        return {"chats": self.agent.chats()}

    def m_agent_chat(self, ctx, chat: str):
        return self.agent.chat(chat)

    def m_agent_chat_rename(self, ctx, chat: str, title: str):
        from stockcompass.agent import memory as AM
        AM.rename_chat(self.db, chat, title)
        return {"ok": True}

    def m_agent_chat_delete(self, ctx, chat: str):
        from stockcompass.agent import memory as AM
        AM.delete_chat(self.db, chat)
        return {"ok": True}

    def m_agent_memory(self, ctx):
        from stockcompass.agent import memory as AM
        self.agent
        return {"memory": [dict(m, ts=str(m["ts"])[:16]) for m in AM.memories(self.db, 500)],
                "log": [dict(r, ts=str(r["ts"])[:16]) for r in self.db.qd("SELECT * FROM agent_log ORDER BY ts DESC LIMIT 100")]}

    def m_agent_memory_add(self, ctx, text: str, pinned: bool = True):
        from stockcompass.agent import memory as AM
        self.agent
        AM.remember(self.db, text, "note", "", "user", pinned)
        return self.m_agent_memory(ctx)

    def m_agent_memory_delete(self, ctx, id: str):
        from stockcompass.agent import memory as AM
        AM.forget(self.db, id)
        return self.m_agent_memory(ctx)

    def m_agent_import_attachment(self, ctx, id: str):
        return self.agent.import_attachment(id)

    def m_agent_open(self, ctx, path: str):
        from stockcompass.paths import exports_dir
        p = Path(path).resolve()
        if exports_dir().resolve() not in p.parents:
            return {"error": "Only files the agent created can be opened here."}
        self.host.open_path(str(p))
        return {"ok": True}

    # ---------------------------------------------------------------------------------- offline models
    def m_local_state(self, ctx, detect: bool = False):
        from stockcompass.agent import local as LO
        return dict(catalogue=LO.CATALOGUE, installed=LO.installed(), downloads=LO.DOWNLOADS.list(), runtime=LO.runtime_status(),
                    server=LO.SERVER.status(), whisper=LO.whisper_models(), local_apps=LO.detect_local() if detect else None,
                    folder=str(LO.models_dir()))

    def m_local_search(self, ctx, query: str = "", mode: str = "gguf"):
        from stockcompass.agent import local as LO
        self.agent.key("huggingface")
        return {"results": LO.search_hf(query, mode=mode), "mode": mode}

    def m_local_files(self, ctx, repo: str):
        from stockcompass.agent import local as LO
        self.agent.key("huggingface")
        return {"repo": repo, "files": LO.repo_files(repo)}

    def m_local_download(self, ctx, repo: str, file: str):
        from stockcompass.agent import local as LO
        return {"job": LO.download_model(repo, file)}

    def m_local_cancel(self, ctx, job: str):
        from stockcompass.agent import local as LO
        LO.DOWNLOADS.cancel(job)
        return {"ok": True}

    def m_local_delete(self, ctx, path: str):
        from stockcompass.agent import local as LO
        if LO.SERVER.status()["path"] == path:
            LO.SERVER.stop()
        return LO.delete_model(path)

    def m_local_link(self, ctx):
        from stockcompass.agent import local as LO
        files = self.host.pick_files("gguf")
        linked = [LO.link_file(f) for f in files if f.lower().endswith(".gguf")]
        return {"linked": linked}

    def m_local_runtime(self, ctx, kind: str = "llama", variant: str = "cpu"):
        from stockcompass.agent import local as LO
        return {"job": LO.install_runtime(kind, variant)}

    def m_local_load(self, ctx, path: str, ctx_size: int = 8192):
        from stockcompass.agent import local as LO
        st = LO.SERVER.start(path, ctx_size)
        self.agent.set_prefs(provider="offline", model=Path(path).name)
        self.agent.warmup()
        return st

    def m_local_unload(self, ctx):
        from stockcompass.agent import local as LO
        LO.SERVER.stop()
        return LO.SERVER.status()

    def m_local_ollama_pull(self, ctx, name: str):
        from stockcompass.agent import local as LO
        return {"job": LO.ollama_pull(name)}

    def m_local_whisper(self, ctx, id: str):
        from stockcompass.agent import local as LO
        return {"job": LO.download_whisper(id)}


def _col(k: str) -> str:
    from stockcompass.i18n import col
    return col(k)


def fmt_val(v, kind: str) -> str:
    if v is None:
        return "—"
    if kind in ("pkr", "money"):
        return fmt_pkr(v)
    if kind in ("pct",):
        return f"{v:.1f}%"
    if kind == "sg":
        return f"{v:+.1f}%"
    if kind == "int":
        return f"{v:,.0f}"
    return str(v)
