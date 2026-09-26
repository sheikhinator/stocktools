"""Sales: net sales vs budget and last year, growth bridge, breakdown with drill-down, family map, suppliers,
bulk (B2B), items and lines lost since last year."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from stockcompass.analytics import sales as SA
from stockcompass.analytics.core import L, fmt_pkr
from stockcompass.i18n import is_rtl, t

from .pages import Page
from .widgets import (DataTable, KpiCard, bar_chart, card, empty_state, grid_of, label, scatter_chart,
                      waterfall_chart)

LEVEL_NAME = {"dept": ("Departments", "ڈیپارٹمنٹس"), "section": ("Sections", "سیکشنز"), "store": ("Stores", "اسٹورز")}


class SalesPage(Page):
    TABS = ["breakdown", "stores", "families", "suppliers", "b2b", "items", "lost"]

    def __init__(self, state, parent=None):
        super().__init__(state, parent)
        self._tab = "breakdown"

    def show_tab(self, name):
        self._tab = name
        if hasattr(self, "tabs") and name in self.TABS:
            self.tabs.setCurrentIndex(self.TABS.index(name))

    # ------------------------------------------------------------------------------------------
    def refresh(self):
        lay = self.reset()
        st = self.state
        self.header(lay, L("Sales", "سیلز"), L("How much we sold, against budget and last year, and where it came from.",
                                               "ہم نے کتنا بیچا، بجٹ اور پچھلے سال کے مقابلے میں، اور کہاں سے۔"))
        pers = SA.periods(st.db)
        if not pers:
            lay.addWidget(empty_state(t("no_data") + L(" (BO 11b, 11f, family sales or 200-10-05 store net sales)",
                                                       " (بی او 11 بی، 11 ایف، فیملی سیلز یا اسٹور نیٹ سیلز)")))
            lay.addStretch(1)
            return
        avail = [p for p, _ in pers]
        if getattr(st, "period", None) not in avail:
            st.period = "MTD" if "MTD" in avail else avail[0]
        st.compare = getattr(st, "compare", "budget")
        bar = QHBoxLayout()
        per = QComboBox()
        for p, d in pers:
            per.addItem(f"{L(*SA.PERIOD_NAMES.get(p, (p, p)))} · {d:%d %b %Y}", p)
        per.setCurrentIndex(avail.index(st.period))
        per.currentIndexChanged.connect(lambda i: (setattr(st, "period", per.itemData(i)), self.refresh()))
        cmp_ = QComboBox()
        cmp_.addItem(L("vs budget", "بجٹ کے مقابلے"), "budget")
        cmp_.addItem(L("vs last year", "پچھلے سال کے مقابلے"), "ly")
        cmp_.setCurrentIndex(0 if st.compare == "budget" else 1)
        cmp_.currentIndexChanged.connect(lambda i: (setattr(st, "compare", cmp_.itemData(i)), self.refresh()))
        bar.addWidget(label(L("Period", "مدت"), "muted"))
        bar.addWidget(per)
        bar.addWidget(label(L("Compare", "موازنہ"), "muted"))
        bar.addWidget(cmp_)
        bar.addStretch(1)
        lay.addLayout(bar)

        kp, ov = SA.kpis(st.db, st.scope, st.period, st.compare)
        if not kp:
            lay.addWidget(empty_state(L("No sales rows for this selection. Try another period or 'All stores'.",
                                        "اس انتخاب کے لیے سیلز ڈیٹا نہیں۔")))
            lay.addStretch(1)
            return
        cards = []
        for k in kp:
            c = KpiCard(k)
            c.clicked.connect(self.navigate.emit)
            cards.append(c)
        lay.addWidget(grid_of(cards, min(6, max(3, len(cards)))))

        groups = [g for g in ov.get("by_group", []) if g["sales"] or g["budget"]]
        if groups:
            lvl = ov.get("group_level", "dept")
            cmp_name = L("Budget", "بجٹ") if st.compare == "budget" else L("Last year", "پچھلا سال")
            top = groups[:8]
            cmpvals = [(g["budget"] if st.compare == "budget" else g["ly"]) or 0 for g in top]
            charts = QHBoxLayout()
            charts.addWidget(card(bar_chart([g["name"][:16] for g in top],
                                            {L("Net sales", "نیٹ سیلز"): [g["sales"] for g in top], cmp_name: cmpvals}),
                                  f"{L(*LEVEL_NAME[lvl])}: {L('sales vs', 'سیلز بمقابلہ')} {cmp_name.lower()}"), 1)
            base = sum((g["budget"] if st.compare == "budget" else g["ly"]) or 0 for g in groups)
            steps = [(g["name"][:14], g["sales"] - ((g["budget"] if st.compare == "budget" else g["ly"]) or 0)) for g in groups[:6]]
            rest = sum(g["sales"] - ((g["budget"] if st.compare == "budget" else g["ly"]) or 0) for g in groups[6:])
            if len(groups) > 6:
                steps.append((L("Other", "دیگر"), rest))
            if base:
                charts.addWidget(card(waterfall_chart(cmp_name, base, steps, L("Net sales", "نیٹ سیلز"), ov["sales"]),
                                      L("What moved the total", "کل میں تبدیلی کہاں سے"),
                                      L(f"From {cmp_name.lower()} to actual, group by group", "گروپ کے حساب سے")), 1)
            lay.addLayout(charts)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._breakdown(ov), L("Breakdown", "تفصیل"))
        self.tabs.addTab(self._stores(ov), L("Stores", "اسٹورز"))
        self.tabs.addTab(self._families(), L("Families", "فیملیز"))
        self.tabs.addTab(self._suppliers(), L("Suppliers", "سپلائرز"))
        self.tabs.addTab(self._b2b(), L("Bulk (B2B)", "بلک (B2B)"))
        self.tabs.addTab(self._items(), L("Items", "آئٹمز"))
        self.tabs.addTab(self._lost(), L("Lost since last year", "پچھلے سال کے بعد ختم"))
        self.tabs.setCurrentIndex(self.TABS.index(self._tab) if self._tab in self.TABS else 0)
        self.tabs.currentChanged.connect(lambda i: setattr(self, "_tab", self.TABS[i]))
        lay.addWidget(self.tabs, 1)
        info = ov.get("info", {})
        lay.addWidget(label(L(f"Source: BO {info.get('source', '')} at {info.get('level', '').replace('_', ' ')} level. "
                              "Percentages are recalculated from the base values.",
                              f"ذریعہ: بی او {info.get('source', '')}"), "muted"))

    # ------------------------------------------------------------------------------------------
    def _group_cols(self):
        return [("name", "text"), ("sales", "money"), ("budget", "money"), ("vs_budget", "pct"), ("ly", "money"),
                ("growth", "pct"), ("share", "pct"), ("margin", "pct"), ("waste", "pct"), ("oos", "pct"),
                ("stock_value", "money")]

    def _breakdown(self, ov):
        rows = [g for g in ov.get("by_group", []) if g["sales"] or g["budget"]]
        if not rows:
            return empty_state(t("no_data"))
        lvl = ov.get("group_level", "dept")
        tbl = DataTable(self._group_cols(), rows, export_name="sales_breakdown",
                        colorer=lambda r: "bad" if (r["margin"] or 0) < 0 else "")
        tbl.setMinimumHeight(360)

        def drill(r):
            if lvl == "dept":
                self.state.window.set_filter(dept=r["key"])
            elif lvl == "section":
                self.state.window.set_filter(section=r["key"])
            elif lvl == "store":
                self.state.focus_store(r["key"])
        tbl.rowActivated.connect(drill)
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 8, 0, 0)
        l.addWidget(label(L(f"{L(*LEVEL_NAME[lvl])}. Double-click a row to go one level down. Red = negative front "
                            "margin.", "نیچے جانے کے لیے قطار پر ڈبل کلک کریں۔ سرخ = منفی مارجن۔"), "muted"))
        l.addWidget(tbl)
        return w

    def _stores(self, ov):
        rows = [g for g in ov.get("by_store", []) if g["sales"] or g["budget"]]
        if not rows:
            return empty_state(L("Store-level sales need the 11b department or section tab, or the store net sales "
                                 "report.", "اسٹور لیول سیلز کے لیے 11 بی یا اسٹور نیٹ سیلز رپورٹ درکار ہے۔"))
        tbl = DataTable(self._group_cols(), rows, export_name="sales_by_store",
                        colorer=lambda r: "" if r["vs_budget"] is None else ("good" if r["vs_budget"] >= 0 else
                                                                             ("bad" if r["vs_budget"] < -10 else "warn")))
        tbl.rowActivated.connect(lambda r: self.state.focus_store(r["key"]))
        tbl.setMinimumHeight(360)
        return tbl

    def _families(self):
        st = self.state
        rows = SA.families(st.db, st.scope, st.period)
        if not rows:
            return empty_state(t("no_data") + " (BO 11f / family sales)")
        pts = [dict(x=r["growth"], y=r["margin"], name=r["name"], size=r["sales_cy"], row=r) for r in rows[:40]]
        chart = scatter_chart(pts, L("Growth vs last year", "پچھلے سال کے مقابلے اضافہ"), L("Front margin", "فرنٹ مارجن"))
        tbl = DataTable([("name", "text"), ("section_name", "text"), ("sales_cy", "money"), ("sales_ly", "money"),
                         ("growth", "pct"), ("share", "pct"), ("margin", "pct"), ("b2b_share", "pct"), ("promo", "pct"),
                         ("suppliers", "int")], rows, export_name="families",
                        colorer=lambda r: "bad" if (r["growth"] or 0) < 0 and (r["margin"] or 0) < 0 else "")
        tbl.setMinimumHeight(320)
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 8, 0, 0)
        l.addWidget(card(chart, L("Family map: growth vs margin", "فیملی نقشہ: اضافہ بمقابلہ مارجن"),
                         L("Top 40 families by sales. Bottom-left = shrinking and low margin.",
                           "نیچے بائیں = کم ہوتی سیلز اور کم مارجن")))
        l.addWidget(tbl)
        return w

    def _suppliers(self):
        st = self.state
        rows = SA.suppliers(st.db, st.scope, st.period)
        if not rows:
            return empty_state(t("no_data") + " (BO 11f)")
        tbl = DataTable([("name", "text"), ("sales_cy", "money"), ("sales_ly", "money"), ("growth", "pct"),
                         ("share", "pct"), ("margin", "pct"), ("b2b", "money"), ("b2b_margin", "pct"), ("promo", "pct"),
                         ("purchase", "money"), ("families", "int")], rows, export_name="suppliers",
                        colorer=lambda r: "bad" if (r["margin"] or 0) < 0 else "")
        tbl.setMinimumHeight(420)
        tbl.rowActivated.connect(lambda r: self.state.window.open_supplier(r["key"]))
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 8, 0, 0)
        l.addWidget(label(L("Double-click a supplier for its full view. Front margin only (before supplier rebates), so big suppliers can show negative margin. "
                            "Red = negative front margin.", "صرف فرنٹ مارجن (ریبیٹ سے پہلے)۔"), "muted"))
        l.addWidget(tbl)
        return w

    def _b2b(self):
        st = self.state
        rows = SA.b2b_by_store(st.db, st.scope, st.period)
        fams = [r for r in SA.families(st.db, st.scope, st.period) if r.get("b2b")]
        if not rows and not fams:
            return empty_state(L("No bulk (B2B) sales in the 11f data for this selection.", "بلک سیلز نہیں۔"))
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 8, 0, 0)
        if rows:
            rows_ = sorted(rows, key=lambda r: -r["b2b"])
            l.addWidget(card(bar_chart([r["name"][:16] for r in rows_][::-1], {"B2B": [r["b2b"] for r in rows_][::-1]},
                                       horizontal=True, height=max(180, 30 * len(rows_))),
                             L("Bulk sales by store", "اسٹور کے حساب سے بلک سیلز")))
        cols = [("name", "text"), ("b2b", "money"), ("b2b_share", "pct"), ("b2b_margin", "pct"), ("sales_cy", "money"),
                ("margin", "pct")]
        tbl = DataTable(cols, sorted(fams, key=lambda r: -(r["b2b"] or 0)), export_name="b2b_families",
                        colorer=lambda r: "bad" if (r["b2b_margin"] or 0) < 0 else "")
        tbl.setMinimumHeight(300)
        l.addWidget(card(tbl, L("Families with bulk sales", "بلک سیلز والی فیملیز"),
                         L("Red = bulk sold below cost (negative front margin).", "سرخ = لاگت سے کم پر بلک")))
        return w

    def _items(self):
        st = self.state
        rows = SA.items(st.db, st.scope)
        if not rows:
            return empty_state(t("no_data") + " (GIMA benchmark)")
        tbl = DataTable([("item", "text"), ("description", "text"), ("section_name", "text"), ("sales", "money"),
                         ("qty", "num"), ("margin", "money"), ("margin_pct", "pct"), ("abc", "text"), ("stock", "num"),
                         ("stores", "int"), ("supplier_name", "text"), ("date_from", "date"), ("date_to", "date")],
                        rows, export_name="item_sales", colorer=lambda r: "bad" if (r["margin"] or 0) < 0 else "")
        tbl.rowActivated.connect(lambda r: self.openItem.emit(r["item"]))
        tbl.setMinimumHeight(420)
        return tbl

    def _lost(self):
        st = self.state
        rows = SA.lost_lines(st.db, st.scope, "YTD")
        if not rows:
            return empty_state(L("Nothing found (needs the BO 11f store tab).", "کچھ نہیں ملا۔"))
        tbl = DataTable([("store_name", "text"), ("section_name", "text"), ("family_name", "text"),
                         ("supplier_name", "text"), ("sales_ly", "money"), ("purchase", "money")], rows,
                        export_name="lost_lines")
        tbl.setMinimumHeight(420)
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 8, 0, 0)
        l.addWidget(label(L("Family × supplier lines that sold last year (year to date) and nothing this year: range "
                            "gaps or suppliers that stopped. Purchase with no sales = stock arriving for something "
                            "that is not selling.", "پچھلے سال بکنے والی مگر اس سال صفر لائنیں۔"), "muted", wrap=True))
        l.addWidget(tbl)
        return w
