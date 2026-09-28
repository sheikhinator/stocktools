"""GIMA LPO support (order proposal sheet), one store per file: every orderable item with its ordering parameters.

Columns (GIMA names): STORE_NUMBER, DEPARTMENT / SECTION / FAMILY / SUB_FAMILY (+ descriptions), SUPPLIER, SUPPLIER_NAME,
MAIN_MULTI, ORDER_DAYS ("Wednesday, Even Week", "All Weeks"), ITEM_CODE, EAN (often destroyed by Excel: ignored),
RESUPPLY_TYPE, DELIVERY (DIR = direct), ITEM_DESCRIPTION, PURCHASE / SELLING / COST_PRICE, LEAD_TIME, PERIOD_TO_COVER,
MINIMUM_STOCK, LOCKMINI, FACING, DAILY_AVG_SALES, COEFF, QUANTITY_STOCK, OFFSITE_QTY, STORE_QTY, ORDERED_QUANTITY
(open orders), PENDING_QTY1/2, PROPOSED_QUANTITY (GIMA's proposal today), PUSH_ORDER_QTY, FRZ_ORDERQTY, QTY_EOF_DAY,
INCREMENT (order multiple / case), TYPE (VFast / Fast / Slow), ASSORTMENT, PLU, ITEM_CATEGORY, ORDER_TYPE (AO / REG),
OUT_OF_STOCK, ITEM_MARGIN, ZERO_ACTIONPLAN, ZERO_DAYS, PROMO (Y/N), SALES_01..07 (last 7 days, 01 = most recent),
SALES_11..17 (last 7 weeks, 11 = most recent), INSERT_USER, INSERT_DATE (HHMMSSDDMMYY).

It gives the Order Advisor exact on-order quantities per item, the item's own lead time, order days and case size,
and 7 weeks of sales (real sales swings for safety stock).
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

from ..reader import Sheet
from ..spec import ParseContext, ParseResult, ReportSpec, register
from ..values import code_text, dept_code, family_code, item_code, num, section_code
from .common import choose_snapshot, colget, load_table, mode_date, report_unknown_stores, resolve_store_value, season_of, text, upper

TOKENS = {"STORE_NUMBER": 2, "ITEM_CODE": 2, "ORDERED_QUANTITY": 3, "PROPOSED_QUANTITY": 3, "PERIOD_TO_COVER": 2,
          "DAILY_AVG_SALES": 2, "QUANTITY_STOCK": 2, "LEAD_TIME": 1, "ORDER_DAYS": 2, "FRZ_ORDERQTY": 2,
          "QTY_EOF_DAY": 1, "PUSH_ORDER_QTY": 1, "RESUPPLY_TYPE": 1, "SALES_11": 1, "SALES_01": 1, "MINIMUM_STOCK": 1}

DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]


def review_days(order_days: str) -> float | None:
    """Days between two orders from GIMA's ORDER_DAYS: 'Wednesday, Even Week' -> 14; 'Monday, Thursday' -> 3.5."""
    s = (order_days or "").upper()
    n = sum(1 for d in DAYS if d in s) or sum(1 for d in DAYS if re.search(rf"\b{d[:3]}\b", s))
    if not n:
        return None
    every = 14.0 if re.search(r"\b(EVEN|ODD)\b", s) else 7.0
    return round(every / n, 1)


def insert_date(v) -> date | None:
    """'102018280926' = 10:20:18 on 28/09/26."""
    s = re.sub(r"\D", "", code_text(v))
    if len(s) < 6:
        return None
    d = s[-6:]
    try:
        return date(2000 + int(d[4:6]), int(d[2:4]), int(d[0:2]))
    except ValueError:
        return None


def parse_lpo_support(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    t = load_table(sheet, TOKENS)
    if t is None:
        res.error("no_header", "Could not find the column header row.")
        return res
    I = lambda *n: t.idx(*n, contains=False)
    ci = dict(st=I("STORE_NUMBER", "STORE"), dept=I("DEPARTMENT"), sec=I("SECTION"), secd=I("SECT_DESCRIPTION"),
              fam=I("FAMILY"), famd=I("FAMILY_DESCRIPTION"), sfam=I("SUB_FAMILY"), sup=I("SUPPLIER"), supn=I("SUPPLIER_NAME"),
              mm=I("MAIN_MULTI"), od=I("ORDER_DAYS"), item=I("ITEM_CODE"), resup=I("RESUPPLY_TYPE"), dlv=I("DELIVERY"),
              desc=I("ITEM_DESCRIPTION"), pp=I("PURCHASE_PRICE"), sp=I("SELLING_PRICE"), cp=I("COST_PRICE"),
              lead=I("LEAD_TIME"), cover=I("PERIOD_TO_COVER"), minst=I("MINIMUM_STOCK"), lock=I("LOCKMINI"),
              facing=I("FACING"), avg=I("DAILY_AVG_SALES"), coeff=I("COEFF"), qty=I("QUANTITY_STOCK"), off=I("OFFSITE_QTY"),
              sq=I("STORE_QTY"), ordq=I("ORDERED_QUANTITY"), p1=I("PENDING_QTY1"), p2=I("PENDING_QTY2"),
              prop=I("PROPOSED_QUANTITY"), push=I("PUSH_ORDER_QTY"), frz=I("FRZ_ORDERQTY"), eof=I("QTY_EOF_DAY"),
              inc=I("INCREMENT"), typ=I("TYPE"), ast=I("ASSORTMENT"), cat=I("ITEM_CATEGORY"), ot=I("ORDER_TYPE"),
              oos=I("OUT_OF_STOCK"), mg=I("ITEM_MARGIN"), zd=I("ZERO_DAYS"), promo=I("PROMO"), ins=I("INSERT_DATE"))
    if ci["item"] is None or ci["ordq"] is None:
        res.error("missing_columns", "ITEM_CODE or ORDERED_QUANTITY column not found.")
        return res
    day_cols = [I(f"SALES_0{i}") for i in range(1, 8)]
    week_cols = [I(f"SALES_1{i}") for i in range(1, 8)]
    choose_snapshot(res, ctx, [(mode_date(insert_date(colget(r, ci["ins"])) for r in t.rows[:2000]) if ci["ins"] is not None else None,
                                "INSERT_DATE in the rows")])
    unknown = Counter()
    n = on_order = zero_not = 0
    for k, r in enumerate(t.rows):
        it = item_code(colget(r, ci["item"]))
        if not it or not it.isalnum():
            continue
        if ci["st"] is not None and colget(r, ci["st"]) not in (None, ""):
            st = resolve_store_value(res, ctx.resolver, colget(r, ci["st"]), unknown)
        else:
            st = ctx.store
        if not st:
            continue
        res.stores.add(st)
        desc = text(colget(r, ci["desc"]))
        sup = code_text(colget(r, ci["sup"]))
        inc = num(colget(r, ci["inc"]))
        sec = section_code(colget(r, ci["sec"]))
        res.items[it] = dict(description=desc, dept=dept_code(colget(r, ci["dept"])), section=sec,
                             family=family_code(colget(r, ci["fam"])), subfamily=code_text(colget(r, ci["sfam"])),
                             supplier=sup, pcb=inc if inc and inc > 0 else None, season=season_of(desc))
        if sup and ci["supn"] is not None and text(colget(r, ci["supn"])):
            res.suppliers[sup] = text(colget(r, ci["supn"]))
        od = text(colget(r, ci["od"]))
        ordered = num(colget(r, ci["ordq"])) or 0.0
        pend = (num(colget(r, ci["p1"])) or 0.0) + (num(colget(r, ci["p2"])) or 0.0)
        stock = num(colget(r, ci["qty"]))
        avg = num(colget(r, ci["avg"]))
        row = dict(snap_date=res.snapshot_date, store=st, item=it, supplier=sup, main_multi=upper(colget(r, ci["mm"])),
                   order_days=od, review_days=review_days(od), resupply=upper(colget(r, ci["resup"])), delivery=upper(colget(r, ci["dlv"])),
                   lead_time=num(colget(r, ci["lead"])), cover_days=num(colget(r, ci["cover"])), min_stock=num(colget(r, ci["minst"])),
                   lockmini=num(colget(r, ci["lock"])), facing=num(colget(r, ci["facing"])), dlyavg=avg, coeff=num(colget(r, ci["coeff"])),
                   stock=stock, offsite=num(colget(r, ci["off"])), store_qty=num(colget(r, ci["sq"])), ordered=ordered, pending=pend,
                   proposed=num(colget(r, ci["prop"])), push_qty=num(colget(r, ci["push"])), frozen_qty=num(colget(r, ci["frz"])),
                   eof_qty=num(colget(r, ci["eof"])), pcb=inc, speed_class=upper(colget(r, ci["typ"])),
                   assortment=code_text(colget(r, ci["ast"])), category=code_text(colget(r, ci["cat"])), order_type=upper(colget(r, ci["ot"])),
                   oos_flag=upper(colget(r, ci["oos"])), margin_pct=num(colget(r, ci["mg"])), zero_days=num(colget(r, ci["zd"])),
                   promo=upper(colget(r, ci["promo"])), purchase_price=num(colget(r, ci["pp"])), selling_price=num(colget(r, ci["sp"])),
                   cost_price=num(colget(r, ci["cp"])))
        for i, j in enumerate(day_cols, 1):
            row[f"d{i}"] = num(colget(r, j)) if j is not None else None
        for i, j in enumerate(week_cols, 1):
            row[f"w{i}"] = num(colget(r, j)) if j is not None else None
        res.add("order_line", row)
        n += 1
        if ordered + pend > 0:
            on_order += 1
        elif (stock or 0) <= 0 and ((avg or 0) > 0 or any((row.get(f"w{i}") or 0) > 0 for i in range(1, 8))):
            zero_not += 1
        if k % 5000 == 0:
            ctx.tick(k / max(1, len(t.rows)), "Reading order lines")
    report_unknown_stores(res, unknown)
    if zero_not:
        res.info("not_on_order", "Selling items at zero stock with nothing on order (top priority).", zero_not)
    res.summary = f"{n:,} items; {on_order:,} on order; {zero_not:,} selling items at zero stock not on order"
    return res


register(ReportSpec(
    key="gima_lpo_support", name="GIMA LPO support (order proposal, item level)", name_ur="جیما ایل پی او سپورٹ",
    source="GIMA", tokens=TOKENS, required=["ITEM_CODE", "ORDERED_QUANTITY"], parse=parse_lpo_support,
    description="Every item of a store with stock, open order quantity, GIMA's proposal, lead time, order days, case size "
                "and 7 days + 7 weeks of sales."))
