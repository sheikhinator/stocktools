"""Other data: every table the importer did not know, as a dataset with stores, items, suppliers, dates and amounts.

The same filters as every screen apply (store / format / region, department, section, As of date). Amounts are
added up (percentages averaged). Datasets with a date column build up history over imports; the others show the
latest import per store, like the known reports."""

from __future__ import annotations

import json
from collections import defaultdict

from stockcompass.db import Database

from .core import AS_OF, Scope, ids_sql

KIND_FMT = {"money": "pkr", "quantity": "int", "percent": "pct", "number": "num"}
AGG_LABEL = {"percent": "average"}


def jcol(name: str, alias: str = "r") -> str:
    path = '$."' + str(name).replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"json_extract_string({alias}.data, '{path.replace(chr(39), chr(39) * 2)}')"


def jnum(name: str, alias: str = "r") -> str:
    return f"TRY_CAST({jcol(name, alias)} AS DOUBLE)"


def _cols(row: dict) -> list[dict]:
    try:
        cols = json.loads(row.get("columns") or "[]")
    except ValueError:
        cols = []
    return [c for c in cols if c.get("role") not in ("wide_store", "ignore")]


def registry(db: Database) -> dict[str, dict]:
    out = {}
    for r in db.qd("SELECT * FROM datasets WHERE NOT coalesce(hidden, false) ORDER BY name"):
        cols = _cols(r)
        out[r["key"]] = dict(key=r["key"], name=r["name"], columns=cols, updated=r["updated"],
                             measures=[c for c in cols if c["role"] == "measure"],
                             labels=[c for c in cols if c["role"] in ("label", "city")],
                             has=({c["role"] for c in cols}))
    return out


def get(db: Database, key: str) -> dict | None:
    return registry(db).get(key)


def import_ids(db: Database, key: str, series: bool | None = None) -> list[int]:
    """Imports that make up the dataset now: all of them for a dated series, else the latest per store scope."""
    d = AS_OF.get()
    rows = db.q("SELECT import_id, coalesce(stores,''), snapshot_date FROM imports WHERE report_type='generic' AND status='ok' "
                "AND variant=? AND (CAST(? AS DATE) IS NULL OR snapshot_date IS NULL OR snapshot_date <= CAST(? AS DATE)) "
                "ORDER BY snapshot_date DESC NULLS LAST, import_id DESC", ["ds:" + key, d, d])
    if series:
        return [r[0] for r in rows]
    covered: set[str] = set()
    out = []
    for iid, st, _ in rows:
        sts = set(filter(None, st.split(",")))
        if not sts:
            if not out:
                out.append(iid)
            continue
        if not sts.issubset(covered):
            out.append(iid)
            covered |= sts
    return out


def _where(ds: dict, sc: Scope | None, ids: list[int]) -> tuple[str, list, str]:
    """WHERE clause, params and the JOIN needed for department / section filters."""
    parts, params = [f"r.import_id IN {ids_sql(ids)}"], []
    join = ""
    if "item" in ds["has"]:
        join = " LEFT JOIN items i ON i.item = r.item"
    if sc is not None:
        if sc.has_store_filter():
            w, p = sc.store_sql("r.store")
            parts.append(w)
            params += p
        dept = "coalesce(json_extract_string(r.data, '$._dept'), " + ("i.dept" if join else "NULL") + ")"
        sec = "coalesce(json_extract_string(r.data, '$._section'), " + ("i.section" if join else "NULL") + ")"
        if sc.section and (join or "section" in ds["has"]):
            parts.append(f"{sec} = ?")
            params.append(sc.section)
        elif sc.dept and (join or "dept" in ds["has"] or "section" in ds["has"]):
            w, p = sc.dept_sql(f"coalesce({dept}, (SELECT s.dept FROM sections s WHERE s.code = {sec}))")
            parts.append(w)
            params += p
    return " AND ".join(parts), params, join


def _agg(c: dict) -> str:
    return f"avg({jnum(c['name'])})" if c.get("kind") == "percent" else f"sum({jnum(c['name'])})"


GROUPS = {"store": "r.store", "item": "r.item", "supplier": "r.supplier", "date": "CAST(r.d AS VARCHAR)",
          "dept": "coalesce(json_extract_string(r.data, '$._dept'), {idept})",
          "section": "coalesce(json_extract_string(r.data, '$._section'), {isec})"}


def group_options(ds: dict) -> list[dict]:
    out = []
    names = {"store": "Store", "item": "Item", "supplier": "Supplier", "date": "Date", "dept": "Department", "section": "Section"}
    for k in ("store", "item", "supplier", "date"):
        if k in ds["has"]:
            out.append(dict(k=k, n=names[k]))
    if "item" in ds["has"] or "dept" in ds["has"] or "section" in ds["has"]:
        out += [dict(k="dept", n="Department"), dict(k="section", n="Section")]
    for c in ds["labels"]:
        out.append(dict(k="col:" + c["name"], n=c.get("label") or c["name"]))
    return out


def summary(db: Database, key: str, sc: Scope | None = None, by: str | None = None, limit: int = 2000) -> dict:
    ds = get(db, key)
    if not ds:
        return dict(error="This dataset no longer exists.")
    series = "date" in ds["has"]
    ids = import_ids(db, key, series)
    if not ids:
        return dict(ds=ds, ids=[], totals={}, rows=[], by=None, groups=group_options(ds), n=0)
    w, p, join = _where(ds, sc, ids)
    ms = ds["measures"]
    sel = ", ".join(f"{_agg(c)} AS m{i}" for i, c in enumerate(ms)) or "NULL AS m0"
    tot = db.q(f"SELECT count(*), {sel}, count(DISTINCT r.store), count(DISTINCT r.item), min(r.d), max(r.d) "
               f"FROM raw_row r{join} WHERE {w}", p)[0]
    n = tot[0]
    totals = {c["name"]: tot[1 + i] for i, c in enumerate(ms)}
    stats = dict(rows=n, stores=tot[1 + max(1, len(ms))], items=tot[2 + max(1, len(ms))],
                 first=tot[3 + max(1, len(ms))], last=tot[4 + max(1, len(ms))])
    groups = group_options(ds)
    by = by if by in [g["k"] for g in groups] else (groups[0]["k"] if groups else None)
    rows = []
    if by:
        expr = jcol(by[4:]) if by.startswith("col:") else GROUPS[by].format(idept="i.dept" if join else "NULL",
                                                                          isec="i.section" if join else "NULL")
        order = "1" if by == "date" else ("2 DESC NULLS LAST" if ms else "count(*) DESC")
        got = db.q(f"SELECT {expr} AS g, {sel}, count(*) FROM raw_row r{join} WHERE {w} GROUP BY 1 ORDER BY {order} LIMIT {int(limit) + 1}", p)
        names = _names(db, by, [g[0] for g in got])
        for g in got[:limit]:
            rows.append(dict(k=g[0], name=names.get(g[0], g[0] if g[0] not in (None, "") else "(not set)"),
                             v={c["name"]: g[1 + i] for i, c in enumerate(ms)}, n=g[-1]))
        more = len(got) > limit
    else:
        more = False
    trend = []
    if series and ms and by != "date":
        trend = db.q(f"SELECT CAST(r.d AS VARCHAR), {_agg(ms[0])} FROM raw_row r{join} WHERE {w} AND r.d IS NOT NULL "
                     f"GROUP BY 1 ORDER BY 1 LIMIT 400", p)
    return dict(ds=ds, ids=ids, totals=totals, stats=stats, rows=rows, more=more, by=by, groups=groups, n=n,
                trend=[dict(d=d, v=v) for d, v in trend], series=series)


def detail_rows(db: Database, key: str, sc: Scope | None = None, limit: int = 1500, where: dict | None = None) -> dict:
    """The rows themselves (for the table and Export)."""
    ds = get(db, key)
    if not ds:
        return dict(cols=[], rows=[], total=0)
    ids = import_ids(db, key, "date" in ds["has"])
    w, p, join = _where(ds, sc, ids)
    for k, v in (where or {}).items():
        if v in (None, ""):
            continue
        if k in ("store", "item", "supplier"):
            w += f" AND r.{k} = ?"
            p.append(str(v))
        elif k == "date":
            w += " AND CAST(r.d AS VARCHAR) = ?"
            p.append(str(v))
        elif k.startswith("col:"):
            w += f" AND {jcol(k[4:])} = ?"
            p.append(str(v))
    total = db.one(f"SELECT count(*) FROM raw_row r{join} WHERE {w}", p, 0)
    got = db.q(f"SELECT r.store, r.item, r.supplier, r.data FROM raw_row r{join} WHERE {w} ORDER BY r.import_id DESC, r.row_no LIMIT {int(limit)}", p)
    stores = {c: n for c, n in db.q("SELECT code, name FROM stores")}
    out = []
    for st, it, sup, data in got:
        try:
            rec = json.loads(data or "{}")
        except ValueError:
            rec = {}
        rec = {k: v for k, v in rec.items() if not k.startswith("_")}
        rec["_store"] = stores.get(st, st) if st else None
        rec["store"], rec["item"], rec["supplier"] = st, it, sup
        out.append(rec)
    cols = [dict(k=c["name"], l=c.get("label") or c["name"], kind=KIND_FMT.get(c.get("kind"), "text") if c["role"] == "measure" else
                 ("date" if c["role"] == "date" else "text")) for c in ds["columns"] if c["role"] not in ("store",)]
    if "store" in ds["has"]:
        cols.insert(0, dict(k="_store", l="Store", kind="text"))
    return dict(cols=cols, rows=out, total=total)


def _names(db: Database, by: str, keys: list) -> dict:
    keys = [k for k in keys if k not in (None, "")]
    if not keys:
        return {}
    if by == "store":
        return {c: f"{n}" for c, n in db.q("SELECT code, name FROM stores")}
    if by == "supplier":
        return {c: n for c, n in db.q("SELECT code, name FROM suppliers")}
    if by == "dept":
        return {c: n for c, n in db.q("SELECT code, name FROM departments")}
    if by == "section":
        return {c: f"S{c} {n}" for c, n in db.q("SELECT code, name FROM sections")}
    if by == "item" and len(keys) <= 3000:
        marks = ",".join("?" * len(keys))
        return {c: f"{c} {d or ''}".strip() for c, d in db.q(f"SELECT item, description FROM items WHERE item IN ({marks})", keys)}
    return {}


def overview(db: Database, sc: Scope | None = None) -> list[dict]:
    """Every dataset with its headline numbers for the current filters (Other data page, Home)."""
    out = []
    for key, ds in registry(db).items():
        ids = import_ids(db, key, "date" in ds["has"])
        if not ids:
            continue
        w, p, join = _where(ds, sc, ids)
        ms = ds["measures"][:4]
        sel = ", ".join(f"{_agg(c)}" for c in ms)
        r = db.q(f"SELECT count(*), count(DISTINCT r.store), max(r.d){', ' + sel if sel else ''} FROM raw_row r{join} WHERE {w}", p)[0]
        imp = db.q(f"SELECT max(snapshot_date), max(imported_at), count(*), string_agg(DISTINCT file_name, ', ') FROM imports WHERE import_id IN {ids_sql(ids)}")[0]
        out.append(dict(key=key, name=ds["name"], rows=r[0], stores=r[1], last=str(r[2] or imp[0] or "") or None,
                        imported=imp[1], imports=imp[2], files=(imp[3] or "")[:200],
                        keys=[x for x in ("store", "item", "supplier", "date") if x in ds["has"]],
                        headline=[dict(name=c.get("label") or c["name"], col=c["name"], kind=c.get("kind"), v=r[3 + i])
                                  for i, c in enumerate(ms)],
                        columns=len(ds["columns"])))
    return sorted(out, key=lambda x: str(x["imported"] or ""), reverse=True)


def for_key(db: Database, field: str, value: str, limit: int = 40) -> list[dict]:
    """Rows of every dataset that mention this item / supplier / store (item and supplier cards)."""
    assert field in ("item", "supplier", "store")
    out = []
    for key, ds in registry(db).items():
        if field not in ds["has"]:
            continue
        ids = import_ids(db, key, "date" in ds["has"])
        if not ids:
            continue
        d = detail_rows(db, key, None, limit, {field: value})
        if d["rows"]:
            cols = [c for c in d["cols"] if not (field == "item" and c["k"] in [x["name"] for x in ds["columns"] if x["role"] in ("item", "description")])]
            out.append(dict(key=key, name=ds["name"], cols=cols, rows=d["rows"], total=d["total"]))
    return out


def by_store_measure(db: Database, key: str, col: str) -> dict[str, float]:
    ds = get(db, key)
    if not ds:
        return {}
    c = next((x for x in ds["measures"] if x["name"] == col), None)
    if not c:
        return {}
    ids = import_ids(db, key, "date" in ds["has"])
    w, p, join = _where(ds, None, ids)
    return {s: v for s, v in db.q(f"SELECT r.store, {_agg(c)} FROM raw_row r{join} WHERE {w} AND r.store IS NOT NULL GROUP BY 1", p)}


def facts(db: Database, key: str, sc: Scope) -> tuple[list[dict], set[str], str]:
    """Rows for Analyse: one per store x item x supplier x day x department, with every amount."""
    ds = get(db, key)
    if not ds:
        return [], set(), ""
    ids = import_ids(db, key, "date" in ds["has"])
    if not ids:
        return [], set(), ""
    w, p, join = _where(ds, sc, ids)
    ms = ds["measures"]
    dept = "coalesce(json_extract_string(r.data, '$._dept'), " + ("i.dept" if join else "NULL") + ")"
    sec = "coalesce(json_extract_string(r.data, '$._section'), " + ("i.section" if join else "NULL") + ")"
    fam = "coalesce(json_extract_string(r.data, '$._family'), " + ("i.family" if join else "NULL") + ")"
    sums = ", ".join(f"sum({jnum(c['name'])}), count({jnum(c['name'])})" for c in ms)
    rows = db.q(f"SELECT r.store, r.item, r.supplier, CAST(r.d AS VARCHAR), {dept}, {sec}, {fam}{', ' + sums if sums else ''} "
                f"FROM raw_row r{join} WHERE {w} GROUP BY ALL", p)
    out = []
    for r in rows:
        f = {}
        for i in range(len(ms)):
            f[f"v{i}"] = float(r[7 + 2 * i] or 0)
            f[f"n{i}"] = float(r[8 + 2 * i] or 0)
        out.append(dict(store=r[0], item=r[1], supplier=r[2], day=r[3], dept=r[4], section=r[5], family=r[6], f=f))
    dims = set()
    if "store" in ds["has"]:
        dims |= {"store", "format", "region"}
    for k in ("item", "supplier"):
        if k in ds["has"]:
            dims.add(k)
    if "date" in ds["has"]:
        dims.add("day")
    if "item" in ds["has"] or "dept" in ds["has"] or "section" in ds["has"]:
        dims |= {"dept", "section"}
    if "item" in ds["has"] or "family" in ds["has"]:
        dims.add("family")
    return out, dims, ds["name"]


def measures_for_analyse(db: Database) -> tuple[dict, list]:
    """Analyse measures for every dataset amount: key ds:<dataset>:<n>."""
    ms, groups = {}, []
    for key, ds in registry(db).items():
        keys = []
        for i, c in enumerate(ds["measures"]):
            mk = f"ds:{key}:{i}"
            kind = KIND_FMT.get(c.get("kind"), "num")
            if c.get("kind") == "percent":
                fn = (lambda s, i=i: s[f"v{i}"] / s[f"n{i}"] if s.get(f"n{i}") else None)
            else:
                fn = (lambda s, i=i: s[f"v{i}"] if s.get(f"n{i}") else None)
            ms[mk] = (f"{c.get('label') or c['name']} ({ds['name'][:30]})", f"ds:{key}", kind, fn,
                      f"From '{ds['name']}' (imported data): {c['name']}, {'averaged' if c.get('kind') == 'percent' else 'added up'}.")
            keys.append(mk)
        if keys:
            groups.append((f"Other data · {ds['name'][:40]}", keys))
    return ms, groups


def set_column(db: Database, key: str, name: str, role: str | None = None, kind: str | None = None, label: str | None = None) -> dict:
    """Correct what a column is. Remembered for every later file with the same columns; re-import to re-read old ones."""
    r = db.qd("SELECT columns FROM datasets WHERE key=?", [key])
    if not r:
        raise ValueError("Unknown dataset")
    cols = json.loads(r[0]["columns"] or "[]")
    for c in cols:
        if c["name"] == name:
            if role:
                c["role"] = role
            if kind is not None:
                c["kind"] = kind or None
            if label is not None:
                c["label"] = label
            c["user"] = True
    db.execute("UPDATE datasets SET columns=? WHERE key=?", [json.dumps(cols, ensure_ascii=False), key])
    if role:
        reapply(db, key)
    return get(db, key) or {}


def reapply(db: Database, key: str) -> int:
    """Re-read the saved rows with the current column roles (store / item / supplier / date / amounts), so a
    correction applies to what was imported before too."""
    from stockcompass.importer.parsers.generic import _split_code
    from stockcompass.importer.values import item_code, parse_date, parse_num
    r = db.qd("SELECT columns FROM datasets WHERE key=?", [key])
    if not r:
        return 0
    cols = json.loads(r[0]["columns"] or "[]")
    role = {c["name"]: c["role"] for c in cols}
    first = {}
    for c in cols:
        first.setdefault(c["role"], c["name"])
    resolver = db.resolver()
    rows = db.q("SELECT import_id, row_no, data, store FROM raw_row WHERE dataset=?", [key])
    out = []
    for iid, no, data, old_store in rows:
        try:
            rec = json.loads(data or "{}")
        except ValueError:
            continue
        st = old_store
        if "store" in first and rec.get(first["store"]) not in (None, ""):
            m = resolver.resolve(rec[first["store"]])
            st = m.code if m.code and m.kind == "store" else None
        it = item_code(rec.get(first["item"])) if "item" in first else None
        sup = _split_code(rec.get(first["supplier"]))[0] if "supplier" in first and rec.get(first["supplier"]) not in (None, "") else None
        d = parse_date(rec.get(first["date"])) if "date" in first and rec.get(first["date"]) else None
        for name, rl in role.items():
            if rl == "measure" and isinstance(rec.get(name), str):
                x = parse_num(rec[name]).value
                if x is not None:
                    rec[name] = x
        out.append(dict(import_id=iid, row_no=no, data=json.dumps(rec, ensure_ascii=False, default=str), dataset=key,
                        store=st, item=it or None, supplier=sup or None, d=d))
    with db.lock:
        db.con.execute("BEGIN")
        try:
            db.con.execute("DELETE FROM raw_row WHERE dataset=?", [key])
            db.insert_rows("raw_row", out)
            for iid in {o["import_id"] for o in out}:
                sts = sorted({o["store"] for o in out if o["import_id"] == iid and o["store"]})
                db.con.execute("UPDATE imports SET stores=? WHERE import_id=?", [",".join(sts), iid])
            db.con.execute("COMMIT")
        except Exception:
            db.con.execute("ROLLBACK")
            raise
    db.rev += 1
    return len(out)


def rename(db: Database, key: str, name: str):
    db.execute("UPDATE datasets SET name=?, user_named=TRUE WHERE key=?", [name.strip()[:120], key])


def hide(db: Database, key: str, hidden: bool = True):
    db.execute("UPDATE datasets SET hidden=? WHERE key=?", [hidden, key])


def stats_by_store(db: Database, sc: Scope | None = None) -> dict[str, list]:
    """Per store: which datasets have rows for it (store drill / map popups)."""
    out = defaultdict(list)
    for key, ds in registry(db).items():
        if "store" not in ds["has"]:
            continue
        ids = import_ids(db, key, "date" in ds["has"])
        if not ids:
            continue
        for st, n in db.q(f"SELECT store, count(*) FROM raw_row r WHERE r.import_id IN {ids_sql(ids)} AND store IS NOT NULL GROUP BY 1"):
            out[st].append(dict(key=key, name=ds["name"], rows=n))
    return out
