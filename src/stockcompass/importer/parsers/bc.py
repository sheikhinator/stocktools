"""BC workbook (business cycle team): the weekly scorecard, plus the supporting tabs (kept as raw rows)."""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

from stockcompass.master.seed import BC_INDICATORS

from ..grid import extract_meta, is_blank, non_empty, norm
from ..reader import Sheet
from ..spec import ParseContext, ParseResult, ReportSpec, register
from ..values import clean_text, find_dates, num, parse_num, percent_column
from .common import choose_snapshot

SC_TOKENS = {"MAIN INDICATORS": 3, "TARGETS": 2, "ZERO STOCK %": 2, "NO. OF GREENS": 3, "STOCK DAYS": 1,
             "SUPPLIER SERVICE LEVEL %": 2, "PURGED LPO %": 2, "LEAFLET ZERO STOCK": 1}

_MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


def indicator_key(label: str) -> tuple[str | None, str]:
    n = norm(label)
    n2 = re.sub(r"\s+", " ", n.replace("%", "").strip())
    best, best_len = None, 0
    for ind in BC_INDICATORS:
        for m in ind["match"]:
            mm = norm(m).replace("%", "").strip()
            if mm and mm in n2 and len(mm) > best_len:
                best, best_len = ind["key"], len(mm)
    return best, n


def parse_scorecard(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    rows = sheet.all_rows()
    hdr = None
    for i, r in enumerate(rows[:40]):
        if any(norm(v) == "MAIN INDICATORS" for v in r):
            hdr = i
            break
    if hdr is None:
        res.error("no_header", "Could not find the 'Main Indicators' row.")
        return res
    head = rows[hdr]
    width = max(len(r) for r in rows[: hdr + 40])
    # 1) which column is which store: a row of GIMA codes above wins; else the header names
    col_store: dict[int, str] = {}
    for r in rows[max(0, hdr - 4):hdr]:
        codes = {}
        for j, v in enumerate(r):
            s = clean_text(v).upper()
            if s and ctx.resolver.resolve(s).reason == "GIMA code":
                codes[j] = ctx.resolver.resolve(s).code
        if len(codes) >= 5:
            col_store = codes
            break
    unknown = Counter()
    targets: list[int] = []
    avg_cols: dict[int, str] = {}
    for j, v in enumerate(head):
        n = norm(v)
        if not n:
            continue
        if n.startswith("TARGET"):
            targets.append(j)
        elif "AVG" in n:
            avg_cols[j] = n
        elif j not in col_store and n != "MAIN INDICATORS":
            m = ctx.resolver.resolve(clean_text(v))
            if m.code:
                col_store[j] = m.code
            else:
                unknown[clean_text(v)] += 1
    if not col_store:
        res.error("no_stores", "No store columns recognised in the scorecard.")
        return res
    # Blocks: each format starts with its 'Avg.' column; its 'Targets' column (if any) sits right before it.
    avg_sorted = sorted(avg_cols)

    def block_of(j):
        left = [a for a in avg_sorted if a <= j]
        return max(left) if left else None

    def target_col(j):
        b = block_of(j)
        if b is None:
            left = [t for t in targets if t < j]
            return max(left) if left else None
        cand = [t for t in targets if t < b and (b - t) <= 2 and not any(t < a < b for a in avg_sorted)]
        return max(cand) if cand else None

    # 2) period and date
    meta = extract_meta(rows, upto=hdr + 1)
    title = meta.get("title") or ""
    m = re.search(r"(MTD|WTD|YTD)[\s\-]*([A-Za-z]{3})[A-Za-z]*[\s\-]*(\d{4})", meta["text"], re.I)
    period = m.group(0).upper().replace(" ", "") if m else ""
    all_text = "\n".join(" ".join(clean_text(v) for v in r if not is_blank(v)) for r in rows[: min(len(rows), 120)])
    ds = [d for d in find_dates(all_text) if abs((d - ctx.ref_date).days) < 400]
    snap = max(ds) if ds else None
    if snap is None and m:
        mon = _MONTHS.index(m.group(2).upper()[:3]) + 1
        y = int(m.group(3))
        import calendar
        snap = date(y, mon, calendar.monthrange(y, mon)[1])
        if snap > ctx.ref_date:
            snap = ctx.ref_date
    choose_snapshot(res, ctx, [(snap, "the dates printed in the scorecard")])
    res.stores |= set(col_store.values())
    # 3) indicator rows
    file_targets = {}
    copied = Counter()
    for r in rows[hdr + 1:]:
        ne = non_empty(r)
        if not ne:
            continue
        label = clean_text(r[ne[0]]) if ne[0] <= 1 else ""
        if not label:
            continue
        nl = norm(label)
        if nl.startswith("NO. OF GREENS"):
            for j, st in col_store.items():
                v = parse_num(r[j]).value if j < len(r) else None
                if v is not None:
                    res.add("bc_value", dict(period=period, store=st, indicator="_greens", label="No. of greens (BC)",
                                             value=v, raw=clean_text(r[j])))
            break
        if nl.startswith("STORE"):
            break
        key, _ = indicator_key(label)
        cols = sorted(set(col_store) | set(avg_cols) | set(targets))
        raw = [r[j] if j < len(r) else None for j in cols]
        is_pct = "STOCK DAYS" not in nl
        vals = percent_column(raw) if is_pct else [parse_num(v).value for v in raw]
        by_col = dict(zip(cols, vals))
        for j, st in col_store.items():
            v = by_col.get(j)
            rawv = clean_text(r[j]) if j < len(r) else ""
            res.add("bc_value", dict(period=period, store=st, indicator=key or f"other:{nl[:40]}", label=label,
                                     value=v, raw=rawv))
            tj = target_col(j)
            if key and tj is not None and by_col.get(tj) is not None:
                fmt = ctx.resolver.format_of(st)
                file_targets[(key, fmt)] = by_col[tj]
            # a store cell equal to an average column of ANOTHER format = copied from the wrong row
            if v is not None and v not in (0, 100) and round(v, 2) != round(v):
                for aj, an in avg_cols.items():
                    if by_col.get(aj) is not None and round(by_col[aj], 2) == round(v, 2) and aj != block_of(j):
                        copied[(st, label)] += 1
    res.tables["_bc_targets_file"] = [dict(indicator=k, format=f, target=t) for (k, f), t in file_targets.items()]
    for (st, label), _ in copied.items():
        res.warn("copied_value", f"Store {st}, '{label}': the value is exactly another format's average. "
                 "Check it in the BC workbook; it may have been copied from the wrong row.")
    if unknown:
        res.info("unknown_columns", "Scorecard columns not matched to a store: " + ", ".join(sorted(unknown)))
    n = len(res.tables.get("bc_value", []))
    res.summary = f"{n:,} scorecard values, {len(res.stores)} stores, period {period or '?'}"
    return res


register(ReportSpec(
    key="bc_scorecard", name="BC scorecard (weekly indicators)", name_ur="بی سی اسکور کارڈ", source="BC workbook",
    tokens=SC_TOKENS, required=["MAIN INDICATORS"], parse=parse_scorecard,
    phrases=[(r"WEEKLY INDICATORS", 0.3)],
    description="Every BC indicator per store with its target, as sent by the BC team."))


def _bc(key, name, name_ur, tokens, phrases=()):
    register(ReportSpec(key=key, name=name, name_ur=name_ur, source="BC workbook", tokens=tokens,
                        phrases=list(phrases), analysed=False,
                        description="Supporting tab of the BC workbook. Kept for reference; Stock Compass "
                                    "recalculates it from GIMA files where possible."))


_bc("bc_eol", "BC EOL stock tab", "ای او ایل اسٹاک",
    {"AST1 EOL VALUE": 3, "007 PERMANENT EOL": 3, "COMBINED EOL VALUE": 3, "COMBINED EOL %": 2, "TOTAL STOCK VALUE": 1})
_bc("bc_purge_ssl", "BC purge and SSL tab", "پرج اور ایس ایس ایل",
    {"COUNT OF LPO": 2, "NO. OF LPO PURGED": 3, "PURGE %": 2, "SUM OF QTY ORD": 2, "SUM OF QTY RCV": 2, "SSL %": 2,
     "GT LOW VALUE": 1})
_bc("bc_sleeping", "BC sleeping stock tab", "سلیپنگ اسٹاک",
    {"STR TYPE": 2, "STR NAME": 1, "DEP NAME": 1, "NON FOOD AVG.": 3, "FMCG": 1, "LHH": 1},
    [(r"SLE+PING STOCK", 0.4)])
_bc("bc_label_survey", "BC label survey tab", "لیبل سروے",
    {"XCID": 3, "LBLCNT": 3, "STRCNT": 2, "PRCMAT": 2, "NOLBL": 2, "NOITM": 2, "PERQC": 2, "XPER": 1})
