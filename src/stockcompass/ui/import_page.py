"""Add reports: drop files, review what was recognised, fix anything once, import with a progress bar."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from stockcompass.importer.pipeline import FilePlan, analyze, commit
from stockcompass.importer.spec import REGISTRY
from stockcompass.i18n import t

from . import theme
from .pages import Page
from .widgets import DataTable, card, label


class Worker(QObject):
    progress = Signal(float, str)
    analysed = Signal(object)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, db, paths=None, plans=None, text=None):
        super().__init__()
        self.db, self.paths, self.plans, self.text = db, paths or [], plans or [], text

    def run_analyze(self):
        plans = []
        try:
            if self.text is not None:
                plans.append(analyze("Pasted data", self.db, text=self.text))
            for i, p in enumerate(self.paths):
                self.progress.emit(i / max(1, len(self.paths)), f"{Path(p).name}")
                try:
                    plans.append(analyze(p, self.db))
                except Exception as e:  # keep going with the other files
                    self.failed.emit(f"{Path(p).name}: {e}")
            self.analysed.emit(plans)
        except Exception as e:
            self.failed.emit(str(e))

    def run_commit(self):
        outs = []
        try:
            for i, plan in enumerate(self.plans):
                def prog(f, m, i=i):
                    self.progress.emit((i + f) / max(1, len(self.plans)), m)
                outs += commit(plan, self.db, progress=prog)
            self.finished.emit(outs)
        except Exception as e:
            self.failed.emit(str(e))


class DropZone(QFrame):
    dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("card")
        self.setMinimumHeight(110)
        self.setStyleSheet(f"QFrame#card{{border:2px dashed {theme.GOLD};background:#fffaf0;border-radius:14px;}}")
        l = QVBoxLayout(self)
        lab = label("⬆  " + t("drop_here"), "h2")
        lab.setAlignment(Qt.AlignCenter)
        l.addWidget(lab)
        sub = label(".xlsx · .xls · .xlsb · .csv · .txt — GIMA, BO, BC, DP, leaflet workbooks", "muted")
        sub.setAlignment(Qt.AlignCenter)
        l.addWidget(sub)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        files = []
        for p in paths:
            pp = Path(p)
            if pp.is_dir():
                files += [str(x) for x in pp.rglob("*") if x.suffix.lower() in (".xlsx", ".xlsm", ".xls", ".xlsb", ".csv",
                                                                                 ".txt", ".tsv", ".htm", ".html", ".ods")]
            else:
                files.append(p)
        if files:
            self.dropped.emit(files)


class ImportPage(Page):
    imported = Signal()

    def __init__(self, state, parent=None):
        super().__init__(state, parent)
        self.plans: list[FilePlan] = []
        self.thread = None

    def refresh(self):
        lay = self.reset()
        self.header(lay, t("import_title"), t("import_sub"))
        dz = DropZone()
        dz.dropped.connect(self.add_files)
        lay.addWidget(dz)
        bar = QHBoxLayout()
        pick = QPushButton(t("choose_files"))
        pick.clicked.connect(self.pick)
        paste = QPushButton(t("paste"))
        paste.clicked.connect(self.paste)
        self.go = QPushButton(t("import_now"))
        self.go.setObjectName("primary")
        self.go.clicked.connect(self.run)
        clear = QPushButton(t("clear"))
        clear.clicked.connect(self.clear)
        for w in (pick, paste):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(clear)
        bar.addWidget(self.go)
        lay.addLayout(bar)
        self.prog = QProgressBar()
        self.prog.setVisible(False)
        self.status = label("", "muted", wrap=True)
        lay.addWidget(self.prog)
        lay.addWidget(self.status)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([t("col_file"), t("col_sheet"), t("col_type"), t("col_conf"),
                                              t("col_store"), t("col_date"), t("col_rows"), t("col_note")])
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(260)
        lay.addWidget(card(self.table, "Review", "Change anything that is wrong before importing. Hidden sheets and "
                                                 "pivot-table data are included automatically."))
        self.results = QVBoxLayout()
        rw = QWidget()
        rw.setLayout(self.results)
        lay.addWidget(rw)
        hist = self.state.db.qd("SELECT import_id, file_name, sheet, report_type, snapshot_date, stores, \"rows\", "
                                "imported_at, status, summary FROM imports ORDER BY import_id DESC LIMIT 500")
        for h in hist:
            h["report_type"] = REGISTRY[h["report_type"]].name if h["report_type"] in REGISTRY else h["report_type"]
        self.hist = DataTable([("file_name", "text"), ("sheet", "text"), ("report_type", "text"),
                               ("snapshot_date", "date"), ("stores", "text"), ("rows", "int"),
                               ("summary", "text")], hist, export_name="imports")
        self.hist.setMinimumHeight(260)
        self._hist_rows = hist
        dl = QPushButton(t("delete_import"))
        dl.clicked.connect(self.delete_selected)
        lay.addWidget(card(self.hist, t("history"), tools=[dl]))
        self._fill()

    # ---------------------------------------------------------------- actions
    def pick(self):
        files, _ = QFileDialog.getOpenFileNames(self, t("choose_files"), str(Path.home()),
                                                "Reports (*.xlsx *.xlsm *.xls *.xlsb *.csv *.txt *.tsv *.htm *.html *.ods);;All files (*)")
        if files:
            self.add_files(files)

    def paste(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(t("paste"))
        dlg.resize(760, 480)
        l = QVBoxLayout(dlg)
        l.addWidget(label("Copy cells in Excel (including the header row) and paste them here.", "muted"))
        ed = QPlainTextEdit()
        l.addWidget(ed, 1)
        ok = QPushButton(t("import_now"))
        ok.setObjectName("primary")
        ok.clicked.connect(dlg.accept)
        l.addWidget(ok, 0, Qt.AlignRight)
        if dlg.exec() and ed.toPlainText().strip():
            self._start_analyze([], ed.toPlainText())

    def add_files(self, files: list[str]):
        self._start_analyze(files, None)

    def _start_analyze(self, files, text):
        self._busy(True, t("working"))
        self.worker = Worker(self.state.db, paths=files, text=text)
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run_analyze)
        self.worker.progress.connect(self._progress)
        self.worker.analysed.connect(self._analysed)
        self.worker.failed.connect(lambda m: self.status.setText("⚠ " + m))
        self.worker.analysed.connect(self.thread.quit)
        self.thread.start()

    def _analysed(self, plans):
        self.plans += plans
        self._busy(False, "")
        self._fill()

    def clear(self):
        self.plans = []
        self._fill()

    def run(self):
        if not self.plans:
            return
        self._read_back()
        missing = [f"{p.path.name} / {sp.sheet.name}" for p in self.plans for sp in p.sheets
                   if sp.chosen != "skip" and sp.needs_store and not sp.store]
        if missing:
            QMessageBox.warning(self, t("pick_store"), "Choose the store for:\n" + "\n".join(missing[:10]))
            return
        self._busy(True, t("working"))
        self.worker = Worker(self.state.db, plans=list(self.plans))
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run_commit)
        self.worker.progress.connect(self._progress)
        self.worker.finished.connect(self._done)
        self.worker.failed.connect(lambda m: (self.status.setText("⚠ " + m), self._busy(False, "")))
        self.worker.finished.connect(self.thread.quit)
        self.thread.start()

    def _done(self, outs):
        self._busy(False, "")
        self.plans = []
        ok = sum(1 for o in outs if o.status == "ok")
        rows = sum(o.rows for o in outs)
        lines = []
        for o in outs:
            icon = "✅" if o.status == "ok" else "⚠"
            name = REGISTRY[o.report_type].name if o.report_type in REGISTRY else o.report_type
            lines.append(f"{icon} {o.file} · {o.sheet} → {name}: {o.summary}")
            for f in o.findings:
                if f.level in ("warn", "error"):
                    lines.append(f"      • {f.message}" + (f" ({f.count:,})" if f.count else ""))
        self.imported.emit()
        self.refresh()
        self.status.setText(f"{t('done')}: {ok} sheet(s), {rows:,} rows.\n" + "\n".join(lines[:60]))

    def delete_selected(self):
        idx = self.hist.view.selectionModel().selectedRows()
        if not idx:
            return
        r = self.hist.model.row(self.hist.proxy.mapToSource(idx[0]).row())
        if QMessageBox.question(self, t("delete_import"), f"{r['file_name']} · {r['sheet']}?") == QMessageBox.Yes:
            self.state.db.delete_import(r["import_id"])
            self.imported.emit()
            self.refresh()

    # ---------------------------------------------------------------- table
    def _busy(self, on, msg):
        self.prog.setVisible(on)
        self.prog.setValue(0)
        self.go.setEnabled(not on)
        if msg:
            self.status.setText(msg)

    def _progress(self, f, msg):
        self.prog.setValue(int(f * 100))
        self.status.setText(msg)

    def _fill(self):
        stores = [("", "—")] + [(s["code"], f"{s['code']} {s['name']}") for s in self.state.db.store_list()]
        types = [("skip", "Skip"), ("generic", "Unrecognised (keep rows)")] + sorted(
            [(k, s.name) for k, s in REGISTRY.items()], key=lambda x: x[1])
        rows = [(p, sp) for p in self.plans for sp in p.sheets]
        self.table.setRowCount(len(rows))
        self._widgets = []
        for i, (p, sp) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(p.path.name))
            self.table.setItem(i, 1, QTableWidgetItem(sp.sheet.name + ("  (hidden)" if sp.sheet.hidden else "")))
            cb = QComboBox()
            for k, n in types:
                cb.addItem(n, k)
            cb.setCurrentIndex(max(0, [k for k, _ in types].index(sp.chosen) if sp.chosen in [k for k, _ in types] else 0))
            self.table.setCellWidget(i, 2, cb)
            conf = QTableWidgetItem(f"{sp.confidence * 100:.0f}%")
            st = "good" if sp.confidence >= 0.8 else ("warn" if sp.confidence >= 0.5 else "bad")
            conf.setForeground(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor(theme.STATUS[st][0]))
            self.table.setItem(i, 3, conf)
            sc = QComboBox()
            for k, n in stores:
                sc.addItem(n, k)
            if sp.store:
                sc.setCurrentIndex(max(0, [k for k, _ in stores].index(sp.store)))
            sc.setEnabled(True)
            self.table.setCellWidget(i, 4, sc)
            de = QDateEdit()
            de.setCalendarPopup(True)
            de.setDisplayFormat("dd MMM yyyy")
            de.setSpecialValueText("auto")
            de.setMinimumDate(QDate(2015, 1, 1))
            d = sp.snapshot_date
            de.setDate(QDate(d.year, d.month, d.day) if d else de.minimumDate())
            self.table.setCellWidget(i, 5, de)
            self.table.setItem(i, 6, QTableWidgetItem(f"{sp.sheet.n_rows or 0:,}"))
            note = sp.reason
            if sp.needs_store and not sp.store:
                note = "⚠ " + t("pick_store") + " · " + note
            if sp.already_imported:
                note = t("already") + " " + note
            self.table.setItem(i, 7, QTableWidgetItem(note))
            self._widgets.append((sp, cb, sc, de))
        self.table.resizeColumnsToContents()
        self.go.setEnabled(bool(rows))

    def _read_back(self):
        for sp, cb, sc, de in getattr(self, "_widgets", []):
            sp.chosen = cb.currentData()
            spec = REGISTRY.get(sp.chosen)
            sp.needs_store = bool(spec and spec.needs_store)
            sp.store = sc.currentData() or None
            qd = de.date()
            sp.snapshot_date = None if qd == de.minimumDate() else date(qd.year(), qd.month(), qd.day())
