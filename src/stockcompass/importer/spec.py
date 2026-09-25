"""Report types, their fingerprints, and what a parser returns."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from .grid import norm, non_empty
from .reader import Sheet


@dataclass
class Finding:
    level: str                  # info | warn | error
    code: str
    message: str
    count: int | None = None
    detail: str = ""


@dataclass
class ParseContext:
    resolver: Any
    ref_date: date
    store: str | None = None            # user-chosen store (for single-store files without a store column)
    snapshot_date: date | None = None   # user-chosen date
    file_name: str = ""
    file_date: date | None = None       # file modified date, last-resort snapshot date
    progress: Callable[[float, str], None] | None = None
    settings: dict = field(default_factory=dict)

    def tick(self, frac: float, msg: str = ""):
        if self.progress:
            self.progress(frac, msg)


@dataclass
class ParseResult:
    tables: dict[str, list[dict]] = field(default_factory=dict)
    items: dict[str, dict] = field(default_factory=dict)
    suppliers: dict[str, str] = field(default_factory=dict)
    snapshot_date: date | None = None
    period_from: date | None = None
    period_to: date | None = None
    stores: set[str] = field(default_factory=set)
    findings: list[Finding] = field(default_factory=list)
    summary: str = ""

    def add(self, table: str, row: dict):
        self.tables.setdefault(table, []).append(row)

    def warn(self, code: str, msg: str, count: int | None = None, detail: str = ""):
        self.findings.append(Finding("warn", code, msg, count, detail))

    def info(self, code: str, msg: str, count: int | None = None, detail: str = ""):
        self.findings.append(Finding("info", code, msg, count, detail))

    def error(self, code: str, msg: str, count: int | None = None, detail: str = ""):
        self.findings.append(Finding("error", code, msg, count, detail))

    @property
    def row_count(self) -> int:
        return sum(len(v) for v in self.tables.values())


@dataclass
class ReportSpec:
    key: str
    name: str
    name_ur: str
    source: str                          # GIMA | BO | BC workbook | DP workbook | Leaflet workbook
    tokens: dict[str, float]             # whole-cell column codes / labels and their weight
    required: list[str] = field(default_factory=list)
    phrases: list[tuple[str, float]] = field(default_factory=list)  # regex over the top text
    anti: list[str] = field(default_factory=list)                    # cells that rule this type out
    needs_store: bool = False            # the file itself has no store column
    parse: Callable[[Sheet, ParseContext], ParseResult] | None = None
    analysed: bool = True                # False = kept as raw rows only (for now)
    custom: Callable[[set[str], str], float] | None = None
    description: str = ""


REGISTRY: dict[str, ReportSpec] = {}


def register(spec: ReportSpec) -> ReportSpec:
    REGISTRY[spec.key] = spec
    return spec


@dataclass
class Detection:
    spec: ReportSpec
    confidence: float        # 0..1
    evidence: list[str]


def sheet_signals(sheet: Sheet, max_rows: int = 60) -> tuple[set[str], str]:
    cells: set[str] = set()
    lines = []
    for r in sheet.head[:max_rows]:
        ne = non_empty(r)
        for j in ne:
            v = r[j]
            if isinstance(v, str):
                n = norm(v)
                if n and len(n) <= 60:
                    cells.add(n)
        lines.append(" ".join(str(r[j]) for j in ne))
    return cells, "\n".join(lines).upper()


def detect(sheet: Sheet) -> list[Detection]:
    cells, text = sheet_signals(sheet)
    out = []
    for spec in REGISTRY.values():
        total = sum(spec.tokens.values()) or 1.0
        got = 0.0
        ev = []
        for tok, w in spec.tokens.items():
            if norm(tok) in cells:
                got += w
                ev.append(tok)
        base = got / total
        for rx, w in spec.phrases:
            if re.search(rx, text, re.I):
                base += w
                ev.append(f"text: {rx}")
        if spec.custom:
            extra = spec.custom(cells, text)
            if extra:
                base += extra
                ev.append("layout match")
        missing_req = [t for t in spec.required if norm(t) not in cells]
        if missing_req:
            base = min(base, 0.45)
        if any(norm(a) in cells for a in spec.anti):
            base *= 0.3
        if base > 0.05:
            out.append(Detection(spec, round(min(base, 1.0), 3), ev))
    out.sort(key=lambda d: d.confidence, reverse=True)
    return out
