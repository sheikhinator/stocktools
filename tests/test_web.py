"""The demo-style screens: data service payloads, import through the screen, export, and the real window."""

import json
import os
import time

import pytest

from stockcompass.db import Database
from stockcompass.web.api import Api, Host, dumps

import synth

PAGES = ["home", "sales", "stock", "orders", "promos", "category", "score", "health", "import", "settings"]
METRICS = ["sales", "zero_stock", "not_on_order", "oos", "lost_sales", "negative", "dp_stock", "late_lpo", "leaflet", "sleeping"]


class TmpHost(Host):
    def __init__(self, folder):
        self.folder = folder

    def save_path(self, name):
        return str(self.folder / name)


@pytest.fixture(scope="module")
def web(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("web")
    files = synth.build_all(tmp / "files")
    for name, fn in [("11b.xlsx", synth.bo_11b_section), ("11f.xlsx", synth.bo_11f_store), ("net.xlsx", synth.bo_net_sales)]:
        fn(tmp / "files" / name)
        files[name] = tmp / "files" / name
    db = Database(tmp / "t.duckdb")
    api = Api(db, TmpHost(tmp))
    yield api, files, tmp
    db.close()


def call(api, method, **p):
    r = json.loads(dumps(api.dispatch(method, p)))    # everything must survive JSON
    assert not (isinstance(r, dict) and r.get("error")), r.get("trace") or r.get("error")
    return r


def wait_import(api):
    for _ in range(600):
        s = call(api, "import_status")
        if not s["busy"]:
            return s
        time.sleep(0.05)
    raise AssertionError("import did not finish")


def test_import_through_screen(web):
    api, files, _ = web
    assert call(api, "boot")["has_data"] is False
    call(api, "import_add", paths=[str(p) for p in files.values()])
    s = wait_import(api)
    assert len(s["plans"]) == len(files) and not s["error"]
    sheets = [sh for p in s["plans"] for sh in p["sheets"]]
    assert all("options" in sh and "chosen" in sh for sh in sheets)
    # a sheet that needs a store without one gets refused until it is chosen
    call(api, "import_run")
    s = wait_import(api)
    if s["plans"]:          # store was missing somewhere: choose it and run again
        for p in s["plans"]:
            for sh in p["sheets"]:
                if sh["needs_store"] and not sh["store"] and sh["chosen"] != "skip":
                    call(api, "import_set", pid=p["pid"], si=sh["si"], store="504")
        call(api, "import_run")
        s = wait_import(api)
    assert not s["plans"] and s["results"] and all(r["ok"] for r in s["results"]), s["results"]
    assert s["done"] >= 1
    boot = call(api, "boot")
    assert boot["has_data"] and boot["stores"] and boot["periods"]


def test_pages_and_tabs(web):
    api = web[0]
    for role, where in [("ho", "all"), ("sm", "504"), ("dm", "reg:Lahore"), ("dh", "504"), ("sec", "504")]:
        ctx = {"role": role, "where": where, "lang": "en"}
        if role == "dh":
            ctx["dept"] = "NF"
        for pg in PAGES:
            r = call(api, "page", ctx=ctx, name=pg)
            assert r.get("title")
    ctx = {"lang": "ur"}
    for tab in ["zero", "oos", "neg", "sleeping", "dp", "move", "blocked", "leaflet"]:
        assert call(api, "page", ctx=ctx, name="stock", tab=tab)["tab"] == tab
    home = call(api, "page", ctx={"role": "sm", "where": "504"}, name="home")
    assert home["jobs"] and all(j["table"]["rows"] for j in home["jobs"])
    k = call(api, "page", ctx={}, name="home")["kpis"]
    assert any(x["tip"] for x in k), "KPI hover breakdowns missing"
    assert all(x.get("explain") for x in k if x["key"] in ("zero_stock", "negative", "dp_stock"))


def test_drill_every_metric(web):
    api = web[0]
    for m in METRICS:
        r = call(api, "drill", ctx={}, metric=m, path=[])
        assert r["by"] and r["cols"][0]["kind"] == "name"
        path = []
        for _ in range(6):          # click the first row until items
            if not r["rows"] or r["by"] == "item":
                break
            row = r["rows"][0]
            path.append({"lvl": r["by"], "k": row["k"], "n": row["name"]})
            r = call(api, "drill", ctx={}, metric=m, path=path)
        if r["rows"] and r["by"] == "item":
            it = call(api, "item", ctx={}, item=r["rows"][0]["k"])
            assert it["item"] and it["rec"]


def test_item_supplier_search_export(web):
    api, _, tmp = web
    item = api.db.one("SELECT item FROM stock_item LIMIT 1")
    d = call(api, "item", ctx={}, item=item)
    assert d["stock"] and d["item"]["item"] == item
    sup = api.db.one("SELECT supplier FROM lpo WHERE supplier IS NOT NULL LIMIT 1")
    s = call(api, "supplier", ctx={}, code=sup)
    assert s["kpis"] and s["name"]
    assert call(api, "search", ctx={}, q=item[:3])["results"]
    r = call(api, "export", ctx={}, name="Zero stock", cols=[{"k": "name", "l": "Store", "kind": "name"},
                                                           {"k": "pct", "l": "Zero %", "kind": "pct"}],
             rows=[{"name": "Fortress", "sub": "Hyper", "pct": 12.5}])
    assert os.path.exists(r["path"])
    r = call(api, "export_jobs", ctx={"role": "sm", "where": "504"})
    assert os.path.getsize(r["path"]) > 0


@pytest.mark.skipif(os.environ.get("SKIP_UI") == "1", reason="UI tests disabled")
def test_real_window(web):
    """The screens inside Qt WebEngine: every page renders with no JavaScript error."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
    try:
        from stockcompass.web import window  # noqa: F401
        from PySide6.QtWidgets import QApplication
    except ImportError as e:  # pragma: no cover
        pytest.skip(f"WebEngine not available: {e}")
    from stockcompass.app import _selftest_web

    app = QApplication.instance() or QApplication([])
    lines = []
    assert _selftest_web(app, web[0].db, lines), lines


def test_analyse_any_measure_by_any_dimension(web):
    api = web[0]
    if not call(api, "boot")["has_data"]:
        test_import_through_screen(web)
    meta = call(api, "explore_meta")
    assert {d["k"] for d in meta["dims"]} >= {"store", "format", "region", "dept", "section", "family", "supplier", "item", "day"}
    ctx = {"role": "ho", "period": "MTD"}
    # every preset runs
    for p in meta["presets"]:
        d = call(api, "explore", ctx=ctx, dim=p["dim"], dim2=p.get("dim2"), measures=p["m"], top=10)
        assert d["dim"] == p["dim"] and "totals" in d
    # additive totals equal the sum of rows plus Others; ratios are recomputed, not averaged
    d = call(api, "explore", ctx=ctx, dim="store", measures=["dp_value", "dp_prov"], top=2)
    assert d["rows"] and d["totals"]["dp_value"] > 0
    rows_sum = sum(r["v"]["dp_value"] for r in d["rows"]) + ((d["others"] or {}).get("v", {}).get("dp_value") or 0)
    assert abs(rows_sum - d["totals"]["dp_value"]) < 1e-6 * max(1, d["totals"]["dp_value"])
    z = call(api, "explore", ctx=ctx, dim="store", measures=["zero_pct"])
    if z["rows"]:
        from stockcompass.analytics import core as A
        from stockcompass.analytics.core import Scope
        assert abs(z["totals"]["zero_pct"] - (A.zero_stock_summary(api.db, Scope()) or {}).get("mtd_pct", z["totals"]["zero_pct"])) < 0.6
    # matrix: row totals and column totals add up to the grand total
    m = call(api, "explore", ctx=ctx, dim="store", dim2="bucket", measures=["dp_value"])
    assert m["cols"] and abs(sum(c["total"] or 0 for c in m["cols"]) - m["totals"]["dp_value"]) < 1
    for r in m["rows"]:
        assert abs(sum(v or 0 for v in r["cells"].values()) - r["v"]["dp_value"]) < 1
    # filters narrow everything; a measure without the asked detail says so instead of guessing
    one = m["rows"][0]["k"]
    f = call(api, "explore", ctx=ctx, dim="bucket", measures=["dp_value"], filters={"store": [one]})
    assert abs(f["totals"]["dp_value"] - m["rows"][0]["v"]["dp_value"]) < 1
    n = call(api, "explore", ctx=ctx, dim="supplier", measures=["zero_pct", "dp_value"])
    assert any("not available by supplier" in x for x in n["notes"]) and n["totals"]["dp_value"]
    # sales by store, department, section
    for dim in ("store", "dept", "section", "format"):
        s = call(api, "explore", ctx=ctx, dim=dim, measures=["sales", "vs_budget", "margin_pct"])
        if s["rows"]:
            assert s["totals"]["sales"] and s["sources"]
    opts = call(api, "explore_options", ctx=ctx, dim="supplier", measure="dp_value")
    assert opts["values"]
    # the agent has the same engine
    from stockcompass.agent.tools import Toolbox
    r = Toolbox(api).call("analyse", {"measures": ["dp_value"], "dim": "store", "dim2": "bucket", "top": 3})
    assert r["rows"] and r["column_totals"] and "Aged (DP) stock" in r["totals"]


def test_delete_many_imports_at_once(web):
    api = web[0]
    if not call(api, "boot")["has_data"]:
        test_import_through_screen(web)
    ids = [r[0] for r in api.db.q("SELECT import_id FROM imports WHERE status='ok' ORDER BY import_id LIMIT 2")]
    assert len(ids) == 2
    r = call(api, "delete_imports", import_ids=ids)
    assert r["deleted"] == 2
    assert not api.db.q(f"SELECT 1 FROM imports WHERE import_id IN ({ids[0]},{ids[1]})")
    assert not api.db.q(f"SELECT 1 FROM raw_row WHERE import_id IN ({ids[0]},{ids[1]})")


def test_cached_screens_follow_every_change(web, tmp_path):
    api = web[0]
    if not call(api, "boot")["has_data"]:
        test_import_through_screen(web)
    ctx = {"role": "ho"}
    a = call(api, "page", ctx=ctx, name="stock", tab="sleeping")
    assert call(api, "page", ctx=ctx, name="stock", tab="sleeping") == a          # second visit comes from the cache
    rev = api.db.rev
    call(api, "save_settings", thresholds={"sleeping_days_cg": 5}) if hasattr(api, "m_save_settings") else api.db.set_setting("sleeping_days_cg", 5)
    assert api.db.rev > rev                                                          # a setting change invalidates
    # deleting a report changes what the screens show
    before = call(api, "page", ctx=ctx, name="home")
    iid = api.db.one("SELECT max(import_id) FROM imports WHERE report_type='dp_master'")
    if iid:
        call(api, "delete_imports", import_ids=[iid])
        after = call(api, "page", ctx=ctx, name="home")
        assert after != before
    # a job ticked on the store view shows as done straight away
    sm = {"role": "sm", "where": "504"}
    home = call(api, "page", ctx=sm, name="home")
    if home.get("jobs"):
        j = home["jobs"][0]
        call(api, "job_done", id=j["id"], done=True)
        assert next(x for x in call(api, "page", ctx=sm, name="home")["jobs"] if x["id"] == j["id"])["done"]
        call(api, "job_done", id=j["id"], done=False)
        assert not next(x for x in call(api, "page", ctx=sm, name="home")["jobs"] if x["id"] == j["id"])["done"]


def test_big_tables_send_the_top_rows_and_export_all(web, tmp_path, monkeypatch):
    from stockcompass.web import api as W
    monkeypatch.setattr(W, "SEND_ROWS", 3)
    rows = [{"item": str(i), "value": float(i), "pct": 10.0} for i in range(10)]
    t = W.table("big_t", [("item", "Item", "text"), ("value", "Value", "pkr"), ("pct", "Rate", "pct")], rows)
    assert len(t["rows"]) == 3 and t["total_rows"] == 10
    assert t["totals"]["value"] == 45 and t["totals"]["pct"] == 10
    api = web[0]
    r = call(api, "export", name="big", title="Big", cols=[{"k": "item", "l": "Item", "kind": "text"}, {"k": "value", "l": "Value", "kind": "pkr"}],
             rows=[], table_id="big_t")
    import openpyxl
    ws = openpyxl.load_workbook(r["path"]).active
    assert ws.max_row >= 10 + 3                                                    # title, blank, header + all 10 rows


def test_presentation_check_opens_everything(web):
    api = web[0]
    if not call(api, "boot")["has_data"]:
        test_import_through_screen(web)
    r = call(api, "readiness", ai=False)
    failed = [c for c in r["checks"] if not c["ok"]]
    assert r["total"] > 40 and not failed, failed


def test_as_of_date_and_guided_setup(web):
    api = web[0]
    if not call(api, "boot")["has_data"]:
        test_import_through_screen(web)
    boot = call(api, "boot")
    assert boot["dates"] and boot["dates"] == sorted(boot["dates"], reverse=True)
    # a date before every import: the screens have nothing to show; the latest date shows everything
    early = call(api, "page", ctx={"role": "ho", "as_of": "2000-01-01"}, name="stock", tab="oos")
    late = call(api, "page", ctx={"role": "ho"}, name="stock", tab="oos")
    assert early != late
    s = call(api, "setup")
    keys = [x["key"] for x in s["steps"]]
    assert keys[:3] == ["stock", "sales_items", "zero_items"] and all(x["status"] for x in s["steps"])
    assert any(x["status"] == "done" for x in s["steps"]) and s["library"] and s["coverage"]["rows"]


def test_order_advisor_suggests_checks_and_transfers(web, tmp_path):
    api = web[0]
    if not call(api, "boot")["has_data"]:
        test_import_through_screen(web)
    meta = call(api, "advisor_meta")
    assert [s["key"] for s in meta["steps"]][:2] == ["stock", "sales_items"] and meta["rules"]["lead_days"] == 7
    r = call(api, "advisor", ctx={"role": "sm"}, store="504")
    assert r["lines"] and all(l["decision"] in ("order", "ist", "ist_order", "none", "stop", "check") and l["reason"] for l in r["lines"])
    for l in r["lines"]:
        if l["decision"] == "order":
            assert l["qty"] > 0 and l["qty"] % (l["pcb"] or 1) == 0          # full cases
    # a pasted order is checked line by line
    txt = "Item\tQty\n" + "\n".join(f"{l['item']}\t{int(l['qty']) + 50}" for l in r["lines"][:5])
    c = call(api, "advisor", ctx={"role": "sm"}, store="504", text=txt)
    assert c["check"] and c["summary"]["proposed_value"] >= 0 and all(l.get("verdict") for l in c["lines"])
    assert "error" in api.dispatch("advisor", {"ctx": {}, "store": "all", "text": "nothing useful"})
    # another Lahore store with plenty of the same items: transfer first, order less
    p = tmp_path / "realtime_500.xlsx"
    synth.realtime(p, store="500")
    api.db.execute("UPDATE stock_item SET qty = 0 WHERE store='504'")
    from stockcompass.importer.pipeline import analyze, commit
    plan = analyze(str(p), api.db)
    for sp in plan.sheets:
        sp.store = "500"
    commit(plan, api.db)
    api.db.execute("UPDATE stock_item SET qty = 500 WHERE store='500'")
    api.db.execute("UPDATE items SET pcb = 1")
    t = call(api, "advisor", ctx={"role": "ho"}, store="504")
    ist = [l for l in t["lines"] if l.get("ist_qty")]
    assert ist and all(l["ist_from"] == "500" for l in ist) and t["summary"]["ist"] == len(ist)
    allst = call(api, "advisor", ctx={"role": "dm"}, store="all")
    assert allst["by_store"]
    saved = call(api, "advisor_rules", rules={"lead_days": 10})
    assert saved["rules"]["lead_days"] == 10
