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
