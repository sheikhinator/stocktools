"""Fallback for tables that are recognised but not analysed yet, or not recognised at all.

Nothing is thrown away: the table is found, its columns are profiled from their values (store, date,
item code, section, percentage, money, quantity, text) and every row is kept as JSON so a later version
can analyse it without re-importing.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime

from ..grid import find_header, build_table, extract_meta
from ..reader import Sheet
from ..spec import ParseContext, ParseResult
from ..values import clean_text, infer_date_format, is_missing, parse_num, section_code
from .common import choose_snapshot

MAX_RAW_ROWS = 300_000


def profile_column(name: str, values: list, resolver) -> tuple[str, float]:
    """Guess what a column holds from its values. Returns (kind, confidence)."""
    vals = [v for v in values if v not in (None, "") and not is_missing(v)][:400]
    if not vals:
        return "empty", 1.0
    n = len(vals)
    strs = [clean_text(v) for v in vals]
    stores = sum(1 for s in strs[:150] if resolver.resolve(s).code)
    if stores / min(n, 150) >= 0.8:
        return "store", stores / min(n, 150)
    nums = [parse_num(v) for v in vals]
    numeric = [x for x in nums if x.value is not None]
    g = infer_date_format(vals)
    if g.fmt and g.parsed / n >= 0.9 and (g.fmt not in ("excel",) or "DAT" in name.upper() or "DATE" in name.upper()):
        if not (g.fmt in ("yymmdd", "ddmmyy", "mmddyy") and len(numeric) == n and len(set(strs)) > n * 0.9
                and "DAT" not in name.upper()):
            return f"date ({g.fmt})", g.parsed / n
    if len(numeric) / n >= 0.9:
        if any(x.percent for x in numeric):
            return "percent", 0.95
        ints = [x.value for x in numeric]
        if all(float(v).is_integer() and 100000 <= v <= 999999 for v in ints) and len(set(ints)) > 0.7 * len(ints):
            return "item code", 0.8
        if all(float(v).is_integer() for v in ints):
            if all(0 <= v <= 99 for v in ints) and len(set(ints)) <= 10:
                return "code", 0.6
            return "quantity", 0.7
        if max(abs(v) for v in ints) > 1000:
            return "money", 0.6
        return "number", 0.6
    if sum(1 for s in strs if section_code(s) and re.match(r"^S\d{3}", s)) / n >= 0.8:
        return "section", 0.9
    if all(len(s) <= 3 and s.isupper() for s in strs) and len(set(strs)) <= 12:
        return "status code", 0.7
    return "text", 0.5


def parse_generic(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    rows = sheet.all_rows()
    h = find_header(rows, [])
    if h is None:
        res.error("no_table", "No table found in this sheet.")
        return res
    t = build_table(rows, h)
    meta = extract_meta(rows, upto=max(h.row - len(h.raw) + 1, 0))
    d = None
    for key in ("END DATE", "TO DATE", "TODAT", "STOCK AS OF", "STOCK AS AT", "REPORT DATE", "DATE"):
        v = meta["pairs"].get(key)
        if v:
            from ..values import find_dates, parse_date
            ds_ = find_dates(v)
            d = max(ds_) if ds_ else parse_date(v)
            if d:
                break
    if d is None and meta.get("range"):
        d = meta["range"][1]
    if d is None:
        run = " ".join(v for k, v in meta["pairs"].items() if "RUN" in k or "TIME" in k)
        from ..values import find_dates
        runs = set(find_dates(run))
        ds = [x for x in meta.get("dates", []) if x not in runs]
        d = max(ds) if ds else None
    choose_snapshot(res, ctx, [(d, "the header of the report")])
    cols = t.columns
    kinds = {}
    for j, c in enumerate(cols):
        kinds[c] = profile_column(c, t.col(j), ctx.resolver)
    store_cols = [c for c, (k, _) in kinds.items() if k == "store"]
    if store_cols:
        j = cols.index(store_cols[0])
        for v in t.col(j)[:5000]:
            m = ctx.resolver.resolve(v)
            if m.code:
                res.stores.add(m.code)
    elif ctx.store:
        res.stores.add(ctx.store)
    for i, r in enumerate(t.rows[:MAX_RAW_ROWS]):
        rec = {}
        for j, c in enumerate(cols):
            v = r[j] if j < len(r) else None
            if v in (None, ""):
                continue
            if isinstance(v, (date, datetime)):
                v = v.isoformat()
            rec[c] = v
        if rec:
            res.add("raw_row", dict(row_no=i, data=json.dumps(rec, ensure_ascii=False, default=str)))
    if len(t.rows) > MAX_RAW_ROWS:
        res.warn("truncated", f"Only the first {MAX_RAW_ROWS:,} rows were kept.", len(t.rows) - MAX_RAW_ROWS)
    res.info("columns", "Columns found: " + "; ".join(f"{c} = {k}" for c, (k, _) in list(kinds.items())[:40]))
    res.summary = f"{len(t.rows):,} rows kept for later analysis ({len(cols)} columns)"
    return res
