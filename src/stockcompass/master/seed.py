"""Built-in master data: stores, departments, sections, codes, BC targets and DP rules.

Everything here is the *starting point*. All of it is copied into the database on first run and
can then be edited in Settings (or learned from imported files). Nothing here is company report data.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------------------------
# Stores. Identity = GIMA code. Corporate codes are kept only as hints (they are NOT unique).
# format: H = hypermarket, S = supermarket, M = Myli (H&B, DPH only, sits inside a host store)
# ---------------------------------------------------------------------------------------------
STORES: list[dict] = [
    dict(code="500", name="Fortress", short="FRT", format="H", city="Lahore", region="Lahore",
         corp=["651"], aliases=["FOR", "FRT", "Fortress", "Fortress Stadium", "LAH Fortress"]),
    dict(code="502", name="WTC Islamabad", short="WTC", format="H", city="Islamabad", region="North",
         corp=["661"], aliases=["WTC", "ISL WTC", "World Trade Center", "Giga Mall"]),
    dict(code="503", name="Emporium Mall", short="EMP", format="H", city="Lahore", region="Lahore",
         corp=["660"], aliases=["EMP", "Emporium", "Emporium Mall", "LAH Emporium Mall"]),
    dict(code="504", name="Packages Mall", short="PKG", format="H", city="Lahore", region="Lahore",
         corp=["656"], aliases=["PKG", "PKGS", "Packages", "Packages Mall", "LAH Packages"]),
    dict(code="505", name="Lucky One", short="LUK", format="H", city="Karachi", region="Karachi",
         corp=["654"], aliases=["LUK", "Lucky One", "Lucky One Mall", "KCH Lucky One"]),
    dict(code="506", name="Lyallpur Galleria", short="LYL", format="H", city="Faisalabad", region="North",
         corp=["663"], aliases=["LYL", "Lyallpur", "Lyallpur Galleria", "FAI Lyallpur Galleria"]),
    dict(code="P03", name="Gujranwala", short="GUJ", format="H", city="Gujranwala", region="North",
         corp=["657"], aliases=["GUJ", "Gujranwala", "Steel Casting", "GUJ Steel Casting"]),
    dict(code="P06", name="D-12 Islamabad", short="D12", format="S", city="Islamabad", region="North",
         corp=["661"], aliases=["D12", "D-12", "ISL D12", "D12 (P06)"]),
    dict(code="P07", name="DHA Rahbar", short="DHA11", format="S", city="Lahore", region="Lahore",
         corp=["659"], aliases=["DHA11", "DHA-011", "DHA 11", "DHA Rahbar", "Rahbar", "Rahber", "DHA Rahber"]),
    dict(code="P08", name="DHA Phase 7", short="DHA07", format="S", city="Lahore", region="Lahore",
         corp=["658"], aliases=["DHA07", "DHA-07", "DHA 7", "DHA 07", "DHA Phase 7", "DHA Ph 07", "Phase 7"]),
    dict(code="P09", name="Askari 10", short="ASK", format="S", city="Lahore", region="Lahore",
         corp=["660"], aliases=["Askari", "Askari 10", "Askari X", "LAH Askari 10"]),
    dict(code="PA6", name="Paragon City", short="PARAGON", format="S", city="Lahore", region="Lahore",
         corp=["652"], aliases=["PARAGON", "Paragon", "High Street Paragon City", "Paragon City"]),
    dict(code="P04", name="Fortress Myli", short="FRT MYLI", format="M", city="Lahore", region="Lahore",
         parent="500", corp=["962"], aliases=["FRT_MYLI", "FRT MYLI", "Myli Fortress", "H&B Fortress"]),
    dict(code="P05", name="Packages Myli", short="PKG MYLI", format="M", city="Lahore", region="Lahore",
         parent="504", corp=["960"], aliases=["PKG_MYLI", "PKG MYLI", "Myli Packages", "H&B Packages Mall"]),
    dict(code="PA2", name="Emporium Myli", short="EMP MYLI", format="M", city="Lahore", region="Lahore",
         parent="503", corp=["965"], aliases=["EMP_MYLI", "EMP MYLI", "Myli Emporium", "H&B EMP"]),
    dict(code="PA4", name="Lucky One Myli", short="LUK MYLI", format="M", city="Karachi", region="Karachi",
         parent="505", corp=["976"], aliases=["LUK_MYLI", "LUK MYLI", "Myli Lucky One", "H&B KCH LUK"]),
    dict(code="PD4", name="DHA Phase 7 Myli", short="DHA07 MYLI", format="M", city="Lahore", region="Lahore",
         parent="P08", corp=["967"], aliases=["DHA 07_MYLI", "DHA07_MYLI", "Dha Ph 07 MYLI", "MYLI Phase 7",
                                               "Myli DHA 7", "H&B DHA Phase"]),
    dict(code="PD2", name="DHA Rahbar Myli", short="RHB MYLI", format="M", city="Lahore", region="Lahore",
         parent="P07", corp=["968"], aliases=["DHA RHB_MYLI", "Dha Rahber MYLI", "Myli Rahbar", "MYLI Rahbar",
                                               "H&B DHA Rahbar"]),
]

# Names that appear in reports but are not live stores. Recognised so they are skipped quietly.
NON_STORES: list[dict] = [
    dict(code="X-DOLMEN", name="Dolmen City Mall", kind="closed", corp=["652"], format="H",
         aliases=["Dolmen", "Dolmen City", "Dolmen City Mall", "KCH Dolmen City Mall"]),
    dict(code="X-CLIFTON", name="Clifton", kind="closed", corp=["665"], format="S", aliases=["Clifton"]),
    dict(code="X-AVENUE", name="Avenue Mall", kind="closed", corp=["651"], format="H", aliases=["Avenue Mall", "Avenue"]),
    dict(code="X-DOLMYLI", name="Dolmen Myli", kind="closed", corp=["977"], format="M", aliases=["DOL Myli", "DOL MYLI"]),
    dict(code="X-HBWTC", name="H&B WTC", kind="closed", corp=["966"], format="M", aliases=["H&B WTC", "HB WTC"]),
    dict(code="X-DARK", name="Dark Store Azam Town", kind="channel", corp=["614"], format="",
         aliases=["Dark Store", "MDS Azam Town", "MDS"]),
    dict(code="X-DARAZ", name="Daraz", kind="channel", corp=["605"], format="", aliases=["Daraz", "WP Daraz", "Daraz Partnership", "PAK Daraz Partnership"]),
    dict(code="X-FOODPANDA", name="Foodpanda", kind="channel", corp=["617"], format="",
         aliases=["Foodpanda", "Food Panda", "WP Foodpanda", "Foodpanda Partnership", "PAK FOODPANDA Partnership"]),
]

UNKNOWN_STORE_CODES = ["PA3", "PM5"]

CITY_TOKENS = {"LAH": "Lahore", "KCH": "Karachi", "KHI": "Karachi", "ISL": "Islamabad",
               "FAI": "Faisalabad", "FSD": "Faisalabad", "GUJ": "Gujranwala"}

FORMAT_NAMES = {"H": "Hypermarket", "S": "Supermarket", "M": "Myli"}

# ---------------------------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------------------------
DEPARTMENTS = [
    dict(code="01", short="CG", name="Consumer Goods", name_ur="کنزیومر گڈز", head="CG",
         aliases=["CGD", "FMCG", "CG", "CONSUMER GOODS", "GROCERY"]),
    dict(code="02", short="FFD", name="Fresh Food", name_ur="فریش فوڈ", head="FFD",
         aliases=["FFD", "FRESH", "FRESH FOOD", "FRS"]),
    dict(code="03", short="LHH", name="Light Household", name_ur="لائٹ ہاؤس ہولڈ", head="NF",
         aliases=["LHH", "LIGHT HOUSEHOLD", "LIGHT HOUSE HOLD"]),
    dict(code="04", short="HHH", name="Heavy Household", name_ur="ہیوی ہاؤس ہولڈ", head="NF",
         aliases=["HHH", "HEAVY HOUSEHOLD", "HEAVY HOUSE HOLD"]),
    dict(code="05", short="TXT", name="Textile", name_ur="ٹیکسٹائل", head="NF",
         aliases=["TXT", "TEXTILE", "TEX"]),
]

# (section code, department code, name, extra spellings seen in reports)
SECTIONS: list[tuple[str, str, str, list[str]]] = [
    ("011", "01", "Beverages", ["BEVERAGE"]),
    ("012", "01", "DPH", ["D.P.H.", "DPH [Detergent. Perfume]", "DETERGENT PERFUME", "HEALTH & BEAUTY"]),
    ("013", "01", "Cigarettes", ["CIGARETTE"]),
    ("014", "01", "Grocery", ["GROCERY [DRY FOOD]", "DRY FOOD"]),
    ("021", "02", "Ultra Fresh", []),
    ("022", "02", "Dairy Products SS", ["DAIRY PRODUCTS", "DAIRY SS"]),
    ("023", "02", "Delicatessen SS", ["DELICATESSEN"]),
    ("024", "02", "Frozen SS", []),
    ("025", "02", "Bread & Pastry SS", []),
    ("026", "02", "Frozen Food", ["FROZEN"]),
    ("030", "03", "Tools - DIY", ["TOOLS - DO IT YOURSELF", "DO IT YOURSELF", "DIY", "TOOLS"]),
    ("031", "03", "Houseware", ["HOUSE-WARE", "HOUSE WARE"]),
    ("032", "03", "Stationery", ["STATIONARY"]),
    ("033", "03", "Camping / Gardening", ["CAMPING GARDENNING", "CAMPING GARDENING", "CAMPING"]),
    ("034", "03", "House Equipment", []),
    ("035", "03", "Car", ["AUTOMOTIVE"]),
    ("036", "03", "Toys", []),
    ("037", "03", "Library", ["BOOKS"]),
    ("039", "03", "Sports", []),
    ("071", "03", "Luggage", []),
    ("040", "05", "Home Linen", []),
    ("041", "05", "Baby", ["BABY TEXTILE"]),
    ("042", "05", "Children", ["KIDS"]),
    ("043", "05", "Ladies", ["WOMEN"]),
    ("044", "05", "Men", []),
    ("060", "05", "Shoes", ["FOOTWEAR"]),
    ("061", "05", "Accessories", []),
    ("050", "02", "Delicatessen Counter", []),
    ("051", "02", "Dairy Counter", []),
    ("052", "02", "Butchery", []),
    ("053", "02", "Fishery", []),
    ("054", "02", "Bakery / Pastry", ["BAKERY/PASTRY", "BAKERY"]),
    ("055", "02", "Traiteur", []),
    ("056", "02", "Fruits & Vegetables", ["F&V", "FRUITS AND VEGETABLES"]),
    ("057", "02", "Coffee Shop", []),
    ("080", "04", "Household Goods", []),
    ("081", "04", "Photo", []),
    ("082", "04", "Office Automation", []),
    ("083", "04", "Mobility", ["MOBILES"]),
    ("084", "04", "Gift & Shop", []),
    ("085", "04", "TV / VCR", ["TV & VCR", "TV"]),
    ("086", "04", "Hi-fi Sound", ["HI-FI", "HIFI"]),
    ("087", "04", "Household Appliances", ["HOUSEHOLD APPLIANCES", "APPLIANCES"]),
]

# ---------------------------------------------------------------------------------------------
# Codes (confirmed by the user unless marked inferred)
# ---------------------------------------------------------------------------------------------
ITEM_STATUS = {
    "AC": ("Active", "فعال", True),
    "NC": ("Not active (blocked, not orderable)", "غیر فعال", True),
    "NI": ("Not part of inventory", "انوینٹری میں شامل نہیں", True),
    "AG": ("Ageing", "ایجنگ", True),
    "HO": ("Unknown (HO)", "نامعلوم", False),
}
ORDER_TYPES = {
    "AO": ("Automatic ordering", "خودکار آرڈر", True),
    "REG": ("Regular (manual) ordering", "دستی آرڈر", True),
    "AOP": ("Unknown (AOP)", "نامعلوم", False),
    "HOP": ("Unknown (HOP)", "نامعلوم", False),
}
LPO_STATUS = {
    "EM": ("Issued, not received yet", "جاری، موصول نہیں ہوا", False),
    "RE": ("Received", "موصول", False),
    "BV": ("Received and validated", "موصول و تصدیق شدہ", False),
}
RANGE_CODES = {"007": ("Permanent range / blocked", "مستقل رینج / بلاک", True)}

# ---------------------------------------------------------------------------------------------
# Thresholds and rules (editable in Settings)
# ---------------------------------------------------------------------------------------------
SETTINGS_DEFAULTS = {
    "sleeping_days_cg": 30,          # CG / FMCG: no sale for 30 days = sleeping (BC definition)
    "sleeping_days_nonfood": 60,     # LHH, HHH, TXT: 60 days
    "low_stock_pcs": 6,              # "stock less than 6 pcs" (includes zero and negative)
    "dp_warning_days": 30,           # early warning window before an item ages into DP
    "min_items_for_pct": 20,         # hide % when fewer items than this (tiny departments)
    "bad_snapshot_drop_pct": 15,     # total items falling this much in a day = suspect snapshot
    "language": "en",
    "urdu_font": "Noto Nastaliq Urdu",
    "vat_rate": 18,
}

# Age (days) at which stock enters DP, per department. Inferred from the DP master.
DP_ENTRY_DAYS = {"01": 361, "02": 361, "03": 181, "04": 91, "05": 91}

# Provision % by age: list of (from_day, pct). Inferred from the DP master; the importer
# re-calibrates this table from every DP master file and reports any difference.
DP_RULES: dict[str, list[tuple[int, float]]] = {
    "01": [(361, 30), (541, 50), (721, 70)],
    "02": [(361, 30), (541, 50), (721, 70)],
    "03": [(181, 10), (271, 20), (361, 30), (541, 40), (721, 50)],
    "03:032": [(181, 10), (271, 25), (361, 40), (541, 60), (721, 75)],
    "03:036": [(181, 10), (271, 25), (361, 40), (541, 60), (721, 75)],
    "03:039": [(181, 10), (271, 25), (361, 40), (541, 60), (721, 75)],
    "04": [(91, 5), (181, 10), (271, 20), (361, 30), (541, 50), (721, 70)],
    "05": [(91, 10), (181, 25), (271, 40), (361, 60), (541, 75), (721, 90)],
}

# Age buckets used by the DP workbook (upper bound in days, label)
AGE_BUCKETS = [
    (90, "Under 3 months"), (180, "6 Months"), (270, "9 Months"), (360, "1 Year"),
    (540, "1.5 Year"), (720, "2 Years"), (10**9, "Above 2 years"),
]

# ---------------------------------------------------------------------------------------------
# BC indicators: key, label, lower-is-better, targets per format (None = not measured)
# computed=True means Stock Compass can calculate it item by item from GIMA files.
# ---------------------------------------------------------------------------------------------
BC_INDICATORS = [
    dict(key="forced_assortment", label="Forced assortment sales %", lo=False, t=dict(H=85, S=85, M=90),
         match=["FORCED ASSORTMENT"]),
    dict(key="zero_stock", label="Zero stock %", lo=True, t=dict(H=12, S=12, M=12), computed=True,
         match=["ZERO STOCK %", "ZERO STOCK"]),
    dict(key="osa_fmcg", label="OSA FMCG %", lo=False, t=dict(H=90, S=80, M=None), match=["OSA-FMCG", "OSA FMCG"]),
    dict(key="osa_nonfood", label="OSA non-food %", lo=False, t=dict(H=90, S=80, M=None),
         match=["OSA-NON FOOD", "OSA NON FOOD", "OSA-NONFOOD"]),
    dict(key="leaflet_zero", label="Leaflet zero stock %", lo=True, t=dict(H=6, S=8, M=6), computed=True,
         match=["LEAFLET ZERO STOCK", "LEAFLET OOS"]),
    dict(key="ssl", label="Supplier service level %", lo=False, t=dict(H=70, S=70, M=70), computed=True,
         match=["SUPPLIER SERVICE LEVEL", "SSL"]),
    dict(key="ao_fmcg", label="AO suppliers FMCG %", lo=False, t=dict(H=95, S=90, M=90), match=["AO SUPPLIERS (FMCG)"]),
    dict(key="ao_lhh", label="AO suppliers LHH %", lo=False, t=dict(H=85, S=70, M=None), match=["AO SUPPLIERS (LHH)"]),
    dict(key="ao_hhh", label="AO suppliers HHH %", lo=False, t=dict(H=30, S=30, M=None), match=["AO SUPPLIERS (HHH)"]),
    dict(key="ao_txt", label="AO suppliers TXT %", lo=False, t=dict(H=20, S=20, M=None), match=["AO SUPPLIERS (TXT)"]),
    dict(key="purged_lpo", label="Purged LPO %", lo=True, t=dict(H=20, S=20, M=20), computed=True,
         match=["PURGED LPO"]),
    dict(key="lpo_done", label="LPO done vs planned %", lo=False, t=dict(H=80, S=75, M=75),
         match=["LPO DONE VS PLANNED", "LPO DONE"]),
    dict(key="label_qty", label="Label survey quantity %", lo=False, t=dict(H=90, S=90, M=90),
         match=["LABELING SURVEY QTY", "LABELLING SURVEY QTY", "LABEL SURVEY QTY"]),
    dict(key="label_quality", label="Label survey quality %", lo=False, t=dict(H=95, S=95, M=95),
         match=["LABELING SURVEY QLTY", "LABELLING SURVEY QLTY", "LABEL SURVEY QUALITY"]),
    dict(key="lines_mod_cg", label="Lines modified CG %", lo=True, t=dict(H=1, S=1, M=1), match=["LINES MODIFIED CG"]),
    dict(key="lines_mod_lhh", label="Lines modified LHH %", lo=True, t=dict(H=1, S=None, M=None), match=["LINES MODIFIED LHH"]),
    dict(key="lines_mod_hhh", label="Lines modified HHH %", lo=True, t=dict(H=1, S=None, M=None), match=["LINES MODIFIED HHH"]),
    dict(key="lines_mod_txt", label="Lines modified TXT %", lo=True, t=dict(H=1, S=None, M=None), match=["LINES MODIFIED TXT"]),
    dict(key="variance_lines", label="Variance of lines %", lo=True, t=dict(H=20, S=20, M=20), match=["VARIANCE OF LINE"]),
    dict(key="low_stock_cg", label="Stock under 6 pcs in CG %", lo=True, t=dict(H=15, S=15, M=15), computed=True,
         match=["STOCK LESS THAN 6", "STOCK < 6", "STOCK 1-5"]),
    dict(key="negative_fmcg", label="Negative stock FMCG %", lo=True, t=dict(H=1, S=1, M=1), computed=True,
         match=["NEGATIVE STOCK FMCG", "NEGATIVE STOCK"]),
    dict(key="nosale_30_cg", label="No sales 30 days CG %", lo=True, t=dict(H=6, S=8, M=8), computed=True,
         match=["NO SALES FOR 30 DAYS", "NO SALES 30"]),
    dict(key="nosale_60_nf", label="No sales 60 days non-food %", lo=True, t=dict(H=15, S=13, M=None), computed=True,
         match=["NO SALES FOR 60 DAYS", "NO SALES 60"]),
    dict(key="eol_stock", label="EOL + delinked stock %", lo=True, t=dict(H=None, S=None, M=None), computed=True,
         match=["EOL+DELINKED", "EOL + DELINKED", "% OF EOL"]),
    dict(key="stock_corrections", label="Stock corrections %", lo=True, t=dict(H=1, S=1, M=1),
         match=["STOCK CORRECTIONS"]),
    dict(key="stock_days", label="Stock days", lo=True, t=dict(H=None, S=None, M=None), match=["STOCK DAYS"]),
]

# GIMA's own reasons for an item being at zero stock (CODDES), grouped into who must act.
OOS_REASON_GROUPS = [
    ("supplier", ["SUPPLIER NO DELIVERY", "NO DELIVERY", "SUPPLIER"]),
    ("schedule", ["ORDERING SCHEDULE", "SET AN ORDERING"]),
    ("reorder", ["PLACE NEW ORDER", "ONLY ONE ORDER"]),
    ("not_ordered", ["TO BE ORDERED", "NO ORDER DONE"]),
    ("new_item", ["NEW ITEM", "FIRST DELIVERY", "NEVER RECEIVED"]),
]
