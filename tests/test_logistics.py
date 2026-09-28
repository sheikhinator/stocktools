"""Other data (any table understood column by column) and the map & logistics tools, all offline."""

import json

import pytest

from stockcompass.db import Database
from stockcompass.importer.pipeline import analyze, commit
from stockcompass.logistics import geo, net
from stockcompass.web.api import Api

net.OFFLINE = True


def call(api, m, **kw):
    r = api.dispatch(m, {"ctx": kw.pop("ctx", {}), **kw})
    assert not (isinstance(r, dict) and r.get("error") and "trace" in r), r.get("trace")
    return r


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKCOMPASS_HOME", str(tmp_path / "home"))
    return Api(Database(tmp_path / "t.duckdb"))


def imp(db, name, text):
    return commit(analyze(name, db, text=text), db)


WASTE = """Store waste report
Store\tItem Code\tItem Description\tSupplier\tWaste Qty\tWaste Value\tWaste %\tDate
Fortress\t178986\tPepsi 1.5L\t10234 - Pepsi Co\t12\t2,400\t1.2%\t12/09/2026
EMP\t178987\tCoke 1L\t10235 - Coca Cola\t3\t600\t0.5%\t13/09/2026
Packages Mall\t178986\tPepsi 1.5L\t10234 - Pepsi Co\t5\t1,000\t0.9%\t13/09/2026
Unknownville\t178988\tSprite\t10235 - Coca Cola\t1\t150\t0.1%\t13/09/2026
"""


def test_geo_offline():
    assert geo.parse_coords("https://www.google.com/maps/place/X/@31.4712,74.3553,17z") == (31.4712, 74.3553)
    assert geo.parse_coords("74.3553, 31.4712") == (31.4712, 74.3553)          # written the other way round
    assert geo.parse_coords("https://maps.google.com/?q=24.86,67.00") == (24.86, 67.0)
    assert geo.city_of("Plot 5, Sundar Industrial Estate, Lahore") == "Lahore"
    assert geo.city_of("RYK") == "Rahim Yar Khan"
    a, b = geo.CITIES["Lahore"][:2], geo.CITIES["Islamabad"][:2]
    assert 350 < geo.haversine(a, b) * geo.road_factor(a, b) < 400                # calibrated on the motorway distance


def test_any_table_becomes_a_dataset(api):
    db = api.db
    out = imp(db, "waste.txt", WASTE)
    assert out[0].status == "ok" and "by store, item code, supplier, date" in out[0].summary
    assert out[0].snapshot_date.isoformat() == "2026-09-13"                     # latest date in the rows
    ds = db.qd("SELECT * FROM datasets")[0]
    assert ds["name"] == "Store waste report"                                  # the title above the table
    roles = {c["name"]: (c["role"], c.get("kind")) for c in json.loads(ds["columns"])}
    assert roles["Waste Qty"] == ("measure", "quantity") and roles["Waste Value"] == ("measure", "money")
    assert roles["Waste %"] == ("measure", "percent") and roles["Store"][0] == "store" and roles["Item Code"][0] == "item"
    rows = db.qd("SELECT store, item, supplier, d FROM raw_row ORDER BY row_no")
    assert [r["store"] for r in rows] == ["500", "503", "504", None]
    assert rows[0]["item"] == "178986" and rows[0]["supplier"] == "10234"
    assert db.one("SELECT name FROM suppliers WHERE code='10234'") == "Pepsi Co"        # masters learned
    assert db.one("SELECT description FROM items WHERE item='178987'") == "Coke 1L"
    assert any(f["code"] == "unknown_store" for f in db.qd("SELECT code FROM findings"))
    # the same columns again, same date: replaces; the dataset stays one
    imp(db, "waste (2).txt", WASTE)
    assert db.one("SELECT count(*) FROM datasets") == 1 and db.one("SELECT count(*) FROM raw_row") == 4


def test_stores_as_columns_and_supplier_addresses(api):
    db = api.db
    out = imp(db, "stock by store.txt", "Item\tDescription\tFRT\tEMP\tPKG\tLucky One\tTotal\n178986\tPepsi\t10\t20\t30\t5\t65\n178987\tCoke\t1\t2\t3\t4\t10\n")
    assert set(out[0].stores) == {"500", "503", "504", "505"}
    got = db.q("SELECT store, json_extract_string(data, '$.Stock') FROM raw_row WHERE item='178986' ORDER BY store")
    assert got == [("500", "10.0"), ("503", "20.0"), ("504", "30.0"), ("505", "5.0")]
    imp(db, "vendor master.txt", "Vendor Code\tVendor Name\tAddress\tCity\n10234\tPepsi Co\tSundar Estate\tLahore\n10235\tCoca Cola\tKorangi\tKarachi\n")
    pl = {r["code"]: r for r in db.qd("SELECT * FROM places WHERE kind='supplier'")}
    assert pl["10234"]["city"] == "Lahore" and not pl["10234"]["confirmed"]       # city only: approximate


def test_other_data_screens_and_analyse(api):
    db = api.db
    imp(db, "waste.txt", WASTE)
    lst = call(api, "data_list")["datasets"]
    assert lst[0]["name"] == "Store waste report" and lst[0]["keys"] == ["store", "item", "supplier", "date"]
    key = lst[0]["key"]
    v = call(api, "data_view", key=key)
    assert v["totals"]["Waste Qty"] == 21 and v["by"] == "store" and v["detail"]["total"] == 4
    assert call(api, "data_view", key=key, ctx={"where": "500"})["totals"]["Waste Value"] == 2400
    v = call(api, "data_view", key=key, by="item")
    assert {r["k"] for r in v["rows"]} == {"178986", "178987", "178988"}
    meta = call(api, "explore_meta")
    ms = [m["k"] for g in meta["groups"] for m in g["m"] if m["k"].startswith("ds:")]
    assert len(ms) == 3
    c = call(api, "explore", dim="store", measures=ms[:2])
    assert c["rows"][0]["k"] == "500" and c["rows"][0]["v"][ms[1]] == 2400
    assert call(api, "item", item="178986")["other"][0]["total"] == 2
    # correct a column once: applied to the saved rows too
    call(api, "data_column", key=key, name="Supplier", role="label")
    assert db.one("SELECT count(*) FROM raw_row WHERE supplier IS NOT NULL") == 0
    call(api, "data_rename", key=key, name="Waste")
    imp(db, "waste.txt", WASTE.replace("12/09", "20/09"))
    assert call(api, "data_list")["datasets"][0]["name"] == "Waste"                # the user's name is kept


def test_map_trip_places_and_transfers(api):
    db = api.db
    b = call(api, "map_boot")
    st = {p["code"]: p for p in b["places"] if p["kind"] == "store"}
    assert {"500", "504", "505"} <= set(st) and b["settings"]["vehicles"] and b["cities"]["Lahore"]
    t = call(api, "map_trip", start=st["500"], stops=[st["505"], st["504"]], optimise=True, cartons=500, value=1_000_000)
    assert t["order"] == [1, 0]                                                   # Packages first, then Karachi
    assert 2000 < t["km"] < 2800 and t["litres"] > 0 and t["total"] > t["fuel_pkr"] and t["vehicle"] == "mazda"
    assert t["source"] == "estimate" and len(t["legs"]) == 3
    r = call(api, "map_place", kind="supplier", code="10234", name="Pepsi Co", address="https://www.google.com/maps/@31.40,74.21,15z")
    assert r["place"]["lat"] == 31.40 and any(p["code"] == "10234" for p in r["places"])
    call(api, "map_place", kind="store", code="504", lat=31.4713, lng=74.3551)
    assert next(p for p in call(api, "map_boot")["places"] if p["code"] == "504")["exact"]
    assert call(api, "map_locate", text="Korangi, Karachi")["how"].startswith("city centre")
    assert "error" in api.dispatch("map_trip", {"ctx": {}, "start": st["500"], "stops": []})
    # transfers: runs per sending store and city, vehicle by load, cost vs value
    from stockcompass.logistics import plan as PL
    adv = {"as_of": "2026-09-28", "lines": [
        dict(store="504", item="1", ist_from="500", ist_qty=240, pcb=12, cost=100, lost_risk=500, reason="x"),
        dict(store="503", item="1", ist_from="500", ist_qty=120, pcb=12, cost=100, lost_risk=0, reason="x"),
        dict(store="505", item="2", ist_from="500", ist_qty=24, pcb=12, cost=50, lost_risk=0, reason="aged stock")]}
    p = PL.transfers(db, advice=adv)
    runs = {r["id"]: r for r in p["runs"]}
    assert set(runs) == {"500:Lahore", "500:Karachi"}
    lah = runs["500:Lahore"]
    assert len(lah["stops"]) == 2 and lah["cartons"] == 30 and lah["vehicle"] == "pickup" and lah["value"] == 36000
    assert not runs["500:Karachi"]["worth"]                                      # 2 cartons to Karachi cost more than they are worth
    p2 = PL.transfers(db, advice=adv, exclude=["500:Karachi"], vehicles={"500:Lahore": "mazda"})
    assert len(p2["runs"]) == 1 and p2["runs"][0]["vehicle"] == "mazda"
    s = call(api, "map_settings", changes={"fuel": {"diesel": 300}})["settings"]
    assert s["fuel"]["diesel"] == 300 and s["fuel"]["petrol"] == 265
    assert call(api, "map_fuel")["ok"] is False                                  # offline: keeps the prices


def test_agent_tools_for_other_data_and_logistics(api):
    from stockcompass.agent.tools import Toolbox
    imp(api.db, "waste.txt", WASTE)
    tb = Toolbox(api)
    lst = tb.call("other_data", {})
    assert lst["datasets"][0]["name"] == "Store waste report"
    d = tb.call("other_data", {"dataset": "waste", "by": "store"})
    assert d["totals"]["Waste Qty"] == 21 and d["groups"][0]["name"]
    t = tb.call("logistics", {"what": "trip", "from": "Fortress", "to": ["Lucky One"], "cartons": 100})
    assert t["km"] > 1000 and t["total"] > 0
    assert tb.call("logistics", {"what": "settings"})["vehicles"]


def test_dc_is_fortress(api):
    b = call(api, "map_boot")
    dc = [p for p in b["places"] if p.get("dc")]
    assert [p["code"] for p in dc] == ["500"]
    r = call(api, "map_dc")
    assert r["dc"] == "500" and r["rows"] and all(x["store"] not in ("500", "P04") for x in r["rows"])   # its Myli goes with it
    near = r["rows"][0]
    assert near["city"] == "Lahore" and near["vehicle"] == "mazda"
    far = next(x for x in r["rows"] if x["store"] == "505")
    assert far["vehicle"] == "container20" and far["km"] > 1000 and far["cost"] > near["cost"]
    call(api, "map_settings", changes={"dc_store": "503"})
    assert call(api, "map_dc")["dc"] == "503"
    from stockcompass.agent.tools import Toolbox
    assert Toolbox(api).call("logistics", {"what": "dc"})["stores"]


def test_lpo_support_feeds_the_order_advisor(api):
    import synth
    db = api.db
    out = imp(db, "LPO SUPPORT 504.txt", synth.lpo_support_text("504"))
    assert out[0].report_type == "gima_lpo_support" and out[0].stores == ["504"]
    assert out[0].snapshot_date.isoformat() == "2026-09-28"                     # from INSERT_DATE (HHMMSSDDMMYY)
    r = db.qd("SELECT * FROM order_line WHERE item='230001'")[0]
    assert r["ordered"] == 120 and r["review_days"] == 14 and r["pcb"] == 12 and r["w1"] == 77 and r["d1"] == 11
    assert db.one("SELECT pcb FROM items WHERE item='230001'") == 12
    adv = call(api, "advisor", store="504")
    lines = {l["item"]: l for l in adv["lines"]}
    a = lines["230000"]                                                           # zero stock, nothing on order, sells ~12/day
    assert a["decision"] == "order" and a["on_order"] == 0 and a["lead"] == 6 and a["review"] == 3.5
    assert a["speed_from"] == "6 full weeks of sales" and a["qty"] % 12 == 0 and a["qty"] > 0
    from stockcompass.analytics.orders import weekly
    assert weekly({"w1": 5, "w2": 60, "w3": 70, "w4": 50, "w5": 0, "w6": 0, "w7": 0}) == [60, 70, 50]   # this week so far and pre-launch zeros left out
    assert lines["230004"]["on_order"] == 600 and lines["230004"]["decision"] == "none"   # plenty on order already
    assert lines["230003"]["decision"] == "stop" and "already on order" in lines["230003"]["reason"]
    assert any("LPO support" in n for n in adv["notes"])
    chk = call(api, "order_checks", store="504")
    g = {x["key"]: x for x in chk["groups"]}
    assert {x["item"] for x in g["zero_not_ordered"]["rows"]} >= {"230000", "230002"}
    assert "230001" not in {x["item"] for x in g["zero_not_ordered"]["rows"]}             # on order
    assert [x["item"] for x in g["not_selling_on_order"]["rows"]] == ["230003"]
    assert "230004" in {x["item"] for x in g["over_ordered"]["rows"]} and g["negative"]["count"] == 1
    home = call(api, "page", name="home", ctx={"role": "sm", "where": "504"})
    assert any(j["key"] == "order_sheet" for j in home["jobs"])
    steps = {s["key"]: s for s in call(api, "setup")["steps"]}
    assert steps["lpo_support"]["status"] in ("done", "partial")
