# Data sources: what Stock Compass reads and how

This is the importer specification: every report format, how it is recognised, what each column means,
the formulas we confirmed, the code tables, and the checks run on import. **It describes formats only. No
company figures belong in this repository.** Real reports stay on the user's PC.

## 1. How a file is recognised

1. **Open everything.** Every sheet is read, including hidden and very hidden sheets. The rows stored
   behind pivot tables (the pivot cache) are read too, even when the source sheet was deleted.
   Formats handled: `.xlsx .xlsm .xlsb .xls .ods`, `.csv/.txt/.tsv` (any delimiter or encoding), `.xls` files
   that are really HTML tables, and text pasted from Excel.
2. **Fingerprint each sheet.** Each report type has weighted tokens: whole-cell column codes such as `NARTW1`,
   `ITEMTO` or `CPVAL`, plus phrases such as the report code `500-30-15` and layout signals such as 12+
   `…W1` columns or `XXX_T/Q/M/S` store groups. The best score above 50% wins. The import screen shows the
   score, and the user can change the choice.
3. **Find the table.** The header row is the row that looks most like a header, with data under it. A
   group row above it (for example `Net Sales` spanning `Actual | Budget`) or a sub-header row below it is
   merged in. `Key : value` lines above the table (Start Date, Report Period, Store Name) become metadata.
4. **Read values per column, not per cell.** See section 3.
5. **Resolve stores.** See section 4.
6. **Check and flag.** Nothing is rejected for being unusual; it is flagged instead (section 7).
7. **Load a snapshot.** Each import is a batch with a report date. Re-importing the same report type for
   the same stores and date replaces the older batch.

Anything recognised but not analysed yet, or not recognised at all, is kept row by row (`raw_row`) with
its columns profiled (store, date, item code, section, percent, money, quantity, text). Later versions
can analyse it without re-importing.

## 2. Reports

### GIMA exports (column codes as headers)

| Report | Fingerprint | Row level | Store | Report date |
|---|---|---|---|---|
| RealTime (item master + stock) | `NARTW1 QPHYW1 CARRW1 STAFW1 PVTCW1 …W1` | item (one store per file) | **not in file**: taken from the file name, or picked by the user | not in file: user, file name, or file date (flagged) |
| Benchmark (item sales) | `FRMDAT TODAT ITEM ITMDSC`, groups `XXX_T/_Q/_M/_S` | item, with one column group per store | group prefix (`PKG_` = 504); `TOTAL_` = country | `TODAT` |
| Zero stock sheet | `ITEMTO PHQTTO CODDES DLYAVG NCDED` | store × item at zero | `STR` | **inferred**: `LDOUTO` (last sale) + `NBRDTO` (days since last sale) |
| Negative stock sheet | `ITEMPR PHQTPR ISTSPR` (not `CPVAL`) | store × item below zero | `STR` (or chosen) | user / file name / file date |
| LPO list (RT LPO) | `LPO LPODAT DLYDAT LPOVAL LPOSTA OTYPE CSUP` | one purchase order | `STR` | latest `LPODAT` |

**RealTime columns:**
- Hierarchy: `CSECW1` department, `CRAYW1` section, `CFAMW1` family, `CSFAW1` sub-family.
- Item: `NARTW1` item, `LARTW1` description, `NFOUW1` supplier, `CMARW1` brand.
- Barcode: `CEANW1` + `DEANW1` (often destroyed by Excel, so never used as a key).
- Status: `CARRW1` item status, `STAFW1` supplier-item status (AC/NC), `ASSTW1` assortment, `RNGCW1` range
  (007 = permanent/blocked).
- Stock and prices: `QPHYW1` stock, `PVTCW1` selling price including tax, `PRNVW1`/`PRFTW1`/`PAFFW1`/`PHTVW1`
  cost (equal in every sample; `PRNVW1` is used first).
- Other: `MARGW1` margin %, `PPTCW1` promo price, `PCBRW1` flow (DIR = direct), `NORDW1`.
- Dates are YYMMDD. The meaning of `DDVAW1`, `DDENW1` and `NORDW1` is still to be confirmed.

**Benchmark columns:** `_T` = net sales without tax, `_Q` = quantity, `_M` = margin (= T − Q × PP, checked on
import), `_S` = stock. Only items that sold somewhere in the period appear. `FRMDAT/TODAT` are dd/mm/yy.

**Zero stock sheet columns (suffix `TO`):**
- `PHQTTO` stock; `LDINTO` / `LDOUTO` last receipt / last sale; `NBRDTO` days since last sale.
- `DLYAVG` average daily sales; `ITMAOP` ordering (AO automatic / REG manual / AOP unknown).
- Orders: `NCDED` open LPO (0 = none); `DLIVD` due date; `DNEXT` next order (999999 = none); `NCDEM` last
  LPO; `TOTORD` / `TOTRCV` total ordered / received.
- `CODDES` **GIMA's own out-of-stock reason**.
- Other: `QMINM` minimum, `FACING`, `SLOWMV`, `PROMO`, `IMPSUP`.

**LPO columns:**
- Dates: `LPODAT` / `DLYDAT` order / delivery date (DDMMYY with the leading zero dropped: `70926` = 07-09-26).
- Values: `LPOVAL`, `GRNVAL` (0 = not received), `XLPQTY` quantity.
- `LPOSTA`: EM issued, RE/BV received.
- `OTYPE`: AO / REG / HOP.
- `CSUP = D` means **purged (deleted)**.
- `USER = GIMA<store>` means automatic.

### BO reports (numbered report codes)

| Report | Fingerprint | Analysed |
|---|---|---|
| 500-30-15 Zero Stock Report Summary: store, department and section tabs | code + `Total Items / Zero Stock / % Zero Stock` per day | yes: `zs_daily` |
| 200-10-05 store net sales | `Section Code Name`, `Section Weight`, `Pent. Rate` | kept |
| 11b country / department / section (Daily, MTD, YTD) | `Penetration Rate %`, `Net Margin After Waste%`, `Promo Weight%` | kept |
| 11f section-family-supplier (with store) | `B2C LY/CY`, `B2B LY/CY`, `B2B Weight%` | kept |
| Family sales (year on year, online/offline) | `Gth %` with year columns | kept |
| 500-30-49 variance of lines | `% Variance` + report code | kept |
| 500-90-08 leaflet zero stock | `Leaflet Code`, `Promotional Item count` | kept |
| 200-10-10 stock days | `Monthly Average Stock`, `Stock Growth` | kept |
| Stock movement analysis (negative, under 6 pcs, corrections) | `Count of Negative`, `Count of Less 6 pcs` | kept |

**500-30-15 layout.** Blocks per department (`01-CGD`) and optionally per section (`S011 - Beverage`). A date
row has one date per group of columns. A label row holds `Total Items | Zero Stock | % Zero Stock`, and it
can come before *or* after the date row. Store rows carry corporate-coded names. `PAK Pakistan` / `PAK SM
Pakistan` rows are group totals and are skipped. Dates are m/d/yyyy.

### BC workbook (business cycle team)

| Tab | Analysed |
|---|---|
| Summary (weekly indicators): a GIMA code row above the header, `Main Indicators`, `Targets` per format, store columns, `No. of Greens` | yes: `bc_value`, and targets are learned |
| EOL, Purge and SSL, Sleeping stock, Label survey | kept (recalculated from GIMA where possible) |
| Blocked stock / permanent range 007 ("Data"): two stock dates above `STOCK 1` / `STOCK 2` | yes: `blocked_item` |
| RT LPO | LPO list (above) |
| Zero stock (500-30-15 tabs) | above |

### DP workbook (depreciation / aged stock)

| Tab | Analysed |
|---|---|
| Master data (often hidden, item level) | yes: `dp_item`. "Current Month" rows are kept when the sheet mixes months. |
| Summary, Ageing by store, Comparison (department / section), Top 50, High risk | kept |

**Master data columns:**
- `Stores` (GIMA code) or `Stores Names`; `ITEMPR`; `PHQTPR` qty.
- Prices: `CSTPPR` cost, `SELPPR` price including tax, `SELPR1` without tax.
- `CPVAL` DP value = qty × cost.
- Age and provision: `AGNGPR` age in days, `Dep Provision` amount, `DEPPC` provision %.
- Buckets: `L31 … G720` (the provision placed in its age bucket); `Months` bucket label.
- `High Risk %age` (formula unknown); `ROT` (999 = no sales?).
- The workbook-level report date is read from "Stock as at 20 Sep" on the summary tab.

### Leaflet workbook

**C&L theme tab.** The title row holds the theme and dates, e.g. "(17-09-2026 to 07-10-2026)".
- Columns: `STORE`, `ITEM`, `PP`, `SP`, `THEME`, `THEME NAME`, `THEME ST` (C-Theme = themed campaign,
  L-Theme = 14–15 day store leaflet), `STKQTY`, `STATUS`, `STK VAL`, `ON ORDER VAL`, `ON ORDER`.
- `01-FMCG` is the same as `01-CGD`.

## 3. Value rules

| Situation | Rule |
|---|---|
| Numbers as text | thousand separators, `(1,234)` negatives, unicode minus, `PKR`/`Rs` prefixes |
| Percentages | `13.%`, `(71.0%)`, `-17.52%`; Excel % cells arrive as fractions: a column with no `%` text where every value ≤ 1.5 is multiplied by 100 |
| Errors / blanks | `#DIV/0!`, `#N/A`, `NA`, `N/A`, `-` = missing (not zero) |
| Dates | decided **per column**: every candidate format is tried on every value, and the one that parses the most, most plausibly, wins (YYMMDD, DDMMYY with the leading zero dropped, d/m/y, m/d/y with AM/PM, d-Mon-yy, `(Thu) 24-Sep-26`, Excel serials, real dates). `0`, `999999` = no date |
| Codes | department `1` → `01`, `01-CGD` / `01-FMCG` / `CGD` → `01`; section `11` / `S011 - Beverage` / `S012-DPH` → `011` |
| Barcodes | `6.2E+11` = destroyed by Excel; always key on item code |
| Percentages printed in reports | never trusted: recomputed from base values |

## 4. Stores

**Identity = GIMA code.**
- Hypermarkets: 500 Fortress, 502 WTC, 503 Emporium, 504 Packages, 505 Lucky One, 506 Lyallpur, P03
  Gujranwala.
- Supermarkets: P06 D-12, P07 DHA Rahbar (DHA-011), P08 DHA 7, P09 Askari 10, PA6 Paragon.
- Mylis (DPH only, inside a host store): P04 (in 500), P05 (504), PA2 (503), PA4 (505), PD4 (P08), PD2 (P07).

Corporate codes (651, 652, 654, 656, 657, 658, 659, 660×2, 661×2, 663, 960…976) are **not unique** and are
only hints. Matching order:
1. Aliases the user confirmed once.
2. An exact GIMA code, including `GIMA500`.
3. A GIMA code in brackets, `(P06)`.
4. A GIMA code as one word, as in `FRT_500` or `DHA07_MYLI_PD4`.
5. Token similarity with prefix credit for cut-off names such as "Paragon Ci".

A Myli marker (H&B, HB, MYLI) must agree with the store format. Closed stores (Dolmen, Clifton, Avenue
Mall, DOL Myli, H&B WTC) and channels (Dark Store, Daraz, Foodpanda) are recognised and skipped. PA3 and PM5
are unknown and flagged.

## 5. Codes

| Code | Meaning |
|---|---|
| AC / NC / NI / AG | active / not active (blocked) / not part of inventory / ageing |
| HO, AOP, HOP | unknown, to be confirmed |
| AO / REG | automatic / regular (manual) ordering |
| Range 007 | permanent range, blocked |
| LPO EM / RE / BV | issued / received / received and validated; `CSUP = D` purged |
| Departments | 01 CG, 02 FFD, 03 LHH, 04 HHH, 05 TXT. DPH = S012 within CG. |

## 6. Formulas (confirmed against the workbooks)

| Measure | Formula |
|---|---|
| Zero stock % (BC) | Σ zero-stock item-days ÷ Σ ranged item-days over the month; zero = closing stock ≤ 0 (negative included); fresh (02) not in the KPI; format averages are totals ÷ totals |
| Stock under 6 pcs CG | items with stock < 6 (zero and negative included) ÷ CG items |
| Negative stock FMCG | items with stock < 0 ÷ items |
| No sales 30d CG / 60d non-food | **by value**: sleeping stock value ÷ stock value (AC items) |
| Combined EOL % | stock value of items that are AST1 = EOL **or** range 007 ÷ total stock value |
| Purge % | purged LPOs ÷ all LPOs |
| SSL % | qty received ÷ qty ordered |
| Label quantity % | labels ÷ items in store (`LBLCNT ÷ STRCNT`) |
| Label quality % | (`LBLCNT` − `PRCMAT` − `NOLBL` − `NOITM`) ÷ `LBLCNT` |
| Stock corrections % | (M± + O± movements) ÷ items |
| DP roll-forward | opening + added − resolved = closing (resolved = sold, wasted, cleared or returned) |
| DP provision | DP value × provision % for the item's department / section and age |
| Lost sales | DLYAVG × days since last sale × price without tax (÷ 1.18) |

Still unknown: the Variance of Lines formula, the High Risk %age formula, the exact Stock Days formula, and
the exact set of indicators the BC team counts as greens (a recount can differ by one; the app shows the
BC team's own count and flags the difference).

## 7. Checks on import (never rejects, always explains)

- **Bad snapshot:** a day where total items drop well below the median and almost nothing is at zero. It
  is marked `suspect` and left out of averages.
- **Blank days** per store.
- **Range cut:** items removed from the range while zero stock falls by a similar amount. The improvement
  came from delisting, not restocking.
- **Sudden jump:** many more items at zero with the range unchanged (a stock count or adjustment?).
- **Printed % differs** from the recalculation.
- **Copied value:** a store cell in the BC scorecard that equals another format's average exactly.
- **Duplicate-looking orders:** same store, supplier, day and value.
- **Late orders:** EM past the due date.
- **Leaflet items below cost.**
- **Provision ≠ value × %.**
- **Margin ≠ sales − qty × PP.**
- **Destroyed barcodes**, duplicates, missing prices.
- **Unknown stores**, listed for one-time mapping in Settings.
- **Report date source** is always stated (from the data, the file name, or the file date).

## 8. Rules learned from files

- **DP provision table:** the most common % per (department[:section], age step) in each DP master file
  updates `dp_rules`. A section rule overrides its department rule.
- **BC targets:** the `Targets` columns of each scorecard update `bc_targets` per format.

Default DP rules (inferred):

| Department | Enters DP at | Provision steps |
|---|---|---|
| FMCG | 361 days | 30 / 50 / 70% at 361 / 541 / 721 days |
| LHH | 181 days | 10 → 50%; Stationery, Toys, Sports up to 75% |
| HHH | 91 days | 5 → 70% |
| TXT | 91 days | 10 → 90% |

## 9. Known issues in shared workbooks (for the BC / DP teams)

These are error *types* found in samples. The app detects most of them automatically.

- A Myli column in the scorecard taking figures from the hypermarket average row.
- A format subtotal divided by the wrong store count (the % survives, but the averages shown are wrong).
- A pivot's store-type list missing stores, which understates the headline totals.
- A 10K–15K bucket copying the 5K–10K bucket.
- A format "average %" that is the sum of the store percentages.
- A share-of-stock lookup failing because store names have trailing spaces.
- An indicator shown as N/A on the scorecard although the source tab has a value.
