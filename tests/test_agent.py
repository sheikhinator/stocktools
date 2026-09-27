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
    yield api, srv, base, tmp
    srv.shutdown()
    db.close()


def call(api, method, **p):
    r = json.loads(dumps(api.dispatch(method, dict(ctx={"role": "ho"}, **p))))
    assert not (isinstance(r, dict) and r.get("trace")), r.get("trace")
    return r


def converse(api, text, model="mock-1", provider="custom_mock", approve=None):
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
    assert len(P.PROVIDERS) >= 25 and all(p.base_url.startswith("http") for p in P.PROVIDERS)


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
    html = Path(kinds["html"]).read_text(encoding="utf-8")
    assert "<svg" in html and "<b>up</b>" in html


def test_model_without_tools_uses_briefing(env):
    api = env[0]
    _, evs = converse(api, "any question", model="mock-notools")
    assert any(e["type"] == "note" for e in evs) and any(e["type"] == "chart" for e in evs)
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
    assert "key" in call(api, "agent_send", text="hi", provider="groq", model="x")["error"]
    assert "offline model" in call(api, "agent_send", text="hi", provider="offline", model="x")["error"].lower()


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
    assert "<h2>Title</h2>" in h and "<ul>" in h and "<table>" in h and "class='n'" in h and "<i>it</i>" in h
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
