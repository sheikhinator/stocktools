"""Today's jobs for a store / department / section: concrete lists built from the data, most urgent first.
Each job says what to do, how many items, what it is worth in PKR, and carries its item list."""

from __future__ import annotations

from dataclasses import dataclass, field

from stockcompass.db import Database

from . import extra as X
from .core import L, Scope, dp_items, fmt_pkr, leaflet_rows, lpo_rows, negative_items, oos_items


@dataclass
class Job:
    key: str
    title: str
    why: str
    count: int
    value: float | None
    value_label: str
    rows: list[dict]
    columns: list[tuple[str, str]]
    level: str = "warn"          # bad | warn | info
    goto: str = ""
    done: bool = False


def jobs(db: Database, scope: Scope) -> list[Job]:
    out: list[Job] = []
    oos = oos_items(db, scope)
    not_ord = [r for r in oos if not r["on_order"]]
    if not_ord:
        out.append(Job("order_now", L("Order these now: out of stock, nothing on order",
                                      "یہ ابھی آرڈر کریں: آؤٹ آف اسٹاک، کوئی آرڈر نہیں"),
                       L("Nothing is on the way for these items. Leaflet items and best sellers first.",
                         "ان آئٹمز کا کچھ بھی راستے میں نہیں۔"),
                       len(not_ord), sum(r["lost_per_day"] for r in not_ord), L("lost per day", "روزانہ نقصان"), not_ord,
                       [("store_name", "text"), ("item", "text"), ("description", "text"), ("section_name", "text"),
                        ("reason", "text"), ("dlyavg", "num"), ("lost_per_day", "money"), ("order_mode", "text"),
                        ("supplier_name", "text")], "bad", "stock:oos"))
    from .orders import lpo_checks
    chk = lpo_checks(db, scope.stores if scope.stores else ([r[0] for r in db.q("SELECT code FROM stores WHERE " + scope.store_sql("code")[0],
                                                                                      scope.store_sql("code")[1])] if scope.has_store_filter() else None),
                     scope.dept, scope.section)
    if chk.get("ready"):
        g = {x["key"]: x for x in chk["groups"]}
        cols = [("store_name", "text"), ("item", "text"), ("description", "text"), ("stock", "num"), ("on_order", "num"),
                ("speed", "num"), ("order_days", "text"), ("why", "text"), ("value", "money")]
        urgent = g["zero_not_ordered"]["rows"] + g["runs_out"]["rows"]
        if urgent:
            out.append(Job("order_sheet", L("Today's order sheet: selling items with nothing on order", "آج کی آرڈر شیٹ"),
                           L("From GIMA LPO support: at zero stock or running out before a delivery could arrive.", "جیما ایل پی او سپورٹ سے۔"),
                           len(urgent), sum(r["value"] or 0 for r in urgent), L("sales at risk / day", "روزانہ خطرہ"), urgent, cols, "bad", "advisor"))
        over = g["over_ordered"]["rows"] + g["not_selling_on_order"]["rows"]
        if over:
            out.append(Job("over_order", L("Reduce or cancel orders: over-ordered or not selling", "زیادہ آرڈر کم کریں"),
                           L("Stock plus open order is above the maximum cover, or the item has not sold in 6 full weeks.", "زیادہ کور یا بکری نہیں۔"),
                           len(over), sum(r["value"] or 0 for r in over), L("stock value too much", "زائد اسٹاک"), over, cols, "warn", "advisor"))
    lf = [r for r in leaflet_rows(db, scope) if r["zero"]]
    if lf:
        out.append(Job("leaflet", L("Leaflet / theme items out of stock", "لیفلیٹ آئٹمز آؤٹ آف اسٹاک"),
                       L("Customers come for these. They count in the BC leaflet zero stock indicator.",
                         "یہ بی سی لیفلیٹ انڈیکیٹر میں گنے جاتے ہیں۔"),
                       len(lf), None, "", lf,
                       [("store_name", "text"), ("theme_name", "text"), ("item", "text"), ("description", "text"),
                        ("on_order_qty", "num"), ("status", "text")], "bad", "promos"))
    chase = [r for r in oos if r["on_order"] and (r["late"] or r["reason_group"] == "supplier")]
    lpo, snap = lpo_rows(db, scope)
    late = [r for r in lpo if r["late_days"]]
    if chase or late:
        rows = [dict(store_name=r["store_name"], what=f"{r['item']} {r['description'] or ''}", supplier_name=r["supplier_name"],
                     due=r["delivery_date"], value=r["lost_per_day"], note=r["reason"]) for r in chase]
        rows += [dict(store_name=r["store_name"], what=f"LPO {r['lpo_no']}", supplier_name=r["supplier_name"],
                      due=r["delivery_date"], value=r["value"], note=L(f"{r['late_days']} days late", f"{r['late_days']} دن تاخیر"))
                 for r in late]
        out.append(Job("chase", L("Chase late deliveries", "تاخیر شدہ ترسیل کی پیروی کریں"),
                       L("On order but not delivered: call the supplier or buyer.", "آرڈر ہوا مگر نہیں پہنچا۔"),
                       len(rows), sum(r["value"] or 0 for r in late), L("orders not delivered", "غیر موصول آرڈرز"), rows,
                       [("store_name", "text"), ("what", "text"), ("supplier_name", "text"), ("due", "date"),
                        ("note", "text"), ("value", "money")], "warn", "orders:late"))
    neg = negative_items(db, scope)
    if neg:
        out.append(Job("negative", L("Fix negative stock", "منفی اسٹاک ٹھیک کریں"),
                       L("Each line says the likely cause and the fix (count, receiving, or item setup for NI).",
                         "ہر لائن میں وجہ اور حل۔"),
                       len(neg), sum(abs(r["value"] or 0) for r in neg), L("at cost", "لاگت پر"), neg,
                       [("store_name", "text"), ("item", "text"), ("description", "text"), ("qty", "num"),
                        ("status", "text"), ("cause", "text"), ("action", "text")], "warn", "stock:neg"))
    dp = [r for r in dp_items(db, scope) if r["days_to_next"] is not None and r["days_to_next"] <= 30]
    if dp:
        out.append(Job("dp_step", L("Clear aged (DP) items before their provision steps up",
                                    "پروویژن بڑھنے سے پہلے ایجڈ آئٹمز نکالیں"),
                       L("Sell, move or return these within 30 days to avoid extra provision.", "30 دن میں نکالیں۔"),
                       len(dp), sum(r["extra_provision"] for r in dp), L("extra provision avoided", "اضافی پروویژن سے بچت"),
                       sorted(dp, key=lambda r: -r["extra_provision"]),
                       [("store_name", "text"), ("item", "text"), ("description", "text"), ("qty", "num"),
                        ("value", "money"), ("days_to_next", "int"), ("extra_provision", "money"), ("route", "text")],
                       "warn", "stock:dp"))
    moves = X.ist(db, scope)
    if scope.stores:
        names = {n for c, n in db.q("SELECT code, name FROM stores") if c in scope.stores}
        moves = [m for m in moves if m["from_store"] in names or m["to_store"] in names]
    if moves:
        out.append(Job("ist", L("Move stock to stores that are out of it", "اسٹاک ان اسٹورز کو بھیجیں جہاں ختم ہے"),
                       L("Aged or idle stock here, out of stock and selling there.", "یہاں فالتو، وہاں ختم۔"),
                       len(moves), sum(m["value"] or 0 for m in moves), L("stock to move", "منتقل کرنے کا اسٹاک"), moves,
                       [("item", "text"), ("description", "text"), ("from_store", "text"), ("to_store", "text"),
                        ("qty", "num"), ("why", "text")], "info", "stock:move"))
    w, p = scope.store_sql("b.store")
    blocked = db.qd(f"""SELECT b.*, i.description, s.name store_name FROM blocked_item b LEFT JOIN items i USING (item)
                        LEFT JOIN stores s ON s.code=b.store WHERE (b.qty2 > 0) AND b.qty2 >= b.qty1
                        AND b.import_id IN (SELECT max(import_id) FROM imports WHERE report_type='blocked_007'
                        GROUP BY stores) AND {w}""", p)
    if scope.dept or scope.section:
        wi, pi = scope.item_sql()
        keep = {r[0] for r in db.q(f"SELECT item FROM items i WHERE {wi}", pi)}
        blocked = [r for r in blocked if r["item"] in keep]
    if blocked:
        out.append(Job("blocked", L("Blocked (007) stock that has not moved", "بلاک (007) اسٹاک جو بالکل نہیں ہلا"),
                       L("Return to the supplier or write off after a count.", "سپلائر کو واپس یا گنتی کے بعد رائٹ آف۔"),
                       len(blocked), sum(r["value2"] or 0 for r in blocked), L("at cost", "لاگت پر"), blocked,
                       [("store_name", "text"), ("item", "text"), ("description", "text"), ("qty2", "num"),
                        ("value2", "money")], "info", "stock:blocked"))
    sl, _ = X.sleeping(db, scope)
    if sl:
        out.append(Job("sleeping", L("Stock not selling (BC no-sales rule)", "اسٹاک جو نہیں بک رہا"),
                       L("Check it is on the shelf and priced; move, promote or return it.", "شیلف اور قیمت چیک کریں۔"),
                       len(sl), sum(r["value"] for r in sl), L("at cost", "لاگت پر"), sl,
                       [("store_name", "text"), ("item", "text"), ("description", "text"), ("qty", "num"),
                        ("value", "money"), ("last_sale", "date")], "info", "stock:sleeping"))
    return out


def job_key(scope: Scope, job: str, day) -> str:
    return f"{day:%Y-%m-%d}|{','.join(scope.stores or [])}|{scope.dept or ''}|{scope.section or ''}|{job}"


def summary_text(j: Job) -> str:
    v = f" · {fmt_pkr(j.value)} {j.value_label}" if j.value else ""
    return f"{j.count:,} {L('items', 'آئٹمز')}{v}"
