"""Order Advisor: before an LPO is placed, check every line and say how much to order, whether to order at all, and
whether another store can send it instead (IST).

For each item x store:
  speed      units sold per day (GIMA Benchmark qty / days; GIMA zero stock sheet daily average when missing)
  on hand    RealTime stock (Benchmark stock, then zero stock sheet, when the store has no RealTime)
  on order   open orders from the zero stock sheet and the leaflet workbook (item-level LPO lines when available)
  lead time  the supplier's typical days from LPO to delivery (LPO list), else the rule default
  review     days until the item's next order date (RealTime), else the rule default
  safety     days of safety stock by ABC class (A sells most in the store)
  target     speed x (lead + review + safety), never below the shelf minimum (facing / min qty)
  suggested  target - (on hand + on order), rounded up to full cases (PCB), capped at the department's maximum cover
Stops: not orderable (NC / 007), aged (DP) stock in the store, not selling with stock, negative stock (recount first).
IST:   another store holding more than its own target (aged stock first, same city first) sends it instead.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date

from stockcompass.db import Database

from .core import L, as_of, ids_sql, latest_imports

DEFAULT_RULES = dict(
    lead_days=7,             # when a supplier has no LPO history
    review_days=7,           # days until the next order, when RealTime has no next-order date
    safety_A=7, safety_B=5, safety_C=3,
    max_cover={"01": 35, "02": 7, "03": 60, "04": 90, "05": 90},   # days of cover after ordering, by department
    max_cover_default=45,
    promo_uplift=1.6,        # sales speed multiplier while the item is in a running / coming leaflet
    ist_same_city=True,      # IST only between stores in the same city (aged stock may always move)
    ist_min_units=3,         # smaller transfers are not worth the trip
    ist_donor_keep_days=10,  # a donor store keeps at least this many days of its own sales
    tolerance_pct=20,        # a proposed quantity within this % of the suggestion is fine as it is
    blocked_status=["NC", "NI", "DL", "SU"],
)

RULE_HELP = dict(
    lead_days="Lead time (days) when a supplier has no order history",
    review_days="Days until the next order when RealTime has no next-order date",
    safety_A="Safety stock (days) for A items", safety_B="Safety stock (days) for B items", safety_C="Safety stock (days) for C items",
    max_cover_default="Maximum days of cover after ordering (other departments)",
    promo_uplift="Sales speed multiplier during a leaflet / promotion",
    ist_min_units="Smallest transfer worth doing (units)",
    ist_donor_keep_days="A store sending stock keeps at least this many days of its own sales",
    tolerance_pct="A proposed quantity within this % of the suggestion is accepted as it is",
)


def rules(db: Database) -> dict:
    r = dict(DEFAULT_RULES)
    saved = db.setting("order_rules") or {}
    for k, v in saved.items():
        if k in r:
            r[k] = v
    r["max_cover"] = {**DEFAULT_RULES["max_cover"], **(saved.get("max_cover") or {})}
    return r


# ------------------------------------------------------------------------------------------------ inputs
def _ids(db, rt):
    return [i for i, _, _ in latest_imports(db, rt)]


def _in(col: str, vals) -> tuple[str, list]:
    vals = [v for v in (vals or []) if v]
    if not vals:
        return "TRUE", []
    return f"{col} IN ({','.join('?' * len(vals))})", list(vals)


def _stock(db, stores, items) -> dict:
    ids = _ids(db, "gima_realtime")
    if not ids:
        return {}
    ws, ps = _in("store", stores)
    wi, pi = _in("item", items) if items is not None and len(items) <= 900 else ("TRUE", [])
    out = {}
    for r in db.qd(f"""SELECT store, item, qty, cost, price, status, range_code, supplier, next_order, snap_date
                       FROM stock_item WHERE import_id IN {ids_sql(ids)} AND {ws} AND {wi}""", ps + pi):
        out[(r["store"], r["item"])] = r
    return out


def _sales(db, stores) -> tuple[dict, dict]:
    """(units per day, benchmark stock) per store x item from the latest Benchmark of each store."""
    ids = _ids(db, "gima_benchmark")
    speed, bstock = {}, {}
    if ids:
        ws, ps = _in("store", stores)
        for st, it, qty, stock, d0, d1 in db.q(f"""SELECT store, item, sum(qty), sum(stock), min(date_from), max(date_to) FROM sales_item
                                                  WHERE import_id IN {ids_sql(ids)} AND {ws} GROUP BY 1, 2""", ps):
            days = max(1, ((d1 - d0).days + 1) if d0 and d1 else 28)
            speed[(st, it)] = max(0.0, (qty or 0) / days)
            if stock is not None:
                bstock[(st, it)] = stock
    return speed, bstock


def _zero(db, stores) -> dict:
    ids = _ids(db, "gima_zero_stock")
    if not ids:
        return {}
    ws, ps = _in("store", stores)
    return {(r["store"], r["item"]): r for r in db.qd(
        f"""SELECT store, item, qty, dlyavg, open_lpo, total_ordered, total_received, min_qty, facing, order_mode, delivery_date
            FROM zero_item WHERE import_id IN {ids_sql(ids)} AND {ws}""", ps)}


def _leaflet(db) -> dict:
    ids = _ids(db, "leaflet_theme")
    if not ids:
        return {}
    return {(r["store"], r["item"]): r for r in db.qd(
        f"""SELECT store, item, max(date_from) date_from, max(date_to) date_to, max(on_order_qty) on_order_qty, max(theme_name) theme
            FROM leaflet_item WHERE import_id IN {ids_sql(ids)} GROUP BY 1, 2""")}


def _aged(db) -> dict:
    ids = _ids(db, "dp_master")
    if not ids:
        return {}
    return {(s, i): (a, v) for s, i, a, v in db.q(
        f"SELECT store, item, max(age_days), sum(value) FROM dp_item WHERE import_id IN {ids_sql(ids)} AND coalesce(qty, 0) > 0 GROUP BY 1, 2")}


def _item_costs(db) -> dict:
    """item -> typical unit cost when the store's RealTime has none: any store's RealTime, DP data, or Benchmark
    sales minus margin."""
    out = {}
    for it, c in db.q("SELECT item, (sum(sales) - sum(margin)) / sum(qty) FROM sales_item GROUP BY item HAVING sum(qty) > 0 AND sum(margin) IS NOT NULL"):
        if c and c > 0:
            out[it] = c
    for it, c in db.q("SELECT item, median(cost) FROM dp_item WHERE cost > 0 GROUP BY item"):
        out[it] = c
    for it, c in db.q("SELECT item, median(cost) FROM stock_item WHERE cost > 0 GROUP BY item"):
        out[it] = c
    return out


def supplier_lead_times(db) -> dict:
    """Typical days from LPO to delivery per supplier (median of the LPO list)."""
    ids = _ids(db, "lpo_list")
    if not ids:
        return {}
    by = defaultdict(list)
    for sup, ld, d0, d1 in db.q(f"SELECT supplier, lead_days, lpo_date, delivery_date FROM lpo WHERE import_id IN {ids_sql(ids)}"):
        v = ld if ld is not None else ((d1 - d0).days if d0 and d1 else None)
        if sup and v is not None and 0 <= v <= 120:
            by[sup].append(v)
    return {s: round(statistics.median(v), 1) for s, v in by.items() if v}


# ------------------------------------------------------------------------------------------------ the advice
def advise(db: Database, stores: list[str] | None = None, supplier: str | None = None, dept: str | None = None,
           section: str | None = None, proposed: list[dict] | None = None, limit: int = 5000) -> dict:
    """Suggested order for the chosen stores (optionally one supplier / department / section), or a check of a
    proposed order (proposed = [{store, item, qty}]). Returns lines with decision and reason, plus a summary."""
    R = rules(db)
    today = as_of() or date.today()
    notes: list[str] = []
    prop = {}
    if proposed:
        for p in proposed:
            st, it = str(p.get("store") or "").strip(), str(p.get("item") or "").strip()
            if st and it:
                prop[(st, it)] = prop.get((st, it), 0) + float(p.get("qty") or 0)
        stores = sorted({s for s, _ in prop})
    all_stores = {s["code"]: s for s in db.store_list()}
    stock_all = _stock(db, None, None)                  # every store: needed for transfers between stores
    speed, bstock = _sales(db, None)
    zero = _zero(db, None)
    leaf = _leaflet(db)
    aged = _aged(db)
    lead_by = supplier_lead_times(db)
    item_info = {r["item"]: r for r in db.qd("SELECT item, description, dept, section, family, supplier, pcb FROM items")}
    sup_names = {c: n for c, n in db.q("SELECT code, name FROM suppliers")}
    costs = _item_costs(db)
    from .core import item_price_any
    prices_any = item_price_any(db)

    # which lines: a proposed order, or every item the chosen stores stock or sell
    if prop:
        keys = list(prop)
    else:
        want = set(stores or all_stores)
        keys = {k for k in list(stock_all) + list(speed) + list(zero) if k[0] in want}
        keys = sorted(keys)

    def info_ok(it):
        inf = item_info.get(it) or {}
        sup = (inf.get("supplier") or "")
        if supplier and sup != supplier:
            return False
        if dept and (inf.get("dept") or "") not in (["03", "04", "05"] if dept == "NF" else [dept]):
            return False
        if section and (inf.get("section") or "") != section:
            return False
        return True

    keys = [k for k in keys if info_ok(k[1])]
    if not stock_all:
        notes.append("No RealTime stock report yet: stock on hand comes from the Benchmark and zero stock sheets (add RealTime per store for exact stock).")
    if not speed:
        notes.append("No GIMA Benchmark yet: sales speed comes only from the zero stock sheet (add a 4-week Benchmark).")

    # ABC per store by sales value
    abc = {}
    by_store = defaultdict(list)
    for (st, it), d in speed.items():
        price = (stock_all.get((st, it)) or {}).get("price") or 0
        by_store[st].append((d * (price or 1), it))
    for st, lst in by_store.items():
        lst.sort(reverse=True)
        tot = sum(v for v, _ in lst) or 1
        run = 0.0
        for v, it in lst:
            run += v
            abc[(st, it)] = "A" if run / tot <= 0.8 else "B" if run / tot <= 0.95 else "C"

    def on_hand(k):
        s = stock_all.get(k)
        if s and s.get("qty") is not None:
            return float(s["qty"]), "RealTime"
        if k in bstock:
            return float(bstock[k] or 0), "Benchmark"
        z = zero.get(k)
        if z:
            return float(z.get("qty") or 0), "zero stock sheet"
        return 0.0, "unknown"

    def rate(k):
        d = speed.get(k)
        if d is None and zero.get(k) and zero[k].get("dlyavg") is not None:
            d = float(zero[k]["dlyavg"] or 0)
        return d

    def target_for(k, d, L, Rv):
        cls = abc.get(k, "C")
        S = R[f"safety_{cls}"]
        lf = leaf.get(k)
        uplift = 1.0
        if lf and lf.get("date_to") and lf["date_to"] >= today and (not lf.get("date_from") or (lf["date_from"] - today).days <= L + Rv):
            uplift = float(R["promo_uplift"])
        z = zero.get(k) or {}
        shelf = max(float(z.get("min_qty") or 0), float(z.get("facing") or 0))
        return max(d * uplift * (L + Rv + S), shelf), cls, S, uplift, shelf

    lines = []
    for k in keys[:limit * 3]:
        st, it = k
        inf = item_info.get(it) or {}
        s = stock_all.get(k) or {}
        sup = inf.get("supplier") or s.get("supplier") or ""
        oh, oh_src = on_hand(k)
        z = zero.get(k) or {}
        on_order = 0.0
        if z.get("open_lpo"):
            on_order = max(0.0, float(z.get("total_ordered") or 0) - float(z.get("total_received") or 0))
        if leaf.get(k) and leaf[k].get("on_order_qty"):
            on_order = max(on_order, float(leaf[k]["on_order_qty"] or 0))
        d = rate(k)
        L = float(lead_by.get(sup) or R["lead_days"])
        nxt = s.get("next_order")
        Rv = float((nxt - today).days) if nxt and nxt > today else float(R["review_days"])
        pcb = float(inf.get("pcb") or 0) or 1.0
        dp = inf.get("dept") or ""
        maxc = float(R["max_cover"].get(dp, R["max_cover_default"]))
        cost = s.get("cost") or costs.get(it) or 0
        price = (s.get("price") / 1.18 if s.get("price") else None) or prices_any.get(it) or 0
        row = dict(store=st, store_name=(all_stores.get(st) or {}).get("name", st), item=it, description=inf.get("description") or "",
                   supplier=sup, supplier_name=sup_names.get(sup, ""), dept=dp, section=inf.get("section") or "",
                   speed=round(d, 2) if d is not None else None, on_hand=oh, on_hand_from=oh_src, on_order=on_order,
                   lead=L, lead_known=sup in lead_by, review=Rv, pcb=pcb, cost=cost, price=price,
                   proposed=prop.get(k), abc=abc.get(k, "C"))
        status = (s.get("status") or "").upper()
        rng = (s.get("range_code") or "")
        avail = max(oh, 0.0) + on_order
        row["cover_days"] = round(avail / d, 1) if d else None
        # ---- stops
        if status in R["blocked_status"] or rng == "007":
            row.update(decision="stop", qty=0, reason=f"Not orderable ({'range 007' if rng == '007' else 'status ' + status}): do not order.")
        elif k in aged:
            age, val = aged[k]
            row.update(decision="stop", qty=0, reason=f"Aged (DP) stock here ({int(age or 0)} days, PKR {val:,.0f}): sell it down or move it before ordering.")
        elif d is not None and d <= 0 and oh > 0:
            row.update(decision="stop", qty=0, reason=f"Not selling: {oh:,.0f} in stock and no sales in the period.")
        elif d is None or d <= 0:
            row.update(decision="check", qty=0, reason="No sales history for this item here: order only the shelf minimum if it is new.")
        else:
            T, cls, S, uplift, shelf = target_for(k, d, L, Rv)
            need = T - avail
            row.update(target=round(T, 1), safety=S, uplift=uplift)
            if need <= 0:
                row.update(decision="none", qty=0, reason=f"Enough stock: {avail:,.0f} on hand and on order covers {avail / d:.0f} days "
                                                           f"(lead {L:.0f} + next order {Rv:.0f} + safety {S} days).")
            else:
                q = math.ceil(need / pcb) * pcb
                cap = max(0.0, math.floor((maxc * d - avail) / pcb) * pcb)
                why = (f"Sells {d:.1f}/day{' (×' + format(uplift, 'g') + ' leaflet)' if uplift > 1 else ''}; needs {T:.0f} for "
                       f"{L:.0f} lead + {Rv:.0f} to next order + {S} safety days; has {avail:,.0f}.")
                if q > cap and cap >= 0:
                    why += f" Capped at {maxc:.0f} days of cover."
                    q = cap
                row.update(decision="order" if q > 0 else "none", qty=q, reason=why + (f" {q:,.0f} = {q / pcb:.0f} case(s) of {pcb:g}." if pcb > 1 and q else ""))
                if oh <= d * L:              # runs out before the delivery arrives
                    short_days = max(0.0, L - (max(oh, 0) / d))
                    row["lost_risk"] = round(short_days * d * (price or 0))
        if oh < 0:
            row["reason"] = f"Negative stock ({oh:,.0f}): recount first. " + row["reason"]
            if row["decision"] in ("none", "order"):
                row["flag"] = "recount"
        if z.get("open_lpo") and row["decision"] == "order" and z.get("delivery_date") and z["delivery_date"] < today:
            row["reason"] += f" LPO {z['open_lpo']} is late: chase it."
        lines.append(row)

    # ---- IST: other stores with more than they need send it first
    by_item = defaultdict(list)
    for (st, it), s in stock_all.items():
        if (s.get("qty") or 0) > 0:
            by_item[it].append(st)
    city = {c: (s.get("city") or "").lower() for c, s in all_stores.items()}
    donors_used = defaultdict(float)
    for row in sorted(lines, key=lambda r: -(r.get("lost_risk") or 0)):
        if row["decision"] != "order" or row["qty"] <= 0:
            continue
        it, st = row["item"], row["store"]
        need = row["qty"]
        best = None
        for s2 in by_item.get(it, []):
            if s2 == st:
                continue
            k2 = (s2, it)
            oh2 = float(stock_all[k2].get("qty") or 0) - donors_used[k2]
            d2 = rate(k2) or 0.0
            is_aged = k2 in aged
            if R["ist_same_city"] and city.get(s2) != city.get(st) and not is_aged:
                continue
            keep = max(d2 * float(R["ist_donor_keep_days"]), 0.0)
            if d2 > 0:
                sup2 = row["supplier"]
                L2 = float(lead_by.get(sup2) or R["lead_days"])
                keep = max(keep, target_for(k2, d2, L2, float(R["review_days"]))[0])
            excess = oh2 - keep
            if excess < float(R["ist_min_units"]):
                continue
            score = (1 if is_aged else 0, 1 if city.get(s2) == city.get(st) else 0, excess)
            if best is None or score > best[0]:
                best = (score, s2, excess, is_aged)
        if best:
            _, s2, excess, is_aged = best
            q = float(min(excess, need))
            q = math.floor(q)
            if q >= float(R["ist_min_units"]):
                donors_used[(s2, it)] += q
                rest = max(0.0, need - q)
                pcb = row["pcb"]
                rest = math.ceil(rest / pcb) * pcb if rest > 0 else 0
                row.update(ist_from=s2, ist_from_name=(all_stores.get(s2) or {}).get("name", s2), ist_qty=q,
                           decision="ist" if rest == 0 else "ist_order", qty=rest)
                row["reason"] = (f"{row['ist_from_name']} has {excess:,.0f} more than it needs{' (aged stock)' if is_aged else ''}: "
                                 f"transfer {q:,.0f} first" + (f", then order {rest:,.0f}." if rest else ", no LPO needed. ") + " " + row["reason"])

    # ---- a proposed order: compare with the suggestion
    tol = float(R["tolerance_pct"]) / 100
    for row in lines:
        p = row.get("proposed")
        if p is None:
            continue
        s = row["qty"]
        if row["decision"] == "stop":
            row["verdict"] = "remove"
        elif row["decision"] == "check":
            row["verdict"] = "check"
        elif row["decision"] == "ist":
            row["verdict"] = "ist"
        elif row["decision"] in ("none",) and p > 0:
            row["verdict"] = "remove"
        elif s == 0 and p == 0:
            row["verdict"] = "ok"
        elif s and abs(p - s) <= tol * s:
            row["verdict"] = "ok"
        elif p > s:
            row["verdict"] = "reduce"
        else:
            row["verdict"] = "increase"
        row["change"] = s - p

    for row in lines:
        row["value"] = round((row.get("qty") or 0) * (row.get("cost") or 0))
        if row.get("proposed") is not None:
            row["proposed_value"] = round(row["proposed"] * (row.get("cost") or 0))
    order_rank = {"order": 0, "ist_order": 1, "ist": 2, "check": 3, "stop": 4, "none": 5}
    lines.sort(key=lambda r: (order_rank.get(r["decision"], 9), -(r.get("lost_risk") or 0), -(r.get("value") or 0)))
    n_no_lead = len({r["supplier"] for r in lines if not r["lead_known"] and r["supplier"]})
    if n_no_lead:
        notes.append(f"{n_no_lead} supplier(s) have no LPO history: lead time {R['lead_days']} days assumed (add the LPO list).")
    if not zero and not leaf:
        notes.append("On-order quantities are not known yet (add the zero stock sheet; item-level LPO lines will make this exact).")
    summ = dict(lines=len(lines),
                order=sum(1 for r in lines if r["decision"] in ("order", "ist_order")),
                ist=sum(1 for r in lines if r.get("ist_qty")),
                stop=sum(1 for r in lines if r["decision"] == "stop"),
                none=sum(1 for r in lines if r["decision"] == "none"),
                value=sum(r["value"] for r in lines),
                ist_value=round(sum((r.get("ist_qty") or 0) * (r.get("cost") or 0) for r in lines)),
                lost_risk=sum(r.get("lost_risk") or 0 for r in lines))
    if prop:
        summ.update(proposed_value=sum(r.get("proposed_value") or 0 for r in lines),
                    remove=sum(1 for r in lines if r.get("verdict") == "remove"),
                    reduce=sum(1 for r in lines if r.get("verdict") == "reduce"),
                    increase=sum(1 for r in lines if r.get("verdict") == "increase"),
                    ok=sum(1 for r in lines if r.get("verdict") == "ok"))
        summ["saving"] = summ["proposed_value"] - summ["value"]
    return dict(lines=lines[:limit], summary=summ, notes=notes, rules=R, check=bool(prop),
                truncated=len(lines) > limit, as_of=str(today))


def parse_proposed(text: str, default_store: str | None = None) -> list[dict]:
    """Pasted order lines: item, qty (and store), in any column order; a header row is optional."""
    import re
    out = []
    rows = [re.split(r"\t|,|;|\s{2,}", ln.strip()) for ln in (text or "").splitlines() if ln.strip()]
    if not rows:
        return out
    head = [c.strip().lower() for c in rows[0]]
    has_head = any(re.search(r"item|article|code|qty|quantity|store|site", c) for c in head)
    ix = dict(item=None, qty=None, store=None)
    if has_head:
        for i, c in enumerate(head):
            if ix["item"] is None and re.search(r"item|article|code|nart", c) and "desc" not in c:
                ix["item"] = i
            elif ix["qty"] is None and re.search(r"qty|quantity|order|units|pcs", c):
                ix["qty"] = i
            elif ix["store"] is None and re.search(r"store|site|branch", c):
                ix["store"] = i
        rows = rows[1:]
    for r in rows:
        nums = [c for c in r if re.fullmatch(r"\d+(\.\d+)?", c.strip())]
        item = r[ix["item"]].strip() if ix["item"] is not None and ix["item"] < len(r) else (nums[0] if nums else "")
        qty = r[ix["qty"]].strip() if ix["qty"] is not None and ix["qty"] < len(r) else (nums[-1] if len(nums) > 1 else "")
        store = r[ix["store"]].strip() if ix["store"] is not None and ix["store"] < len(r) else (default_store or "")
        try:
            q = float(str(qty).replace(",", ""))
        except ValueError:
            continue
        item = re.sub(r"\.0+$", "", item)
        if item:
            out.append(dict(store=store, item=item, qty=q))
    return out
