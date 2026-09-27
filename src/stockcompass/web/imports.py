"""Import jobs for the web screens: analyse files in the background, let the user review, then commit.

The screen polls `status()` while a job runs, so nothing here blocks the window.
"""

from __future__ import annotations

import threading
import traceback
from datetime import date
from pathlib import Path

from stockcompass.analytics.core import L
from stockcompass.db import Database
from stockcompass.importer.pipeline import FilePlan, analyze, commit
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
                with self._lock:
                    self.plans.append(plan)
            self.msg = ""

        return self._run(work)

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
                outs += commit(plan, self.db, progress=prog)
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
            plans = [dict(pid=i, file=p.path.name, warnings=p.warnings[:5],
                          date=p.workbook_date.isoformat() if p.workbook_date else None,
                          sheets=[dict(si=j, sheet=sp.sheet.name, kind=sp.sheet.kind, chosen=sp.chosen,
                                       name=sp.spec_name, conf=round(sp.confidence * 100),
                                       rows=sp.sheet.n_rows, hidden=sp.sheet.hidden,
                                       store=sp.store, store_source=sp.store_source, needs_store=sp.needs_store,
                                       date=sp.snapshot_date.isoformat() if sp.snapshot_date else None,
                                       already=bool(sp.already_imported), reason=sp.reason,
                                       options=[dict(k=d.spec.key, n=d.spec.name, c=round(d.confidence * 100))
                                                for d in sp.detections[:6]])
                                  for j, sp in enumerate(p.sheets)]) for i, p in enumerate(self.plans)]
        return dict(busy=self.busy, progress=self.progress, msg=self.msg, error=self.error, plans=plans,
                    results=self.results, done=self.done_count)
