"""Sales reports from BO: 11b (country / department / section × store, Day / MTD / YTD), 11f (section × family
× supplier, with B2C / B2B and last year), family sales (year on year, online / offline) and the 200-10-05 store
net sales report (one block per store).

These reports repeat the same label many times ("Gth%" after Net Sales, after Customer, after Avg Selling
Price...). Labels are therefore read in context: a bare "Gth%" belongs to the metric just before it.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

from ..grid import is_blank, norm
from ..reader import Sheet
from ..spec import ParseContext, ParseResult, ReportSpec, register
from ..values import clean_text, dept_code, find_date_range, find_dates, parse_date, parse_num, section_code
from .common import choose_snapshot, report_unknown_stores

PERIOD_RE = re.compile(r"^(DAILY|DAY|MTD|YTD|WTD)\b", re.I)


def _period_name(label: str) -> str:
    u = label.upper()
    return "DAY" if u.startswith("DA") else u[:3]


def _num(v):
    return parse_num(v).value


def _pct(v, frac_ok: bool = True):
    """Percent cell. Text with % is already percent; a bare small number in a % column is a fraction."""
    p = parse_num(v)
    if p.value is None:
        return None
    if p.percent:
        return p.value
    if frac_ok and isinstance(v, (int, float)) and abs(p.value) <= 1.5:
        return p.value * 100
    if frac_ok and isinstance(v, str) and abs(p.value) <= 1.5 and "." in v:
        return p.value * 100
    return p.value


def _context_labels(labels: list[str]) -> list[str]:
    """'GTH%' after 'NET SALES' -> 'NET SALES GTH%'; after 'ACTUAL' (ASP) -> 'ACTUAL GTH%'."""
    out, prev = [], ""
    for l in labels:
        n = re.sub(r"\s+", " ", norm(l).replace(" %", "%"))
        if n in ("GTH%", "GTH", "GROWTH%", "VAR%") and prev:
            out.append(f"{prev} {n}")
        else:
            out.append(n)
            if n:
                prev = n
    return out


def _blocks(rows, max_scan: int = 25):
    """Find the period group row (Daily / MTD / YTD) and the label row under it.
    Returns (group_row_idx, label_row_idx, dims{col: name}, blocks{period: {label: col}})."""
    for gi in range(min(len(rows), max_scan)):
        r = rows[gi]
        starts = [(j, clean_text(v)) for j, v in enumerate(r) if isinstance(v, str) and PERIOD_RE.match(clean_text(v))]
        if len(starts) >= 2 or (starts and gi + 1 < len(rows)):
            li = gi + 1
            if li >= len(rows) or len([v for v in rows[li] if not is_blank(v)]) < 5:
                continue
            first = starts[0][0]
            dims = {}
            for j in range(first):
                name = clean_text(r[j]) if j < len(r) else ""
                sub = clean_text(rows[li][j]) if j < len(rows[li]) else ""
                if name or sub:
                    dims[j] = norm(name or sub)
            blocks = {}
            bounds = [s[0] for s in starts] + [max(len(rows[li]), len(r))]
            for k, (j0, lab) in enumerate(starts):
                j1 = bounds[k + 1]
                labels = [clean_text(rows[li][j]) if j < len(rows[li]) else "" for j in range(j0, j1)]
                ctx = _context_labels(labels)
                cols = {}
                for off, name in enumerate(ctx):
                    if name and name not in cols:
                        cols[name] = j0 + off
                blocks[_period_name(lab)] = cols
            return gi, li, dims, blocks
    return None


def _col(cols: dict, *names):
    for n in names:
        n2 = re.sub(r"\s+", " ", norm(n).replace(" %", "%"))
        if n2 in cols:
            return cols[n2]
    return None


def _get(r, j):
    return r[j] if j is not None and j < len(r) else None


def _report_date(rows, ctx) -> tuple[date | None, date | None]:
    """'Daily : (Sat) 25-Jul-26', 'Sales Date (Tue) 25-Aug-26', 'Report Period : 24/09/2026 - 24/09/2026'."""
    text = "\n".join(" ".join(clean_text(v) for v in r if not is_blank(v)) for r in rows[:12])
    rng = find_date_range(text)
    if rng:
        return rng
    ds = [d for d in find_dates(text) if abs((d - ctx.ref_date).days) < 800]
    if ds:
        return None, ds[0]
    return None, None


def _store_of(ctx, res, v, unknown: Counter):
    m = ctx.resolver.resolve(v)
    if m.code:
        return m.code
    t = clean_text(v)
    if t:
        unknown[f"{t} ({m.kind})" if m.kind in ("closed", "channel") else t] += 1
    return None


# =============================================================================================
# 11b: Department | Section | Code | [Store Type | Store Short Name] | Daily ... | MTD ... | YTD ...
# =============================================================================================

def parse_11b(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    rows = sheet.all_rows()
    b = _blocks(rows)
    if not b:
        res.error("no_header", "Could not find the Daily / MTD / YTD column groups.")
        return res
    gi, li, dims, blocks = b
    dfrom, dto = _report_date(rows, ctx)
    choose_snapshot(res, ctx, [(dto, "the report header")])
    dto = res.snapshot_date
    dcol = next((j for j, n in dims.items() if n.startswith("DEPARTMENT")), None)
    scol = next((j for j, n in dims.items() if n in ("SECTION", "SECTION CODE NAME")), None)
    ccol = next((j for j, n in dims.items() if n == "CODE"), None)
    stcol = next((j for j, n in dims.items() if "STORE SHORT" in n or n in ("STORE", "STORE NAME")), None)
    unknown = Counter()
    for r in rows[li + 1:]:
        if not any(not is_blank(v) for v in r):
            continue
        head3 = " ".join(clean_text(_get(r, j)) for j in range(3)).upper()
        if "MAF RETAIL" in head3 or " TOTAL" in f" {head3}":
            continue
        dept = dept_code(_get(r, dcol)) if dcol is not None else ""
        if not dept and dcol is not None:
            dn = norm(_get(r, dcol))
            dept = {"CONSUMER GOODS": "01", "FRESH FOOD": "02", "LIGHT HOUSEHOLD": "03", "HEAVY HOUSEHOLD": "04",
                    "TEXTILE": "05"}.get(dn, "")
        sec = ""
        if ccol is not None:
            sec = section_code(_get(r, ccol))
        if not sec and scol is not None:
            sec = section_code(_get(r, scol))
        store = None
        if stcol is not None:
            store = _store_of(ctx, res, _get(r, stcol), unknown)
            if not store:
                continue
            res.stores.add(store)
        if not dept and not sec:
            continue  # grand total ("MAF Retail - Stores") or a blank line
        level = "section" if sec else "dept"
        if store is None:
            level = "country_" + level
        for period, cols in blocks.items():
            sales = _num(_get(r, _col(cols, "NET SALES")))
            budget = _num(_get(r, _col(cols, "BUDGET")))
            if sales is None and budget is None:
                continue
            g = _pct(_get(r, _col(cols, "NET SALES GTH%")), frac_ok=False)
            ly = sales / (1 + g / 100) if sales is not None and g is not None and g > -99.9 else None
            res.add("sales_block", dict(
                source="11b", period=period, date_from=dfrom, date_to=dto, level=level, store=store, dept=dept,
                section=sec, budget=budget, sales=sales, growth_pct=g, ly_sales=ly,
                var_budget_pct=_pct(_get(r, _col(cols, "NET SALES VAR%", "VAR%")), frac_ok=False),
                margin_pct=_pct(_get(r, _col(cols, "MARGIN%")), frac_ok=False),
                waste_pct=_pct(_get(r, _col(cols, "WASTE%")), frac_ok=False),
                customers=_num(_get(r, _col(cols, "CUSTOMER"))),
                penetration=_pct(_get(r, _col(cols, "PENETRATION RATE%", "PENETRATION%")), frac_ok=False),
                qty=_num(_get(r, _col(cols, "QTY"))), avg_basket=_num(_get(r, _col(cols, "AVG BASK"))),
                asp=_num(_get(r, _col(cols, "ACTUAL"))), stock_value=_num(_get(r, _col(cols, "STOCK VALUE"))),
                stock_days=_num(_get(r, _col(cols, "STOCK DAYS"))),
                oos_pct=_pct(_get(r, _col(cols, "OUT OF STOCK%")), frac_ok=False),
                promo_pct=_pct(_get(r, _col(cols, "PROMO WEIGHT%")), frac_ok=False)))
    report_unknown_stores(res, unknown)
    n = len(res.tables.get("sales_block", []))
    res.variant = ",".join(sorted({x["level"] for x in res.tables.get("sales_block", [])}))
    levels = Counter(x["level"] for x in res.tables.get("sales_block", []))
    res.summary = f"{n:,} sales rows ({', '.join(f'{k} {v}' for k, v in levels.items())}), periods " \
                  f"{', '.join(blocks)}, date {dto}"
    return res


register(ReportSpec(
    key="bo_11b", name="BO 11b sales (country / department / section)", name_ur="بی او 11 بی سیلز", source="BO",
    tokens={"WEIGHT %": 1, "BUDGET": 1, "NET SALES": 1, "PENETRATION RATE %": 2, "NET MARGIN AFTER WASTE%": 2,
            "OUT OF STOCK %": 1, "STOCK DAYS": 1, "PROMO WEIGHT%": 2, "WEIGHT IN STORE%": 1, "MTD": 1, "YTD": 1},
    phrases=[(r"\bDAILY\s*:", 0.2)], anti=["B2C LY", "B2B CY"], parse=parse_11b,
    description="Net sales, budget, growth vs last year, margin, customers, stock and OOS by section and store."))


# =============================================================================================
# 11f: Country | [Store Type | Store] | Department | Section | Family | Supplier | Day ... | MTD ... | YTD ...
# =============================================================================================

def parse_11f(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    rows = sheet.all_rows()
    b = _blocks(rows, max_scan=30)
    if not b:
        res.error("no_header", "Could not find the Day / MTD / YTD column groups.")
        return res
    gi, li, dims, blocks = b
    _, dto = _report_date(rows[:gi + 1], ctx)
    choose_snapshot(res, ctx, [(dto, "the Sales Date in the header")])
    dto = res.snapshot_date
    find = lambda *ks: next((j for j, n in dims.items() if any(n.startswith(k) for k in ks)), None)
    stcol, dcol, scol = find("STORE"), find("DEPARTMENT"), find("SECTION")
    fcol, pcol = find("FAMILY"), find("SUPPLIER")
    if stcol is not None and norm(dims[stcol]).startswith("STORE TYPE"):
        stcol = next((j for j, n in dims.items() if n == "STORE"), None)
    unknown = Counter()
    fams = {}
    for r in rows[li + 1:]:
        if not any(not is_blank(v) for v in r):
            continue
        store = None
        if stcol is not None:
            store = _store_of(ctx, res, _get(r, stcol), unknown)
            if not store:
                continue
            res.stores.add(store)
        dept = dept_code(_get(r, dcol))
        sec = section_code(_get(r, scol))
        ftxt = clean_text(_get(r, fcol))
        m = re.match(r"^\s*(\d{1,4})\s*-\s*(.*)$", ftxt)
        fam, fname = (m.group(1).zfill(3), m.group(2).strip()) if m else ("", ftxt)
        ptxt = clean_text(_get(r, pcol))
        m = re.match(r"^\s*(?:PK)?(\d+)\s*-\s*(.*)$", ptxt, re.I)
        sup, sname = (m.group(1), m.group(2).strip()) if m else ("", ptxt)
        if not sec and not fam:
            continue
        if fam and sec:
            fams[(fam, sec)] = fname
        if sup and sname:
            res.suppliers[sup] = sname
        for period, cols in blocks.items():
            ly = _num(_get(r, _col(cols, "GROSS SALES LY")))
            cy = _num(_get(r, _col(cols, "GROSS SALES CY")))
            if ly is None and cy is None:
                continue
            res.add("sales_fss", dict(
                period=period, date_to=dto, store=store, dept=dept, section=sec, family=fam, supplier=sup,
                sales_ly=ly, sales_cy=cy, b2c_ly=_num(_get(r, _col(cols, "B2C LY"))),
                b2c_cy=_num(_get(r, _col(cols, "B2C CY"))), b2b_ly=_num(_get(r, _col(cols, "B2B LY"))),
                b2b_cy=_num(_get(r, _col(cols, "B2B CY"))), margin_pct=_pct(_get(r, _col(cols, "MARGIN%")), False),
                waste_pct=_pct(_get(r, _col(cols, "WASTE%")), False),
                b2c_margin=_num(_get(r, _col(cols, "B2C MARGIN VALUE"))),
                b2b_margin=_num(_get(r, _col(cols, "B2B MARGIN VALUE"))),
                customers=_num(_get(r, _col(cols, "CUSTOMER"))),
                promo_pct=_pct(_get(r, _col(cols, "PROMO SALES%")), False),
                purchase=_num(_get(r, _col(cols, "PURCHASE"))), stock_value=_num(_get(r, _col(cols, "STOCK VALUE"))),
                stock_days=_num(_get(r, _col(cols, "STOCK DAYS"))), qty_cy=_num(_get(r, _col(cols, "QTY SOLD CY"))),
                qty_ly=_num(_get(r, _col(cols, "QTY SOLD LY")))))
    report_unknown_stores(res, unknown)
    res.tables["_families"] = [dict(code=f, section=s, name=n) for (f, s), n in fams.items()]
    res.variant = "store" if stcol is not None else "country"
    rows_ = res.tables.get("sales_fss", [])
    lost = sum(1 for x in rows_ if x["period"] == "YTD" and (x["sales_ly"] or 0) > 0 and not (x["sales_cy"] or 0))
    if lost:
        res.info("lost_lines", "Family / supplier lines that sold last year and nothing this year.", lost)
    res.summary = f"{len(rows_):,} family × supplier rows, {len(res.stores) or 'country'} store(s), date {dto}"
    return res


register(ReportSpec(
    key="bo_11f", name="BO 11f sales (section / family / supplier)", name_ur="بی او 11 ایف سیلز", source="BO",
    tokens={"B2C LY": 2, "B2C CY": 2, "B2B LY": 2, "B2B CY": 2, "B2B WEIGHT%": 2, "PURCHASE": 1, "QTY SOLD CY": 1,
            "GROSS SALES CY": 1, "FAMILY CODE NAME NEW": 1, "SUPPLIER": 1}, phrases=[(r"200-10-11F", 0.5)],
    parse=parse_11f, description="Sales this year vs last year by section, family and supplier, split B2C / B2B."))


# =============================================================================================
# Family sales: Department Name | Section Name | Family Name | Total Sales 2025 2026 Gth% | Online ... | ...
# =============================================================================================

def parse_family(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    rows = sheet.all_rows()
    hi = next((i for i, r in enumerate(rows[:20]) if any(norm(v) == "FAMILY NAME" for v in r)), None)
    if hi is None or hi + 1 >= len(rows):
        res.error("no_header", "Could not find the 'Family Name' header.")
        return res
    group, sub = rows[hi], rows[hi + 1]
    width = max(len(group), len(sub))
    cur = ""
    keys = {}
    years = sorted({int(clean_text(v)) for v in sub if re.fullmatch(r"20\d\d", clean_text(v))})
    cy = years[-1] if years else ctx.ref_date.year
    for j in range(width):
        g = clean_text(group[j]) if j < len(group) else ""
        if g:
            cur = norm(g)
        s = clean_text(sub[j]) if j < len(sub) else ""
        if not s:
            continue
        tag = "CY" if s.startswith(str(cy)) else ("LY" if re.match(r"20\d\d", s) else norm(s))
        if s.endswith("%") and re.match(r"20\d\d", s):
            tag += "%"
        keys.setdefault(f"{cur}|{tag}", j)
    k = lambda g, t: keys.get(f"{g}|{t}")
    choose_snapshot(res, ctx, [])
    store = ctx.store
    if store:
        res.stores.add(store)
    fams = {}
    for r in rows[hi + 2:]:
        dtxt = clean_text(_get(r, 0))
        stxt = clean_text(_get(r, 1))
        ftxt = clean_text(_get(r, 2))
        if not ftxt or "TOTAL" in stxt.upper() or "TOTAL" in ftxt.upper():
            continue
        m = re.match(r"^\s*(\d{1,4})\s*-\s*(.*)$", ftxt)
        if not m:
            continue
        fam, fname = m.group(1).zfill(3), m.group(2).strip()
        sec = section_code(stxt)
        fams[(fam, sec)] = fname
        res.add("sales_family", dict(
            date_to=res.snapshot_date, store=store, dept=dept_code(dtxt), section=sec, family=fam,
            sales_ly=_num(_get(r, k("TOTAL SALES", "LY"))), sales_cy=_num(_get(r, k("TOTAL SALES", "CY"))),
            online_ly=_num(_get(r, k("ONLINE SALES", "LY"))), online_cy=_num(_get(r, k("ONLINE SALES", "CY"))),
            offline_ly=_num(_get(r, k("OFFLINE SALES", "LY"))), offline_cy=_num(_get(r, k("OFFLINE SALES", "CY"))),
            margin_ly=_num(_get(r, k("TOTAL FRONT MARGIN", "LY"))), margin_cy=_num(_get(r, k("TOTAL FRONT MARGIN", "CY"))),
            qty_ly=_num(_get(r, k("TOTAL QUANTITY SOLD", "LY"))), qty_cy=_num(_get(r, k("TOTAL QUANTITY SOLD", "CY"))),
            promo_ly=_num(_get(r, k("TOTAL PROMOTION SALES", "LY"))),
            promo_cy=_num(_get(r, k("TOTAL PROMOTION SALES", "CY"))),
            waste_cy=_num(_get(r, k("TOTAL WASTE", "WASTE")))))
    res.tables["_families"] = [dict(code=f, section=s, name=n) for (f, s), n in fams.items()]
    if not store:
        res.info("no_store", "No store in this file: loaded as all stores. Choose a store in the import screen if "
                 "it is one store's report.")
    res.summary = f"{len(res.tables.get('sales_family', [])):,} families, {cy - 1} vs {cy}"
    return res


register(ReportSpec(
    key="bo_family_sales", name="BO family sales (year on year)", name_ur="فیملی سیلز", source="BO",
    tokens={"DEPARTMENT NAME": 1, "SECTION NAME": 1, "FAMILY NAME": 3, "TOTAL SALES": 2, "ONLINE SALES": 2,
            "OFFLINE SALES": 2, "TOTAL FRONT MARGIN": 2}, parse=parse_family,
    description="Family sales, margin, quantity and promotion sales, this year vs last year, online and offline."))


# =============================================================================================
# 200-10-05 store net sales: one block per store ("Store Name: HM PK LAH Fortress")
# =============================================================================================

def parse_net_sales(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    rows = sheet.all_rows()
    text = "\n".join(" ".join(clean_text(v) for v in r if not is_blank(v)) for r in rows[:6])
    period = "MTD" if re.search(r"CURR\s*-\s*MTD|\bMTD\b", text, re.I) else ("YTD" if re.search(r"\bYTD\b", text) else "DAY")
    rng = find_date_range(text)
    choose_snapshot(res, ctx, [(rng[1] if rng else None, "the Report Period")])
    dfrom = rng[0] if rng else res.snapshot_date
    unknown = Counter()
    store = None
    cols = {}
    grp: list[str] = []
    for r in rows:
        cells = [clean_text(v) for v in r]
        joined = " ".join(c for c in cells if c)
        m = re.search(r"Store Name\s*:\s*(.+?)(?:\s{2,}|$|Report Period)", joined, re.I)
        if m:
            store = _store_of(ctx, res, m.group(1).strip(), unknown)
            cols = {}
            continue
        if cells and norm(cells[0]) == "SECTION CODE NAME":
            grp = cells
            continue
        if cells and not cells[0] and "ACTUAL" in [norm(c) for c in cells] and "BUDGET" in [norm(c) for c in cells]:
            cur, out = "", {}
            for j, c in enumerate(cells):
                g = norm(grp[j]) if j < len(grp) else ""
                if g:
                    cur = g
                n = norm(c)
                key = f"{cur}|{n}" if n else cur
                out.setdefault(key, j)
            cols = out
            continue
        if not cols or not store or not cells:
            continue
        sec = section_code(cells[0]) if re.match(r"^S\d{3}", cells[0]) else ""
        if not sec:
            continue
        g = lambda key: r[cols[key]] if key in cols and cols[key] < len(r) else None
        sales = _num(g("NET SALES|ACTUAL"))
        growth = _pct(g("NET SALES|GTH %") if "NET SALES|GTH %" in cols else g("NET SALES|GTH%"), False)
        res.stores.add(store)
        res.add("sales_block", dict(
            source="200-10-05", period=period, date_from=dfrom, date_to=res.snapshot_date, level="section",
            store=store, dept="", section=sec, budget=_num(g("NET SALES|BUDGET")), sales=sales, growth_pct=growth,
            ly_sales=sales / (1 + growth / 100) if sales is not None and growth is not None and growth > -99.9 else None,
            var_budget_pct=_pct(g("NET SALES|VAR %") if "NET SALES|VAR %" in cols else g("NET SALES|VAR%"), False),
            margin_pct=_pct(g("MARGIN %|NETMRG"), False), waste_pct=_pct(g("MARGIN %|WASTE"), False),
            customers=_num(g("CUSTOMER|CUST")), penetration=_pct(g("PENT. RATE"), False), qty=_num(g("ITEM|ACTUAL")),
            avg_basket=_num(g("AVG BASKET|ACTUAL")), asp=_num(g("AVG SELLING PRICE|ACTUAL")),
            stock_value=_num(g("AVG STOCK")), oos_pct=_pct(g("OUT OF STOCK %"), False)))
    report_unknown_stores(res, unknown)
    res.summary = f"{len(res.tables.get('sales_block', [])):,} section rows, {len(res.stores)} stores, {period}"
    return res


register(ReportSpec(
    key="bo_store_net_sales", name="BO 200-10-05 store net sales", name_ur="اسٹور نیٹ سیلز", source="BO",
    tokens={"SECTION CODE NAME": 2, "NET SALES": 2, "SECTION WEIGHT": 2, "PENT. RATE": 2, "AVG BASKET": 1,
            "AVG STOCK": 1, "OUT OF STOCK %": 1}, phrases=[(r"200-10-05", 0.5), (r"STORE PERFORMANCE", 0.2)],
    parse=parse_net_sales, description="Net sales vs budget and last year by section, one block per store."))
