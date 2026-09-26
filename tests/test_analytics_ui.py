import os

import pytest

from stockcompass.analytics import core as A
from stockcompass.db import Database
from stockcompass.importer.pipeline import import_files

import synth


@pytest.fixture(scope="module")
def loaded(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("an")
    files = synth.build_all(tmp / "files")
    db = Database(tmp / "t.duckdb")
    import_files(list(files.values()), db)
    yield db
    db.close()


def test_overview(loaded):
    kpis, insights = A.overview(loaded, A.Scope())
    keys = {k.key for k in kpis}
    assert {"zero_stock", "not_on_order", "negative", "dp_stock", "late_lpo", "bc_greens"} <= keys
    zs = next(k for k in kpis if k.key == "zero_stock")
    assert zs.explain and "item-days" in zs.explain.formula
    assert insights


def test_zero_stock_excludes_broken_day(loaded):
    s = A.zero_stock_summary(loaded, A.Scope())
    assert s["suspect_days"] == 1
    manual = loaded.one("SELECT sum(zero_items)/sum(total_items)*100 FROM zs_daily WHERE NOT suspect")
    assert s["mtd_pct"] == pytest.approx(manual)


def test_scope_and_items(loaded):
    rows = A.oos_items(loaded, A.Scope(stores=["504"]))
    assert rows and all(r["store"] == "504" for r in rows)
    assert rows[0]["on_order"] is False          # not on order comes first
    assert all(r["price_ex_tax"] for r in rows)   # priced from RealTime / benchmark
    neg = A.negative_items(loaded, A.Scope())
    assert {r["status"] for r in neg} == {"NI", "NC", "AC"}
    dp = A.dp_items(loaded, A.Scope())
    assert any(r["route"] == "Hold for season" for r in dp) or any(r["route"] for r in dp)
    sc = A.scorecard(loaded)
    assert sc["official"]["504"] == 0 and sc["cells"]


@pytest.mark.skipif(os.environ.get("SKIP_UI") == "1", reason="UI tests disabled")
def test_ui_pages_render(loaded):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
        from stockcompass.ui.main_window import MainWindow
    except ImportError as e:  # pragma: no cover
        pytest.skip(f"Qt not available: {e}")
    app = QApplication.instance() or QApplication([])
    w = MainWindow(loaded)
    for target in ["home", "stock:zero", "stock:oos", "stock:neg", "stock:dp", "stock:blocked", "stock:leaflet",
                   "orders:late", "score", "import", "health", "settings"]:
        w.go(target)
        app.processEvents()
    w.set_where("504")
    w.toggle_lang()
    w.go("home")
    w.toggle_lang()
    w.close()
