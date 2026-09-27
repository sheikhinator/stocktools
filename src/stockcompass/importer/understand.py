"""Help the importer understand files it is not sure about.

1. The user's one-line description ("DP report for September", "zero stock sheet Packages") re-ranks the report types.
   It is remembered for files with a similar name.
2. When an AI model is connected, it looks at the first rows of an unsure sheet and says what the report is,
   which store and date it covers and what each column means. The answer is checked against the known report
   types; the columns' meanings are kept so the agent can use even unrecognised tables.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from .spec import REGISTRY

SYNONYMS = {
    "zero": ["zero stock", "oos", "out of stock", "empty", "0 stock", "availability"],
    "negative": ["negative", "minus stock", "-ve"],
    "dp": ["dp", "depreciation", "provision", "aged", "ageing", "aging", "old stock"],
    "lpo": ["lpo", "purchase order", "orders", "po list", "grn", "purge", "purged"],
    "sales": ["sales", "turnover", "revenue", "11b", "11f", "benchmark", "net sales", "budget"],
    "leaflet": ["leaflet", "promo", "promotion", "theme", "catalogue", "offer"],
    "blocked": ["blocked", "007", "block"],
    "bc": ["bc", "scorecard", "business cycle", "indicator", "kpi"],
    "realtime": ["realtime", "real time", "stock on hand", "soh", "item master", "stock report"],
    "family": ["family", "families"],
}


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def hint_scores(hint: str) -> dict[str, float]:
    """0..1 match between the user's description and every report type."""
    h = (hint or "").lower()
    if not h.strip():
        return {}
    hw = _words(h)
    groups = {g for g, syns in SYNONYMS.items() if any(sy in h for sy in syns)}
    out = {}
    for key, spec in REGISTRY.items():
        text = f"{spec.key} {spec.name} {spec.source} {spec.description or ''}".lower()
        sw = _words(text)
        score = len(hw & sw) / max(3, len(hw))
        score += 0.5 * sum(1 for g in groups if any(sy in text for sy in SYNONYMS[g]))
        if spec.source.lower() in h:
            score += 0.2
        out[key] = min(1.0, score)
    return out


def apply_hint(plan, hint: str) -> list[str]:
    """Re-rank each sheet's report type with the description. Returns what changed (for the screen)."""
    changes = []
    scores = hint_scores(hint)
    plan.hint = hint
    if not scores:
        return changes
    for sp in plan.sheets:
        if sp.chosen == "skip" and sp.reason.startswith("empty"):
            continue
        base = {d.spec.key: d.confidence for d in sp.detections}
        best_key, best = sp.chosen, base.get(sp.chosen, 0.0) + 0.35 * scores.get(sp.chosen, 0.0)
        for key, conf in base.items():
            val = conf + 0.35 * scores.get(key, 0.0)
            if val > best + 0.05 and conf >= 0.15:
                best_key, best = key, val
        if best_key != sp.chosen and best_key in REGISTRY:
            changes.append(f"{sp.sheet.name}: {REGISTRY[best_key].name}")
            sp.chosen, sp.confidence = best_key, min(0.99, best)
            sp.reason = f"matched your description: '{hint}'"
            sp.needs_store = REGISTRY[best_key].needs_store
    return changes


def name_key(file_name: str) -> str:
    """'DP report 26-09-2026 (3).xlsx' -> 'dp report' so the description is reused for next month's file."""
    stem = Path(file_name).stem.lower()
    stem = re.sub(r"\(\d+\)|\d+", " ", stem)
    return " ".join(re.findall(r"[a-z]+", stem))[:60]


# ------------------------------------------------------------------------------------------------ AI
def _sample(sheet, rows: int = 25, width: int = 30) -> str:
    out = []
    for r in sheet.head[:rows]:
        cells = ["" if v is None else str(v)[:40] for v in r[:width]]
        if any(cells):
            out.append("\t".join(cells))
    return "\n".join(out)[:9000]


def catalogue() -> str:
    return "\n".join(f"- {k}: {s.name} ({s.source}). {s.description or ''} Key columns: {', '.join(list(s.tokens)[:10])}"
                     for k, s in sorted(REGISTRY.items()))


PROMPT = """You help a retail data tool (Carrefour Pakistan: GIMA, BO, BC, DP, LPO and leaflet reports) read a spreadsheet.
Known report types:
{catalogue}

File: {file}
Sheet: {sheet}
The user describes the file as: {hint}
First rows (tab separated):
{sample}

Answer with ONE JSON object only, no other text:
{{"report_type": "<one key from the list, or 'generic' if none fits, or 'skip' if it is not data>",
  "confidence": <0..1>, "what_it_is": "<one short line>", "store": "<store name or GIMA code if the whole sheet is one store, else null>",
  "date": "<YYYY-MM-DD the data is as of, or null>", "columns": {{"<header>": "<what it means>"}}, "notes": "<anything odd, or empty>"}}"""


def ask_ai(chat_fn: Callable[[str], str], file: str, sheet, hint: str = "") -> dict:
    text = chat_fn(PROMPT.format(catalogue=catalogue(), file=file, sheet=sheet.name, hint=hint or "(no description)",
                                 sample=_sample(sheet)))
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("The AI did not return an answer the importer could read.")
    raw = m.group(0)
    try:
        ans = json.loads(raw)
    except ValueError:
        ans = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))       # trailing commas from small models
    rt = str(ans.get("report_type") or "generic").strip()
    if rt not in REGISTRY and rt not in ("generic", "skip"):
        rt = "generic"
    ans["report_type"] = rt
    try:
        ans["confidence"] = max(0.0, min(1.0, float(ans.get("confidence") or 0)))
    except (TypeError, ValueError):
        ans["confidence"] = 0.5
    if not isinstance(ans.get("columns"), dict):
        ans["columns"] = {}
    return ans


def apply_ai(sp, ans: dict, resolver=None):
    """Use the AI's reading when it is sure enough, and keep its explanation either way."""
    from datetime import date
    sp.ai = ans
    rt = ans["report_type"]
    base = {d.spec.key: d.confidence for d in sp.detections}
    if rt in REGISTRY and (ans["confidence"] >= 0.6 or base.get(rt, 0) >= 0.2) and rt != sp.chosen and sp.confidence < 0.8:
        sp.chosen = rt
        sp.confidence = max(sp.confidence, min(0.95, ans["confidence"]))
        sp.needs_store = REGISTRY[rt].needs_store
        sp.reason = "AI: " + (ans.get("what_it_is") or REGISTRY[rt].name)
    elif rt == "skip" and ans["confidence"] >= 0.8 and sp.chosen == "generic":
        sp.chosen, sp.reason = "skip", "AI: " + (ans.get("what_it_is") or "not data")
    elif sp.chosen == "generic":
        sp.reason = "AI: " + (ans.get("what_it_is") or "unrecognised table; kept as rows with column meanings")
    if ans.get("store") and resolver is not None and not sp.store:
        m = resolver.resolve(ans["store"])
        if m and m.code:
            sp.store, sp.store_source = m.code, "AI"
    if ans.get("date") and not sp.snapshot_date:
        try:
            sp.snapshot_date = date.fromisoformat(str(ans["date"])[:10])
        except ValueError:
            pass
