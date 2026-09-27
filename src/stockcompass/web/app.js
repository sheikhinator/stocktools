/* Stock Compass screens: the v2 demo interface, every number from the local data service (web/api.py).
   Hover anything for its breakdown, click anything to drill store → department → section → family → item. */
"use strict";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const fmtN = v => v == null || !isFinite(v) ? "—" : Math.round(v).toLocaleString("en-US");
const fmtM = v => {if (v == null || !isFinite(v)) return "—"; const a = Math.abs(v), s = v < 0 ? "−" : ""; if (a >= 1e9) return s + (a / 1e9).toFixed(2) + "B"; if (a >= 1e6) return s + (a / 1e6).toFixed(a >= 1e8 ? 0 : 1) + "M"; if (a >= 1e3) return s + (a / 1e3).toFixed(a >= 1e5 ? 0 : 1) + "K"; return s + Math.round(a)};
const pkr = v => v == null || !isFinite(v) ? "—" : "PKR " + fmtM(v);
const pc = (v, d = 1) => v == null || !isFinite(v) ? "—" : (v < 0 ? "−" : "") + Math.abs(v).toFixed(d) + "%";
const sg = (v, d = 1) => v == null || !isFinite(v) ? "—" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(d) + "%";
const IC = {cal: '<svg class="ic" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
  pin: '<svg class="ic" viewBox="0 0 24 24"><path d="M12 22s7-7.2 7-12a7 7 0 0 0-14 0c0 4.8 7 12 7 12z"/><circle cx="12" cy="10" r="2.5"/></svg>',
  cmp: '<svg class="ic" viewBox="0 0 24 24"><path d="M12 3v18M5 7h14M5 7l-3 7h6zM19 7l-3 7h6z"/></svg>',
  gear: '<svg class="ic" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1L7 17M17 7l2.1-2.1"/></svg>'};
/* Urdu screens: keep English words, numbers and dates inside a sentence in their own left-to-right run */
const bx = s => {const e = esc(s); if (S.lang !== "ur") return e; return e.replace(/[A-Za-z0-9+\-−≤≥%.,:()\/&#;·–|×]+(?: +[A-Za-z0-9+\-−≤≥%.,:()\/&#;·–|×]+)*/g, m => {if (!/[A-Za-z0-9]/.test(m)) return m; const l = m.match(/^[·–|\s]*/)[0], r = m.slice(l.length).match(/[·–|\s]*$/)[0]; return l + `<bdi dir="ltr">${m.slice(l.length, m.length - r.length)}</bdi>` + r})};
const bd = s => `<bdi dir="ltr">${s}</bdi>`;
const icon = {good: "✓", warn: "!", crit: "✕", serious: "!", neutral: ""};
const chip = (c, x) => `<span class="chip ${c}">${icon[c] && !/^[\s]*[✓✕!▲▼⚠]/.test(String(x).replace(/<[^>]+>/g, "")) ? icon[c] + " " : ""}${x}</span>`;
const J = o => encodeURIComponent(JSON.stringify(o));
const stc = s => ({bad: "crit", good: "good", warn: "warn", crit: "crit", serious: "serious"}[s] || "neutral");
const MON_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MON_UR = ["جنوری", "فروری", "مارچ", "اپریل", "مئی", "جون", "جولائی", "اگست", "ستمبر", "اکتوبر", "نومبر", "دسمبر"];
const fdate = s => {if (!s) return "—"; const [y, m, d] = String(s).slice(0, 10).split("-").map(Number); if (!m) return String(s); return `${d} ${(S.lang === "ur" ? MON_UR : MON_EN)[m - 1]}${y !== new Date().getFullYear() ? " " + y : ""}`};
const fday = s => {const [, m, d] = String(s).slice(0, 10).split("-").map(Number); return `${d} ${(S.lang === "ur" ? MON_UR : MON_EN)[m - 1]}`};

/* ---------------- words (the data service sends its own titles and labels) ---------------- */
const T = {
  en: {agent: "Agent", noJobs: "Nothing to do today", noJobsP: "No out-of-stock, negative, late-order or aged-stock jobs for this store and section.", resetTip: "Back to all stores, all departments, month to date, vs budget", vsL: "vs", deptS: "Dept", brand: "Stock Compass", brandsub: "Carrefour Pakistan", home: "Home", sales: "Sales", stock: "Stock health", orders: "Orders", promos: "Promotions",
    category: "Category", score: "BC scorecard", health: "Data checks", import: "Add reports", settings: "Settings",
    search: "Search item code, name, supplier or store", search2: "Search in this table", rows: "rows", export: "Export", page: "Page", of: "of", total: "Total",
    chartView: "Chart", tableView: "Table", tipClick: "Click to see what's inside", how: "How is this worked out?", definition: "What it means",
    formula: "How it is worked out", source: "Source", asOf: "as of", close: "Close", drill_t: "What makes up this number", groupBy: "Group by",
    item360: "Item card", sup360: "Supplier card", recommend: "What to do", price: "Price (incl. tax)", cost: "Cost", margin: "Margin", status: "Status",
    stockByStore: "Stock by store", units: "units", emptyNow: "Out of stock", where: "Where", dept: "Department", sec: "Section", when: "Period",
    compare: "Compare with", viewAs: "View as", allPk: "All Pakistan", allDept: "All departments", allSec: "All sections", regions: "Regions",
    formats: "Formats", storesL: "Stores", fH: "Hypermarkets", fS: "Supermarkets", fM: "Mylis", r_ho: "Head office", r_dm: "District manager (country)",
    r_sm: "Store manager", r_dh: "Department head", r_sec: "Section manager", c_budget: "Budget", c_ly: "Last year", addReports: "Add reports",
    loading: "Working it out…", noData: "Nothing here yet", importFirst: "Add the reports to fill this screen.", goImport: "Add reports",
    yes: "Yes", no: "No", reset: "Reset filters", share: "Share", lower: "lower is better", higher: "higher is better", target: "Target",
    myJobs: "Your jobs today", jobsDone: "done", exportJobs: "Export action list", knowTitle: "What you need to know", stars: "Growing & profitable",
    cash: "Profitable, shrinking", question: "Growing, low margin", problems: "Shrinking, low margin", growth: "Growth", netSales: "Net sales",
    exported: "Saved to", cancelled: "Cancelled", nf: "Non-food (LHH, HHH, TXT)", dataFresh: "Data on this PC only", version: "Version",
    drop: "Drop Excel, CSV or text files here, or", pick: "Choose files", pickFolder: "Choose a folder", paste: "Paste from Excel", importNow: "Import",
    clear: "Clear", reviewT: "Review before importing", reviewP: "Stock Compass read every sheet, including hidden ones and pivot caches. Change anything that is wrong.",
    file: "File", sheet: "Sheet", type: "Report", conf: "Sure", storeC: "Store", dateC: "Date", note: "Note", skip: "Skip this sheet", generic: "Keep as rows (not recognised)",
    already: "already imported", pasteHere: "Copy cells in Excel (with the header row) and paste them here.", history: "Imported reports", del: "Delete",
    delQ: "Delete this import? Its numbers will disappear from every screen.", done: "Done", results: "What was imported", chooseStore: "Choose the store",
    lang: "Language", nastaliq: "Nastaliq", naskh: "Naskh", thresholds: "Thresholds", targets: "BC targets", save: "Save", saved: "Saved",
    storesT: "Stores and names", unknown: "Names we could not match", addAlias: "Add as a name for", dpRules: "DP provision steps", people: "Stores",
    error: "Something went wrong", retry: "Try again", period: "Period", theme: "Promotion", itemsL: "items", day: "day", phase: "Phase",
    cell: "Scorecard cell", ours: "Our calculation", bcTeam: "BC team", seeItems: "See the items", peers: "Same format stores", computed: "computed by Stock Compass"},
  ur: {vsL: "موازنہ", deptS: "ڈیپارٹمنٹ", brand: "اسٹاک کمپاس", brandsub: "کیریفور پاکستان", home: "ہوم", sales: "سیلز", stock: "اسٹاک کی صحت", orders: "آرڈرز", promos: "پروموشنز",
    category: "کیٹیگری", score: "بی سی اسکور کارڈ", health: "ڈیٹا چیک", import: "رپورٹس شامل کریں", settings: "سیٹنگز",
    search: "آئٹم کوڈ، نام، سپلائر یا اسٹور تلاش کریں", search2: "اس ٹیبل میں تلاش کریں", rows: "قطاریں", export: "ایکسپورٹ", page: "صفحہ", of: "میں سے", total: "کل",
    chartView: "چارٹ", tableView: "ٹیبل", tipClick: "اندر دیکھنے کے لیے کلک کریں", how: "یہ کیسے نکالا گیا؟", definition: "مطلب",
    formula: "حساب", source: "ماخذ", asOf: "بتاریخ", close: "بند کریں", drill_t: "یہ نمبر کس سے بنا ہے", groupBy: "گروپ",
    item360: "آئٹم کارڈ", sup360: "سپلائر کارڈ", recommend: "کیا کریں", price: "قیمت (ٹیکس سمیت)", cost: "لاگت", margin: "مارجن", status: "حالت",
    stockByStore: "اسٹور کے حساب سے اسٹاک", units: "یونٹس", emptyNow: "آؤٹ آف اسٹاک", where: "کہاں", dept: "ڈیپارٹمنٹ", sec: "سیکشن", when: "مدت",
    compare: "موازنہ", viewAs: "بطور", allPk: "پورا پاکستان", allDept: "تمام ڈیپارٹمنٹس", allSec: "تمام سیکشنز", regions: "علاقے",
    formats: "فارمیٹس", storesL: "اسٹورز", fH: "ہائپر مارکیٹس", fS: "سپر مارکیٹس", fM: "مائلی", r_ho: "ہیڈ آفس", r_dm: "ڈسٹرکٹ مینیجر",
    r_sm: "اسٹور مینیجر", r_dh: "ڈیپارٹمنٹ ہیڈ", r_sec: "سیکشن مینیجر", c_budget: "بجٹ", c_ly: "پچھلا سال", addReports: "رپورٹس شامل کریں",
    loading: "حساب ہو رہا ہے…", noData: "ابھی یہاں کچھ نہیں", importFirst: "یہ اسکرین بھرنے کے لیے رپورٹس شامل کریں۔", goImport: "رپورٹس شامل کریں",
    yes: "ہاں", no: "نہیں", reset: "فلٹر ہٹائیں", share: "حصہ", lower: "کم بہتر ہے", higher: "زیادہ بہتر ہے", target: "ہدف",
    myJobs: "آج کے کام", jobsDone: "مکمل", exportJobs: "ایکشن لسٹ ایکسپورٹ کریں", knowTitle: "آپ کو کیا جاننا چاہیے", stars: "بڑھتا اور منافع بخش",
    cash: "منافع بخش، گھٹتا", question: "بڑھتا، کم مارجن", problems: "گھٹتا، کم مارجن", growth: "اضافہ", netSales: "نیٹ سیلز",
    exported: "محفوظ کیا گیا", cancelled: "منسوخ", nf: "نان فوڈ (LHH, HHH, TXT)", dataFresh: "ڈیٹا صرف اس کمپیوٹر پر", version: "ورژن",
    drop: "ایکسل، CSV یا ٹیکسٹ فائلیں یہاں چھوڑیں، یا", pick: "فائلیں منتخب کریں", pickFolder: "فولڈر منتخب کریں", paste: "ایکسل سے پیسٹ کریں", importNow: "امپورٹ کریں",
    clear: "صاف کریں", reviewT: "امپورٹ سے پہلے دیکھ لیں", reviewP: "ہر شیٹ پڑھ لی گئی، چھپی ہوئی شیٹس اور پیوٹ بھی۔ جو غلط ہو بدل دیں۔",
    file: "فائل", sheet: "شیٹ", type: "رپورٹ", conf: "یقین", storeC: "اسٹور", dateC: "تاریخ", note: "نوٹ", skip: "یہ شیٹ چھوڑ دیں", generic: "قطاروں کی صورت میں رکھیں",
    already: "پہلے امپورٹ ہو چکی", pasteHere: "ایکسل میں خانے (ہیڈر سمیت) کاپی کر کے یہاں پیسٹ کریں۔", history: "امپورٹ شدہ رپورٹس", del: "حذف",
    delQ: "یہ امپورٹ حذف کریں؟ اس کے نمبر ہر اسکرین سے ہٹ جائیں گے۔", done: "مکمل", results: "کیا امپورٹ ہوا", chooseStore: "اسٹور منتخب کریں",
    lang: "زبان", nastaliq: "نستعلیق", naskh: "نسخ", thresholds: "حدیں", targets: "بی سی اہداف", save: "محفوظ کریں", saved: "محفوظ ہو گیا",
    storesT: "اسٹورز اور نام", unknown: "نام جو میچ نہیں ہوئے", addAlias: "اس کا نام بنائیں", dpRules: "DP پروویژن کے مراحل", people: "اسٹورز",
    error: "کچھ غلط ہو گیا", retry: "دوبارہ کوشش کریں", period: "مدت", theme: "پروموشن", itemsL: "آئٹمز", day: "دن", phase: "مرحلہ",
    cell: "اسکور کارڈ خانہ", ours: "ہمارا حساب", bcTeam: "بی سی ٹیم", seeItems: "آئٹمز دیکھیں", peers: "اسی فارمیٹ کے اسٹورز", computed: "اسٹاک کمپاس کا حساب"}
};
const t = k => T[S.lang][k] ?? T.en[k] ?? k;

/* ---------------- state ---------------- */
const S = {lang: "en", naskh: false, role: "ho", roleStore: "", roleDept: "01", roleSec: "", page: "home",
  f: {where: "all", dept: "", section: "", period: "", compare: "budget"}, tab: "oos", theme: "", scoreF: "H",
  data: null, busy: 0, drawer: null, modal: null, tv: {}, tbl: {}, q: "", sugg: [], toast: null, boot: null, imp: null};
const PAGES = ["home", "agent", "sales", "stock", "orders", "promos", "category", "score"];
const ICONS = {home: '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>', sales: '<path d="M4 19V9M10 19V5M16 19v-7M22 19H2"/>',
  stock: '<path d="M3 7l9-4 9 4v10l-9 4-9-4z"/><path d="M3 7l9 4 9-4M12 11v10"/>', orders: '<path d="M3 6h11v10H3zM14 9h4l3 3v4h-7"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
  promos: '<path d="M20 12l-8 8-9-9V3h8z"/><circle cx="7.5" cy="7.5" r="1.5"/>', score: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
  category: '<path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/>', health: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  import: '<path d="M12 3v12M7 10l5 5 5-5M4 21h16"/>',
  agent: '<path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>'};
const svgI = k => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[k]}</svg>`;
const allowed = () => ({ho: [...PAGES, "health"], dm: [...PAGES, "health"], sm: ["home", "agent", "sales", "stock", "orders", "promos", "score"],
  dh: ["home", "agent", "sales", "stock", "orders", "promos", "score"], sec: ["home", "agent", "sales", "stock", "orders", "promos"]})[S.role] || PAGES;
const storeRole = () => ["sm", "dh", "sec"].includes(S.role);

/* ---------------- talking to the data service ---------------- */
let bridge = null;
function ctx() {
  const c = {lang: S.lang, role: S.role, period: S.f.period, compare: S.f.compare, where: S.f.where, dept: S.f.dept, section: S.f.section};
  if (storeRole()) c.where = S.roleStore || "all";
  if (S.role === "dh") {c.dept = S.roleDept; c.section = S.f.section}
  if (S.role === "sec") {c.dept = ""; c.section = S.roleSec}
  return c;
}
function api(method, params = {}) {
  const p = JSON.stringify({...params, ctx: ctx()});
  return new Promise((res, rej) => {
    if (bridge) bridge.call(method, p, r => {try {res(JSON.parse(r))} catch (e) {rej(e)}});
    else fetch("api/" + method, {method: "POST", headers: {"Content-Type": "application/json"}, body: p}).then(r => r.json()).then(res, rej);
  });
}
const cache = new Map();
function pageKey() {return JSON.stringify([S.page, ctx(), S.tab, S.theme, S.scoreF])}
async function load(force) {
  if (S.page === "agent") {agentLoad(); return}
  const key = pageKey();
  if (!force && cache.has(key)) {S.data = cache.get(key); render(); return}
  S.busy++; render();
  let d;
  try {d = await api("page", {name: S.page, tab: S.tab, theme: S.theme, fmt: S.scoreF})} catch (e) {d = {error: String(e)}}
  S.busy--;
  if (key !== pageKey()) return;           // the user moved on while this was loading
  if (!d.error) cache.set(key, d);
  S.data = d; render();
}
function saveView() {api("save_view", {view: {lang: S.lang, role: S.role, roleStore: S.roleStore, roleDept: S.roleDept, roleSec: S.roleSec, naskh: S.naskh, where: S.f.where, dept: S.f.dept, section: S.f.section, compare: S.f.compare}})}

/* ---------------- tooltip ---------------- */
const tip = $("#tip");
document.addEventListener("pointermove", e => {
  const el = e.target.closest("[data-tip]"); if (!el) {tip.hidden = true; return}
  tip.innerHTML = el.getAttribute("data-tip"); tip.hidden = false; const w = tip.offsetWidth, h = tip.offsetHeight; let x = e.clientX + 14, y = e.clientY + 14;
  if (x + w > innerWidth - 8) x = e.clientX - w - 14; if (y + h > innerHeight - 8) y = e.clientY - h - 14; tip.style.left = x + "px"; tip.style.top = y + "px";
});
const hideTip = () => {tip.hidden = true};
document.addEventListener("pointerleave", hideTip);
document.addEventListener("pointerdown", hideTip, true);
window.addEventListener("scroll", hideTip, true);
document.addEventListener("keydown", hideTip, true);

/* ---------------- value formats ---------------- */
function fmtV(v, f) {
  if (v == null || v === "" || (typeof v === "number" && !isFinite(v))) return "—";
  if (typeof v === "string" && !["date", "text", "name"].includes(f) && isNaN(+v)) return v;
  switch (f) {
    case "pkr": return pkr(+v); case "money": case "int": return fmtN(+v);
    case "num": return (+v).toLocaleString("en-US", {maximumFractionDigits: 2});
    case "pct": case "pct_chip": case "pct_neg": return pc(+v); case "sg": return sg(+v); case "x": return (+v).toFixed(2) + "×";
    case "date": return fdate(v); case "bool": return v ? t("yes") : t("no");
    default: return String(v);
  }
}
const axisF = f => f === "pkr" || f === "money" ? v => fmtM(v) : f === "pct" ? (v, d = 0) => pc(v, d) : v => fmtN(v);

/* ---------------- charts (as in the demo) ---------------- */
function nice(lo, hi, n = 4) {const span = hi - lo || 1; const raw = span / n; const p = Math.pow(10, Math.floor(Math.log10(raw))); const m = raw / p; const st = (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p; return {lo: Math.floor(lo / st) * st, hi: Math.ceil(hi / st) * st, st}}
const PAL = ["var(--s1)", "var(--s2)", "var(--s3)", "#6a8f3a", "#8a4fa3", "#2a9d8f", "#c0506a", "#5c6b7a"];
function lineChart({id, series, xs, fmt, height = 260, zero = false, drill}) {
  series.forEach((s, i) => {if (!s.c) s.c = PAL[i % PAL.length]});
  const fmtY = axisF(fmt), W = 640, H = height, L = 52, Rr = 12, Tp = 14, B = 26; const all = series.flatMap(s => s.v).filter(v => v != null);
  if (!all.length) return emptyBox(t("noData"), "");
  let lo = zero ? 0 : Math.min(...all), hi = Math.max(...all); if (!zero) {const pad = (hi - lo) * .15 || 1; lo -= pad; hi += pad; if (Math.min(...all) >= 0) lo = Math.max(0, lo)} const n = nice(lo, hi); lo = zero ? 0 : Math.max(Math.min(...all) >= 0 ? 0 : -Infinity, n.lo); hi = n.hi;
  const x = i => L + (W - L - Rr) * (xs.length === 1 ? .5 : i / (xs.length - 1)), y = v => Tp + (H - Tp - B) * (1 - (v - lo) / (hi - lo));
  let g = ""; for (let v = lo; v <= hi + 1e-9; v += n.st) g += `<line class="gridl" x1="${L}" x2="${W - Rr}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${fmtY(v)}</text>`;
  const every = Math.max(1, Math.ceil(xs.length / 8)); xs.forEach((d, i) => {if (i % every === 0 || i === xs.length - 1) g += `<text class="axis" x="${x(i)}" y="${H - 6}" text-anchor="middle">${fday(d)}</text>`});
  series.forEach(s => {
    const pts = s.v.map((v, i) => v == null ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`).filter(Boolean).join(" ");
    if (s.area) g += `<polygon points="${x(0)},${y(lo)} ${pts} ${x(s.v.length - 1)},${y(lo)}" fill="${s.c}" opacity=".09"/>`;
    g += `<polyline points="${pts}" fill="none" stroke="${s.c}" stroke-width="2" ${s.dash ? 'stroke-dasharray="5 4"' : ""} stroke-linejoin="round"/>`;
    const li = s.v.length - 1; if (s.v[li] != null && !s.dash) g += `<circle cx="${x(li)}" cy="${y(s.v[li])}" r="4" fill="${s.c}" stroke="var(--card)" stroke-width="2"/>`;
  });
  const w = (W - L - Rr) / Math.max(1, xs.length - 1);
  const additive = fmt === "pkr" || fmt === "money" || fmt === "int";
  const real = series.filter(s => !s.dash);
  xs.forEach((d, i) => {
    const vals = real.map(s => s.v[i]).filter(v => v != null);
    const body = series.map(s => `<span style="color:${s.c}">■</span> ${esc(s.n)}: <b>${s.v[i] == null ? "—" : fmtY(s.v[i], 1)}</b>`).join("<br>")
      + (additive && vals.length > 1 ? `<br>Total: <b>${fmtY(vals.reduce((a, b) => a + b, 0), 1)}</b>` : "")
      + (i > 0 && real[0] && real[0].v[i] != null && real[0].v[i - 1] != null ? `<br><span style="opacity:.8">vs day before: ${real[0].v[i] - real[0].v[i - 1] >= 0 ? "+" : "−"}${fmtY(Math.abs(real[0].v[i] - real[0].v[i - 1]), 1)}</span>` : "");
    g += `<rect class="hov" x="${x(i) - w / 2}" y="${Tp}" width="${w}" height="${H - Tp - B}" data-tip="${esc(`<b>${fday(d)}</b><br>${body}${drill ? "<br><i>" + t("tipClick") + "</i>" : ""}`)}" ${drill ? `data-drill="${J(drill)}"` : ""}/>`;
  });
  const tbl = `<div class="tbl-wrap"><table><thead><tr><th class="nosort"></th>${series.map(s => `<th class="n nosort">${esc(s.n)}</th>`).join("")}</tr></thead><tbody>${xs.map((d, i) => `<tr><td>${fday(d)}</td>${series.map(s => `<td class="n">${s.v[i] == null ? "—" : fmtY(s.v[i], 1)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  return S.tv[id] ? tbl : `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img">${g}</svg></div>`;
}
function barChart({id, cats, series, fmt, height = 260, drill}) {
  const fmtY = axisF(fmt), W = 640, H = height, L = 52, Rr = 8, Tp = 12, B = 40; const n = nice(0, Math.max(1, ...series.flatMap(s => s.v.map(v => v || 0))) * 1.05); const hi = n.hi;
  const y = v => Tp + (H - Tp - B) * (1 - v / hi); const band = (W - L - Rr) / Math.max(1, cats.length), bw = Math.min(28, band * .7 / series.length);
  const dr = c => drill ? {m: drill.m, path: [{lvl: drill.lvl, k: c.k, n: c.l}]} : null;
  let g = ""; for (let v = 0; v <= hi + 1e-9; v += n.st) g += `<line class="gridl" x1="${L}" x2="${W - Rr}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${fmtY(v)}</text>`;
  cats.forEach((c, ci) => {
    const cx = L + band * ci + band / 2, gw = bw * series.length + 2 * (series.length - 1);
    series.forEach((s, si) => {const bx = cx - gw / 2 + si * (bw + 2), v = Math.max(0, s.v[ci] || 0), top = y(v), bot = y(0), r = Math.max(0, Math.min(4, bw / 2, (bot - top) / 2));
      g += `<path d="M${bx},${bot} V${top + r} Q${bx},${top} ${bx + r},${top} H${bx + bw - r} Q${bx + bw},${top} ${bx + bw},${top + r} V${bot} Z" fill="${s.c}"/>`});
    const lines = String(c.l).split(" "); g += `<text class="axis" x="${cx}" y="${H - 24}" text-anchor="middle">${esc(lines.slice(0, 2).join(" ").slice(0, 22))}</text>` + (lines.length > 2 ? `<text class="axis" x="${cx}" y="${H - 11}" text-anchor="middle">${esc(lines.slice(2).join(" ").slice(0, 22))}</text>` : "");
    const tots = series.map(s => s.v.reduce((a, v) => a + (+v || 0), 0));
    const body = series.map((s, si) => `<span style="color:${s.c}">■</span> ${esc(s.n)}: <b>${fmtV(s.v[ci], fmt)}</b>${fmt !== "pct" && tots[si] ? ` <span style="opacity:.8">(${pc((s.v[ci] || 0) / tots[si] * 100)} of ${fmtV(tots[si], fmt)})</span>` : ""}`).join("<br>")
      + (series.length === 2 && fmt !== "pct" && series[1].v[ci] ? `<br>Difference: <b>${fmtV(series[0].v[ci] - series[1].v[ci], fmt)}</b> (${sg((series[0].v[ci] / series[1].v[ci] - 1) * 100)})` : "");
    g += `<rect class="hov" x="${cx - band / 2}" y="${Tp}" width="${band}" height="${H - Tp - B}" data-tip="${esc(`<b>${esc(c.l)}</b><br>${body}<br><i>${t("tipClick")}</i>`)}" ${drill ? `data-drill="${J(dr(c))}"` : ""}/>`;
  });
  const tbl = `<div class="tbl-wrap"><table><thead><tr><th class="nosort"></th>${series.map(s => `<th class="n nosort">${esc(s.n)}</th>`).join("")}</tr></thead><tbody>${cats.map((c, i) => `<tr class="click" ${drill ? `data-drill="${J(dr(c))}"` : ""}><td>${esc(c.l)}</td>${series.map(s => `<td class="n">${fmtN(s.v[i])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  return S.tv[id] ? tbl : `<div class="chart"><svg viewBox="0 0 ${W} ${H}">${g}</svg></div>`;
}
function waterfall({id, items, start, end, labels, fmt, height = 260, drill}) {
  const fmtY = axisF(fmt), W = 640, H = height, L = 52, Rr = 8, Tp = 18, B = 40; let run = start; const bars = [{l: labels[0], a: 0, b: start, tot: 1}];
  items.forEach(it => {bars.push({l: it.l, a: run, b: run + it.v, v: it.v, k: it.k}); run += it.v}); bars.push({l: labels[1], a: 0, b: end, tot: 1});
  const mn = Math.min(...bars.filter(b => !b.tot).map(b => Math.min(b.a, b.b)), start, end) * .85; const n = nice(mn, Math.max(...bars.map(b => Math.max(b.a, b.b))));
  const lo = Math.max(0, n.lo), hi = n.hi; const y = v => Tp + (H - Tp - B) * (1 - (v - lo) / (hi - lo || 1)); const band = (W - L - Rr) / bars.length, bw = Math.min(44, band * .6);
  let g = ""; for (let v = lo; v <= hi + 1e-9; v += n.st) g += `<line class="gridl" x1="${L}" x2="${W - Rr}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${fmtY(v)}</text>`;
  bars.forEach((b, i) => {
    const cx = L + band * i + band / 2, top = y(Math.max(b.a, b.b)), bot = y(Math.max(lo, Math.min(b.a, b.b))); const col = b.tot ? "var(--s1)" : b.v >= 0 ? "var(--good)" : "var(--crit)";
    g += `<rect x="${cx - bw / 2}" y="${top}" width="${bw}" height="${Math.max(2, bot - top)}" rx="3" fill="${col}"/>`;
    const txt = b.tot ? fmtY(b.b) : (b.v >= 0 ? "+" : "−") + fmtY(Math.abs(b.v)); g += `<text class="lbl" x="${cx}" y="${top - 5}" text-anchor="middle">${txt}</text>`;
    const ws = String(b.l).split(" "); g += `<text class="axis" x="${cx}" y="${H - 24}" text-anchor="middle">${esc(ws[0].slice(0, 14))}</text>` + (ws.length > 1 ? `<text class="axis" x="${cx}" y="${H - 11}" text-anchor="middle">${esc(ws.slice(1).join(" ").slice(0, 14))}</text>` : "");
    if (i < bars.length - 1) g += `<line x1="${cx + bw / 2}" x2="${L + band * (i + 1) + band / 2 - bw / 2}" y1="${y(b.b)}" y2="${y(b.b)}" stroke="var(--muted)" stroke-dasharray="2 2"/>`;
    const d = !b.tot && drill ? {m: drill.m, path: [{lvl: drill.lvl, k: b.k, n: b.l}]} : null;
    g += `<rect class="hov" x="${cx - band / 2}" y="${Tp}" width="${band}" height="${H - Tp - B}" data-tip="${esc(`<b>${esc(b.l)}</b><br>${b.tot ? pkr(b.b) : (b.v >= 0 ? "+" : "−") + pkr(Math.abs(b.v)) + `<br>Running total: <b>${pkr(b.b)}</b>` + (start ? ` (${sg(b.v / start * 100)} of ${esc(labels[0])})` : "")}${d ? "<br><i>" + t("tipClick") + "</i>" : ""}`)}" ${d ? `data-drill="${J(d)}"` : ""}/>`;
  });
  const tbl = `<div class="tbl-wrap"><table><tbody>${bars.map(b => `<tr><td>${esc(b.l)}</td><td class="n">${b.tot ? fmtN(b.b) : (b.v >= 0 ? "+" : "−") + fmtN(Math.abs(b.v))}</td></tr>`).join("")}</tbody></table></div>`;
  return S.tv[id] ? tbl : `<div class="chart"><svg viewBox="0 0 ${W} ${H}">${g}</svg></div>`;
}
function hbars({items, fmt, max}) {
  if (!items.length) return emptyBox(t("noData"), "");
  const hi = max || Math.max(...items.map(i => i.v || 0), 1);
  const tot = items.reduce((a, i) => a + (+i.v || 0), 0); const addv = fmt !== "pct" && fmt !== "num";
  return `<div style="display:flex;flex-direction:column;gap:6px">${items.map(it => `<button class="hbar-row" ${it.drill ? `data-drill="${J(it.drill)}"` : ""} data-tip="${esc(`<b>${esc(it.l)}</b><br>${fmtV(it.v, fmt)}${addv && tot ? ` · ${pc((it.v || 0) / tot * 100)} of total ${fmtV(tot, fmt)}` : ""}${it.x ? "<br>" + esc(it.x) : ""}${it.drill ? "<br><i>" + t("tipClick") + "</i>" : ""}`)}">
  <span style="font-weight:700;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(it.l)}</span><span style="height:12px;border-radius:0 4px 4px 0;background:var(--line-2);direction:ltr"><i style="display:block;height:100%;width:${Math.max(0, Math.min(100, (it.v || 0) / hi * 100)).toFixed(1)}%;background:${it.c || "var(--s1)"};border-radius:0 4px 4px 0"></i></span>
  <span class="num" style="font-weight:800;font-variant-numeric:tabular-nums">${bd(fmtV(it.v, fmt))}</span></button>`).join("")}</div>`;
}
function scatter({id, pts, height = 300}) {
  if (!pts.length) return emptyBox(t("noData"), "");
  const W = 640, H = height, L = 46, Rr = 14, Tp = 14, B = 30; const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
  const nx = nice(Math.min(-20, ...xs) - 3, Math.max(30, ...xs) + 3), ny = nice(Math.min(-10, ...ys) - 3, Math.max(35, ...ys) + 3);
  const x = v => L + (W - L - Rr) * (v - nx.lo) / (nx.hi - nx.lo), y = v => Tp + (H - Tp - B) * (1 - (v - ny.lo) / (ny.hi - ny.lo)); const avgM = pts.reduce((a, p) => a + p.y * p.s, 0) / (pts.reduce((a, p) => a + p.s, 0) || 1);
  let g = ""; for (let v = ny.lo; v <= ny.hi + 1e-9; v += ny.st) g += `<line class="gridl" x1="${L}" x2="${W - Rr}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${Math.round(v)}%</text>`;
  for (let v = nx.lo; v <= nx.hi + 1e-9; v += nx.st) g += `<text class="axis" x="${x(v)}" y="${H - 8}" text-anchor="middle">${v > 0 ? "+" : ""}${Math.round(v)}%</text>`;
  g += `<line x1="${x(0)}" x2="${x(0)}" y1="${Tp}" y2="${H - B}" stroke="var(--muted)"/><line x1="${L}" x2="${W - Rr}" y1="${y(avgM)}" y2="${y(avgM)}" stroke="var(--muted)" stroke-dasharray="4 3"/>`;
  g += `<text class="lbl" x="${W - Rr - 4}" y="${Tp + 12}" text-anchor="end">${esc(t("stars"))}</text><text class="lbl" x="${L + 6}" y="${Tp + 12}">${esc(t("cash"))}</text><text class="lbl" x="${W - Rr - 4}" y="${H - B - 6}" text-anchor="end">${esc(t("question"))}</text><text class="lbl" x="${L + 6}" y="${H - B - 6}">${esc(t("problems"))}</text>`;
  const smax = Math.max(...pts.map(p => p.s)) || 1; const top = new Set([...pts].sort((a, b) => b.s - a.s).slice(0, 5).map(p => p.k)); const placed = [];
  pts.forEach(p => {
    const c = p.x >= 0 && p.y >= avgM ? "var(--s2)" : p.x < 0 && p.y < avgM ? "var(--crit)" : "var(--s3)"; const rad = 5 + Math.sqrt(Math.max(0, p.s) / smax) * 13;
    g += `<circle class="mark" cx="${x(p.x)}" cy="${y(p.y)}" r="${rad}" fill="${c}" fill-opacity=".8" stroke="var(--card)" stroke-width="2" data-tip="${esc(`<b>${esc(p.n)}</b><br>${t("growth")}: ${sg(p.x)}<br>${t("margin")}: ${pc(p.y)}<br>${t("netSales")}: ${pkr(p.s)}<br><i>${t("tipClick")}</i>`)}" ${p.drill ? `data-drill="${J(p.drill)}"` : ""}/>`;
    if (top.has(p.k)) {const lx = x(p.x) + rad + 3, ly = y(p.y) + 4; if (!placed.some(q => Math.abs(q[0] - lx) < 70 && Math.abs(q[1] - ly) < 13)) {placed.push([lx, ly]); g += `<text class="lbl" x="${lx}" y="${ly}">${esc(String(p.n).replace(/^\d+ /, "").slice(0, 22))}</text>`}}
  });
  const tbl = `<div class="tbl-wrap"><table><thead><tr><th class="nosort"></th><th class="n nosort">${esc(t("growth"))}</th><th class="n nosort">${esc(t("margin"))}</th><th class="n nosort">${esc(t("netSales"))}</th></tr></thead><tbody>${pts.map(p => `<tr class="click" ${p.drill ? `data-drill="${J(p.drill)}"` : ""}><td>${esc(p.n)}</td><td class="n">${sg(p.x)}</td><td class="n">${pc(p.y)}</td><td class="n">${fmtN(p.s)}</td></tr>`).join("")}</tbody></table></div>`;
  return S.tv[id] ? tbl : `<div class="chart"><svg viewBox="0 0 ${W} ${H}">${g}</svg></div>`;
}
function heat(b) {
  const tg = b.target || 12; const cls = v => v <= tg ? "good" : v <= tg * 1.5 ? "warn" : v <= tg * 2.5 ? "serious" : "crit";
  return `<div class="tbl-wrap" style="max-height:none"><div class="heat" style="grid-template-columns:150px repeat(${b.cols.length},minmax(58px,1fr));min-width:${150 + b.cols.length * 62}px"><div></div>${b.cols.map(c => `<div class="hh">${esc(c.n)}</div>`).join("")}
  ${b.rows.map((r, i) => `<div class="hr" title="${esc(r.n)}">${esc(r.n)}</div>${b.cols.map((c, j) => {const v = b.cells[i][j]; if (v == null) return `<div class="hc" style="background:var(--line-2);color:var(--muted);cursor:default">—</div>`;
    const k = cls(v); const d = b.drill ? {m: b.drill.m, path: [{lvl: "store", k: r.k, n: r.n}, {lvl: "dept", k: c.k, n: c.n}]} : null;
    return `<button class="hc" style="background:var(--${k}-bg);color:var(--${k}-ink)" ${d ? `data-drill="${J(d)}"` : ""} data-tip="${esc(`<b>${esc(r.n)} · ${esc(c.n)}</b><br>${pc(v)} (${t("target")} ≤${tg}%)<br><i>${t("tipClick")}</i>`)}">${pc(v, 0)}</button>`}).join("")}`).join("")}</div></div>`;
}
function spark(v, c = "var(--s1)", w = 110, h = 28) {const vv = v.filter(x => x != null); if (vv.length < 2) return ""; const lo = Math.min(...vv), hi = Math.max(...vv); const pts = v.map((d, i) => `${(i / (v.length - 1) * (w - 4) + 2).toFixed(1)},${(h - 3 - ((d ?? lo) - lo) / (hi - lo || 1) * (h - 6)).toFixed(1)}`); const l = pts[pts.length - 1].split(",");
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none" style="direction:ltr;display:block"><polyline points="${pts.join(" ")}" fill="none" stroke="${c}" stroke-width="1.8" vector-effect="non-scaling-stroke"/></svg>`}
const legend = items => `<div class="legend">${items.map(i => `<span ${i.tip ? `data-tip="${esc(i.tip)}"` : ""}><i class="${i.dash ? "dash" : ""}" style="${i.dash ? `border-top-color:${i.c}` : `background:${i.c}`}"></i>${esc(i.n)}</span>`).join("")}</div>`;
const seriesTip = (s, fmt) => {const v = (s.v || []).filter(x => x != null && isFinite(x)); if (!v.length) return ""; const sum = v.reduce((a, b) => a + b, 0);
  return `<b>${esc(s.n)}</b><br>${fmt === "pct" ? "" : `Total: <b>${fmtV(sum, fmt)}</b><br>`}Average: <b>${fmtV(sum / v.length, fmt)}</b><br>Lowest ${fmtV(Math.min(...v), fmt)} · Highest ${fmtV(Math.max(...v), fmt)}`};
const emptyBox = (b, p, btn) => `<div class="emptybox"><b>${esc(b)}</b>${p ? `<span>${esc(p)}</span>` : ""}${btn || ""}</div>`;

/* ---------------- tables ---------------- */
const TB = {};
function cellHTML(c, r) {
  const v = r[c.k];
  if (v && typeof v === "object" && "d" in v) return c.kind === "mdnum" ? bd(esc(v.d)) : typeof mdInline === "function" ? mdInline(v.d) : esc(v.d);
  switch (c.kind) {
    case "name": return `<b>${esc(v ?? "—")}</b>${r.sub ? `<div class="muted" style="font-size:12px">${esc(r.sub)}</div>` : ""}`;
    case "pct_chip": return v == null ? "—" : chip(r._c || "neutral", bd(pc(v)));
    case "pct_neg": return `<span class="${v < 0 ? "down" : ""}">${bd(pc(v))}</span>`;
    case "sg": return v == null ? "—" : `<span class="${v >= 0 ? "up" : "down"}">${bd(sg(v))}</span>`;
    case "bool": return v == null ? "—" : v ? chip("good", esc(t("yes"))) : chip("crit", esc(t("no")));
    case "level": return v ? chip(stc(v), esc(v)) : "";
    case "text": return esc(v ?? "");
    default: return bd(esc(fmtV(v, c.kind)));
  }
}
const numKind = k => ["int", "num", "pct", "pct_chip", "pct_neg", "pkr", "money", "sg", "x"].includes(k);
function rowAttr(tb, r, i) {
  const a = tb.action; if (!a) return "";
  if (a.kind === "item" && r.item) return `class="click" data-item="${esc(r.item)}"`;
  if (a.kind === "supplier" && (r.supplier || r.key)) return `class="click" data-sup="${esc(r.supplier || r.key)}"`;
  if (a.kind === "focus_store" && r.store) return `class="click" data-focus="${esc(r.store)}" data-tip="${esc(t("tipClick"))}"`;
  if (a.kind === "drill") {const k = r[a.lvl] ?? r.key ?? r.k; return `class="click" data-drill="${J({m: a.m, path: [{lvl: a.lvl, k, n: r.name ?? k}]})}"`}
  if (a.kind === "dsub") return `class="click" data-dsub="${tb.rows.indexOf(r)}"`;
  if (a.kind === "import") return `data-imp="${esc(r.key)}"`;
  return "";
}
/* column maths: sums for money / counts, averages for rates; used by totals rows and header hovers */
const cellV = x => x && typeof x === "object" ? x.v : x;
const isRate = c => ["pct", "pct_chip", "pct_neg", "sg", "x"].includes(c.kind) || (c.kind === "mdnum" && c.unit === "%");
const summable = c => (["money", "int", "pkr", "num"].includes(c.kind) || (c.kind === "mdnum" && c.unit !== "%"))
  && !/avg|average|per[_ ]day|\/day|days|age\b|age_|dly|price|\bcost\b|rate|cover|pct|share|rank|\bcode\b|%/i.test(c.k + " " + (c.l || "")) && !/^(year|week|month)$/i.test(c.k);
function colStats(c, rs) {
  const vals = rs.map(r => cellV(r[c.k])).filter(v => typeof v === "number" && isFinite(v));
  if (!vals.length) return null;
  const sum = vals.reduce((a, b) => a + b, 0);
  return {n: vals.length, sum, avg: sum / vals.length, min: Math.min(...vals), max: Math.max(...vals)};
}
function fmtCol(c, v) {
  if (c.kind === "mdnum") return c.unit === "%" ? pc(v) : c.unit === "PKR" ? pkr(v) : (Math.abs(v) >= 100 ? fmtN(v) : (+v).toLocaleString("en-US", {maximumFractionDigits: 2}));
  return fmtV(v, c.kind === "pct_chip" || c.kind === "pct_neg" ? "pct" : c.kind);
}
function tableC(tb, title) {
  const id = tb.id; TB[id] = {tb, title}; const st = S.tbl[id] || (S.tbl[id] = {sort: null, dir: -1, q: "", p: 0}); let rs = tb.rows;
  const cols = tb.cols; const pageSize = tb.page_size || 40;
  if (st.q) {const q = st.q.toLowerCase(); rs = rs.filter(r => cols.some(c => String((r[c.k] && r[c.k].d) || fmtV(r[c.k], c.kind) + " " + (r.sub || "")).toLowerCase().includes(q)))}
  if (st.sort != null && cols[st.sort]) {const c = cols[st.sort]; rs = [...rs].sort((a, b) => {const x = cellV(a[c.k]), y = cellV(b[c.k]); if (x == null || x === "") return 1; if (y == null || y === "") return -1; return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, {numeric: true})) * st.dir})}
  const pages = Math.max(1, Math.ceil(rs.length / pageSize)); st.p = Math.min(st.p, pages - 1); const view = rs.slice(st.p * pageSize, (st.p + 1) * pageSize);
  const stats = cols.map(c => (numKind(c.kind) || c.kind === "mdnum") ? colStats(c, rs) : null);
  const tipFor = (c, s) => s ? esc(`<b>${esc(c.l)}</b><br>${summable(c) ? `Total: <b>${fmtCol(c, s.sum)}</b><br>` : ""}Average: <b>${fmtCol(c, s.avg)}</b><br>Lowest: ${fmtCol(c, s.min)} · Highest: ${fmtCol(c, s.max)}<br>${fmtN(s.n)} values · click to sort`) : esc(`<b>${esc(c.l)}</b><br>Click to sort`);
  const head = cols.map((c, i) => `<th class="${numKind(c.kind) || c.kind === "mdnum" ? "n" : ""}" data-tsort="${id}|${i}" data-tip="${tipFor(c, stats[i])}">${esc(c.l)}<span class="sarrow">${st.sort === i ? (st.dir < 0 ? "▾" : "▴") : "↕"}</span></th>`).join("") + (tb.action && tb.action.kind === "import" ? "<th class='nosort'></th>" : "");
  const body = view.map((r, ri) => `<tr ${rowAttr(tb, r, ri)}>${cols.map((c, i) => {
    const num = numKind(c.kind) || c.kind === "mdnum"; const v = cellV(r[c.k]); const s = stats[i];
    const share = num && s && summable(c) && typeof v === "number" && s.sum ? ` data-tip="${esc(`<b>${esc(c.l)}</b>: ${fmtCol(c, v)}<br>${pc(v / s.sum * 100)} of the total ${fmtCol(c, s.sum)}`)}"` : "";
    return `<td class="${num ? "n" : ""}${c.kind === "date" || c.kind === "bool" || c.kind === "pct_chip" ? " nw" : ""}${i === 0 && r._c ? " cbar" : ""}" ${i === 0 && r._c ? `style="--c:var(--${stc(r._c)})"` : ""}${share}>${cellHTML(c, r)}</td>`}).join("")}${tb.action && tb.action.kind === "import" ? `<td><button class="linkbtn" data-delimp="${esc(r.key)}">${esc(t("del"))}</button></td>` : ""}</tr>`).join("");
  const showTot = tb.total !== false && rs.length > 1 && stats.some(Boolean);
  const tot = showTot ? `<tr class="tot">${cols.map((c, i) => {const s = stats[i]; const cls = numKind(c.kind) || c.kind === "mdnum" ? "n" : "";
    if (i === 0) return `<td class="${cls}">${esc(t("total"))} <span class="muted">(${fmtN(rs.length)})</span></td>`;
    if (!s) return `<td></td>`;
    if (summable(c)) return `<td class="${cls}" data-tip="${esc(`Total of ${esc(c.l)}`)}">${bd(fmtCol(c, s.sum))}</td>`;
    if (isRate(c)) return `<td class="${cls}" data-tip="${esc(`Average of ${esc(c.l)} (simple average of the rows)`)}"><span class="muted" style="font-weight:600">avg</span> ${bd(fmtCol(c, s.avg))}</td>`;
    return `<td></td>`}).join("")}</tr>` : "";
  if (!tb.rows.length) return emptyBox(t("noData"), "");
  return `<div class="tbl-tools"><input data-tsearch="${id}" value="${esc(st.q)}" placeholder="${esc(t("search2"))}" aria-label="${esc(t("search2"))}"><span class="muted" style="font-size:12px">${fmtN(rs.length)} ${esc(t("rows"))}</span><span class="spacer"></span><button class="pill-btn" data-export="${id}">⤓ ${esc(t("export"))}</button></div>
  <div class="tbl-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody>${tot ? `<tfoot>${tot}</tfoot>` : ""}</table></div>
  ${pages > 1 ? `<div class="pager">${esc(t("page"))} ${st.p + 1} ${esc(t("of"))} ${pages} <button data-tpage="${id}|-1" ${st.p === 0 ? "disabled" : ""}>‹</button><button data-tpage="${id}|1" ${st.p >= pages - 1 ? "disabled" : ""}>›</button></div>` : ""}`;
}

/* ---------------- panels, KPIs ---------------- */
const EX = {};
let exN = 0;
function bodyHTML(b, title) {
  if (!b) return "";
  switch (b.type) {
    case "line": b.series.forEach((s, i) => {if (!s.c) s.c = PAL[i % PAL.length]}); return legend(b.series.map(s => ({n: s.n, c: s.c, dash: s.dash, tip: s.dash ? "" : seriesTip(s, b.fmt)}))) + lineChart(b);
    case "bar": return legend(b.series.map(s => ({n: s.n, c: s.c, tip: seriesTip(s, b.fmt)}))) + barChart(b);
    case "waterfall": return waterfall(b);
    case "hbars": return hbars(b);
    case "scatter": return scatter(b);
    case "heat": return heat(b);
    case "table": return tableC(b, title);
    case "empty": return emptyBox(b.text || t("noData"), "");
    case "note": return `<div class="note">${esc(b.text)}</div>`;
    case "html": return b.html;
    case "raw": return "\u0000BODY\u0000";
    default: return `<pre>${esc(JSON.stringify(b).slice(0, 400))}</pre>`;
  }
}
function panelC(p) {
  const b = p.body || {}; const chartId = ["line", "bar", "waterfall", "scatter"].includes(b.type) ? (b.id || p.id) : null;
  const tools = chartId ? `<div class="tools"><button data-tv="${chartId}" data-tvv="0" aria-pressed="${!S.tv[chartId]}">${esc(t("chartView"))}</button><button data-tv="${chartId}" data-tvv="1" aria-pressed="${!!S.tv[chartId]}">${esc(t("tableView"))}</button></div>` : "";
  return `<section class="panel"><div class="phd"><h2>${bx(p.title)} ${p.sub ? `<small>${bx(p.sub)}</small>` : ""}</h2>${tools}</div>${bodyHTML(b, p.title)}</section>`;
}
function kpiC(k) {
  const id = "e" + (exN++); if (k.explain) EX[id] = {...k.explain, __m: k.drill && k.drill.m};
  const tipLines = k.tip && k.tip.length ? `<b>${esc(k.tip[0])}</b><br>` + k.tip.slice(1).map(esc).join("<br>") + (k.drill ? `<br><i>${t("tipClick")}</i>` : "") : (k.drill ? `<i>${t("tipClick")}</i>` : "");
  const status = k.chip ? chip(stc(k.status), esc(k.chip)) : "";
  const v = typeof k.v === "string" ? esc(k.v) : fmtV(k.v, k.fmt);
  const dr = k.drill ? (k.drill.page ? `data-page="${k.drill.page}"` : `data-drill="${J(k.drill)}"`) : "";
  const sc = stc(k.status);
  return `<div class="kpi" role="button" tabindex="0" ${dr} ${tipLines ? `data-tip="${esc(tipLines)}"` : ""} ${sc !== "neutral" ? `style="box-shadow:var(--shadow),inset 0 3px 0 var(--${sc})"` : ""}>
  <div class="kpi-l"><span>${esc(k.l)}</span>${k.explain ? `<button class="info" data-explain="${id}" aria-label="${esc(t("how"))}">i</button>` : ""}</div>
  <div class="kpi-top"><div class="kpi-v num">${bd(v)}</div>${status}</div><div class="kpi-s">${bx(k.sub || "")}</div>
  ${k.spark && k.spark.length > 1 ? spark(k.spark, sc === "crit" ? "var(--crit)" : "var(--s1)", 220, 28) : ""}${k.period ? `<div class="kpi-p">${IC.cal}<span>${bx(k.period)}</span></div>` : ""}</div>`;
}
function insightsC(list) {
  const col = {bad: "var(--crit)", crit: "var(--crit)", warn: "var(--warn)", info: "var(--s2)", good: "var(--good)"};
  return `<div class="insights">${list.map(x => `<button class="ins" ${x.drill ? `data-drill="${J(x.drill)}"` : x.goto ? `data-goto="${esc(x.goto)}"` : ""}><span class="bar" style="background:${col[x.level] || "var(--s1)"}"></span><span><b>${bx(x.title)}</b><p>${bx(x.text || "")}</p><span class="linkbtn">${esc(t("tipClick"))} →</span></span><span class="money num">${x.value != null ? bd(fmtV(x.value, x.fmt || "pkr")) : ""}</span></button>`).join("")}</div>`;
}
function layout(panels) {
  let out = "", pend = [];
  const flush = () => {if (pend.length === 2) out += `<div class="grid g2">${pend.join("")}</div>`; else if (pend.length) out += pend[0]; pend = []};
  for (const p of panels) {
    const wide = p.span === 2 || (p.body && p.body.type === "table" && (p.body.cols || []).length > 4) || p.wide;
    if (wide) {flush(); out += p.html} else {pend.push(p.html); if (pend.length === 2) flush()}
  }
  flush(); return out;
}

/* ---------------- pages ---------------- */
function scopeLine(d) {
  const per = (S.boot && S.boot.periods || []).find(p => p.p === ctx().period);
  return `<span>${IC.pin}${bx(d.scope || t("allPk"))}</span>${per ? `<span>${IC.cal}${esc(S.lang === "ur" ? per.nu || per.p : per.n || per.p)} · ${bd(fdate(per.d))}</span>` : ""}<span>${IC.cmp}${esc(t("c_" + S.f.compare))}</span>`;
}
function head(d, right = "") {return `<div class="ph"><div><h1>${esc(d.title || t(S.page))}</h1>${d.sub ? `<p>${esc(d.sub)}</p>` : ""}<div class="scope">${scopeLine(d)}</div></div><div class="row">${right}</div></div>`}
function pageHTML() {
  if (S.page === "agent") return agentPage();
  const d = S.data;
  if (!d) return `<div class="loading"><span class="spin"></span>${esc(t("loading"))}</div>`;
  if (d.error) return `<div class="errbox">${esc(t("error"))}: ${esc(d.error)}<pre>${esc(d.trace || "")}</pre><button class="primary" data-reload="1">${esc(t("retry"))}</button></div>`;
  if (S.page === "import") return importPage(d);
  if (S.page === "settings") return settingsPage(d);
  let right = "";
  if (d.tabs) right = `<div class="tabs">${d.tabs.map(x => `<button data-stab="${x.k}" aria-pressed="${d.tab === x.k}">${esc(x.n)}</button>`).join("")}</div>`;
  if (S.page === "score") right = `<div class="tabs">${["H", "S", "M"].map(x => `<button data-scoref="${x}" aria-pressed="${S.scoreF === x}">${esc(t("f" + x))}</button>`).join("")}</div>`;
  let h = head(d, right);
  if (d.themes && d.themes.length) h += `<div class="promo-cards">${d.themes.map(x => `<button class="promo-card" data-theme="${esc(x.k)}" aria-pressed="${d.theme === x.k}"><b>${esc(x.n)}</b><small>${esc(x.k)} · ${fdate(x.d0)} – ${fdate(x.d1)} · ${x.items} ${esc(t("itemsL"))}${x.running ? " · ●" : ""}</small></button>`).join("")}</div>`;
  if (d.notes) h += d.notes.map(n => `<div class="banner">⚠ ${esc(n)}</div>`).join("");
  if (d.empty && !(d.kpis || []).length) return h + emptyBox(t("noData"), d.empty, `<button class="primary" data-page="import">${esc(t("goImport"))}</button>`);
  if ((d.kpis || []).length) h += `<div class="kpis">${d.kpis.map(kpiC).join("")}</div>`;
  if (d.empty) h += emptyBox(t("noData"), d.empty, `<button class="primary" data-page="import">${esc(t("goImport"))}</button>`);
  if (d.jobs) h += jobsC(d.jobs);
  const panels = [];
  if (d.insights && d.insights.length) panels.push({html: panelC({title: t("knowTitle"), sub: String(d.insights.length), body: {type: "raw"}}).replace("\u0000BODY\u0000", () => insightsC(d.insights))});
  for (const b of d.blocks || []) for (const p of b.panels || []) panels.push({...p, html: panelC(p)});
  h += layout(panels);
  if (d.score) h += scoreC(d.score);
  if (!(d.kpis || []).length && !panels.length && !d.jobs && !d.score && !d.empty) h += emptyBox(t("noData"), t("importFirst"), `<button class="primary" data-page="import">${esc(t("goImport"))}</button>`);
  return h;
}
function jobsC(jobs) {
  if (!jobs.length) return panelC({title: t("myJobs"), body: {type: "html", html: emptyBox(t("noJobs"), t("noJobsP"))}});
  const done = jobs.filter(j => j.done).length;
  return panelC({title: t("myJobs"), sub: `${done}/${jobs.length} ${t("jobsDone")}`, body: {type: "raw"}}).replace("\u0000BODY\u0000", () =>
    `<div class="row"><div class="progress" style="flex:1"><i style="width:${jobs.length ? done / jobs.length * 100 : 0}%"></i></div><button class="pill-btn" data-exportjobs="1">⤓ ${esc(t("exportJobs"))}</button></div>
    <div class="jobs">${jobs.map(j => {const lv = stc(j.level); return `<div class="job ${j.done ? "done" : ""}"><input type="checkbox" data-job="${esc(j.id)}" ${j.done ? "checked" : ""} aria-label="${esc(j.title)}">
    <div><div class="jt">${bx(j.title)}</div><div class="jm">${chip(lv, lv === "crit" ? (S.lang === "ur" ? "ابھی" : "Now") : lv === "warn" ? (S.lang === "ur" ? "آج" : "Today") : (S.lang === "ur" ? "اس ہفتے" : "This week"))} <span>${bx(j.why)}</span></div></div>
    <div class="money num" style="font-weight:800;text-align:end">${j.value ? bd(pkr(j.value)) : bd(fmtN(j.count))}<div class="muted" style="font-size:11px;font-family:var(--f-ui)">${esc(j.value ? j.value_label || "" : t("itemsL"))}</div></div>
    <button class="pill-btn" data-jobopen="${esc(j.key)}">${esc(t("seeItems"))} ${S.lang === "ur" ? "←" : "→"}</button></div>`}).join("")}</div>`);
}
function scoreC(s) {
  const k = s.stores.map((st, i) => kpiC({l: st.n, v: `${fmtN(s.greens[i])} / ${fmtN(s.measured[i])}`, sub: s.diff[st.k] ? `${t("bcTeam")} ${s.diff[st.k][0]} · ${t("ours")} ${s.diff[st.k][1]}` : "", status: s.greens[i] / Math.max(1, s.measured[i]) >= .6 ? "good" : s.greens[i] / Math.max(1, s.measured[i]) >= .4 ? "warn" : "crit", drill: {m: "zero_stock", path: [{lvl: "store", k: st.k, n: st.n}]}}));
  const cls = c => ({good: "good", bad: "crit", warn: "warn", crit: "crit"}[c.status] || "neutral");
  return `<div class="kpis">${k.join("")}</div>` + `<section class="panel"><div class="phd"><h2>${esc(t("f" + s.fmt))} <small>✓ = ${esc(t("target"))} · ◆ ${esc(t("computed"))} · ${esc(s.file || "")} · ${fdate(s.as_of)}</small></h2></div>
  <div class="tbl-wrap" style="max-height:none"><table class="score"><thead><tr><th></th>${s.rows.map(r => `<th>${r.computed ? "◆ " : ""}${esc(r.label)}</th>`).join("")}</tr></thead><tbody>
  <tr class="target"><td class="name">${esc(t("target"))}</td>${s.rows.map(r => `<td>${r.target == null ? "—" : bd((r.lo ? "≤" : "≥") + r.target + "%")}</td>`).join("")}</tr>
  ${s.stores.map((st, i) => `<tr><td class="name">${esc(st.n)}</td>${s.rows.map((r, j) => {const c = r.cells[i]; const k2 = cls(c); return `<td style="background:var(--${k2}-bg);color:var(--${k2}-ink)" data-cell="${i}|${j}" data-tip="${esc(`<b>${esc(st.n)} · ${esc(r.label)}</b><br>${c.raw || fmtV(c.v, "num")} · ${t("target")} ${r.lo ? "≤" : "≥"}${r.target ?? "—"}%${c.ours != null ? `<br>${t("ours")}: ${pc(c.ours)}` : ""}<br><i>${t("tipClick")}</i>`)}">${bd((icon[k2] || "") + " " + (c.v == null ? "—" : (+c.v).toFixed(1)))}</td>`}).join("")}</tr>`).join("")}
  </tbody></table></div></section>`;
}

/* ---------------- import & settings (full pages in the real app) ---------------- */
function importPage(d) {
  const im = S.imp || {plans: [], results: []}; const types = S.boot ? S.boot.report_types : []; const stores = S.boot ? S.boot.stores : [];
  const review = im.plans.length ? `<section class="panel"><div class="phd"><h2>${esc(t("reviewT"))} <small>${esc(t("reviewP"))}</small></h2><div class="row"><button class="pill-btn" data-impclear="1">${esc(t("clear"))}</button><button class="primary" data-imprun="1" ${im.busy ? "disabled" : ""}>${esc(t("importNow"))}</button></div></div>
  <div class="tbl-wrap imp-grid" style="max-height:none"><table><thead><tr><th class="nosort">${esc(t("file"))} / ${esc(t("sheet"))}</th><th class="nosort">${esc(t("type"))}</th><th class="n nosort">${esc(t("conf"))}</th><th class="nosort">${esc(t("storeC"))}</th><th class="nosort">${esc(t("dateC"))}</th><th class="n nosort">${esc(t("rows"))}</th><th class="nosort">${esc(t("note"))}</th></tr></thead><tbody>
  ${im.plans.map(p => p.sheets.map((s, i) => {const opts = [...s.options.map(o => [o.k, `${o.n} (${o.c}%)`]), ...types.filter(x => !s.options.some(o => o.k === x.key)).map(x => [x.key, x.name]), ["generic", t("generic")], ["skip", t("skip")]];
    const sk = s.chosen === "skip"; const c = sk ? "neutral" : s.conf >= 80 ? "good" : s.conf >= 50 ? "warn" : "crit";
    return `${i === 0 ? `<tr class="imp-file"><td colspan="7"><div class="row"><b>${esc(p.file)}</b><button class="linkbtn" data-impremove="${p.pid}" title="Remove">×</button>
      <input class="imp-hint" data-imphint="${p.pid}" value="${esc((S.hintDraft || {})[p.pid] ?? p.hint ?? "")}" placeholder="What is this file? One line, e.g. 'DP report September, all stores' (optional; helps the importer)">
      <button class="pill-btn" data-imphintgo="${p.pid}">Apply</button>${im.ai_ready ? `<button class="pill-btn" data-impai="${p.pid}" title="Ask the AI to read this file">✦ AI check</button>` : ""}</div></td></tr>` : ""}<tr style="${sk ? "opacity:.55" : ""}"><td><span class="muted">${esc(s.sheet)}${s.hidden ? " (hidden)" : ""}${s.kind === "pivot" ? " (pivot)" : ""}</span></td>
    <td><select data-impset="${p.pid}|${s.si}|chosen">${opts.map(o => `<option value="${esc(o[0])}" ${o[0] === s.chosen ? "selected" : ""}>${esc(o[1])}</option>`).join("")}</select></td>
    <td class="n">${sk ? "" : chip(c, bd(s.conf + "%"))}</td>
    <td>${s.needs_store ? `<select data-impset="${p.pid}|${s.si}|store" style="${!s.store && !sk ? "border-color:var(--crit)" : ""}"><option value="">${esc(t("chooseStore"))}</option>${stores.map(x => `<option value="${x.code}" ${x.code === s.store ? "selected" : ""}>${esc(x.code + " " + x.name)}</option>`).join("")}</select>` : `<span class="muted">${esc(t("storeC"))}: auto</span>`}</td>
    <td><input type="date" data-impset="${p.pid}|${s.si}|day" value="${esc(s.date || "")}"></td><td class="n">${fmtN(s.rows)}</td>
    <td class="muted" style="font-size:12px">${s.already ? chip("warn", esc(t("already"))) + " " : ""}${esc(s.reason)}${s.ai ? `<div class="imp-ai">✦ <b>AI:</b> ${esc(s.ai.what_it_is || "")}${s.ai.confidence != null ? ` <span class="muted">(${Math.round(s.ai.confidence * 100)}% sure${s.ai.columns ? ` · ${s.ai.columns} columns explained` : ""})</span>` : ""}${s.ai.notes ? `<br>${esc(s.ai.notes)}` : ""}</div>` : ""}</td></tr>`}).join("")).join("")}</tbody></table></div></section>` : "";
  const aiBar = im.ai && im.ai.running ? `<div class="note"><span class="spin sm"></span> ${esc(im.ai.msg || "AI is reading the files…")}</div>` : im.ai && im.ai.error ? `<div class="errbox">AI: ${esc(im.ai.error)}</div>` : "";
  const aiHint = im.plans.length && !im.ai_ready ? `<div class="note">Tip: connect an AI model in the Agent tab and the importer will read files it is unsure about and explain every column.</div>` : "";
  const prog = im.busy ? `<section class="panel"><div class="row"><span class="spin"></span><b>${esc(im.msg || t("loading"))}</b></div><div class="pbar"><i style="width:${Math.round((im.progress || 0) * 100)}%"></i></div></section>` : "";
  const res = im.results && im.results.length ? `<section class="panel"><div class="phd"><h2>${esc(t("results"))}</h2></div>${im.results.map(r => `<div class="file" style="cursor:default"><span class="ic" style="background:var(--${r.ok ? "good" : "crit"}-bg);color:var(--${r.ok ? "good" : "crit"}-ink)">${r.ok ? "✓" : "!"}</span><div><b>${esc(r.file)} · ${esc(r.sheet)}</b><div class="muted" style="font-size:12px">${esc(r.type)} · ${esc(r.summary)}</div>${(r.notes || []).map(n => `<div style="font-size:12px;color:var(--warn-ink)">• ${esc(n)}</div>`).join("")}</div><span>${r.rows ? bd(fmtN(r.rows)) : ""}</span></div>`).join("")}</section>` : "";
  const err = im.error ? `<div class="errbox">${esc(im.error)}</div>` : "";
  const miss = im.missing ? `<div class="errbox">${esc(t("chooseStore"))}: ${esc(im.missing.join(", "))}</div>` : "";
  return head(d) + `<div class="drop" id="drop">⬆ ${esc(t("drop"))} <button class="primary" data-imppick="0">${esc(t("pick"))}</button> <button class="pill-btn" data-imppick="1">${esc(t("pickFolder"))}</button> <button class="pill-btn" data-imppaste="1">${esc(t("paste"))}</button></div>`
    + err + miss + prog + aiBar + aiHint + review + res + (d.history ? panelC({title: t("history"), body: d.history}) : "");
}
function settingsPage(d) {
  const lang = `<div class="set-grid"><div class="lang"><button data-lang="en" aria-pressed="${S.lang === "en"}">English</button><button class="ur" data-lang="ur" aria-pressed="${S.lang === "ur"}">اردو</button></div><div class="tabs"><button data-naskh="0" aria-pressed="${!S.naskh}">${esc(t("nastaliq"))}</button><button data-naskh="1" aria-pressed="${S.naskh}">${esc(t("naskh"))}</button></div></div>`;
  const th = `<div class="tbl-wrap set-tbl"><table><tbody>${(d.thresholds || []).map(x => `<tr><td>${esc(x.l)}</td><td class="n"><input type="number" step="any" data-thr="${esc(x.k)}" value="${esc(x.v)}"></td></tr>`).join("")}</tbody></table></div><div class="row"><span class="spacer"></span><button class="primary" data-savethr="1">${esc(t("save"))}</button></div>`;
  const tg = `<div class="tbl-wrap set-tbl"><table><thead><tr><th class="nosort"></th><th class="n nosort">${esc(t("fH"))}</th><th class="n nosort">${esc(t("fS"))}</th><th class="n nosort">${esc(t("fM"))}</th></tr></thead><tbody>${(d.targets || []).map(x => `<tr><td>${esc(x.l)} <span class="muted">${x.lo ? "≤" : "≥"}</span></td>${["H", "S", "M"].map(f => `<td class="n"><input type="number" step="any" data-tgt="${esc(x.k)}|${f}" value="${x[f] ?? ""}"></td>`).join("")}</tr>`).join("")}</tbody></table></div><div class="row"><span class="spacer"></span><button class="primary" data-savetgt="1">${esc(t("save"))}</button></div>`;
  const st = tableC({type: "table", id: "set_stores", cols: [{k: "code", l: "GIMA", kind: "text"}, {k: "name", l: t("storeC"), kind: "name"}, {k: "format", l: "", kind: "text"}, {k: "city", l: "", kind: "text"}, {k: "corp", l: "Corp", kind: "text"}, {k: "aliases", l: "", kind: "text"}], rows: d.stores || [], page_size: 40}, t("storesT"));
  const unk = (d.unknown_names || []).length ? `<div class="tbl-wrap"><table><tbody>${d.unknown_names.map(n => `<tr><td><b>${esc(n)}</b></td><td><select data-alias="${esc(n)}"><option value="">${esc(t("addAlias"))}…</option>${(d.stores || []).map(s => `<option value="${s.code}">${esc(s.code + " " + s.name)}</option>`).join("")}</select></td></tr>`).join("")}</tbody></table></div>` : emptyBox("✓", "");
  const dp = tableC({type: "table", id: "set_dp", cols: [{k: "rule_key", l: "Rule", kind: "text"}, {k: "from_day", l: "From day", kind: "int"}, {k: "pct", l: "%", kind: "pct"}, {k: "source", l: t("source"), kind: "text"}], rows: d.dp_rules || [], page_size: 30}, t("dpRules"));
  return head(d) + `${panelC({title: t("unknown"), body: {type: "raw"}}).replace("\u0000BODY\u0000", () => unk)}
  <div class="grid g2 top-align">${panelC({title: t("thresholds"), body: {type: "raw"}}).replace("\u0000BODY\u0000", () => th)}${panelC({title: t("targets"), sub: "BC", body: {type: "raw"}}).replace("\u0000BODY\u0000", () => tg)}</div>
  ${panelC({title: t("storesT"), body: {type: "raw"}}).replace("\u0000BODY\u0000", () => st)}${panelC({title: t("dpRules"), body: {type: "raw"}}).replace("\u0000BODY\u0000", () => dp)}
  <p class="muted" style="font-size:12px">${esc(t("version"))} ${esc(S.boot ? S.boot.version : "")} · ${esc(t("dataFresh"))}</p>`;
}

/* ---------------- drawers: drill, item, supplier, score cell, job ---------------- */
async function openDrill(x) {
  if (!x) return; if (x.page) {go(x.page); return}
  S.drawer = {kind: "drill", m: x.m, path: x.path || [], by: x.by || null, data: null}; render(); fetchDrill();
}
async function fetchDrill() {
  const D = S.drawer; if (!D || D.kind !== "drill") return; D.data = null; render();
  const r = await api("drill", {metric: D.m, path: D.path, by: D.by}); if (S.drawer !== D) return; D.data = r; D.by = r.by || D.by; render();
}
function drawerShell(narrow, sub, title, extra, body) {
  return `<div class="scrim" data-close="1"></div><aside class="drawer ${narrow ? "narrow" : ""}" role="dialog"><header><div><div class="muted" style="font-size:12px;font-weight:700">${esc(sub)}</div><h3>${title}</h3>${extra}</div><button class="x" data-close="1" aria-label="${esc(t("close"))}">×</button></header><div class="body">${body}</div></aside>`;
}
const loadingBox = () => `<div class="loading"><span class="spin"></span>${esc(t("loading"))}</div>`;
function drillHTML() {
  const D = S.drawer, d = D.data;
  if (!d) return drawerShell(false, t("drill_t"), "…", "", loadingBox());
  if (d.error) return drawerShell(false, t("drill_t"), esc(D.m), "", `<div class="errbox">${esc(d.error)}<pre>${esc(d.trace || "")}</pre></div>`);
  const root = (S.data && S.data.scope) || t("allPk"); const crumbs = [`<button data-crumb="-1">${esc(root)}</button>`].concat(D.path.map((p, i) => `<button data-crumb="${i}">${esc(p.n || p.k)}</button>`)).join(" › ");
  const bySel = `<select id="drillBy">${(d.levels || []).map(l => `<option value="${l.k}" ${d.by === l.k ? "selected" : ""}>${esc(l.n)}</option>`).join("")}</select>`;
  const cols = [...d.cols]; const rows = d.rows.map(r => ({...r}));
  if (d.share_of) {const tot = rows.reduce((a, r) => a + (+r[d.share_of] || 0), 0); rows.forEach(r => r._share = tot ? (+r[d.share_of] || 0) / tot * 100 : null); cols.push({k: "_share", l: t("share"), kind: "pct"})}
  rows.forEach(r => {r.item = d.by === "item" ? r.k : undefined});
  const tb = {type: "table", id: "drill-" + D.m + "-" + d.by + "-" + D.path.length, cols, rows, total: !["pct"].includes(d.fmt), page_size: 50, action: d.by === "item" ? {kind: "item"} : {kind: "dsub"}};
  const tbl = tableC(tb, d.title);
  const body = `<div class="crumbs">${crumbs}</div><div class="row"><span class="fbox"><label for="drillBy">${esc(t("groupBy"))}</label>${bySel}</span><span class="muted" style="font-size:12.5px">${esc(t("tipClick"))}${d.next ? " → " + esc(((d.levels || []).find(l => l.k === d.next) || {}).n || d.next) : d.by === "item" ? " → " + esc(t("item360")) : ""}</span>${d.by === "supplier" ? "" : ""}</div>
   ${tbl}
   <p class="muted" style="margin:0;font-size:12px">${esc(t("source"))}: ${esc(d.source || "")}</p>`;
  const exId = Object.keys(EX).find(k => EX[k] && EX[k].__m === D.m);
  return drawerShell(false, t("drill_t"), `${esc(d.title)} ${exId ? `<button class="linkbtn" data-explain="${exId}">ⓘ ${esc(t("how"))}</button>` : ""}`, `<div class="hv num">${bd(fmtV(d.total, d.fmt))}</div><div class="scope">📍 ${esc(root)}${D.path.length ? " › " + D.path.map(p => esc(p.n || p.k)).join(" › ") : ""}</div>`, body);
}
function itemHTML() {
  const D = S.drawer, d = D.data;
  if (!d) return drawerShell(true, t("item360"), esc(D.id), "", loadingBox());
  if (d.error) return drawerShell(true, t("item360"), esc(D.id), "", `<div class="errbox">${esc(d.error)}</div>`);
  const it = d.item || {};
  const statuses = [...new Set(d.stock.map(r => r.status).filter(Boolean))].join(" / ") || "—";
  const zeroBy = Object.fromEntries(d.zero.map(z => [z.store, z]));
  const bars = d.stock.map(r => {const z = zeroBy[r.store]; const q = r.qty || 0; return {l: r.store_name, v: Math.max(0, q), c: q <= 0 ? "var(--crit)" : "var(--s1)", x: `${fmtN(q)} ${t("units")} · ${r.status || ""}${z ? ` · ${z.days_out ?? "?"}d · ${z.reason || ""}${z.open_lpo ? " · LPO " + z.open_lpo : ""}` : ""}`}}).sort((a, b) => b.v - a.v);
  const T2 = (id, cols, rows) => rows.length ? tableC({type: "table", id, cols, rows, page_size: 15}) : "";
  const body = `<div class="dl"><div><span>${esc(t("price"))}</span><b>${bd(fmtV(d.price, "num"))}</b></div><div><span>${esc(t("cost"))}</span><b>${bd(fmtV(d.cost, "num"))}</b></div><div><span>${esc(t("margin"))}</span><b class="${d.margin < 0 ? "down" : ""}">${bd(pc(d.margin))}</b></div><div><span>${esc(t("status"))}</span><b>${esc(statuses)}</b></div><div><span>${esc(t("units"))}</span><b>${bd(fmtN(d.stock_total))}</b></div>${it.season ? `<div><span>Season</span><b>${esc(it.season)}</b></div>` : ""}</div>
  <div class="ins" style="cursor:default"><span class="bar" style="background:${d.rec.length && !/No urgent|کوئی فوری/.test(d.rec[0]) ? "var(--crit)" : "var(--good)"}"></span><span><b>${esc(t("recommend"))}</b>${d.rec.map(r => `<p>${esc(r)}</p>`).join("")}</span><span></span></div>
  ${d.stock.length ? panelC({title: t("stockByStore"), body: {type: "raw"}}).replace("\u0000BODY\u0000", () => hbars({items: bars, fmt: "int"})) : ""}
  ${d.zero.length ? panelC({title: t("emptyNow"), body: {type: "raw"}}).replace("\u0000BODY\u0000", () => T2("i_zero", [{k: "store_name", l: t("storeC"), kind: "text"}, {k: "days_out", l: S.lang === "ur" ? "دن" : "Days out", kind: "int"}, {k: "dlyavg", l: S.lang === "ur" ? "روزانہ" : "Sells/day", kind: "num"}, {k: "reason", l: S.lang === "ur" ? "وجہ" : "Reason", kind: "text"}, {k: "open_lpo", l: "LPO", kind: "text"}, {k: "delivery_date", l: S.lang === "ur" ? "واجب" : "Due", kind: "date"}], d.zero)) : ""}
  ${d.sales.length ? panelC({title: t("sales"), body: {type: "raw"}}).replace("\u0000BODY\u0000", () => T2("i_sales", [{k: "store_name", l: t("storeC"), kind: "text"}, {k: "date_to", l: t("dateC"), kind: "date"}, {k: "sales", l: t("netSales"), kind: "money"}, {k: "qty", l: t("units"), kind: "int"}, {k: "margin", l: t("margin"), kind: "pct_neg"}], d.sales)) : ""}
  ${d.dp.length ? panelC({title: S.lang === "ur" ? "ایجڈ (DP) اسٹاک" : "Aged (DP) stock", body: {type: "raw"}}).replace("\u0000BODY\u0000", () => T2("i_dp", [{k: "store_name", l: t("storeC"), kind: "text"}, {k: "qty", l: t("units"), kind: "int"}, {k: "age_days", l: S.lang === "ur" ? "عمر" : "Age (days)", kind: "int"}, {k: "value", l: "PKR", kind: "money"}, {k: "provision", l: "Provision", kind: "money"}, {k: "bucket", l: "", kind: "text"}], d.dp)) : ""}
  ${d.negative.length ? panelC({title: S.lang === "ur" ? "منفی اسٹاک" : "Negative stock", body: {type: "raw"}}).replace("\u0000BODY\u0000", () => T2("i_neg", [{k: "store_name", l: t("storeC"), kind: "text"}, {k: "qty", l: t("units"), kind: "int"}, {k: "status", l: t("status"), kind: "text"}, {k: "snap_date", l: t("dateC"), kind: "date"}], d.negative)) : ""}
  ${d.leaflet.length ? panelC({title: S.lang === "ur" ? "لیفلیٹ" : "Leaflet", body: {type: "raw"}}).replace("\u0000BODY\u0000", () => T2("i_leaf", [{k: "store_name", l: t("storeC"), kind: "text"}, {k: "theme_name", l: t("theme"), kind: "text"}, {k: "stock_qty", l: t("units"), kind: "int"}, {k: "on_order_qty", l: S.lang === "ur" ? "آرڈر پر" : "On order", kind: "int"}, {k: "sp", l: t("price"), kind: "num"}], d.leaflet)) : ""}`;
  return drawerShell(true, t("item360"), esc(it.description || it.item), `<div class="muted">${esc(it.item)} · ${esc(d.section || "")}${it.supplier ? ` · <button class="linkbtn" data-sup="${esc(it.supplier)}">${esc(d.supplier_name || it.supplier)}</button>` : ""}</div>`, body);
}
function supHTML() {
  const D = S.drawer, d = D.data;
  if (!d) return drawerShell(true, t("sup360"), esc(D.id), "", loadingBox());
  if (d.error) return drawerShell(true, t("sup360"), esc(D.id), "", `<div class="errbox">${esc(d.error)}</div>`);
  return drawerShell(true, t("sup360"), esc(d.name), `<div class="muted">${esc(d.code)} · ${esc(d.scope || "")}</div>`, `<div class="kpis">${d.kpis.map(kpiC).join("")}</div>${(d.blocks || []).map(panelC).join("")}`);
}
function cellDrawer() {
  const s = S.data && S.data.score; const [i, j] = S.drawer.id; if (!s) return "";
  const st = s.stores[i], r = s.rows[j], c = r.cells[i]; const k = ({good: "good", bad: "crit", warn: "warn", crit: "crit"}[c.status] || "neutral");
  const peers = s.stores.map((x, n) => ({l: x.n, v: r.cells[n].v || 0, c: n === i ? "var(--brand)" : "var(--line)"}));
  const map = {zero_stock: "zero_stock", negative_fmcg: "negative", leaflet_zero: "leaflet", no_sales_30: "sleeping", no_sales_60: "sleeping", sleeping_cg: "sleeping", sleeping_nf: "sleeping"};
  const m = map[r.k] || (/zero/.test(r.k) ? "zero_stock" : /neg/.test(r.k) ? "negative" : /leaf/.test(r.k) ? "leaflet" : /sales_?\d|sleep/.test(r.k) ? "sleeping" : null);
  const body = `<div class="dl"><div><span>${esc(t("bcTeam"))}</span><b>${bd(esc(c.raw || fmtV(c.v, "num")))}</b></div>${c.ours != null ? `<div><span>${esc(t("ours"))}</span><b>${bd(pc(c.ours))}</b></div>` : ""}<div><span>${esc(t("target"))}</span><b>${bd((r.lo ? "≤" : "≥") + (r.target ?? "—") + "%")}</b></div></div>
  ${m ? `<button class="primary" data-drill="${J({m, path: [{lvl: "store", k: st.k, n: st.n}]})}">${esc(t("seeItems"))} →</button>` : ""}
  ${panelC({title: t("peers"), body: {type: "raw"}}).replace("\u0000BODY\u0000", () => hbars({items: peers, fmt: "num"}))}`;
  return drawerShell(true, t("cell"), `${esc(st.n)} · ${esc(r.label)}`, `<div class="row">${chip(k, bd(esc(c.raw || fmtV(c.v, "num"))))} <span class="muted">${r.computed ? esc(t("computed")) : esc(t("bcTeam"))}</span></div>`, body);
}
function jobDrawer() {
  const j = (S.data && S.data.jobs || []).find(x => x.key === S.drawer.key); if (!j) return "";
  return drawerShell(false, t("myJobs"), esc(j.title), `<div class="muted">${esc(j.why)}</div>`, tableC(j.table, j.title));
}
function explainHTML(e) {
  return `<div class="scrim" data-mclose="1" style="z-index:55"></div><div class="modal" role="dialog"><div class="box"><div class="row" style="justify-content:space-between"><h3>ⓘ ${esc(e.title)}</h3><button class="x" data-mclose="1">×</button></div>
  <div><b>${esc(t("definition"))}</b><p style="margin:4px 0 0">${esc(e.definition)}</p></div><div><b>${esc(t("formula"))}</b><div class="formula">${esc(e.formula)}</div></div>
  <div><b>${esc(t("source"))}</b><p style="margin:4px 0 0">${esc(e.source)}${e.as_of ? " · " + esc(e.as_of) : ""}</p></div>${e.note ? `<p class="muted" style="margin:0">${esc(e.note)}</p>` : ""}</div></div>`;
}
function pasteModal() {
  return `<div class="scrim" data-mclose="1" style="z-index:55"></div><div class="modal" role="dialog"><div class="box" style="max-width:820px"><div class="row" style="justify-content:space-between"><h3>${esc(t("paste"))}</h3><button class="x" data-mclose="1">×</button></div>
  <p class="muted" style="margin:0">${esc(t("pasteHere"))}</p><textarea id="pastebox" style="width:100%;height:320px;border:1px solid var(--line);border-radius:10px;padding:8px;font-family:monospace;font-size:12px;background:var(--card)"></textarea>
  <div class="row"><span class="spacer"></span><button class="primary" data-pastego="1">${esc(t("importNow"))}</button></div></div></div>`;
}
async function openItem(id) {S.drawer = {kind: "item", id, data: null}; S.q = ""; S.sugg = []; render(); const r = await api("item", {item: String(id)}); if (S.drawer && S.drawer.id === id) {S.drawer.data = r; render()}}
async function openSup(id) {S.drawer = {kind: "sup", id, data: null}; S.q = ""; S.sugg = []; render(); const r = await api("supplier", {code: String(id)}); if (S.drawer && S.drawer.id === id) {S.drawer.data = r; render()}}

/* ---------------- shell ---------------- */
function filterBar() {
  const b = S.boot || {stores: [], regions: [], depts: [], sections: []}; const f = S.f; const fixed = storeRole();
  const stores = b.stores; const sName = s => `${s.name} (${s.code})`;
  const whereOpts = `<option value="all">${esc(t("allPk"))}</option>${b.regions.length ? `<optgroup label="${esc(t("regions"))}">${b.regions.map(r => `<option value="reg:${esc(r)}" ${f.where === "reg:" + r ? "selected" : ""}>${esc(r)}</option>`).join("")}</optgroup>` : ""}<optgroup label="${esc(t("formats"))}">${["H", "S", "M"].map(x => `<option value="fmt:${x}" ${f.where === "fmt:" + x ? "selected" : ""}>${esc(t("f" + x))}</option>`).join("")}</optgroup><optgroup label="${esc(t("storesL"))}">${stores.map(s => `<option value="${s.code}" ${f.where === s.code ? "selected" : ""}>${esc(sName(s))}</option>`).join("")}</optgroup>`;
  const dname = d => S.lang === "ur" && d.name_ur ? d.name_ur : d.name;
  const deptSel = S.role === "dh" ? S.roleDept : f.dept;
  const secs = b.sections.filter(s => !deptSel ? true : deptSel === "NF" ? ["03", "04", "05"].includes(s.dept) : s.dept === deptSel);
  const storeOpt = v => stores.map(s => `<option value="${s.code}" ${v === s.code ? "selected" : ""}>${esc(sName(s))}</option>`).join("");
  const roleSel = `<span class="role">${esc(t("viewAs"))} <select id="role">${["ho", "dm", "sm", "dh", "sec"].map(r => `<option value="${r}" ${S.role === r ? "selected" : ""}>${esc(t("r_" + r))}</option>`).join("")}</select>
   ${fixed ? `<select id="roleStore">${storeOpt(S.roleStore)}</select>` : ""}
   ${S.role === "dh" ? `<select id="roleDept">${b.depts.filter(d => ["01", "02"].includes(d.code)).map(d => `<option value="${d.code}" ${S.roleDept === d.code ? "selected" : ""}>${esc(dname(d))}</option>`).join("")}<option value="NF" ${S.roleDept === "NF" ? "selected" : ""}>${esc(t("nf"))}</option></select>` : ""}
   ${S.role === "sec" ? `<select id="roleSec">${b.sections.map(s => `<option value="${s.code}" ${S.roleSec === s.code ? "selected" : ""}>S${s.code} ${esc(s.name)}</option>`).join("")}</select>` : ""}</span>`;
  const per = b.periods && b.periods.length ? `<div class="fbox" title="${esc(t("when"))}"><label for="fper">${esc(t("when"))}</label><select id="fper" class="w-per">${b.periods.map(p => `<option value="${p.p}" ${ctx().period === p.p || (!f.period && p.p === "MTD") ? "selected" : ""}>${esc(S.lang === "ur" ? p.nu || p.p : p.n || p.p)} · ${fdate(p.d)}</option>`).join("")}</select></div>` : "";
  const chips = [];
  const changed = (!fixed && f.where !== "all") || (S.role !== "dh" && S.role !== "sec" && f.dept) || (S.role !== "sec" && f.section) || (f.period && f.period !== "MTD") || f.compare !== "budget";
  if (!fixed && f.where !== "all") chips.push(["where", ($("#where option:checked") || {}).textContent || f.where]);
  if (S.role !== "dh" && S.role !== "sec" && f.dept) chips.push(["dept", f.dept === "NF" ? t("nf") : dname(b.depts.find(d => d.code === f.dept) || {name: f.dept})]);
  if (S.role !== "sec" && f.section) chips.push(["section", "S" + f.section]);
  return {roleSel, html: `<div class="filters">
   ${fixed ? "" : `<div class="fbox" title="${esc(t("where"))}"><label for="where">${esc(t("where"))}</label><select id="where" class="w-where">${whereOpts}</select></div>`}
   ${S.role === "sec" || S.role === "dh" ? "" : `<div class="fbox" title="${esc(t("dept"))}"><label for="fdept">${esc(t("deptS"))}</label><select id="fdept" class="w-dept"><option value="">${esc(t("allDept"))}</option>${b.depts.map(d => `<option value="${d.code}" ${f.dept === d.code ? "selected" : ""}>${esc(dname(d))}</option>`).join("")}<option value="NF" ${f.dept === "NF" ? "selected" : ""}>${esc(t("nf"))}</option></select></div>`}
   ${S.role === "sec" ? "" : `<div class="fbox" title="${esc(t("sec"))}"><label for="fsec">${esc(t("sec"))}</label><select id="fsec" class="w-sec"><option value="">${esc(t("allSec"))}</option>${secs.map(s => `<option value="${s.code}" ${f.section === s.code ? "selected" : ""}>S${s.code} ${esc(s.name)}</option>`).join("")}</select></div>`}
   ${per}
   <div class="fbox" title="${esc(t("compare"))}"><label for="fcmp">${esc(t("vsL"))}</label><select id="fcmp" class="w-cmp">${["budget", "ly"].map(k => `<option value="${k}" ${f.compare === k ? "selected" : ""}>${esc(t("c_" + k))}</option>`).join("")}</select></div>
   ${chips.length ? `<div class="chips">${chips.map(c => `<span class="fchip">${esc(c[1])}<button data-unf="${c[0]}" aria-label="remove">×</button></span>`).join("")}</div>` : ""}</div>`, reset: `<button class="pill-btn reset-btn" data-reset="1" ${changed ? "" : "disabled"} title="${esc(t("resetTip"))}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/></svg>${esc(t("reset"))}</button>`};
}
function render() {
  tip.hidden = true;
  const agFocus = document.activeElement && document.activeElement.id === "ag-input";
  const agSel = agFocus ? document.activeElement.selectionStart : 0;
  const app = $("#app"); const y = scrollY; for (const k in EX) delete EX[k]; exN = 0;
  app.setAttribute("dir", S.lang === "ur" ? "rtl" : "ltr"); app.setAttribute("lang", S.lang === "ur" ? "ur" : "en"); app.classList.toggle("naskh", S.naskh);
  const al = allowed(); if (!al.includes(S.page) && !["import", "settings", "health"].includes(S.page)) S.page = "home";
  const fb = filterBar(); const main = pageHTML();
  let dr = "";
  if (S.drawer) dr = S.drawer.kind === "drill" ? drillHTML() : S.drawer.kind === "item" ? itemHTML() : S.drawer.kind === "sup" ? supHTML() : S.drawer.kind === "cell" ? cellDrawer() : S.drawer.kind === "job" ? jobDrawer() : S.drawer.kind === "agset" ? agentSettingsHTML() : "";
  const sugg = S.q.length > 1 && S.sugg.length ? `<div class="sugg">${S.sugg.map(r => `<button ${r.t === "item" ? `data-item="${esc(r.k)}"` : r.t === "supplier" ? `data-sup="${esc(r.k)}"` : `data-focus="${esc(r.k)}"`}><span class="sn">${esc(r.n)}</span><span class="muted">${esc(r.t === "item" ? (S.lang === "ur" ? "آئٹم" : "item") : r.t === "supplier" ? (S.lang === "ur" ? "سپلائر" : "supplier") : t("storeC"))}</span></button>`).join("")}</div>` : "";
  const nav = [...al, "import"].map(k => `<button data-page="${k}" title="${esc(t(k))}" ${S.page === k ? 'aria-current="page"' : ""}>${svgI(k)}<span>${esc(t(k))}</span></button>`).join("");
  app.innerHTML = `<aside class="side"><div class="brandmark"><div class="logo">SC</div><div><div class="brandname">${esc(t("brand"))}</div><div class="brandsub">${esc(t("brandsub"))}</div></div></div>
  <nav class="nav">${nav}</nav>
  <div class="side-foot"><button data-page="settings" ${S.page === "settings" ? 'aria-current="page"' : ""}>${IC.gear}<span>${esc(t("settings"))}</span></button><span><span class="dot"></span>${esc(t("dataFresh"))}</span><span>${S.boot && S.boot.last_import ? esc(fdate(S.boot.last_import)) + " · " : ""}v${esc(S.boot ? S.boot.version : "")}</span></div></aside>
  <div class="main"><header class="top"><div class="top-row"><label class="search"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg><input id="q" value="${esc(S.q)}" placeholder="${esc(t("search"))}" aria-label="${esc(t("search"))}" autocomplete="off">${sugg}</label>
  <span class="spacer"></span>${fb.reset}${fb.roleSel}<button class="pill-btn" data-page="import"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12M7 10l5 5 5-5M4 21h16"/></svg>${esc(t("addReports"))}</button>
  </div>${S.page === "agent" ? "" : fb.html}</header>
  <main class="page${S.page === "agent" ? " page-agent" : ""}">${main}</main></div>${dr}${S.modal ? (S.modal === "paste" ? pasteModal() : explainHTML(S.modal)) : ""}${S.toast ? `<div class="toast" role="status">${esc(S.toast)}</div>` : ""}${S.busy ? '<div class="topbar-load"></div>' : ""}`;
  window.scrollTo(0, y);
  const agIn = $("#ag-input"); if (agIn) {agIn.style.height = "auto"; agIn.style.height = Math.min(260, agIn.scrollHeight) + "px"; if (agFocus) {agIn.focus(); agIn.setSelectionRange(agSel, agSel)}}
  if (S.focusQ) {const q = $("#q"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); S.focusQ = false}
}
let toastT; const toast = m => {S.toast = m; render(); clearTimeout(toastT); toastT = setTimeout(() => {S.toast = null; render()}, 3200)};
function go(page) {
  const [p, tab] = String(page).split(":"); S.page = p; if (tab) {if (p === "stock") S.tab = tab} S.drawer = null; S.data = null; window.scrollTo(0, 0);
  if (p === "import") pollImport(true);
  load();
}
function refilter() {cache.clear(); S.data = null; saveView(); load()}

/* ---------------- import polling ---------------- */
let pollT = null, lastDone = null;
async function pollImport(once) {
  clearTimeout(pollT);
  const r = await api("import_status"); S.imp = {...(S.imp || {}), ...r};
  if (lastDone != null && r.done !== lastDone) {cache.clear(); S.boot = await api("boot"); if (S.page === "import") load(true)}
  lastDone = r.done;
  if (S.page === "import") render();
  if (r.busy || (r.ai && r.ai.running)) pollT = setTimeout(() => pollImport(), 350);
}
async function aiPoll() {const r = await api("import_status"); S.imp = r; if (S.page === "import") render(); if (r.ai && r.ai.running) setTimeout(aiPoll, 700)}
async function impCall(m, p) {const r = await api(m, p || {}); S.imp = r; render(); if (r.busy) pollImport()}

/* ---------------- events ---------------- */
document.addEventListener("click", async e => {
  const g = e.target.closest("[data-explain],[data-page],[data-goto],[data-lang],[data-naskh],[data-stab],[data-theme],[data-scoref],[data-close],[data-mclose],[data-item],[data-sup],[data-cell],[data-drill],[data-tv],[data-export],[data-exportjobs],[data-tsort],[data-tpage],[data-crumb],[data-dsub],[data-focus],[data-unf],[data-reset],[data-reload],[data-jobopen],[data-imppick],[data-imppaste],[data-pastego],[data-imprun],[data-imphintgo],[data-impai],[data-impclear],[data-impremove],[data-delimp],[data-savethr],[data-savetgt]");
  if (!g) return; const d = g.dataset;
  if (d.explain) {e.stopPropagation(); S.modal = EX[d.explain]; render(); return}
  if (d.page) {go(d.page); return}
  if (d.goto) {go(d.goto); return}
  if (d.lang) {S.lang = "en"; cache.clear(); saveView(); if (S.drawer && S.drawer.kind === "drill") fetchDrill(); load(); return}
  
  if (d.stab) {S.tab = d.stab; S.data = null; load(); return}
  if (d.theme) {S.theme = d.theme; S.data = null; load(); return}
  if (d.scoref) {S.scoreF = d.scoref; S.data = null; load(); return}
  if (d.close) {S.drawer = null; render(); return}
  if (d.mclose) {S.modal = null; render(); return}
  if (d.item !== undefined) {openItem(d.item); return}
  if (d.sup !== undefined) {openSup(d.sup); return}
  if (d.cell) {S.drawer = {kind: "cell", id: d.cell.split("|").map(Number)}; render(); return}
  if (d.jobopen) {S.drawer = {kind: "job", key: d.jobopen}; render(); return}
  if (d.tv) {S.tv[d.tv] = d.tvv === "1"; render(); return}
  if (d.export) {const x = TB[d.export]; if (!x) return; const plain = v => v && typeof v === "object" && "d" in v ? (typeof v.v === "number" ? v.v : v.d) : v;
    const cols = x.tb.cols.map(c => c.kind === "mdnum" ? {...c, kind: c.unit === "%" ? "pct" : "num"} : c);
    const r = await api("export", {name: x.title || x.tb.id, title: (x.title || "") + " · " + (S.data && S.data.scope || ""), cols, rows: x.tb.rows.map(row => Object.fromEntries(Object.entries(row).map(([k, v]) => [k, plain(v)])))}); toast(r.path ? t("exported") + ": " + r.path : r.error || t("cancelled")); return}
  if (d.exportjobs) {const r = await api("export_jobs"); toast(r.path ? t("exported") + ": " + r.path : r.error || t("cancelled")); return}
  if (d.tsort) {const [id, i] = d.tsort.split("|"); const st = S.tbl[id]; if (st) {if (st.sort === +i) st.dir *= -1; else {st.sort = +i; st.dir = -1}} render(); return}
  if (d.tpage) {const [id, x] = d.tpage.split("|"); S.tbl[id].p += +x; render(); return}
  if (d.crumb !== undefined) {S.drawer.path = S.drawer.path.slice(0, +d.crumb + 1); S.drawer.by = null; fetchDrill(); return}
  if (d.dsub !== undefined) {
    const D = S.drawer, dd = D.data, row = dd.rows[+d.dsub]; if (!row) return;
    if (dd.by === "supplier" && e.shiftKey) {openSup(row.k); return}
    D.path.push({lvl: dd.by, k: row.k, n: row.name}); D.by = null; fetchDrill(); return;
  }
  if (d.focus !== undefined) {if (storeRole()) S.roleStore = d.focus; else S.f.where = d.focus; S.q = ""; S.sugg = []; S.drawer = null; refilter(); return}
  if (d.unf) {if (d.unf === "dept") {S.f.dept = ""; S.f.section = ""} else if (d.unf === "section") S.f.section = ""; else S.f[d.unf] = "all"; refilter(); return}
  if (d.reset) {S.f = {...S.f, where: "all", dept: "", section: "", period: "", compare: "budget"}; refilter(); return}
  if (d.reload) {cache.clear(); load(true); return}
  if (d.drill) {e.stopPropagation(); openDrill(JSON.parse(decodeURIComponent(d.drill))); return}
  if (d.imppick !== undefined) {impCall("import_pick", {folder: d.imppick === "1"}); return}
  if (d.imppaste) {S.modal = "paste"; render(); setTimeout(() => $("#pastebox") && $("#pastebox").focus(), 30); return}
  if (d.pastego) {const txt = $("#pastebox").value; S.modal = null; if (txt.trim()) impCall("import_add", {text: txt}); else render(); return}
  if (d.imprun) {impCall("import_run"); return}
  if (d.imphintgo !== undefined) {const inp = document.querySelector(`[data-imphint="${d.imphintgo}"]`); const r = await api("import_hint", {pid: +d.imphintgo, hint: inp ? inp.value : ""}); S.imp = r; if (r.changed && r.changed.length) toast("Now read as: " + r.changed.join("; ")); render(); aiPoll(); return}
  if (d.impai !== undefined) {S.imp = await api("import_ai", {pid: +d.impai, force: true}); render(); aiPoll(); return}
  if (d.impclear) {impCall("import_clear"); return}
  if (d.impremove !== undefined) {impCall("import_remove", {pid: +d.impremove}); return}
  if (d.delimp) {if (confirm(t("delQ"))) {await api("delete_import", {import_id: +d.delimp}); cache.clear(); S.boot = await api("boot"); load(true)} return}
  if (d.savethr) {const th = {}; document.querySelectorAll("[data-thr]").forEach(i => th[i.dataset.thr] = +i.value); await api("save_settings", {thresholds: th}); cache.clear(); toast(t("saved")); return}
  if (d.savetgt) {const tg = []; document.querySelectorAll("[data-tgt]").forEach(i => {const [k, f] = i.dataset.tgt.split("|"); if (i.value !== "") tg.push({k, f, v: +i.value})}); await api("save_settings", {targets: tg}); cache.clear(); toast(t("saved")); return}
});
document.addEventListener("keydown", e => {
  if (e.key === "Enter" && e.target.dataset && e.target.dataset.imphint !== undefined) {const b = document.querySelector(`[data-imphintgo="${e.target.dataset.imphint}"]`); if (b) b.click(); return}
  if (e.key === "Escape") {if (S.modal) S.modal = null; else S.drawer = null; render()}
  if ((e.key === "Enter" || e.key === " ") && e.target.classList && e.target.classList.contains("kpi")) {e.preventDefault(); e.target.click()}
});
let qT;
document.addEventListener("input", e => {
  const el = e.target;
  if (el.id === "q") {S.q = el.value; clearTimeout(qT); qT = setTimeout(async () => {const r = await api("search", {q: S.q}); S.sugg = r.results || []; S.focusQ = true; render()}, 160)}
  else if (el.dataset.imphint !== undefined) {S.hintDraft = S.hintDraft || {}; S.hintDraft[el.dataset.imphint] = el.value}
  else if (el.dataset.tsearch) {const id = el.dataset.tsearch; S.tbl[id].q = el.value; S.tbl[id].p = 0; const pos = el.selectionStart; render(); const n = document.querySelector(`[data-tsearch="${id}"]`); if (n) {n.focus(); n.setSelectionRange(pos, pos)}}
});
document.addEventListener("change", async e => {
  const el = e.target, id = el.id, v = el.value;
  if (id === "role") {S.role = v; S.page = "home"; S.f = {...S.f, where: "all", dept: "", section: ""};
    if (storeRole() && !S.roleStore && S.boot && S.boot.stores.length) S.roleStore = S.boot.stores[0].code;
    if (v === "sec" && !S.roleSec && S.boot && S.boot.sections.length) S.roleSec = S.boot.sections[0].code;
    S.drawer = null; refilter(); return}
  if (id === "roleStore") {S.roleStore = v; refilter(); return}
  if (id === "roleDept") {S.roleDept = v; S.f.section = ""; refilter(); return}
  if (id === "roleSec") {S.roleSec = v; refilter(); return}
  if (id === "where") {S.f.where = v; refilter(); return}
  if (id === "fdept") {S.f.dept = v; S.f.section = ""; refilter(); return}
  if (id === "fsec") {S.f.section = v; refilter(); return}
  if (id === "fper") {S.f.period = v; refilter(); return}
  if (id === "fcmp") {S.f.compare = v; refilter(); return}
  if (id === "drillBy") {S.drawer.by = v; fetchDrill(); return}
  if (el.dataset.job) {await api("job_done", {id: el.dataset.job, done: el.checked}); cache.clear(); load(true); return}
  if (el.dataset.impset) {const [pid, si, f] = el.dataset.impset.split("|"); impCall("import_set", {pid: +pid, si: +si, [f]: v}); return}
  if (el.dataset.alias) {if (v) {await api("add_alias", {code: v, alias: el.dataset.alias}); cache.clear(); load(true)} return}
});
// files dropped on the window (the desktop app passes real paths; a browser cannot)
window.SC_drop = paths => {if (S.page === "agent") {agentAttachPaths(paths); return} go("import"); impCall("import_add", {paths})};
document.addEventListener("dragover", e => {e.preventDefault(); const d = $("#drop"); if (d) d.classList.add("over")});
document.addEventListener("dragleave", () => {const d = $("#drop"); if (d) d.classList.remove("over")});
document.addEventListener("drop", e => e.preventDefault());

/* ---------------- start ---------------- */
async function start() {
  const b = await api("boot"); S.boot = b;
  const v = b.view || {}; S.lang = "en"; S.naskh = false;  // English only
  if (v.role) S.role = v.role; S.roleStore = v.roleStore || (b.stores[0] || {}).code || ""; S.roleDept = v.roleDept || "01"; S.roleSec = v.roleSec || (b.sections[0] || {}).code || "";
  S.f.where = v.where || "all"; S.f.dept = v.dept || ""; S.f.section = v.section || ""; S.f.compare = v.compare || "budget";
  if (!b.has_data) S.page = "import";
  go(S.page);
}
function boot() {
  if (window.qt && window.qt.webChannelTransport) {
    const s = document.createElement("script"); s.src = "qrc:///qtwebchannel/qwebchannel.js";
    s.onload = () => new QWebChannel(qt.webChannelTransport, ch => {bridge = ch.objects.bridge; start()});
    document.head.appendChild(s);
  } else start();
}
window.addEventListener("error", e => {window.SC_errors = (window.SC_errors || []).concat(String(e.message))});
boot();
