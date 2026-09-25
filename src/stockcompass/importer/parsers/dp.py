"""DP (depreciation / aged stock) workbook: the item-level master, plus the summary tabs (kept as raw rows)."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from ..reader import Sheet
from ..spec import ParseContext, ParseResult, ReportSpec, register
from ..values import clean_text, code_text, dept_code, family_code, find_dates, item_code, num, pct_value, section_code
from .common import choose_snapshot, colget, load_table, report_unknown_stores, resolve_store_value, season_of, text, upper

DP_TOKENS = {"ITEMPR": 2, "AGNGPR": 3, "CPVAL": 3, "DEPPC": 3, "DEP PROVISION": 3, "PHQTPR": 1, "CSTPPR": 1,
             "SELPPR": 1, "MONTHS": 1, "HIGH RISK %AGE": 1, "STORES": 1, "L31": 1, "G720": 1}

BUCKET_FROM = [(0, "L31"), (31, "L91"), (91, "L181"), (181, "L271"), (271, "L361"), (361, "L541"), (541, "L721"),
               (721, "G720")]


def bucket_start(age: int) -> int:
    start = 0
    for fd, _ in BUCKET_FROM:
        if age >= fd:
            start = fd
    return start


def parse_dp_master(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    t = load_table(sheet, DP_TOKENS)
    if t is None:
        res.error("no_header", "Could not find the column header row.")
        return res
    I = lambda *n: t.idx(*n, contains=False)
    ci = dict(when=I("REPORT DATE"), sname=I("STORES NAMES", "STORE NAME"), st=I("STORES", "STORE", "STR"),
              dept=I("DEPTPR"), sec=I("SECTPR"), secname=I("SECTION NAMES"), fam=I("FAMIPR"), item=I("ITEMPR"),
              desc=I("IDSCPR"), sup=I("SUPPPR"), qty=I("PHQTPR"), status=I("ITMSTS"), cost=I("CSTPPR"),
              price=I("SELPPR"), value=I("CPVAL"), rot=I("ROT"), rng=I("RANGE"), age=I("AGNGPR"),
              prov=I("DEP PROVISION"), pct=I("DEPPC"), months=I("MONTHS"), risk=I("HIGH RISK %AGE"))
    if ci["item"] is None or ci["value"] is None:
        res.error("missing_columns", "Item (ITEMPR) or DP value (CPVAL) column not found.")
        return res
    # Workbook-level hint like "Stock as at 20 Sep" is passed in ctx.settings by the pipeline
    hint = ctx.settings.get("workbook_date")
    choose_snapshot(res, ctx, [(hint, "the workbook summary ('Stock as at …')")])
    months = Counter(upper(colget(r, ci["when"])) for r in t.rows) if ci["when"] is not None else Counter()
    keep_month = None
    if len(months) > 1:
        keep_month = "CURRENT MONTH" if "CURRENT MONTH" in months else months.most_common(1)[0][0]
        res.info("other_month_rows", f"Only '{keep_month.title()}' rows loaded; other months skipped.",
                 sum(v for k, v in months.items() if k != keep_month))
    unknown = Counter()
    obs: dict[tuple[str, int], Counter] = defaultdict(Counter)
    prov_bad = 0
    for r in t.rows:
        if keep_month and upper(colget(r, ci["when"])) != keep_month:
            continue
        it = item_code(colget(r, ci["item"]))
        if not it:
            continue
        ref = colget(r, ci["st"]) if ci["st"] is not None else colget(r, ci["sname"])
        st = resolve_store_value(res, ctx.resolver, ref, unknown)
        if not st and ci["sname"] is not None:
            st = resolve_store_value(res, ctx.resolver, colget(r, ci["sname"]), Counter())
        if not st:
            continue
        res.stores.add(st)
        dept = dept_code(colget(r, ci["dept"]))
        sec = section_code(colget(r, ci["sec"]))
        desc = text(colget(r, ci["desc"]))
        age = num(colget(r, ci["age"]))
        value = num(colget(r, ci["value"]))
        prov = num(colget(r, ci["prov"]))
        pct = pct_value(colget(r, ci["pct"]), fraction_hint=False)
        if pct is not None and 0 < pct <= 1 and prov and value and abs(prov / value - pct) < 0.02:
            pct *= 100  # stored as a fraction
        if age is not None and pct is not None:
            obs[(f"{dept}:{sec}", bucket_start(int(age)))][round(pct)] += 1
            obs[(dept, bucket_start(int(age)))][round(pct)] += 1
        if value and pct is not None and prov is not None and abs(value * pct / 100 - prov) > max(2, abs(prov) * 0.02):
            prov_bad += 1
        res.items[it] = dict(description=desc, dept=dept, section=sec, family=family_code(colget(r, ci["fam"])),
                             supplier=code_text(colget(r, ci["sup"])), season=season_of(desc))
        res.add("dp_item", dict(snap_date=res.snapshot_date, store=st, item=it, qty=num(colget(r, ci["qty"])),
                                cost=num(colget(r, ci["cost"])), price=num(colget(r, ci["price"])), value=value,
                                age_days=int(age) if age is not None else None, provision=prov, prov_pct=pct,
                                bucket=text(colget(r, ci["months"])), rot=num(colget(r, ci["rot"])),
                                high_risk=pct_value(colget(r, ci["risk"]), fraction_hint=True),
                                status=upper(colget(r, ci["status"])), range_code=code_text(colget(r, ci["rng"]))))
    report_unknown_stores(res, unknown)
    if prov_bad:
        res.warn("provision_check", "Rows where provision is not DP value x provision %.", prov_bad)
    # Learn the provision table from the data (most common % per department/section and age step)
    learned = []
    for (key, start), cnt in obs.items():
        pct, n = cnt.most_common(1)[0]
        if n >= 3 and pct > 0:
            learned.append((key, start, float(pct), n))
    res.tables["_dp_rules_observed"] = [dict(rule_key=k, from_day=s, pct=p, n=n) for k, s, p, n in learned]
    rows = res.tables.get("dp_item", [])
    tv = sum(x["value"] or 0 for x in rows)
    tp = sum(x["provision"] or 0 for x in rows)
    res.summary = f"{len(rows):,} DP item-store rows; DP stock {tv:,.0f}; provision {tp:,.0f}"
    return res


register(ReportSpec(
    key="dp_master", name="DP master data (item level)", name_ur="ڈی پی ماسٹر ڈیٹا (آئٹم)", source="DP workbook",
    tokens=DP_TOKENS, required=["CPVAL"], parse=parse_dp_master,
    description="Every aged (DP) item per store with age, DP value and provision."))


def _dp_tab(key, name, name_ur, tokens, phrases=()):
    register(ReportSpec(key=key, name=name, name_ur=name_ur, source="DP workbook", tokens=tokens,
                        phrases=list(phrases), analysed=False,
                        description="Summary tab of the DP workbook. Kept for reference; Stock Compass recalculates "
                                    "it from the DP master data."))


_dp_tab("dp_summary", "DP summary (department)", "ڈی پی خلاصہ",
        {"DEPT.": 1, "PROVISION": 1, "STOCK": 1, "STOCK AGING": 2, "3 TO 6 MONTHS": 2, "6 TO 12 MONTHS": 2,
         "ABOVE 12 MONTHS": 2}, [(r"DEPARTMENT WISE SUMMARY", 0.4)])
_dp_tab("dp_aging_store", "DP ageing by store", "اسٹور کے حساب سے ڈی پی ایجنگ",
        {"STORE": 1, "6 MONTHS STOCK IN AGING": 3, "9 MONTHS STOCK IN AGING": 3, "1 YEAR STOCK IN AGING": 2,
         "GRAND TOTAL": 1})
_dp_tab("dp_comparison", "DP comparison vs last month", "ڈی پی موازنہ",
        {"STORE": 1, "DEPT.": 1, "PROVISION ADDED IN CURRENT MONTH": 3, "STOCK RESOLVED IN CURRENT MONTH": 3,
         "ACTUAL STOCK FOR NOW": 2, "CLOSING STOCK 31 AUG": 1})
_dp_tab("dp_top50", "Top 50 DP items", "ٹاپ 50 ڈی پی آئٹمز",
        {"SR. #": 1, "ITEM CODE": 1, "DEPRECIATION STOCK": 3, "PROVISION AGAINST DEP STOCK": 3, "QTY": 1})
_dp_tab("dp_high_risk", "DP high risk items", "ہائی رسک ڈی پی آئٹمز",
        {"HIGH RISK %AGE": 3, "DEPRECIATION STOCK": 2, "DEP PROV AMOUNT": 3, "ITEM CODE": 1, "CRITERIA": 1})


def workbook_date_hint(texts: list[str], ref) -> object:
    """Find 'Stock as at 20 Sep' / 'Stock as of 9/22/2026' anywhere in the workbook."""
    for tx in texts:
        m = re.search(r"(?:STOCK\s+)?AS\s+(?:AT|OF)\s*:?\s*([0-9]{1,2}[\s\-/][A-Za-z]{3,9}(?:[\s\-/,]+\d{2,4})?|"
                      r"\d{1,2}/\d{1,2}/\d{2,4})", tx, re.I)
        if m:
            s = m.group(1)
            if re.fullmatch(r"\d{1,2}[\s\-/][A-Za-z]{3,9}", s.strip()):
                s = f"{s.strip()} {ref.year}"
            ds = find_dates(s)
            if ds:
                d = ds[0]
                if d > ref:  # "20 Sep" read in January belongs to last year
                    d = d.replace(year=d.year - 1)
                return d
    return None
