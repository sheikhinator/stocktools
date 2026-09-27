"""What the agent can do inside Stock Compass.

Read tools see everything the screens see (and the raw tables). Write tools change settings, targets,
promotion periods and store names; they need the user's approval unless 'Ask before changes' is off.
Results are compacted so a model with a small context can still use them.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any, Callable

from stockcompass.analytics.core import L
from stockcompass.master.seed import BC_INDICATORS

from . import memory as M

MAX_ROWS = 40

# ------------------------------------------------------------------------------------------------ table guide
TABLE_GUIDE = {
    "stores": "Store master. code = GIMA store code (500, 502, P03, PA6...), name, format H/S/M (hyper/super/Myli), city, region.",
    "items": "Item master: item code, description, dept (01 CG, 02 FFD, 03 LHH, 04 HHH, 05 TXT), section, family, supplier, brand.",
    "sections": "Section master: code (e.g. 011), dept, name.",
    "suppliers": "Supplier code and name.",
    "imports": "Every imported sheet: import_id, file_name, sheet, report_type, snapshot_date, period_from/to, stores, rows, status, summary.",
    "stock_item": "GIMA RealTime stock per store × item: qty, cost, price, status (AC active, NC not active, NI not in inventory), snap_date.",
    "sales_item": "Item sales from the BO benchmark: store, item, date_from, date_to, sales (PKR ex tax), qty, margin, stock.",
    "zero_item": "GIMA zero stock sheet: items out of stock per store with days_out, dlyavg (sells/day), reason, open_lpo, delivery_date.",
    "negative_item": "GIMA negative stock items: store, item, qty (<0), status.",
    "dp_item": "Aged / DP stock per store × item: qty, cost, value, age_days, provision, prov_pct, bucket.",
    "lpo": "Purchase orders (LPO): store, lpo_no, lpo_date, delivery_date, value, grn_value (received), status (EM open, BV/RE received), deleted, supplier.",
    "leaflet_item": "Promotion / leaflet items: theme (code), theme_name, date_from, date_to, store, item, stock_qty, on_order_qty, pp (cost), sp (promo price).",
    "blocked_item": "Blocked (007) items with stock.",
    "zs_daily": "BO 500-30-15 zero stock summary by day: day, store, level (store/dept/section), dept, section, zero_items, total_items, suspect (broken day).",
    "bc_value": "BC scorecard values per store × indicator as printed by the BC team.",
    "bc_targets": "BC targets: indicator, format (H/S/M), target, lower_better.",
    "sales_block": "BO 11b/net sales: source, period (DAY/MTD/YTD), level, date_to, store, dept, section, sales, budget, ly_sales, margin_pct, qty, oos_pct, stock_value.",
    "sales_fss": "BO 11f family × supplier × store sales: period, store, section, family, supplier, sales_cy, sales_ly, margin_pct, b2b_cy, promo_pct, stock_value.",
    "sales_family": "BO family sales year on year.",
    "findings": "Data checks: problems found while reading each import.",
    "user_promo": "Promotion periods logged by the user or the agent: code, name, date_from, date_to, stores, items, note.",
    "agent_memory": "The agent's long-term memory notes.",
}

_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|copy|attach|detach|install|load|pragma|export|import|call|set|"
                        r"truncate|vacuum|checkpoint|grant|begin|commit|rollback)\b", re.I)


def _r(v):
    if isinstance(v, float):
        return round(v, 2) if abs(v) < 1e6 else round(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10] if isinstance(v, date) and not isinstance(v, datetime) else str(v)[:16]
    return v


def _rows(rows: list[dict], cols: list[str] | None = None, n: int = MAX_ROWS) -> dict:
    out = [{k: _r(r.get(k)) for k in (cols or list(r.keys())) if not str(k).startswith("_")} for r in rows[:n]]
    return {"rows": out, "total_rows": len(rows), **({"note": f"showing first {n} of {len(rows)}"} if len(rows) > n else {})}


# ------------------------------------------------------------------------------------------------ compacting screens
def compact_body(b: dict) -> dict:
    t = b.get("type")
    if t == "table":
        cols = b["cols"]
        rows = [{c["l"]: _r(r.get(c["k"])) for c in cols} | ({"item_code": r["item"]} if r.get("item") else {}) for r in b["rows"][:MAX_ROWS]]
        return {"table": rows, "total_rows": len(b["rows"])}
    if t == "line":
        xs = b["xs"]
        step = max(1, len(xs) // 31)
        return {"line": {s["n"]: {x: _r(v) for x, v in list(zip(xs, s["v"]))[::step]} for s in b["series"]}, "unit": b.get("fmt")}
    if t == "bar":
        return {"bars": {s["n"]: {c["l"]: _r(v) for c, v in zip(b["cats"], s["v"])} for s in b["series"]}, "unit": b.get("fmt")}
    if t == "waterfall":
        return {"bridge": {"start": _r(b["start"]), "steps": {i["l"]: _r(i["v"]) for i in b["items"]}, "end": _r(b["end"])}}
    if t == "hbars":
        return {"ranking": {i["l"]: _r(i["v"]) for i in b["items"]}, "unit": b.get("fmt")}
    if t == "scatter":
        return {"points": [{"name": p["n"], "growth_pct": _r(p["x"]), "margin_pct": _r(p["y"]), "sales": _r(p["s"])} for p in b["pts"][:30]]}
    if t == "heat":
        return {"grid": {r["n"]: {c["n"]: _r(v) for c, v in zip(b["cols"], b["cells"][i])} for i, r in enumerate(b["rows"])}, "target": b.get("target")}
    if t in ("empty", "note"):
        return {"note": b.get("text")}
    return {}


def compact_page(d: dict) -> dict:
    out: dict[str, Any] = {"title": d.get("title"), "scope": d.get("scope")}
    if d.get("error"):
        return {"error": d["error"]}
    if d.get("empty"):
        out["empty"] = d["empty"]
    if d.get("kpis"):
        out["kpis"] = [{"name": k.get("l"), "value": _r(k.get("v")), "unit": k.get("fmt"), "detail": k.get("sub"),
                        "status": k.get("status"), "as_of": k.get("period"), "top_contributors": (k.get("tip") or [])[1:]}
                       for k in d["kpis"]]
    if d.get("insights"):
        out["insights"] = [{"level": i.get("level"), "title": i.get("title"), "text": i.get("text")} for i in d["insights"]]
    if d.get("jobs"):
        out["jobs"] = [{"job": j["title"], "why": j["why"], "items": j["count"], "value": _r(j.get("value"))} for j in d["jobs"]]
    for blk in d.get("blocks") or []:
        for p in blk.get("panels") or []:
            out.setdefault("panels", []).append({"title": p.get("title"), **compact_body(p.get("body") or {})})
    if d.get("tabs"):
        out["tabs"] = [t["k"] for t in d["tabs"]]
    if d.get("themes"):
        out["promotions"] = d["themes"]
    if d.get("score"):
        s = d["score"]
        out["scorecard"] = {"format": s["fmt"], "as_of": s.get("as_of"),
                            "greens": {st["n"]: f"{g}/{m}" for st, g, m in zip(s["stores"], s["greens"], s["measured"])},
                            "cells": {r["label"]: {st["n"]: (c.get("raw") or _r(c.get("v")), c.get("status")) for st, c in zip(s["stores"], r["cells"])}
                                      for r in s["rows"]}}
    if d.get("notes"):
        out["notes"] = d["notes"]
    if d.get("history"):
        out["imports"] = compact_body(d["history"])
    return out


# ------------------------------------------------------------------------------------------------ the tools
SCOPE_PROPS = {
    "where": {"type": "string", "description": "Store name or GIMA code (e.g. 'Emporium', '504'), a format 'fmt:H'/'fmt:S'/'fmt:M', a region 'reg:Lahore', or 'all'."},
    "dept": {"type": "string", "description": "Department code 01 CG, 02 FFD, 03 LHH, 04 HHH, 05 TXT, or 'NF' for all non-food."},
    "section": {"type": "string", "description": "Section code, e.g. '011' (Beverages)."},
    "period": {"type": "string", "enum": ["DAY", "WTD", "MTD", "YTD"], "description": "Sales period (default month to date)."},
    "compare": {"type": "string", "enum": ["budget", "ly"], "description": "Compare sales with budget or last year."},
}

CHART_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["bar", "line", "hbar", "table"], "description": "bar = columns, line = trend over time, hbar = ranking, table = plain table"},
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "labels": {"type": "array", "items": {"type": "string"}, "description": "Category or date labels (dates as YYYY-MM-DD)."},
        "series": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "values": {"type": "array", "items": {"type": ["number", "null"]}}}, "required": ["name", "values"]}},
        "unit": {"type": "string", "enum": ["pkr", "pct", "int", "num"], "description": "How to show values."},
    },
    "required": ["type", "title", "labels", "series"],
}


def tool_specs() -> list[dict]:
    return [
        {"name": "data_overview", "write": False,
         "description": "What data is loaded: every report with its date and stores, the stores list, departments, sales periods, and today's date. Call this first when unsure what is available.",
         "parameters": {"type": "object", "properties": {}}},
        {"name": "screen", "write": False,
         "description": "Read any Stock Compass screen exactly as the user sees it (KPIs, insights, tables, charts). pages: home, sales, stock (tabs: zero, oos, neg, sleeping, dp, move, blocked, leaflet), orders, promos (theme = promotion code), category, score (fmt H/S/M), health (data checks), import (history).",
         "parameters": {"type": "object", "properties": {"page": {"type": "string", "enum": ["home", "sales", "stock", "orders", "promos", "category", "score", "health", "import"]},
                                                         "tab": {"type": "string"}, "theme": {"type": "string"}, "fmt": {"type": "string"}, **SCOPE_PROPS}, "required": ["page"]}},
        {"name": "drill", "write": False,
         "description": "Break a number down: store → dept → section → family → supplier → item. metric: sales, zero_stock, not_on_order, oos, lost_sales, negative, dp_stock, late_lpo, leaflet, sleeping, bulk. path narrows it, e.g. [{\"lvl\":\"store\",\"k\":\"503\"},{\"lvl\":\"dept\",\"k\":\"01\"}]. by forces the grouping level.",
         "parameters": {"type": "object", "properties": {"metric": {"type": "string"}, "path": {"type": "array", "items": {"type": "object", "properties": {"lvl": {"type": "string"}, "k": {"type": "string"}}}},
                                                         "by": {"type": "string", "enum": ["store", "dept", "section", "family", "supplier", "item"]}, **SCOPE_PROPS}, "required": ["metric"]}},
        {"name": "find", "write": False,
         "description": "Find items (by code or words in the description), suppliers and stores. Use it to turn a name like 'Dettol 500ml' into item codes.",
         "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
        {"name": "item_status", "write": False,
         "description": "Everything about one item: stock by store, price, cost, margin, out-of-stock reason and order, sales, aged/DP, negative stock, leaflet. Optionally only one store.",
         "parameters": {"type": "object", "properties": {"item": {"type": "string", "description": "Item code (or words to search)."}, "store": {"type": "string"}}, "required": ["item"]}},
        {"name": "supplier_status", "write": False,
         "description": "A supplier's sales, delivery (received %), purged orders, late orders, out-of-stock items and aged stock.",
         "parameters": {"type": "object", "properties": {"supplier": {"type": "string", "description": "Supplier code or name."}, **SCOPE_PROPS}, "required": ["supplier"]}},
        {"name": "describe_tables", "write": False,
         "description": "List database tables with what they mean and their columns, before writing SQL.",
         "parameters": {"type": "object", "properties": {"tables": {"type": "array", "items": {"type": "string"}}}}},
        {"name": "sql", "write": False,
         "description": "Run one read-only SQL query (DuckDB dialect: SELECT or WITH) on the Stock Compass database for anything the screens do not show. Returns at most 200 rows; aggregate in SQL.",
         "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
        {"name": "recall", "write": False,
         "description": "Search long-term memory: notes the user asked to remember, earlier conclusions and the automatic digest saved after every import.",
         "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
        {"name": "remember", "write": False,
         "description": "Save a fact to long-term memory (user preferences, explanations the user gave, important findings with dates).",
         "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "tags": {"type": "string"}, "pinned": {"type": "boolean"}}, "required": ["text"]}},
        {"name": "chart", "write": False,
         "description": "Show a chart or table in the chat. Use real numbers from tools. Keep to one idea per chart.",
         "parameters": CHART_SCHEMA},
        {"name": "make_report", "write": False,
         "description": "Create a formatted report file (PDF, Word, Excel and/or HTML) with a title, an executive summary, sections of markdown text, charts and tables. Use real numbers from tools.",
         "parameters": {"type": "object", "properties": {
             "title": {"type": "string"}, "subtitle": {"type": "string"},
             "summary": {"type": "string", "description": "Executive summary in markdown (3-6 bullets)."},
             "sections": {"type": "array", "items": {"type": "object", "properties": {
                 "heading": {"type": "string"}, "text": {"type": "string", "description": "Markdown."},
                 "chart": CHART_SCHEMA,
                 "table": {"type": "object", "properties": {"columns": {"type": "array", "items": {"type": "string"}}, "rows": {"type": "array", "items": {"type": "array"}}}}},
                 "required": ["heading"]}},
             "formats": {"type": "array", "items": {"type": "string", "enum": ["pdf", "docx", "xlsx", "html"]}}},
             "required": ["title", "sections"]}},
        {"name": "open_screen", "write": False,
         "description": "Open a Stock Compass screen for the user (and set its filters).",
         "parameters": {"type": "object", "properties": {"page": {"type": "string"}, "tab": {"type": "string"}, **SCOPE_PROPS}, "required": ["page"]}},
        # ---------------------------------------------------------------- changes (need approval)
        {"name": "add_promotion", "write": True,
         "description": "Log a promotion period (code, name, dates, stores, items) so it appears in Promotions and can be analysed before/during/after.",
         "parameters": {"type": "object", "properties": {"code": {"type": "string"}, "name": {"type": "string"},
                                                         "date_from": {"type": "string", "description": "YYYY-MM-DD"}, "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                                                         "stores": {"type": "string", "description": "Comma-separated store codes or names; empty = all."},
                                                         "items": {"type": "string", "description": "Comma-separated item codes (optional)."},
                                                         "note": {"type": "string"}}, "required": ["code", "name", "date_from", "date_to"]}},
        {"name": "delete_promotion", "write": True, "description": "Remove a promotion period that was logged in Stock Compass.",
         "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
        {"name": "set_bc_target", "write": True,
         "description": "Change a BC target for a store format. indicator keys: " + ", ".join(i["key"] for i in BC_INDICATORS),
         "parameters": {"type": "object", "properties": {"indicator": {"type": "string"}, "format": {"type": "string", "enum": ["H", "S", "M"]},
                                                         "target": {"type": ["number", "null"]}}, "required": ["indicator", "format", "target"]}},
        {"name": "set_threshold", "write": True,
         "description": "Change a threshold: sleeping_days_cg, sleeping_days_nonfood, low_stock_pcs, dp_warning_days, min_items_for_pct, bad_snapshot_drop_pct.",
         "parameters": {"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "number"}}, "required": ["key", "value"]}},
        {"name": "add_store_name", "write": True,
         "description": "Teach Stock Compass another name for a store (used when reading reports).",
         "parameters": {"type": "object", "properties": {"store": {"type": "string", "description": "GIMA code"}, "name": {"type": "string"}}, "required": ["store", "name"]}},
    ]


def describe_change(name: str, a: dict) -> str:
    if name == "add_promotion":
        return f"Log promotion {a.get('code')} '{a.get('name')}' from {a.get('date_from')} to {a.get('date_to')}" + (f" in {a['stores']}" if a.get("stores") else " in all stores")
    if name == "delete_promotion":
        return f"Delete logged promotion {a.get('code')}"
    if name == "set_bc_target":
        return f"Set BC target '{a.get('indicator')}' for format {a.get('format')} to {a.get('target')}"
    if name == "set_threshold":
        return f"Set threshold {a.get('key')} to {a.get('value')}"
    if name == "add_store_name":
        return f"Add '{a.get('name')}' as a name for store {a.get('store')}"
    return f"{name} {json.dumps(a)}"


class Toolbox:
    """Runs tools against the live data service (web.api.Api)."""

    def __init__(self, api, emit: Callable[[dict], None] | None = None, chat_id: str = "", report_fn=None):
        self.api = api
        self.db = api.db
        self.emit = emit or (lambda ev: None)
        self.chat_id = chat_id
        self.report_fn = report_fn
        self._resolver = None

    # -------------------------------------------------------------- helpers
    def store(self, ref: str | None) -> str | None:
        if not ref or str(ref).lower() in ("all", "pakistan", "country", "all stores"):
            return None
        ref = str(ref).strip()
        if ref.startswith(("fmt:", "reg:")):
            return ref
        if self._resolver is None:
            self._resolver = self.db.resolver()
        m = self._resolver.resolve(ref)
        return m.code if m and m.code else ref

    def ctx(self, a: dict) -> dict:
        c = {"lang": "en", "role": "ho", "where": self.store(a.get("where")) or "all"}
        for k in ("dept", "section", "period", "compare"):
            if a.get(k):
                c[k] = str(a[k])
        if c.get("section") and c["section"].upper().startswith("S") and c["section"][1:].isdigit():
            c["section"] = c["section"][1:]
        return c

    def call(self, name: str, args: dict) -> dict:
        fn = getattr(self, "t_" + name, None)
        if fn is None:
            return {"error": f"Unknown tool {name}"}
        try:
            return fn(**(args or {}))
        except TypeError as e:
            return {"error": f"Wrong arguments for {name}: {e}"}
        except Exception as e:  # tell the model; it can try another way
            return {"error": f"{type(e).__name__}: {e}"}

    # -------------------------------------------------------------- read tools
    def t_data_overview(self, **_):
        db = self.db
        imps = db.qd("""SELECT report_type, count(*) sheets, max(snapshot_date) latest, min(snapshot_date) first_date,
                               max(period_to) period_to, string_agg(DISTINCT stores, ',') stores, sum("rows") rows_
                        FROM imports WHERE status='ok' GROUP BY 1 ORDER BY latest DESC NULLS LAST""")
        from stockcompass.importer.spec import REGISTRY
        for r in imps:
            r["report"] = REGISTRY[r["report_type"]].name if r["report_type"] in REGISTRY else r["report_type"]
            st = sorted({s for s in (r.pop("stores") or "").split(",") if s})
            r["stores"] = len(st)
        return {"today": date.today().isoformat(),
                "reports": _rows(imps, ["report", "report_type", "sheets", "first_date", "latest", "period_to", "stores", "rows_"], 60),
                "stores": [f"{s['code']} {s['name']} ({s['format']}, {s['region']})" for s in db.store_list()],
                "departments": [f"{c} {n}" for c, n in db.q("SELECT code, name FROM departments ORDER BY 1")],
                "sections": len(db.q("SELECT 1 FROM sections")), "items": db.one("SELECT count(*) FROM items", default=0),
                "sales_periods": [dict(period=p["p"], latest=str(p["d"])) for p in self.api.m_boot({})["periods"]],
                "logged_promotions": [dict(code=p["code"], name=p["name"], date_from=_r(p["date_from"]), date_to=_r(p["date_to"])) for p in M.promos(db)]}

    def t_screen(self, page: str, tab: str | None = None, theme: str | None = None, fmt: str | None = None, **a):
        c = self.ctx(a)
        extra = {k: v for k, v in (("tab", tab), ("theme", theme), ("fmt", fmt)) if v}
        return compact_page(self.api.m_page(c, page, **extra))

    def t_drill(self, metric: str, path: list | None = None, by: str | None = None, **a):
        c = self.ctx(a)
        path = [dict(p, k=(self.store(p.get("k")) if p.get("lvl") == "store" else str(p.get("k"))), n=p.get("n") or str(p.get("k"))) for p in (path or [])]
        d = self.api.m_drill(c, metric, path, by)
        if d.get("error"):
            return d
        cols = [x["k"] for x in d["cols"]]
        return {"metric": d["title"], "unit": d["fmt"], "total": _r(d["total"]), "grouped_by": d["by"], "next_level": d.get("next"),
                "scope": d.get("scope"), "path": [p.get("n") for p in path], "source": d.get("source"),
                "columns": {x["k"]: x["l"] for x in d["cols"]},
                **_rows([{"key": r.get("k"), **{k: r.get(k) for k in cols}, **({"sub": r["sub"]} if r.get("sub") else {})} for r in d["rows"]], n=60)}

    def t_find(self, query: str, **_):
        q = (query or "").strip()
        res = self.api.m_search({}, q).get("results", [])
        words = [w for w in re.findall(r"\w+", q.upper()) if len(w) > 1]
        if words:
            cond = " AND ".join(["upper(description) LIKE ?"] * len(words))
            more = self.db.qd(f"SELECT item, description, section, supplier FROM items WHERE {cond} LIMIT 25", [f"%{w}%" for w in words])
            seen = {r["k"] for r in res if r["t"] == "item"}
            res += [dict(t="item", k=m["item"], n=f"{m['item']} {m['description']} (section {m['section']}, supplier {m['supplier']})")
                    for m in more if m["item"] not in seen]
        return {"results": res[:40]}

    def t_item_status(self, item: str, store: str | None = None, **_):
        code = str(item).strip()
        if not self.db.one("SELECT 1 FROM items WHERE item=?", [code]):
            hits = [r for r in self.t_find(code)["results"] if r["t"] == "item"]
            if not hits:
                return {"error": f"No item matches '{item}'."}
            if len(hits) > 1:
                return {"several_matches": hits[:15], "hint": "Ask which one, or call item_status with the item code."}
            code = hits[0]["k"]
        d = self.api.m_item({}, code)
        st = self.store(store) if store else None
        keep = (lambda rs: [r for r in rs if r.get("store") == st]) if st else (lambda rs: rs)
        return {"item": {k: _r(v) for k, v in (d.get("item") or {}).items() if v is not None}, "section": d.get("section"),
                "supplier": d.get("supplier_name"), "price_incl_tax": _r(d.get("price")), "cost": _r(d.get("cost")), "margin_pct": _r(d.get("margin")),
                "what_to_do": d.get("rec"), "store_filter": st,
                "stock_by_store": _rows(keep(d["stock"]), ["store", "store_name", "qty", "status", "snap_date"], 30),
                "out_of_stock": _rows(keep(d["zero"]), ["store_name", "snap_date", "days_out", "dlyavg", "reason", "open_lpo", "delivery_date"], 30),
                "sales": _rows(keep(d["sales"]), ["store_name", "date_from", "date_to", "sales", "qty", "margin", "stock"], 30),
                "aged_dp": _rows(keep(d["dp"]), ["store_name", "qty", "value", "age_days", "provision", "bucket"], 30),
                "negative": _rows(keep(d["negative"]), ["store_name", "qty", "status", "snap_date"], 30),
                "leaflet": _rows(keep(d["leaflet"]), ["store_name", "theme", "theme_name", "stock_qty", "on_order_qty", "pp", "sp"], 30)}

    def t_supplier_status(self, supplier: str, **a):
        code = str(supplier).strip()
        if not self.db.one("SELECT 1 FROM suppliers WHERE code=?", [code]):
            m = self.db.qd("SELECT code, name FROM suppliers WHERE upper(name) LIKE ? LIMIT 10", [f"%{code.upper()}%"])
            if not m:
                return {"error": f"No supplier matches '{supplier}'."}
            if len(m) > 1:
                return {"several_matches": m}
            code = m[0]["code"]
        d = self.api.m_supplier(self.ctx(a), code)
        return {"supplier": d.get("name"), "code": code, "scope": d.get("scope"),
                "kpis": [{"name": k["l"], "value": _r(k["v"]), "unit": k["fmt"], "detail": k.get("sub")} for k in d.get("kpis") or []],
                "panels": [{"title": p["title"], **compact_body(p["body"])} for p in d.get("blocks") or []]}

    def t_describe_tables(self, tables: list | None = None, **_):
        cols = self.db.q("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema='main' ORDER BY table_name, ordinal_position")
        by: dict[str, list] = {}
        for t, c, ty in cols:
            by.setdefault(t, []).append(f"{c} {ty}")
        want = [t for t in (tables or TABLE_GUIDE.keys()) if t in by]
        return {t: {"meaning": TABLE_GUIDE.get(t, ""), "columns": by[t],
                    "rows": self.db.one(f'SELECT count(*) FROM "{t}"', default=0)} for t in want}

    def t_sql(self, query: str, **_):
        q = (query or "").strip().rstrip(";")
        if ";" in q or not re.match(r"^\s*(select|with|describe|show|summarize|from)\b", q, re.I) or _FORBIDDEN.search(re.sub(r"'[^']*'", "''", q)):
            return {"error": "Only one read-only SELECT/WITH query is allowed."}
        with self.db.lock:
            cur = self.db.con.execute(q)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(201)
        data = [dict(zip(cols, r)) for r in rows[:200]]
        return {"columns": cols, "rows": [{k: _r(v) for k, v in r.items()} for r in data], "truncated": len(rows) > 200}

    def t_recall(self, query: str, **_):
        return {"memories": M.recall(self.db, query, 10)}

    def t_remember(self, text: str, tags: str = "", pinned: bool = False, **_):
        mid = M.remember(self.db, text, "note", tags, "agent", bool(pinned))
        self.emit({"type": "memory", "text": text})
        return {"saved": mid}

    def t_chart(self, **spec):
        body = chart_body(spec)
        self.emit({"type": "chart", "title": spec.get("title"), "sub": spec.get("subtitle") or "", "body": body})
        return {"shown": True, "note": "The chart is shown to the user; do not repeat all its numbers."}

    def t_make_report(self, **spec):
        if not self.report_fn:
            return {"error": "Reports are not available here."}
        files = self.report_fn(spec)
        self.emit({"type": "report", "title": spec.get("title"), "files": files})
        return {"created": [f["name"] for f in files], "note": "The files are shown to the user with open buttons."}

    def t_open_screen(self, page: str, tab: str | None = None, **a):
        c = self.ctx(a)
        self.emit({"type": "navigate", "page": page, "tab": tab, "where": c.get("where"), "dept": c.get("dept", ""), "section": c.get("section", "")})
        return {"opened": page}

    # -------------------------------------------------------------- write tools (run after approval)
    def t_add_promotion(self, code: str, name: str, date_from: str, date_to: str, stores: str = "", items: str = "", note: str = "", **_):
        d0, d1 = date.fromisoformat(date_from[:10]), date.fromisoformat(date_to[:10])
        if d1 < d0:
            return {"error": "date_to is before date_from"}
        st = ",".join(filter(None, (self.store(s.strip()) for s in stores.split(",")))) if stores else ""
        M.save_promo(self.db, code.strip().upper(), name.strip(), d0, d1, st, items, note)
        M.log(self.db, "add_promotion", dict(code=code, name=name, date_from=date_from, date_to=date_to, stores=st), self.chat_id)
        M.remember(self.db, f"Promotion {code} '{name}' logged: {d0} to {d1}" + (f" in {st}" if st else " in all stores") + (f". {note}" if note else ""), "event", "promotion", "agent")
        return {"ok": True, "code": code.upper(), "stores": st or "all"}

    def t_delete_promotion(self, code: str, **_):
        n = M.delete_promo(self.db, code.strip().upper())
        M.log(self.db, "delete_promotion", {"code": code}, self.chat_id)
        return {"ok": bool(n), "deleted": n}

    def t_set_bc_target(self, indicator: str, format: str, target, **_):
        keys = {i["key"]: i for i in BC_INDICATORS}
        if indicator not in keys:
            return {"error": f"Unknown indicator. Use one of: {', '.join(keys)}"}
        old = self.db.one("SELECT target FROM bc_targets WHERE indicator=? AND format=?", [indicator, format])
        self.api.m_save_settings({}, targets=[{"k": indicator, "f": format, "v": target}])
        M.log(self.db, "set_bc_target", dict(indicator=indicator, format=format, old=old, new=target), self.chat_id)
        return {"ok": True, "old": old, "new": target}

    def t_set_threshold(self, key: str, value, **_):
        allowed = {"sleeping_days_cg", "sleeping_days_nonfood", "low_stock_pcs", "dp_warning_days", "min_items_for_pct", "bad_snapshot_drop_pct"}
        if key not in allowed:
            return {"error": f"Unknown threshold. Use one of: {', '.join(sorted(allowed))}"}
        old = self.db.setting(key)
        self.db.set_setting(key, value)
        M.log(self.db, "set_threshold", dict(key=key, old=old, new=value), self.chat_id)
        return {"ok": True, "old": old, "new": value}

    def t_add_store_name(self, store: str, name: str, **_):
        code = self.store(store)
        if not self.db.one("SELECT 1 FROM stores WHERE code=?", [code]):
            return {"error": f"Unknown store {store}"}
        self.api.m_add_alias({}, code, name)
        M.log(self.db, "add_store_name", dict(store=code, name=name), self.chat_id)
        return {"ok": True, "store": code}


def chart_body(spec: dict) -> dict:
    """Turn the model's chart spec into one of the screen's chart components."""
    t = spec.get("type") or "bar"
    labels = [str(x) for x in spec.get("labels") or []]
    series = spec.get("series") or []
    unit = spec.get("unit") or "num"
    fmt = {"pkr": "pkr", "pct": "pct", "int": "int"}.get(unit, "num")
    colors = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--a4)", "var(--good)", "var(--crit)"]
    if t == "line":
        return {"type": "line", "id": "c_" + str(abs(hash(spec.get("title") or "")) % 10**8), "xs": labels, "fmt": fmt,
                "series": [{"n": s.get("name") or "", "c": colors[i % len(colors)], "v": [v for v in (s.get("values") or [])]} for i, s in enumerate(series)]}
    if t == "hbar":
        vals = (series[0].get("values") if series else []) or []
        return {"type": "hbars", "fmt": fmt, "items": [{"l": l, "v": v or 0} for l, v in zip(labels, vals)]}
    if t == "table":
        cols = [{"k": "label", "l": "", "kind": "text"}] + [{"k": f"s{i}", "l": s.get("name") or "", "kind": fmt if fmt != "num" else "num"} for i, s in enumerate(series)]
        rows = [{"label": l, **{f"s{i}": (s.get("values") or [None] * len(labels))[j] for i, s in enumerate(series)}} for j, l in enumerate(labels)]
        return {"type": "table", "id": "t_" + str(abs(hash(spec.get("title") or "")) % 10**8), "cols": cols, "rows": rows, "page_size": 50}
    return {"type": "bar", "id": "b_" + str(abs(hash(spec.get("title") or "")) % 10**8), "fmt": fmt,
            "cats": [{"l": l, "k": l} for l in labels],
            "series": [{"n": s.get("name") or "", "c": colors[i % len(colors)], "v": [v or 0 for v in (s.get("values") or [])]} for i, s in enumerate(series)]}
