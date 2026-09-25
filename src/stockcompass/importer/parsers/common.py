"""Helpers shared by the report parsers."""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

from ..grid import Table, build_table, extract_meta, find_header, norm
from ..reader import Sheet
from ..spec import ParseContext, ParseResult
from ..values import clean_text, date_column, infer_date_format, parse_date

SEASON_RE = re.compile(r"\b([WSEA])0?(2\d)(?:\b|\d\b)")


def load_table(sheet: Sheet, vocab: Iterable[str], stop_blank_run: int = 0) -> Table | None:
    rows = sheet.all_rows()
    h = find_header(rows, vocab)
    if h is None:
        return None
    t = build_table(rows, h, stop_blank_run=stop_blank_run)
    t.meta = extract_meta(rows, upto=max(h.row - len(h.raw) + 1, 0))
    return t


def season_of(desc: str) -> str:
    """'LC BOYS QUILTED MOCK NECK SL W025' -> 'W25' (W=winter, S=summer, E=eid, A=autumn)."""
    m = SEASON_RE.search((desc or "").upper())
    return f"{m.group(1)}{m.group(2)}" if m else ""


def date_from_filename(name: str, ref: date) -> date | None:
    stem = Path(name).stem
    for rx, fmt in [(r"(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})", "ymd"), (r"(\d{1,2})[-_.](\d{1,2})[-_.](20\d{2}|\d{2})", "dmy")]:
        m = re.search(rx, stem)
        if m:
            a, b, c = (int(x) for x in m.groups())
            try:
                if fmt == "ymd":
                    return date(a, b, c)
                y = c + 2000 if c < 100 else c
                return date(y, b, a)
            except ValueError:
                pass
    m = re.search(r"(?<!\d)(\d{6})(?!\d)", stem)
    if m:
        g = infer_date_format([m.group(1)], ref=ref)
        if g.fmt:
            return parse_date(m.group(1), g.fmt)
    return None


def store_from_filename(name: str, resolver) -> str | None:
    stem = Path(name).stem
    toks = [t for t in re.split(r"[^A-Za-z0-9&]+", stem) if t]
    found = set()
    for n in (3, 2, 1):
        for i in range(len(toks) - n + 1):
            chunk = " ".join(toks[i:i + n])
            if n == 1 and (chunk.isdigit() and len(chunk) != 3):
                continue
            m = resolver.resolve(chunk)
            if m.code and m.confidence >= 0.99:
                found.add(m.code)
        if found:
            break
    return found.pop() if len(found) == 1 else None


def choose_snapshot(res: ParseResult, ctx: ParseContext, candidates: list[tuple[date | None, str]]):
    """User's choice wins; then evidence from the data; then the file name; then the file date."""
    if ctx.snapshot_date:
        res.snapshot_date = ctx.snapshot_date
        return
    for d, src in candidates:
        if d:
            res.snapshot_date = d
            res.info("date_source", f"Report date {d:%d %b %Y} taken from {src}.")
            return
    fd = date_from_filename(ctx.file_name, ctx.ref_date)
    if fd:
        res.snapshot_date = fd
        res.info("date_source", f"Report date {fd:%d %b %Y} taken from the file name.")
        return
    if ctx.file_date:
        res.snapshot_date = ctx.file_date
        res.warn("date_guess", f"No date inside the file. Using the file's saved date {ctx.file_date:%d %b %Y}; "
                               "change it in the import screen if that is wrong.")
        return
    res.snapshot_date = ctx.ref_date
    res.warn("date_guess", "No date found. Using today; change it in the import screen if that is wrong.")


def mode_date(values: Iterable[date | None]) -> date | None:
    c = Counter(v for v in values if v)
    return c.most_common(1)[0][0] if c else None


def colget(row: list[Any], i: int | None):
    if i is None or i >= len(row):
        return None
    return row[i]


def dates_of(tbl: Table, i: int | None, ref: date, prefer: list[str] | None = None) -> list[date | None]:
    if i is None:
        return [None] * len(tbl.rows)
    vals, _ = date_column(tbl.col(i), ref=ref, prefer=prefer)
    return vals


def text(v: Any) -> str:
    return clean_text(v)


def upper(v: Any) -> str:
    return clean_text(v).upper()


def resolve_store_value(res: ParseResult, resolver, v: Any, unknown: Counter) -> str | None:
    m = resolver.resolve(v)
    if m.code:
        return m.code
    if m.kind in ("closed", "channel"):
        unknown[f"{text(v)} ({m.kind})"] += 1
    elif text(v):
        unknown[text(v)] += 1
    return None


def report_unknown_stores(res: ParseResult, unknown: Counter):
    closed = {k: v for k, v in unknown.items() if k.endswith("(closed)") or k.endswith("(channel)")}
    other = {k: v for k, v in unknown.items() if k not in closed}
    if closed:
        res.info("skipped_nonstores", "Skipped closed stores / non-store channels: " + ", ".join(sorted(closed)),
                 sum(closed.values()))
    if other:
        res.warn("unknown_store", "Store names not recognised (rows skipped). Map them once in Settings > Stores: "
                 + ", ".join(sorted(other)[:12]), sum(other.values()), detail="|".join(sorted(other)))


def within_week(d: date, ref: date) -> bool:
    return abs((d - ref).days) <= 7


__all__ = ["load_table", "season_of", "choose_snapshot", "mode_date", "colget", "dates_of", "text", "upper",
           "store_from_filename", "date_from_filename", "resolve_store_value", "report_unknown_stores", "norm",
           "timedelta"]
