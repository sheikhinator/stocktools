"""Open any report file and expose every table inside it as a grid of cells.

Sources handled:
- .xlsx / .xlsm / .xlsb / .xls / .ods through calamine (fast, reads hidden and very hidden sheets)
- pivot caches inside .xlsx: the rows behind a pivot table, even when the source sheet is hidden
  or deleted ("double-click the grand total" without clicking anything)
- .xls files that are really HTML tables (common for BO/web exports) and .htm/.html
- .csv / .txt / .tsv with any delimiter and encoding (UTF-8, UTF-16, Windows-1252)
- text pasted from the clipboard
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterator
from xml.etree import ElementTree as ET

HEAD_ROWS = 400

Row = list[Any]


@dataclass
class Sheet:
    name: str
    kind: str                      # sheet | pivot | csv | html | paste
    hidden: bool = False
    head: list[Row] = field(default_factory=list)
    n_rows: int | None = None
    _rows: Callable[[], Iterator[Row]] | None = None
    note: str = ""

    def rows(self) -> Iterator[Row]:
        if self._rows is None:
            yield from self.head
        else:
            yield from self._rows()

    def all_rows(self) -> list[Row]:
        return list(self.rows())


@dataclass
class Workbook:
    path: Path
    sheets: list[Sheet]
    file_hash: str
    warnings: list[str] = field(default_factory=list)


def file_hash(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def open_file(path: str | Path) -> Workbook:
    path = Path(path)
    head = path.open("rb").read(4096)
    warnings: list[str] = []
    sheets: list[Sheet] = []
    ext = path.suffix.lower()
    kind = sniff(head, ext)
    if kind == "zip-xlsx":
        sheets += _calamine_sheets(path, warnings)
        try:
            sheets += _pivot_sheets(path, warnings)
        except Exception as e:  # pivot caches are a bonus, never fatal
            warnings.append(f"Pivot data could not be read: {e}")
    elif kind in ("ole-xls", "zip-other"):
        sheets += _calamine_sheets(path, warnings)
    elif kind == "html":
        sheets += _html_sheets(path.read_bytes(), warnings)
    else:
        sheets += _text_sheets(path.read_bytes(), path.name, warnings)
    if not sheets:
        warnings.append("No tables found in this file.")
    return Workbook(path=path, sheets=sheets, file_hash=file_hash(path), warnings=warnings)


def from_text(text: str, name: str = "Pasted data") -> Workbook:
    sheets = _text_sheets(text.encode("utf-8"), name, [], kind="paste")
    return Workbook(path=Path(name), sheets=sheets, file_hash=hashlib.sha1(text.encode()).hexdigest())


def sniff(head: bytes, ext: str) -> str:
    if head.startswith(b"PK"):
        return "zip-xlsx"  # xlsx/xlsm/xlsb/ods; pivot-cache reading simply finds nothing in non-xlsx zips
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "ole-xls"
    low = head.lstrip(b"\xef\xbb\xbf \r\n\t").lower()
    if low.startswith(b"<") and (b"<table" in head.lower() or b"<html" in low or b"<!doctype" in low
                                 or b"<?xml" in low):
        return "html"
    return "text"


# ---------------------------------------------------------------------------------------------
# Excel via calamine
# ---------------------------------------------------------------------------------------------

def _calamine_sheets(path: Path, warnings: list[str]) -> list[Sheet]:
    try:
        import python_calamine as pc
    except ImportError:  # pragma: no cover
        return _openpyxl_sheets(path, warnings)
    try:
        wb = pc.CalamineWorkbook.from_path(str(path))
    except Exception as e:
        warnings.append(f"Fast reader failed ({e}); trying the slower reader.")
        return _openpyxl_sheets(path, warnings)
    out = []
    for meta in wb.sheets_metadata:
        name = meta.name
        hidden = "Visible" not in str(meta.visible)
        if "WorkSheet" not in str(meta.typ) and "Worksheet" not in str(meta.typ):
            continue  # chart sheets etc.
        try:
            sh = wb.get_sheet_by_name(name)
        except Exception as e:
            warnings.append(f"Sheet '{name}' could not be opened: {e}")
            continue

        def rows(p=str(path), n=name) -> Iterator[Row]:
            w = pc.CalamineWorkbook.from_path(p)
            for r in w.get_sheet_by_name(n).iter_rows():
                yield list(r)

        head = []
        for i, r in enumerate(sh.iter_rows()):
            if i >= HEAD_ROWS:
                break
            head.append(list(r))
        n_rows = sh.height
        if not head or all(all(c in ("", None) for c in r) for r in head):
            continue
        out.append(Sheet(name=name, kind="sheet", hidden=hidden, head=head, n_rows=n_rows, _rows=rows))
    return out


def _openpyxl_sheets(path: Path, warnings: list[str]) -> list[Sheet]:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as e:
        warnings.append(f"This file could not be opened as a workbook: {e}")
        return []
    out = []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        out.append(Sheet(name=ws.title, kind="sheet", hidden=ws.sheet_state != "visible",
                         head=rows[:HEAD_ROWS], n_rows=len(rows), _rows=lambda rr=rows: iter(rr)))
    return out


# ---------------------------------------------------------------------------------------------
# Pivot caches
# ---------------------------------------------------------------------------------------------
_NS = re.compile(r"\{.*?\}")


def _tag(el) -> str:
    return _NS.sub("", el.tag)


def _cell(el) -> Any:
    t = _tag(el)
    v = el.get("v")
    if t == "n":
        try:
            f = float(v)
            return int(f) if f.is_integer() and abs(f) < 1e15 else f
        except (TypeError, ValueError):
            return None
    if t == "d":
        try:
            return datetime.fromisoformat(v)
        except (TypeError, ValueError):
            return v
    if t == "b":
        return v in ("1", "true")
    if t in ("m",):
        return None
    if t == "e":
        return v
    return v  # s


def _pivot_sheets(path: Path, warnings: list[str]) -> list[Sheet]:
    out = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        defs = sorted(n for n in names if re.match(r"xl/pivotCache/pivotCacheDefinition\d+\.xml$", n))
        for d in defs:
            num = re.search(r"(\d+)\.xml$", d).group(1)
            rec = f"xl/pivotCache/pivotCacheRecords{num}.xml"
            if rec not in names:
                continue
            root = ET.fromstring(z.read(d))
            source = ""
            fields: list[str] = []
            shared: list[list[Any]] = []
            for el in root.iter():
                t = _tag(el)
                if t == "worksheetSource":
                    source = el.get("sheet") or el.get("name") or el.get("ref") or ""
                elif t == "cacheField":
                    fields.append(el.get("name") or f"Field{len(fields) + 1}")
                    items = []
                    for si in el:
                        if _tag(si) == "sharedItems":
                            items = [_cell(x) for x in si]
                    shared.append(items)
            records = []
            for _, el in ET.iterparse(io.BytesIO(z.read(rec)), events=("end",)):
                if _tag(el) != "r":
                    continue
                row = []
                for i, c in enumerate(el):
                    if _tag(c) == "x":
                        idx = int(c.get("v", "0"))
                        items = shared[i] if i < len(shared) else []
                        row.append(items[idx] if idx < len(items) else None)
                    else:
                        row.append(_cell(c))
                records.append(row)
                el.clear()
            if not records:
                continue
            grid = [fields] + records
            label = f"Pivot data: {source}" if source else f"Pivot data {num}"
            out.append(Sheet(name=label, kind="pivot", hidden=True, head=grid[:HEAD_ROWS], n_rows=len(grid),
                             _rows=lambda g=grid: iter(g),
                             note=f"Rows stored inside the workbook behind a pivot table (source: {source or 'unknown'})."))
    return out


# ---------------------------------------------------------------------------------------------
# HTML tables
# ---------------------------------------------------------------------------------------------
class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[Row]] = []
        self._stack: list[list[Row]] = []
        self._row: Row | None = None
        self._cell: list[str] | None = None
        self._span = 1

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self._stack.append([])
        elif tag == "tr" and self._stack:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
            try:
                self._span = max(1, int(a.get("colspan", "1")))
            except ValueError:
                self._span = 1
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._row.extend([""] * (self._span - 1))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._stack:
            self._stack[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._stack:
            t = self._stack.pop()
            if t:
                self.tables.append(t)

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _decode(data: bytes) -> str:
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if len(data) > 4 and data[1:2] == b"\x00" and data[3:4] == b"\x00":
        return data.decode("utf-16-le", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _html_sheets(data: bytes, warnings: list[str]) -> list[Sheet]:
    p = _TableParser()
    p.feed(_decode(data))
    out = []
    for i, t in enumerate(p.tables, 1):
        if len(t) < 2:
            continue
        out.append(Sheet(name=f"Table {i}", kind="html", head=t[:HEAD_ROWS], n_rows=len(t), _rows=lambda g=t: iter(g)))
    return out


# ---------------------------------------------------------------------------------------------
# Delimited text
# ---------------------------------------------------------------------------------------------

def _text_sheets(data: bytes, name: str, warnings: list[str], kind: str = "csv") -> list[Sheet]:
    text = _decode(data)
    lines = text.splitlines()
    sample = "\n".join(lines[:200])
    delim = _guess_delimiter(sample)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    grid = [r for r in reader]
    if not grid:
        return []
    return [Sheet(name=name, kind=kind, head=grid[:HEAD_ROWS], n_rows=len(grid), _rows=lambda g=grid: iter(g),
                  note=f"Delimiter: {'TAB' if delim == chr(9) else delim}")]


def _guess_delimiter(sample: str) -> str:
    counts = {}
    lines = [l for l in sample.splitlines() if l.strip()][:100]
    for d in ["\t", ",", ";", "|"]:
        per = [len(next(csv.reader([l], delimiter=d))) for l in lines] if lines else [1]
        per = sorted(per)
        med = per[len(per) // 2]
        consistency = sum(1 for x in per if x == med) / len(per)
        counts[d] = (med > 1) * (med * consistency)
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","
