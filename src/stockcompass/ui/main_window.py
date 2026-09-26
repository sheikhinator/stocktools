"""Main window: sidebar, scope bar (where / department / section / role), language switch, pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from stockcompass import __version__
from stockcompass.analytics.core import Scope
from stockcompass.db import Database
from stockcompass.i18n import is_rtl, set_lang, t

from . import theme
from .import_page import ImportPage
from .pages import HealthPage, HomePage, ItemDialog, OrdersPage, ScorePage, StockPage
from .sales_page import SalesPage
from .settings_page import SettingsPage
from .widgets import label

ROLES = [("ho", "Head office"), ("dm", "District / regional"), ("sm", "Store manager"), ("dh", "Department head"),
         ("sec", "Section manager")]
ROLES_UR = {"ho": "ہیڈ آفس", "dm": "ڈسٹرکٹ منیجر", "sm": "اسٹور منیجر", "dh": "ڈیپارٹمنٹ ہیڈ", "sec": "سیکشن منیجر"}


class State:
    def __init__(self, db: Database, window: "MainWindow"):
        self.db = db
        self.window = window
        self.scope = Scope()
        self.role = "ho"
        self.period = None
        self.compare = "budget"

    def focus_store(self, code: str):
        self.window.set_where(code)


class MainWindow(QMainWindow):
    PAGES = ["home", "sales", "stock", "orders", "score", "import", "health", "settings"]

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.state = State(db, self)
        self.setWindowTitle(f"Stock Compass {__version__}")
        self.resize(1440, 900)
        self._building = False
        self.build()

    # ------------------------------------------------------------------ layout
    def build(self):
        self._building = True
        set_lang(self.db.setting("language") or "en")
        app = QApplication.instance()
        app.setLayoutDirection(Qt.RightToLeft if is_rtl() else Qt.LeftToRight)
        app.setFont(theme.base_font(is_rtl(), self.db.setting("urdu_font") or "Noto Nastaliq Urdu"))
        app.setStyleSheet(theme.qss(is_rtl()))
        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._sidebar())
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._topbar())
        self.stack = QStackedWidget()
        self.pages = {
            "home": HomePage(self.state), "sales": SalesPage(self.state), "stock": StockPage(self.state), "orders": OrdersPage(self.state),
            "score": ScorePage(self.state), "import": ImportPage(self.state), "health": HealthPage(self.state),
            "settings": SettingsPage(self.state),
        }
        for k in self.PAGES:
            p = self.pages[k]
            p.navigate.connect(self.go)
            p.openItem.connect(self.open_item)
            self.stack.addWidget(p)
        self.pages["import"].imported.connect(self.refresh_filters)
        self.pages["settings"].changed.connect(self.rebuild)
        right.addWidget(self.stack, 1)
        rw = QWidget()
        rw.setLayout(right)
        h.addWidget(rw, 1)
        self.setCentralWidget(root)
        self._building = False
        self.refresh_filters()
        self.go(getattr(self, "_current", "home"))

    def rebuild(self):
        cur = getattr(self, "_current", "home")
        self._current = cur
        self.build()

    def _sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        v = QVBoxLayout(side)
        v.setContentsMargins(12, 16, 12, 12)
        v.setSpacing(4)
        v.addWidget(label(t("app"), "brand"))
        v.addWidget(label(t("tagline"), "brandsub"))
        v.addSpacing(16)
        self.navgroup = QButtonGroup(self)
        self.navbtn = {}
        icons = {"home": "⌂", "sales": "▤", "stock": "▦", "orders": "⇄", "score": "◎", "import": "⬆", "health": "✓",
                 "settings": "⚙"}
        for k in self.PAGES:
            b = QPushButton(f"{icons[k]}   {t('nav_' + k)}")
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=k: self.go(k))
            self.navgroup.addButton(b)
            self.navbtn[k] = b
            v.addWidget(b)
            if k == "score":
                v.addSpacing(10)
        v.addStretch(1)
        last = self.db.one("SELECT max(imported_at) FROM imports WHERE status='ok'")
        v.addWidget(label(f"● {t('data_fresh')}: {last:%d %b %H:%M}" if last else "", "brandsub"))
        v.addWidget(label(f"v{__version__} · offline", "brandsub"))
        return side

    def _topbar(self):
        bar = QFrame()
        bar.setObjectName("topbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 10, 20, 10)
        h.setSpacing(8)
        self.where = QComboBox()
        self.where.setMinimumWidth(220)
        self.dept = QComboBox()
        self.sec = QComboBox()
        self.sec.setMinimumWidth(180)
        self.role = QComboBox()
        for k, n in ROLES:
            self.role.addItem(ROLES_UR[k] if is_rtl() else n, k)
        for lab_, w in [(t("where"), self.where), (t("department"), self.dept), (t("section"), self.sec)]:
            h.addWidget(label(lab_, "muted"))
            h.addWidget(w)
        h.addStretch(1)
        lang = QPushButton("اردو" if not is_rtl() else "English")
        lang.clicked.connect(self.toggle_lang)
        h.addWidget(lang)
        add = QPushButton("⬆ " + t("nav_import"))
        add.setObjectName("primary")
        add.clicked.connect(lambda: self.go("import"))
        h.addWidget(add)
        self.where.currentIndexChanged.connect(self._scope_changed)
        self.dept.currentIndexChanged.connect(self._dept_changed)
        self.sec.currentIndexChanged.connect(self._scope_changed)
        return bar

    # ------------------------------------------------------------------ scope
    def refresh_filters(self):
        self._building = True
        cur_where = self.where.currentData() if self.where.count() else None
        self.where.clear()
        self.where.addItem(t("all_stores"), "all")
        self.where.addItem(t("hypers"), "fmt:H")
        self.where.addItem(t("supers"), "fmt:S")
        self.where.addItem(t("mylis"), "fmt:M")
        for s in self.db.store_list():
            self.where.addItem(f"{s['code']} · {s['name']}", s["code"])
        if cur_where:
            i = self.where.findData(cur_where)
            if i >= 0:
                self.where.setCurrentIndex(i)
        self.dept.clear()
        self.dept.addItem(t("all_depts"), None)
        for c, n, nu in self.db.q("SELECT code, name, name_ur FROM departments ORDER BY code"):
            self.dept.addItem(f"{c} {nu if is_rtl() else n}", c)
        self._fill_sections()
        self._building = False
        self._scope_changed()

    def _fill_sections(self):
        self.sec.clear()
        self.sec.addItem(t("all_sections"), None)
        d = self.dept.currentData()
        rows = self.db.q("SELECT code, name FROM sections " + ("WHERE dept=? " if d else "") + "ORDER BY code",
                         [d] if d else [])
        for c, n in rows:
            self.sec.addItem(f"S{c} {n}", c)

    def _dept_changed(self):
        if self._building:
            return
        self._building = True
        self._fill_sections()
        self._building = False
        self._scope_changed()

    def _role_changed(self):
        self.state.role = self.role.currentData()
        self._scope_changed()

    def set_filter(self, dept: str | None = None, section: str | None = None):
        """Drill down from a table: set the department and/or section filter."""
        self._building = True
        if section and not dept:
            dept = self.db.one("SELECT dept FROM sections WHERE code=?", [section])
        if dept:
            i = self.dept.findData(dept)
            if i >= 0:
                self.dept.setCurrentIndex(i)
        self._fill_sections()
        if section:
            i = self.sec.findData(section)
            if i >= 0:
                self.sec.setCurrentIndex(i)
        self._building = False
        self._scope_changed()

    def set_where(self, code: str):
        i = self.where.findData(code)
        if i >= 0:
            self.where.setCurrentIndex(i)

    def _scope_changed(self):
        if self._building:
            return
        w = self.where.currentData()
        sc = Scope()
        if w and w.startswith("fmt:"):
            sc.formats = [w[4:]]
        elif w and w != "all":
            sc.stores = [w]
        sc.dept = self.dept.currentData()
        sc.section = self.sec.currentData()
        if sc.section and not sc.dept:
            sc.dept = self.db.one("SELECT dept FROM sections WHERE code=?", [sc.section])
        self.state.scope = sc
        self.go(getattr(self, "_current", "home"), refresh=True)

    # ------------------------------------------------------------------ navigation
    def go(self, target: str, refresh: bool = True):
        page, _, tab = target.partition(":")
        if page not in self.pages:
            return
        self._current = page
        p = self.pages[page]
        if tab:
            p.show_tab(tab)
        if refresh:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                p.refresh()
            finally:
                QApplication.restoreOverrideCursor()
        self.stack.setCurrentWidget(p)
        self.navbtn[page].setChecked(True)

    def open_item(self, item: str):
        ItemDialog(self.db, item, self).exec()

    def toggle_lang(self):
        self.db.set_setting("language", "en" if is_rtl() else "ur")
        self.rebuild()
