"""The Agent: provider formats, tool loop with approvals, reports, memory, offline runtime — all offline, against a
fake AI server (tests/mock_llm.py) that speaks the OpenAI and Anthropic streaming formats."""

import json
import os
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from stockcompass.agent import local as LO
from stockcompass.agent import memory as M
from stockcompass.agent import providers as P
from stockcompass.agent import report as R
from stockcompass.agent import secrets as K
from stockcompass.agent.tools import Toolbox
from stockcompass.db import Database
from stockcompass.importer.pipeline import import_files
from stockcompass.web.api import Api, Host, dumps

import mock_llm
import synth


class TmpHost(Host):
    def __init__(self, folder):
        self.folder = folder

    def save_path(self, name):
        return str(self.folder / name)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("agent")
    os.environ["STOCKCOMPASS_HOME"] = str(tmp / "home")
    files = synth.build_all(tmp / "files")
    db = Database(tmp / "t.duckdb")
    import_files(list(files.values()), db)
    api = Api(db, TmpHost(tmp))
    srv = mock_llm.serve()
    base = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    api.dispatch("agent_custom_add", {"ctx": {}, "name": "Mock", "base_url": base, "key": "k", "models": "mock-1"})
    api.dispatch("agent_custom_add", {"ctx": {}, "name": "MockA", "base_url": base, "key": "k", "models": "claude-x", "kind": "anthropic"})
    # keep the tests off the internet: keyless public services would otherwise really be called on a build machine
    saved = list(P.PROVIDERS)
    P.PROVIDERS[:] = [p for p in P.PROVIDERS if p.needs_key or p.local or p.id == "auto"]
    yield api, srv, base, tmp
    P.PROVIDERS[:] = saved
    srv.shutdown()
    db.close()


def call(api, method, **p):
    r = json.loads(dumps(api.dispatch(method, dict(ctx={"role": "ho"}, **p))))
    assert not (isinstance(r, dict) and r.get("trace")), r.get("trace")
    return r


def converse(api, text, model="mock-1", provider="custom_mock", approve=None, answer=None):
    r = call(api, "agent_send", text=text, provider=provider, model=model, effort="medium")
    assert "run" in r, r
    evs, since = [], 0
    for _ in range(400):
        p = call(api, "agent_poll", run=r["run"], since=since)
        evs += p["events"]
        since = len(evs)
        for e in p["events"]:
            if e["type"] == "approval" and approve is not None:
                call(api, "agent_approve", run=r["run"], action=e["id"], yes=approve)
            if e["type"] == "question" and answer is not None:
                call(api, "agent_answer", run=r["run"], id=e["id"], answer=answer)
        if p["done"]:
            break
        time.sleep(0.03)
    return r["chat"], evs


# ------------------------------------------------------------------------------------------------ formats
def test_message_formats():
    msgs = [{"role": "system", "content": "sys"},
            {"role": "user", "content": [{"type": "text", "text": "hi"}, {"type": "image", "media_type": "image/png", "data": "AAA"}]},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "name": "find", "args": {"query": "x"}}]},
            {"role": "tool", "tool_call_id": "t1", "name": "find", "content": "{}"},
            {"role": "tool", "tool_call_id": "t2", "name": "find", "content": "{}"}]
    o = P._to_openai(msgs, vision=True)
    assert o[1]["content"][1]["type"] == "image_url" and o[2]["tool_calls"][0]["function"]["arguments"] == '{"query": "x"}'
    assert o[3]["tool_call_id"] == "t1"
    o2 = P._to_openai(msgs, vision=False)
    assert isinstance(o2[1]["content"], str) and "cannot see images" in o2[1]["content"]
    system, a = P._to_anthropic(msgs)
    assert system == "sys" and a[1]["content"][0]["type"] == "tool_use"
    assert a[2]["role"] == "user" and [b["type"] for b in a[2]["content"]] == ["tool_result", "tool_result"]   # merged
    assert len(P.PROVIDERS) >= 25 and all(p.base_url.startswith("http") for p in P.PROVIDERS if p.id != "auto")


def test_keys_are_not_stored_in_clear():
    blob = K.protect("sk-secret-123456")
    assert "sk-secret" not in blob and K.unprotect(blob) == "sk-secret-123456"
    assert K.mask("sk-secret-123456").startswith("sk-s") and K.unprotect("") == ""


# ------------------------------------------------------------------------------------------------ provider test button
def test_provider_test_and_errors(env):
    api, srv, base, _ = env
    r = call(api, "agent_test", provider="custom_mock", model="mock-1")
    assert r["ok"] and r["tools"] and any(s["step"] == "models" and s["ok"] for s in r["steps"])
    bad = P.test(P.Provider("x", "Xcorp", base), "bad")
    assert not bad["ok"] and "rejected the key" in bad["error"]
    with pytest.raises(P.ProviderError) as e:
        P.list_models(P.Provider("y", "Nowhere", "http://127.0.0.1:9/v1", local=True), "")
    assert "running on this PC" in str(e.value)
    assert P.transcribe(P.Provider("m", "Mock", base), "k", b"RIFF....") == "what is happening in the country"


# ------------------------------------------------------------------------------------------------ the agent loop
def test_tool_loop_chart_and_saved_chat(env):
    api = env[0]
    chat, evs = converse(api, "What's happening in the country?")
    kinds = [e["type"] for e in evs]
    assert kinds[0] == "start" and kinds[-1] == "done" and "error" not in kinds
    assert [e["name"] for e in evs if e["type"] == "tool" and e["status"] == "done"] == ["data_overview", "chart"]
    assert "chart" in kinds and "thinking" in kinds
    msgs = call(api, "agent_chat", chat=chat)["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    blocks = [b["type"] for b in msgs[1]["blocks"]]
    assert blocks == ["tool", "tool", "chart", "text"] and "42" in msgs[1]["text"]
    assert any(c["id"] == chat for c in call(api, "agent_chats")["chats"])
    # a follow-up in the same chat carries the history
    chat2, _ = converse(api, "thanks")
    assert chat2 != chat


def test_changes_need_approval(env):
    api = env[0]
    _, evs = converse(api, "add a promotion please", approve=False)
    assert any(e["type"] == "approval_done" and not e["approved"] for e in evs)
    assert not api.db.q("SELECT * FROM user_promo WHERE code='TST1'")
    _, evs = converse(api, "add a promotion please", approve=True)
    row = api.db.qd("SELECT * FROM user_promo WHERE code='TST1'")
    assert row and row[0]["stores"] and str(row[0]["date_from"]) == "2026-10-01"
    assert "TST1" in [t["k"] for t in call(api, "page", name="promos")["themes"]]
    assert call(api, "agent_memory")["log"][0]["action"] == "add_promotion"
    # with approvals switched off the change goes straight through
    call(api, "agent_prefs", ask_changes=False)
    api.db.execute("DELETE FROM user_promo")
    _, evs = converse(api, "add a promotion please")
    assert "approval" not in [e["type"] for e in evs] and api.db.q("SELECT 1 FROM user_promo")
    call(api, "agent_prefs", ask_changes=True)


def test_report_files(env):
    api = env[0]
    _, evs = converse(api, "make me a report")
    rep = next(e for e in evs if e["type"] == "report")
    kinds = {f["kind"]: f["path"] for f in rep["files"]}
    assert {"html", "docx", "xlsx"} <= set(kinds)
    from docx import Document
    doc = Document(kinds["docx"])
    assert "Test report" in doc.paragraphs[1].text or any("Test report" in p.text for p in doc.paragraphs)
    assert doc.tables and doc.tables[-1].rows[0].cells[0].text == "Store"
    import openpyxl
    wb = openpyxl.load_workbook(kinds["xlsx"])
    assert "Summary" in wb.sheetnames and len(wb.sheetnames) >= 2
    sh = wb[wb.sheetnames[1]]
    formulas = [c.value for row in sh.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=SUM")]
    assert formulas and sh.auto_filter.ref
    html = Path(kinds["html"]).read_text(encoding="utf-8")
    assert "<svg" in html and "<b>up</b>" in html


def test_model_without_tools_uses_briefing(env):
    api = env[0]
    _, evs = converse(api, "any question", model="mock-notools")
    assert any(e["type"] == "chart" for e in evs) and not any(e["type"] == "error" for e in evs)
    assert "mock-notools" in call(api, "agent_config")["providers"][-2]["no_tools"] or any(
        "mock-notools" in p.get("no_tools", []) for p in call(api, "agent_config")["providers"])
    # the other model on the same provider keeps its tools
    _, evs = converse(api, "What's happening in the country?")
    assert any(e["type"] == "tool" for e in evs)


def test_anthropic_format(env):
    api = env[0]
    _, evs = converse(api, "what's happening?", model="claude-x", provider="custom_mocka")
    assert [e["name"] for e in evs if e["type"] == "tool" and e["status"] == "done"] == ["data_overview", "chart"]
    assert "error" not in [e["type"] for e in evs]


def test_missing_setup_is_explained(env):
    api = env[0]
    call(api, "agent_prefs", router=False)             # with the router off, missing setup is explained
    assert "key" in call(api, "agent_send", text="hi", provider="groq", model="x")["error"]
    call(api, "agent_prefs", router=True)              # with it on, the question still goes somewhere
    r = call(api, "agent_send", text="hi", provider="groq", model="x")
    assert r.get("run") and not r.get("error")
    for _ in range(600):
        if call(api, "agent_poll", run=r["run"])["done"]:
            break
        time.sleep(0.05)


# ------------------------------------------------------------------------------------------------ tools on real-shaped data
def test_tools_answer_from_the_data(env):
    api = env[0]
    tb = Toolbox(api)
    ov = tb.call("data_overview", {})
    assert ov["reports"]["rows"] and ov["stores"]
    item = api.db.one("SELECT item FROM stock_item WHERE store='504' LIMIT 1")
    st = tb.call("item_status", {"item": item, "store": "Packages"})
    assert st["store_filter"] == "504" and all(r["store"] == "504" for r in st["stock_by_store"]["rows"])
    word = api.db.one("SELECT split_part(description, ' ', 1) FROM items WHERE item=?", [item])
    assert tb.call("find", {"query": word})["results"]
    assert tb.call("sql", {"query": "SELECT count(*) n FROM items"})["rows"][0]["n"] > 0
    for bad in ["DELETE FROM items", "select 1; drop table items", "UPDATE items SET item='x'", "attach 'x.db'"]:
        assert "error" in tb.call("sql", {"query": bad})
    assert tb.call("screen", {"page": "stock", "tab": "neg"})["kpis"]
    d = tb.call("drill", {"metric": "negative", "path": [{"lvl": "store", "k": "504"}]})
    assert d["total"] and d["rows"]
    assert "several_matches" in tb.call("item_status", {"item": "zzzz-nothing"}) or "error" in tb.call("item_status", {"item": "zzzz-nothing"})
    cols = tb.call("describe_tables", {"tables": ["zero_item"]})
    assert "days_out INTEGER" in cols["zero_item"]["columns"]


def test_memory_and_digest(env):
    api = env[0]
    M.remember(api.db, "Packages Mall LHH is being refitted until 15 Oct", "note", "", "user", True)
    M.remember(api.db, "Unrelated fact about bakery", "note")
    hits = M.recall(api.db, "what is going on at packages LHH")
    assert hits and "refitted" in hits[0]["text"]
    before = len(M.memories(api.db))
    api.agent.digest([{"ok": True, "type": "GIMA negative stock sheet", "file": "neg.xlsx", "summary": "20 rows"}])
    mem = M.memories(api.db)
    assert len(mem) == before + 1 and any(m["kind"] == "digest" and "Headline" in m["text"] for m in mem)


def test_attachments(env, tmp_path):
    api = env[0]
    import base64
    csv = "store,item,qty\n504,123,5\n"
    r = call(api, "agent_upload", name="stock.csv", data=base64.b64encode(csv.encode()).decode())
    assert r["kind"] == "text" and r["is_report"] and "store,item" in r["preview"]
    png = call(api, "agent_upload", name="shot.png", data="data:image/png;base64," + base64.b64encode(b"\x89PNG....").decode(), mime="image/png")
    assert png["kind"] == "image"
    chat, evs = converse(api, "What's happening in the country?")
    r2 = call(api, "agent_send", text="look at this", attachments=[r["id"], png["id"]], provider="custom_mock", model="mock-1")
    for _ in range(200):
        if call(api, "agent_poll", run=r2["run"])["done"]:
            break
        time.sleep(0.03)
    sent = env[1].requests[-1]["messages"]
    user = next(m for m in reversed(sent) if m["role"] == "user")
    assert isinstance(user["content"], list) and any(p.get("type") == "image_url" for p in user["content"])
    assert any("stock.csv" in (p.get("text") or "") for p in user["content"])


# ------------------------------------------------------------------------------------------------ reports module
def test_markdown_and_charts():
    h = R.md_to_html("# Title\n\n- **a** b\n- c\n\n| A | B |\n|---|---|\n| x | 1,200 |\n\nplain *it*")
    assert "<h2>Title</h2>" in h and "<ul>" in h and "<table class='sortable'>" in h and "class='n'" in h and "<i>it</i>" in h
    t = R.table_html(["Store", "Sales", "Margin %"], [["A", "PKR 1,000", "10%"], ["B", 2000, "20%"]])
    assert "<tfoot>" in t and "PKR 3,000" in t and "avg 15.0%" in t
    assert R.totals_row(["Store", "Sales"], [["A", 1], ["Total", 1]]) is None      # already has a total
    for t in ("bar", "line", "hbar"):
        svg = R.svg_chart({"type": t, "labels": ["2026-09-01", "2026-09-02"], "series": [{"name": "s", "values": [1, 2.5]}], "unit": "pkr"})
        assert svg.startswith("<svg") and "</svg>" in svg
    assert R.svg_chart({"type": "bar", "labels": [], "series": []}) == ""


# ------------------------------------------------------------------------------------------------ offline models
def test_download_resumes(tmp_path):
    (tmp_path / "srv").mkdir()
    blob = os.urandom(3_000_000)
    (tmp_path / "srv" / "m.gguf").write_bytes(blob)

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(tmp_path / "srv"), **k)

        def log_message(self, *a):
            pass

        def send_head(self):   # simple Range support like Hugging Face's CDN
            rng = self.headers.get("Range")
            if not rng:
                return super().send_head()
            start = int(rng.split("=")[1].split("-")[0])
            data = blob[start:]
            self.send_response(206)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            import io
            return io.BytesIO(data)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    dest = tmp_path / "out" / "m.gguf"
    dest.parent.mkdir()
    dest.with_suffix(".gguf.part").write_bytes(blob[:1_000_000])     # an interrupted earlier download
    jid = LO.DOWNLOADS.start(f"http://127.0.0.1:{srv.server_address[1]}/m.gguf", dest, "m")
    for _ in range(200):
        if LO.DOWNLOADS.jobs[jid]["status"] != "running":
            break
        time.sleep(0.05)
    srv.shutdown()
    assert LO.DOWNLOADS.jobs[jid]["status"] == "done" and dest.read_bytes() == blob


@pytest.mark.skipif(sys.platform == "win32", reason="uses a shell-script stand-in for llama-server")
def test_offline_server_lifecycle(env, tmp_path):
    api = env[0]
    rt = LO.runtime_dir() / "llama"
    rt.mkdir(parents=True, exist_ok=True)
    fake = rt / "llama-server"
    fake.write_text(f"#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(Path(__file__).parent)!r})\n"
                    + (Path(__file__).parent / "fake_llama_server.py").read_text())
    fake.chmod(0o755)
    model = LO.models_dir() / "tiny.gguf"
    model.write_bytes(b"GGUF" + b"\0" * 100)
    st = call(api, "local_state")
    assert st["runtime"]["llama"] and any(m["file"] == "tiny.gguf" for m in st["installed"]) and st["catalogue"]
    call(api, "local_load", path=str(model))
    for _ in range(100):
        if LO.SERVER.status()["ready"]:
            break
        time.sleep(0.1)
    assert LO.SERVER.status()["ready"]
    cfg = call(api, "agent_config")
    assert cfg["provider"] == "offline" and cfg["server"]["model"] == "tiny.gguf"
    _, evs = converse(api, "What's happening in the country?", model="tiny.gguf", provider="offline")
    assert "done" in [e["type"] for e in evs] and "error" not in [e["type"] for e in evs]
    call(api, "local_unload")
    assert not LO.SERVER.status()["running"]
    call(api, "local_delete", path=str(model))
    assert not model.exists()


def test_repo_file_listing(monkeypatch):
    monkeypatch.setattr(LO, "_get_json", lambda url, timeout=30: [
        {"path": "Qwen2.5-3B-Instruct-Q4_K_M.gguf", "lfs": {"size": 1_930_000_000}},
        {"path": "Qwen2.5-3B-Instruct-Q8_0.gguf", "size": 3_300_000_000},
        {"path": "mmproj-model-f16.gguf", "size": 1}, {"path": "README.md", "size": 5}])
    files = LO.repo_files("bartowski/Qwen2.5-3B-Instruct-GGUF")
    assert [f["quant"] for f in files] == ["Q4_K_M", "Q8_0"] and files[0]["gb"] == 1.93


# ------------------------------------------------------------------------------------------------ round 2
def test_test_all_providers(env):
    api = env[0]
    call(api, "agent_test_all", start=True)
    for _ in range(200):
        st = call(api, "agent_test_all", start=False)
        if not st.get("running"):
            break
        time.sleep(0.05)
    res = st["results"]
    assert res["custom_mock"]["status"] == "ok" and res["custom_mock"]["tools"] is True
    assert "groq" not in res                       # no key -> not tested
    assert all(r["status"] in ("ok", "failed", "busy") for r in res.values())   # keyless services may be rate-limited


def test_role_aware_prompt_and_scope(env):
    api = env[0]
    svc = api.agent
    dm = svc._system({"role": "dm"}, True)
    assert "ONE district manager for the whole country" in dm and "Audience: the HEAD OFFICE" not in dm
    assert svc._system({"role": "ho", "where": "504"}, True) == svc._system({"role": "ho", "where": "500"}, True)   # cache-friendly
    note = svc._context_note("how are sales", {"role": "sm", "where": "504", "dept": "01"})
    assert "store 504" in note and "department 01" in note
    tb = Toolbox(api, scope={"where": "504"})
    assert tb.ctx({})["where"] == "504" and tb.ctx({"where": "all"})["where"] == "all"
    _, evs = converse(api, "What's happening in the country?")
    sent = env[1].requests[-1]["messages"]
    user = next(m for m in sent if m["role"] == "user")
    assert "[Context]" in (user["content"] if isinstance(user["content"], str) else user["content"][0]["text"])


def test_import_hint_and_ai(env, tmp_path):
    api = env[0]
    from stockcompass.importer import understand as U
    sc = U.hint_scores("purchase orders LPO list with GRN")
    assert max(sc, key=sc.get) == "lpo_list"
    # an odd sheet the importer cannot place on its own
    api.imp.ai_fn = None
    api._ai_hook = lambda: None                    # this test brings its own fake model
    p = tmp_path / "weekly waste log 12.csv"
    p.write_text("Branch,Article,Waste Qty,Waste Value\nFortress,123,4,1200\nEmporium,124,2,800\nPackages,125,1,50\nLucky,126,7,3000\n")
    call(api, "import_add", paths=[str(p)])
    for _ in range(200):
        st = call(api, "import_status")
        if not st["busy"] and not (st.get("ai") or {}).get("running"):
            break
        time.sleep(0.05)
    pid = next(x["pid"] for x in st["plans"] if x["file"] == p.name)
    answers = []

    def fake_ai(prompt):
        answers.append(prompt)
        assert "weekly waste log" in prompt and "Known report types" in prompt
        return ('Sure! {"report_type": "generic", "confidence": 0.8, "what_it_is": "Weekly waste by store and item", '
                '"store": null, "date": "2026-09-20", "columns": {"Waste Qty": "units thrown away", "Waste Value": "PKR at cost"}, "notes": ""}')

    api.imp.ai_fn = fake_ai
    api._ai_hook = lambda: None                    # keep the fake model
    st = call(api, "import_hint", pid=pid, hint="waste report from stores")
    for _ in range(200):
        st = call(api, "import_status")
        if not st["ai"]["running"]:
            break
        time.sleep(0.05)
    sheet = next(x for x in st["plans"] if x["pid"] == pid)["sheets"][0]
    assert answers and sheet["ai"]["what_it_is"] == "Weekly waste by store and item" and sheet["ai"]["columns"] == 2
    assert sheet["date"] == "2026-09-20"
    for other in st["plans"]:
        if other["pid"] != pid:
            call(api, "import_remove", pid=other["pid"])
    call(api, "import_run")
    for _ in range(300):
        st = call(api, "import_status")
        if not st["busy"]:
            break
        time.sleep(0.05)
    assert st["results"] and st["results"][0]["ok"], st["results"]
    note = api.db.qd("SELECT * FROM import_notes ORDER BY import_id DESC LIMIT 1")[0]
    assert note["hint"] == "waste report from stores" and "units thrown away" in note["columns"]
    # the description is remembered for next month's file with a similar name
    assert api.db.learned("import_hint").get(U.name_key("weekly waste log 13.csv").upper()) == "waste report from stores"
    # and the agent can read the file, rows and meanings
    tb = Toolbox(api)
    r = tb.call("read_import", {"file": "weekly waste"})
    assert r["table"] == "raw_row" and r["rows"] and r["notes"][0]["columns"]["Waste Value"] == "PKR at cost"
    assert "raw_row" in tb.call("describe_tables", {})["tables"]
    api.imp.ai_fn = None


@pytest.mark.skipif(sys.platform == "win32", reason="uses a shell-script stand-in for llama-server")
def test_offline_server_falls_back_on_unknown_flags(env, tmp_path):
    rt = LO.runtime_dir() / "llama"
    rt.mkdir(parents=True, exist_ok=True)
    fake = rt / "llama-server"
    fake.write_text(f"#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(Path(__file__).parent)!r})\n"
                    "if '-fa' in sys.argv: sys.exit('error: invalid argument: -fa')\n"
                    + (Path(__file__).parent / "fake_llama_server.py").read_text())
    fake.chmod(0o755)
    model = LO.models_dir() / "tiny2.gguf"
    model.write_bytes(b"GGUF")
    st = LO.SERVER.start(str(model))
    for _ in range(100):
        if LO.SERVER.status()["ready"]:
            break
        time.sleep(0.1)
    st = LO.SERVER.status()
    assert st["ready"] and not st["fast"] and "-b" in LO.SERVER.args
    LO.SERVER.stop()
    model.unlink()


def test_hierarchy_in_prompt(env):
    svc = env[0].agent
    sec = svc._system({"role": "sec"}, True)
    assert "SECTION MANAGER" in sec and "reports to the department head" in sec.lower() and "ESCALATION" in sec
    assert "COMMERCIAL DIRECTOR" in svc._system({"role": "cd"}, True)
    note = svc._context_note("x", {"role": "sec", "where": "504", "section": "12"})
    assert "section manager of S12" in note and "reports to the department head" in note
    assert "category team" in svc._context_note("x", {"role": "ho", "dept": "02"})
    home = call(env[0], "page", name="home")
    assert home is not None


def test_agent_asks_and_remembers_meanings(env):
    api = env[0]
    _, evs = converse(api, "what is XYZ in this file?", answer="Extra yield from promotions")
    q = next(e for e in evs if e["type"] == "question")
    assert q["term"] == "XYZ" and q["options"]
    assert any(e["type"] == "answer" and e["answer"] == "Extra yield from promotions" for e in evs)
    g = call(api, "agent_glossary")["glossary"]
    assert any(x["term"] == "XYZ" and "Extra yield" in x["text"] for x in g)
    # the glossary is part of the fixed prompt and the importer's AI prompt; a new meaning replaces the old one
    assert "XYZ = Extra yield" in api.agent._system({"role": "ho"}, True)
    from stockcompass.importer import understand as U
    assert "XYZ = Extra yield" in U.glossary(api.db)
    call(api, "agent_define", term="xyz", meaning="Cross-dock")
    g = call(api, "agent_glossary")["glossary"]
    assert [x["text"] for x in g if x["term"].lower() == "xyz"] == ["xyz = Cross-dock"]
    # a skipped question is not saved
    _, evs = converse(api, "what is xyz again", answer="")
    assert any(e["type"] == "answer" and e["answer"] is None for e in evs)


def test_agent_runs_the_import(env, tmp_path):
    api = env[0]
    p = tmp_path / "shrink list 3.csv"
    p.write_text("Branch,Article,Shrink Qty,Shrink Value\nFortress,123,4,1200\nEmporium,124,2,800\nPackages,125,1,50\n")
    call(api, "import_clear")
    tb = Toolbox(api, files={"shrink list 3.csv": str(p)})
    assert "error" in tb.call("import_file", {"file": "nothing.xlsx"})
    q = tb.call("import_file", {"file": "shrink list", "hint": "shrinkage by store"})
    f = next(x for x in q["files"] if x["file"] == p.name)
    assert f["description"] == "shrinkage by store" and f["sheets"][0]["read_as"]
    q = tb.call("import_set", {"file_no": f["file_no"], "sheet_no": 0, "report_type": "generic"})
    assert q["files"][f["file_no"]]["sheets"][0]["read_as"] == "generic"
    r = tb.call("import_run", {})
    assert r["results"] and r["results"][0]["ok"], r
    iid = api.db.one("SELECT max(import_id) FROM imports WHERE file_name=?", [p.name])
    assert tb.call("save_meaning", {"term": "Shrink Value", "meaning": "PKR lost at cost", "import_id": iid})["saved"]
    assert "PKR lost at cost" in tb.call("read_import", {"import_id": iid})["notes"][0]["columns"]["Shrink Value"]
    assert tb.call("delete_import", {"import_id": iid})["deleted"]
    assert not api.db.q("SELECT 1 FROM imports WHERE import_id=?", [iid])
    names = {t["name"]: t["write"] for t in __import__("stockcompass.agent.tools", fromlist=["x"]).tool_specs()}
    assert names["import_run"] and names["delete_import"] and not names["ask_user"]


def test_retired_or_busy_models_fall_back(env):
    api, _, base, _ = env
    call(api, "agent_custom_add", name="Stale", base_url=base, key="k", models="gone-1,busy-1")
    r = call(api, "agent_test", provider="custom_stale")
    assert r["ok"] and r["model"] == "mock-1" and r["switched_from"] == "gone-1", r
    assert "text-embedding-3" not in P.candidates(api.agent.provider("custom_stale"), r["models"])
    # the model that answered becomes the default for that provider
    assert call(api, "agent_config")["providers"][-1]["models"][0] == "mock-1"
    # a chat on a retired model switches by itself and says so
    chat, evs = converse(api, "What's happening in the country?", provider="custom_stale", model="gone-1")
    assert any(e["type"] == "route" and "mock-1" in e["text"] for e in evs) and not any(e["type"] == "error" for e in evs)
    assert "mock-1" in call(api, "agent_chat", chat=chat)["messages"][-1]["model"]
    # rate limits are "busy", a bad key is not a model problem
    assert P.rate_limited(P.ProviderError("x", 429)) and P.model_error(P.ProviderError("x", 429))
    assert not P.model_error(P.ProviderError("bad key", 401))
    assert P.model_error(P.ProviderError("m", 400, '{"error":{"message":"Model gpt-oss:20b is currently unavailable"}}'))
    gem = P.get("gemini", [])
    assert gem.models[0].endswith("-latest")
    P.MODEL_INFO["openrouter"] = {"a/x:free": {"tools": True, "free": True}, "a/y": {"tools": True, "free": False},
                                  "a/z:free": {"tools": False, "free": True}}
    c = P.candidates(P.get("openrouter", []), ["a/x:free", "a/y", "a/z:free"])
    assert "a/y" not in c and c.index("a/x:free") < c.index("a/z:free")
    call(api, "agent_custom_remove", provider="custom_stale")


def test_rate_limits_wait_and_suggested_models(env):
    api, srv, base, _ = env
    call(api, "agent_custom_add", name="Tight", base_url=base, key="k", models="tpm-1")
    chat, evs = converse(api, "What's happening in the country?", provider="custom_tight", model="tpm-1")
    assert not any(e["type"] == "error" for e in evs), evs
    assert "42" in call(api, "agent_chat", chat=chat)["messages"][-1]["text"]
    sent = [r for r in srv.requests if r.get("model") == "tpm-1" and r.get("tools")]
    assert len(sent[-1]["tools"]) < len(sent[0]["tools"])         # fewer tools after going lean
    assert api.agent.cfg()["providers"]["custom_tight"]["lean"] is True
    # a retired model whose error names its replacement: that one is tried first
    chat, evs = converse(api, "What's happening in the country?", provider="custom_tight", model="gone-2")
    assert any(e["type"] == "route" and "→ mock-1" in e["text"] for e in evs), evs
    from stockcompass.agent.service import lean_specs
    from stockcompass.agent.tools import tool_specs
    names = {t["name"] for t in lean_specs(tool_specs(), "suppliers with highest depreciation in all stores")}
    assert {"analyse", "supplier_status"} <= names and "make_report" not in names and len(names) < 16
    call(api, "agent_custom_remove", provider="custom_tight")


def test_router_never_leaves_the_user_without_an_answer(env):
    api = env[0]
    svc = api.agent
    call(api, "agent_custom_add", name="Dead", base_url="http://127.0.0.1:9/v1", key="k", models="x-1")
    # the chosen service is down: the router moves on to one that works, quietly
    chat, evs = converse(api, "What's happening in the country?", provider="custom_dead", model="x-1")
    assert not any(e["type"] == "error" for e in evs), evs
    assert any(e["type"] == "route" and "Dead" in e["text"] for e in evs)
    last = call(api, "agent_chat", chat=chat)["messages"][-1]
    assert "42" in last["text"] and "Dead" not in last["model"] and last["stats"]["route"]
    assert not svc._healthy("custom_dead")                           # cooling down, skipped next time
    assert call(api, "agent_config")["health"]["custom_dead"]["cooling"] > 0
    # the Auto choice works with no setup at all and lists its order
    t = call(api, "agent_test", provider="auto")
    assert t["ok"] and "Stock Compass analysis" in t["steps"][0]["detail"]
    # every AI down: Stock Compass answers from its own analysis
    from stockcompass.agent import providers as PP
    orig_route, orig_off = svc._route, svc._start_offline
    svc._route = lambda first, model: [(svc.provider("custom_dead"), "x-1")]
    svc._start_offline = lambda run: None
    svc.health.clear()
    try:
        chat, evs = converse(api, "tell me suppliers with highest depreciation amount in all stores", provider="custom_dead", model="x-1")
    finally:
        svc._route, svc._start_offline = orig_route, orig_off
    last = call(api, "agent_chat", chat=chat)["messages"][-1]
    assert not any(e["type"] == "error" for e in evs), evs
    assert last["model"].startswith("Stock Compass analysis") and "| # | Supplier |" in last["text"] and "Total" in last["text"]
    assert any(b["type"] == "chart" for b in last["blocks"])
    call(api, "agent_custom_remove", provider="custom_dead")
    svc.health.clear()


def test_tool_calls_written_as_text_and_cut_answers(env):
    api, srv, base, _ = env
    call(api, "agent_custom_add", name="Texty", base_url=base, key="k", models="textcalls-1,long-1")
    chat, evs = converse(api, "What's happening in the country?", provider="custom_texty", model="textcalls-1")
    last = call(api, "agent_chat", chat=chat)["messages"][-1]
    assert "42" in last["text"] and "<tool_call>" not in last["text"], last["text"]
    assert any(e["type"] == "tool" and e["name"] == "data_overview" and e["status"] == "done" for e in evs)
    assert not any(e["type"] == "text" and "<tool_call" in e.get("delta", "") for e in evs)   # never shown
    chat, evs = converse(api, "hello", provider="custom_texty", model="long-1")
    assert call(api, "agent_chat", chat=chat)["messages"][-1]["text"] == "First half and the second half."
    from stockcompass.agent import providers as PP
    assert PP.text_tool_calls("plain answer", {"sql"}) == ("plain answer", [])
    call(api, "agent_custom_remove", provider="custom_texty")


def test_a_slow_service_is_overtaken(env):
    api = env[0]
    svc = api.agent
    call(api, "agent_custom_add", name="Slowpoke", base_url=env[2], key="k", models="slow-1")
    call(api, "agent_custom_add", name="Quick", base_url=env[2], key="k", models="mock-1")
    c = svc.cfg()
    for x in c["custom"]:
        if x["id"] in ("custom_slowpoke", "custom_quick"):
            x["local"] = False                  # behave like internet services (local ones are never raced)
    c["providers"]["custom_quick"]["tested"] = {"ok": True}
    svc.save_cfg(c)
    svc.health.clear()
    t0 = time.time()
    chat, evs = converse(api, "What's happening in the country?", provider="custom_slowpoke", model="slow-1")
    took = time.time() - t0
    last = call(api, "agent_chat", chat=chat)["messages"][-1]
    assert "42" in last["text"] and "Quick" in last["model"], (last["model"], evs)
    assert any(e["type"] == "route" and "slow to start" in e["text"] for e in evs)
    assert took < 5.5, took                     # not the 6 s the slow one needs (and not a 35 s timeout)
    for pid in ("custom_slowpoke", "custom_quick"):
        call(api, "agent_custom_remove", provider=pid)
    svc.health.clear()


def test_connections_are_reused():
    import json as _j
    import threading as _th
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    seen = []

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            seen.append(self.client_address[1])          # the client's port = one TCP connection
            b = _j.dumps({"data": [{"id": "m"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    _th.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/v1/models"
    for _ in range(4):
        assert P.http_json("GET", url, {}) == {"data": [{"id": "m"}]}
    assert len(seen) == 4 and len(set(seen)) == 1                   # four requests, one connection
    for conns in list(P._POOL.values()):                             # the server dropped idle connections: reconnect
        for c in conns:
            c.sock.close()
    assert P.http_json("GET", url, {})["data"][0]["id"] == "m"
    srv.shutdown()
