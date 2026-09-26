"""Finding the table inside a sheet: header rows, multi-row headers, report metadata above them.

Nothing here assumes a fixed position. The header row is the row that *looks* most like a header
(many short text cells, known column words) with rows of data under it. A group row above it
("Net Sales" spanning Actual/Budget/Gth %) or a sub-header row below it is merged in automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Sequence

from .values import clean_text, find_date_range, find_dates, is_missing, parse_num

REPORT_CODE_RE = re.compile(r"\b(\d{3}-\d{2}-\d{2}[A-Z]?)\b", re.I)


def norm(s: Any) -> str:
    t = clean_text(s).upper()
    t = re.sub(r"[\"'`]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip(" :.-_")


def is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def non_empty(row: Sequence[Any]) -> list[int]:
    return [i for i, v in enumerate(row) if not is_blank(v)]


def is_numberish(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float, date, datetime)):
        return True
    s = clean_text(v)
    if not s:
        return False
    if is_missing(s) and s not in ("",):
        return True  # #DIV/0!, NA... sit in number columns
    return parse_num(s).value is not None


def row_text(row: Sequence[Any]) -> str:
    return " ".join(clean_text(v) for v in row if not is_blank(v))


def trim_row(row: Sequence[Any]) -> list[Any]:
    r = list(row)
    while r and is_blank(r[-1]):
        r.pop()
    return r


@dataclass
class Header:
    row: int                       # index of the last header row (data starts after it)
    columns: list[str]             # combined, cleaned column names
    raw: list[list[str]]           # the header rows used, top to bottom
    score: float = 0.0


@dataclass
class Table:
    columns: list[str]
    rows: list[list[Any]]
    header: Header
    meta: dict = field(default_factory=dict)

    def idx(self, *names: str, contains: bool = True, default: int | None = None) -> int | None:
        return find_col(self.columns, *names, contains=contains, default=default)

    def col(self, i: int | None) -> list[Any]:
        if i is None:
            return [None] * len(self.rows)
        return [r[i] if i < len(r) else None for r in self.rows]


def find_col(columns: Sequence[str], *names: str, contains: bool = True, default: int | None = None) -> int | None:
    """Find a column by any of several names: exact match first, then prefix, then contains."""
    ncols = [norm(c) for c in columns]
    wanted = [norm(n) for n in names if n]
    for w in wanted:
        for i, c in enumerate(ncols):
            if c == w:
                return i
    for w in wanted:
        for i, c in enumerate(ncols):
            if c.startswith(w + " ") or c.startswith(w + "|") or c.endswith("| " + w) or c.endswith("|" + w):
                return i
    if contains:
        for w in wanted:
            if len(w) < 3:
                continue
            for i, c in enumerate(ncols):
                if w in c:
                    return i
    return default


def header_score(rows: list[list[Any]], i: int, vocab: set[str]) -> float:
    row = rows[i]
    cells = [v for v in row if not is_blank(v)]
    if len(cells) < 2:
        return 0.0
    text_cells = [v for v in cells if isinstance(v, str) and not is_numberish(v)]
    ratio = len(text_cells) / len(cells)
    if ratio < 0.55:
        return 0.0
    hits = sum(1 for v in text_cells if norm(v) in vocab)
    short = sum(1 for v in text_cells if len(clean_text(v)) <= 40)
    below = rows[i + 1:i + 8]
    numeric_below = 0.0
    for r in below:
        ne = [v for v in r if not is_blank(v)]
        if ne:
            numeric_below += sum(1 for v in ne if is_numberish(v)) / len(ne)
    # a long sentence in one cell is a title, not a header
    long_text = sum(1 for v in text_cells if len(clean_text(v)) > 60)
    return hits * 6 + short * 1.0 + numeric_below * 3 + min(len(cells), 40) * 0.2 - long_text * 3


def find_header(rows: list[list[Any]], vocab: Iterable[str] = (), max_scan: int = 80) -> Header | None:
    vocab_n = {norm(v) for v in vocab}
    best_i, best_s = None, 0.0
    for i in range(min(len(rows), max_scan)):
        s = header_score(rows, i, vocab_n)
        if s > best_s:
            best_i, best_s = i, s
    if best_i is None:
        return None
    top = best_i
    raw_rows = [rows[best_i]]
    last = best_i
    # sub-header row below (mostly text, data right after it)
    if best_i + 1 < len(rows):
        nxt = rows[best_i + 1]
        ne = [v for v in nxt if not is_blank(v)]
        if len(ne) >= 2 and sum(1 for v in ne if not is_numberish(v)) / len(ne) >= 0.6:
            after = rows[best_i + 2:best_i + 6]
            dens = [sum(1 for v in r if is_numberish(v)) / max(1, len(non_empty(r))) for r in after if non_empty(r)]
            if dens and sum(dens) / len(dens) >= 0.4:
                raw_rows.append(nxt)
                last = best_i + 1
    # group row above (fewer cells, all text, not a "Key: value" metadata line)
    if top > 0:
        above = rows[top - 1]
        ne = non_empty(above)
        if 1 <= len(ne) < len(non_empty(rows[top])) and all(isinstance(above[j], str) and not is_numberish(above[j]) for j in ne):
            txt = row_text(above)
            datey = any(re.fullmatch(r"\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}.*", clean_text(above[j])) for j in ne)
            if ":" not in txt and not REPORT_CODE_RE.search(txt) and len(ne) >= 2 and not datey:
                raw_rows.insert(0, above)
    width = max(len(r) for r in raw_rows)
    layers = []
    for r in raw_rows:
        r = list(r) + [None] * (width - len(r))
        layers.append([clean_text(v) for v in r])
    # forward-fill group labels across the columns they span (only for rows above the last one)
    filled = []
    for li, layer in enumerate(layers):
        if li < len(layers) - 1 and len(layers) > 1:
            cur = ""
            out = []
            for j, v in enumerate(layer):
                if v:
                    cur = v
                # stop the span where the lower row is also empty (a gap between groups)
                out.append(cur if (v or any(l[j] for l in layers[li + 1:])) else "")
            filled.append(out)
        else:
            filled.append(layer)
    columns = []
    for j in range(width):
        parts = [filled[li][j] for li in range(len(filled)) if filled[li][j]]
        dedup = []
        for p in parts:
            if not dedup or dedup[-1] != p:
                dedup.append(p)
        columns.append(" | ".join(dedup))
    # make empty and duplicate names unique but recognisable
    seen: dict[str, int] = {}
    for j, c in enumerate(columns):
        if not c:
            c = f"Column {j + 1}"
        k = c.upper()
        if k in seen:
            seen[k] += 1
            c = f"{c} ({seen[k]})"
        else:
            seen[k] = 1
        columns[j] = c
    return Header(row=last, columns=columns,
                  raw=[[clean_text(v) for v in r] for r in raw_rows], score=best_s)


def extract_meta(rows: list[list[Any]], upto: int | None = None) -> dict:
    """Pick up 'Key : value' lines, report codes, dates and titles from the top of a sheet."""
    meta: dict = {"pairs": {}, "text": "", "report_code": None, "dates": [], "range": None, "title": ""}
    lines = []
    for r in rows[: (upto if upto is not None else 25)]:
        ne = non_empty(r)
        if not ne:
            continue
        cells = [clean_text(r[j]) for j in ne]
        line = " ".join(cells)
        lines.append(line)
        # "Key", "", "Value" layout
        if len(cells) >= 2 and len(cells[0]) <= 40 and not is_numberish(cells[0]):
            meta["pairs"].setdefault(norm(cells[0]), cells[1])
        # "Key: value" inside cells
        for c in cells:
            m = re.match(r"^([A-Za-z][A-Za-z .()/&]{1,40}?)\s*:\s*(.+)$", c)
            if m:
                meta["pairs"].setdefault(norm(m.group(1)), m.group(2).strip())
        if not meta["title"] and len(cells) == 1 and len(cells[0]) > 8:
            meta["title"] = cells[0]
    text = "\n".join(lines)
    meta["text"] = text
    m = REPORT_CODE_RE.search(text)
    if m:
        meta["report_code"] = m.group(1).upper()
    meta["range"] = find_date_range(text)
    meta["dates"] = find_dates(text)
    return meta


def build_table(rows: list[list[Any]], header: Header, stop_blank_run: int = 0) -> Table:
    data = []
    blank_run = 0
    for r in rows[header.row + 1:]:
        if not any(c is not None and c != "" and not (type(c) is str and not c.strip()) for c in r):
            blank_run += 1
            if stop_blank_run and blank_run >= stop_blank_run and data:
                break
            continue
        blank_run = 0
        rr = list(r) + [None] * (len(header.columns) - len(r))
        data.append(rr)
    return Table(columns=header.columns, rows=data, header=header)
