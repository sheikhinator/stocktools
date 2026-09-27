"""The local snapshot database (DuckDB, one file on this PC).

Every import is a batch in `imports`. Fact tables carry the import_id and the snapshot date, so the
same report for the same store and date can be re-imported: the newer batch replaces the older one.
Master tables (stores, sections, codes, rules) start from master/seed.py and are editable.
"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

import duckdb

# DuckDB imports these lazily at runtime; importing them here makes sure the Windows build bundles them.
import decimal  # noqa: F401,E402
import uuid  # noqa: F401,E402

from stockcompass.master import seed
from stockcompass.paths import db_path

SCHEMA_VERSION = 1

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS meta (key VARCHAR PRIMARY KEY, value VARCHAR);

CREATE TABLE IF NOT EXISTS stores (
    code VARCHAR PRIMARY KEY, name VARCHAR, short VARCHAR, format VARCHAR, city VARCHAR, region VARCHAR,
    parent VARCHAR, active BOOLEAN DEFAULT TRUE, corp_codes VARCHAR);
CREATE TABLE IF NOT EXISTS store_alias (alias VARCHAR PRIMARY KEY, code VARCHAR, source VARCHAR);
CREATE TABLE IF NOT EXISTS departments (code VARCHAR PRIMARY KEY, short VARCHAR, name VARCHAR, name_ur VARCHAR, head VARCHAR);
CREATE TABLE IF NOT EXISTS sections (code VARCHAR PRIMARY KEY, dept VARCHAR, name VARCHAR, aliases VARCHAR);
CREATE TABLE IF NOT EXISTS families (code VARCHAR, section VARCHAR, name VARCHAR, PRIMARY KEY (code, section));
CREATE TABLE IF NOT EXISTS codes (kind VARCHAR, code VARCHAR, meaning VARCHAR, meaning_ur VARCHAR, confirmed BOOLEAN,
    PRIMARY KEY (kind, code));
CREATE TABLE IF NOT EXISTS settings (key VARCHAR PRIMARY KEY, value VARCHAR);
CREATE TABLE IF NOT EXISTS dp_rules (rule_key VARCHAR, from_day INTEGER, pct DOUBLE, source VARCHAR,
    PRIMARY KEY (rule_key, from_day));
CREATE TABLE IF NOT EXISTS bc_targets (indicator VARCHAR, format VARCHAR, target DOUBLE, lower_better BOOLEAN,
    PRIMARY KEY (indicator, format));
CREATE TABLE IF NOT EXISTS learned (kind VARCHAR, key VARCHAR, value VARCHAR, confirmed_at TIMESTAMP,
    PRIMARY KEY (kind, key));
CREATE TABLE IF NOT EXISTS job_done (key VARCHAR PRIMARY KEY, done_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS items (
    item VARCHAR PRIMARY KEY, description VARCHAR, dept VARCHAR, section VARCHAR, family VARCHAR, subfamily VARCHAR,
    supplier VARCHAR, brand VARCHAR, barcode VARCHAR, pcb DOUBLE, ast1 VARCHAR, ast2 VARCHAR, season VARCHAR,
    updated DATE);
CREATE TABLE IF NOT EXISTS suppliers (code VARCHAR PRIMARY KEY, name VARCHAR);

CREATE SEQUENCE IF NOT EXISTS import_seq START 1;
CREATE TABLE IF NOT EXISTS imports (
    import_id INTEGER PRIMARY KEY, file_name VARCHAR, file_hash VARCHAR, sheet VARCHAR, report_type VARCHAR,
    confidence DOUBLE, snapshot_date DATE, period_from DATE, period_to DATE, stores VARCHAR, rows INTEGER,
    imported_at TIMESTAMP, status VARCHAR, summary VARCHAR);
CREATE TABLE IF NOT EXISTS findings (
    import_id INTEGER, level VARCHAR, code VARCHAR, message VARCHAR, count INTEGER, detail VARCHAR);

-- GIMA RealTime: item master + stock + price, one store per file
CREATE TABLE IF NOT EXISTS stock_item (
    import_id INTEGER, snap_date DATE, store VARCHAR, item VARCHAR, qty DOUBLE, cost DOUBLE, price DOUBLE,
    status VARCHAR, sup_status VARCHAR, ast1 VARCHAR, range_code VARCHAR, supplier VARCHAR,
    date_a DATE, date_b DATE, next_order DATE, flow VARCHAR, promo_price DOUBLE);
-- GIMA Benchmark: item x store sales for a period
CREATE TABLE IF NOT EXISTS sales_item (
    import_id INTEGER, date_from DATE, date_to DATE, store VARCHAR, item VARCHAR, sales DOUBLE, qty DOUBLE,
    margin DOUBLE, stock DOUBLE);
-- GIMA zero stock sheet: every zero-stock item with GIMA's reason and order status
CREATE TABLE IF NOT EXISTS zero_item (
    import_id INTEGER, snap_date DATE, store VARCHAR, item VARCHAR, qty DOUBLE, last_in DATE, last_out DATE,
    days_out INTEGER, dlyavg DOUBLE, order_mode VARCHAR, open_lpo VARCHAR, delivery_date DATE, next_order DATE,
    last_lpo VARCHAR, reason VARCHAR, status VARCHAR, supplier VARCHAR, slow VARCHAR, promo VARCHAR,
    import_sup VARCHAR, total_ordered DOUBLE, total_received DOUBLE, min_qty DOUBLE, facing DOUBLE);
-- GIMA negative stock sheet
CREATE TABLE IF NOT EXISTS negative_item (
    import_id INTEGER, snap_date DATE, store VARCHAR, item VARCHAR, qty DOUBLE, status VARCHAR);
-- DP master (item level)
CREATE TABLE IF NOT EXISTS dp_item (
    import_id INTEGER, snap_date DATE, store VARCHAR, item VARCHAR, qty DOUBLE, cost DOUBLE, price DOUBLE,
    value DOUBLE, age_days INTEGER, provision DOUBLE, prov_pct DOUBLE, bucket VARCHAR, rot DOUBLE,
    high_risk DOUBLE, status VARCHAR, range_code VARCHAR);
-- LPO list (one line per purchase order)
CREATE TABLE IF NOT EXISTS lpo (
    import_id INTEGER, store VARCHAR, lpo_no VARCHAR, lpo_date DATE, delivery_date DATE, dept VARCHAR,
    section VARCHAR, value DOUBLE, grn VARCHAR, grn_value DOUBLE, qty DOUBLE, supplier VARCHAR, lead_days DOUBLE,
    status VARCHAR, order_type VARCHAR, deleted BOOLEAN, created_by VARCHAR, last_user VARCHAR, category VARCHAR);
-- Leaflet / theme items
CREATE TABLE IF NOT EXISTS leaflet_item (
    import_id INTEGER, theme VARCHAR, theme_name VARCHAR, theme_type VARCHAR, date_from DATE, date_to DATE,
    store VARCHAR, item VARCHAR, stock_qty DOUBLE, status VARCHAR, stock_value DOUBLE, on_order_value DOUBLE,
    on_order_qty DOUBLE, pp DOUBLE, sp DOUBLE);
-- Blocked / permanent range 007 stock with two snapshots
CREATE TABLE IF NOT EXISTS blocked_item (
    import_id INTEGER, store VARCHAR, item VARCHAR, status VARCHAR, cost DOUBLE, qty1 DOUBLE, value1 DOUBLE,
    qty2 DOUBLE, value2 DOUBLE, date1 DATE, date2 DATE);
-- BO 500-30-15 zero stock summary, per day (store / department / section level)
CREATE TABLE IF NOT EXISTS zs_daily (
    import_id INTEGER, level VARCHAR, store VARCHAR, dept VARCHAR, section VARCHAR, day DATE,
    total_items DOUBLE, zero_items DOUBLE, printed_pct DOUBLE, suspect BOOLEAN);
-- BC scorecard values as printed in the BC workbook
CREATE TABLE IF NOT EXISTS bc_value (
    import_id INTEGER, period VARCHAR, store VARCHAR, indicator VARCHAR, label VARCHAR, value DOUBLE, raw VARCHAR);
-- Anything recognised but not yet analysed, kept row by row so no data is lost
CREATE TABLE IF NOT EXISTS raw_row (import_id INTEGER, row_no INTEGER, data VARCHAR);
CREATE TABLE IF NOT EXISTS import_notes (import_id INTEGER, file VARCHAR, sheet VARCHAR, hint VARCHAR, what VARCHAR,
    columns VARCHAR, source VARCHAR);
-- Sales by section / department (BO 11b tabs, 200-10-05 store net sales). store NULL = country total.
CREATE TABLE IF NOT EXISTS sales_block (
    import_id INTEGER, source VARCHAR, period VARCHAR, date_from DATE, date_to DATE, level VARCHAR, store VARCHAR,
    dept VARCHAR, section VARCHAR, budget DOUBLE, sales DOUBLE, growth_pct DOUBLE, ly_sales DOUBLE,
    var_budget_pct DOUBLE, margin_pct DOUBLE, waste_pct DOUBLE, customers DOUBLE, penetration DOUBLE, qty DOUBLE,
    avg_basket DOUBLE, asp DOUBLE, stock_value DOUBLE, stock_days DOUBLE, oos_pct DOUBLE, promo_pct DOUBLE);
-- Sales by section x family x supplier (BO 11f), with B2C / B2B and last year. store NULL = country.
CREATE TABLE IF NOT EXISTS sales_fss (
    import_id INTEGER, period VARCHAR, date_to DATE, store VARCHAR, dept VARCHAR, section VARCHAR, family VARCHAR,
    supplier VARCHAR, sales_ly DOUBLE, sales_cy DOUBLE, b2c_ly DOUBLE, b2c_cy DOUBLE, b2b_ly DOUBLE, b2b_cy DOUBLE,
    margin_pct DOUBLE, waste_pct DOUBLE, b2c_margin DOUBLE, b2b_margin DOUBLE, customers DOUBLE, promo_pct DOUBLE,
    purchase DOUBLE, stock_value DOUBLE, stock_days DOUBLE, qty_cy DOUBLE, qty_ly DOUBLE);
-- Family sales year on year (online / offline)
CREATE TABLE IF NOT EXISTS sales_family (
    import_id INTEGER, date_to DATE, store VARCHAR, dept VARCHAR, section VARCHAR, family VARCHAR, sales_ly DOUBLE,
    sales_cy DOUBLE, online_ly DOUBLE, online_cy DOUBLE, offline_ly DOUBLE, offline_cy DOUBLE, margin_ly DOUBLE,
    margin_cy DOUBLE, qty_ly DOUBLE, qty_cy DOUBLE, promo_ly DOUBLE, promo_cy DOUBLE, waste_cy DOUBLE);
"""

FACT_TABLES = ["sales_block", "sales_fss", "sales_family", "stock_item", "sales_item", "zero_item", "negative_item", "dp_item", "lpo", "leaflet_item",
               "blocked_item", "zs_daily", "bc_value", "raw_row", "findings"]


class Database:
    def __init__(self, path: str | Path | None = None, read_only: bool = False):
        self.path = str(path or db_path())
        self.con = duckdb.connect(self.path, read_only=read_only)
        self.lock = threading.RLock()
        if not read_only:
            self.con.execute(SCHEMA)
            self.con.execute("ALTER TABLE imports ADD COLUMN IF NOT EXISTS variant VARCHAR")
            self._seed()

    # ------------------------------------------------------------------ basics
    def q(self, sql: str, params: Sequence[Any] | None = None) -> list[tuple]:
        with self.lock:
            return self.con.execute(sql, params or []).fetchall()

    def qd(self, sql: str, params: Sequence[Any] | None = None) -> list[dict]:
        with self.lock:
            cur = self.con.execute(sql, params or [])
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def one(self, sql: str, params: Sequence[Any] | None = None, default=None):
        r = self.q(sql, params)
        return r[0][0] if r and r[0] and r[0][0] is not None else default

    rev = 0      # bumped by every change that can alter an analysis; cached results are keyed on it

    def execute(self, sql: str, params: Sequence[Any] | None = None):
        with self.lock:
            self.con.execute(sql, params or [])
        head = sql[:80].lower()
        if not any(t in head for t in ("agent_", "job_done", "import_notes")):
            self.rev += 1

    def close(self):
        with self.lock:
            self.con.close()

    def insert_rows(self, table: str, rows: list[dict]):
        """Fast bulk insert: rows go through a temporary CSV file that DuckDB loads in one go
        (no heavy dependencies; 300k rows load in seconds). Missing keys become NULL."""
        if not rows:
            return
        import csv
        import os
        import tempfile

        desc = self.q(f"DESCRIBE {table}")
        cols = [c[0] for c in desc]
        types = {c[0]: c[1] for c in desc}
        fd, path = tempfile.mkstemp(suffix=".csv", prefix="sc_", dir=str(Path(self.path).parent)
                                    if self.path != ":memory:" else None)
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(cols)
                for r in rows:
                    out = []
                    for c in cols:
                        v = r.get(c)
                        t = types[c]
                        if v is None:
                            out.append("\\N")
                        elif t == "DATE":
                            out.append((v.date() if isinstance(v, datetime) else v).isoformat() if isinstance(v, date) else "\\N")
                        elif t in ("DOUBLE", "FLOAT", "INTEGER", "BIGINT"):
                            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
                                out.append("\\N")
                            else:
                                out.append(repr(int(v)) if t in ("INTEGER", "BIGINT") else repr(float(v)))
                        elif t == "BOOLEAN":
                            out.append("true" if v else "false")
                        elif t == "TIMESTAMP":
                            out.append(v.isoformat(sep=" ") if isinstance(v, datetime) else "\\N")
                        else:
                            out.append(str(v))
                    w.writerow(out)
            spec = ", ".join(f"'{c}': '{types[c]}'" for c in cols)
            with self.lock:
                self.con.execute(f"INSERT INTO {table} SELECT {', '.join(cols)} FROM read_csv(?, header=true, "
                                 f"columns={{{spec}}}, nullstr='\\N', quote='\"', escape='\"', "
                                 f"auto_detect=false, delim=',')", [path])
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    # ------------------------------------------------------------------ seed
    def _seed(self):
        if self.one("SELECT value FROM meta WHERE key='seeded'"):
            return
        with self.lock:
            self.con.execute("BEGIN")
            try:
                for s in seed.STORES:
                    self.con.execute("INSERT OR REPLACE INTO stores VALUES (?,?,?,?,?,?,?,?,?)",
                                     [s["code"], s["name"], s.get("short"), s["format"], s.get("city"),
                                      s.get("region"), s.get("parent"), True, ",".join(s.get("corp", []))])
                for d in seed.DEPARTMENTS:
                    self.con.execute("INSERT OR REPLACE INTO departments VALUES (?,?,?,?,?)",
                                     [d["code"], d["short"], d["name"], d["name_ur"], d["head"]])
                for code, dept, name, al in seed.SECTIONS:
                    self.con.execute("INSERT OR REPLACE INTO sections VALUES (?,?,?,?)", [code, dept, name, "|".join(al)])
                for kind, table in [("item_status", seed.ITEM_STATUS), ("order_type", seed.ORDER_TYPES),
                                    ("lpo_status", seed.LPO_STATUS), ("range", seed.RANGE_CODES)]:
                    for code, (m, mu, conf) in table.items():
                        self.con.execute("INSERT OR REPLACE INTO codes VALUES (?,?,?,?,?)", [kind, code, m, mu, conf])
                for k, v in seed.SETTINGS_DEFAULTS.items():
                    self.con.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", [k, json.dumps(v)])
                for key, steps in seed.DP_RULES.items():
                    for fd, pct in steps:
                        self.con.execute("INSERT OR REPLACE INTO dp_rules VALUES (?,?,?,?)", [key, fd, pct, "built-in (inferred)"])
                for ind in seed.BC_INDICATORS:
                    for f, t in ind["t"].items():
                        self.con.execute("INSERT OR REPLACE INTO bc_targets VALUES (?,?,?,?)", [ind["key"], f, t, ind["lo"]])
                self.con.execute("INSERT OR REPLACE INTO meta VALUES ('seeded', ?)", [datetime.now().isoformat()])
                self.con.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", [str(SCHEMA_VERSION)])
                self.con.execute("COMMIT")
            except Exception:
                self.con.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------------ settings & learning
    def setting(self, key: str, default=None):
        v = self.one("SELECT value FROM settings WHERE key=?", [key])
        if v is None:
            return seed.SETTINGS_DEFAULTS.get(key, default)
        try:
            return json.loads(v)
        except (TypeError, ValueError):
            return v

    def set_setting(self, key: str, value):
        with self.lock:
            self.con.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", [key, json.dumps(value)])
        if key not in ("agent", "view", "language", "urdu_font"):     # UI / agent preferences do not change analyses
            self.rev += 1

    def learned(self, kind: str) -> dict[str, str]:
        return {k: v for k, v in self.q("SELECT key, value FROM learned WHERE kind=?", [kind])}

    def learn(self, kind: str, key: str, value: str):
        self.execute("INSERT OR REPLACE INTO learned VALUES (?,?,?,?)", [kind, key.upper().strip(), value, datetime.now()])

    def store_list(self, active_only: bool = True) -> list[dict]:
        rows = self.qd("SELECT * FROM stores" + (" WHERE active" if active_only else "") + " ORDER BY format, code")
        aliases = {}
        for a, c in self.q("SELECT alias, code FROM store_alias"):
            aliases.setdefault(c, []).append(a)
        seeded = {s["code"]: s for s in seed.STORES}
        for r in rows:
            r["aliases"] = list(seeded.get(r["code"], {}).get("aliases", [])) + aliases.get(r["code"], [])
        return rows

    def resolver(self):
        from stockcompass.importer.stores import StoreResolver

        learned = dict(self.learned("store"))
        learned.update({a: c for a, c in self.q("SELECT alias, code FROM store_alias")})
        return StoreResolver(stores=self.store_list(active_only=False), learned=learned)

    # ------------------------------------------------------------------ imports
    def new_import(self, **kw) -> int:
        iid = self.one("SELECT nextval('import_seq')")
        self.execute(
            "INSERT INTO imports (import_id, file_name, file_hash, sheet, report_type, confidence, snapshot_date, "
            "period_from, period_to, stores, \"rows\", imported_at, status, summary) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [iid, kw.get("file_name"), kw.get("file_hash"), kw.get("sheet"), kw.get("report_type"), kw.get("confidence"),
             kw.get("snapshot_date"), kw.get("period_from"), kw.get("period_to"), kw.get("stores"), kw.get("rows", 0),
             datetime.now(), kw.get("status", "loading"), kw.get("summary")])
        return iid

    def stamp(self) -> tuple:
        """Changes whenever imported data or settings change (cached analyses are keyed on it)."""
        try:
            with self.lock:
                n, mx = self.con.execute("SELECT count(*), coalesce(max(import_id), 0) FROM imports").fetchone()
        except Exception:
            n = mx = 0
        return (self.rev, n, mx)

    def finish_import(self, iid: int, rows: int, status: str, summary: str = ""):
        self.execute("UPDATE imports SET rows=?, status=?, summary=? WHERE import_id=?", [rows, status, summary, iid])

    def delete_import(self, iid: int):
        with self.lock:
            for t in FACT_TABLES:
                self.con.execute(f"DELETE FROM {t} WHERE import_id=?", [iid])
            self.con.execute("DELETE FROM imports WHERE import_id=?", [iid])
        self.rev += 1

    def delete_imports(self, ids: list[int]) -> int:
        """Delete many imports in one transaction (one statement per table instead of one per import)."""
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        marks = ",".join("?" * len(ids))
        with self.lock:
            self.con.execute("BEGIN")
            try:
                for t in list(FACT_TABLES) + ["import_notes", "findings"]:
                    try:
                        self.con.execute(f"DELETE FROM {t} WHERE import_id IN ({marks})", ids)
                    except Exception:
                        if t in FACT_TABLES:
                            raise
                self.con.execute(f"DELETE FROM imports WHERE import_id IN ({marks})", ids)
                self.con.execute("COMMIT")
            except Exception:
                self.con.execute("ROLLBACK")
                raise
        self.rev += 1
        return len(ids)

    def supersede(self, iid: int, report_type: str, stores: Iterable[str], snapshot_date: date | None,
                  period_from: date | None = None, period_to: date | None = None, variant: str = "") -> list[int]:
        """Remove older imports of the same report, store scope, date and tab variant (a re-import replaces them)."""
        key = ",".join(sorted(set(stores)))
        self.execute("UPDATE imports SET variant=? WHERE import_id=?", [variant or "", iid])
        old = [r[0] for r in self.q(
            "SELECT import_id FROM imports WHERE report_type=? AND coalesce(stores,'')=? "
            "AND coalesce(snapshot_date, DATE '1900-01-01')=coalesce(?, DATE '1900-01-01') "
            "AND coalesce(period_from, DATE '1900-01-01')=coalesce(?, DATE '1900-01-01') "
            "AND coalesce(period_to, DATE '1900-01-01')=coalesce(?, DATE '1900-01-01') "
            "AND coalesce(variant,'')=? AND import_id<>?",
            [report_type, key, snapshot_date, period_from, period_to, variant or "", iid])]
        for o in old:
            self.delete_import(o)
        return old

    def already_imported(self, file_hash: str, sheet: str) -> int | None:
        return self.one("SELECT import_id FROM imports WHERE file_hash=? AND sheet=? AND status='ok'", [file_hash, sheet])

    # ------------------------------------------------------------------ master upserts from reports
    def upsert_items(self, items: dict[str, dict], as_of: date | None):
        if not items:
            return
        rows = []
        for code, it in items.items():
            rows.append(dict(item=code, description=it.get("description"), dept=it.get("dept"), section=it.get("section"),
                             family=it.get("family"), subfamily=it.get("subfamily"), supplier=it.get("supplier"),
                             brand=it.get("brand"), barcode=it.get("barcode"), pcb=it.get("pcb"), ast1=it.get("ast1"),
                             ast2=it.get("ast2"), season=it.get("season"), updated=as_of or date.today()))
        with self.lock:
            self.con.execute("CREATE TEMP TABLE IF NOT EXISTS _items AS SELECT * FROM items WHERE false")
            self.con.execute("DELETE FROM _items")
        self.insert_rows("_items", rows)
        with self.lock:
            # keep existing non-null values where the new report doesn't carry them
            self.con.execute("""
                INSERT OR REPLACE INTO items
                SELECT n.item,
                       coalesce(nullif(n.description,''), o.description), coalesce(nullif(n.dept,''), o.dept),
                       coalesce(nullif(n.section,''), o.section), coalesce(nullif(n.family,''), o.family),
                       coalesce(nullif(n.subfamily,''), o.subfamily), coalesce(nullif(n.supplier,''), o.supplier),
                       coalesce(nullif(n.brand,''), o.brand), coalesce(nullif(n.barcode,''), o.barcode),
                       coalesce(n.pcb, o.pcb), coalesce(nullif(n.ast1,''), o.ast1), coalesce(nullif(n.ast2,''), o.ast2),
                       coalesce(nullif(n.season,''), o.season), n.updated
                FROM (SELECT DISTINCT ON (item) * FROM _items) n LEFT JOIN items o USING (item)""")

    def upsert_suppliers(self, sups: dict[str, str]):
        sups = {k: v for k, v in sups.items() if k and v}
        if not sups:
            return
        with self.lock:
            for k, v in sups.items():
                self.con.execute("INSERT OR REPLACE INTO suppliers VALUES (?,?)", [k, v])
