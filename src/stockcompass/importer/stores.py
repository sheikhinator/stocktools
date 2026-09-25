"""Matching any store reference in any report to the one true store identity: the GIMA code.

Reports refer to stores in many ways:
  "504", "P03", "pa6"                       GIMA codes (the only reliable identity)
  "651 LAH Fortress", "660 LAH Askari 10"   corporate code + city + name (corporate codes are NOT unique)
  "HM PK LAH Fortress", "SM PK ISL D12 (P06)", "H&B PK LAH Packages Mall", "HB ... EMP (MYLI)"
  "FOR", "DHA11", "FRT_MYLI", "DHA 07_MYLI"  scorecard short names
  "MYLI Phase 7", "Lyallpur"                  DP workbook names
  "652 LAH High Street Paragon Ci"            names cut off by the report

How it decides: learned aliases first (confirmed by a user once), then GIMA code, a GIMA code in
brackets, exact alias, then token similarity with prefix matching for cut-off names. A Myli marker
(H&B, HB, MYLI) must agree with the store format, so "DHA Rahbar" and "H&B DHA Rahbar" never mix up.
Closed stores and non-store channels are recognised and reported as such, never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from stockcompass.master.seed import CITY_TOKENS, NON_STORES, STORES

NOISE = {"HM", "SM", "PK", "PAK", "PAKISTAN", "MALL", "THE", "STORE", "HYPER", "SUPER", "HYPERMARKET",
         "SUPERMARKET", "CARREFOUR", "MAF", "CITY", "GALLERIA"}
MYLI_MARKERS = {"MYLI", "HB", "H&B", "H & B", "HANDB"}


@dataclass
class StoreMatch:
    code: str | None
    confidence: float
    kind: str = "store"      # store | closed | channel | unknown
    reason: str = ""
    name: str = ""


def _tokens(s: str) -> tuple[list[str], bool, str | None]:
    """Normalised tokens, Myli flag, GIMA code found inside brackets."""
    raw = s.upper().replace("_", " ").replace("-", " ").replace(".", " ")
    myli = bool(re.search(r"\bMYLI\b|\bH\s*&\s*B\b|\bHB\b", raw))
    bracket = None
    m = re.search(r"\(([A-Z]{1,2}\d{1,2}|\d{3})\)", raw)
    if m:
        bracket = m.group(1)
    raw = re.sub(r"\(.*?\)", " ", raw)
    raw = raw.replace("&", " ")
    toks = [t for t in re.split(r"[^A-Z0-9]+", raw) if t]
    # drop a leading 3-digit corporate code
    if toks and re.fullmatch(r"\d{3}", toks[0]) and len(toks) > 1:
        toks = toks[1:]
    toks = [t for t in toks if t not in NOISE and t not in CITY_TOKENS and t not in {"MYLI", "HB", "H", "B"}]
    # normalise numbers: "07" -> "7", "011" -> "11"
    toks = [str(int(t)) if t.isdigit() else t for t in toks]
    return toks, myli, bracket


def _sim(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    inter = len(sa & sb)
    # prefix credit for cut-off names ("CI" -> "CITY", "PHASE" in "PH")
    for x in sa - sb:
        if any(y.startswith(x) or x.startswith(y) for y in sb - sa if min(len(x), len(y)) >= 2):
            inter += 0.8
    return inter / max(len(sa), len(sb))


class StoreResolver:
    def __init__(self, stores: list[dict] | None = None, learned: dict[str, str] | None = None,
                 non_stores: list[dict] | None = None):
        self.stores = stores if stores is not None else STORES
        self.non_stores = non_stores if non_stores is not None else NON_STORES
        self.learned = {k.upper().strip(): v for k, v in (learned or {}).items()}
        self.by_code = {s["code"].upper(): s for s in self.stores}
        self._index = []
        for s in self.stores:
            names = [s["name"], s.get("short", "")] + list(s.get("aliases", []))
            for n in names:
                if n:
                    toks, myli, _ = _tokens(n)
                    self._index.append((s, toks, myli or s["format"] == "M", n))
        self._non = []
        for s in self.non_stores:
            for n in [s["name"]] + list(s.get("aliases", [])):
                toks, myli, _ = _tokens(n)
                self._non.append((s, toks, myli or s.get("format") == "M"))
        self._cache: dict[str, StoreMatch] = {}

    def resolve(self, ref) -> StoreMatch:
        if ref is None:
            return StoreMatch(None, 0, "unknown", "empty")
        key = str(ref).strip()
        if isinstance(ref, float) and ref.is_integer():
            key = str(int(ref))
        if not key:
            return StoreMatch(None, 0, "unknown", "empty")
        k = key.upper()
        if k in self._cache:
            return self._cache[k]
        m = self._resolve(key)
        self._cache[k] = m
        return m

    def _resolve(self, key: str) -> StoreMatch:
        k = re.sub(r"\s+", " ", key.upper()).strip()
        if k in self.learned:
            code = self.learned[k]
            return StoreMatch(code, 1.0, "store", "confirmed before", self._name(code))
        if k in self.by_code:
            return StoreMatch(self.by_code[k]["code"], 1.0, "store", "GIMA code", self.by_code[k]["name"])
        if k.startswith("GIMA") and k[4:] in self.by_code:          # GIMA500, GIMAP09 user ids
            return StoreMatch(self.by_code[k[4:]]["code"], 0.9, "store", "GIMA user code", self.by_code[k[4:]]["name"])
        toks, myli, bracket = _tokens(key)
        if bracket and bracket in self.by_code:
            return StoreMatch(bracket, 1.0, "store", "GIMA code in brackets", self._name(bracket))
        # a GIMA code as one of the words ("FRT_500", "DHA07_MYLI_PD4"); corporate codes never collide
        raw_toks = [t for t in re.split(r"[^A-Z0-9]+", k) if t]
        hits = {t for t in raw_toks if t in self.by_code and (self.by_code[t]["format"] == "M") == myli}
        if len(hits) == 1:
            c = hits.pop()
            return StoreMatch(self.by_code[c]["code"], 0.95, "store", "GIMA code in the name", self.by_code[c]["name"])
        # exact alias
        best, best_s, best_n = None, 0.0, ""
        for s, atoks, amyli, n in self._index:
            if amyli != myli:
                continue
            sc = _sim(toks, atoks)
            if sc > best_s or (sc == best_s and best is not None and len(atoks) > len(best_n)):
                best, best_s, best_n = s, sc, n
        non_best, non_s = None, 0.0
        for s, atoks, amyli in self._non:
            if amyli != myli:
                continue
            sc = _sim(toks, atoks)
            if sc > non_s:
                non_best, non_s = s, sc
        if non_best is not None and non_s >= 0.99 and non_s >= best_s:
            return StoreMatch(None, non_s, non_best["kind"], f"{non_best['kind']} ({non_best['name']})", non_best["name"])
        if best is not None and best_s >= 0.5:
            return StoreMatch(best["code"], round(min(1.0, best_s), 2), "store", f"name match: {best_n}", best["name"])
        if non_best is not None and non_s >= 0.6:
            return StoreMatch(None, non_s, non_best["kind"], f"{non_best['kind']} ({non_best['name']})", non_best["name"])
        return StoreMatch(None, 0.0, "unknown", "no match")

    def _name(self, code: str) -> str:
        s = self.by_code.get(code.upper())
        return s["name"] if s else code

    def format_of(self, code: str) -> str:
        s = self.by_code.get((code or "").upper())
        return s["format"] if s else ""
