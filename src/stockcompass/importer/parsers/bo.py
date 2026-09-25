"""BO reports (numbered report codes like 500-30-15, 200-10-05)."""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from datetime import date

from ..grid import extract_meta, is_blank, non_empty, norm
from ..reader import Sheet
from ..spec import ParseContext, ParseResult, ReportSpec, register
from ..values import clean_text, date_column, infer_date_format, num, parse_date, pct_value
from .common import choose_snapshot, report_unknown_stores, text

# =============================================================================================
# 500-30-15 Zero Stock Report Summary: stores x days (store tab, department tab, section tab)
# =============================================================================================
ZSS_TOKENS = {"TOTAL ITEMS": 3, "ZERO STOCK": 3, "% ZERO STOCK": 3, "START DATE": 1, "END DATE": 1}
DEPT_RE = re.compile(r"^0?([1-5])\s*-\s*[A-Z]{2,5}$", re.I)
SEC_RE = re.compile(r"^S?(\d{3})\s*-\s*\S", re.I)


def _is_date_cell(v) -> bool:
    if isinstance(v, (date,)):
        return True
    s = clean_text(v)
    return bool(re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}(\s+\d{1,2}:\d{2}(:\d{2})?\s*[AP]M)?", s))


def parse_zero_summary(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    rows = sheet.all_rows()
    meta = extract_meta(rows, upto=12)
    p = meta["pairs"]
    sd = parse_date(p.get("START DATE")) if p.get("START DATE") else None
    ed = parse_date(p.get("END DATE")) if p.get("END DATE") else None
    # all date cells in the grid decide the date format (m/d/yyyy in BO)
    all_date_cells = [v for r in rows for v in r if _is_date_cell(v)]
    g = infer_date_format(all_date_cells, ref=ctx.ref_date, prefer=["m/d/y"])
    fmt = g.fmt
    if sd is None or ed is None:
        ds = sorted(d for d in (parse_date(v, fmt) for v in all_date_cells) if d)
        if ds:
            sd, ed = sd or ds[0], ed or ds[-1]
    res.period_from, res.period_to = sd, ed
    choose_snapshot(res, ctx, [(ed, "the report End Date")])
    dept = sec = None
    date_cols: dict[int, date] = {}
    labels: dict[int, str] = {}
    groups: list[tuple[date, int | None, int | None, int | None]] = []

    def rebuild():
        nonlocal groups
        groups = []
        starts = sorted(date_cols)
        for gi, c0 in enumerate(starts):
            c1 = starts[gi + 1] if gi + 1 < len(starts) else c0 + 6
            lab = {labels[c]: c for c in range(c0 - 1, c1) if c in labels}
            groups.append((date_cols[c0], lab.get("TOTAL ITEMS"), lab.get("ZERO STOCK"), lab.get("% ZERO STOCK")))

    unknown = Counter()
    seen_levels = set()
    for r in rows:
        ne = non_empty(r)
        if not ne:
            continue
        first = clean_text(r[ne[0]])
        dcells = [j for j in ne if _is_date_cell(r[j])]
        if len(dcells) >= 2 and len(dcells) >= len(ne) * 0.8:
            date_cols = {j: parse_date(r[j], fmt) for j in dcells}
            rebuild()
            continue
        labs = {j: norm(r[j]) for j in ne if norm(r[j]) in ("TOTAL ITEMS", "ZERO STOCK", "% ZERO STOCK")}
        if len(labs) >= 3:
            labels = labs
            rebuild()
            continue
        if ne[0] == 0 or len(ne) == 1:
            if DEPT_RE.match(first):
                dept = "0" + DEPT_RE.match(first).group(1)
                sec = None
                continue
            if SEC_RE.match(first):
                sec = SEC_RE.match(first).group(1)
                continue
        if not groups:
            continue
        up = first.upper()
        if up.startswith("PAK ") or up in ("PAK PAKISTAN", "PAK SM PAKISTAN") or "TOTAL" in up or "COUNTRY" in up:
            continue
        sm = ctx.resolver.resolve(first)
        if not sm.code:
            if sm.kind in ("closed", "channel"):
                unknown[f"{first} ({sm.kind})"] += 1
            else:
                unknown[first] += 1
            continue
        level = "section" if sec else ("dept" if dept else "store")
        seen_levels.add(level)
        res.stores.add(sm.code)
        for d, ct, cz, cp in groups:
            tot = num(r[ct]) if ct is not None and ct < len(r) else None
            zer = num(r[cz]) if cz is not None and cz < len(r) else None
            pr = pct_value(r[cp], fraction_hint=True) if cp is not None and cp < len(r) and not is_blank(r[cp]) else None
            if tot is None and zer is None:
                continue
            res.add("zs_daily", dict(level=level, store=sm.code, dept=dept or "", section=sec or "", day=d,
                                     total_items=tot, zero_items=zer, printed_pct=pr))
    report_unknown_stores(res, unknown)
    _checks(res, ctx)
    rs = res.tables.get("zs_daily", [])
    days = sorted({x["day"] for x in rs if x["day"]})
    res.summary = (f"{len(rs):,} store-day rows ({', '.join(sorted(seen_levels)) or 'no'} level), "
                   f"{len(res.stores)} stores, {len(days)} days")
    return res


def _where(key) -> str:
    lvl, st, dp, sc = key
    return st + (f" dept {dp}" if dp else "") + (f" section {sc}" if sc else "")


def _checks(res: ParseResult, ctx: ParseContext):
    """Flag what a human analyst would: failed loads, blank days, range cuts, sudden jumps, wrong printed %."""
    rs = res.tables.get("zs_daily", [])
    series = defaultdict(list)
    for x in rs:
        series[(x["level"], x["store"], x["dept"], x["section"])].append(x)
    drop_pct = float(ctx.settings.get("bad_snapshot_drop_pct", 15) or 15)
    all_days = sorted({x["day"] for x in rs if x["day"]})
    pct_mismatch = 0
    bad_msgs, cut_msgs, jump_msgs = [], [], []
    missing = Counter()
    for key, xs in series.items():
        xs.sort(key=lambda x: x["day"])
        have = {x["day"] for x in xs}
        if key[0] == "store":
            missing[key[1]] += sum(1 for d in all_days if d not in have)
        tots = [x["total_items"] for x in xs if x["total_items"]]
        if len(tots) < 3:
            continue
        med_t = statistics.median(tots)
        med_z = statistics.median([x["zero_items"] or 0 for x in xs])
        bad_days = set()
        for x in xs:
            t, z = x["total_items"], x["zero_items"]
            if t and z is not None:
                if x["printed_pct"] is not None and abs(z / t * 100 - x["printed_pct"]) > 1.01:
                    pct_mismatch += 1
                if t < med_t * (1 - drop_pct / 100) and z < 0.25 * max(med_z, 1):
                    bad_days.add(x["day"])
                    x["suspect"] = True
        if bad_days:
            bad_msgs.append(f"{_where(key)}: " + ", ".join(f"{d:%d %b}" for d in sorted(bad_days)))
        good = [x for x in xs if x["day"] not in bad_days and x["total_items"] and x["zero_items"] is not None]
        cuts, cut_items, cut_zero = [], 0, 0
        for prev, x in zip(good, good[1:]):
            if (x["day"] - prev["day"]).days > 3:
                continue
            d_items = x["total_items"] - prev["total_items"]
            d_zero = x["zero_items"] - prev["zero_items"]
            limit = max(30, 0.005 * prev["total_items"])
            if d_items <= -limit and d_zero <= -0.6 * abs(d_items):
                cuts.append(x["day"])
                cut_items += -d_items
                cut_zero += -d_zero
            elif d_zero >= max(50, 0.15 * max(prev["zero_items"], 1)) and d_zero > 3 * abs(d_items):
                jump_msgs.append((d_zero, f"{_where(key)} on {x['day']:%d %b}: {int(d_zero)} more items went to zero "
                                  f"stock while the range stayed about the same ({int(d_items):+d} items). "
                                  "Looks like a stock count or adjustment, not sales. Check with the store."))
        if cuts and key[0] != "store":
            cut_msgs.append((cut_zero, f"{_where(key)}: {int(cut_items)} items removed from the range on "
                             + ", ".join(f"{d:%d %b}" for d in cuts)
                             + f", and zero stock fell by {int(cut_zero)}. That part of the improvement came from "
                               "delisting, not restocking."))
    if bad_msgs:
        res.warn("bad_snapshot", "Days where the stock load looks broken (far fewer items and almost no zero stock). "
                 "They are left out of averages: " + "; ".join(bad_msgs[:20]), len(bad_msgs), detail="|".join(bad_msgs))
    blank = {k: v for k, v in missing.items() if v}
    if blank:
        res.info("missing_days", "Days left blank in the report: " + ", ".join(f"{k} ({v})" for k, v in sorted(blank.items())),
                 sum(blank.values()))
    for _, m in sorted(cut_msgs, reverse=True)[:15]:
        res.warn("range_cut", m)
    for _, m in sorted(jump_msgs, reverse=True)[:15]:
        res.warn("zero_jump", m)
    if pct_mismatch:
        res.info("pct_recomputed", "Printed % differs from zero stock ÷ total items; Stock Compass uses its own "
                 "calculation.", pct_mismatch)
    for x in rs:
        x["suspect"] = bool(x.get("suspect"))


register(ReportSpec(
    key="bo_zero_summary", name="BO 500-30-15 zero stock summary", name_ur="بی او زیرو اسٹاک سمری",
    source="BO", tokens=ZSS_TOKENS, required=["TOTAL ITEMS"], parse=parse_zero_summary,
    phrases=[(r"500-30-15", 0.5), (r"ZERO STOCK REPORT SUMMARY", 0.3)],
    anti=["LEAFLET CODE", "AVG ZERO STOCK ITEMS"],
    description="Total items and zero-stock items per store (or department / section) for every day."))


# =============================================================================================
# Other BO reports: recognised and kept row by row (analysis screens come in a later version)
# =============================================================================================
def _bo(key, name, name_ur, tokens, phrases):
    register(ReportSpec(key=key, name=name, name_ur=name_ur, source="BO", tokens=tokens, phrases=phrases,
                        analysed=False, description="Recognised BO report, stored for later analysis."))


_bo("bo_store_net_sales", "BO 200-10-05 store net sales", "اسٹور نیٹ سیلز",
    {"SECTION CODE NAME": 2, "NET SALES": 2, "SECTION WEIGHT": 2, "PENT. RATE": 2, "AVG BASKET": 1, "AVG STOCK": 1,
     "OUT OF STOCK %": 1}, [(r"200-10-05", 0.5), (r"STORE PERFORMANCE", 0.2)])
_bo("bo_11b", "BO 11b sales (country / department / section)", "بی او 11 بی سیلز",
    {"WEIGHT %": 1, "BUDGET": 1, "NET SALES": 1, "PENETRATION RATE %": 2, "NET MARGIN AFTER WASTE%": 2,
     "OUT OF STOCK %": 1, "STOCK DAYS": 1, "PROMO WEIGHT%": 2, "WEIGHT IN STORE%": 1}, [(r"\bDAILY\s*:", 0.2)])
_bo("bo_11f", "BO 11f sales (section / family / supplier)", "بی او 11 ایف سیلز",
    {"B2C LY": 2, "B2C CY": 2, "B2B LY": 2, "B2B CY": 2, "B2B WEIGHT%": 2, "PURCHASE": 1, "QTY SOLD CY": 1,
     "GROSS SALES CY": 1}, [(r"200-10-11F", 0.5)])
_bo("bo_family_sales", "BO family sales (year on year)", "فیملی سیلز",
    {"DEPARTMENT NAME": 1, "SECTION NAME": 1, "FAMILY": 1, "GTH %": 2, "2025": 1, "2026": 1},
    [(r"\bFAMILY\b.*\bONLINE\b|\bONLINE\b.*\bOFFLINE\b", 0.3)])
_bo("bo_variance_lines", "BO 500-30-49 variance of lines received", "لائنوں کا فرق",
    {"% VARIANCE": 3, "STORE": 1, "DEPARTMENT": 1}, [(r"500-30-49", 0.6), (r"VARIANCE OF LINES", 0.3)])
_bo("bo_leaflet_zero", "BO 500-90-08 leaflet zero stock", "لیفلیٹ زیرو اسٹاک",
    {"LEAFLET CODE": 3, "LEAFLET NAME": 2, "PROMOTIONAL ITEM COUNT": 2, "AVG ZERO STOCK ITEMS": 2,
     "AVG ZERO STOCK %": 2}, [(r"500-90-08", 0.5)])
_bo("bo_stock_days", "BO 200-10-10 country daily stock (stock days)", "اسٹاک ڈیز",
    {"MONTHLY AVERAGE STOCK": 3, "LY NET SALES GROWTH": 2, "STOCK GROWTH": 2, "STOCK DAYS": 1},
    [(r"200-10-10", 0.5), (r"STOCK AS OF", 0.1)])
_bo("bo_stock_movement", "Stock movement analysis (corrections, under 6 pcs, negative)", "اسٹاک موومنٹ",
    {"NO. OF ITEMS": 2, "COUNT OF NEGATIVE": 3, "COUNT OF LESS 6 PCS": 3, "% OF STOCK CORRECTIONS": 2, "M-": 1,
     "M+": 1, "O-": 1, "O+": 1}, [(r"STOCK MOVEMENT ANALYSIS", 0.4)])
