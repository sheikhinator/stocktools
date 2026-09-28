"""Any other table: understood column by column and kept as a dataset the screens can use.

Nothing is thrown away. The table is found, and each column gets a role from its header and its values:
store (matched to the GIMA code like every report), item code, supplier, department / section / family, date,
coordinates / address / city, an amount (money, quantity, percent) or a label. Rows are kept with the store, item,
supplier and date pulled out, so the new data appears on the Other data page, in item and supplier cards, in
Analyse and for the agent, filtered like everything else. Tables with the same columns are the same dataset: a
newer file for the same store and date replaces the older one, other dates build up history.

Also learned from such files: item descriptions, supplier names, and locations of stores / suppliers (for the map).
A table with stores as column headers ("Item | Fortress | Emporium | …") is turned around into one row per store.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from ..grid import build_table, extract_meta, find_header, norm
from ..reader import Sheet
from ..spec import ParseContext, ParseResult
from ..values import (clean_text, code_text, dept_code, family_code, infer_date_format, is_missing, item_code,
                      parse_date, parse_num, pct_value, section_code)
from .common import choose_snapshot

MAX_RAW_ROWS = 300_000

ROLES = {"store": "Store", "item": "Item code", "description": "Item name", "supplier": "Supplier",
         "supplier_name": "Supplier name", "dept": "Department", "section": "Section", "family": "Family",
         "date": "Date", "lat": "Latitude", "lng": "Longitude", "address": "Address", "city": "City",
         "measure": "Amount", "label": "Label", "text": "Text", "ignore": "Ignore"}
KINDS = {"money": "PKR", "quantity": "Quantity", "percent": "Percent", "number": "Number"}

_H = [  # header words -> role (checked in order)
    ("lat", r"^(lat|latitude|y coord)"), ("lng", r"^(lng|lon|long|longitude|x coord)"),
    ("address", r"address|street|location detail|plot"), ("city", r"^(city|town|district|area city)$|\bcity\b"),
    ("supplier_name", r"(supplier|vendor|principal).*(name|desc)|^(supplier|vendor)\s*name"),
    ("supplier", r"\b(supplier|vendor|supp|principal|sup code|sup no)\b"),
    ("description", r"(item|article|product|sku).*(name|desc)|^description$|^desc$|^item description|^product$"),
    ("item", r"\b(item|article|sku|product code|art no|art\.? ?code|itm|material)\b"),
    ("store", r"\b(store|site|branch|outlet|shop|hyper|super|location|loc)\b"),
    ("family", r"\bfamily\b|\bfam\b"), ("section", r"\bsection\b|\bsect\b|^sec$"),
    ("dept", r"\b(dept|department|division)\b"),
]
_MEASURE = [("percent", r"%|\bpct\b|percent|\brate\b|ratio|\bshare\b|growth|achiev"),
            ("quantity", r"qty|quantity|\bunits?\b|pcs|pieces|cartons?|\bctn\b|\bcases?\b|\bnos\b"),
            ("money", r"value|amount|\bamt\b|sales|revenue|turnover|\bcost\b|price|pkr|\brs\b|budget|margin|provision|spend|"
                      r"gmv|\bnet\b|gross|profit|loss|waste|shrink|rebate|discount|payable|invoice|\bgrn\b"),
            ("quantity", r"qty|quantity|\bunits?\b|pcs|pieces|cartons?|\bctn\b|cases?|stock|soh|on ?hand|count|no\.? of|"
                         r"number of|facings?|orders?|lines|customers|footfall|visits|days")]


def _hk(h: str) -> str:
    return re.sub(r"[_\-/\.]+", " ", str(h or "").lower()).strip()


def dataset_key(cols: list[str]) -> str:
    sig = "|".join(sorted({norm(c) for c in cols if c and not str(c).startswith("Column")}))
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:12]


def profile_column(name: str, values: list, resolver) -> tuple[str, float]:
    """Guess what a column holds from its values. Returns (kind, confidence)."""
    vals = [v for v in values if v not in (None, "") and not is_missing(v)][:400]
    if not vals:
        return "empty", 1.0
    n = len(vals)
    strs = [clean_text(v) for v in vals]
    stores = sum(1 for s in strs[:150] if resolver.resolve(s).code)
    if stores / min(n, 150) >= 0.8:
        return "store", stores / min(n, 150)
    nums = [parse_num(v) for v in vals]
    numeric = [x for x in nums if x.value is not None]
    g = infer_date_format(vals)
    if g.fmt and g.parsed / n >= 0.9 and (g.fmt not in ("excel",) or "DAT" in name.upper() or "DATE" in name.upper()):
        if not (g.fmt in ("yymmdd", "ddmmyy", "mmddyy") and len(numeric) == n and len(set(strs)) > n * 0.9
                and "DAT" not in name.upper()):
            return f"date ({g.fmt})", g.parsed / n
    if len(numeric) / n >= 0.9:
        if any(x.percent for x in numeric):
            return "percent", 0.95
        ints = [x.value for x in numeric]
        if all(float(v).is_integer() and 100000 <= v <= 999999 for v in ints) and len(set(ints)) > 0.7 * len(ints):
            return "item code", 0.8
        if all(float(v).is_integer() for v in ints):
            if all(0 <= v <= 99 for v in ints) and len(set(ints)) <= 10:
                return "code", 0.6
            return "quantity", 0.7
        if max(abs(v) for v in ints) > 1000:
            return "money", 0.6
        return "number", 0.6
    if sum(1 for s in strs if section_code(s) and re.match(r"^S\d{3}", s)) / n >= 0.8:
        return "section", 0.9
    if all(len(s) <= 3 and s.isupper() for s in strs) and len(set(strs)) <= 12:
        return "status code", 0.7
    return "text", 0.5


def _role(name: str, kind: str, values: list, resolver, cities) -> tuple[str, str | None]:
    """(role, measure kind) for one column."""
    h = _hk(name)
    measure_word = next((k for k, rx in _MEASURE if re.search(rx, h)), None)
    numeric = kind in ("percent", "quantity", "money", "number", "code", "item code")
    if kind == "store":
        return "store", None
    if kind.startswith("date"):
        return "date", None
    for role, rx in _H:
        if not re.search(rx, h):
            continue
        if role in ("lat", "lng"):
            if numeric:
                return role, None
            continue
        if role == "store" and measure_word and numeric:
            break                                   # "store stock qty" is an amount, not a store
        if role == "store":
            strs = [clean_text(v) for v in values[:200] if v not in (None, "")]
            hits = sum(1 for x in strs if resolver.resolve(x).code)
            if strs and hits / len(strs) < 0.3:     # a "Location" column that is not our stores
                if re.search(r"location|loc\b", h) and not numeric:
                    return "address", None
                continue
        if role in ("item", "supplier") and measure_word and numeric and kind != "item code" and not re.search(r"code|no\b|number|id\b", h):
            break                                   # "items sold", "supplier sales" are amounts
        if role == "city" and numeric:
            continue
        return role, None
    if kind == "item code" and not measure_word:
        return "item", None
    if kind == "section":
        return "section", None
    if numeric:
        if kind == "code" and not measure_word and (re.search(r"code|\bid\b|type|class|grade|flag|status|level|rank|zone|group", h)
                                                    or len([v for v in values if v not in (None, "")]) >= 30):
            return "label", None
        mk = "percent" if kind == "percent" else (measure_word or ("money" if kind == "money" else "quantity" if kind == "quantity" else "number"))
        return "measure", mk
    strs = [clean_text(v) for v in values[:300] if v not in (None, "")]
    if strs and cities and sum(1 for s in strs if cities(s)) / len(strs) >= 0.7:
        return "city", None
    distinct = len(set(strs))
    if distinct <= max(60, len(strs) * 0.5):
        return "label", None
    return "text", None


def _split_code(v) -> tuple[str, str]:
    """'10234 - Nestle Pakistan' -> ('10234', 'Nestle Pakistan')."""
    s = clean_text(v)
    m = re.match(r"^\s*([A-Z0-9]{2,12})\s*[-–:|]\s*(.+)$", s, re.I)
    if m and re.search(r"\d", m.group(1)):
        return m.group(1).upper(), m.group(2).strip()
    return code_text(v), ""


def _stores_as_headers(cols: list[str], resolver) -> list[int]:
    idx = []
    for j, c in enumerate(cols):
        if not c or re.search(r"total|grand|sum|avg|average|%", str(c), re.I):
            continue
        m = resolver.resolve(c)
        if m.code and m.confidence >= 0.9 and m.kind == "store":
            idx.append(j)
    return idx if len(idx) >= 2 else []


def parse_generic(sheet: Sheet, ctx: ParseContext) -> ParseResult:
    res = ParseResult()
    rows = sheet.all_rows()
    h = find_header(rows, [])
    if h is None:
        res.error("no_table", "No table found in this sheet.")
        return res
    t = build_table(rows, h)
    meta = extract_meta(rows, upto=max(h.row - len(h.raw) + 1, 0))
    d = None
    for key in ("END DATE", "TO DATE", "TODAT", "STOCK AS OF", "STOCK AS AT", "REPORT DATE", "AS OF", "DATE"):
        v = meta["pairs"].get(key)
        if v:
            from ..values import find_dates
            ds_ = find_dates(v)
            d = max(ds_) if ds_ else parse_date(v)
            if d:
                break
    if d is None and meta.get("range"):
        d = meta["range"][1]
    if d is None:
        run = " ".join(v for k, v in meta["pairs"].items() if "RUN" in k or "TIME" in k)
        from ..values import find_dates
        runs = set(find_dates(run))
        ds = [x for x in meta.get("dates", []) if x not in runs]
        d = max(ds) if ds else None
    cols = [str(c) for c in t.columns]
    key = dataset_key(cols)
    known = (ctx.settings.get("datasets") or {}).get(key) or {}
    over = {c["name"]: c for c in known.get("columns", []) if c.get("user")}
    ai = ctx.settings.get("ai") or {}
    ai_cols = ai.get("columns") or {}
    ai_roles = ai.get("roles") or {}
    from stockcompass.logistics.geo import city_of

    # 1. what each column is
    wide = _stores_as_headers(cols, ctx.resolver)
    spec = []
    for j, c in enumerate(cols):
        col_vals = t.col(j)
        kind, conf = profile_column(c, col_vals, ctx.resolver)
        if j in wide:
            role, mk = "wide_store", "number"
        elif wide and re.search(r"total|grand|sum\b", c, re.I):
            role, mk = "ignore", None           # the row total of the store columns
        elif c in over:
            role, mk = over[c]["role"], over[c].get("kind")
        elif ai_roles.get(c) in ROLES:
            role, mk = ai_roles[c], None
            if role == "measure":
                mk = next((k for k, rx in _MEASURE if re.search(rx, _hk(c))), "number")
        else:
            role, mk = _role(c, kind, col_vals, ctx.resolver, city_of)
        if kind == "empty":
            role, mk = "ignore", None
        label = (over.get(c) or {}).get("label") or ai_cols.get(c) or ""
        spec.append(dict(name=c, role=role, kind=mk, label=str(label)[:120], found=kind))
    if wide:                       # stores across the top: one measure, one row per store
        ctx_words = _hk(" ".join([ctx.file_name or "", meta.get("title") or "", ai.get("what_it_is") or "", sheet.name or ""]))
        wk = next((k for k, rx in _MEASURE if re.search(rx, ctx_words)), "quantity")
        base = re.sub(r"\b(week|wk|day|month|report|data|file|sheet|by store|stores?)\b|\d+|[_\-]+", " ", Path(ctx.file_name or "").stem, flags=re.I)
        base = re.sub(r"\s+", " ", base).strip()
        wname = (ai.get("what_it_is") or (base.capitalize() if 3 <= len(base) <= 30 else "") or "Value")[:40]
        spec.append(dict(name=wname if wname not in cols else wname + " (value)", role="measure", kind=wk, label="", found="stores as columns"))

    def first(role):
        return next((i for i, s in enumerate(spec) if s["role"] == role and i < len(cols)), None)

    j_store, j_item, j_sup, j_supn, j_desc = first("store"), first("item"), first("supplier"), first("supplier_name"), first("description")
    j_date, j_dept, j_sec, j_fam = first("date"), first("dept"), first("section"), first("family")
    j_lat, j_lng, j_addr, j_city = first("lat"), first("lng"), first("address"), first("city")
    date_fmt = None
    if j_date is not None:
        g = infer_date_format(t.col(j_date)[:400])
        date_fmt = g.fmt
    pct_fraction = {}
    for i, s in enumerate(spec[:len(cols)]):
        if s["role"] == "measure" and s["kind"] == "percent":
            vals = [parse_num(v) for v in t.col(i)[:400]]
            nums = [x.value for x in vals if x.value is not None]
            pct_fraction[i] = bool(nums) and not any(x.percent for x in vals) and all(abs(x) <= 1.5 for x in nums)

    # 2. the rows, with store / item / supplier / date pulled out
    unknown = Counter()
    places, n_rows, days = {}, 0, []
    wide_name = spec[-1]["name"] if wide else None
    for i, r in enumerate(t.rows[:MAX_RAW_ROWS]):
        rec = {}
        for j, c in enumerate(cols):
            if j in wide:
                continue
            v = r[j] if j < len(r) else None
            if v in (None, "") or is_missing(v):
                continue
            s = spec[j]
            if s["role"] == "ignore":
                continue
            if s["role"] == "measure":
                x = pct_value(v, pct_fraction.get(j)) if s["kind"] == "percent" else parse_num(v).value
                if x is None:
                    continue
                v = x
            elif s["role"] == "date":
                dv = parse_date(v, date_fmt)
                v = dv.isoformat() if dv else clean_text(v)
            elif isinstance(v, (date, datetime)):
                v = v.isoformat()
            elif isinstance(v, float) and v.is_integer():
                v = int(v)
            rec[c] = v
        store = None
        if j_store is not None and j_store < len(r) and r[j_store] not in (None, ""):
            m = ctx.resolver.resolve(r[j_store])
            if m.code and m.kind == "store":
                store = m.code
            elif m.kind not in ("closed", "channel"):
                unknown[clean_text(r[j_store])] += 1
        elif ctx.store:
            store = ctx.store
        item = item_code(r[j_item]) if j_item is not None and j_item < len(r) else ""
        if item and not re.match(r"^[A-Z0-9]{3,14}$", item):
            m = re.match(r"^\s*(\d{4,9})\b", str(r[j_item]))
            item = m.group(1).lstrip("0") if m else ""
        sup, supn = ("", "")
        if j_sup is not None and j_sup < len(r) and r[j_sup] not in (None, ""):
            sup, supn = _split_code(r[j_sup])
        if j_supn is not None and j_supn < len(r) and r[j_supn] not in (None, ""):
            supn = clean_text(r[j_supn])
            if not sup:
                sup = supn.upper()[:40]
        dd = None
        if j_date is not None and j_date < len(r):
            dd = parse_date(r[j_date], date_fmt)
            if dd:
                days.append(dd)
        if item and j_desc is not None and j_desc < len(r) and r[j_desc] not in (None, ""):
            res.items.setdefault(item, {"description": clean_text(r[j_desc])[:120]})
        if sup and supn and sup != supn.upper()[:40]:
            res.suppliers[sup] = supn[:120]
        if j_dept is not None and j_dept < len(r):
            rec["_dept"] = dept_code(r[j_dept]) or None
        if j_sec is not None and j_sec < len(r):
            rec["_section"] = section_code(r[j_sec]) or None
        if j_fam is not None and j_fam < len(r):
            rec["_family"] = family_code(r[j_fam]) or None
        # locations of stores / suppliers for the map
        if (j_lat is not None or j_addr is not None or j_city is not None) and (store or sup):
            def cell(j):
                return r[j] if j is not None and j < len(r) and r[j] not in (None, "") else None
            lat, lng = parse_num(cell(j_lat)).value if j_lat is not None else None, parse_num(cell(j_lng)).value if j_lng is not None else None
            k = ("store", store) if store and not sup else ("supplier", sup)
            places.setdefault(k, dict(kind=k[0], code=k[1], name=supn if k[0] == "supplier" else "", lat=lat, lng=lng,
                                      address=clean_text(cell(j_addr)) if cell(j_addr) else "", city=clean_text(cell(j_city)) if cell(j_city) else ""))
        base = dict(dataset=key, store=store, item=item or None, supplier=sup or None, d=dd)
        if wide:
            for j in wide:
                v = parse_num(r[j] if j < len(r) else None).value
                if v is None:
                    continue
                res.add("raw_row", dict(row_no=n_rows, data=json.dumps({**rec, "Store": cols[j], wide_name: v}, ensure_ascii=False, default=str),
                                        **{**base, "store": ctx.resolver.resolve(cols[j]).code}))
                n_rows += 1
        elif rec:
            res.add("raw_row", dict(row_no=n_rows, data=json.dumps(rec, ensure_ascii=False, default=str), **base))
            n_rows += 1
        if store:
            res.stores.add(store)
    if wide:
        res.stores |= {ctx.resolver.resolve(cols[j]).code for j in wide}
        spec.insert(0, dict(name="Store", role="store", kind=None, label="from the column headers", found="stores as columns"))
    if not res.stores and ctx.store:
        res.stores.add(ctx.store)
    choose_snapshot(res, ctx, [(d, "the header of the report"), (max(days) if days else None, "the latest date in the rows")])
    if days:
        res.period_from, res.period_to = min(days), max(days)
    if len(t.rows) > MAX_RAW_ROWS:
        res.warn("truncated", f"Only the first {MAX_RAW_ROWS:,} rows were kept.", len(t.rows) - MAX_RAW_ROWS)
    if unknown:
        names = [n for n, _ in unknown.most_common(40)]
        res.warn("unknown_store", "Store names not recognised (rows kept without a store). Map them once in Settings > Stores: "
                 + ", ".join(names[:8]) + ("…" if len(names) > 8 else ""), sum(unknown.values()), detail="|".join(names))
    title = meta.get("title") or ""
    title = title if 4 <= len(title) <= 80 and not re.search(r"\d{4,}|page \d", title, re.I) else ""
    name = (known.get("name") if known.get("user_named") else None) or ai.get("what_it_is") or ctx.settings.get("hint") \
        or known.get("name") or title or _pretty(ctx.file_name, sheet.name)
    res.variant = "ds:" + key
    res.tables["_dataset"] = [dict(key=key, name=str(name)[:120], columns=spec, headers=cols)]
    if places:
        res.tables["_places"] = list(places.values())
    measures = [s["name"] for s in spec if s["role"] == "measure"]
    keys_found = [ROLES[x] for x in ("store", "item", "supplier", "date") if any(s["role"] == x or (x == "store" and wide) for s in spec)]
    res.info("columns", "Columns understood: " + "; ".join(f"{s['name']} = {ROLES.get(s['role'], s['role'])}"
                                                           + (f" ({KINDS.get(s['kind'], s['kind'])})" if s.get("kind") else "")
                                                           for s in spec[:40]))
    res.summary = (f"{n_rows:,} rows kept as '{str(name)[:60]}'"
                   + (f", by {', '.join(k.lower() for k in keys_found)}" if keys_found else ", country level")
                   + (f"; amounts: {', '.join(measures[:6])}" if measures else "")
                   + (f"; {len(places)} locations for the map" if places else ""))
    return res


def _pretty(file_name: str, sheet: str) -> str:
    stem = Path(file_name or "").stem
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\(\d+\)|\b\d{1,2}[ .]\d{1,2}[ .]\d{2,4}\b|\b20\d{2}[ .]?\d{2}[ .]?\d{2}\b", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip() or "Data"
    if sheet and not re.match(r"^(sheet|page|data|export)\s*\d*$", sheet, re.I) and Path(sheet).stem.lower() != Path(file_name or "").stem.lower():
        return f"{stem} · {sheet}"
    return stem
