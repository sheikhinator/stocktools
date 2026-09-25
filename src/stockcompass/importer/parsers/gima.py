"""GIMA exports: RealTime (item master + stock), Benchmark (item sales), zero stock sheet, negative stock sheet."""

from __future__ import annotations

import re
from collections import Counter
from datetime import timedelta

from ..reader import Sheet
from ..spec import ParseContext, ParseResult, ReportSpec, register
from ..values import barcode, code_text, dept_code, family_code, is_destroyed_barcode, item_code, num, section_code
from .common import (choose_snapshot, colget, dates_of, load_table, mode_date, report_unknown_stores,
                     resolve_store_value, season_of, store_from_filename, text, upper)

# =============================================================================================
# RealTime (GIMA, per store): CSECW1 CRAYW1 CFAMW1 ... QPHYW1 PVTCW1 ...
# =============================================================================================
RT_TOKENS = {"NARTW1": 3, "QPHYW1": 3, "CARRW1": 2, "STAFW1": 2, "PVTCW1": 2, "CRAYW1": 1, "CSECW1": 1,
             "CFAMW1": 1, "LARTW1": 1, "NFOUW1": 1, "PRFTW1": 1, "ASSTW1": 1}


def _w1_layout(cells: set[str], text: str) -> float:
    n = sum(1 for c in cells if re.fullmatch(r"[A-Z0-9]{4}W1", c))
    return 0.3 if n >= 12 else 0.0


def parse_realtime(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    t = load_table(sheet, RT_TOKENS)
    if t is None:
        res.error("no_header", "Could not find the column header row.")
        return res
    I = lambda *n: t.idx(*n, contains=False)
    ci = dict(dept=I("CSECW1"), sec=I("CRAYW1"), fam=I("CFAMW1"), sfam=I("CSFAW1"), desc=I("LARTW1"),
              item=I("NARTW1"), sup=I("NFOUW1"), ean=I("CEANW1"), brand=I("CMARW1"), st=I("CARRW1"),
              sst=I("STAFW1"), cost=I("PRNVW1", "PRFTW1", "PAFFW1", "PHTVW1"), price=I("PVTCW1"), da=I("DDVAW1"),
              db=I("DDENW1"), qty=I("QPHYW1"), promo=I("PPTCW1"), ast=I("ASSTW1"), rng=I("RNGCW1"),
              nord=I("NORDW1"), flow=I("PCBRW1"), pcb=I("PRPSW1"))
    if ci["item"] is None or ci["qty"] is None:
        res.error("missing_columns", "Item code (NARTW1) or stock (QPHYW1) column not found.")
        return res
    store = ctx.store or store_from_filename(ctx.file_name, ctx.resolver)
    if not store:
        res.error("need_store", "This RealTime file has no store column. Choose the store in the import screen.")
        return res
    res.stores.add(store)
    choose_snapshot(res, ctx, [])
    da = dates_of(t, ci["da"], ctx.ref_date, ["yymmdd"])
    db = dates_of(t, ci["db"], ctx.ref_date, ["yymmdd"])
    nord = dates_of(t, ci["nord"], ctx.ref_date, ["yymmdd"])
    destroyed = neg = noprice = 0
    seen = Counter()
    for k, r in enumerate(t.rows):
        it = item_code(colget(r, ci["item"]))
        if not it or not it.isalnum():
            continue
        seen[it] += 1
        qty = num(colget(r, ci["qty"]))
        price = num(colget(r, ci["price"]))
        if qty is not None and qty < 0:
            neg += 1
        if not price:
            noprice += 1
        raw_ean = colget(r, ci["ean"])
        if is_destroyed_barcode(raw_ean):
            destroyed += 1
        desc = text(colget(r, ci["desc"]))
        res.items[it] = dict(description=desc, dept=dept_code(colget(r, ci["dept"])),
                             section=section_code(colget(r, ci["sec"])), family=family_code(colget(r, ci["fam"])),
                             subfamily=code_text(colget(r, ci["sfam"])), supplier=code_text(colget(r, ci["sup"])),
                             brand=code_text(colget(r, ci["brand"])), barcode=barcode(raw_ean),
                             ast1=upper(colget(r, ci["ast"])), season=season_of(desc))
        res.add("stock_item", dict(snap_date=res.snapshot_date, store=store, item=it, qty=qty,
                                   cost=num(colget(r, ci["cost"])), price=price, status=upper(colget(r, ci["st"])),
                                   sup_status=upper(colget(r, ci["sst"])), ast1=upper(colget(r, ci["ast"])),
                                   range_code=code_text(colget(r, ci["rng"])).zfill(3) if code_text(colget(r, ci["rng"])) else "",
                                   supplier=code_text(colget(r, ci["sup"])), date_a=da[k], date_b=db[k],
                                   next_order=nord[k], flow=upper(colget(r, ci["flow"])),
                                   promo_price=num(colget(r, ci["promo"]))))
        if k % 5000 == 0:
            ctx.tick(k / max(1, len(t.rows)), "Reading stock")
    dups = sum(1 for v in seen.values() if v > 1)
    if dups:
        res.warn("duplicates", "Items listed more than once (last row kept for the item list).", dups)
    if destroyed:
        res.info("barcodes_destroyed", "Barcodes damaged by Excel (like 6.2E+11). Not a problem: items are matched "
                 "on item code.", destroyed)
    if neg:
        res.info("negative", "Items with negative stock.", neg)
    if noprice:
        res.warn("no_price", "Items with no selling price.", noprice)
    n = len(res.tables.get("stock_item", []))
    res.summary = f"{n:,} items, store {store}"
    return res


register(ReportSpec(
    key="gima_realtime", name="GIMA RealTime (stock and item master)", name_ur="جیما ریئل ٹائم (اسٹاک)",
    source="GIMA", tokens=RT_TOKENS, required=["NARTW1", "QPHYW1"], needs_store=True, parse=parse_realtime,
    custom=_w1_layout, description="Stock on hand, cost, price and status for every item of one store."))

# =============================================================================================
# Benchmark (GIMA): FRMDAT TODAT ... ITEM ITMDSC ... TOTAL_T TOTAL_Q TOTAL_M TOTAL_S PKG_T ...
# =============================================================================================
BM_TOKENS = {"FRMDAT": 3, "TODAT": 3, "ITEM": 2, "ITMDSC": 2, "SUPPLR": 1, "SUPDEC": 1, "AST1": 1, "PP": 1,
             "SP": 1, "PCB": 1, "TOTAL_T": 2, "TOTAL_Q": 2}
GROUP_RE = re.compile(r"^([A-Z0-9 &]{2,20})_([TQMS])$")


def parse_benchmark(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    t = load_table(sheet, BM_TOKENS)
    if t is None:
        res.error("no_header", "Could not find the column header row.")
        return res
    I = lambda *n: t.idx(*n, contains=False)
    ci = dict(fr=I("FRMDAT"), to=I("TODAT"), dept=I("DEPT"), sec=I("SEC"), fam=I("FAM"), sfam=I("SFA"),
              sup=I("SUPPLR"), supn=I("SUPDEC"), ean=I("BARCODE"), item=I("ITEM"), desc=I("ITMDSC"), ast1=I("AST1"),
              ast2=I("AST2"), brand=I("BRAND"), pp=I("PP"), sp=I("SP"), pcb=I("PCB"))
    groups: dict[str, dict[str, int]] = {}
    for j, c in enumerate(t.columns):
        m = GROUP_RE.match(c.strip().upper())
        if m:
            groups.setdefault(m.group(1).strip(), {})[m.group(2)] = j
    store_cols = {}
    unknown = Counter()
    for prefix, cols in groups.items():
        if prefix in ("TOTAL", "TOT", "COUNTRY", "ALL"):
            continue
        sm = ctx.resolver.resolve(prefix)
        if sm.code:
            store_cols[sm.code] = cols
        else:
            unknown[prefix] += 1
    report_unknown_stores(res, unknown)
    if not store_cols:
        if ctx.store and "TOTAL" in groups:
            store_cols[ctx.store] = groups["TOTAL"]
            res.warn("total_as_store", f"No store columns found; TOTAL used as store {ctx.store}.")
        else:
            res.error("no_store_groups", "No store column groups (like PKG_T, PKG_Q) were found.")
            return res
    fr = dates_of(t, ci["fr"], ctx.ref_date, ["d/m/y"])
    to = dates_of(t, ci["to"], ctx.ref_date, ["d/m/y"])
    res.period_from, res.period_to = mode_date(fr), mode_date(to)
    choose_snapshot(res, ctx, [(res.period_to, "the TODAT column")])
    if res.period_from is None:
        res.period_from = res.snapshot_date
    if res.period_to is None:
        res.period_to = res.snapshot_date
    tot = groups.get("TOTAL", {})
    margin_bad = 0
    sum_store_t = 0.0
    sum_total_t = 0.0
    for k, r in enumerate(t.rows):
        it = item_code(colget(r, ci["item"]))
        if not it:
            continue
        desc = text(colget(r, ci["desc"]))
        pp = num(colget(r, ci["pp"]))
        sup = code_text(colget(r, ci["sup"]))
        res.items[it] = dict(description=desc, dept=dept_code(colget(r, ci["dept"])),
                             section=section_code(colget(r, ci["sec"])), family=family_code(colget(r, ci["fam"])),
                             subfamily=code_text(colget(r, ci["sfam"])), supplier=sup,
                             brand=code_text(colget(r, ci["brand"])), barcode=barcode(colget(r, ci["ean"])),
                             pcb=num(colget(r, ci["pcb"])), ast1=upper(colget(r, ci["ast1"])),
                             ast2=upper(colget(r, ci["ast2"])), season=season_of(desc))
        if sup and ci["supn"] is not None:
            res.suppliers[sup] = text(colget(r, ci["supn"]))
        if tot.get("T") is not None:
            sum_total_t += num(colget(r, tot["T"])) or 0
        for st, cols in store_cols.items():
            T = num(colget(r, cols.get("T"))) if "T" in cols else None
            Q = num(colget(r, cols.get("Q"))) if "Q" in cols else None
            M = num(colget(r, cols.get("M"))) if "M" in cols else None
            S = num(colget(r, cols.get("S"))) if "S" in cols else None
            if not any([T, Q, M]) and S is None:
                continue
            sum_store_t += T or 0
            if T and Q and pp is not None and M is not None and abs((T - Q * pp) - M) > max(2.0, abs(M) * 0.02):
                margin_bad += 1
            res.add("sales_item", dict(date_from=res.period_from, date_to=res.period_to, store=st, item=it, sales=T,
                                       qty=Q, margin=M, stock=S))
            res.stores.add(st)
    if margin_bad:
        res.info("margin_check", "Rows where margin is not sales minus qty x purchase price (price changed during "
                 "the period?).", margin_bad)
    if sum_total_t and sum_store_t and abs(sum_total_t - sum_store_t) > 1 and len(store_cols) < 5:
        share = sum_store_t / sum_total_t * 100
        res.info("total_is_country", f"TOTAL columns cover more stores than this file; this file's stores are "
                 f"{share:.1f}% of TOTAL sales.")
    n = len(res.tables.get("sales_item", []))
    res.summary = f"{n:,} item-store sales rows, {len(store_cols)} store(s), {res.period_from} to {res.period_to}"
    return res


register(ReportSpec(
    key="gima_benchmark", name="GIMA Benchmark (item sales)", name_ur="جیما بینچ مارک (آئٹم سیلز)", source="GIMA",
    tokens=BM_TOKENS, required=["ITEM"], parse=parse_benchmark,
    custom=lambda cells, text: 0.3 if sum(1 for c in cells if GROUP_RE.match(c)) >= 4 else 0.0,
    description="Net sales, quantity, margin and stock per item and store for a date range."))

# =============================================================================================
# GIMA zero stock sheet: STR BACDTO ... ITEMTO ... CODDES ...
# =============================================================================================
ZS_TOKENS = {"ITEMTO": 3, "PHQTTO": 3, "CODDES": 3, "IDSCTO": 1, "DLYAVG": 2, "NCDED": 1, "LDOUTO": 1, "LDINTO": 1,
             "NBRDTO": 1, "ITMAOP": 1, "STR": 1, "DLIVD": 1, "DNEXT": 1}


def parse_zero_sheet(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    t = load_table(sheet, ZS_TOKENS)
    if t is None:
        res.error("no_header", "Could not find the column header row.")
        return res
    I = lambda *n: t.idx(*n, contains=False)
    ci = dict(st=I("STR"), ean=I("BACDTO"), dept=I("DEPTTO"), sec=I("SECTTO"), desc=I("IDSCTO"), qty=I("PHQTTO"),
              item=I("ITEMTO"), fam=I("FAMITO"), sfam=I("SFAMTO"), status=I("ISTSTO", "ITMSTA", "STAFE"),
              lin=I("LDINTO"), lout=I("LDOUTO"), days=I("NBRDTO"), sup=I("SUPPTO"), supn=I("RSOCF"),
              ast=I("ASSTTO"), dliv=I("DLIVD"), open=I("NCDED"), nbree=I("NBREE"), lastlpo=I("NCDEM"),
              minq=I("QMINM"), dnext=I("DNEXT"), facing=I("FACING"), mode=I("ITMAOP"), avg=I("DLYAVG"),
              slow=I("SLOWMV"), promo=I("PROMO"), imp=I("IMPSUP"), reason=I("CODDES"), tord=I("TOTORD"),
              trcv=I("TOTRCV"), flow=I("ITMFLW"))
    if ci["item"] is None:
        res.error("missing_columns", "Item code column (ITEMTO) not found.")
        return res
    lin = dates_of(t, ci["lin"], ctx.ref_date, ["yymmdd"])
    lout = dates_of(t, ci["lout"], ctx.ref_date, ["yymmdd"])
    dliv = dates_of(t, ci["dliv"], ctx.ref_date, ["yymmdd"])
    dnext = dates_of(t, ci["dnext"], ctx.ref_date, ["yymmdd"])
    # The report date is hidden in the data: last sale date + days since last sale = the day GIMA counted from.
    refs = []
    for k, r in enumerate(t.rows):
        d = num(colget(r, ci["days"]))
        if lout[k] and d and d > 0:
            refs.append(lout[k] + timedelta(days=int(d)))
    inferred = mode_date(refs)
    choose_snapshot(res, ctx, [(inferred, "last-sale date + days since last sale")])
    unknown = Counter()
    reasons = Counter()
    for k, r in enumerate(t.rows):
        it = item_code(colget(r, ci["item"]))
        if not it:
            continue
        st = resolve_store_value(res, ctx.resolver, colget(r, ci["st"]), unknown) if ci["st"] is not None else ctx.store
        if not st:
            continue
        res.stores.add(st)
        desc = text(colget(r, ci["desc"]))
        sup = code_text(colget(r, ci["sup"]))
        res.items[it] = dict(description=desc, dept=dept_code(colget(r, ci["dept"])),
                             section=section_code(colget(r, ci["sec"])), family=family_code(colget(r, ci["fam"])),
                             subfamily=code_text(colget(r, ci["sfam"])), supplier=sup,
                             barcode=barcode(colget(r, ci["ean"])), ast1=upper(colget(r, ci["ast"])),
                             season=season_of(desc))
        if sup and ci["supn"] is not None:
            res.suppliers[sup] = text(colget(r, ci["supn"]))
        open_lpo = code_text(colget(r, ci["open"]))
        reason = text(colget(r, ci["reason"]))
        reasons[reason or "(none)"] += 1
        days = num(colget(r, ci["days"]))
        res.add("zero_item", dict(
            snap_date=res.snapshot_date, store=st, item=it, qty=num(colget(r, ci["qty"])), last_in=lin[k],
            last_out=lout[k], days_out=int(days) if days is not None else None, dlyavg=num(colget(r, ci["avg"])),
            order_mode=upper(colget(r, ci["mode"])), open_lpo=None if open_lpo in ("", "0") else open_lpo,
            delivery_date=dliv[k], next_order=dnext[k], last_lpo=code_text(colget(r, ci["lastlpo"])),
            reason=reason, status=upper(colget(r, ci["status"])), supplier=sup, slow=upper(colget(r, ci["slow"])),
            promo=upper(colget(r, ci["promo"])), import_sup=upper(colget(r, ci["imp"])),
            total_ordered=num(colget(r, ci["tord"])), total_received=num(colget(r, ci["trcv"])),
            min_qty=num(colget(r, ci["minq"])), facing=num(colget(r, ci["facing"]))))
    report_unknown_stores(res, unknown)
    rows = res.tables.get("zero_item", [])
    not_on_order = sum(1 for x in rows if not x["open_lpo"])
    res.info("not_on_order", "Zero-stock items with nothing on order (top priority).", not_on_order)
    pos = sum(1 for x in rows if (x["qty"] or 0) > 0)
    if pos:
        res.warn("positive_in_zero_sheet", "Rows with stock above zero in a zero-stock sheet (stock came in after "
                 "the report?).", pos)
    res.summary = f"{len(rows):,} zero-stock items; {not_on_order:,} not on order; top reason: " \
                  f"{reasons.most_common(1)[0][0] if reasons else '-'}"
    return res


register(ReportSpec(
    key="gima_zero_stock", name="GIMA zero stock sheet (with reasons)", name_ur="جیما زیرو اسٹاک شیٹ",
    source="GIMA", tokens=ZS_TOKENS, required=["ITEMTO"], parse=parse_zero_sheet,
    description="Every zero-stock item with GIMA's reason, open order, last sale and daily sales rate."))

# =============================================================================================
# GIMA negative stock sheet: STR DEPTPR SECTPR FAMIPR IDSCPR PHQTPR BACDPR CHDGPR ITEMPR ISTSPR
# =============================================================================================
NEG_TOKENS = {"ITEMPR": 3, "PHQTPR": 3, "ISTSPR": 3, "IDSCPR": 1, "DEPTPR": 1, "SECTPR": 1, "STR": 1}


def parse_negative(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    t = load_table(sheet, NEG_TOKENS)
    if t is None:
        res.error("no_header", "Could not find the column header row.")
        return res
    I = lambda *n: t.idx(*n, contains=False)
    ci = dict(st=I("STR", "STORE", "STORES"), dept=I("DEPTPR"), sec=I("SECTPR"), fam=I("FAMIPR"), desc=I("IDSCPR"),
              qty=I("PHQTPR"), ean=I("BACDPR"), item=I("ITEMPR"), status=I("ISTSPR", "ITMSTS"))
    choose_snapshot(res, ctx, [])
    unknown = Counter()
    by_status = Counter()
    for r in t.rows:
        it = item_code(colget(r, ci["item"]))
        if not it:
            continue
        st = resolve_store_value(res, ctx.resolver, colget(r, ci["st"]), unknown) if ci["st"] is not None else ctx.store
        if not st:
            continue
        qty = num(colget(r, ci["qty"]))
        status = upper(colget(r, ci["status"]))
        by_status[status] += 1
        res.stores.add(st)
        desc = text(colget(r, ci["desc"]))
        res.items[it] = dict(description=desc, dept=dept_code(colget(r, ci["dept"])),
                             section=section_code(colget(r, ci["sec"])), family=family_code(colget(r, ci["fam"])),
                             barcode=barcode(colget(r, ci["ean"])), season=season_of(desc))
        res.add("negative_item", dict(snap_date=res.snapshot_date, store=st, item=it, qty=qty, status=status))
    report_unknown_stores(res, unknown)
    if not res.stores and not ctx.store:
        res.error("need_store", "No store column found. Choose the store in the import screen.")
    n = len(res.tables.get("negative_item", []))
    res.summary = f"{n:,} negative-stock items (" + ", ".join(f"{k or '?'} {v}" for k, v in by_status.most_common()) + ")"
    return res


register(ReportSpec(
    key="gima_negative_stock", name="GIMA negative stock sheet", name_ur="جیما منفی اسٹاک شیٹ", source="GIMA",
    tokens=NEG_TOKENS, required=["ITEMPR", "PHQTPR"], anti=["CPVAL", "AGNGPR", "DEP PROVISION"],
    parse=parse_negative, description="Items with stock below zero, with their status (AC / NC / NI)."))
