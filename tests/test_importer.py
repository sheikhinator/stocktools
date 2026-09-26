from datetime import date
from pathlib import Path

import pytest

from stockcompass.db import Database
from stockcompass.importer.pipeline import analyze, commit
from stockcompass.importer.reader import open_file
from stockcompass.importer.stores import StoreResolver
from stockcompass.importer.values import (date_column, dept_code, find_date_range, item_code, parse_num,
                                          percent_column, section_code, barcode)

import synth


# ------------------------------------------------------------------ values
@pytest.mark.parametrize("raw,val,pct", [
    ('456,789', 456789, False), ("(71.0%)", -71.0, True), ("13.%", 13.0, True), ("-17.52%", -17.52, True),
    ("#DIV/0!", None, False), ("(123,456.7%)", -123456.7, True), (" 12,345 ", 12345, False), ("N/A", None, False),
    ("PKR 1,200", 1200, False), (" -   ", None, False),
])
def test_numbers(raw, val, pct):
    n = parse_num(raw)
    assert n.value == val
    if val is not None:
        assert n.percent == pct


def test_percent_fraction_column():
    assert percent_column([0.1447, 0.2]) == pytest.approx([14.47, 20.0])
    assert percent_column(["14%", "9.5%"]) == [14.0, 9.5]
    assert percent_column([85, 12]) == [85.0, 12.0]


def test_dates_per_column():
    ref = date(2026, 9, 25)
    ds, g = date_column([260721, 260710, 260615], ref=ref)
    assert g.fmt == "yymmdd" and ds[0] == date(2026, 7, 21)
    ds, g = date_column(["210926", "110926", "70926"], ref=ref)      # DMMYY with the leading zero dropped
    assert g.fmt == "ddmmyy" and ds[2] == date(2026, 9, 7)
    ds, g = date_column(["9/1/2026 12:00:00 AM", "9/24/2026 12:00:00 AM"], ref=ref)
    assert ds == [date(2026, 9, 1), date(2026, 9, 24)]
    ds, g = date_column(["24/07/26"], ref=ref)
    assert ds == [date(2026, 7, 24)]
    assert find_date_range("(17-09-2026 to 07-10-2026)") == (date(2026, 9, 17), date(2026, 10, 7))


def test_codes():
    assert dept_code("01-FMCG") == "01" and dept_code("CGD") == "01" and dept_code(3.0) == "03"
    assert section_code("S012-DPH") == "012" and section_code(11.0) == "011"
    assert item_code(235385.0) == "235385"
    assert barcode("5.904E+11") == "" and barcode("4006381333931") == "4006381333931"


# ------------------------------------------------------------------ stores
@pytest.mark.parametrize("name,code", [
    ("651 LAH Fortress", "500"), ("660 LAH Askari 10", "P09"), ("660 LAH Emporium Mall", "503"),
    ("661 ISL WTC", "502"), ("661 ISL D12 (P06)", "P06"), ("652 LAH High Street Paragon Ci", "PA6"),
    ("968 LAH H&B PAK LAH DHA Rahbar", "PD2"), ("659 LAH DHA Rahbar", "P07"), ("967 LAH H&B PAK LAH DHA Phase", "PD4"),
    ("HM PK LAH Packages Mall", "504"), ("H&B PK LAH Packages Mall", "P05"), ("FOR", "500"), ("DHA11", "P07"),
    ("DHA 07_MYLI", "PD4"), ("MYLI Phase 7", "PD4"), ("FRT_500", "500"), ("pa6", "PA6"), ("GIMAP09", "P09"),
    ("Lyallpur", "506"),
])
def test_store_resolver(name, code):
    assert StoreResolver().resolve(name).code == code


def test_closed_and_channels_not_guessed():
    r = StoreResolver()
    assert r.resolve("652 KCH Dolmen City Mall").kind == "closed"
    assert r.resolve("605 WP Daraz").kind == "channel"
    assert r.resolve("PA3").code is None


# ------------------------------------------------------------------ end to end
@pytest.fixture()
def env(tmp_path):
    files = synth.build_all(tmp_path / "files")
    db = Database(tmp_path / "t.duckdb")
    yield db, files, tmp_path
    db.close()


def _import(db, path, **overrides):
    plan = analyze(path, db)
    for sp in plan.sheets:
        for k, v in overrides.items():
            setattr(sp, k, v)
    return plan, commit(plan, db)


EXPECTED = {
    "realtime_504.xlsx": "gima_realtime", "benchmark.xlsx": "gima_benchmark", "gima_zero.xlsx": "gima_zero_stock",
    "gima_negative_504.xlsx": "gima_negative_stock", "lpo.xlsx": "lpo_list", "zero_summary.xlsx": "bo_zero_summary",
    "bc.xlsx": "bc_scorecard", "blocked.xlsx": "blocked_007", "leaflet.xlsx": "leaflet_theme",
}


def test_detection(env):
    db, files, _ = env
    for name, key in EXPECTED.items():
        plan = analyze(files[name], db)
        chosen = [sp.chosen for sp in plan.sheets if sp.chosen != "skip"]
        assert key in chosen, (name, [(sp.sheet.name, sp.chosen, sp.confidence) for sp in plan.sheets])


def test_realtime_store_from_filename_and_barcodes(env):
    db, files, _ = env
    plan, outs = _import(db, files["realtime_504.xlsx"])
    assert plan.sheets[0].store == "504"
    o = outs[0]
    assert o.status == "ok" and o.rows == len(synth.ITEMS)
    assert any(f.code == "barcodes_destroyed" for f in o.findings)
    assert db.one("SELECT count(*) FROM stock_item WHERE qty < 0") == 1
    assert db.one("SELECT range_code FROM stock_item WHERE item='230009'") == "007"


def test_zero_sheet_infers_report_date(env):
    db, files, _ = env
    _, outs = _import(db, files["gima_zero.xlsx"])
    assert outs[0].snapshot_date == date(2026, 9, 17)
    assert db.one("SELECT count(*) FROM zero_item WHERE open_lpo IS NULL") == 19


def test_lpo_dates_and_checks(env):
    db, files, _ = env
    _, outs = _import(db, files["lpo.xlsx"])
    o = outs[0]
    codes = {f.code for f in o.findings}
    assert {"unknown_store", "duplicate_orders", "late"} <= codes
    assert db.one("SELECT min(lpo_date) FROM lpo") == date(2026, 9, 1)
    assert db.one("SELECT count(*) FROM lpo WHERE deleted") >= 4


def test_dp_hidden_sheet_and_rule_learning(env):
    db, files, _ = env
    plan, outs = _import(db, files["dp.xlsx"])
    master = [sp for sp in plan.sheets if sp.chosen == "dp_master"][0]
    assert master.sheet.hidden
    assert plan.workbook_date == date(2026, 9, 20)
    o = [o for o in outs if o.report_type == "dp_master"][0]
    assert o.snapshot_date == date(2026, 9, 20)
    assert any(f.code == "other_month_rows" for f in o.findings)
    assert db.one("SELECT count(*) FROM dp_item") == 40
    assert db.one("SELECT count(*) FROM dp_rules WHERE source LIKE 'learned%'") > 0


def test_zero_summary_checks(env):
    db, files, _ = env
    _, outs = _import(db, files["zero_summary.xlsx"])
    codes = {f.code for f in outs[0].findings}
    assert {"bad_snapshot", "range_cut", "zero_jump"} <= codes
    assert db.one("SELECT count(*) FROM zs_daily WHERE suspect") == 1
    assert db.one("SELECT count(DISTINCT store) FROM zs_daily") == 4


def test_scorecard_and_copied_value(env):
    db, files, _ = env
    _, outs = _import(db, files["bc.xlsx"])
    o = outs[0]
    assert o.snapshot_date is not None
    assert db.one("SELECT value FROM bc_value WHERE store='505' AND indicator='zero_stock'") == pytest.approx(13.82)
    assert db.one("SELECT value FROM bc_value WHERE store='500' AND indicator='stock_days'") == 29
    # DHA 07 Myli SSL equals the hypermarket average: flagged
    assert any(f.code == "copied_value" and "PD4" in f.message for f in o.findings)


def test_leaflet_and_blocked(env):
    db, files, _ = env
    _, outs = _import(db, files["leaflet.xlsx"])
    assert outs[0].rows == 10
    assert db.one("SELECT min(date_from) FROM leaflet_item") == date(2026, 9, 17)
    assert any(f.code == "below_cost" for f in outs[0].findings)
    _, outs = _import(db, files["blocked.xlsx"])
    assert db.one("SELECT max(date2) FROM blocked_item").month == 9
    assert db.one("SELECT count(*) FROM blocked_item") == 12


def test_reimport_replaces(env):
    db, files, _ = env
    _import(db, files["gima_negative_504.xlsx"])
    _import(db, files["gima_negative_504.xlsx"], snapshot_date=None)
    assert db.one("SELECT count(*) FROM negative_item") == 15


def test_pivot_cache_and_csv_and_html(env):
    db, files, tmp = env
    p = tmp / "pivot.xlsx"
    synth.gima_negative(p)
    synth.add_pivot_cache(p, ["Store", "Item", "Value"], [["Fortress", "A", 10], ["WTC", "B", 20], ["Fortress", "C", 5]])
    wb = open_file(p)
    piv = [s for s in wb.sheets if s.kind == "pivot"]
    assert piv and piv[0].head[0] == ["Store", "Item", "Value"] and len(piv[0].head) == 4
    csv = tmp / "neg.csv"
    csv.write_text("STR;ITEMPR;PHQTPR;ISTSPR;IDSCPR\n504;123456;-3;NI;X\n500;123457;-1;AC;Y\n", encoding="utf-8")
    plan, outs = _import(db, csv)
    assert outs[0].report_type == "gima_negative_stock" and outs[0].rows == 2
    html = tmp / "neg_html.xls"
    html.write_text("<html><table><tr><td>STR</td><td>ITEMPR</td><td>PHQTPR</td><td>ISTSPR</td></tr>"
                    "<tr><td>504</td><td>123456</td><td>-3</td><td>NC</td></tr></table></html>")
    plan, outs = _import(db, html)
    assert outs[0].report_type == "gima_negative_stock" and outs[0].rows == 1


def test_unknown_table_is_kept(env):
    db, files, tmp = env
    p = tmp / "mystery.csv"
    p.write_text("Store,Thing,Amount\n651 LAH Fortress,a,1\n661 ISL WTC,b,2\n659 LAH DHA Rahbar,c,3\n"
                 "660 LAH Askari 10,d,4\n", encoding="utf-8")
    plan, outs = _import(db, p)
    assert outs[0].report_type == "generic" and outs[0].rows == 4
    assert set(outs[0].stores) == {"500", "502", "P07", "P09"}


def test_sales_reports(env):
    db, files, tmp = env
    p = tmp / "b11.xlsx"
    synth.bo_11b_section(p)
    _, outs = _import(db, p)
    o = outs[0]
    assert o.report_type == "bo_11b" and o.status == "ok"
    # 3 real store rows x 2 periods; channel and grand total skipped
    assert db.one("SELECT count(*) FROM sales_block") == 6
    assert db.one("SELECT sales FROM sales_block WHERE store='500' AND section='011' AND period='DAY'") == 100000
    assert db.one("SELECT round(ly_sales) FROM sales_block WHERE store='500' AND section='011' AND period='DAY'") == 80000
    assert db.one("SELECT budget FROM sales_block WHERE store='500' AND section='011' AND period='MTD'") == 1600000
    assert any(f.code == "skipped_nonstores" for f in o.findings)
    p = tmp / "f11.xlsx"
    synth.bo_11f_store(p)
    _, outs = _import(db, p)
    assert outs[0].report_type == "bo_11f"
    assert db.one("SELECT sum(b2b_cy) FROM sales_fss WHERE period='DAY'") == 350
    assert db.one("SELECT name FROM families WHERE code='355'") == "SHAMPOO"
    assert db.one("SELECT name FROM suppliers WHERE code='45503'") == "SOAP CO"
    assert any(f.code == "lost_lines" for f in outs[0].findings)
    p = tmp / "net.xlsx"
    synth.bo_net_sales(p)
    _, outs = _import(db, p)
    assert outs[0].report_type == "bo_store_net_sales"
    assert db.one("SELECT count(DISTINCT store) FROM sales_block WHERE source='200-10-05'") == 2
    assert db.one("SELECT budget FROM sales_block WHERE source='200-10-05' AND store='P06' AND section='011'") == 400000

    from stockcompass.analytics import sales as SA
    from stockcompass.analytics.core import Scope
    k, ov = SA.kpis(db, Scope(stores=["500"]), "MTD", "budget")
    assert ov["sales"] == 6000000 and round(ov["vs_budget"], 1) == round((6000000 / 6000000 - 1) * 100, 1)
    fam = SA.families(db, Scope(), "YTD")
    assert fam and SA.lost_lines(db, Scope(), "YTD")
