"""'Your jobs today' for store roles: one card per job with a tick box, its item list and Excel export."""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from stockcompass.analytics import jobs as J
from stockcompass.analytics.core import L
from stockcompass.i18n import t
from stockcompass.paths import exports_dir

from . import theme
from .widgets import DataTable, card, label


class JobCard(QFrame):
    open_list = Signal(object)

    def __init__(self, db, scope, job: J.Job, parent=None):
        super().__init__(parent)
        self.db, self.job = db, job
        self.key = J.job_key(scope, job.key, date.today())
        self.setObjectName("insight")
        fg = {"bad": theme.BAD, "warn": theme.WARN, "info": theme.GOLD}.get(job.level, theme.GOLD)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 10, 0)
        bar = QFrame()
        bar.setFixedWidth(4)
        bar.setStyleSheet(f"background:{fg};border-radius:2px;")
        h.addWidget(bar)
        self.cb = QCheckBox()
        self.cb.setChecked(bool(db.one("SELECT 1 FROM job_done WHERE key=?", [self.key])))
        self.cb.toggled.connect(self._toggle)
        self.cb.setToolTip(L("Tick when done", "مکمل ہونے پر نشان لگائیں"))
        h.addWidget(self.cb)
        box = QVBoxLayout()
        box.setContentsMargins(4, 8, 0, 8)
        self.title = label(job.title, wrap=True)
        box.addWidget(self.title)
        box.addWidget(label(job.why, "muted", wrap=True))
        box.addWidget(label(J.summary_text(job), "chip"), 0, Qt.AlignLeft)
        h.addLayout(box, 1)
        b = QPushButton(L("Open list", "فہرست کھولیں"))
        b.clicked.connect(lambda: self.open_list.emit(job))
        h.addWidget(b)
        self._style()

    def _style(self):
        done = self.cb.isChecked()
        self.title.setStyleSheet("font-weight:800;" + ("text-decoration: line-through; color:#7a6a5a;" if done else ""))

    def _toggle(self, on):
        if on:
            self.db.execute("INSERT OR REPLACE INTO job_done VALUES (?,?)", [self.key, datetime.now()])
        else:
            self.db.execute("DELETE FROM job_done WHERE key=?", [self.key])
        self._style()


class JobsPanel(QWidget):
    openItem = Signal(str)

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.jobs = J.jobs(state.db, state.scope)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(8)
        if not self.jobs:
            il.addWidget(label(L("Nothing urgent found in the imported data for this store and section. Import today's "
                                 "GIMA zero stock and negative stock sheets to get the daily jobs.",
                                 "کوئی فوری کام نہیں ملا۔ آج کی جیما شیٹس امپورٹ کریں۔"), "muted", wrap=True))
        for j in self.jobs:
            c = JobCard(state.db, state.scope, j)
            c.open_list.connect(self._open)
            il.addWidget(c)
        exp = QPushButton("⬇ " + L("Export action list", "ایکشن لسٹ ایکسپورٹ کریں"))
        exp.setObjectName("primary")
        exp.clicked.connect(self.export)
        exp.setEnabled(bool(self.jobs))
        lay.addWidget(card(inner, L("Your jobs today", "آج کے کام"),
                           L(f"{self.state.scope.label(self.state.db)} · most urgent first. Tick a job when it is done.",
                             f"{self.state.scope.label(self.state.db)} · سب سے فوری پہلے"), tools=[exp]))

    def _open(self, job: J.Job):
        dlg = QDialog(self)
        dlg.setWindowTitle(job.title)
        dlg.resize(1000, 640)
        l = QVBoxLayout(dlg)
        l.addWidget(label(job.title, "h1"))
        l.addWidget(label(job.why, "muted", wrap=True))
        tbl = DataTable(job.columns, job.rows, export_name=f"job_{job.key}")
        tbl.rowActivated.connect(lambda r: r.get("item") and self.openItem.emit(r["item"]))
        l.addWidget(tbl, 1)
        b = QPushButton(t("close"))
        b.clicked.connect(dlg.accept)
        l.addWidget(b, 0, Qt.AlignRight)
        dlg.exec()

    def export(self):
        default = exports_dir() / f"action_list_{date.today():%Y%m%d}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, L("Export action list", "ایکشن لسٹ"), str(default), "Excel (*.xlsx)")
        if not path:
            return
        export_jobs(path, self.jobs, self.state.scope.label(self.state.db))
        QMessageBox.information(self, t("export"), f"{t('done')}: {path}")


def export_jobs(path, jobs: list[J.Job], scope_label: str):
    import xlsxwriter

    from stockcompass.i18n import col

    wb = xlsxwriter.Workbook(str(path))
    head = wb.add_format({"bold": True, "bg_color": theme.BROWN_2, "font_color": "white", "border": 1})
    title = wb.add_format({"bold": True, "font_size": 14})
    num = wb.add_format({"num_format": "#,##0"})
    dt = wb.add_format({"num_format": "dd mmm yyyy"})
    ws = wb.add_worksheet("Summary")
    ws.write(0, 0, f"Action list · {scope_label} · {date.today():%d %b %Y}", title)
    ws.write_row(2, 0, ["Job", "Items", "PKR", "What it is", "Done"], head)
    for i, j in enumerate(jobs, 3):
        ws.write(i, 0, j.title)
        ws.write_number(i, 1, j.count)
        if j.value:
            ws.write_number(i, 2, j.value, num)
        ws.write(i, 3, j.why)
        ws.write(i, 4, "")
    ws.set_column(0, 0, 55)
    ws.set_column(3, 3, 70)
    for j in jobs:
        sh = wb.add_worksheet(j.key[:31])
        sh.write_row(0, 0, [col(k) for k, _ in j.columns] + ["Done"], head)
        for r, row in enumerate(j.rows, 1):
            for c, (k, kind) in enumerate(j.columns):
                v = row.get(k)
                if v is None:
                    continue
                if kind == "date" and hasattr(v, "year"):
                    sh.write_datetime(r, c, datetime(v.year, v.month, v.day), dt)
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    sh.write_number(r, c, float(v), num)
                else:
                    sh.write(r, c, str(v))
        sh.freeze_panes(1, 0)
        sh.autofilter(0, 0, max(1, len(j.rows)), len(j.columns))
        sh.set_column(0, len(j.columns), 16)
    wb.close()
