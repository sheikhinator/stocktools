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
from .more_pages import CategoryPage, PromosPage, SupplierDialog
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
    PAGES = ["home", "sales", "stock", "orders", "promos", "category", "score", "import", "health", "settings"]

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
            "home": HomePage(self.state), "sales": SalesPage(self.state), "promos": PromosPage(self.state),
            "category": CategoryPage(self.state), "stock": StockPage(self.state), "orders": OrdersPage(self.state),
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
        icons = {"home": "⌂", "sales": "▤", "promos": "✦", "category": "◫", "stock": "▦", "orders": "⇄", "score": "◎", "import": "⬆", "health": "✓",
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
        self.role = QComboBox()
        for k, n in ROLES:
            self.role.addItem(ROLES_UR[k] if is_rtl() else n, k)
        self.where = QComboBox()
        self.where.setMinimumWidth(200)
        self.dept = QComboBox()
        self.sec = QComboBox()
        self.sec.setMinimumWidth(170)
        for lab_, w in [(t("view_as"), self.role), (t("where"), self.where), (t("department"), self.dept),
                        (t("section"), self.sec)]:
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
        self.role.currentIndexChanged.connect(self._role_changed)
        return bar

    # ------------------------------------------------------------------ scope
    def refresh_filters(self):
        self._building = True
        saved = self.db.setting("view") or {}
        cur_where = self.where.currentData() if self.where.count() else saved.get("where")
        cur_dept = self.dept.currentData() if self.dept.count() else saved.get("dept")
        cur_sec = self.sec.currentData() if self.sec.count() else saved.get("section")
        role = self.state.role if getattr(self, "_role_init", False) else saved.get("role", "ho")
        self._role_init = True
        i = self.role.findData(role)
        if i >= 0:
            self.role.setCurrentIndex(i)
        self.state.role = self.role.currentData()
        self.where.clear()
        self.where.addItem(t("all_stores"), "all")
        for r in [x[0] for x in self.db.q("SELECT DISTINCT region FROM stores WHERE active AND region IS NOT NULL ORDER BY 1")]:
            self.where.addItem(("ریجن: " if is_rtl() else "Region: ") + r, "reg:" + r)
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
        self.dept.addItem("نان فوڈ (LHH, HHH, TXT)" if is_rtl() else "Non-Food (LHH, HHH, TXT)", "NF")
        if cur_dept:
            i = self.dept.findData(cur_dept)
            if i >= 0:
                self.dept.setCurrentIndex(i)
        self._fill_sections()
        if cur_sec:
            i = self.sec.findData(cur_sec)
            if i >= 0:
                self.sec.setCurrentIndex(i)
        self._apply_role_rules()
        self._building = False
        self._scope_changed()

    def _fill_sections(self):
        self.sec.clear()
        self.sec.addItem(t("all_sections"), None)
        d = self.dept.currentData()
        depts = ["03", "04", "05"] if d == "NF" else ([d] if d else [])
        q = "SELECT code, name FROM sections " + (f"WHERE dept IN ({','.join('?' * len(depts))}) " if depts else "") + "ORDER BY code"
        for c, n in self.db.q(q, depts):
            self.sec.addItem(f"S{c} {n}", c)

    def _dept_changed(self):
        if self._building:
            return
        self._building = True
        self._fill_sections()
        self._building = False
        self._scope_changed()

    def _apply_role_rules(self):
        """Each role needs a scope: a store for store roles, a region for district, a department for heads."""
        role = self.role.currentData()
        w = self.where.currentData() or "all"
        is_store = w not in ("all",) and not w.startswith(("fmt:", "reg:"))
        if role in ("sm", "dh", "sec") and not is_store:
            first = next((i for i in range(self.where.count()) if not str(self.where.itemData(i)).startswith(("all", "fmt:", "reg:"))), None)
            if first is not None:
                self.where.setCurrentIndex(first)
        if role == "dm" and not w.startswith("reg:"):
            i = next((i for i in range(self.where.count()) if str(self.where.itemData(i)).startswith("reg:")), None)
            if i is not None:
                self.where.setCurrentIndex(i)
        if role in ("dh", "sec") and not self.dept.currentData():
            self.dept.setCurrentIndex(max(0, self.dept.findData("01")))
            self._fill_sections()
        if role == "sec" and not self.sec.currentData() and self.sec.count() > 1:
            self.sec.setCurrentIndex(1)
        if role in ("ho",):
            pass
        hide = {"category"} if role in ("sm", "dh", "sec") else set()
        for k, b in getattr(self, "navbtn", {}).items():
            b.setVisible(k not in hide)

    def _role_changed(self):
        if self._building:
            return
        self.state.role = self.role.currentData()
        self._building = True
        if self.state.role == "ho":
            self.where.setCurrentIndex(0)
            self.dept.setCurrentIndex(0)
            self._fill_sections()
        self._apply_role_rules()
        self._building = False
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
        elif w and w.startswith("reg:"):
            sc.region = w[4:]
        elif w and w != "all":
            sc.stores = [w]
        sc.dept = self.dept.currentData()
        sc.section = self.sec.currentData()
        if sc.section and not sc.dept:
            sc.dept = self.db.one("SELECT dept FROM sections WHERE code=?", [sc.section])
        self.state.scope = sc
        self.state.role = self.role.currentData() or "ho"
        self.db.set_setting("view", {"role": self.state.role, "where": w, "dept": self.dept.currentData(),
                                     "section": self.sec.currentData()})
        cur = getattr(self, "_current", "home")
        if cur == "category" and self.state.role in ("sm", "dh", "sec"):
            cur = "home"
        self.go(cur, refresh=True)

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

    def open_supplier(self, code: str):
        SupplierDialog(self.state, code, self).exec()

    def toggle_lang(self):
        self.db.set_setting("language", "en" if is_rtl() else "ur")
        self.rebuild()
