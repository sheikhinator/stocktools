"""Settings: language, Urdu font, thresholds, stores and their alternative names, BC targets, DP rules, codes."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QInputDialog, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from stockcompass.i18n import t

from .pages import Page
from .widgets import DataTable, card, label


class SettingsPage(Page):
    changed = Signal()

    def refresh(self):
        lay = self.reset()
        lay.addWidget(label(t("settings_title"), "h1"))
        tabs = QTabWidget()
        tabs.addTab(self._general(), t("thresholds"))
        tabs.addTab(self._stores(), t("stores"))
        tabs.addTab(self._targets(), t("targets"))
        tabs.addTab(self._rules(), t("dp_rules"))
        tabs.addTab(self._codes(), t("codes"))
        lay.addWidget(tabs, 1)

    # ------------------------------------------------------------------ general
    def _general(self):
        db = self.state.db
        w = QWidget()
        f = QFormLayout(w)
        lang = QComboBox()
        lang.addItem("English", "en")
        lang.addItem("اردو", "ur")
        lang.setCurrentIndex(1 if db.setting("language") == "ur" else 0)
        font = QComboBox()
        for n in ("Noto Nastaliq Urdu", "Noto Naskh Arabic"):
            font.addItem(n, n)
        font.setCurrentIndex(0 if db.setting("urdu_font") != "Noto Naskh Arabic" else 1)
        spins = {}
        for key, lab, lo, hi in [("sleeping_days_cg", "Sleeping stock, CG (days without a sale)", 1, 365),
                                 ("sleeping_days_nonfood", "Sleeping stock, non-food (days)", 1, 730),
                                 ("low_stock_pcs", "Low stock: fewer than (pcs)", 1, 100),
                                 ("dp_warning_days", "Early warning before a DP step (days)", 1, 180),
                                 ("min_items_for_pct", "Hide % when fewer items than", 0, 1000),
                                 ("bad_snapshot_drop_pct", "Broken day: items drop by more than (%)", 1, 90)]:
            s = QSpinBox()
            s.setRange(lo, hi)
            s.setValue(int(db.setting(key) or 0))
            spins[key] = s
            f.addRow(lab, s)
        f.insertRow(0, t("language"), lang)
        f.insertRow(1, t("urdu_font"), font)
        save = QPushButton(t("save"))
        save.setObjectName("primary")

        def do_save():
            db.set_setting("language", lang.currentData())
            db.set_setting("urdu_font", font.currentData())
            for k, s in spins.items():
                db.set_setting(k, s.value())
            self.changed.emit()

        save.clicked.connect(do_save)
        f.addRow("", save)
        return card(w)

    # ------------------------------------------------------------------ stores
    def _stores(self):
        db = self.state.db
        rows = db.store_list(active_only=False)
        for r in rows:
            r["aliases_txt"] = ", ".join(r["aliases"])
        tbl = DataTable([("code", "text"), ("name", "text"), ("format", "text"), ("city", "text"),
                         ("parent", "text"), ("corp_codes", "text"), ("aliases_txt", "text")], rows,
                        export_name="stores")
        tbl.setMinimumHeight(420)
        add = QPushButton(t("add_alias"))

        def add_alias():
            idx = tbl.view.selectionModel().selectedRows()
            if not idx:
                return
            r = tbl.model.row(tbl.proxy.mapToSource(idx[0]).row())
            name, ok = QInputDialog.getText(self, t("add_alias"), f"{r['code']} {r['name']}:")
            if ok and name.strip():
                db.execute("INSERT OR REPLACE INTO store_alias VALUES (?,?,?)", [name.strip().upper(), r["code"], "user"])
                self.refresh()

        add.clicked.connect(add_alias)
        unknown = db.qd("""SELECT f.detail FROM findings f WHERE f.code='unknown_store' AND f.detail IS NOT NULL""")
        names = sorted({n for u in unknown for n in (u["detail"] or "").split("|") if n})
        w = QWidget()
        l = QVBoxLayout(w)
        l.addWidget(card(tbl, t("stores"), "GIMA code is the identity. Other names and corporate codes are only used "
                                          "to recognise the store in reports.", tools=[add]))
        if names:
            l.addWidget(label("Names seen in reports but not recognised yet: " + ", ".join(names[:30])
                              + ". Select the store above and add the name.", "muted", wrap=True))
        return w

    # ------------------------------------------------------------------ targets
    def _targets(self):
        db = self.state.db
        from stockcompass.master.seed import BC_INDICATORS
        inds = BC_INDICATORS
        tw = QTableWidget(len(inds), 4)
        tw.setHorizontalHeaderLabels(["Indicator", "Hypermarket", "Supermarket", "Myli"])
        cur = {(k, f): v for k, f, v in db.q("SELECT indicator, format, target FROM bc_targets")}
        for i, ind in enumerate(inds):
            it = QTableWidgetItem(("↓ " if ind["lo"] else "↑ ") + ind["label"])
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            tw.setItem(i, 0, it)
            for j, f in enumerate("HSM", 1):
                v = cur.get((ind["key"], f))
                tw.setItem(i, j, QTableWidgetItem("" if v is None else f"{v:g}"))
        tw.resizeColumnsToContents()
        save = QPushButton(t("save"))
        save.setObjectName("primary")

        def do_save():
            for i, ind in enumerate(inds):
                for j, f in enumerate("HSM", 1):
                    txt = (tw.item(i, j).text() if tw.item(i, j) else "").strip()
                    try:
                        v = float(txt) if txt else None
                    except ValueError:
                        continue
                    db.execute("INSERT OR REPLACE INTO bc_targets VALUES (?,?,?,?)", [ind["key"], f, v, ind["lo"]])
            self.changed.emit()

        save.clicked.connect(do_save)
        return card(tw, t("targets"), "↓ lower is better · ↑ higher is better. Targets are also updated automatically "
                                      "from each BC scorecard you import.", tools=[save])

    # ------------------------------------------------------------------ DP rules
    def _rules(self):
        rows = self.state.db.qd("""SELECT r.rule_key, r.from_day, r.pct, r.source, d.name dept_name, s.name sec_name
                                  FROM dp_rules r LEFT JOIN departments d ON d.code = split_part(r.rule_key, ':', 1)
                                  LEFT JOIN sections s ON s.code = nullif(split_part(r.rule_key, ':', 2), '')
                                  ORDER BY r.rule_key, r.from_day""")
        for r in rows:
            r["applies_to"] = (r["dept_name"] or r["rule_key"]) + (f" / {r['sec_name']}" if r["sec_name"] else "")
        tbl = DataTable([("applies_to", "text"), ("from_day", "int"), ("pct", "num"), ("source", "text")], rows,
                        export_name="dp_rules")
        tbl.setMinimumHeight(420)
        return card(tbl, t("dp_rules"), "From this age (days) the provision % applies. Learned from every DP master "
                                        "file you import; a section rule overrides its department rule.")

    def _codes(self):
        rows = self.state.db.qd("SELECT kind, code, meaning, meaning_ur, confirmed FROM codes ORDER BY kind, code")
        tbl = DataTable([("kind", "text"), ("code", "text"), ("meaning", "text"), ("meaning_ur", "text"),
                         ("confirmed", "bool")], rows, export_name="codes")
        tbl.setMinimumHeight(420)
        return card(tbl, t("codes"))
