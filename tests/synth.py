"""Synthetic report files in the exact layouts of the real GIMA / BO / BC / DP / leaflet reports.

All values are made up. Used by the tests and for demos; never commit real company files.
"""

from __future__ import annotations

import random
import zipfile
from datetime import date, timedelta
from pathlib import Path

import xlsxwriter

REF = date(2026, 9, 24)
STORES_GIMA = ["500", "502", "503", "504", "505", "506", "P03", "P06", "P07", "P08", "P09", "PA6",
               "P04", "P05", "PA2", "PA4", "PD4", "PD2"]
BO_NAMES = {"500": "651 LAH Fortress", "505": "654 KCH Lucky One", "504": "656 LAH Packages",
            "P03": "657 GUJ Steel Casting", "P09": "660 LAH Askari 10", "503": "660 LAH Emporium Mall",
            "502": "661 ISL WTC", "506": "663 FAI Lyallpur Galleria", "P05": "960 H&B LAH Packages Mall",
            "P04": "962 H&B LAH Fortress", "PA2": "965 LAH H&B PAK LAH EMP (MYLI)",
            "PA4": "976 KCH H&B PAK KCH LUK (MYLI)", "PA6": "652 LAH High Street Paragon Ci", "P08": "658 LAH DHA 7",
            "P07": "659 LAH DHA Rahbar", "P06": "661 ISL D12 (P06)", "PD4": "967 LAH H&B PAK LAH DHA Phase",
            "PD2": "968 LAH H&B PAK LAH DHA Rahbar"}

rnd = random.Random(7)


def yymmdd(d: date) -> int:
    return int(d.strftime("%y%m%d"))


def ddmmyy_nolead(d: date) -> int:
    return int(d.strftime("%d%m%y"))  # int() drops the leading zero, exactly like GIMA exports


def _xlsx(path: Path, sheets: dict[str, list[list]], hidden: set[str] = frozenset()):
    wb = xlsxwriter.Workbook(str(path))
    for name, rows in sheets.items():
        ws = wb.add_worksheet(name)
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                if v is None or v == "":
                    continue
                ws.write(i, j, v)
        if name in hidden:
            ws.hide()
    # xlsxwriter needs one visible sheet active
    wb.close()


ITEMS = [(f"{230000 + i}", f"TEST ITEM {i}", "01" if i % 3 else "03", "011" if i % 3 else "030", str(170 + i % 5),
          f"4{5000 + i % 7}") for i in range(60)]


def realtime(path: Path, store: str = "504"):
    head = ["CSECW1", "CRAYW1", "CFAMW1", "CSFAW1", "LARTW1", "NARTW1", "NFOUW1", "CEANW1", "DEANW1", "CMARW1",
            "CMKPW1", "CARRW1", "STAFW1", "SUPPW1", "PPRCW1", "PRFTW1", "PHTVW1", "PAFFW1", "MARGW1", "TOTFW1",
            "PRNVW1", "MRGCW1", "PVTCW1", "DDVAW1", "DDENW1", "QPHYW1", "CDEMW1", "CTVAW1", "CFTCW1", "PPTCW1",
            "DDVSW1", "DFVSW1", "PAPFW1", "DDVPW1", "DFVPW1", "ASSTW1", "ASS2W1", "ASS3W1", "FSDAW1", "CIFLW1",
            "CAPRW1", "LAREW1", "PRPSW1", "NORDW1", "RNGCW1", "RSPLW1", "PCBRW1", "TYPEW1"]
    rows = [head]
    for k, (it, desc, dp, sec, fam, sup) in enumerate(ITEMS):
        cost = 100 + k * 3
        price = round(cost * 1.18 * 1.3)
        qty = -2 if k == 5 else (0 if k % 4 == 0 else k % 17)
        r = [dp, sec, fam, "100", desc, int(it), int(sup), "3.00111E+11", 5, 34150, "", "AC", "NC" if k == 7 else "AC",
             0, 0, cost, cost, cost, 30.0, 0, cost, 30.0, price, yymmdd(REF - timedelta(days=90)),
             yymmdd(REF - timedelta(days=k)), qty, 18, 18, "Y", 0, 0, 0, 0, 0, 0, "106", "", "", "Y", 0, "", desc, "",
             yymmdd(REF + timedelta(days=4)), "7" if k == 9 else "", 1, "DIR", ""]
        rows.append(r)
    _xlsx(path, {"Sheet1": rows})


def benchmark(path: Path):
    head = ["FRMDAT", "TODAT", "DEPT", "SEC", "FAM", "SFA", "SUPPLR", "SUPDEC", "BARCODE", "ITEM", "ITMDSC", "AST1",
            "AST2", "AST3", "BRAND", "RANGE", "PP", "SP", "PCB", "EXT_DESC", "TOTAL_T", "TOTAL_Q", "TOTAL_M", "TOTAL_S",
            "PKG_T", "PKG_Q", "PKG_M", "PKG_S", "FRT_T", "FRT_Q", "FRT_M", "FRT_S"]
    rows = [head]
    for k, (it, desc, dp, sec, fam, sup) in enumerate(ITEMS[:40]):
        pp, sp = 100 + k * 3, round((100 + k * 3) * 1.18 * 1.3)
        q1, q2 = k % 3, (k + 1) % 4
        t1, t2 = round(q1 * sp / 1.18, 2), round(q2 * sp / 1.18, 2)
        rows.append(["24/07/26", "24/07/26", dp, sec, fam, "100", sup, "SUPPLIER " + sup, "4006381333931", int(it), desc,
                     "106", "", "", "32677", "", pp, sp, 12, "", t1 + t2, q1 + q2, round(t1 + t2 - (q1 + q2) * pp, 2), 30,
                     t1, q1, round(t1 - q1 * pp, 2), 10, t2, q2, round(t2 - q2 * pp, 2), 20])
    _xlsx(path, {"Benchmark": rows})


def gima_zero(path: Path):
    head = ["STR", "BACDTO", "CHDGTO", "DEPTTO", "SECTTO", "IDSCTO", "PHQTTO", "ITEMTO", "FAMITO", "SFAMTO", "MKCDTO",
            "ISTSTO", "IMCDTO", "LDINTO", "LDOUTO", "NBRDTO", "ICDTTO", "STAFE", "SUPPTO", "RSOCF", "COMPTO", "UNITTO",
            "ASSTTO", "ASSTT2", "ASSTT3", "QCDFS", "PRHPRS", "DLIVD", "NCDED", "NBREE", "DRECE", "NCDEM", "QTYDLV",
            "QMINM", "DDSOS", "DNEXT", "WITHL", "PCKNUM", "PCKSTS", "HMECAT", "COEFFC", "LCKMIN", "FACING", "ITMPRM",
            "ITMSTA", "ACTSUP", "ITMAOP", "DLYAVG", "SLOWMV", "QTYTTO", "LPOCDT", "PROMO", "IMPSUP", "MULACT", "HOSUP",
            "QTYORD", "CODDES"]
    reasons = ["Supplier no delivery", "To set an ordering schedule", "Place new order (only one order done)",
               "To be ordered (No order done since 1 month)"]
    snap = date(2026, 9, 17)
    rows = [head]
    for k, (it, desc, dp, sec, fam, sup) in enumerate(ITEMS[:24]):
        last_out = snap - timedelta(days=10 + k * 5)
        rows.append(["504", "5.904E+11", 2, dp, sec, desc, 0, int(it), fam, "003", "", "AC", "03048",
                     yymmdd(last_out - timedelta(days=30)), yymmdd(last_out), (snap - last_out).days, 201007, "AC",
                     int(sup), "SUPPLIER " + sup, "", 0, "104", "", "", 48, "", yymmdd(snap + timedelta(days=3)),
                     26015608 if k % 5 == 0 else 0, 26100573, yymmdd(last_out), 26000240, 0, 12,
                     yymmdd(last_out), 999999, "Y", 0, "", "", 1, 12, 2, "", "AC", "YES", "AO" if k % 2 else "REG",
                     round(0.5 + k / 10, 2), "N", 0, yymmdd(snap), "Y" if k == 3 else "N", "N", "N", "N", 24,
                     reasons[k % 4]])
    _xlsx(path, {"Zero": rows})


def gima_negative(path: Path):
    rows = [["STR", "DEPTPR", "SECTPR", "FAMIPR", "IDSCPR", "PHQTPR", "BACDPR", "CHDGPR", "ITEMPR", "ISTSPR"]]
    for k in range(15):
        rows.append(["504", "03", "030", "304", f"NEG ITEM {k}", -(k % 6) - 1, "3E+11", 4, 311800 + k,
                     ["NI", "NC", "AC"][k % 3]])
    _xlsx(path, {"Neg": rows})


def lpo(path: Path):
    rows = [["RT LPO CREATION MTD (SUMMARY)"],
            ["STR", "LPODAT", "DLYDAT", "DEP", "SEC", "LPO", "LPOVAL", "GRN", "GRNVAL", "XLPQTY", "USER", "SUPLR",
             "SUPNAM", "LDTME", "LPOSTA", "CNRNO", "OTYPE", "CSUP", "LUSER", "Category"]]
    for k in range(30):
        od = date(2026, 9, 1) + timedelta(days=k % 21)
        dd = od + timedelta(days=5)
        st = ["500", "504", "P09"][k % 3]
        rows.append([st, ddmmyy_nolead(od), ddmmyy_nolead(dd), "01", "014", 26000900 + k, 100000 + k * 1000,
                     0 if k % 4 else 26100000 + k, 0 if k % 4 else 90000 + k * 900, 100 + k, f"GIMA{st}", 45000 + k % 5,
                     f"SUPPLIER {k % 5}", 6, "EM" if k % 4 else "RE", 0, "AO" if k % 2 else "REG",
                     "D" if k % 7 == 0 else "", "USER", "ok"])
    rows.append(rows[-1][:])  # a duplicate-looking order
    rows.append(["PM5", ddmmyy_nolead(date(2026, 9, 21)), ddmmyy_nolead(date(2026, 9, 28)), "01", "014", 26009999,
                 5000, 0, 0, 5, "GIMAPM5", 47227, "SUP", 0, "EM", 0, "HOP", "", "X", "ok"])
    _xlsx(path, {"RT LPO": rows})


def dp_master(path: Path):
    head = ["UI", "Report Date", "Stores Names", "Stores", "DEPTPR", "Department ", "SECTPR", "Section Names", "FAMIPR",
            "ITEMPR", "IDSCPR", "SUPPPR", "MKCDPR", "ASSTTO", "BACDPR", "CHDGPR", "PCB", "PHQTPR", "ITMSTS", "CSTPPR",
            "SELPPR", "SELPR1", "CPVAL", "MARGIN", "MARGPC", "ROT", "RANGE", "AGNGPR", "XDAYS1", "AGNGP1",
            "Dep Provision", "DEPPC", "L31", "L91", "L181", "L271", "L361", "L541", "L721", "G720", "Months",
            "High Risk %age", "High Risk Flage", "Main Unique ID", "DEPTPR2"]
    stores = [("Lyallpur", "506"), ("Fortress", "500"), ("MYLI Phase 7", "PD4"), ("Gujranwala", "P03")]
    rows = [head]
    for k in range(40):
        name, code = stores[k % 4]
        dept = ["01", "03", "04", "05"][k % 4]
        age = [400, 600, 800, 200, 300, 100, 150, 750][k % 8]
        if dept == "01":
            age = [400, 600, 800][k % 3]
            pct = 30 if age < 541 else (50 if age < 721 else 70)
        elif dept == "03":
            pct = 10 if age < 271 else (20 if age < 361 else (30 if age < 541 else 50))
        elif dept == "04":
            pct = 5 if age < 181 else (10 if age < 271 else (30 if age < 541 else 70))
        else:
            pct = 10 if age < 181 else (25 if age < 271 else (60 if age < 541 else 90))
        qty, cost = 1 + k % 5, 200 + k * 10
        val = qty * cost
        rows.append([f"CM{code}{k}", "Current Month", name, code, dept, "", "044" if dept == "05" else "012",
                     "", "608", 290000 + k, f"DP ITEM {k} W025" if k == 3 else f"DP ITEM {k}", 45403, "", "", "2E+11", 8,
                     3, qty, "AG", cost, round(cost * 1.18 * 1.1), round(cost * 1.1, 2), val, 0, 0, 999, "", age, 0, age,
                     round(val * pct / 100, 2), pct, 0, 0, 0, 0, 0, 0, 0, 0, "1.5 Year", 0.001, 0, "", dept])
    rows.append(rows[1][:])
    rows[-1][1] = "Last Month"
    _xlsx(path, {"Summary": [["Department Wise Summary", "", "Stock as at 20 Sep"], ["Dept.", "Provision"]],
                 "Master Data": rows}, hidden={"Master Data"})


def bo_zero_summary(path: Path, days: int = 12):
    d0 = date(2026, 9, 1)
    ds = [d0 + timedelta(days=i) for i in range(days)]
    rows = [["Report Name", "", "500-30-15-Zero Stock Report Summary"],
            ["Start Date", "", f"{ds[0].month}/{ds[0].day}/{ds[0].year} 12:00:00 AM"],
            ["End Date", "", f"{ds[-1].month}/{ds[-1].day}/{ds[-1].year} 12:00:00 AM"],
            ["Country", "", "Pakistan"], [], [], ["01-CGD"], []]
    drow, lrow = ["", ""], ["", ""]
    for d in ds:
        drow += [f"{d.month}/{d.day}/{d.year}", "", ""]
        lrow += ["Total Items", "Zero Stock", "% Zero Stock"]
    rows += [drow, lrow]
    for code in ["500", "504", "P03", "P08"]:
        r = [BO_NAMES[code], ""]
        for i, d in enumerate(ds):
            tot, zero = 6500, 800 + i * 3
            if code == "P03" and i == 5:          # broken stock load
                tot, zero = 4000, 5
            if code == "P08" and i >= 7:          # items removed from the range at zero
                tot, zero = 6100, 420
            if code == "504" and i >= 9:          # sudden jump with the range unchanged
                zero += 300
            r += [tot, zero, f"{round(zero / tot * 100)}%"]
        rows.append(r)
    rows.append(["PAK Pakistan", "", "", "", "14%"])
    _xlsx(path, {"Department": rows})


def bc_scorecard(path: Path):
    codes = ["", "", "", "505", "500", "503", "504", "502", "506", "P03", "", "", "", "P06", "P07", "P08", "P09", "PA6",
             "", "", "P04", "P05", "PA2", "PD4", "PD2", "PA4"]
    head = ["Main Indicators", "Targets", "Hypermarket Avg.", "LUK", "FOR", "EMP", "PKG", "WTC", "LYL", "GUJ", "",
            "Targets", "Supermarket Avg.", "D12", "DHA11", "DHA07", "Askari", "PARAGON", "", "MYLI Avg.", "FRT_MYLI",
            "PKG_MYLI", "EMP_MYLI", "DHA 07_MYLI", "DHA RHB_MYLI", "LUK_MYLI"]
    rows = [codes, ["Weekly Indicators B.C & Supply Chain MTD-Sep2026"],
            ["HYPER MARKET", "", "", "", "", "", "", "", "", "", "", "SUPER MARKET", "", "", "", "", "", "", "", "MYLI"],
            head, [], []]

    def line(label, th, ts, vals_h, vals_s, vals_m, avg=("10.00%", "20.00%", "30.00%")):
        return [label, th, avg[0]] + vals_h + ["", ts, avg[1]] + vals_s + ["", avg[2]] + vals_m

    rows.append(line("Zero stock %", "12%", "12%", ["13.82%", "14.47%", "11.00%", "17.12%", "10.50%", "24.72%", "21.33%"],
                     ["23.06%", "20.02%", "19.59%", "16.91%", "11.99%"], ["12.35%", "14.90%", "11.86%", "23.42%", "22.78%", "18.57%"]))
    rows.append(line("Supplier Service Level %", "70%", "70%", ["58.15%", "61.86%", "71.00%", "64.96%", "52.05%", "53.47%", "46.19%"],
                     ["50.85%", "64.88%", "60.39%", "56.03%", "62.33%"], ["54.35%", "58.54%", "58.41%", "57.86%", "43.74%", "33.66%"],
                     avg=("57.86%", "59.51%", "51.09%")))
    rows.append(line("Stock Days", "", "", ["35", "29", "37", "33", "50", "57", "36"], ["39", "41", "44", "33", "39"],
                     ["68", "65", "82", "168", "N/A", "105"], avg=("39", "46", "150")))
    rows.append(line("No. of Greens", "", "", ["1", "1", "2", "0", "1", "0", "0"], ["0", "0", "0", "0", "1"],
                     ["0", "0", "0", "0", "0", "0"], avg=("", "", "")))
    _xlsx(path, {"Summary": rows})


def blocked(path: Path):
    rows = [["", "", "", "", "", "", "6,259.00"], ["", "", "", "", "", "", "", "", "", "", "", "3-Aug", "", "", "", "7-Sep"],
            ["STORE CODE", "STORE NAME", "DEP", "DEPARTMENT", "SEC", "SECTION", "ITEMS#", "DESC", "SUPP", "SUP_DEC",
             "STS", "STOCK 1", "CP", "OPENING STOCK VALUE ", "RANGE CODE", "STOCK 2", "NEW STOCK VALUE", "VARIANCE",
             "VARIANCE VALUE", "CHANGE"]]
    for k in range(12):
        q1, q2 = 10, 10 if k % 2 else 4
        rows.append(["PA2", "MYLI EMPORIUM", "01", "CONSUMER GOODS", "012", "D.P.H.", 252600 + k, f"BLOCKED {k}", 46720,
                     "SUPPLIER X", "NC", q1, 30.0, q1 * 30.0, "007", q2, q2 * 30.0, q2 - q1, (q2 - q1) * 30.0, "0%"])
    _xlsx(path, {"Data": rows})


def leaflet(path: Path):
    rows = [["CURRENT C &  L Theme (WEDDING GALA  2026) (17-09-2026 to 07-10-2026)"], [],
            ["COMMON compo", "Common Single", "STORE", "STR NAME", "DEPT", "DEP NAME", "SEC", "SEC NAME", "FAM",
             "SUB_FAMILY", "SUPPLIER", "SUP_DEC", "ITEM", "ITEM NAME", "Item ComPOSE", " PP ", "SP", "PCB", "THEME",
             "THEME NAME", "THEME ST", "STKQTY", "STATUS", "TYPE", "STK VAL", "ON ORDER VAL", "ON ORDER "]]
    for k in range(10):
        pp, sp = 400.0, (445.0 if k % 3 else 380.0)
        rows.append(["", f"P06{303080 + k}", "P06", "D12", "", "01-FMCG", "", "S012-DPH", "273", "2", 47169, "SUP",
                     303080 + k, f"LEAF ITEM {k}", "", pp, sp, 6, "CM86", "WEDDING GALA MYLI 2026", "C-Theme",
                     0 if k < 6 else 5, "Zero Stock" if k < 6 else "OK", "Single Item", " -   ", " -   ",
                     12 if k in (1, 7) else 0])
    _xlsx(path, {"C&L Theme": rows})


def add_pivot_cache(xlsx_path: Path, fields: list[str], records: list[list]):
    """Inject a pivot cache (definition + records) into an existing .xlsx, like Excel stores one."""
    shared = [sorted({r[i] for r in records if isinstance(r[i], str)}) for i in range(len(fields))]
    d = ['<?xml version="1.0" encoding="UTF-8"?><pivotCacheDefinition xmlns="http://schemas.openxmlformats.org/'
         'spreadsheetml/2006/main" recordCount="%d"><cacheSource type="worksheet"><worksheetSource ref="A1:C9" '
         'sheet="DeletedData"/></cacheSource><cacheFields count="%d">' % (len(records), len(fields))]
    for i, f in enumerate(fields):
        d.append(f'<cacheField name="{f}"><sharedItems>' + "".join(f'<s v="{v}"/>' for v in shared[i])
                 + "</sharedItems></cacheField>")
    d.append("</cacheFields></pivotCacheDefinition>")
    r = ['<?xml version="1.0" encoding="UTF-8"?><pivotCacheRecords xmlns="http://schemas.openxmlformats.org/'
         'spreadsheetml/2006/main" count="%d">' % len(records)]
    for rec in records:
        r.append("<r>" + "".join(f'<x v="{shared[i].index(v)}"/>' if isinstance(v, str) else f'<n v="{v}"/>'
                                  for i, v in enumerate(rec)) + "</r>")
    r.append("</pivotCacheRecords>")
    with zipfile.ZipFile(xlsx_path, "a") as z:
        z.writestr("xl/pivotCache/pivotCacheDefinition1.xml", "".join(d))
        z.writestr("xl/pivotCache/pivotCacheRecords1.xml", "".join(r))


def build_all(folder: Path) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, fn in [("realtime_504.xlsx", realtime), ("benchmark.xlsx", benchmark), ("gima_zero.xlsx", gima_zero),
                     ("gima_negative_504.xlsx", gima_negative), ("lpo.xlsx", lpo), ("dp.xlsx", dp_master),
                     ("zero_summary.xlsx", bo_zero_summary), ("bc.xlsx", bc_scorecard), ("blocked.xlsx", blocked),
                     ("leaflet.xlsx", leaflet)]:
        p = folder / name
        fn(p)
        out[name] = p
    return out


# ------------------------------------------------------------------------------------------------ sales
_B11 = ["Weight %", "Weight In Store%", "Budget ", "Net Sales", "Gth%", "Var%", "Margin %", "Margin % Gth%", "Waste %",
        "Net Margin After Waste%", "Customer", "Customer Gth%", "Penetration Rate %", "Avg Bask", "Avg Bsk Gth %", "Qty",
        "Qty Gth%", "Stock Value", "Stock Days", "Actual", "Gth%", "Out Of Stock%"]


def bo_11b_section(path: Path):
    """11b section tab: Department | Section | Code | Store Type | Store Short Name | Daily | MTD blocks."""
    n = len(_B11)
    g0 = ["Department", "Section", "Code", "Store Type", "Store Short Name", "Daily      :  (Sat) 25-Jul-26"] + [""] * (n - 1)
    g0[5 + 19] = "Avg Selling Price"
    g0 += ["MTD"] + [""] * (n - 1)
    g1 = ["", "", "", "", ""] + _B11 + _B11
    rows = [g0, g1]
    data = [("Consumer Goods", "CGD - Beverages", "S011", "Hypermarket", "651 LAH Fortress", 100000, 80000, "25.0%", "(2.0%)"),
            ("Consumer Goods", "CGD - DPH [Detergent. Perfume]", "S012", "Hypermarket", "651 LAH Fortress", 200000, 220000, "(10.0%)", "3.5%"),
            ("Consumer Goods", "CGD - Beverages", "S011", "Supermarket", "658 LAH DHA 7", 50000, 60000, "(20.0%)", "1.0%"),
            ("Consumer Goods", "CGD - Beverages", "S011", "WP", "605 PAK Daraz Partnership", 0, 1000, "0.0%", "0.0%"),
            ("", "MAF Retail - Stores", "", "", "", 350000, 360000, "(1.0%)", "2.0%")]
    for dep, sec, code, typ, st, sales, bud, g, m in data:
        blk = ["1.0%", "10.0%", f"{bud:,}", f"{sales:,}", g, "(5.0%)", m, "0.1%", "0.2%", "1.0%", "100", "1.0%", "30.00%",
               "500", "1.0%", "400", "1.0%", "1,000,000", "20", "250.5", "0.0123", "12.%"]
        rows.append([dep, sec, code, typ, st] + blk + [x if i not in (2, 3) else f"{int(str(x).replace(',', '')) * 20:,}"
                                                       for i, x in enumerate(blk)])
    _xlsx(path, {"Section": rows})


def bo_11f_store(path: Path):
    lab = ["Gross Sales LY", "Gross Sales CY", "Total Gth% ", "B2C LY", "B2C CY", "B2C Gth%", "B2B LY", "B2B CY", "B2B Gth%",
           "B2B Weight%", "Margin% ", "Waste %", "Net Margin After Waste%", "B2C Margin Value ", "B2C Margin%",
           "B2B Margin Value", "B2B Margin %", "Customer", "Customer Gth%", "Avg Bask", "Avg Bsk Gth %", "Promo Sales%",
           "Purchase", "Stock Value", "Stock Days", "Qty Sold CY ", "Qty Sold LY ", "Qty Sold Gth%"]
    rows = [["Report Name", "200-10-11F-Country Family_Supplier Benchmark Analysis(DAY,MTD,YTD)"],
            ["Sales Date", "(Tue) 25-Aug-26"], ["Country", "Pakistan"], ["Department", "01-CGD"], [],
            ["Country Name", "Store Type", "Store", "Department ", "Section Code Name", "Family", "Supplier", "Day"]
            + [""] * (len(lab) - 1) + ["YTD"] + [""] * (len(lab) - 1),
            [""] * 7 + lab + lab]
    lines = [("960 H&B LAH Packages Mall", "272 - ORAL CARE", "PK46254 - TOOTH CO", 0, 0, 0, 0, 5220, 0),
             ("651 LAH Fortress", "355 - SHAMPOO", "PK45503 - SOAP CO", 1000, 1200, 0, 300, 50000, 60000),
             ("651 LAH Fortress", "293 - DETERGENT", "PK45503 - SOAP CO", 800, 700, 100, 50, 40000, 35000)]
    for st, fam, sup, ly, cy, b2bly, b2bcy, yly, ycy in lines:
        def blk(l, c, b):
            return [l or "", c or "", "", (l - b2bly) or "", (c - b) or "", "", b2bly or "", b or "", "", "", "5.00%", "0.10%",
                    "4.90%", "", "", -20 if b else "", "-10.00%" if b else "", 10, "", 100, "", "20.00%", 500, 1000, 15, 3, 4, ""]
        rows.append(["Pakistan", "H&B" if "H&B" in st else "Hypermarket", st, "01-CGD", "S012 - DPH", fam, sup]
                    + blk(ly, cy, b2bcy) + blk(yly, ycy, b2bcy))
    _xlsx(path, {"Store": rows})


def bo_net_sales(path: Path):
    head = ["Section Code Name", "Net Sales", "", "", "", "", "", "Section Weight", "", "Customer", "", "Pent. Rate", "Item",
            "", "Avg Basket", "", "Avg Selling Price", "", "Margin %", "", "", "Avg Stock", "Out of Stock %"]
    sub = ["", "Actual", "Forecast", "Budget", "Gth %", "Var FCT %", "Var %", " in Store", "in Cntry", "Cust", "Gth %", "",
           "Actual", "Gth %", "Actual", "Gth %", "Actual", "Gth %", "NetMrg", "Waste ", "NetMrg-Wst", "", ""]
    rows = []
    for store, s1 in [("HM PK LAH Fortress", 381532), ("SM PK ISL D12 (P06)", 90000)]:
        rows += [[f"Report Name: 200-10-05-Country Periodic Store Performance Report", "", "", "", "", "Currency:  LOCAL CURR - DAY"],
                 [f"Store Name: {store}", "", "", "", "", "Report Period : 24/09/2026 - 24/09/2026"], [], head, sub,
                 ["S011 - Beverages", f"{s1:,}", "", "400,000", "20.4%", "", "(4.6%)", "4.1%", "0.6%", "682", "(11.7%)",
                  "35.0%", "2,212", "(15.0%)", "559.4", "36.3%", "172.5", "41.6%", "12.7%", "0.4%", "12.4%", "19,747,373", "11.7%"],
                 ["S013 - Cigarette", "", "", "0", "0.0%", "", "0.0%"],
                 ["Total Store", f"{s1:,}"]]
    _xlsx(path, {"Store net sales": rows})


LPO_SUPPORT_HEAD = ["STORE_NUMBER", "DEPARTMENT", "DEPT_DESCRIPTION", "SECTION", "SECT_DESCRIPTION", "FAMILY", "FAMILY_DESCRIPTION",
                    "SUB_FAMILY", "SUBFAMILY_DESCRIPTION", "SUPPLIER", "SUPPLIER_NAME", "MAIN_MULTI", "ORDER_DAYS", "ITEM_CODE", "EAN",
                    "DIGITS_EAN", "RESUPPLY_TYPE", "DELIVERY", "SUPPLIER_INTERNAL_CODE", "ITEM_DESCRIPTION", "SUPP_DESCRIPTION",
                    "PURCHASE_PRICE", "SELLING_PRICE", "COST_PRICE", "LEAD_TIME", "PERIOD_TO_COVER", "MINIMUM_STOCK", "LOCKMINI",
                    "FACING", "STRAIGHT_DAS", "DAILY_AVG_SALES", "COEFF", "QUANTITY_STOCK", "OFFSITE_QTY", "STORE_QTY",
                    "ORDERED_QUANTITY", "PENDING_QTY1", "PENDING_QTY2", "PROPOSED_QUANTITY", "PUSH_ORDER_QTY", "FRZ_ORDERQTY",
                    "QTY_EOF_DAY", "INCREMENT", "TOTAL_INCR_IN_UNIT", "COMPOSED", "MIX_UNI", "TYPE", "ASSORTMENT", "PLU",
                    "ITEM_CATEGORY", "ORDER_TYPE", "OUT_OF_STOCK", "ITEM_MARGIN", "ZERO_ACTIONPLAN", "ZERO_DAYS", "PROMO",
                    "SALES_01", "SALES_02", "SALES_03", "SALES_04", "SALES_05", "SALES_06", "SALES_07",
                    "SALES_11", "SALES_12", "SALES_13", "SALES_14", "SALES_15", "SALES_16", "SALES_17", "INSERT_USER", "INSERT_DATE"]


def lpo_support_text(store: str = "504", n: int = 12) -> str:
    """GIMA LPO support in its exact layout (made-up items). Item k: stock, open order and weekly sales vary so that
    some are out of stock with nothing on order, some are over-ordered and some are fine."""
    rows = ["\t".join(LPO_SUPPORT_HEAD)]
    for k, (it, desc, dp, sec, fam, sup) in enumerate(ITEMS[:n]):
        weekly = [0] * 7 if k == 3 else [70 + (k * 7 + i * 13) % 30 for i in range(7)]       # item 3: not selling
        avg = round(sum(weekly) / 49, 4)
        stock = 0 if k in (0, 1) else (-5 if k == 2 else 400 if k in (3, 4) else 30 + k)
        ordered = 0 if k in (0, 2) else (600 if k == 4 else 60 if k == 3 else 120 if k % 2 else 0)
        days = "Wednesday, Even Week" if k % 2 else "Monday, Thursday"
        cells = [store, dp, "DEPT", sec, "SECTION", fam, "FAMILY", "001", "SUB", sup, "TEST SUPPLIER " + sup, "", days, it,
                 "8.99051E+11", 4, 1, "DIR", "000" + it, desc, desc, 100 + k, 140 + k, 100 + k, 6, 16, 0, 1, 12, 0, avg, 1,
                 stock, 0, 0, ordered, 0, 0, 24 if k == 1 else 0, ordered, ordered, stock, 12, 0, 0, "", "Fast", "101", 0, "",
                 "AO", "", 20.5, "", 3 if stock <= 0 else 0, "N",
                 *[round(w / 7) for w in weekly[:7]], *weekly, "TESTUSER", "102018280926"]
        rows.append("\t".join(str(c) for c in cells))
    return "\n".join(rows) + "\n"
