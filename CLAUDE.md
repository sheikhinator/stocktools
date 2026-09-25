# Carrefour Pakistan — Stock Status & Management Tool

## Purpose
A PC tool for MAF Carrefour Pakistan that turns system-generated reports (GIMA, BO, BC/DP workbooks) into stock-health diagnostics, commercial performance views and actionable lists. Goal: improve BC indicators and give every stakeholder — from section manager to head office — a clear, quantified (PKR) view of stock and sales performance.

It is an **operations + commercial** tool: supply chain, stock health, sales, margin, suppliers, promotions, ageing/depreciation.

## Tech constraints
- Proper Windows desktop software, distributed as a downloadable .exe installer (per-user install, no admin) plus a portable build. NOT an HTML page.
- Works fully offline; no server or internet needed to run. Report data never leaves the PC.
- Stack: Python + PySide6 (Qt) UI, DuckDB for storage and processing (Polars optional), calamine/fastexcel for fast Excel reading, xlsxwriter for export, PyInstaller + Inno Setup built on a GitHub Actions Windows runner.
- Must handle large item × store datasets (100k+ rows, 11F store tab can be several hundred thousand) quickly. Heavy processing runs off the UI thread with a progress bar.
- Local storage of dated snapshots in DuckDB for trend and week-over-week comparisons.
- MAF brand colours: brown, gold, white. Currency: PKR.

## Status
All sample report formats collected — see `docs/DATA_SOURCES.md` (the importer spec: every report, column meanings, formulas, code tables, store master, BC targets, inferred DP rules, and known errors in shared workbooks).
**Next step:** build v1 — app shell, smart importer, store/code master tables, snapshot DB, first screens (zero/negative stock, BC scorecard, DP/ageing).

## Key principles
- **Store identity = GIMA code** (500, 502, P03, PA6, …). Corporate codes (651, 660, …) are NOT unique — match those reports by store name via an editable alias table.
- **Smart parsing, never give up**: detect report type from report code/header/layout; detect columns from data (dates in YYMMDD, DMMYY-without-leading-zero, dd/mm/yy, m/d/yyyy h:mm AM; bracket negatives; `#DIV/0`; `13.%`); read hidden sheets and pivot caches; tolerate missing/extra stores and rows; flag anomalies instead of rejecting.
- **Barcodes are often destroyed by Excel** (`6.2E+11`). Always key on item code, never barcode.
- Unknown codes are inferred from behaviour and confirmed once by the user, then remembered.
- Recompute percentages from base values; never trust printed %.

## Users & modes
- **Store mode**: section managers, department heads (CG head, FFD head, one Non-Food head for LHH+HHH+TXT), store manager.
- **Head office mode**: commercial/category, BC (business cycle) team, supply chain — all stores.

## Phase 1
1. Data intake (multi-file, any store scope, date selector, snapshots).
2. Stock health: zero stock (BC definition: closing stock ≤ 0 incl. negative), OOS vs zero stock, sleeping (CG 30d / Non-Food 60d), overstock, negative stock with cause (AC/NC/NI).
3. On-order logic: OOS not on order (top priority), late LPOs, GIMA OOS reason categories, conflicts (NC/007 items on order, AO vs REG).
4. IST opportunities.
5. Sales & velocity: ROS (DLYAVG), days of cover, ABC; A-class and promo/leaflet OOS first.
6. BC scorecard computed and explained item by item.
7. DP/ageing: provision, ageing buckets, early warning (items about to age in), resolve route (IST → markdown → RTS → write-off).

## Phase 2
- Markdown candidates from age/cover/provision (no "optimal price" claims without price history).
- Min/max suggested order quantities, aged stock analysis, supplier scorecards, RTS terms.

## Outputs
- Head office summary: lost sales from OOS (DLYAVG × days out × price), PKR tied in sleeping/DP/EOL stock, store rankings, BC green count.
- Action lists per section manager, exportable to Excel.
- Drill-down: country → store → department → section → family → item.

## Business context
- Departments: 01 Consumer Goods (CG/FMCG), 02 Fresh Food (FFD), 03 Light Household (LHH), 04 Heavy Household (HHH), 05 Textile (TXT).
- Store types: Hypermarket, Supermarket, Myli (H&B) — standalone DPH stores inside hypers/supers.
- DPH (S012) is a section within CG, not a department.
- Online sales = Foodpanda. Front margin = margin before back margin / supplier rebates.
- Consignment stock is not our inventory (exclude from stock value, DP, markdown, IST).
