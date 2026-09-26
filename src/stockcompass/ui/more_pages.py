"""Promotions page, category page and the supplier view."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QPushButton, QTabWidget, QVBoxLayout, QWidget

from stockcompass.analytics import extra as X
from stockcompass.analytics import sales as SA
from stockcompass.analytics.core import Kpi, L, fmt_pkr
from stockcompass.i18n import t

from .pages import Page
from .widgets import DataTable, KpiCard, bar_chart, card, empty_state, grid_of, label


class PromosPage(Page):
    def __init__(self, state, parent=None):
        super().__init__(state, parent)
        self._theme = None

    def refresh(self):
        lay = self.reset()
        self.header(lay, L("Promotions", "پروموشنز"),
                    L("Is every leaflet and theme item on the shelf, on order, and priced to make money?",
                      "کیا ہر لیفلیٹ آئٹم شیلف پر، آرڈر میں اور منافع والی قیمت پر ہے؟"))
        th = X.themes(self.state.db)
        if not th:
            lay.addWidget(empty_state(t("no_data") + L(" (Leaflet workbook, C&L theme tab)", " (لیفلیٹ ورک بک)")))
            lay.addStretch(1)
            return
        keys = [x["theme"] for x in th]
        if self._theme not in keys:
            self._theme = keys[0]
        bar = QHBoxLayout()
        cb = QComboBox()
        for x in th:
            dates = f"{x['date_from']:%d %b} – {x['date_to']:%d %b %Y}" if x["date_from"] and x["date_to"] else ""
            cb.addItem(f"{x['theme']} · {x['theme_name']} · {dates}", x["theme"])
        cb.setCurrentIndex(keys.index(self._theme))
        cb.currentIndexChanged.connect(lambda i: (setattr(self, "_theme", cb.itemData(i)), self.refresh()))
        bar.addWidget(label(L("Promotion", "پروموشن"), "muted"))
        bar.addWidget(cb, 1)
        lay.addLayout(bar)
        p = X.promo(self.state.db, self.state.scope, self._theme)
        if not p:
            lay.addWidget(empty_state(L("No items of this promotion in the selected stores.", "منتخب اسٹورز میں آئٹمز نہیں۔")))
            lay.addStretch(1)
            return
        status = L("running", "جاری") if p["running"] else L("ended", "ختم")
        ks = [Kpi("ready", L("Promo items in stock", "اسٹاک میں پروموشن آئٹمز"), p["ready"], "pct",
                  sub=L(f"{p['items']} items × {p['stores']} stores · {status}", f"{p['items']} آئٹمز · {p['stores']} اسٹورز"),
                  status="good" if p["ready"] >= 95 else ("warn" if p["ready"] >= 88 else "bad"), target=95),
              Kpi("pz", L("Zero stock % (promo items)", "زیرو اسٹاک % (پروموشن)"), p["zero_pct"], "pct",
                  sub=L("BC target ≤ 6% (hyper)", "بی سی ہدف ≤ 6%"), status="good" if p["zero_pct"] <= 6 else "bad"),
              Kpi("pno", L("Out of stock, not on order", "آؤٹ آف اسٹاک، آرڈر نہیں"), p["zero_not_ordered"], "int",
                  status="bad" if p["zero_not_ordered"] else "good",
                  chip=L("✕ order these first", "✕ پہلے آرڈر کریں") if p["zero_not_ordered"] else ""),
              Kpi("pbc", L("Priced below cost", "لاگت سے کم قیمت"), p["below_cost"], "int",
                  sub=L("every sale loses money", "ہر سیل پر نقصان"), status="bad" if p["below_cost"] else "good")]
        if p["promo_sales"]:
            ks.append(Kpi("psales", L("Promo sales so far", "پروموشن سیلز"), p["promo_sales"], "pkr",
                          sub=L("from benchmark files inside the promo dates", "بینچ مارک سے")))
        lay.addWidget(grid_of([KpiCard(k) for k in ks], len(ks)))
        bs = p["by_store"]
        lay.addWidget(card(bar_chart([b["store_name"][:18] for b in bs], {L("In stock %", "اسٹاک میں %"): [b["ready"] for b in bs]},
                                     horizontal=True, height=max(160, 32 * len(bs)), suffix="%"),
                           L("Store readiness", "اسٹور کی تیاری"), L("Share of this promotion's items in stock in each store",
                                                                    "ہر اسٹور میں اسٹاک والے آئٹمز کا حصہ")))
        tbl = self.item_table([("store_name", "text"), ("item", "text"), ("description", "text"), ("section_name", "text"),
                               ("stock_qty", "num"), ("on_order_qty", "num"), ("issue", "text"), ("pp", "money"),
                               ("sp", "money")], p["rows"], f"promo_{self._theme}",
                              colorer=lambda r: "bad" if r["issue"] in ("Priced below cost", "Out of stock, not on order")
                              else ("warn" if r["issue"] != "OK" else ""))
        lay.addWidget(card(tbl, L("Promotion items: problems first", "پروموشن آئٹمز: مسائل پہلے"), t("open_item")))
        lay.addStretch(1)


class CategoryPage(Page):
    def refresh(self):
        lay = self.reset()
        st = self.state
        self.header(lay, L("Category view", "کیٹیگری"),
                    L("Every section's role, return on stock, availability and aged stock, side by side.",
                      "ہر سیکشن کا کردار، اسٹاک پر منافع، دستیابی اور ایجڈ اسٹاک۔"))
        pers = [p for p, _ in SA.periods(st.db)]
        if not pers:
            lay.addWidget(empty_state(t("no_data") + " (BO 11b / store net sales)"))
            lay.addStretch(1)
            return
        per = st.period if getattr(st, "period", None) in pers else ("MTD" if "MTD" in pers else pers[0])
        rows = X.category(st.db, st.scope, per)
        if not rows:
            lay.addWidget(empty_state(L("No section-level sales for this selection.", "سیکشن سیلز نہیں۔")))
            lay.addStretch(1)
            return
        tot = sum(r["sales"] for r in rows)
        mv = sum(r["sales"] * (r["margin"] or 0) / 100 for r in rows)
        sv = sum(r["stock_value"] or 0 for r in rows)
        roles = {}
        for r in rows:
            roles[r["role_name"]] = roles.get(r["role_name"], 0) + r["sales"]
        ks = [Kpi("cs", L("Net sales", "نیٹ سیلز"), tot, "pkr", sub=L(*SA.PERIOD_NAMES.get(per, (per, per)))),
              Kpi("cm", L("Front margin", "فرنٹ مارجن"), mv / tot * 100 if tot else None, "pct"),
              Kpi("cg", L("Sections", "سیکشنز"), len(rows), "int",
                  sub=", ".join(f"{k} {v / tot * 100:.0f}%" for k, v in roles.items()) if tot else "")]
        lay.addWidget(grid_of([KpiCard(k) for k in ks], 3))
        tbl = DataTable([("name", "text"), ("role_name", "text"), ("sales", "money"), ("share", "pct"),
                         ("growth", "pct"), ("vs_budget", "pct"), ("margin", "pct"), ("gmroi", "num"),
                         ("zero_pct", "pct"), ("dp_value", "money"), ("tail", "text"), ("stock_value", "money")], rows,
                        export_name="category", colorer=lambda r: "bad" if (r["margin"] or 0) < 0 else "")
        tbl.rowActivated.connect(lambda r: st.window.set_filter(section=r["key"]) or self.navigate.emit("sales"))
        tbl.setMinimumHeight(460)
        lay.addWidget(card(tbl, L("Sections", "سیکشنز"),
                           L("Roles: traffic builder = big share, low margin; profit maker = small share, margin ≥ 15%; "
                             "destination = ≥ 8% of sales; occasional = the rest. GMROI = yearly front margin ÷ stock "
                             "value. Tail = items that make 80% of sales (from benchmark files). Double-click a section "
                             "to open its sales.",
                             "کردار: ٹریفک = بڑا حصہ کم مارجن؛ منافع = چھوٹا حصہ زیادہ مارجن؛ منزل = 8%+ سیلز۔")))
        lay.addStretch(1)


class SupplierDialog(QDialog):
    def __init__(self, state, code: str, parent=None):
        super().__init__(parent)
        st = state
        pers = [p for p, _ in SA.periods(st.db)]
        per = st.period if getattr(st, "period", None) in pers else ("YTD" if "YTD" in pers else (pers[0] if pers else None))
        d = X.supplier(st.db, code, st.scope, per)
        self.setWindowTitle(L("Supplier", "سپلائر") + f" · {d['name']}")
        self.resize(1050, 740)
        lay = QVBoxLayout(self)
        lay.addWidget(label(d["name"], "h1"))
        lay.addWidget(label(f"{L('Supplier code', 'سپلائر کوڈ')} {code} · {st.scope.label(st.db)}", "muted"))
        ks = []
        s = d.get("sales")
        if s:
            ks += [Kpi("ss", L("Sales", "سیلز"), s["sales_cy"], "pkr", sub=L(f"{per} · last year {fmt_pkr(s['sales_ly'])}", per)),
                   Kpi("sg", L("Growth", "اضافہ"), s["growth"], "pct", status="good" if (s["growth"] or 0) >= 0 else "bad",
                       chip=L("▲ up", "▲ اضافہ") if (s["growth"] or 0) >= 0 else L("▼ down", "▼ کمی")),
                   Kpi("sm", L("Front margin", "فرنٹ مارجن"), s["margin"], "pct", status="bad" if (s["margin"] or 0) < 0 else "")]
        if d["received_pct"] is not None:
            ks.append(Kpi("sr", L("Order value received", "موصول آرڈر مالیت"), d["received_pct"], "pct",
                          status="good" if d["received_pct"] >= 70 else "bad", sub=L("SSL target ≥ 70%", "ہدف ≥ 70%")))
        ks.append(Kpi("so", L("Items out of stock", "آؤٹ آف اسٹاک آئٹمز"), len(d["oos"]), "int",
                      sub=L(f"{sum(1 for r in d['oos'] if r['reason_group'] == 'supplier')} because the supplier did not deliver",
                            "سپلائر کی عدم ترسیل"), status="bad" if d["oos"] else ""))
        if d["dp"]:
            ks.append(Kpi("sd", L("Aged (DP) stock", "ایجڈ (DP) اسٹاک"), sum(r["value"] or 0 for r in d["dp"]), "pkr",
                          sub=L(f"{len(d['dp'])} items · return-to-supplier talk", f"{len(d['dp'])} آئٹمز")))
        if ks:
            lay.addWidget(grid_of([KpiCard(k) for k in ks], min(6, len(ks))))
        tabs = QTabWidget()
        if d.get("families"):
            tabs.addTab(DataTable([("name", "text"), ("sales_cy", "money"), ("sales_ly", "money"), ("growth", "pct"),
                                   ("margin", "pct"), ("b2b", "money"), ("promo", "pct")], d["families"],
                                  export_name=f"supplier_{code}_families"), L("Families", "فیملیز"))
        if d["oos"]:
            tabs.addTab(DataTable([("store_name", "text"), ("item", "text"), ("description", "text"), ("reason", "text"),
                                   ("on_order", "bool"), ("days_out", "int"), ("lost_per_day", "money")], d["oos"],
                                  export_name=f"supplier_{code}_oos"), L("Out of stock", "آؤٹ آف اسٹاک"))
        if d["lpo"]:
            tabs.addTab(DataTable([("store_name", "text"), ("lpo_no", "text"), ("lpo_date", "date"), ("delivery_date", "date"),
                                   ("late_days", "int"), ("value", "money"), ("status", "text"), ("deleted", "bool")],
                                  d["lpo"], export_name=f"supplier_{code}_lpo"), L("Orders", "آرڈرز"))
        if d["dp"]:
            tabs.addTab(DataTable([("store_name", "text"), ("item", "text"), ("description", "text"), ("value", "money"),
                                   ("age_days", "int"), ("prov_pct", "pct"), ("route", "text")], d["dp"],
                                  export_name=f"supplier_{code}_dp"), L("Aged (DP) stock", "ایجڈ اسٹاک"))
        if tabs.count() == 0:
            lay.addWidget(empty_state(t("no_data")))
        lay.addWidget(tabs, 1)
        b = QPushButton(t("close"))
        b.clicked.connect(self.accept)
        lay.addWidget(b, 0, Qt.AlignRight)
