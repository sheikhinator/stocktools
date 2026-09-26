"""Purchase orders (LPO list), leaflet / theme items, and blocked (range 007) stock."""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

from ..grid import find_header, is_blank, non_empty
from ..reader import Sheet
from ..spec import ParseContext, ParseResult, ReportSpec, register
from ..values import (clean_text, code_text, dept_code, family_code, find_date_range, item_code, num, parse_date,
                      section_code)
from .common import (choose_snapshot, colget, dates_of, load_table, report_unknown_stores, resolve_store_value,
                     season_of, text, upper)

# =============================================================================================
# LPO list: STR LPODAT DLYDAT DEP SEC LPO LPOVAL GRN GRNVAL XLPQTY USER SUPLR SUPNAM LDTME LPOSTA CNRNO OTYPE CSUP
# =============================================================================================
LPO_TOKENS = {"LPO": 2, "LPODAT": 3, "DLYDAT": 3, "LPOVAL": 2, "LPOSTA": 2, "OTYPE": 2, "CSUP": 2, "STR": 1,
              "GRNVAL": 1, "XLPQTY": 1, "SUPLR": 1, "SUPNAM": 1, "LDTME": 1}


def parse_lpo(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    t = load_table(sheet, LPO_TOKENS)
    if t is None:
        res.error("no_header", "Could not find the column header row.")
        return res
    I = lambda *n: t.idx(*n, contains=False)
    ci = dict(st=I("STR"), od=I("LPODAT"), dd=I("DLYDAT"), dept=I("DEP"), sec=I("SEC"), lpo=I("LPO"),
              val=I("LPOVAL"), grn=I("GRN"), grnv=I("GRNVAL"), qty=I("XLPQTY"), user=I("USER"), sup=I("SUPLR"),
              supn=I("SUPNAM"), lead=I("LDTME"), status=I("LPOSTA"), otype=I("OTYPE"), csup=I("CSUP"),
              luser=I("LUSER"), cat=I("CATEGORY"))
    od = dates_of(t, ci["od"], ctx.ref_date, ["ddmmyy"])
    dd = dates_of(t, ci["dd"], ctx.ref_date, ["ddmmyy"])
    latest = max((d for d in od if d), default=None)
    choose_snapshot(res, ctx, [(latest, "the latest order date in the file")])
    unknown = Counter()
    seen = Counter()
    for k, r in enumerate(t.rows):
        no = code_text(colget(r, ci["lpo"]))
        if not no or not re.fullmatch(r"\d+", no):
            continue
        st = resolve_store_value(res, ctx.resolver, colget(r, ci["st"]), unknown) if ci["st"] is not None else ctx.store
        if not st:
            continue
        res.stores.add(st)
        sup = code_text(colget(r, ci["sup"]))
        if sup and ci["supn"] is not None:
            res.suppliers[sup] = text(colget(r, ci["supn"]))
        val = num(colget(r, ci["val"]))
        seen[(st, sup, od[k], val)] += 1
        res.add("lpo", dict(store=st, lpo_no=no, lpo_date=od[k], delivery_date=dd[k],
                            dept=dept_code(colget(r, ci["dept"])), section=section_code(colget(r, ci["sec"])),
                            value=val, grn=code_text(colget(r, ci["grn"])), grn_value=num(colget(r, ci["grnv"])),
                            qty=num(colget(r, ci["qty"])), supplier=sup, lead_days=num(colget(r, ci["lead"])),
                            status=upper(colget(r, ci["status"])), order_type=upper(colget(r, ci["otype"])),
                            deleted=upper(colget(r, ci["csup"])) == "D", created_by=text(colget(r, ci["user"])),
                            last_user=text(colget(r, ci["luser"])), category=text(colget(r, ci["cat"]))))
    report_unknown_stores(res, unknown)
    rows = res.tables.get("lpo", [])
    snap = res.snapshot_date
    late = [x for x in rows if x["status"] == "EM" and not x["deleted"] and x["delivery_date"] and snap
            and x["delivery_date"] < snap]
    if late:
        res.info("late", "Orders past their delivery date and still not received.", len(late))
    dup = sum(v - 1 for (st, sup, d, val), v in seen.items() if v > 1 and val)
    if dup:
        res.warn("duplicate_orders", "Orders that look duplicated (same store, supplier, day and value). "
                 "Check they are intended.", dup)
    deleted = sum(1 for x in rows if x["deleted"])
    res.summary = f"{len(rows):,} orders; {deleted:,} purged; {len(late):,} late"
    return res


register(ReportSpec(
    key="lpo_list", name="LPO list (purchase orders)", name_ur="ایل پی او لسٹ (خریداری آرڈرز)", source="GIMA",
    tokens=LPO_TOKENS, required=["LPODAT"], parse=parse_lpo,
    description="One line per purchase order with dates, value, received value, status and order type."))

# =============================================================================================
# Leaflet workbook, C&L theme tab
# =============================================================================================
LF_TOKENS = {"THEME": 2, "THEME NAME": 3, "THEME ST": 2, "STKQTY": 2, "ON ORDER": 2, "ON ORDER VAL": 2,
             "COMMON SINGLE": 2, "STORE": 1, "ITEM": 1, "ITEM NAME": 1, "STK VAL": 1, "STATUS": 1}


def parse_leaflet(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    t = load_table(sheet, LF_TOKENS)
    if t is None:
        res.error("no_header", "Could not find the column header row.")
        return res
    I = lambda *n: t.idx(*n, contains=False)
    ci = dict(st=I("STORE", "STR"), dept=I("DEP NAME", "DEPT"), sec=I("SEC NAME", "SEC"), fam=I("FAM"),
              sup=I("SUPPLIER"), supn=I("SUP_DEC"), item=I("ITEM"), desc=I("ITEM NAME"), pp=I("PP"), sp=I("SP"),
              theme=I("THEME"), tname=I("THEME NAME"), ttype=I("THEME ST", "THEME TYPE"), qty=I("STKQTY"),
              status=I("STATUS"), sval=I("STK VAL"), oval=I("ON ORDER VAL"), oqty=I("ON ORDER"))
    rng = t.meta.get("range") or find_date_range(t.meta.get("text", ""))
    dfrom, dto = (rng if rng else (None, None))
    title = t.meta.get("title", "")
    choose_snapshot(res, ctx, [])
    unknown = Counter()
    below_cost = 0
    for r in t.rows:
        it = item_code(colget(r, ci["item"]))
        if not it or not it.isalnum():
            continue
        st = resolve_store_value(res, ctx.resolver, colget(r, ci["st"]), unknown)
        if not st:
            continue
        res.stores.add(st)
        pp, sp = num(colget(r, ci["pp"])), num(colget(r, ci["sp"]))
        if pp and sp and sp < pp:
            below_cost += 1
        desc = text(colget(r, ci["desc"]))
        sup = code_text(colget(r, ci["sup"]))
        if sup and ci["supn"] is not None:
            res.suppliers[sup] = text(colget(r, ci["supn"]))
        res.items[it] = dict(description=desc, dept=dept_code(colget(r, ci["dept"])),
                             section=section_code(colget(r, ci["sec"])), family=family_code(colget(r, ci["fam"])),
                             supplier=sup, season=season_of(desc))
        res.add("leaflet_item", dict(theme=text(colget(r, ci["theme"])), theme_name=text(colget(r, ci["tname"])) or title,
                                     theme_type=text(colget(r, ci["ttype"])), date_from=dfrom, date_to=dto, store=st,
                                     item=it, stock_qty=num(colget(r, ci["qty"])), status=text(colget(r, ci["status"])),
                                     stock_value=num(colget(r, ci["sval"])), on_order_value=num(colget(r, ci["oval"])),
                                     on_order_qty=num(colget(r, ci["oqty"])), pp=pp, sp=sp))
    report_unknown_stores(res, unknown)
    if below_cost:
        res.warn("below_cost", "Leaflet items whose selling price is below their purchase price: every sale loses money.",
                 below_cost)
    rows = res.tables.get("leaflet_item", [])
    res.period_from, res.period_to = dfrom, dto
    zero = sum(1 for x in rows if (x["stock_qty"] or 0) <= 0)
    res.summary = f"{len(rows):,} leaflet item-store rows; {zero:,} at zero stock" + (f"; {dfrom} to {dto}" if dfrom else "")
    return res


register(ReportSpec(
    key="leaflet_theme", name="Leaflet / theme items (C & L theme)", name_ur="لیفلیٹ / تھیم آئٹمز",
    source="Leaflet workbook", tokens=LF_TOKENS, required=["STKQTY"], parse=parse_leaflet,
    phrases=[(r"C\s*&\s*L\s+THEME", 0.3)],
    description="Every leaflet or theme item per store with stock, status and what is on order."))

# =============================================================================================
# Blocked stock item report, permanent range 007 ("Data" sheet)
# =============================================================================================
BL_TOKENS = {"STORE CODE": 2, "ITEMS#": 2, "STOCK 1": 3, "STOCK 2": 3, "OPENING STOCK VALUE": 3,
             "NEW STOCK VALUE": 3, "RANGE CODE": 2, "STS": 1, "CP": 1, "VARIANCE VALUE": 1}


def _dates_above(rows, header_top: int, ref: date) -> list[date]:
    out = []
    for r in rows[max(0, header_top - 3):header_top + 1]:
        for v in r:
            if is_blank(v):
                continue
            if hasattr(v, "year") and hasattr(v, "month"):
                out.append(v if isinstance(v, date) and not hasattr(v, "hour") else v.date())
                continue
            s = clean_text(v)
            m = re.fullmatch(r"(\d{1,2})[\s\-]([A-Za-z]{3})[A-Za-z]*(?:[\s\-](\d{2,4}))?", s)
            if m:
                y = m.group(3) or str(ref.year)
                d = parse_date(f"{m.group(1)}-{m.group(2)}-{y}")
                if d and not m.group(3) and d > ref:
                    d = d.replace(year=d.year - 1)
                if d:
                    out.append(d)
    return out


def parse_blocked(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    rows = sheet.all_rows()
    h = find_header(rows, BL_TOKENS)
    t = load_table(sheet, BL_TOKENS)
    if t is None or h is None:
        res.error("no_header", "Could not find the column header row.")
        return res
    I = lambda *n: t.idx(*n)
    ci = dict(st=I("STORE CODE"), sn=I("STORE NAME"), dept=I("DEP"), sec=I("SEC"), item=I("ITEMS#", "ITEM"),
              desc=I("DESC"), sup=I("SUPP"), supn=I("SUP_DEC"), sts=I("STS"), q1=I("STOCK 1"), cp=I("CP"),
              v1=I("OPENING STOCK VALUE"), rng=I("RANGE CODE"), q2=I("STOCK 2"), v2=I("NEW STOCK VALUE"))
    ds = _dates_above(rows, h.row - len(h.raw) + 1, ctx.ref_date)
    d1, d2 = (ds[0], ds[-1]) if len(ds) >= 2 else (None, ds[0] if ds else None)
    choose_snapshot(res, ctx, [(d2, "the second stock date above the table")])
    res.period_from, res.period_to = d1, d2 or res.snapshot_date
    unknown = Counter()
    for r in t.rows:
        it = item_code(colget(r, ci["item"]))
        if not it or not it.isalnum():
            continue
        st = resolve_store_value(res, ctx.resolver, colget(r, ci["st"]), unknown)
        if not st and ci["sn"] is not None:
            st = resolve_store_value(res, ctx.resolver, colget(r, ci["sn"]), Counter())
        if not st:
            continue
        res.stores.add(st)
        sup = code_text(colget(r, ci["sup"]))
        if sup and ci["supn"] is not None:
            res.suppliers[sup] = text(colget(r, ci["supn"]))
        desc = text(colget(r, ci["desc"]))
        res.items[it] = dict(description=desc, dept=dept_code(colget(r, ci["dept"])),
                             section=section_code(colget(r, ci["sec"])), supplier=sup, season=season_of(desc))
        res.add("blocked_item", dict(store=st, item=it, status=upper(colget(r, ci["sts"])), cost=num(colget(r, ci["cp"])),
                                     qty1=num(colget(r, ci["q1"])), value1=num(colget(r, ci["v1"])),
                                     qty2=num(colget(r, ci["q2"])), value2=num(colget(r, ci["v2"])),
                                     date1=res.period_from, date2=res.period_to))
    report_unknown_stores(res, unknown)
    rs = res.tables.get("blocked_item", [])
    v1 = sum(x["value1"] or 0 for x in rs)
    v2 = sum(x["value2"] or 0 for x in rs)
    still = sum(1 for x in rs if (x["qty2"] or 0) > 0 and (x["qty2"] or 0) >= (x["qty1"] or 0))
    res.summary = f"{len(rs):,} blocked items; value {v1:,.0f} -> {v2:,.0f} ({(1 - v2 / v1) * 100 if v1 else 0:.0f}% cleared)"
    if still:
        res.info("not_moving", "Blocked items that have not moved at all between the two dates.", still)
    return res


register(ReportSpec(
    key="blocked_007", name="Blocked stock / permanent range 007", name_ur="بلاک اسٹاک / رینج 007",
    source="BC workbook", tokens=BL_TOKENS, required=["STOCK 2"], parse=parse_blocked,
    description="Blocked (007) items per store, stock at two dates, and how much was cleared."))
