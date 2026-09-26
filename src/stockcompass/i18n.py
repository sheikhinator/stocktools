"""English / Urdu text. Urdu wording should be reviewed by a native speaker (see docs)."""

from __future__ import annotations

_lang = "en"

T: dict[str, tuple[str, str]] = {
    # navigation
    "app": ("Stock Compass", "اسٹاک کمپاس"),
    "tagline": ("Carrefour Pakistan", "کیریفور پاکستان"),
    "nav_home": ("Home", "ہوم"),
    "nav_sales": ("Sales", "سیلز"),
    "nav_stock": ("Stock health", "اسٹاک کی صحت"),
    "nav_orders": ("Orders", "آرڈرز"),
    "nav_score": ("BC scorecard", "بی سی اسکور کارڈ"),
    "nav_import": ("Add reports", "رپورٹس شامل کریں"),
    "nav_health": ("Data checks", "ڈیٹا کی جانچ"),
    "nav_settings": ("Settings", "سیٹنگز"),
    # filters
    "where": ("Where", "کہاں"),
    "all_stores": ("All stores", "تمام اسٹورز"),
    "hypers": ("All hypermarkets", "تمام ہائپر مارکیٹس"),
    "supers": ("All supermarkets", "تمام سپر مارکیٹس"),
    "mylis": ("All Mylis", "تمام مائلی"),
    "department": ("Department", "ڈیپارٹمنٹ"),
    "section": ("Section", "سیکشن"),
    "all_depts": ("All departments", "تمام ڈیپارٹمنٹس"),
    "all_sections": ("All sections", "تمام سیکشنز"),
    "view_as": ("View as", "بطور دیکھیں"),
    "language": ("Language", "زبان"),
    # common
    "search": ("Search…", "تلاش…"),
    "export": ("Export to Excel", "ایکسل میں ایکسپورٹ"),
    "rows": ("rows", "قطاریں"),
    "total": ("Total", "کل"),
    "close": ("Close", "بند کریں"),
    "how": ("How is this calculated?", "یہ کیسے نکالا گیا؟"),
    "source": ("Source", "ذریعہ"),
    "as_of": ("As of", "بتاریخ"),
    "formula": ("Calculation", "حساب"),
    "definition": ("What it means", "مطلب"),
    "no_data": ("No data yet. Add the report that feeds this view.", "ابھی ڈیٹا نہیں۔ اس کے لیے رپورٹ شامل کریں۔"),
    "needs": ("Needs", "درکار"),
    "open_item": ("Double-click a row to see the item in every store.", "آئٹم کی مکمل تفصیل کے لیے قطار پر ڈبل کلک کریں۔"),
    "yes": ("Yes", "ہاں"),
    "no": ("No", "نہیں"),
    # home
    "greet_ho": ("Good day, head office", "خوش آمدید، ہیڈ آفس"),
    "greet_store": ("Good day", "خوش آمدید"),
    "home_sub": ("The numbers that matter most, and what needs attention.", "اہم ترین نمبرز، اور کن چیزوں پر توجہ درکار ہے۔"),
    "things_to_know": ("Things you should know", "اہم باتیں"),
    "zs_trend": ("Zero stock % by day", "روزانہ زیرو اسٹاک %"),
    "store_ranking": ("Stores: zero stock % this month", "اسٹورز: اس ماہ زیرو اسٹاک %"),
    "data_fresh": ("Latest data", "تازہ ترین ڈیٹا"),
    "welcome_title": ("Welcome to Stock Compass", "اسٹاک کمپاس میں خوش آمدید"),
    "welcome_text": ("Start by adding your reports: GIMA RealTime, zero stock and negative stock sheets, the BC "
                     "workbook, the DP workbook, LPO list, leaflet workbook. Drop any Excel file; Stock Compass "
                     "works out what it is.",
                     "اپنی رپورٹس شامل کر کے شروع کریں: جیما ریئل ٹائم، زیرو اسٹاک اور منفی اسٹاک شیٹس، بی سی ورک بک، "
                     "ڈی پی ورک بک، ایل پی او لسٹ، لیفلیٹ ورک بک۔ کوئی بھی ایکسل فائل ڈالیں، اسٹاک کمپاس خود پہچان لے گا۔"),
    # KPI labels
    "kpi_zero_stock": ("Zero stock % (month to date)", "زیرو اسٹاک % (ماہ اب تک)"),
    "kpi_not_on_order": ("Out of stock, not on order", "آؤٹ آف اسٹاک، آرڈر نہیں"),
    "kpi_lost_sales": ("Sales lost per day", "روزانہ ضائع سیلز"),
    "kpi_negative": ("Negative stock items", "منفی اسٹاک آئٹمز"),
    "kpi_dp_stock": ("Aged (DP) stock", "ایجڈ (DP) اسٹاک"),
    "kpi_late_lpo": ("Late orders", "تاخیر شدہ آرڈرز"),
    "kpi_bc_greens": ("BC targets met", "بی سی اہداف پورے"),
    # stock page
    "stock_title": ("Stock health", "اسٹاک کی صحت"),
    "stock_sub": ("Is the right stock on the shelf, and is aged (DP) stock under control?",
                  "کیا صحیح اسٹاک شیلف پر ہے، اور کیا ایجڈ (DP) اسٹاک قابو میں ہے؟"),
    "tab_zero": ("Zero stock", "زیرو اسٹاک"),
    "tab_oos": ("Out-of-stock items", "آؤٹ آف اسٹاک آئٹمز"),
    "tab_neg": ("Negative stock", "منفی اسٹاک"),
    "tab_dp": ("Aged / DP stock", "ایجڈ / DP اسٹاک"),
    "tab_blocked": ("Blocked (007)", "بلاک (007)"),
    "tab_leaflet": ("Leaflet items", "لیفلیٹ آئٹمز"),
    "why_oos": ("Why items are out of stock", "آئٹمز آؤٹ آف اسٹاک کیوں ہیں"),
    "oos_list": ("Out-of-stock items: not on order first, then biggest lost sales",
                 "آؤٹ آف اسٹاک آئٹمز: پہلے جن کا آرڈر نہیں، پھر سب سے زیادہ نقصان"),
    "neg_by_cause": ("Negative stock by cause", "وجہ کے حساب سے منفی اسٹاک"),
    "dp_by_bucket": ("DP stock by ageing bucket", "ایجنگ بکٹ کے حساب سے DP اسٹاک"),
    "dp_by_route": ("Best next step for DP stock", "DP اسٹاک کے لیے بہترین قدم"),
    "dp_list": ("DP items: biggest value first", "DP آئٹمز: سب سے زیادہ مالیت پہلے"),
    # orders
    "orders_title": ("Orders (LPO)", "آرڈرز (ایل پی او)"),
    "orders_sub": ("Late deliveries, purged orders and orders that look duplicated.",
                   "تاخیر سے ترسیل، منسوخ شدہ آرڈرز اور دہرے لگنے والے آرڈرز۔"),
    "tab_late": ("Late orders", "تاخیر شدہ آرڈرز"),
    "tab_purge": ("Purge by store", "اسٹور کے حساب سے پرج"),
    "tab_all_lpo": ("All orders", "تمام آرڈرز"),
    # score
    "score_title": ("BC scorecard", "بی سی اسکور کارڈ"),
    "score_sub": ("Every BC indicator per store, green when the target is met. Click a cell to see why.",
                  "ہر اسٹور کے لیے بی سی انڈیکیٹرز، ہدف پورا ہونے پر سبز۔ وجہ دیکھنے کے لیے خانے پر کلک کریں۔"),
    "hyper": ("Hypermarkets", "ہائپر مارکیٹس"),
    "super": ("Supermarkets", "سپر مارکیٹس"),
    "myli": ("Mylis", "مائلی"),
    "target": ("Target", "ہدف"),
    "greens": ("Greens", "سبز"),
    "bc_count": ("BC count", "بی سی گنتی"),
    "our_calc": ("Our calculation", "ہمارا حساب"),
    # import
    "import_title": ("Add reports", "رپورٹس شامل کریں"),
    "import_sub": ("Drop Excel, CSV or text files here, or paste data. Stock Compass recognises each sheet, "
                   "shows what it found, and asks only when it is not sure.",
                   "ایکسل، سی ایس وی یا ٹیکسٹ فائلیں یہاں ڈالیں یا ڈیٹا پیسٹ کریں۔ اسٹاک کمپاس ہر شیٹ پہچانتا ہے "
                   "اور صرف تب پوچھتا ہے جب یقین نہ ہو۔"),
    "choose_files": ("Choose files…", "فائلیں منتخب کریں…"),
    "paste": ("Paste data", "ڈیٹا پیسٹ کریں"),
    "import_now": ("Import", "امپورٹ کریں"),
    "clear": ("Clear", "صاف کریں"),
    "col_file": ("File", "فائل"),
    "col_sheet": ("Sheet", "شیٹ"),
    "col_type": ("Recognised as", "پہچانا گیا"),
    "col_conf": ("Sure?", "یقین"),
    "col_store": ("Store", "اسٹور"),
    "col_date": ("Report date", "رپورٹ کی تاریخ"),
    "col_rows": ("Rows", "قطاریں"),
    "col_note": ("Notes", "نوٹس"),
    "history": ("Imported so far", "اب تک امپورٹ شدہ"),
    "delete_import": ("Remove selected import", "منتخب امپورٹ ہٹائیں"),
    "drop_here": ("Drop report files here", "رپورٹ فائلیں یہاں ڈالیں"),
    "working": ("Working…", "کام جاری ہے…"),
    "done": ("Done", "مکمل"),
    "pick_store": ("Choose store", "اسٹور منتخب کریں"),
    "already": ("Imported before; importing again replaces it.", "پہلے امپورٹ ہو چکی؛ دوبارہ امپورٹ پرانی کو بدل دے گی۔"),
    # health
    "health_title": ("Data checks", "ڈیٹا کی جانچ"),
    "health_sub": ("Everything Stock Compass noticed while reading your files: broken days, missing stores, "
                   "numbers that don't add up.",
                   "فائلیں پڑھتے ہوئے اسٹاک کمپاس نے جو کچھ دیکھا: خراب دن، غائب اسٹورز، نہ ملنے والے نمبرز۔"),
    # settings
    "settings_title": ("Settings", "سیٹنگز"),
    "stores": ("Stores", "اسٹورز"),
    "targets": ("BC targets", "بی سی اہداف"),
    "dp_rules": ("DP provision rules", "DP پروویژن قواعد"),
    "thresholds": ("Thresholds", "حدود"),
    "codes": ("Codes", "کوڈز"),
    "urdu_font": ("Urdu font", "اردو فونٹ"),
    "save": ("Save", "محفوظ کریں"),
    "add_alias": ("Add a name for the selected store", "منتخب اسٹور کے لیے نام شامل کریں"),
    # item
    "item360": ("Item overview", "آئٹم کا جائزہ"),
    "stock_by_store": ("Stock by store", "اسٹور کے حساب سے اسٹاک"),
    "sales_hist": ("Sales", "سیلز"),
    "zero_hist": ("Zero stock history", "زیرو اسٹاک کی تاریخ"),
    "dp_hist": ("DP / ageing", "DP / ایجنگ"),
}

# Column headers used across tables
COLS: dict[str, tuple[str, str]] = {
    "store": ("Store", "اسٹور"), "store_name": ("Store", "اسٹور"), "item": ("Item", "آئٹم"),
    "description": ("Description", "تفصیل"), "section_name": ("Section", "سیکشن"), "section": ("Section", "سیکشن"),
    "dept": ("Dept", "ڈیپارٹمنٹ"), "qty": ("Qty", "مقدار"), "value": ("Value (PKR)", "مالیت"),
    "reason": ("GIMA reason", "جیما وجہ"), "action": ("What to do", "کیا کریں"), "on_order": ("On order", "آرڈر میں"),
    "days_out": ("Days since last sale", "آخری سیل کے دن"), "dlyavg": ("Sells / day", "روزانہ فروخت"),
    "lost_per_day": ("Lost / day (PKR)", "روزانہ نقصان"), "lost_to_date": ("Lost so far (PKR)", "اب تک نقصان"),
    "supplier_name": ("Supplier", "سپلائر"), "order_mode": ("Ordering", "آرڈرنگ"), "delivery_date": ("Due", "متوقع"),
    "status": ("Status", "اسٹیٹس"), "cause": ("Likely cause", "ممکنہ وجہ"), "age_days": ("Age (days)", "عمر (دن)"),
    "provision": ("DP provision", "DP پروویژن"), "prov_pct": ("Provision %", "پروویژن %"),
    "bucket": ("Ageing bucket", "ایجنگ بکٹ"), "days_to_next": ("Days to next step", "اگلے مرحلے تک دن"),
    "extra_provision": ("Extra provision if not cleared", "اضافی پروویژن"), "route": ("Best next step", "بہترین قدم"),
    "route_why": ("Why", "کیوں"), "lpo_no": ("LPO", "ایل پی او"), "lpo_date": ("Ordered", "آرڈر"),
    "late_days": ("Days late", "دن تاخیر"), "order_type": ("Type", "قسم"), "deleted": ("Purged", "منسوخ"),
    "lpos": ("Orders", "آرڈرز"), "purged": ("Purged", "منسوخ"), "purge_pct": ("Purge %", "پرج %"),
    "received_value_pct": ("Received value %", "موصول مالیت %"), "late": ("Late", "تاخیر"),
    "mtd_pct": ("Zero stock % MTD", "زیرو اسٹاک % ماہ"), "day_pct": ("Latest day %", "آخری دن %"),
    "zero_today": ("Zero today", "آج زیرو"), "items_today": ("Items today", "آج آئٹمز"),
    "theme_name": ("Theme", "تھیم"), "stock_qty": ("Stock", "اسٹاک"), "on_order_qty": ("On order qty", "آرڈر مقدار"),
    "below_cost": ("Below cost", "لاگت سے کم"), "zero": ("Zero", "زیرو"), "qty1": ("Stock (first date)", "اسٹاک (پہلی تاریخ)"),
    "qty2": ("Stock (latest)", "اسٹاک (تازہ)"), "value1": ("Value (first)", "مالیت (پہلی)"),
    "value2": ("Value (latest)", "مالیت (تازہ)"), "cost": ("Cost", "لاگت"), "price": ("Price", "قیمت"),
    "sales": ("Net sales", "نیٹ سیلز"), "margin": ("Margin", "مارجن"), "stock": ("Stock", "اسٹاک"),
    "date_from": ("From", "سے"), "date_to": ("To", "تک"), "snap_date": ("Date", "تاریخ"), "open_lpo": ("Open LPO", "کھلا ایل پی او"),
    "level": ("Level", "سطح"), "message": ("What we found", "کیا ملا"), "count": ("Count", "تعداد"),
    "file_name": ("File", "فائل"), "sheet": ("Sheet", "شیٹ"), "report_type": ("Report", "رپورٹ"),
    "snapshot_date": ("Report date", "رپورٹ کی تاریخ"), "rows": ("Rows", "قطاریں"), "imported_at": ("Imported", "امپورٹ"),
    "summary": ("Summary", "خلاصہ"), "stores": ("Stores", "اسٹورز"), "leaflet": ("Leaflet", "لیفلیٹ"),
    "name": ("Name", "نام"), "budget": ("Budget", "بجٹ"), "vs_budget": ("vs budget %", "بجٹ کے مقابلے %"),
    "ly": ("Last year", "پچھلا سال"), "growth": ("Growth %", "اضافہ %"), "share": ("Share %", "حصہ %"),
    "oos": ("OOS % (BO)", "آؤٹ آف اسٹاک %"), "waste": ("Waste %", "ویسٹ %"), "promo": ("Promo sales %", "پروموشن %"),
    "stock_value": ("Stock value", "اسٹاک مالیت"), "sales_cy": ("Sales this year", "اس سال سیلز"),
    "sales_ly": ("Sales last year", "پچھلے سال سیلز"), "b2b": ("Bulk (B2B)", "بلک (B2B)"),
    "b2b_share": ("Bulk share %", "بلک حصہ %"), "b2b_margin": ("Bulk margin %", "بلک مارجن %"),
    "suppliers": ("Suppliers", "سپلائرز"), "families": ("Families", "فیملیز"), "purchase": ("Purchases", "خریداری"),
    "margin_pct": ("Margin %", "مارجن %"), "abc": ("ABC", "اے بی سی"), "family_name": ("Family", "فیملی"),
    "qty_cy": ("Qty this year", "اس سال مقدار"), "qty_ly": ("Qty last year", "پچھلے سال مقدار"),
}


def set_lang(lang: str):
    global _lang
    _lang = "ur" if lang == "ur" else "en"


def lang() -> str:
    return _lang


def is_rtl() -> bool:
    return _lang == "ur"


def t(key: str) -> str:
    v = T.get(key)
    if not v:
        return key
    return v[1] if _lang == "ur" and v[1] else v[0]


def col(key: str) -> str:
    v = COLS.get(key)
    if not v:
        return key.replace("_", " ").capitalize()
    return v[1] if _lang == "ur" else v[0]
