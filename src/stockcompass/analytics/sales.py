"""Sales and commercial numbers: sales vs budget and last year, growth, front margin, B2C / B2B, families,
suppliers, stores and items. Everything is recalculated from base values (never the printed %)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from stockcompass.db import Database

from .core import Explain, Kpi, L, Scope, fmt_pkr, ids_sql

PERIOD_NAMES = {"DAY": ("Day", "دن"), "WTD": ("Week to date", "ہفتہ اب تک"), "MTD": ("Month to date", "ماہ اب تک"),
                "YTD": ("Year to date", "سال اب تک")}


def _wavg(rows, val, w="sales"):
    num = sum((r[val] or 0) * (r[w] or 0) for r in rows if r[val] is not None and r[w])
    den = sum(r[w] or 0 for r in rows if r[val] is not None and r[w])
    return num / den if den else None


def periods(db: Database) -> list[tuple[str, date]]:
    """Periods available in the sales data, with their latest date."""
    rows = db.q("SELECT period, max(date_to) FROM sales_block GROUP BY period")
    rows += [r for r in db.q("SELECT period, max(date_to) FROM sales_fss GROUP BY period") if r[0] not in {x[0] for x in rows}]
    order = {"DAY": 0, "WTD": 1, "MTD": 2, "YTD": 3}
    return sorted(rows, key=lambda r: order.get(r[0], 9))


def _scope_filters(scope: Scope, alias: str = "b") -> tuple[str, list]:
    w, p = scope.store_sql(f"{alias}.store")
    parts, params = [w], list(p)
    if scope.section:
        parts.append(f"{alias}.section = ?")
        params.append(scope.section)
    elif scope.dept:
        parts.append(f"coalesce(nullif({alias}.dept,''), sec.dept) = ?")
        params.append(scope.dept)
    return " AND ".join(parts), params


def block_rows(db: Database, scope: Scope, period: str) -> tuple[list[dict], dict]:
    """Rows from 11b / store net sales for the latest date of this period, at the most detailed level
    available: store × section, then store × department, then country × section."""
    d = db.one("SELECT max(date_to) FROM sales_block WHERE period=?", [period])
    if not d:
        return [], {}
    info = {"date": d, "period": period}
    w, p = _scope_filters(scope)
    want_store = bool(scope.stores or scope.formats)
    for level, need_store in [("section", True), ("dept", True), ("country_section", False), ("country_dept", False)]:
        if level.startswith("country") and want_store:
            break
        if level == "dept" and scope.section:
            continue
        src = db.one("SELECT source FROM sales_block WHERE period=? AND date_to=? AND level=? "
                     "ORDER BY source='11b' DESC LIMIT 1", [period, d, level])
        if not src:
            continue
        storecond = "b.store IS NOT NULL" if need_store else "b.store IS NULL"
        wl = w if need_store else _scope_filters(Scope(dept=scope.dept, section=scope.section))[0]
        pl = p if need_store else _scope_filters(Scope(dept=scope.dept, section=scope.section))[1]
        rows = db.qd(f"""SELECT b.*, coalesce(nullif(b.dept,''), sec.dept) dept2, sec.name section_name,
                                d.name dept_name, s.name store_name, s.format
                         FROM sales_block b LEFT JOIN sections sec ON sec.code=b.section
                         LEFT JOIN departments d ON d.code=coalesce(nullif(b.dept,''), sec.dept)
                         LEFT JOIN stores s ON s.code=b.store
                         WHERE b.period=? AND b.date_to=? AND b.level=? AND b.source=? AND {storecond} AND {wl}""",
                     [period, d, level, src] + pl)
        if rows:
            for r in rows:
                r["dept"] = r.pop("dept2")
            info.update(level=level, source=src)
            return rows, info
    return [], info


def _agg(rows, key, name_key) -> list[dict]:
    g = defaultdict(list)
    for r in rows:
        g[r[key]].append(r)
    out = []
    tot = sum(r["sales"] or 0 for r in rows) or 1
    for k, rs in g.items():
        s = sum(r["sales"] or 0 for r in rs)
        b = sum(r["budget"] or 0 for r in rs)
        ly = sum(r["ly_sales"] or 0 for r in rs if r["ly_sales"] is not None)
        has_ly = any(r["ly_sales"] is not None for r in rs)
        sv = sum(r["stock_value"] or 0 for r in rs)
        out.append(dict(key=k, name=rs[0].get(name_key) or k, sales=s, budget=b or None,
                        vs_budget=(s / b - 1) * 100 if b else None, ly=ly if has_ly else None,
                        growth=(s / ly - 1) * 100 if has_ly and ly else None, share=s / tot * 100,
                        margin=_wavg(rs, "margin_pct"), qty=sum(r["qty"] or 0 for r in rs),
                        stock_value=sv or None, oos=_wavg(rs, "oos_pct"), waste=_wavg(rs, "waste_pct"),
                        promo=_wavg(rs, "promo_pct")))
    return sorted(out, key=lambda x: -x["sales"])


def overview(db: Database, scope: Scope, period: str, compare: str = "budget") -> dict:
    rows, info = block_rows(db, scope, period)
    fss = fss_rows(db, scope, period)
    if not rows and not fss:
        return {}
    res = {"info": info, "rows": rows}
    if rows:
        s = sum(r["sales"] or 0 for r in rows)
        b = sum(r["budget"] or 0 for r in rows)
        lyr = [r for r in rows if r["ly_sales"] is not None]
        ly = sum(r["ly_sales"] for r in lyr)
        s_ly = sum(r["sales"] or 0 for r in lyr)
        res.update(sales=s, budget=b or None, vs_budget=(s / b - 1) * 100 if b else None,
                   ly=ly or None, growth=(s_ly / ly - 1) * 100 if ly else None, margin=_wavg(rows, "margin_pct"),
                   qty=sum(r["qty"] or 0 for r in rows), stock_value=sum(r["stock_value"] or 0 for r in rows) or None,
                   oos=_wavg(rows, "oos_pct"), waste=_wavg(rows, "waste_pct"))
        lvl = "section" if (scope.dept or scope.section or info.get("level") in ("section", "country_section")) else "dept"
        if scope.section:
            res["by_group"] = _agg(rows, "store", "store_name") if info["level"] == "section" else _agg(rows, "section", "section_name")
            res["group_level"] = "store" if info["level"] == "section" else "section"
        elif scope.dept and lvl == "section":
            res["by_group"] = _agg(rows, "section", "section_name")
            res["group_level"] = "section"
        else:
            res["by_group"] = _agg(rows, "dept", "dept_name")
            res["group_level"] = "dept"
        res["by_section"] = _agg(rows, "section", "section_name") if info.get("level") in ("section", "country_section") else []
        res["by_store"] = _agg([r for r in rows if r["store"]], "store", "store_name")
    if fss:
        cy = sum(r["sales_cy"] or 0 for r in fss)
        b2b = sum(r["b2b_cy"] or 0 for r in fss)
        b2bm = sum(r["b2b_margin"] or 0 for r in fss)
        res.update(b2b=b2b, b2b_share=b2b / cy * 100 if cy else None, b2b_margin_pct=b2bm / b2b * 100 if b2b else None,
                   fss_date=fss[0]["date_to"])
    return res


def kpis(db: Database, scope: Scope, period: str, compare: str) -> tuple[list[Kpi], dict]:
    ov = overview(db, scope, period, compare)
    if not ov:
        return [], {}
    out = []
    info = ov["info"]
    pname = L(*PERIOD_NAMES.get(period, (period, period)))
    as_of = f"{pname} · {info['date']:%d %b %Y}" if info.get("date") else pname
    if "sales" in ov:
        st = "" if ov["vs_budget"] is None else ("good" if ov["vs_budget"] >= 0 else ("warn" if ov["vs_budget"] >= -10 else "bad"))
        out.append(Kpi("sales", L("Net sales", "نیٹ سیلز"), ov["sales"], "pkr",
                       sub=(L(f"{ov['vs_budget']:+.1f}% vs budget {fmt_pkr(ov['budget'])}",
                              f"بجٹ کے مقابلے {ov['vs_budget']:+.1f}%") if ov["vs_budget"] is not None else as_of),
                       status=st, goto="sales:breakdown",
                       chip=(L("✓ above budget", "✓ بجٹ سے زیادہ") if st == "good" else L("✕ below budget", "✕ بجٹ سے کم"))
                       if st else "",
                       explain=Explain(L("Net sales", "نیٹ سیلز"), "Sales without tax for the period and scope shown.",
                                       f"Σ net sales = {fmt_pkr(ov['sales'])}; Σ budget = {fmt_pkr(ov['budget'])}; "
                                       f"vs budget = {ov['vs_budget']:+.1f}%" if ov["vs_budget"] is not None else
                                       f"Σ net sales = {fmt_pkr(ov['sales'])}",
                                       f"BO {info.get('source', '')} ({info.get('level', '')} level)", as_of)))
        if ov["growth"] is not None:
            out.append(Kpi("growth", L("Growth vs last year", "پچھلے سال کے مقابلے اضافہ"), ov["growth"], "pct",
                           sub=L(f"Last year {fmt_pkr(ov['ly'])}", f"پچھلا سال {fmt_pkr(ov['ly'])}"),
                           status="good" if ov["growth"] >= 0 else "bad", goto="sales:breakdown",
                           chip=L("▲ up", "▲ اضافہ") if ov["growth"] >= 0 else L("▼ down", "▼ کمی"),
                           explain=Explain(L("Growth vs last year", "پچھلے سال کے مقابلے اضافہ"),
                                           "Last year's sales are rebuilt from each row's sales and printed growth "
                                           "(LY = sales ÷ (1 + growth)), then added up; growth is recalculated.",
                                           f"{fmt_pkr(ov['sales'])} ÷ {fmt_pkr(ov['ly'])} − 1 = {ov['growth']:+.1f}%",
                                           "BO 11b / store net sales", as_of)))
        if ov["margin"] is not None:
            out.append(Kpi("margin", L("Front margin", "فرنٹ مارجن"), ov["margin"], "pct",
                           sub=L("before back margin / rebates", "بیک مارجن سے پہلے"),
                           status="bad" if ov["margin"] < 0 else "", goto="sales:breakdown",
                           chip=L("✕ negative", "✕ منفی") if ov["margin"] < 0 else "",
                           explain=Explain(L("Front margin", "فرنٹ مارجن"), "Margin before back margin and supplier "
                                           "rebates, weighted by sales.", f"Σ(sales × margin%) ÷ Σ sales = {ov['margin']:.1f}%",
                                           "BO 11b / store net sales", as_of)))
        if ov.get("qty"):
            out.append(Kpi("qty", L("Units sold", "فروخت شدہ یونٹس"), ov["qty"], "int", sub=as_of, goto="sales:breakdown"))
        if ov.get("oos") is not None:
            out.append(Kpi("oos_bo", L("Out of stock % (BO)", "آؤٹ آف اسٹاک % (بی او)"), ov["oos"], "pct",
                           sub=L("as printed by BO, sales-weighted", "بی او کے مطابق"), goto="stock:zero"))
    if ov.get("b2b") is not None:
        out.append(Kpi("b2b", L("Bulk (B2B) share", "بلک (B2B) حصہ"), ov["b2b_share"], "pct",
                       sub=L(f"{fmt_pkr(ov['b2b'])} · margin {ov['b2b_margin_pct']:.1f}%" if ov["b2b_margin_pct"] is not None
                             else fmt_pkr(ov["b2b"]), f"{fmt_pkr(ov['b2b'])}"),
                       status="bad" if (ov.get("b2b_margin_pct") or 0) < 0 else "", goto="sales:b2b",
                       chip=L("✕ sold below cost", "✕ لاگت سے کم") if (ov.get("b2b_margin_pct") or 0) < 0 else "",
                       explain=Explain(L("Bulk (B2B) share", "بلک حصہ"), "Business-to-business (bulk / trade) sales as a "
                                       "share of gross sales, and the front margin earned on them. Shown separately so a "
                                       "big bulk order does not hide weak retail sales.",
                                       f"B2B {fmt_pkr(ov['b2b'])} ÷ gross sales", "BO 11f",
                                       f"{pname} · {ov['fss_date']:%d %b %Y}" if ov.get("fss_date") else pname)))
    return out, ov


# ------------------------------------------------------------------------------------------------
# 11f: families, suppliers, B2C / B2B
# ------------------------------------------------------------------------------------------------

def fss_rows(db: Database, scope: Scope, period: str) -> list[dict]:
    d = db.one("SELECT max(date_to) FROM sales_fss WHERE period=?", [period])
    if not d:
        return []
    want_store = bool(scope.stores or scope.formats)
    has_store = db.one("SELECT count(*) FROM sales_fss WHERE period=? AND date_to=? AND store IS NOT NULL", [period, d])
    if want_store and not has_store:
        return []
    w, p = _scope_filters(scope, "f")
    storecond = "f.store IS NOT NULL" if (want_store or not db.one(
        "SELECT count(*) FROM sales_fss WHERE period=? AND date_to=? AND store IS NULL", [period, d])) else "f.store IS NULL"
    if storecond == "f.store IS NULL":
        w, p = _scope_filters(Scope(dept=scope.dept, section=scope.section), "f")
    return db.qd(f"""SELECT f.*, fam.name family_name, sup.name supplier_name, sec.name section_name, s.name store_name
                    FROM sales_fss f LEFT JOIN families fam ON fam.code=f.family AND fam.section=f.section
                    LEFT JOIN suppliers sup ON sup.code=f.supplier LEFT JOIN sections sec ON sec.code=f.section
                    LEFT JOIN stores s ON s.code=f.store
                    WHERE f.period=? AND f.date_to=? AND {storecond} AND {w}""", [period, d] + p)


def _fss_group(rows, key, name_key, extra=None) -> list[dict]:
    g = defaultdict(list)
    for r in rows:
        g[r[key]].append(r)
    tot = sum(r["sales_cy"] or 0 for r in rows) or 1
    out = []
    for k, rs in g.items():
        cy = sum(r["sales_cy"] or 0 for r in rs)
        ly = sum(r["sales_ly"] or 0 for r in rs)
        b2b = sum(r["b2b_cy"] or 0 for r in rs)
        b2bm = sum(r["b2b_margin"] or 0 for r in rs)
        wm = [r for r in rs if r["margin_pct"] is not None and r["sales_cy"]]
        margin = sum(r["margin_pct"] * r["sales_cy"] for r in wm) / sum(r["sales_cy"] for r in wm) if wm and sum(
            r["sales_cy"] for r in wm) else None
        row = dict(key=k, name=rs[0].get(name_key) or k, sales_cy=cy, sales_ly=ly,
                   growth=(cy / ly - 1) * 100 if ly else None, share=cy / tot * 100, margin=margin, b2b=b2b,
                   b2b_share=b2b / cy * 100 if cy else None, b2b_margin=b2bm / b2b * 100 if b2b else None,
                   promo=_wavg([dict(x, sales=x["sales_cy"]) for x in rs], "promo_pct"),
                   stock_value=sum(r["stock_value"] or 0 for r in rs) or None,
                   purchase=sum(r["purchase"] or 0 for r in rs) or None,
                   qty_cy=sum(r["qty_cy"] or 0 for r in rs), qty_ly=sum(r["qty_ly"] or 0 for r in rs))
        if extra:
            row.update(extra(rs))
        out.append(row)
    return sorted(out, key=lambda x: -x["sales_cy"])


def families(db: Database, scope: Scope, period: str) -> list[dict]:
    rows = fss_rows(db, scope, period)
    if rows:
        for r in rows:
            r["fam_key"] = f"{r['section']}:{r['family']}"
            r["fam_label"] = f"{r['family']} {r['family_name'] or ''}".strip()
        out = _fss_group(rows, "fam_key", "fam_label",
                         extra=lambda rs: dict(section_name=rs[0]["section_name"], family=rs[0]["family"],
                                               suppliers=len({r["supplier"] for r in rs})))
        return out
    # fallback: family year-on-year report
    wi = "TRUE"
    params: list = []
    if scope.section:
        wi, params = "f.section=?", [scope.section]
    elif scope.dept:
        wi, params = "f.dept=?", [scope.dept]
    rows = db.qd(f"""SELECT f.*, fam.name family_name, sec.name section_name FROM sales_family f
                    LEFT JOIN families fam ON fam.code=f.family AND fam.section=f.section
                    LEFT JOIN sections sec ON sec.code=f.section
                    WHERE f.import_id=(SELECT max(import_id) FROM imports WHERE report_type='bo_family_sales') AND {wi}""",
                 params)
    tot = sum(r["sales_cy"] or 0 for r in rows) or 1
    return sorted([dict(key=f"{r['section']}:{r['family']}", name=f"{r['family']} {r['family_name'] or ''}",
                        section_name=r["section_name"], sales_cy=r["sales_cy"], sales_ly=r["sales_ly"],
                        growth=(r["sales_cy"] / r["sales_ly"] - 1) * 100 if r["sales_ly"] and r["sales_cy"] is not None else None,
                        share=(r["sales_cy"] or 0) / tot * 100,
                        margin=(r["margin_cy"] / r["sales_cy"] * 100) if r["sales_cy"] and r["margin_cy"] is not None else None,
                        online_share=(r["online_cy"] or 0) / r["sales_cy"] * 100 if r["sales_cy"] else None,
                        promo=(r["promo_cy"] or 0) / r["sales_cy"] * 100 if r["sales_cy"] else None)
                   for r in rows], key=lambda x: -(x["sales_cy"] or 0))


def suppliers(db: Database, scope: Scope, period: str) -> list[dict]:
    rows = fss_rows(db, scope, period)
    for r in rows:
        r["sup_label"] = r["supplier_name"] or r["supplier"]
    return _fss_group(rows, "supplier", "sup_label",
                      extra=lambda rs: dict(families=len({r["family"] for r in rs}),
                                            stock_days=_wavg([dict(x, sales=x["stock_value"]) for x in rs], "stock_days")))


def b2b_by_store(db: Database, scope: Scope, period: str) -> list[dict]:
    rows = [r for r in fss_rows(db, scope, period) if r["store"]]
    out = _fss_group(rows, "store", "store_name")
    return [x for x in out if x["b2b"]]


def lost_lines(db: Database, scope: Scope, period: str = "YTD") -> list[dict]:
    """Family × supplier lines that sold last year and nothing this year: range or supplier gaps."""
    rows = fss_rows(db, scope, period)
    out = [dict(r, lost=r["sales_ly"]) for r in rows if (r["sales_ly"] or 0) > 0 and not (r["sales_cy"] or 0)]
    return sorted(out, key=lambda r: -r["lost"])


def items(db: Database, scope: Scope) -> list[dict]:
    """Item sales from the latest benchmark period."""
    ids = [r[0] for r in db.q("SELECT max(import_id) FROM imports WHERE report_type='gima_benchmark' GROUP BY stores")]
    if not ids:
        return []
    w, p = scope.store_sql("s.store")
    wi, pi = scope.item_sql()
    rows = db.qd(f"""SELECT s.item, i.description, sec.name section_name, sup.name supplier_name,
                           sum(s.sales) sales, sum(s.qty) qty, sum(s.margin) margin, sum(s.stock) stock,
                           count(DISTINCT s.store) stores, min(s.date_from) date_from, max(s.date_to) date_to
                    FROM sales_item s LEFT JOIN items i USING (item) LEFT JOIN sections sec ON sec.code=i.section
                    LEFT JOIN suppliers sup ON sup.code=i.supplier
                    WHERE s.import_id IN {ids_sql(ids)} AND {w} AND {wi} GROUP BY ALL ORDER BY sales DESC""", p + pi)
    tot = sum(r["sales"] or 0 for r in rows) or 1
    run = 0.0
    for r in rows:
        r["margin_pct"] = r["margin"] / r["sales"] * 100 if r["sales"] else None
        run += r["sales"] or 0
        r["abc"] = "A" if run / tot <= 0.8 else ("B" if run / tot <= 0.95 else "C")
    return rows
