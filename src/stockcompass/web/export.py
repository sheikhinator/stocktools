"""Excel export for anything on screen (tables, drill-downs) and the store action list. No Qt here."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

HEAD_BG = "#3a2618"   # MAF brown


def _formats(wb):
    return dict(head=wb.add_format({"bold": True, "bg_color": HEAD_BG, "font_color": "white", "border": 1}),
                title=wb.add_format({"bold": True, "font_size": 14}),
                int=wb.add_format({"num_format": "#,##0"}), num=wb.add_format({"num_format": "#,##0.00"}),
                pct=wb.add_format({"num_format": "0.0"}), date=wb.add_format({"num_format": "dd mmm yyyy"}))


def _cell(ws, f, i, j, v, kind):
    if v is None or v == "":
        return
    if kind == "date" and isinstance(v, str) and len(v) >= 10 and v[4] == "-":
        try:
            v = date.fromisoformat(v[:10])
        except ValueError:
            pass
    if isinstance(v, (date, datetime)):
        ws.write_datetime(i, j, datetime(v.year, v.month, v.day), f["date"])
    elif isinstance(v, bool):
        ws.write(i, j, "Yes" if v else "No")
    elif isinstance(v, (int, float)):
        fmt = f["pct"] if kind in ("pct", "pct_chip", "pct_neg", "sg") else f["num"] if kind in ("num", "x") else f["int"]
        ws.write_number(i, j, float(v), fmt)
    else:
        ws.write(i, j, str(v))


def write_table(path: str | Path, title: str, cols: list[dict], rows: list[dict], sheet: str = "Data"):
    """cols: [{k, l, kind}] exactly as the screen tables carry them."""
    import xlsxwriter

    wb = xlsxwriter.Workbook(str(path))
    f = _formats(wb)
    ws = wb.add_worksheet((sheet or "Data")[:31])
    ws.write(0, 0, title, f["title"])
    for j, c in enumerate(cols):
        pct = c.get("kind") in ("pct", "pct_chip", "pct_neg", "sg")
        ws.write(2, j, c["l"] + (" %" if pct and "%" not in c["l"] else ""), f["head"])
        ws.set_column(j, j, 34 if c.get("kind") in ("name", "text") else 14)
    for i, r in enumerate(rows, 3):
        for j, c in enumerate(cols):
            v = r.get(c["k"])
            if c.get("kind") == "name" and r.get("sub"):
                v = f"{v} ({r['sub']})"
            _cell(ws, f, i, j, v, c.get("kind"))
    if len(rows) > 1:                         # live totals row: sums for amounts, averages for rates
        from xlsxwriter.utility import xl_rowcol_to_cell as rc
        tot = wb.add_format({"bold": True, "top": 2, "bg_color": "#F3EDE4", "num_format": "#,##0.##"})
        r = 3 + len(rows)
        ws.write(r, 0, "Total", tot)
        for j, c in enumerate(cols[1:], 1):
            kind = c.get("kind")
            if kind in ("money", "int", "pkr", "num", "pct", "pct_chip", "pct_neg", "sg", "x"):
                avg = kind not in ("money", "int", "pkr") or re.search(r"avg|price|cost|days|age|rate|dly", c["k"] + " " + c["l"], re.I)
                ws.write_formula(r, j, f"={'AVERAGE' if avg else 'SUM'}({rc(3, j)}:{rc(r - 1, j)})", tot)
            else:
                ws.write(r, j, "", tot)
    ws.freeze_panes(3, 1)
    ws.autofilter(2, 0, max(3, len(rows) + 2), max(0, len(cols) - 1))
    wb.close()


def write_jobs(path: str | Path, jobs: list[dict], scope_label: str):
    """jobs: the 'jobs' list of the home page payload (title, why, count, value, table{cols, rows})."""
    import xlsxwriter

    wb = xlsxwriter.Workbook(str(path))
    f = _formats(wb)
    ws = wb.add_worksheet("Summary")
    ws.write(0, 0, f"Action list · {scope_label} · {date.today():%d %b %Y}", f["title"])
    ws.write_row(2, 0, ["Job", "Items", "PKR", "What it is", "Done"], f["head"])
    for i, j in enumerate(jobs, 3):
        ws.write(i, 0, j["title"])
        ws.write_number(i, 1, j.get("count") or 0)
        if j.get("value"):
            ws.write_number(i, 2, j["value"], f["int"])
        ws.write(i, 3, j.get("why") or "")
        ws.write(i, 4, "✓" if j.get("done") else "")
    ws.set_column(0, 0, 55)
    ws.set_column(3, 3, 70)
    for j in jobs:
        tb = j.get("table") or {}
        cols = tb.get("cols") or []
        sh = wb.add_worksheet(j["key"][:31])
        sh.write_row(0, 0, [c["l"] for c in cols] + ["Done"], f["head"])
        for r, row in enumerate(tb.get("rows") or [], 1):
            for c, col in enumerate(cols):
                _cell(sh, f, r, c, row.get(col["k"]), col.get("kind"))
        sh.freeze_panes(1, 0)
        sh.autofilter(0, 0, max(1, len(tb.get("rows") or [])), len(cols))
        sh.set_column(0, len(cols), 16)
    wb.close()
