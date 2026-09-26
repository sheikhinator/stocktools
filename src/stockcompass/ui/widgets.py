"""Reusable pieces: KPI cards, insight cards, data tables with search/sort/export, charts, dialogs."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCharts import (QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QDateTimeAxis,
                              QHorizontalBarSeries, QLineSeries, QValueAxis)
from PySide6.QtCore import (QAbstractTableModel, QDateTime, QMargins, QModelIndex, QSortFilterProxyModel, Qt, Signal)
from PySide6.QtGui import QBrush, QColor, QFont, QPainter
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QTableView,
                               QVBoxLayout, QWidget)

from stockcompass.analytics.core import Explain, Kpi, fmt_pkr
from stockcompass.i18n import col, is_rtl, t
from stockcompass.paths import exports_dir

from . import theme


# ------------------------------------------------------------------------------------------------
# formatting
# ------------------------------------------------------------------------------------------------

def fmt_value(v: Any, kind: str) -> str:
    if v is None or v == "":
        return "–"
    try:
        if kind == "pct":
            return f"{float(v):.1f}%"
        if kind == "pkr":
            return fmt_pkr(float(v))
        if kind == "money":
            return f"{float(v):,.0f}"
        if kind == "int":
            return f"{float(v):,.0f}"
        if kind == "num":
            return f"{float(v):,.2f}".rstrip("0").rstrip(".")
        if kind == "days":
            return f"{float(v):,.0f}"
        if kind == "date":
            return v.strftime("%d %b %Y") if isinstance(v, (date, datetime)) else str(v)
        if kind == "bool":
            return t("yes") if v else t("no")
    except (TypeError, ValueError):
        return str(v)
    return str(v)


def label(text: str, obj: str = "", wrap: bool = False) -> QLabel:
    l = QLabel(text)
    if obj:
        l.setObjectName(obj)
    l.setWordWrap(wrap)
    return l


def card(inner: QWidget | None = None, title: str = "", sub: str = "", tools: list[QWidget] | None = None) -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(8)
    if title or tools:
        top = QHBoxLayout()
        box = QVBoxLayout()
        box.setSpacing(0)
        if title:
            box.addWidget(label(title, "h2", wrap=True))
        if sub:
            box.addWidget(label(sub, "muted", wrap=True))
        top.addLayout(box, 1)
        for w in tools or []:
            top.addWidget(w)
        lay.addLayout(top)
    if inner is not None:
        lay.addWidget(inner, 1)
    return f


# ------------------------------------------------------------------------------------------------
# explain dialog
# ------------------------------------------------------------------------------------------------

class ExplainDialog(QDialog):
    def __init__(self, ex: Explain, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("how"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.addWidget(label(ex.title, "h1"))
        for head, body in [(t("definition"), ex.definition), (t("formula"), ex.formula), (t("source"), ex.source),
                           (t("as_of"), ex.as_of)]:
            if body:
                lay.addWidget(label(head, "h2"))
                b = label(body, wrap=True)
                b.setTextInteractionFlags(Qt.TextSelectableByMouse)
                lay.addWidget(b)
        close = QPushButton(t("close"))
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)


# ------------------------------------------------------------------------------------------------
# KPI card
# ------------------------------------------------------------------------------------------------

class KpiCard(QFrame):
    clicked = Signal(str)

    def __init__(self, k: Kpi, parent=None):
        super().__init__(parent)
        self.k = k
        self.setObjectName("kpi")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)
        top = QHBoxLayout()
        name = t(f"kpi_{k.key}") if t(f"kpi_{k.key}") != f"kpi_{k.key}" else k.label
        top.addWidget(label(name, "muted", wrap=True), 1)
        if k.explain:
            info = QPushButton("i")
            info.setFixedSize(22, 22)
            info.setToolTip(t("how"))
            info.setStyleSheet("QPushButton{border-radius:11px;padding:0;font-weight:800;color:#7a6a5a}")
            info.clicked.connect(self._explain)
            top.addWidget(info)
        lay.addLayout(top)
        v = QLabel(self._value())
        v.setStyleSheet("font-size: 24px; font-weight: 800;")
        lay.addWidget(v)
        if k.status:
            fg, bg = theme.STATUS[k.status]
            chip = QLabel({"good": "✓ on target", "warn": "! watch", "bad": "✕ off target"}[k.status]
                          if not is_rtl() else {"good": "✓ ہدف پر", "warn": "! توجہ", "bad": "✕ ہدف سے باہر"}[k.status])
            chip.setStyleSheet(f"background:{bg};color:{fg};border-radius:8px;padding:1px 8px;font-weight:700;")
            chip.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            lay.addWidget(chip)
        if k.sub:
            lay.addWidget(label(k.sub, "muted", wrap=True))
        if k.spark:
            lay.addWidget(Spark(k.spark, theme.BAD if k.status == "bad" else theme.BROWN_2))

    def _value(self) -> str:
        k = self.k
        if k.fmt == "pct":
            return fmt_value(k.value, "pct")
        if k.fmt == "pkr":
            return fmt_pkr(k.value)
        return fmt_value(k.value, "int")

    def _explain(self):
        ExplainDialog(self.k.explain, self).exec()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.k.goto:
            self.clicked.emit(self.k.goto)
        super().mouseReleaseEvent(e)


class Spark(QWidget):
    def __init__(self, values: list[float], color: str, parent=None):
        super().__init__(parent)
        self.values = [v for v in values if v is not None][-40:]
        self.color = QColor(color)
        self.setFixedHeight(28)

    def paintEvent(self, _):
        if len(self.values) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        lo, hi = min(self.values), max(self.values)
        rng = (hi - lo) or 1
        pts = []
        for i, v in enumerate(self.values):
            x = i / (len(self.values) - 1) * (w - 2) + 1
            y = h - 2 - (v - lo) / rng * (h - 4)
            pts.append((x, y))
        pen = p.pen()
        pen.setColor(self.color)
        pen.setWidthF(1.8)
        p.setPen(pen)
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            p.drawLine(int(x1), int(y1), int(x2), int(y2))


class InsightCard(QFrame):
    clicked = Signal(str)

    def __init__(self, ins: dict, parent=None):
        super().__init__(parent)
        self.goto = ins.get("goto", "")
        self.setObjectName("insight")
        self.setCursor(Qt.PointingHandCursor)
        fg = {"bad": theme.BAD, "warn": theme.WARN, "info": theme.GOLD}.get(ins.get("level"), theme.GOLD)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 10, 0)
        bar = QFrame()
        bar.setFixedWidth(4)
        bar.setStyleSheet(f"background:{fg};border-radius:2px;")
        lay.addWidget(bar)
        box = QVBoxLayout()
        box.setContentsMargins(8, 8, 0, 8)
        title = label(ins["title"], wrap=True)
        title.setStyleSheet("font-weight:800;")
        box.addWidget(title)
        box.addWidget(label(ins.get("text", ""), "muted", wrap=True))
        lay.addLayout(box, 1)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.goto:
            self.clicked.emit(self.goto)
        super().mouseReleaseEvent(e)


# ------------------------------------------------------------------------------------------------
# Tables
# ------------------------------------------------------------------------------------------------

class DictModel(QAbstractTableModel):
    def __init__(self, rows: list[dict], columns: list[tuple[str, str]], colorer: Callable[[dict], str] | None = None):
        super().__init__()
        self.rows = rows
        self.columns = columns          # (key, kind)
        self.colorer = colorer

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return col(self.columns[section][0])
        return None

    def data(self, index, role=Qt.DisplayRole):
        r = self.rows[index.row()]
        key, kind = self.columns[index.column()]
        v = r.get(key)
        if role == Qt.DisplayRole:
            return fmt_value(v, kind)
        if role == Qt.UserRole:
            if isinstance(v, (date, datetime)):
                return v.toordinal() if isinstance(v, date) else v.timestamp()
            if isinstance(v, bool):
                return int(v)
            return v if v is not None else ("" if kind in ("text",) else float("-inf"))
        if role == Qt.TextAlignmentRole:
            if kind in ("int", "num", "pct", "pkr", "money", "days"):
                return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.BackgroundRole and self.colorer:
            st = self.colorer(r)
            if st:
                return QBrush(QColor(theme.STATUS[st][1]))
        if role == Qt.ForegroundRole and kind == "status":
            return QBrush(QColor(theme.STATUS.get(str(v), theme.STATUS[""])[0]))
        return None

    def row(self, i: int) -> dict:
        return self.rows[i]


class _Proxy(QSortFilterProxyModel):
    def lessThan(self, a, b):
        x, y = a.data(Qt.UserRole), b.data(Qt.UserRole)
        try:
            return x < y
        except TypeError:
            return str(x) < str(y)


class DataTable(QWidget):
    rowActivated = Signal(dict)

    def __init__(self, columns: list[tuple[str, str]], rows: list[dict] | None = None, title: str = "",
                 colorer=None, export_name: str = "export", parent=None):
        super().__init__(parent)
        self.columns = columns
        self.export_name = export_name
        self.colorer = colorer
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("search"))
        self.search.setMaximumWidth(280)
        self.count = label("", "muted")
        exp = QPushButton("⬇ " + t("export"))
        exp.clicked.connect(self.export)
        bar.addWidget(self.search)
        bar.addWidget(self.count)
        bar.addStretch(1)
        bar.addWidget(exp)
        lay.addLayout(bar)
        self.view = QTableView()
        self.view.setAlternatingRowColors(True)
        self.view.setSortingEnabled(True)
        self.view.setSelectionBehavior(QTableView.SelectRows)
        self.view.setEditTriggers(QTableView.NoEditTriggers)
        self.view.verticalHeader().setVisible(False)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.view.setWordWrap(False)
        self.view.doubleClicked.connect(self._activated)
        lay.addWidget(self.view, 1)
        self.proxy = _Proxy()
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.search.textChanged.connect(self._filter)
        self.set_rows(rows or [])

    def set_rows(self, rows: list[dict]):
        self.model = DictModel(rows, self.columns, self.colorer)
        self.proxy.setSourceModel(self.model)
        self.view.setModel(self.proxy)
        self.view.resizeColumnsToContents()
        for i in range(len(self.columns)):
            if self.view.columnWidth(i) > 320:
                self.view.setColumnWidth(i, 320)
        self._filter(self.search.text())

    def _filter(self, text: str):
        self.proxy.setFilterFixedString(text)
        self.count.setText(f"{self.proxy.rowCount():,} {t('rows')}")

    def _activated(self, idx):
        src = self.proxy.mapToSource(idx)
        self.rowActivated.emit(self.model.row(src.row()))

    def visible_rows(self) -> list[dict]:
        return [self.model.row(self.proxy.mapToSource(self.proxy.index(i, 0)).row()) for i in range(self.proxy.rowCount())]

    def export(self):
        default = exports_dir() / f"{self.export_name}_{date.today():%Y%m%d}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, t("export"), str(default), "Excel (*.xlsx)")
        if not path:
            return
        export_xlsx(path, self.columns, self.visible_rows(), self.export_name)
        QMessageBox.information(self, t("export"), f"{t('done')}: {path}")


def export_xlsx(path: str | Path, columns: list[tuple[str, str]], rows: list[dict], sheet: str = "Data"):
    import xlsxwriter

    wb = xlsxwriter.Workbook(str(path))
    ws = wb.add_worksheet(sheet[:31] or "Data")
    head = wb.add_format({"bold": True, "bg_color": theme.BROWN_2, "font_color": "white", "border": 1})
    fmts = {"int": wb.add_format({"num_format": "#,##0"}), "money": wb.add_format({"num_format": "#,##0"}),
            "pkr": wb.add_format({"num_format": "#,##0"}), "num": wb.add_format({"num_format": "#,##0.00"}),
            "pct": wb.add_format({"num_format": "0.0"}), "date": wb.add_format({"num_format": "dd mmm yyyy"}),
            "days": wb.add_format({"num_format": "#,##0"})}
    for j, (k, kind) in enumerate(columns):
        ws.write(0, j, col(k) + (" %" if kind == "pct" else ""), head)
        ws.set_column(j, j, 14 if kind != "text" else 28)
    for i, r in enumerate(rows, 1):
        for j, (k, kind) in enumerate(columns):
            v = r.get(k)
            if v is None:
                continue
            if kind == "date" and isinstance(v, (date, datetime)):
                ws.write_datetime(i, j, datetime(v.year, v.month, v.day), fmts["date"])
            elif kind in fmts and isinstance(v, (int, float)) and not isinstance(v, bool):
                ws.write_number(i, j, float(v), fmts[kind])
            elif kind == "bool":
                ws.write(i, j, t("yes") if v else t("no"))
            else:
                ws.write(i, j, str(v))
    ws.freeze_panes(1, 0)
    ws.autofilter(0, 0, max(1, len(rows)), len(columns) - 1)
    wb.close()


# ------------------------------------------------------------------------------------------------
# Charts
# ------------------------------------------------------------------------------------------------

def _chart_base(title: str = "") -> QChart:
    c = QChart()
    c.setBackgroundVisible(False)
    c.setMargins(QMargins(4, 4, 4, 4))
    c.legend().setAlignment(Qt.AlignTop)
    c.legend().setVisible(True)
    if title:
        c.setTitle(title)
    return c


def _view(c: QChart, height: int = 240) -> QChartView:
    v = QChartView(c)
    v.setRenderHint(QPainter.Antialiasing)
    v.setMinimumHeight(height)
    v.setStyleSheet("background: transparent;")
    return v


def line_chart(series: dict[str, list[tuple[date, float | None]]], y_suffix: str = "%", target: float | None = None,
               height: int = 240) -> QChartView:
    c = _chart_base()
    ax = QDateTimeAxis()
    ax.setFormat("dd MMM")
    ay = QValueAxis()
    ay.setLabelFormat("%.0f" + y_suffix.replace("%", "%%"))
    c.addAxis(ax, Qt.AlignBottom)
    c.addAxis(ay, Qt.AlignLeft)
    lo, hi = None, None
    allx = []
    for i, (name, pts) in enumerate(series.items()):
        s = QLineSeries()
        s.setName(name)
        pen = s.pen()
        pen.setColor(QColor(theme.SERIES[i % len(theme.SERIES)]))
        pen.setWidthF(2.2)
        s.setPen(pen)
        for d, v in pts:
            if v is None:
                continue
            dt = QDateTime.fromString(d.isoformat(), "yyyy-MM-dd")
            s.append(dt.toMSecsSinceEpoch(), v)
            lo = v if lo is None else min(lo, v)
            hi = v if hi is None else max(hi, v)
            allx.append(d)
        c.addSeries(s)
        s.attachAxis(ax)
        s.attachAxis(ay)
    if target is not None and allx:
        s = QLineSeries()
        s.setName(f"{t('target')} {target:g}{y_suffix}")
        pen = s.pen()
        pen.setColor(QColor(theme.GOOD))
        pen.setStyle(Qt.DashLine)
        s.setPen(pen)
        for d in (min(allx), max(allx)):
            s.append(QDateTime.fromString(d.isoformat(), "yyyy-MM-dd").toMSecsSinceEpoch(), target)
        c.addSeries(s)
        s.attachAxis(ax)
        s.attachAxis(ay)
        lo = min(lo, target) if lo is not None else target
        hi = max(hi, target) if hi is not None else target
    if lo is not None:
        ay.setRange(max(0, lo - (hi - lo) * 0.15 - 0.5), hi + (hi - lo) * 0.15 + 0.5)
        ay.applyNiceNumbers()
    return _view(c, height)


def bar_chart(categories: list[str], sets: dict[str, list[float]], horizontal: bool = False, height: int = 260,
              suffix: str = "") -> QChartView:
    c = _chart_base()
    series = QHorizontalBarSeries() if horizontal else QBarSeries()
    allv0 = [abs(v) for vals in sets.values() for v in vals if v is not None]
    scale, unit = (1e6, "M") if allv0 and max(allv0) >= 2e6 else ((1e3, "K") if allv0 and max(allv0) >= 2e4 else (1, ""))
    if scale != 1:
        sets = {k: [(v or 0) / scale for v in vals] for k, vals in sets.items()}
        suffix = unit + suffix
    for i, (name, vals) in enumerate(sets.items()):
        bs = QBarSet(name)
        bs.setColor(QColor(theme.SERIES[i % len(theme.SERIES)]))
        bs.setBorderColor(QColor(theme.SERIES[i % len(theme.SERIES)]))
        for v in vals:
            bs.append(float(v or 0))
        series.append(bs)
    c.addSeries(series)
    cat = QBarCategoryAxis()
    cat.append(categories)
    val = QValueAxis()
    val.setLabelFormat(("%.1f" if scale == 1e6 else "%.0f") + suffix.replace("%", "%%"))
    if horizontal:
        c.addAxis(cat, Qt.AlignLeft)
        c.addAxis(val, Qt.AlignBottom)
    else:
        c.addAxis(cat, Qt.AlignBottom)
        c.addAxis(val, Qt.AlignLeft)
    series.attachAxis(cat)
    series.attachAxis(val)
    allv = [v for vals in sets.values() for v in vals if v is not None]
    if allv:
        val.setRange(min(0, min(allv)), max(allv) * 1.1 if max(allv) > 0 else 1)
        val.applyNiceNumbers()
    c.legend().setVisible(len(sets) > 1)
    return _view(c, height)


def empty_state(text: str) -> QWidget:
    w = QFrame()
    w.setObjectName("card")
    l = QVBoxLayout(w)
    lab = label(text, "muted", wrap=True)
    lab.setAlignment(Qt.AlignCenter)
    l.addWidget(lab)
    w.setMinimumHeight(90)
    return w


def scroll_page(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    inner.setObjectName("page")
    sa.setWidget(inner)
    return sa


def grid_of(widgets: list[QWidget], cols: int) -> QWidget:
    w = QWidget()
    g = QGridLayout(w)
    g.setContentsMargins(0, 0, 0, 0)
    g.setSpacing(10)
    for i, x in enumerate(widgets):
        g.addWidget(x, i // cols, i % cols)
    return w
