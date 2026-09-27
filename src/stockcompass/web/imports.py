"""Import jobs for the web screens: analyse files in the background, let the user review, then commit.

The screen polls `status()` while a job runs, so nothing here blocks the window.
"""

from __future__ import annotations

import json
import threading
import traceback
from datetime import date
from pathlib import Path

from stockcompass.analytics.core import L
from stockcompass.db import Database
from stockcompass.importer.pipeline import FilePlan, analyze, commit
from stockcompass.importer import understand as U
from stockcompass.importer.spec import REGISTRY

EXTS = (".xlsx", ".xlsm", ".xls", ".xlsb", ".csv", ".txt", ".tsv", ".htm", ".html", ".ods")


def expand(paths: list[str]) -> list[str]:
    """Folders become the report files inside them."""
    out = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            out += sorted(str(x) for x in pp.rglob("*") if x.suffix.lower() in EXTS)
        elif pp.exists():
            out.append(str(pp))
    return out


class ImportJobs:
    def __init__(self, db: Database):
        self.db = db
        self.plans: list[FilePlan] = []
        self.busy = False
        self.progress = 0.0
        self.msg = ""
        self.error = ""
        self.results: list[dict] = []
        self.done_count = 0          # goes up after every commit so the screen knows to reload
        self.on_done = None          # called with the results after a commit (the agent's memory digest)
        self.ai_fn = None            # prompt -> text, set when an AI model is connected (helps with unsure sheets)
        self.ai_state = {"running": False, "msg": "", "error": ""}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ jobs
    def _run(self, fn):
        if self.busy:
            return False
        self.busy, self.progress, self.error = True, 0.0, ""

        def wrap():
            try:
                fn()
            except Exception as e:  # shown on screen, never a crash
                self.error = f"{e}"
                traceback.print_exc()
            finally:
                self.busy = False
                self.progress = 1.0

        threading.Thread(target=wrap, daemon=True).start()
        return True

    def add(self, paths: list[str] | None = None, text: str | None = None):
        files = expand(paths or [])

        def work():
            self.results = []
            if text:
                self.msg = L("Reading pasted data", "پیسٹ شدہ ڈیٹا پڑھ رہے ہیں")
                plan = analyze("Pasted data", self.db, text=text)
                with self._lock:
                    self.plans.append(plan)
            for i, p in enumerate(files):
                self.msg = Path(p).name
                self.progress = i / max(1, len(files))
                try:
                    plan = analyze(p, self.db)
                except Exception as e:
                    self.results.append(dict(ok=False, file=Path(p).name, sheet="", type="",
                                             summary=L(f"Could not open: {e}", f"نہیں کھلی: {e}"), notes=[]))
                    continue
                known = (self.db.learned("import_hint") or {}).get(U.name_key(plan.path.name).upper())
                if known:                      # the user described a file like this before
                    U.apply_hint(plan, known)
                with self._lock:
                    self.plans.append(plan)
            self.msg = ""
            if self.ai_fn and self.db.setting("ai_import") is not False:
                self._ai_pass(None)

        return self._run(work)

    # ------------------------------------------------------------------ understanding
    def set_hint(self, pid: int, hint: str):
        with self._lock:
            plan = self.plans[pid]
        changes = U.apply_hint(plan, hint)
        if hint.strip():
            self.db.learn("import_hint", U.name_key(plan.path.name), hint.strip()[:200])
        if self.ai_fn:
            self.ai_check(pid)
        return {**self.status(), "changed": changes}

    def ai_check(self, pid: int | None = None, force: bool = False):
        if not self.ai_fn:
            return {**self.status(), "error": "Connect an AI model in the Agent tab to let it read unsure files."}
        if self.ai_state["running"]:
            return self.status()
        threading.Thread(target=self._ai_pass, args=(pid, force), daemon=True).start()
        return self.status()

    def _ai_pass(self, pid: int | None, force: bool = False):
        self.ai_state.update(running=True, error="", msg="")
        try:
            resolver = self.db.resolver()
            plans = [self.plans[pid]] if pid is not None and pid < len(self.plans) else list(self.plans)
            for plan in plans:
                for sp in plan.sheets:
                    unsure = sp.chosen == "generic" or sp.confidence < 0.75 or force
                    if not unsure or getattr(sp, "ai", None) and not force or (sp.chosen == "skip" and sp.reason.startswith("empty")):
                        continue
                    self.ai_state["msg"] = f"AI is reading {plan.path.name} / {sp.sheet.name}"
                    try:
                        ans = U.ask_ai(self.ai_fn, plan.path.name, sp.sheet, getattr(plan, "hint", ""))
                        with self._lock:
                            U.apply_ai(sp, ans, resolver)
                    except Exception as e:
                        self.ai_state["error"] = str(e)[:300]
        finally:
            self.ai_state.update(running=False, msg="")

    def run(self):
        missing = [f"{p.path.name} / {sp.sheet.name}" for p in self.plans for sp in p.sheets
                   if sp.chosen != "skip" and sp.needs_store and not sp.store]
        if missing:
            return dict(ok=False, missing=missing)
        plans = list(self.plans)

        def work():
            outs = []
            for i, plan in enumerate(plans):
                def prog(f, m, i=i):
                    self.progress = (i + f) / max(1, len(plans))
                    self.msg = m
                got = commit(plan, self.db, progress=prog)
                outs += got
                by_sheet = {sp.sheet.name: sp for sp in plan.sheets}
                for o in got:
                    sp = by_sheet.get(o.sheet)
                    ai = getattr(sp, "ai", None) or {}
                    hint = getattr(plan, "hint", "")
                    if o.import_id and (hint or ai):
                        self.db.execute("INSERT INTO import_notes VALUES (?,?,?,?,?,?,?)",
                                        [o.import_id, o.file, o.sheet, hint, ai.get("what_it_is") or "",
                                         json.dumps(ai.get("columns") or {}), "AI" if ai else "user"])
            with self._lock:
                self.plans = []
            self.results = [dict(ok=o.status == "ok", file=o.file, sheet=o.sheet,
                                 type=REGISTRY[o.report_type].name if o.report_type in REGISTRY else o.report_type,
                                 rows=o.rows, summary=o.summary,
                                 notes=[f.message + (f" ({f.count:,})" if f.count else "") for f in o.findings
                                        if f.level in ("warn", "error")][:8]) for o in outs]
            self.done_count += 1
            self.msg = ""
            if self.on_done:
                try:
                    self.on_done(self.results)
                except Exception:
                    traceback.print_exc()

        return dict(ok=self._run(work))

    # ------------------------------------------------------------------ review
    def set(self, pid: int, si: int, chosen: str | None = None, store: str | None = None, day: str | None = None):
        with self._lock:
            sp = self.plans[pid].sheets[si]
            if chosen is not None:
                sp.chosen = chosen
                spec = REGISTRY.get(chosen)
                sp.needs_store = bool(spec and spec.needs_store)
            if store is not None:
                sp.store, sp.store_source = (store or None), "you"
            if day is not None:
                sp.snapshot_date = date.fromisoformat(day) if day else None
        return self.status()

    def remove(self, pid: int):
        with self._lock:
            if 0 <= pid < len(self.plans):
                self.plans.pop(pid)
        return self.status()

    def clear(self):
        with self._lock:
            self.plans = []
            self.results = []
        return self.status()

    def status(self) -> dict:
        with self._lock:
            plans = [dict(pid=i, file=p.path.name, warnings=p.warnings[:5], hint=getattr(p, "hint", ""),
                          date=p.workbook_date.isoformat() if p.workbook_date else None,
                          sheets=[dict(si=j, sheet=sp.sheet.name, kind=sp.sheet.kind, chosen=sp.chosen,
                                       name=sp.spec_name, conf=round(sp.confidence * 100),
                                       rows=sp.sheet.n_rows, hidden=sp.sheet.hidden,
                                       store=sp.store, store_source=sp.store_source, needs_store=sp.needs_store,
                                       date=sp.snapshot_date.isoformat() if sp.snapshot_date else None,
                                       already=bool(sp.already_imported), reason=sp.reason,
                                       ai=({k: (getattr(sp, "ai") or {}).get(k) for k in ("what_it_is", "confidence", "notes", "report_type")}
                                           | {"columns": len((getattr(sp, "ai") or {}).get("columns") or {})}) if getattr(sp, "ai", None) else None,
                                       options=[dict(k=d.spec.key, n=d.spec.name, c=round(d.confidence * 100))
                                                for d in sp.detections[:6]])
                                  for j, sp in enumerate(p.sheets)]) for i, p in enumerate(self.plans)]
        return dict(busy=self.busy, progress=self.progress, msg=self.msg, error=self.error, plans=plans,
                    results=self.results, done=self.done_count, ai_ready=bool(self.ai_fn), ai=dict(self.ai_state))
