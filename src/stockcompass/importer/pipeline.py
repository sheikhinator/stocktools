"""Import pipeline: look at a file, propose what each sheet is, then load it into the snapshot database.

analyze(path)  -> FilePlan   (no database writes; shown in the import screen for review)
commit(plan)   -> outcomes   (parses and loads each chosen sheet, with progress and findings)
"""

from __future__ import annotations

import os
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from stockcompass.db import Database
from stockcompass.master.seed import BC_INDICATORS

from . import parsers  # noqa: F401  (registers all report types)
from .grid import non_empty, norm
from .parsers.common import date_from_filename, store_from_filename
from .parsers.dp import workbook_date_hint
from .parsers.generic import parse_generic
from .reader import Sheet, Workbook, from_text, open_file
from .spec import REGISTRY, Detection, Finding, ParseContext, detect

MIN_CONFIDENCE = 0.5


@dataclass
class SheetPlan:
    sheet: Sheet
    detections: list[Detection]
    chosen: str                  # spec key | "generic" | "skip"
    confidence: float
    store: str | None = None
    store_source: str = ""
    snapshot_date: date | None = None
    needs_store: bool = False
    already_imported: int | None = None
    reason: str = ""

    @property
    def spec_name(self) -> str:
        if self.chosen in REGISTRY:
            return REGISTRY[self.chosen].name
        return {"generic": "Unrecognised table (kept as rows)", "skip": "Skip"}.get(self.chosen, self.chosen)


@dataclass
class FilePlan:
    path: Path
    workbook: Workbook
    sheets: list[SheetPlan]
    workbook_date: date | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class Outcome:
    file: str
    sheet: str
    report_type: str
    import_id: int | None
    rows: int
    status: str                  # ok | failed | skipped
    summary: str
    findings: list[Finding]
    snapshot_date: date | None = None
    stores: list[str] = field(default_factory=list)


def _looks_like_data(sheet: Sheet) -> bool:
    rows = [r for r in sheet.head if non_empty(r)]
    return len(rows) >= 4


def analyze(path: str | Path, db: Database, text: str | None = None) -> FilePlan:
    wb = from_text(text, str(path)) if text is not None else open_file(path)
    resolver = db.resolver()
    today = date.today()
    heads = ["\n".join(" ".join(str(c) for c in r if c not in (None, "")) for r in s.head[:12]) for s in wb.sheets]
    wdate = workbook_date_hint(heads, today)
    visible_headers = {}
    for s in wb.sheets:
        if s.kind != "pivot":
            for r in s.head[:40]:
                ne = non_empty(r)
                if len(ne) >= 4:
                    visible_headers.setdefault(tuple(norm(r[j]) for j in ne), s.name)
    plans = []
    for s in wb.sheets:
        dets = detect(s)
        best = dets[0] if dets else None
        if best and best.confidence >= MIN_CONFIDENCE:
            chosen, conf, reason = best.spec.key, best.confidence, "recognised: " + ", ".join(best.evidence[:5])
        elif _looks_like_data(s):
            chosen, conf, reason = "generic", best.confidence if best else 0.0, "not recognised; rows will be kept"
        else:
            chosen, conf, reason = "skip", 0.0, "empty or too small"
        if s.kind == "pivot" and s.head:
            key = tuple(norm(v) for v in s.head[0] if v not in (None, ""))
            if key in visible_headers:
                chosen, reason = "skip", f"same data as sheet '{visible_headers[key]}'"
        sp = SheetPlan(sheet=s, detections=dets, chosen=chosen, confidence=conf, reason=reason)
        spec = REGISTRY.get(chosen)
        if spec and spec.needs_store:
            sp.needs_store = True
            st = store_from_filename(f"{Path(str(path)).stem} {s.name}", resolver)
            if st:
                sp.store, sp.store_source = st, "file name"
        sp.already_imported = db.already_imported(wb.file_hash, s.name)
        plans.append(sp)
    return FilePlan(path=Path(str(path)), workbook=wb, sheets=plans, workbook_date=wdate, warnings=list(wb.warnings))


def commit(plan: FilePlan, db: Database, progress: Callable[[float, str], None] | None = None,
           replace_existing: bool = True) -> list[Outcome]:
    out: list[Outcome] = []
    todo = [sp for sp in plan.sheets if sp.chosen != "skip"]
    resolver = db.resolver()
    settings = {k: db.setting(k) for k in ("bad_snapshot_drop_pct", "vat_rate")}
    settings["workbook_date"] = plan.workbook_date
    try:
        fdate = datetime.fromtimestamp(os.path.getmtime(plan.path)).date() if plan.path.exists() else None
    except OSError:
        fdate = None
    for n, sp in enumerate(todo):
        def tick(frac, msg="", n=n):
            if progress:
                progress((n + max(0.0, min(1.0, frac))) / max(1, len(todo)), f"{sp.sheet.name}: {msg}")

        tick(0, "reading")
        spec = REGISTRY.get(sp.chosen)
        ctx = ParseContext(resolver=resolver, ref_date=date.today(), store=sp.store, snapshot_date=sp.snapshot_date,
                           file_name=plan.path.name, file_date=fdate, progress=tick, settings=settings)
        try:
            fn = spec.parse if (spec and spec.analysed and spec.parse) else parse_generic
            res = fn(sp.sheet, ctx)
        except Exception as e:  # a parser bug must never lose the rest of the file
            out.append(Outcome(plan.path.name, sp.sheet.name, sp.chosen, None, 0, "failed",
                               f"Could not read this sheet: {e}",
                               [Finding("error", "crash", str(e), detail=traceback.format_exc())]))
            continue
        errors = [f for f in res.findings if f.level == "error"]
        if errors and res.row_count == 0:
            out.append(Outcome(plan.path.name, sp.sheet.name, sp.chosen, None, 0, "failed",
                               errors[0].message, res.findings))
            continue
        tick(0.7, "saving")
        stores = sorted(res.stores)
        with db.lock:
            db.con.execute("BEGIN")
            try:
                iid = db.new_import(file_name=plan.path.name, file_hash=plan.workbook.file_hash, sheet=sp.sheet.name,
                                    report_type=sp.chosen, confidence=sp.confidence, snapshot_date=res.snapshot_date,
                                    period_from=res.period_from, period_to=res.period_to, stores=",".join(stores))
                total = 0
                for table, rows in res.tables.items():
                    if table.startswith("_") or not rows:
                        continue
                    for r in rows:
                        r["import_id"] = iid
                    db.insert_rows(table, rows)
                    total += len(rows)
                db.upsert_items(res.items, res.snapshot_date)
                db.upsert_suppliers(res.suppliers)
                _learn(db, res, sp.chosen)
                for f in res.findings:
                    db.con.execute("INSERT INTO findings VALUES (?,?,?,?,?,?)",
                                   [iid, f.level, f.code, f.message, f.count, f.detail[:4000] if f.detail else None])
                replaced = []
                if replace_existing:
                    replaced = db.supersede(iid, sp.chosen, stores, res.snapshot_date, res.period_from, res.period_to,
                                              res.variant)
                summary = res.summary + (f" (replaced {len(replaced)} earlier import)" if replaced else "")
                db.finish_import(iid, total, "ok", summary)
                db.con.execute("COMMIT")
            except Exception as e:
                db.con.execute("ROLLBACK")
                out.append(Outcome(plan.path.name, sp.sheet.name, sp.chosen, None, 0, "failed",
                                   f"Could not save: {e}", res.findings + [Finding("error", "save", str(e),
                                                                                   detail=traceback.format_exc())]))
                continue
        tick(1.0, "done")
        out.append(Outcome(plan.path.name, sp.sheet.name, sp.chosen, iid, total, "ok", summary, res.findings,
                           res.snapshot_date, stores))
    return out


def _learn(db: Database, res, report_type: str):
    """Keep what files teach us: DP provision steps and BC targets as the BC team sets them."""
    obs = res.tables.get("_dp_rules_observed") or []
    changed = []
    for o in obs:
        cur = db.one("SELECT pct FROM dp_rules WHERE rule_key=? AND from_day=?", [o["rule_key"], o["from_day"]])
        if cur is None or abs(cur - o["pct"]) > 0.01:
            changed.append(f"{o['rule_key']} from day {o['from_day']}: {cur if cur is not None else '-'}% -> {o['pct']:.0f}%")
            db.con.execute("INSERT OR REPLACE INTO dp_rules VALUES (?,?,?,?)",
                           [o["rule_key"], o["from_day"], o["pct"], f"learned from DP master ({o['n']} items)"])
    if changed:
        res.info("dp_rules_learned", "Provision rules updated from this file: " + "; ".join(changed[:15]), len(changed))
    for f in res.tables.get("_families") or []:
        if f["code"] and f["name"]:
            db.con.execute("INSERT OR REPLACE INTO families VALUES (?,?,?)", [f["code"], f["section"] or "", f["name"]])
    tg = res.tables.get("_bc_targets_file") or []
    tchanged = []
    for t in tg:
        if not t["format"]:
            continue
        cur = db.one("SELECT target FROM bc_targets WHERE indicator=? AND format=?", [t["indicator"], t["format"]])
        if cur is None or abs(cur - t["target"]) > 0.001:
            lo = next((i["lo"] for i in BC_INDICATORS if i["key"] == t["indicator"]), True)
            db.con.execute("INSERT OR REPLACE INTO bc_targets VALUES (?,?,?,?)", [t["indicator"], t["format"], t["target"], lo])
            tchanged.append(f"{t['indicator']} ({t['format']}): {cur} -> {t['target']:g}")
    if tchanged:
        res.info("targets_updated", "BC targets taken from this scorecard: " + "; ".join(tchanged[:12]), len(tchanged))


def import_files(paths: list[str | Path], db: Database, progress=None) -> list[Outcome]:
    """Convenience for scripts/tests: analyse and import with the automatic choices."""
    outs = []
    for i, p in enumerate(paths):
        plan = analyze(p, db)
        outs += commit(plan, db, progress=(lambda f, m, i=i: progress((i + f) / len(paths), m)) if progress else None)
    return outs
