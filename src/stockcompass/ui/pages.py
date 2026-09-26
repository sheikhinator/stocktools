"""The main screens. Each page reads the shared state (database + scope) and redraws on refresh()."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from stockcompass.analytics import core as A
from stockcompass.analytics.core import L
from stockcompass.i18n import is_rtl, t

from . import theme
from .widgets import (DataTable, ExplainDialog, InsightCard, KpiCard, bar_chart, card, empty_state, fmt_value,
                      grid_of, label, line_chart, scroll_page)


class Page(QWidget):
    navigate = Signal(str)
    openItem = Signal(str)

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setObjectName("page")
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(0, 0, 0, 0)
        self.body = None

    def reset(self) -> QVBoxLayout:
        if self.body is not None:
            self.body.setParent(None)
            self.body.deleteLater()
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(22, 16, 22, 22)
        lay.setSpacing(14)
        self.body = scroll_page(inner)
        self.outer.addWidget(self.body)
        return lay

    def header(self, lay: QVBoxLayout, title: str, sub: str):
        lay.addWidget(label(title, "h1"))
        lay.addWidget(label(sub, "sub", wrap=True))
        lay.addWidget(label("📍 " + self.state.scope.label(self.state.db), "chip"), 0,
                      Qt.AlignRight if is_rtl() else Qt.AlignLeft)

    def item_table(self, columns, rows, name, colorer=None) -> DataTable:
        tbl = DataTable(columns, rows, colorer=colorer, export_name=name)
        tbl.setMinimumHeight(360)
        tbl.rowActivated.connect(lambda r: r.get("item") and self.openItem.emit(r["item"]))
        return tbl

    def refresh(self):
        pass

    def show_tab(self, name: str):
        pass


# ================================================================================================
# Home
# ================================================================================================
class HomePage(Page):
    def refresh(self):
        lay = self.reset()
        st = self.state
        role = getattr(st, "role", "ho")
        who = {"ho": L("head office", "ہیڈ آفس"), "dm": L("district manager", "ڈسٹرکٹ منیجر"),
               "sm": L("store manager", "اسٹور منیجر"), "dh": L("department head", "ڈیپارٹمنٹ ہیڈ"),
               "sec": L("section manager", "سیکشن منیجر")}.get(role, "")
        greet = t("greet_ho") if role == "ho" and not st.scope.stores else f"{t('greet_store')}, {who}"
        lay.addWidget(label(greet, "h1"))
        lay.addWidget(label(t("home_sub"), "sub", wrap=True))
        lay.addWidget(label("📍 " + st.scope.label(st.db), "chip"), 0, Qt.AlignRight if is_rtl() else Qt.AlignLeft)
        if role in ("sm", "dh", "sec"):
            from .jobs_widget import JobsPanel
            jp = JobsPanel(st)
            jp.openItem.connect(self.openItem.emit)
            lay.addWidget(jp)
        kpis, insights = A.overview(st.db, st.scope)
        if getattr(st, "role", "ho") in ("sm", "dh", "sec"):
            insights = [i for i in insights if i.get("goto") != "health"]  # workbook / data-quality notes are for head office
        from stockcompass.analytics import sales as SA
        pers = [p for p, _ in SA.periods(st.db)]
        if pers:
            per = st.period if getattr(st, "period", None) in pers else ("MTD" if "MTD" in pers else pers[0])
            sk, _ = SA.kpis(st.db, st.scope, per, "budget")
            for k in sk:
                k.goto = "sales"
            kpis = [k for k in sk if k.key in ("sales", "growth", "margin")] + kpis
        if not kpis:
            w = card(label(t("welcome_text"), wrap=True), t("welcome_title"))
            go = QPushButton(t("nav_import"))
            go.setObjectName("primary")
            go.clicked.connect(lambda: self.navigate.emit("import"))
            w.layout().addWidget(go, 0, Qt.AlignLeft)
            lay.addWidget(w)
            lay.addStretch(1)
            return
        cards = []
        for k in kpis:
            c = KpiCard(k)
            c.clicked.connect(self.navigate.emit)
            cards.append(c)
        lay.addWidget(grid_of(cards, 4 if len(cards) > 6 else max(3, min(4, len(cards)))))
        row = QHBoxLayout()
        row.setSpacing(12)
        ins_box = QWidget()
        il = QVBoxLayout(ins_box)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(8)
        for ins in insights[:8]:
            ic = InsightCard(ins)
            ic.clicked.connect(self.navigate.emit)
            il.addWidget(ic)
        il.addStretch(1)
        row.addWidget(card(ins_box, t("things_to_know")), 1)
        zs = A.zero_stock_summary(st.db, st.scope)
        right = QVBoxLayout()
        if zs:
            by_fmt = self._trend_by_format()
            target = st.db.one("SELECT min(target) FROM bc_targets WHERE indicator='zero_stock'", default=None)
            right.addWidget(card(line_chart(by_fmt, target=target), t("zs_trend"),
                                 f"{zs['month_start']:%d %b} – {zs['last_day']:%d %b}"))
            names = {c: n for c, n in st.db.q("SELECT code, name FROM stores")}
            rows = [dict(s, store_name=names.get(s["store"], s["store"])) for s in zs["stores"]]
            tbl = DataTable([("store_name", "text"), ("mtd_pct", "pct"), ("day_pct", "pct"), ("zero_today", "int"),
                             ("items_today", "int")], rows,
                            colorer=lambda r: "bad" if (r["mtd_pct"] or 0) > (target or 12) * 1.25 else
                            ("warn" if (r["mtd_pct"] or 0) > (target or 12) else "good"), export_name="zero_stock_by_store")
            tbl.setMinimumHeight(300)
            tbl.rowActivated.connect(lambda r: self.state.focus_store(r["store"]))
            right.addWidget(card(tbl, t("store_ranking"), "Double-click a store to focus on it."))
        rw = QWidget()
        rw.setLayout(right)
        row.addWidget(rw, 1)
        lay.addLayout(row)
        fresh = A.data_status(st.db)
        txt = "   ·   ".join(f"{r['report_type']}: {r['latest']:%d %b}" for r in fresh[:8] if r["latest"])
        lay.addWidget(label(f"{t('data_fresh')}: {txt}", "muted", wrap=True))
        lay.addStretch(1)

    def _trend_by_format(self):
        st = self.state
        rows = A.zero_stock_daily(st.db, st.scope)
        fmt = {c: f for c, f in st.db.q("SELECT code, format FROM stores")}
        agg = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
        for r in rows:
            if r["suspect"] or not r["total"]:
                continue
            f = fmt.get(r["store"], "?")
            agg[f][r["day"]][0] += r["zero"]
            agg[f][r["day"]][1] += r["total"]
        names = {"H": t("hyper"), "S": t("super"), "M": t("myli")}
        out = {}
        for f in ("H", "S", "M"):
            if f in agg:
                out[names[f]] = sorted((d, z / tt * 100) for d, (z, tt) in agg[f].items() if tt)
        return out


# ================================================================================================
# Stock health
# ================================================================================================
class StockPage(Page):
    TABS = ["zero", "oos", "neg", "sleeping", "dp", "move", "blocked", "leaflet"]

    def __init__(self, state, parent=None):
        super().__init__(state, parent)
        self._tab = "oos"

    def show_tab(self, name):
        self._tab = name
        if hasattr(self, "tabs"):
            self.tabs.setCurrentIndex(self.TABS.index(name) if name in self.TABS else 0)

    def refresh(self):
        lay = self.reset()
        self.header(lay, t("stock_title"), t("stock_sub"))
        self.tabs = QTabWidget()
        builders = [self._zero, self._oos, self._neg, self._sleeping, self._dp, self._move, self._blocked, self._leaflet]
        for key, b in zip(self.TABS, builders):
            self.tabs.addTab(b(), t(f"tab_{key}"))
        self.tabs.setCurrentIndex(self.TABS.index(self._tab) if self._tab in self.TABS else 0)
        self.tabs.currentChanged.connect(lambda i: setattr(self, "_tab", self.TABS[i]))
        lay.addWidget(self.tabs, 1)

    def _wrap(self, *widgets) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 10, 0, 0)
        l.setSpacing(12)
        for x in widgets:
            l.addWidget(x) if isinstance(x, QWidget) else l.addLayout(x)
        return w

    def _zero(self):
        st = self.state
        zs = A.zero_stock_summary(st.db, st.scope)
        if not zs:
            return self._wrap(empty_state(t("no_data") + " (BO 500-30-15)"))
        rows = A.zero_stock_daily(st.db, st.scope)
        names = {c: n for c, n in st.db.q("SELECT code, name FROM stores")}
        series = defaultdict(list)
        for r in rows:
            if not r["suspect"] and r["total"]:
                series[names.get(r["store"], r["store"])].append((r["day"], r["zero"] / r["total"] * 100))
        top = sorted(zs["stores"], key=lambda s: -(s["mtd_pct"] or 0))[:6]
        chart_series = {names.get(s["store"], s["store"]): sorted(series[names.get(s["store"], s["store"])]) for s in top}
        target = st.db.one("SELECT min(target) FROM bc_targets WHERE indicator='zero_stock'", default=None)
        store_rows = [dict(s, store_name=names.get(s["store"], s["store"])) for s in zs["stores"]]
        tbl = DataTable([("store_name", "text"), ("mtd_pct", "pct"), ("day_pct", "pct"), ("zero_today", "int"),
                         ("items_today", "int")], store_rows, export_name="zero_stock")
        tbl.setMinimumHeight(300)
        tbl.rowActivated.connect(lambda r: self.state.focus_store(r["store"]))
        ex = A.Explain("Zero stock %", "Items with closing stock of zero or below (negative included) ÷ items in range, "
                       "summed over the days of the month. Days where the stock load failed are left out.",
                       f"{zs['mtd_zero']:,.0f} ÷ {zs['mtd_total']:,.0f} = {zs['mtd_pct']:.2f}%",
                       "BO 500-30-15 zero stock summary", f"{zs['month_start']:%d %b} – {zs['last_day']:%d %b %Y}")
        how = QPushButton("ⓘ " + t("how"))
        how.setObjectName("link")
        how.clicked.connect(lambda: ExplainDialog(ex, self).exec())
        return self._wrap(card(line_chart(chart_series, target=target, height=280),
                               "Worst 6 stores: zero stock % by day", tools=[how]),
                          card(tbl, t("store_ranking")))

    def _oos(self):
        st = self.state
        rows = A.oos_items(st.db, st.scope)
        if not rows:
            return self._wrap(empty_state(t("no_data") + " (GIMA zero stock sheet)"))
        g = Counter(r["reason_group"] for r in rows)
        cats = [A.REASON_ACTION[k][2 if is_rtl() else 0] for k, _ in g.most_common()]
        chart = bar_chart(cats[::-1], {t("rows"): [v for _, v in g.most_common()][::-1]}, horizontal=True,
                          height=max(160, 34 * len(cats)))
        tbl = self.item_table([("store_name", "text"), ("item", "text"), ("description", "text"),
                               ("section_name", "text"), ("on_order", "bool"), ("reason", "text"), ("action", "text"),
                               ("days_out", "int"), ("dlyavg", "num"), ("lost_per_day", "money"),
                               ("lost_to_date", "money"), ("order_mode", "text"), ("supplier_name", "text"),
                               ("delivery_date", "date")], rows, "out_of_stock",
                              colorer=lambda r: "bad" if not r["on_order"] else ("warn" if r["late"] else ""))
        return self._wrap(card(chart, t("why_oos")), card(tbl, t("oos_list"), t("open_item")))

    def _neg(self):
        st = self.state
        rows = A.negative_items(st.db, st.scope)
        if not rows:
            return self._wrap(empty_state(t("no_data") + " (GIMA negative stock sheet / RealTime)"))
        c = Counter(r["status"] or "?" for r in rows)
        chart = bar_chart(list(c.keys()), {t("rows"): list(c.values())}, height=200)
        tbl = self.item_table([("store_name", "text"), ("item", "text"), ("description", "text"), ("qty", "num"),
                               ("status", "text"), ("cause", "text"), ("action", "text"), ("value", "money")],
                              rows, "negative_stock")
        return self._wrap(card(chart, t("neg_by_cause"), "NI = not part of inventory · NC = not active (blocked) · "
                                                         "AC = active"), card(tbl, t("tab_neg"), t("open_item")))

    def _dp(self):
        st = self.state
        rows = A.dp_items(st.db, st.scope)
        if not rows:
            return self._wrap(empty_state(t("no_data") + " (DP workbook, master data sheet)"))
        order = ["6 Months", "9 Months", "1 Year", "1.5 Year", "2 Years", "Above 2 years"]
        b = defaultdict(float)
        for r in rows:
            b[r["bucket"] or "?"] += r["value"] or 0
        cats = [x for x in order if x in b] + [x for x in b if x not in order]
        c1 = bar_chart(cats, {"PKR": [b[x] for x in cats]}, height=240)
        rt = defaultdict(float)
        for r in rows:
            rt[r["route"]] += r["value"] or 0
        rk = sorted(rt, key=rt.get)
        c2 = bar_chart(rk, {"PKR": [rt[x] for x in rk]}, horizontal=True, height=240)
        charts = QHBoxLayout()
        charts.addWidget(card(c1, t("dp_by_bucket")), 1)
        charts.addWidget(card(c2, t("dp_by_route"), "IST → markdown → return to supplier → write-off"), 1)
        tbl = self.item_table([("store_name", "text"), ("item", "text"), ("description", "text"),
                               ("section_name", "text"), ("qty", "num"), ("value", "money"), ("age_days", "int"),
                               ("bucket", "text"), ("prov_pct", "pct"), ("provision", "money"),
                               ("days_to_next", "int"), ("extra_provision", "money"), ("route", "text"),
                               ("route_why", "text"), ("supplier_name", "text")], rows, "dp_stock",
                              colorer=lambda r: "warn" if r["days_to_next"] is not None and r["days_to_next"] <= 30 else "")
        return self._wrap(charts, card(tbl, t("dp_list"), "Amber rows move to a higher provision step within 30 days."))

    def _sleeping(self):
        from stockcompass.analytics import extra as X
        st = self.state
        rows, note = X.sleeping(st.db, st.scope)
        if not rows:
            return self._wrap(empty_state(note or (t("no_data") + " (GIMA RealTime + benchmark)")))
        tv = sum(r["value"] for r in rows)
        tbl = self.item_table([("store_name", "text"), ("item", "text"), ("description", "text"), ("section_name", "text"),
                               ("qty", "num"), ("value", "money"), ("days_rule", "int"), ("last_sale", "date"),
                               ("supplier_name", "text")], rows, "sleeping_stock")
        return self._wrap(card(tbl, L(f"{len(rows):,} items with stock and no sale · {A.fmt_pkr(tv)} at cost",
                                      f"{len(rows):,} آئٹمز بغیر سیل · {A.fmt_pkr(tv)}"),
                               L("Active items with stock on hand and no sale in the benchmark files for 30 days (CG) or "
                                 "60 days (non-food), the BC rule.", "بی سی قاعدہ: سی جی 30 دن، نان فوڈ 60 دن۔")
                               + (" " + note if note else "")))

    def _move(self):
        from stockcompass.analytics import extra as X
        st = self.state
        rows = X.ist(st.db, st.scope)
        if not rows:
            return self._wrap(empty_state(L("No transfer found yet. Suggestions need aged (DP) or sleeping stock in one "
                                            "store and the same item out of stock (with daily sales) in another: DP "
                                            "master + GIMA zero stock sheets for several stores.",
                                            "ٹرانسفر کے لیے کئی اسٹورز کا ڈیٹا درکار ہے۔")))
        tbl = self.item_table([("item", "text"), ("description", "text"), ("from_store", "text"), ("to_store", "text"),
                               ("qty", "num"), ("value", "money"), ("why", "text"), ("sells_per_day", "num"),
                               ("lost_per_day", "money"), ("same_region", "bool")], rows, "ist_suggestions")
        return self._wrap(card(tbl, L("Move stock between stores (IST)", "اسٹورز کے درمیان اسٹاک منتقلی"),
                               L("Stock that is aged or not selling in one store, sent to a store where the item is out of "
                                 "stock and normally sells. Quantity = up to 30 days of that store's sales. Same region "
                                 "first; Mylis only to Mylis.", "ایک اسٹور کا فالتو اسٹاک وہاں جہاں آئٹم ختم ہے۔")))

    def _blocked(self):
        st = self.state
        w, p = st.scope.store_sql("b.store")
        rows = st.db.qd(f"""SELECT b.*, i.description, s.name store_name, sup.name supplier_name FROM blocked_item b
                            LEFT JOIN items i USING (item) LEFT JOIN stores s ON s.code=b.store
                            LEFT JOIN suppliers sup ON sup.code=i.supplier
                            WHERE b.import_id IN (SELECT max(import_id) FROM imports WHERE report_type='blocked_007'
                            GROUP BY stores) AND {w} ORDER BY b.value2 DESC NULLS LAST""", p)
        if not rows:
            return self._wrap(empty_state(t("no_data") + " (Blocked stock item report, range 007)"))
        for r in rows:
            r["moved"] = (r["qty1"] or 0) - (r["qty2"] or 0)
        tbl = self.item_table([("store_name", "text"), ("item", "text"), ("description", "text"), ("status", "text"),
                               ("qty1", "num"), ("qty2", "num"), ("value1", "money"), ("value2", "money"),
                               ("supplier_name", "text")], rows, "blocked_007",
                              colorer=lambda r: "warn" if r["moved"] <= 0 and (r["qty2"] or 0) > 0 else "")
        v1 = sum(r["value1"] or 0 for r in rows)
        v2 = sum(r["value2"] or 0 for r in rows)
        return self._wrap(card(tbl, f"{A.fmt_pkr(v1)} → {A.fmt_pkr(v2)}",
                               "Amber = has not moved at all: candidate for return to supplier or write-off."))

    def _leaflet(self):
        st = self.state
        rows = A.leaflet_rows(st.db, st.scope)
        if not rows:
            return self._wrap(empty_state(t("no_data") + " (Leaflet workbook, C&L theme tab)"))
        tbl = self.item_table([("store_name", "text"), ("theme_name", "text"), ("item", "text"),
                               ("description", "text"), ("stock_qty", "num"), ("on_order_qty", "num"),
                               ("status", "text"), ("below_cost", "bool")], rows, "leaflet",
                              colorer=lambda r: "bad" if r["zero"] and not r["on_order"] else ("warn" if r["below_cost"] else ""))
        zero = sum(1 for r in rows if r["zero"])
        nz = sum(1 for r in rows if r["zero"] and not r["on_order"])
        return self._wrap(card(tbl, f"{zero:,} / {len(rows):,} leaflet items at zero stock · {nz:,} not on order",
                               "Red = zero stock and nothing on order. Amber = selling price below cost."))


# ================================================================================================
# Orders
# ================================================================================================
class OrdersPage(Page):
    TABS = ["late", "purge", "all_lpo"]

    def __init__(self, state, parent=None):
        super().__init__(state, parent)
        self._tab = "late"

    def show_tab(self, name):
        self._tab = name
        if hasattr(self, "tabs"):
            self.tabs.setCurrentIndex(self.TABS.index(name) if name in self.TABS else 0)

    def refresh(self):
        lay = self.reset()
        self.header(lay, t("orders_title"), t("orders_sub"))
        rows, snap = A.lpo_rows(self.state.db, self.state.scope)
        if not rows:
            lay.addWidget(empty_state(t("no_data") + " (LPO list)"))
            lay.addStretch(1)
            return
        cols = [("store_name", "text"), ("lpo_no", "text"), ("supplier_name", "text"), ("lpo_date", "date"),
                ("delivery_date", "date"), ("late_days", "int"), ("value", "money"), ("received_value_pct", "pct"),
                ("status", "text"), ("order_type", "text"), ("deleted", "bool")]
        late = sorted([r for r in rows if r["late_days"]], key=lambda r: -(r["value"] or 0))
        self.tabs = QTabWidget()
        a = DataTable(cols, late, export_name="late_orders")
        b = DataTable([("store", "text"), ("lpos", "int"), ("purged", "int"), ("purge_pct", "pct"),
                       ("received_value_pct", "pct"), ("late", "int")], A.purge_by_store(rows), export_name="purge")
        c = DataTable(cols, rows, export_name="all_orders",
                      colorer=lambda r: "bad" if r["late_days"] else ("" if not r["deleted"] else "warn"))
        for w, k in [(a, "late"), (b, "purge"), (c, "all_lpo")]:
            w.setMinimumHeight(420)
            self.tabs.addTab(w, t(f"tab_{k}"))
        self.tabs.setCurrentIndex(self.TABS.index(self._tab))
        lay.addWidget(label(f"{t('as_of')} {snap:%d %b %Y}" if snap else "", "muted"))
        lay.addWidget(self.tabs, 1)


# ================================================================================================
# BC scorecard
# ================================================================================================
class ScorePage(Page):
    def __init__(self, state, parent=None):
        super().__init__(state, parent)
        self._fmt = "H"

    def refresh(self):
        lay = self.reset()
        self.header(lay, t("score_title"), t("score_sub"))
        sc = A.scorecard(self.state.db)
        if not sc:
            lay.addWidget(empty_state(t("no_data") + " (BC workbook, summary tab)"))
            lay.addStretch(1)
            return
        self.sc = sc
        tabs = QHBoxLayout()
        for f, key in [("H", "hyper"), ("S", "super"), ("M", "myli")]:
            bt = QPushButton(t(key))
            bt.setCheckable(True)
            bt.setChecked(f == self._fmt)
            bt.clicked.connect(lambda _=False, f=f: self._set_fmt(f))
            if f == self._fmt:
                bt.setObjectName("primary")
            tabs.addWidget(bt)
        tabs.addStretch(1)
        tabs.addWidget(label(f"{t('as_of')} {sc['as_of']:%d %b %Y} · {sc['file']}", "muted"))
        lay.addLayout(tabs)
        lay.addWidget(self._grid(sc), 1)
        if sc.get("greens_diff"):
            txt = "; ".join(f"{s}: BC {a:g} vs recount {b}" for s, (a, b) in sc["greens_diff"].items())
            lay.addWidget(label("Green count check — " + txt + ". The BC team may count some indicators differently; "
                                "ask them which ones count.", "muted", wrap=True))

    def _set_fmt(self, f):
        self._fmt = f
        self.refresh()

    def _grid(self, sc) -> QWidget:
        cells = [c for c in sc["cells"] if c["format"] == self._fmt]
        stores = sorted({(c["store"], c["store_name"]) for c in cells})
        inds = [k for k in sc["order"] if any(c["indicator"] == k for c in cells)]
        extra = sorted({c["indicator"] for c in cells if c["indicator"] not in inds})
        inds += extra
        by = {(c["indicator"], c["store"]): c for c in cells}
        tw = QTableWidget(len(inds) + 1, len(stores) + 2)
        tw.setHorizontalHeaderLabels([t("target"), ""] + [n for _, n in stores])
        tw.horizontalHeader().setSectionHidden(1, True)
        labels = []
        for i, k in enumerate(inds):
            c0 = next((c for c in cells if c["indicator"] == k), None)
            labels.append(A.IND.get(k, {}).get("label", c0["label"] if c0 else k))
            tgt = c0["target"] if c0 else None
            it = QTableWidgetItem(("" if tgt is None else (("≤" if c0["lower_better"] else "≥") + f"{tgt:g}")))
            it.setForeground(QColor(theme.MUTED))
            tw.setItem(i, 0, it)
            for j, (s, _) in enumerate(stores):
                c = by.get((k, s))
                item = QTableWidgetItem("" if not c or c["value"] is None else f"{c['value']:.1f}")
                item.setTextAlignment(Qt.AlignCenter)
                if c and c["status"]:
                    fg, bg = theme.STATUS[c["status"]]
                    item.setBackground(QColor(bg))
                    item.setForeground(QColor(fg))
                    item.setText(("✓ " if c["status"] == "good" else "✕ ") + item.text())
                tw.setItem(i, j + 2, item)
        labels.append(t("greens") + " (" + t("bc_count") + ")")
        for j, (s, _) in enumerate(stores):
            g = sc["official"].get(s, sc["greens"].get(s, 0))
            item = QTableWidgetItem(f"{g:g} / {sc['measured'].get(s, 0)}")
            item.setTextAlignment(Qt.AlignCenter)
            f = item.font()
            f.setBold(True)
            item.setFont(f)
            tw.setItem(len(inds), j + 2, item)
        tw.setVerticalHeaderLabels(labels)
        tw.setEditTriggers(QTableWidget.NoEditTriggers)
        tw.resizeColumnsToContents()
        tw.setMinimumHeight(min(900, 34 * (len(inds) + 3)))
        tw.cellClicked.connect(lambda r, c: self._cell(inds, stores, by, r, c))
        self._inds = inds
        return card(tw)

    def _cell(self, inds, stores, by, r, c):
        if r >= len(inds) or c < 2:
            return
        k = inds[r]
        s = stores[c - 2][0]
        cell = by.get((k, s))
        if not cell:
            return
        tgt = cell["target"]
        status = {"good": "meets the target", "bad": "misses the target", "": "has no target"}[cell["status"]]
        formula = f"{cell['value']:.2f} vs target {'≤' if cell['lower_better'] else '≥'}{tgt:g} → {status}" \
            if cell["value"] is not None and tgt is not None else f"Printed value: {cell['raw']}"
        if cell.get("ours") is not None:
            formula += f"\nStock Compass recount from the daily zero stock report: {cell['ours']:.2f}%"
        ind = A.IND.get(k, {})
        more = " Stock Compass can list the items behind this indicator on the Stock health page." if ind.get("computed") else \
            " This value comes from the BC team's own sources (surveys or order data not in GIMA exports)."
        ExplainDialog(A.Explain(f"{cell['store_name']} · {cell['label']}",
                                ("Lower is better." if cell["lower_better"] else "Higher is better.") + more,
                                formula, "BC workbook scorecard", f"{cell['period']} · as of {self.sc['as_of']:%d %b %Y}"),
                      self).exec()


# ================================================================================================
# Data checks
# ================================================================================================
class HealthPage(Page):
    def refresh(self):
        lay = self.reset()
        self.header(lay, t("health_title"), t("health_sub"))
        rows = self.state.db.qd("""SELECT f.level, f.message, f.count, i.file_name, i.sheet, i.report_type,
                                   i.snapshot_date, i.imported_at FROM findings f JOIN imports i USING (import_id)
                                   WHERE f.code NOT IN ('date_source','columns')
                                   ORDER BY CASE f.level WHEN 'error' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END,
                                   i.imported_at DESC""")
        if not rows:
            lay.addWidget(empty_state(t("no_data")))
            lay.addStretch(1)
            return
        tbl = DataTable([("level", "text"), ("message", "text"), ("count", "int"), ("report_type", "text"),
                         ("file_name", "text"), ("sheet", "text"), ("snapshot_date", "date")], rows,
                        colorer=lambda r: {"error": "bad", "warn": "warn"}.get(r["level"], ""), export_name="data_checks")
        tbl.view.setWordWrap(True)
        tbl.setMinimumHeight(520)
        lay.addWidget(card(tbl), 1)


# ================================================================================================
# Item overview
# ================================================================================================
class ItemDialog(QDialog):
    def __init__(self, db, item: str, parent=None):
        super().__init__(parent)
        d = A.item_360(db, item)
        it = d["item"]
        self.setWindowTitle(f"{t('item360')} · {item}")
        self.resize(1000, 720)
        lay = QVBoxLayout(self)
        lay.addWidget(label(f"{it.get('description') or item}", "h1"))
        lay.addWidget(label(f"{item} · {it.get('section_name') or ''} · "
                            f"{it.get('supplier_name') or it.get('supplier') or ''} · status {it.get('ast1') or '-'}"
                            + (f" · season {it['season']}" if it.get("season") else ""), "muted"))
        tabs = QTabWidget()
        for key, rows, cols in [
            ("stock_by_store", d["stock"], [("store", "text"), ("qty", "num"), ("cost", "money"), ("price", "money"),
                                             ("status", "text"), ("snap_date", "date")]),
            ("sales_hist", d["sales"], [("store", "text"), ("date_from", "date"), ("date_to", "date"), ("sales", "money"),
                                        ("qty", "num"), ("margin", "money"), ("stock", "num")]),
            ("zero_hist", d["zero"], [("store", "text"), ("snap_date", "date"), ("days_out", "int"), ("dlyavg", "num"),
                                      ("reason", "text"), ("open_lpo", "text"), ("delivery_date", "date")]),
            ("dp_hist", d["dp"], [("store", "text"), ("snap_date", "date"), ("qty", "num"), ("value", "money"),
                                  ("age_days", "int"), ("prov_pct", "pct"), ("provision", "money"), ("bucket", "text")]),
            ("tab_neg", d["negative"], [("store", "text"), ("snap_date", "date"), ("qty", "num"), ("status", "text")]),
            ("tab_leaflet", d["leaflet"], [("store", "text"), ("theme_name", "text"), ("stock_qty", "num"),
                                           ("on_order_qty", "num"), ("status", "text")]),
        ]:
            if rows:
                tabs.addTab(DataTable(cols, rows, export_name=f"item_{item}_{key}"), f"{t(key)} ({len(rows)})")
        if tabs.count() == 0:
            lay.addWidget(empty_state(t("no_data")))
        lay.addWidget(tabs, 1)
        b = QPushButton(t("close"))
        b.clicked.connect(self.accept)
        lay.addWidget(b, 0, Qt.AlignRight)
