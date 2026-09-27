"""The Agent: runs conversations with the chosen model, lets it use Stock Compass tools, and remembers.

The screen sends a message and then polls for events (text as it is written, tools being used, charts,
reports, approval requests) so the window never freezes.
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import re
import tempfile
import threading
import time
import traceback
import uuid
from datetime import date
from pathlib import Path

from stockcompass.paths import exports_dir

from . import local, memory as M, providers as P, report as R, secrets as K
from .tools import Toolbox, chart_body, describe_change, tool_specs

EFFORT = {"low": {"rounds": 4, "tokens": 1800}, "medium": {"rounds": 8, "tokens": 4000}, "high": {"rounds": 14, "tokens": 8000}}

SYSTEM = """You are the Stock Compass analyst for MAF Carrefour Pakistan: an expert in retail supply chain, stock health,
sales, margin, suppliers, promotions, BC (business cycle) indicators and aged (DP) stock. You work inside the
Stock Compass desktop app and can see all the data the user imported (GIMA, BO, BC, DP, LPO and leaflet reports).

How to work
- Always get numbers from the tools; never invent or estimate figures you did not read. If the data is not loaded, say
  which report is missing (e.g. "import the BO 11b report for sales vs budget").
- You can see EVERYTHING in Stock Compass: every imported report and sheet (read_import, also for files that were not a
  known report), every table (describe_tables lists all; sql queries them), settings, targets, data checks and memory.
  Never say you cannot access something before checking with these tools.
- Start with data_overview when you are not sure what is loaded. Use screen / drill for the standard views, item_status
  for "status of X at Y", find to turn names into item codes, supplier_status for suppliers, and sql for anything else
  (call describe_tables first). Stores are identified by GIMA code (500 Fortress, 503 Emporium Mall, 504 Packages Mall…);
  tools accept store names too.
- Use recall when the question refers to the past, people, or things the user told you before. Use remember to save
  facts the user teaches you and important conclusions (with dates).
- If you do not understand a header, code, abbreviation or term and it is not in the glossary, memory or data, call
  ask_user with one short question (and the term) instead of guessing; the answer is saved so you never ask twice.
  When the user explains something in chat, save it with save_meaning.
- You also run the Import screen: import_file (attached files or paths), import_queue, import_set to correct a
  sheet's report type / store / date, then import_run. Check the queue before running.
- Changes (promotions, targets, thresholds, store names, importing or deleting data) go through tools; the user
  approves them.
- When a picture helps, call chart (one idea per chart). When the user asks for a report or document, call make_report
  with a clear structure; default formats PDF, Word and Excel.

How to write (reporting standard)
- Lead with the answer in one or two sentences, then the evidence, then what to do. Quantify in PKR and %.
- Use short headings, bullet points and small markdown tables. Name the period and scope ("month to date, 25 Jul,
  Packages Mall"). Say where a number comes from when it matters (e.g. "BO 11b").
- Wording: "zero stock" (the % measure: closing stock ≤ 0) and "out of stock" (items); never "empty". "Aged stock" or
  "DP stock", never "old stock". Currency is PKR (use K / M). Consignment stock is not ours.
- Recommendations must be concrete: which items, which stores, which supplier, what action, how much money.
- Be honest about gaps: broken days, missing stores, stale reports.

Today is {today}.
{org}
{persona}
{scope}
"""

ORG = """Organisation and reporting line (most senior first). Follow it in every action plan.
1. COMMERCIAL DIRECTOR (country) and DISTRICT MANAGER (country, ONE for all stores) - the senior-most pair.
   The commercial director owns commercial strategy: range, pricing, suppliers, promotions, budgets, margin.
   The district manager owns store operations across Pakistan: execution, availability, stock discipline, people.
2. HEAD OFFICE CATEGORY TEAM - one team per department (CG, FFD, Non-Food), reports to the commercial director.
   Owns its department's suppliers, assortment, listings / delistings, promo plans, orders policy, markdown approval,
   supplier claims and back margin.
3. STORE MANAGER - one per store, reports to the district manager. Owns everything in the store.
4. DEPARTMENT HEAD - CG head, FFD head, one Non-Food head (LHH+HHH+TXT), reports to the store manager; works with the
   category team of the same department on supplier and range topics.
5. SECTION MANAGER - reports to the department head. Owns shelves, counts, orders and daily tasks of one section.

Rules for every recommendation
- Only give the user actions inside THEIR sphere of control (what their role can decide or do themselves).
- Work that belongs to someone below them is a DELEGATION: say who does it ("ask the FFD head to …").
- Anything outside their control is an ESCALATION, and it goes ONE level up their own line, never skipping a level and
  never sideways to another store: a section manager raises it with the department head; a department head with the
  store manager (supplier / range / listing topics with the category team of their department, copying the store
  manager); a store manager with the district manager (and with the category team for supplier, range and promo
  issues); a category team with the commercial director; the commercial director and the district manager align
  with each other.
- Write each action with an owner and a deadline where sensible: "Owner: you / FFD head / category team (CG) …".
  When the user must push someone or send a message, draft it in the right tone for that person's level.
- Never tell a junior role to decide what only a senior role can (prices, delistings, supplier terms, budgets, markdown
  approval, IST between stores); tell them what to propose and to whom, with the evidence (items, PKR).
"""

PERSONA = {
    "cd": """Audience: the COMMERCIAL DIRECTOR (senior-most, all of Pakistan, all departments).
- Strategic and commercial: sales vs budget and LY, front margin, mix, suppliers, promotions ROI, range, price, DP provision.
- Break down by department (and its category team), format and region; name the worst suppliers and categories.
- Actions are decisions and asks to the category teams (owner = category team per department), plus what to align
  with the district manager on store execution. Short, executive, PKR first.""",
    "ho": """Audience: the HEAD OFFICE CATEGORY TEAM of one department (the department in the view; if none, ask which
department they buy for or cover all), for all stores. Reports to the commercial director.
- Think category-wide across stores: suppliers, families, items, listings, promotions, orders, aged/DP stock, margin.
- Rank stores and suppliers inside the department; show the spread and the PKR at stake.
- Their actions: supplier escalation and fill-rate chasing, range / listing changes, promo plans, order policy,
  markdown approval. Store execution issues go to store managers (via the district manager if systemic); decisions above
  their authority go to the commercial director.""",
    "dm": """Audience: the DISTRICT MANAGER. There is ONE district manager for the whole country (all stores), not a region.
Senior-most on operations, alongside the commercial director.
- Think store by store: which stores need a visit or a call today, what to ask each store manager, and follow-up items.
- Always break numbers down by store (then department) and flag exceptions against targets and against peers of the
  same format. Give a per-store action list (owner = that store manager) with PKR impact. Supplier, range and promo
  problems that are not a store's fault go to the category team of the department.""",
    "sm": """Audience: the STORE MANAGER of one store. Reports to the district manager.
- Talk about this store only unless asked to compare. Break down by department and section; name items and suppliers.
- Give today's priorities as a checklist with owners: department heads (CG / FFD / Non-Food) and section managers.
  Escalate to the district manager (operations) or the department's category team (suppliers, range, promos).
  Compare with same-format stores only for context.""",
    "dh": """Audience: a DEPARTMENT HEAD (CG, FFD or Non-Food = LHH+HHH+TXT) in one store. Reports to the store manager.
- Focus on their department in their store: sections, top items, suppliers, promotions, aged stock.
- Concrete item-level actions, delegated per section manager. Escalate to the store manager; raise supplier / range
  issues with the category team of the department (copy the store manager).""",
    "sec": """Audience: a SECTION MANAGER in one store. Reports to the department head.
- Very practical and short: item-level to-do list for their own section only (item code, description, what to do,
  why, PKR). Group by action: order now / chase / recount / move / mark down (propose).
- Anything they cannot do themselves goes to their department head: say exactly what to tell them. Simple words.""",
}

NO_TOOLS = """
This model cannot call tools, so a data briefing is included below. Answer from it only. To show a chart, write a fenced
block exactly like:
```chart
{{"type": "bar", "title": "…", "labels": ["A", "B"], "series": [{{"name": "Sales", "values": [1, 2]}}], "unit": "pkr"}}
```
"""


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(p.get("text", "") for p in content or [] if p.get("type") == "text")


class Run:
    def __init__(self, rid: str, chat_id: str):
        self.id, self.chat_id = rid, chat_id
        self.events: list[dict] = []
        self.done = False
        self.stop = threading.Event()
        self.approvals: dict[str, dict] = {}
        self.lock = threading.Lock()

    def emit(self, ev: dict):
        with self.lock:
            ev["i"] = len(self.events)
            self.events.append(ev)


class AgentService:
    def __init__(self, api):
        self.api = api
        self.db = api.db
        M.ensure(self.db)
        self.runs: dict[str, Run] = {}
        self.attach: dict[str, dict] = {}         # uploaded files waiting to be sent
        self.tests: dict = {}
        self.key("huggingface")
        self._model_cache: dict[str, list[str]] = {}

    # ------------------------------------------------------------------------------ settings
    def cfg(self) -> dict:
        c = self.db.setting("agent") or {}
        c.setdefault("providers", {})
        c.setdefault("custom", [])
        c.setdefault("provider", "")
        c.setdefault("model", "")
        c.setdefault("effort", "medium")
        c.setdefault("ask_changes", True)
        c.setdefault("voice", "auto")
        return c

    def save_cfg(self, c: dict):
        self.db.set_setting("agent", c)

    def key(self, pid: str) -> str:
        k = K.unprotect(self.cfg()["providers"].get(pid, {}).get("key", ""))
        if pid == "huggingface":
            local.HF_TOKEN["value"] = k
        return k

    # ------------------------------------------------------------------------------ test every provider
    def test_all(self) -> dict:
        if self.tests.get("running"):
            return self.tests
        c = self.cfg()
        todo = [p for p in P.PROVIDERS + [P.get(x["id"], c["custom"]) for x in c["custom"]]
                if (not p.needs_key or self.key(p.id)) and (p.id != "offline" or local.SERVER.status()["running"])
                and (not p.local or p.id == "offline" or p.id.startswith("custom") or (local.detect_local().get(p.id) is not None))]
        self.tests = {"running": True, "started": time.time(), "results": {p.id: {"id": p.id, "name": p.name, "status": "waiting", "local": p.local} for p in todo}}

        def one(p):
            r = self.tests["results"][p.id]
            r["status"] = "testing"
            t0 = time.time()
            try:
                model = (self.cfg()["model"] if self.cfg()["provider"] == p.id else None)
                if p.id == "offline":
                    model = local.SERVER.status()["model"]
                res = self.test(p.id, model)
                r.update(status="ok" if res.get("ok") else "failed", model=res.get("model"), tools=res.get("tools"),
                         models=len(res.get("models") or []), seconds=round(time.time() - t0, 1),
                         detail=res.get("error") or "; ".join(f"{x['step']}: {x['detail']}" for x in res.get("steps", [])))
            except Exception as e:
                r.update(status="failed", detail=str(e), seconds=round(time.time() - t0, 1))

        def run_all():
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(6) as ex:
                list(ex.map(one, todo))
            self.tests["running"] = False

        threading.Thread(target=run_all, daemon=True).start()
        return self.tests

    def account(self, pid: str) -> str:
        return self.cfg()["providers"].get(pid, {}).get("account", "")

    def provider(self, pid: str) -> P.Provider | None:
        return P.get(pid, self.cfg()["custom"])

    def config(self) -> dict:
        c = self.cfg()
        rows = []
        for p in P.PROVIDERS + [P.get(x["id"], c["custom"]) for x in c["custom"]]:
            pc = c["providers"].get(p.id, {})
            k = K.unprotect(pc.get("key", ""))
            rows.append(dict(id=p.id, name=p.name, free=p.free, key_url=p.key_url, local=p.local, needs_key=p.needs_key,
                             has_key=bool(k), key_mask=K.mask(k), account=pc.get("account", ""), needs_account=p.needs_account,
                             tools=p.tools, no_tools=pc.get("no_tools") or [], vision=p.vision, note=p.note, custom=p.id.startswith("custom"),
                             ready=bool(k) or not p.needs_key, tested=pc.get("tested"), models=self._models_for(p)))
        return dict(providers=rows, provider=c["provider"], model=c["model"], effort=c["effort"], ask_changes=c["ask_changes"],
                    voice=c["voice"], server=local.SERVER.status())

    def _models_for(self, p: P.Provider) -> list[str]:
        live = self.cfg()["providers"].get(p.id, {}).get("models") or self._model_cache.get(p.id) or []
        seen, out = set(), []
        for m in list(p.models) + list(live):
            if m not in seen:
                seen.add(m)
                out.append(m)
        c = self.cfg()
        if c["provider"] == p.id and c["model"] and c["model"] not in seen and p.id != "offline":
            out.insert(0, c["model"])
        if p.id == "offline":
            st = local.SERVER.status()
            out = [st["model"]] if st["model"] else [m["file"] for m in local.installed()]
        return out

    def set_key(self, pid: str, key: str = "", account: str = "") -> dict:
        c = self.cfg()
        pc = c["providers"].setdefault(pid, {})
        if key is not None:
            pc["key"] = K.protect(key.strip())
        if account is not None:
            pc["account"] = account.strip()
        pc.pop("tested", None)
        if not c["provider"] and key:
            c["provider"] = pid
            p = self.provider(pid)
            c["model"] = (p.models or [""])[0] if p else ""
        self.save_cfg(c)
        return self.config()

    def set_prefs(self, **kw) -> dict:
        c = self.cfg()
        for k in ("provider", "model", "effort", "ask_changes", "voice"):
            if k in kw and kw[k] is not None:
                c[k] = kw[k]
        self.save_cfg(c)
        return self.config()

    def add_custom(self, name: str, base_url: str, key: str = "", models: str = "", kind: str = "openai") -> dict:
        c = self.cfg()
        cid = "custom_" + re.sub(r"\W+", "_", name.lower()).strip("_")[:24]
        c["custom"] = [x for x in c["custom"] if x["id"] != cid] + [dict(id=cid, name=name, base_url=base_url.rstrip("/"), kind=kind,
                                                                           models=[m.strip() for m in models.split(",") if m.strip()],
                                                                           needs_key=bool(key), local=bool(re.search(r"localhost|127\.0\.0\.1", base_url)))]
        c["providers"].setdefault(cid, {})["key"] = K.protect(key)
        self.save_cfg(c)
        return self.config()

    def remove_custom(self, pid: str) -> dict:
        c = self.cfg()
        c["custom"] = [x for x in c["custom"] if x["id"] != pid]
        c["providers"].pop(pid, None)
        self.save_cfg(c)
        return self.config()

    def refresh_models(self, pid: str) -> dict:
        p = self.provider(pid)
        ids = P.list_models(p, self.key(pid), self.account(pid))
        c = self.cfg()
        c["providers"].setdefault(pid, {})["models"] = ids[:500]
        self.save_cfg(c)
        return {"models": self._models_for(p)}

    def test(self, pid: str, model: str | None = None) -> dict:
        p = self.provider(pid)
        if p is None:
            return {"ok": False, "error": "Unknown provider"}
        if p.needs_key and not self.key(pid):
            return {"ok": False, "error": "Add a key first."}
        r = P.test(p, self.key(pid), model, self.account(pid))
        c = self.cfg()
        pc = c["providers"].setdefault(pid, {})
        pc["tested"] = {"ok": r.get("ok"), "when": time.strftime("%Y-%m-%d %H:%M"), "model": r.get("model")}
        if "tools" in r and r.get("model"):
            nt = set(pc.get("no_tools") or [])
            (nt.discard if r["tools"] else nt.add)(r["model"])
            pc["no_tools"] = sorted(nt)
        if r.get("models"):
            pc["models"] = r["models"]
        self.save_cfg(c)
        return r

    # ------------------------------------------------------------------------------ attachments & voice
    def upload(self, name: str, data_b64: str, mime: str = "") -> dict:
        raw = base64.b64decode(data_b64.split(",", 1)[-1])
        mime = mime or mimetypes.guess_type(name)[0] or "application/octet-stream"
        aid = uuid.uuid4().hex[:10]
        safe = re.sub(r"[^\w.\-]+", "_", name)
        path = Path(tempfile.gettempdir()) / "stockcompass-agent" / f"{aid}-{safe}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        info = {"id": aid, "name": name, "mime": mime, "size": len(raw), "path": str(path)}
        info["kind"], info["text"] = self._extract(path, mime, raw)
        info["is_report"] = path.suffix.lower() in (".xlsx", ".xlsm", ".xls", ".xlsb", ".csv", ".txt", ".tsv", ".htm", ".html", ".ods")
        self.attach[aid] = info
        return {k: v for k, v in info.items() if k not in ("text", "path")} | {"preview": (info["text"] or "")[:300]}

    def _extract(self, path: Path, mime: str, raw: bytes) -> tuple[str, str]:
        ext = path.suffix.lower()
        try:
            if mime.startswith("image/"):
                return "image", ""
            if ext in (".txt", ".md", ".csv", ".tsv", ".json", ".log", ".xml", ".html", ".htm", ".sql", ".py", ".js"):
                return "text", raw.decode("utf-8", "replace")[:60000]
            if ext in (".xlsx", ".xlsm", ".xls", ".xlsb", ".ods"):
                from stockcompass.importer.reader import open_file
                wb = open_file(path)
                out = []
                for s in wb.sheets[:6]:
                    out.append(f"## Sheet: {s.name} ({s.kind}{', hidden' if s.hidden else ''}, {s.n_rows or '?'} rows)")
                    for r in s.head[:40]:
                        out.append("\t".join("" if v is None else str(v) for v in r))
                return "sheet", "\n".join(out)[:60000]
            if ext == ".docx":
                from docx import Document
                d = Document(io.BytesIO(raw))
                return "text", "\n".join(p.text for p in d.paragraphs)[:60000]
            if ext == ".pdf":
                try:
                    from pypdf import PdfReader
                    rd = PdfReader(io.BytesIO(raw))
                    return "text", "\n".join((pg.extract_text() or "") for pg in rd.pages[:40])[:60000]
                except ImportError:
                    return "file", "(PDF text could not be read on this PC.)"
            if mime.startswith("audio/"):
                return "audio", ""
        except Exception as e:
            return "file", f"(Could not read this file: {e})"
        return "file", ""

    def transcribe(self, wav_b64: str) -> dict:
        wav = base64.b64decode(wav_b64.split(",", 1)[-1])
        c = self.cfg()
        tried = []
        order = []
        if c["voice"] in ("auto", "offline"):
            order.append("offline")
        if c["voice"] in ("auto", "cloud"):
            order += [pid for pid in ("groq", "openai") if self.key(pid)]
        for how in order:
            try:
                if how == "offline":
                    if not local.find_exe("whisper"):
                        tried.append("offline voice not installed")
                        continue
                    return {"text": local.transcribe_offline(wav), "via": "offline (this PC)"}
                p = self.provider(how)
                return {"text": P.transcribe(p, self.key(how), wav, account=self.account(how)), "via": p.name}
            except Exception as e:
                tried.append(f"{how}: {e}")
        return {"error": "Voice typing needs either the offline voice model (Agent → Offline models → Voice) or a Groq/OpenAI key. "
                         + ("; ".join(tried) if tried else "")}

    # ------------------------------------------------------------------------------ chats
    def chats(self) -> list[dict]:
        return M.chats(self.db)

    def chat(self, cid: str) -> dict:
        msgs = M.messages(self.db, cid)
        return {"id": cid, "messages": [{"role": m["role"], "text": m.get("text", ""), "blocks": m.get("blocks") or [],
                                         "attachments": m.get("attachments") or [], "model": m.get("model"), "ts": str(m["_ts"])[:16],
                                         "error": m.get("error"), "stats": m.get("stats")} for m in msgs]}

    # ------------------------------------------------------------------------------ running a turn
    def send(self, text: str, chat_id: str | None = None, attachments: list[str] | None = None, provider: str | None = None,
             model: str | None = None, effort: str | None = None, ctx: dict | None = None) -> dict:
        c = self.cfg()
        pid = provider or c["provider"]
        p = self.provider(pid) if pid else None
        if p is None:
            return {"error": "Choose a model first (Agent → Models & keys)."}
        if p.needs_key and not self.key(pid):
            return {"error": f"Add your {p.name} key in Agent → Models & keys."}
        model = model or c["model"] or (self._models_for(p) or [""])[0]
        effort = effort or c["effort"]
        if pid == "offline" and not local.SERVER.status()["running"]:
            return {"error": "Load an offline model first (Agent → Offline models)."}
        if not chat_id:
            chat_id = M.new_chat(self.db, (text or "New chat").strip().split("\n")[0][:60], pid, model)
        att = [self.attach[a] for a in attachments or [] if a in self.attach]
        M.add_msg(self.db, chat_id, "user", {"text": text, "attachments": [{"id": a["id"], "name": a["name"], "kind": a["kind"], "size": a["size"],
                                                                             "is_report": a["is_report"]} for a in att]})
        run = Run(uuid.uuid4().hex[:10], chat_id)
        self.runs[run.id] = run
        threading.Thread(target=self._run, args=(run, p, model, effort, text, att, ctx or {}), daemon=True).start()
        return {"run": run.id, "chat": chat_id}

    def poll(self, run_id: str, since: int = 0) -> dict:
        r = self.runs.get(run_id)
        if not r:
            return {"events": [], "done": True}
        with r.lock:
            ev = r.events[since:]
        return {"events": ev, "done": r.done, "chat": r.chat_id}

    def stop(self, run_id: str) -> dict:
        r = self.runs.get(run_id)
        if r:
            r.stop.set()
            for a in r.approvals.values():
                a["answer"] = False
                a["event"].set()
        return {"ok": True}

    def approve(self, run_id: str, action_id: str, yes: bool) -> dict:
        r = self.runs.get(run_id)
        if r and action_id in r.approvals:
            r.approvals[action_id]["answer"] = bool(yes)
            r.approvals[action_id]["event"].set()
        return {"ok": True}

    def answer(self, run_id: str, qid: str, answer: str | None) -> dict:
        r = self.runs.get(run_id)
        if r and qid in r.approvals:
            r.approvals[qid]["answer"] = (answer or "").strip() or None
            r.approvals[qid]["event"].set()
        return {"ok": True}

    def _history(self, chat_id: str, limit_turns: int = 12) -> list[dict]:
        msgs = M.messages(self.db, chat_id)[:-1]          # the new user message is added separately
        out: list[dict] = []
        for m in msgs[-limit_turns * 2:]:
            if m["role"] == "user":
                t = m.get("text") or ""
                for a in m.get("attachments") or []:
                    t += f"\n[attached earlier: {a['name']}]"
                out.append({"role": "user", "content": t})
            elif m["role"] == "assistant":
                if m.get("llm"):
                    for x in m["llm"]:
                        if x["role"] == "tool" and isinstance(x.get("content"), str) and len(x["content"]) > 2500:
                            x = dict(x, content=x["content"][:2500] + " …(cut)")
                        out.append(x)
                elif m.get("text"):
                    out.append({"role": "assistant", "content": m["text"]})
        return out

    def _scope_text(self, ctx: dict) -> str:
        names = {c: n for c, n in self.db.q("SELECT code, name FROM stores")}
        where = (ctx or {}).get("where") or "all"
        w = ("all of Pakistan" if where in ("all", "") else f"format {where[4:]}" if where.startswith("fmt:") else
             f"region {where[4:]}" if where.startswith("reg:") else f"store {where} {names.get(where, '')}".strip())
        dept = (ctx or {}).get("dept") or ""
        dname = {"NF": "Non-Food (LHH, HHH, TXT)"} | {c: n for c, n in self.db.q("SELECT code, name FROM departments")}
        sec = (ctx or {}).get("section") or ""
        sname = self.db.one("SELECT name FROM sections WHERE code=?", [sec]) if sec else ""
        parts = [w] + ([f"department {dept} {dname.get(dept, '')}".strip()] if dept else []) + ([f"section S{sec} {sname or ''}".strip()] if sec else [])
        per = (ctx or {}).get("period") or "MTD"
        role = (ctx or {}).get("role") or "ho"
        dn = dname.get(dept, "") if dept else ""
        who = {"cd": "the commercial director (senior-most; category teams report to them)",
               "dm": "the district manager for all of Pakistan (senior-most on operations; store managers report to them)",
               "ho": f"the head office category team{' for ' + dn if dn else ''} (reports to the commercial director)",
               "sm": "the store manager (reports to the district manager)",
               "dh": f"the {dn or 'department'} head of the store (reports to the store manager)",
               "sec": f"the section manager of S{sec} {sname or ''} (reports to the department head)".replace("  ", " ")}.get(role, "")
        return (f"The user is {who}. " if who else "") + ("The user is currently looking at: " + " · ".join(parts) + f" (sales period {per}, compare with {(ctx or {}).get('compare') or 'budget'}). "
                "When the question does not name a store / department / section, answer for this view (tools default to it); "
                "pass where='all' to look at the whole country.")

    def _system(self, ctx: dict, tools_ok: bool) -> str:
        """The fixed part of the prompt. It stays identical between questions (the view and memory go into the
        question itself) so providers and the offline runtime can reuse their prompt cache: much faster replies."""
        role = (ctx or {}).get("role") or "ho"
        s = SYSTEM.format(today=date.today().strftime("%A %d %B %Y"), org=ORG, persona=PERSONA.get(role, PERSONA["ho"]),
                          scope="Each question starts with a [Context] note: the view the user has open and relevant memories.")
        try:
            inv = self.db.qd("""SELECT report_type, max(snapshot_date) latest, count(*) n FROM imports WHERE status='ok'
                                GROUP BY 1 ORDER BY latest DESC NULLS LAST, report_type LIMIT 30""")
            s += "\nData loaded (report: latest date): " + "; ".join(f"{r['report_type']}: {r['latest']}" for r in inv) + "\n"
        except Exception:
            pass
        g = M.glossary_text(self.db)
        if g:
            s += "\nGlossary (meanings the users taught you; trust these):\n" + g + "\n"
        if not tools_ok:
            s += NO_TOOLS
        return s

    def _context_note(self, question: str, ctx: dict) -> str:
        note = "[Context] " + self._scope_text(ctx)
        pins = [m for m in M.memories(self.db, 80) if m["pinned"] and m["kind"] != "definition"][:8]
        hits = [h for h in M.recall(self.db, question, 8) if h.get("kind") != "definition"][:6]
        mem = {m["id"]: m["text"] for m in pins} | {h["id"]: f"({h['when']}) {h['text']}" for h in hits}
        if mem:
            note += "\nFrom memory:\n" + "\n".join(f"- {t}" for t in mem.values())
        return note + "\n[Question]\n"

    def _briefing(self, tb: Toolbox, question: str) -> str:
        parts = {"overview": tb.t_data_overview(), "home": tb.t_screen("home"), "memory": tb.t_recall(question)}
        stores = [s for s in self.db.store_list() if s["name"].split()[0].lower() in question.lower()]
        if stores:
            parts["store_view"] = tb.t_screen("home", where=stores[0]["code"])
        words = re.findall(r"\b\d{5,7}\b", question)
        for w in words[:2]:
            parts[f"item_{w}"] = tb.t_item_status(w)
        if re.search(r"sale|budget|growth|margin", question, re.I):
            parts["sales"] = tb.t_screen("sales", where=stores[0]["code"] if stores else None)
        if re.search(r"promo|leaflet|theme", question, re.I):
            parts["promotions"] = tb.t_screen("promos")
        return json.dumps(parts, default=str)[:24000]

    def _run(self, run: Run, p: P.Provider, model: str, effort: str, text: str, att: list[dict], ctx: dict):
        blocks: list[dict] = []
        llm: list[dict] = []
        cur_text = {"t": ""}

        def emit(ev):
            if ev["type"] in ("chart", "report", "navigate", "memory"):
                flush_text()
                blocks.append({k: v for k, v in ev.items() if k != "i"})
            run.emit(ev)

        def flush_text():
            if cur_text["t"].strip():
                blocks.append({"type": "text", "text": cur_text["t"]})
            cur_text["t"] = ""

        def on_text(d):
            out_chars["n"] += len(d)
            cur_text["t"] += d
            run.emit({"type": "text", "delta": d})

        def on_think(d):
            run.emit({"type": "thinking", "delta": d})

        def ask(question, options, term):
            qid = uuid.uuid4().hex[:8]
            waiter = {"event": threading.Event(), "answer": None}
            run.approvals[qid] = waiter
            run.emit({"type": "question", "id": qid, "text": question, "options": options, "term": term})
            waiter["event"].wait(1800)
            ans = waiter["answer"] if isinstance(waiter["answer"], str) and waiter["answer"].strip() else None
            run.emit({"type": "answer", "id": qid, "answer": ans})
            flush_text()
            blocks.append({"type": "question", "text": question, "term": term, "answer": ans})
            return ans

        files = {a["name"]: a["path"] for a in self.attach.values()}
        tb = Toolbox(self.api, emit=emit, chat_id=run.chat_id, report_fn=self._report, scope=ctx, ask_fn=ask, files=files)
        pc = self.cfg()["providers"].get(p.id, {})
        tools_ok = bool(p.tools) and model not in (pc.get("no_tools") or [])
        specs = tool_specs()
        if p.local:      # small offline models: fewer, core tools = shorter prompt = much faster first answer
            core = {"data_overview", "screen", "drill", "find", "item_status", "supplier_status", "sql", "recall", "remember",
                    "chart", "make_report", "add_promotion", "read_import", "ask_user", "save_meaning"}
            specs = [t for t in specs if t["name"] in core]
        spec_by = {t["name"]: t for t in tool_specs()}
        cut = 6000 if p.local else 14000
        t_start, out_chars = time.time(), {"n": 0}
        key, account = self.key(p.id), self.account(p.id)
        lim = EFFORT.get(effort, EFFORT["medium"])
        run.emit({"type": "start", "model": model, "provider": p.name, "local": p.local})
        try:
            content: list[dict] = [{"type": "text", "text": self._context_note(text, ctx) + (text or "(see attachments)")}]
            for a in att:
                if a["kind"] == "image":
                    content.append({"type": "image", "media_type": a["mime"], "data": base64.b64encode(Path(a["path"]).read_bytes()).decode()})
                else:
                    extra = (a.get("text") or "")[:40000]
                    content.append({"type": "text", "text": f"\n--- Attached file: {a['name']} ({a['kind']}, {a['size']:,} bytes)"
                                                            + (" — this looks like a report; the user can import it into Stock Compass." if a["is_report"] else "")
                                                            + (f"\n{extra}" if extra else "") + "\n---"})
            convo = [{"role": "system", "content": self._system(ctx, tools_ok)}] + self._history(run.chat_id)
            if not tools_ok:
                convo[0]["content"] += "\n\nDATA BRIEFING (JSON):\n" + self._briefing(tb, text)
            user_msg = {"role": "user", "content": content if len(content) > 1 else content[0]["text"]}
            convo.append(user_msg)
            for rnd in range(lim["rounds"]):
                if run.stop.is_set():
                    break
                use_tools = tools_ok and rnd < lim["rounds"] - 1
                try:
                    rep = P.chat(p, key, model, convo, tools=[{k: v for k, v in t.items() if k != "write"} for t in specs] if use_tools else None,
                                 effort=effort, on_text=on_text, on_thinking=on_think, stop=run.stop, account=account, max_tokens=lim["tokens"])
                except P.ToolsUnsupported:
                    tools_ok = False
                    c = self.cfg()
                    nt = c["providers"].setdefault(p.id, {}).setdefault("no_tools", [])
                    if model not in nt:
                        nt.append(model)
                    self.save_cfg(c)
                    convo[0]["content"] = self._system(ctx, False) + "\n\nDATA BRIEFING (JSON):\n" + self._briefing(tb, text)
                    run.emit({"type": "note", "text": "This model cannot use tools; answering from a data briefing instead."})
                    continue
                if not rep.tool_calls:
                    llm.append({"role": "assistant", "content": rep.text})
                    break
                flush_text()
                am = {"role": "assistant", "content": rep.text, "tool_calls": rep.tool_calls}
                convo.append(am)
                llm.append(am)
                for tc in rep.tool_calls:
                    if run.stop.is_set():
                        break
                    spec = spec_by.get(tc["name"], {})
                    run.emit({"type": "tool", "id": tc["id"], "name": tc["name"], "args": tc["args"], "status": "running"})
                    tblock = {"type": "tool", "name": tc["name"], "args": tc["args"], "status": "running", "summary": ""}
                    blocks.append(tblock)
                    if spec.get("write") and self.cfg()["ask_changes"]:
                        aid = uuid.uuid4().hex[:8]
                        waiter = {"event": threading.Event(), "answer": None}
                        run.approvals[aid] = waiter
                        desc = describe_change(tc["name"], tc["args"])
                        run.emit({"type": "approval", "id": aid, "text": desc, "tool": tc["name"], "args": tc["args"]})
                        waiter["event"].wait(900)
                        ok = bool(waiter["answer"])
                        run.emit({"type": "approval_done", "id": aid, "approved": ok})
                        blocks.append({"type": "change", "text": desc, "approved": ok})
                        result = tb.call(tc["name"], tc["args"]) if ok else {"declined": "The user did not approve this change."}
                    else:
                        result = tb.call(tc["name"], tc["args"])
                    res_txt = json.dumps(result, default=str)
                    status = "error" if isinstance(result, dict) and result.get("error") else "done"
                    run.emit({"type": "tool", "id": tc["id"], "name": tc["name"], "status": status, "summary": _summary(tc["name"], result)})
                    tblock.update(status=status, summary=_summary(tc["name"], result))
                    tm = {"role": "tool", "tool_call_id": tc["id"], "name": tc["name"], "content": res_txt[:cut]}
                    convo.append(tm)
                    llm.append(dict(tm, content=res_txt[:3000]))
            flush_text()
            # charts written as fenced blocks (models without tools)
            final_blocks = []
            for b in blocks:
                if b["type"] == "text" and "```chart" in b["text"]:
                    for piece in re.split(r"(```chart\s*\n.*?```)", b["text"], flags=re.S):
                        m = re.match(r"```chart\s*\n(.*?)```", piece, re.S)
                        if m:
                            try:
                                spec = json.loads(m.group(1))
                                final_blocks.append({"type": "chart", "title": spec.get("title"), "sub": spec.get("subtitle", ""), "body": chart_body(spec)})
                                run.emit(final_blocks[-1] | {"late": True})
                            except ValueError:
                                final_blocks.append({"type": "text", "text": piece})
                        elif piece.strip():
                            final_blocks.append({"type": "text", "text": piece})
                else:
                    final_blocks.append(b)
            text_all = "\n\n".join(b["text"] for b in final_blocks if b["type"] == "text")
            secs = time.time() - t_start
            stats = {"seconds": round(secs, 1), "tps": round(out_chars["n"] / 4 / secs, 1) if secs > 0 and out_chars["n"] else None}
            run.emit({"type": "stats", **stats})
            M.add_msg(self.db, run.chat_id, "assistant", {"text": text_all, "blocks": final_blocks, "llm": llm, "model": f"{p.name} · {model}",
                                                          "stopped": run.stop.is_set(), "stats": stats})
        except P.ProviderError as e:
            run.emit({"type": "error", "text": str(e)})
            flush_text()
            M.add_msg(self.db, run.chat_id, "assistant", {"text": cur_text["t"], "blocks": blocks, "error": str(e), "model": f"{p.name} · {model}"})
        except Exception as e:
            traceback.print_exc()
            run.emit({"type": "error", "text": f"{type(e).__name__}: {e}"})
            M.add_msg(self.db, run.chat_id, "assistant", {"text": "", "blocks": blocks, "error": str(e), "model": f"{p.name} · {model}"})
        finally:
            run.done = True
            run.emit({"type": "done"})

    def complete(self, prompt: str, max_tokens: int = 1500) -> str:
        """One short answer from the chosen model, no tools (used by the importer to read unsure files)."""
        c = self.cfg()
        p = self.provider(c["provider"]) if c["provider"] else None
        if p is None or (p.needs_key and not self.key(p.id)):
            raise RuntimeError("No AI model is connected.")
        model = c["model"] or (self._models_for(p) or [""])[0]
        r = P.chat(p, self.key(p.id), model, [{"role": "user", "content": prompt}], effort="low",
                   account=self.account(p.id), timeout=240, max_tokens=max_tokens)
        return r.text

    def ready(self) -> bool:
        c = self.cfg()
        p = self.provider(c["provider"]) if c["provider"] else None
        return bool(p) and (not p.needs_key or bool(self.key(p.id))) and (p.id != "offline" or local.SERVER.status()["running"])

    def warmup(self):
        """After an offline model is loaded: read it into memory and pre-fill the prompt cache with the fixed
        instructions and tools, so the first real question is answered quickly."""
        def go():
            for _ in range(600):
                st = local.SERVER.status()
                if st["ready"] or not st["running"]:
                    break
                time.sleep(0.5)
            if not local.SERVER.status()["ready"]:
                return
            p = self.provider("offline")
            core = {"data_overview", "screen", "drill", "find", "item_status", "supplier_status", "sql", "recall", "remember",
                    "chart", "make_report", "add_promotion"}
            tools = [{k: v for k, v in t.items() if k != "write"} for t in tool_specs() if t["name"] in core]
            try:
                P.chat(p, "", local.SERVER.status()["model"], [{"role": "system", "content": self._system({"role": (self.db.setting("view") or {}).get("role") or "ho"}, True)},
                                                                {"role": "user", "content": "Reply OK."}],
                       tools=tools, effort="low", max_tokens=1, timeout=600)
            except Exception:
                pass
        threading.Thread(target=go, daemon=True).start()

    # ------------------------------------------------------------------------------ reports & digests
    def _report(self, spec: dict) -> list[dict]:
        host = self.api.host
        return R.write_report(spec, exports_dir() / "Reports", getattr(host, "html_to_pdf", None), getattr(host, "svg_to_png", None))

    def import_attachment(self, aid: str) -> dict:
        a = self.attach.get(aid)
        if not a:
            return {"error": "That file is no longer available; attach it again."}
        self.api.imp.add(paths=[a["path"]])
        return {"ok": True}

    def digest(self, results: list[dict]):
        """After every import: remember what arrived and the headline numbers, so the agent can recall history."""
        try:
            ok = [r for r in results if r.get("ok")]
            if not ok:
                return
            lines = [f"Imported {len(ok)} sheet(s): " + "; ".join(f"{r['type']} ({r['file']}): {r['summary']}" for r in ok[:12])]
            from stockcompass.analytics import core as A
            kp, ins = A.overview(self.db, A.Scope())
            lines.append("Headline after import: " + "; ".join(f"{k.label} {k.value if not isinstance(k.value, float) else round(k.value, 1)} ({k.sub})" for k in kp if k.value is not None))
            if ins:
                lines.append("Signals: " + "; ".join(i["title"] for i in ins[:6]))
            M.remember(self.db, "\n".join(lines), "digest", "import", "auto")
        except Exception:
            traceback.print_exc()


def _summary(name: str, r: dict) -> str:
    if not isinstance(r, dict):
        return ""
    if r.get("error"):
        return str(r["error"])[:160]
    if name == "sql":
        return f"{len(r.get('rows') or [])} rows"
    if name in ("screen",):
        return (r.get("title") or "") + (f" · {r.get('scope')}" if r.get("scope") else "")
    if name == "drill":
        return f"{r.get('metric')} by {r.get('grouped_by')}: {r.get('total_rows')} rows"
    if name == "find":
        return f"{len(r.get('results') or [])} matches"
    if name == "item_status":
        it = r.get("item") or {}
        return f"{it.get('item', '')} {it.get('description', '')}".strip() or ("several matches" if r.get("several_matches") else "")
    if name == "recall":
        return f"{len(r.get('memories') or [])} memories"
    if name == "make_report":
        return ", ".join(r.get("created") or [])
    if r.get("declined"):
        return "not approved"
    if r.get("ok"):
        return "done"
    return ""
