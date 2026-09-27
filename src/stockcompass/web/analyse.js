/* Stock Compass — Analyse: any measure by any dimension (and a second one for a matrix), with filters, totals,
   shares, ranks, top-N, charts and export. Totals and ratios come from the data service, recomputed from base values. */

const AN = {meta: null, dim: "store", dim2: "", measures: ["sales", "vs_budget", "margin_pct"], filters: {}, top: 25, chart: "auto",
  sort: null, desc: true, data: null, busy: false, pick: null, opts: null, optQ: "", key: ""};
const DRILL_NEXT = {format: "store", region: "store", store: "dept", dept: "section", section: "family", family: "supplier", supplier: "item",
  reason: "item", bucket: "item", cause: "item", theme: "item", order_type: "supplier"};

function anLoadState() {try {const s = JSON.parse(localStorage.getItem("sc_an") || "null"); if (s) Object.assign(AN, {dim: s.dim, dim2: s.dim2 || "", measures: s.measures, filters: s.filters || {}, top: s.top ?? 25, chart: s.chart || "auto"})} catch (e) {}}
function anSaveState() {try {localStorage.setItem("sc_an", JSON.stringify({dim: AN.dim, dim2: AN.dim2, measures: AN.measures, filters: AN.filters, top: AN.top, chart: AN.chart}))} catch (e) {}}
anLoadState();

async function analyseLoad(force) {
  if (!AN.meta) AN.meta = await api("explore_meta");
  const key = JSON.stringify([ctx(), AN.dim, AN.dim2, AN.measures, AN.filters, AN.top, AN.sort, AN.desc]);
  if (!force && AN.data && AN.key === key) {render(); return}
  AN.busy = true; render();
  let d;
  try {d = await api("explore", {dim: AN.dim, dim2: AN.dim2 || null, measures: AN.measures, filters: AN.filters, top: AN.top, sort: AN.sort, desc: AN.desc})} catch (e) {d = {error: String(e)}}
  AN.busy = false; AN.data = d; AN.key = key; anSaveState(); render();
}
const anM = k => {for (const g of (AN.meta || {groups: []}).groups) for (const m of g.m) if (m.k === k) return m; return {k, l: k, kind: "num"}};
const anD = k => ((AN.meta || {dims: []}).dims.find(d => d.k === k) || {l: k}).l;
const anKind = k => ({pkr: "pkr", int: "int", pct: "pct", sg: "sg"})[k] || "num";

function analysePage() {
  if (!AN.meta) return `<div class="loading"><span class="spin"></span>${esc(t("loading"))}</div>`;
  const d = AN.data || {};
  const dimOpts = (sel, none) => (none ? `<option value="">— none —</option>` : "") + ["Where", "Range", "Time", "Detail"].map(g => `<optgroup label="${g}">${AN.meta.dims.filter(x => x.g === g).map(x => `<option value="${x.k}" ${sel === x.k ? "selected" : ""}>${esc(x.l)}</option>`).join("")}</optgroup>`).join("");
  const mOpts = AN.meta.groups.map(g => `<optgroup label="${esc(g.n)}">${g.m.filter(m => !AN.measures.includes(m.k)).map(m => `<option value="${m.k}">${esc(m.l)}</option>`).join("")}</optgroup>`).join("");
  const chips = AN.measures.map((k, i) => `<span class="an-chip ${i === 0 ? "main" : ""}" data-tip="${esc(`<b>${esc(anM(k).l)}</b><br>${esc(anM(k).help || "")}${i ? "<br><i>Click to make it the main measure</i>" : "<br><i>Main measure: sorts, charts and shares</i>"}`)}"><button class="an-cm" data-an="main" data-k="${k}">${esc(anM(k).l)}</button>${AN.measures.length > 1 ? `<button class="an-x" data-an="rmm" data-k="${k}" aria-label="Remove ${esc(anM(k).l)}">×</button>` : ""}</span>`).join("");
  const fchips = Object.entries(AN.filters).filter(([, v]) => v && v.length).map(([dim, vals]) => `<span class="an-chip f"><button class="an-cm" data-an="fedit" data-k="${dim}">${esc(anD(dim))}: ${esc(vals.length > 2 ? vals.length + " selected" : vals.map(v => (AN.lbl || {})[dim + "|" + v] || v).join(", "))}</button><button class="an-x" data-an="frm" data-k="${dim}" aria-label="Remove filter ${esc(anD(dim))}">×</button></span>`).join("");
  const presets = `<select id="an-preset" class="an-sel" aria-label="Ready-made views"><option value="">Ready-made views…</option>${AN.meta.presets.map((p, i) => `<option value="${i}">${esc(p.n)}</option>`).join("")}</select>`;
  const ctl = `<section class="panel an-ctl">
    <div class="an-row"><span class="an-lbl">Show</span><div class="an-chips">${chips}</div>
      ${AN.dim2 ? `<span class="muted" style="font-size:12px">Matrix shows the main measure</span>` : `<select id="an-addm" aria-label="Add a measure"><option value="">+ Add measure</option>${mOpts}</select>`}</div>
    <div class="an-row"><label class="an-lbl" for="an-dim">By</label><select id="an-dim">${dimOpts(AN.dim)}</select>
      <label class="an-lbl" for="an-dim2">Across</label><select id="an-dim2">${dimOpts(AN.dim2, true)}</select>
      <label class="an-lbl" for="an-top">Rows</label><select id="an-top">${[[10, "Top 10"], [25, "Top 25"], [50, "Top 50"], [100, "Top 100"], [0, "All"]].map(([v, l]) => `<option value="${v}" ${+AN.top === v ? "selected" : ""}>${l}</option>`).join("")}</select>
      <button class="pill-btn" data-an="swap" ${AN.dim2 ? "" : "disabled"} data-tip="Swap rows and columns">⇄</button>
</div>
    <div class="an-row"><span class="an-lbl">Filters</span><div class="an-chips">${fchips || `<span class="muted" style="font-size:12.5px">None — plus the store / department / section chosen at the top</span>`}</div>
      <select id="an-addf" aria-label="Add a filter"><option value="">+ Filter</option>${AN.meta.dims.filter(x => x.k !== "day").map(x => `<option value="${x.k}">${esc(x.l)}</option>`).join("")}</select></div>
    ${AN.pick ? anPicker() : ""}</section>`;
  let h = `<div class="ph"><div><h1>${esc(t("analyse"))}</h1><p>Any measure by store, format, region, department, section, family, supplier, item or day — with totals, shares and filters.</p>
    <div class="scope">${esc(d.scope || "")}${d.sources && d.sources.length ? " · " + esc(d.sources.join(" · ")) : ""}</div></div>
    <div class="row">${presets}<button class="pill-btn" data-an="export" ${d.rows && d.rows.length ? "" : "disabled"}>⤓ Excel</button><button class="pill-btn" data-an="reset">Reset</button></div></div>` + ctl;
  if (AN.busy && !AN.data) return h + `<div class="loading"><span class="spin"></span>${esc(t("loading"))}</div>`;
  if (d.error) return h + `<div class="errbox">${esc(d.error)}</div>`;
  for (const n of d.notes || []) h += `<div class="banner">ⓘ ${esc(n)}</div>`;
  if (!d.rows || !d.rows.length) return h + emptyBox(t("noData"), "Nothing matches these choices. Try another measure, fewer filters, or import the report it needs.", `<button class="primary" data-page="import">${esc(t("goImport"))}</button>`);
  h += `<div class="kpis an-kpis">${d.measures.map(m => `<div class="kpi" data-tip="${esc(`<b>${esc(m.l)}</b><br>${esc(m.help)}<br>Total over everything filtered${d.others ? ", including Others" : ""}; rates are recomputed from base values.`)}"><div class="kpi-l"><span>${esc(m.l)}</span></div><div class="kpi-top"><div class="kpi-v num">${bd(anFmt(d.totals[m.k], m.kind))}</div></div><div class="kpi-s">${esc(t("total"))} · ${fmtN(d.stats.count)} ${esc(d.dim_label.toLowerCase())}${d.stats.count === 1 ? "" : "s"}</div></div>`).join("")}
    <div class="kpi"><div class="kpi-l"><span>${esc(d.measures[0].l)}: spread</span></div><div class="kpi-top"><div class="kpi-v num" style="font-size:18px">${bd(anFmt(d.stats.min, d.measures[0].kind))} → ${bd(anFmt(d.stats.max, d.measures[0].kind))}</div></div><div class="kpi-s">Average ${anFmt(d.stats.avg, d.measures[0].kind)} per ${esc(d.dim_label.toLowerCase())} (shown rows)</div></div></div>`;
  const chartTabs = `<div class="tools">${[["auto", "Auto"], ["bar", "Bars"], ["hbar", "Ranking"], ["line", "Line"], ["none", "Hide"]].map(([k, l]) => `<button data-an="chart" data-k="${k}" aria-pressed="${AN.chart === k}">${l}</button>`).join("")}</div>`;
  if (AN.chart !== "none") h += `<section class="panel"><div class="phd"><h2>${esc(d.measures[0].l)} by ${esc(d.dim_label.toLowerCase())}${d.dim2 ? ` and ${esc(d.dim2_label.toLowerCase())}` : ""}</h2>${chartTabs}</div>${anChart(d)}</section>`;
  else h += `<div class="row" style="justify-content:flex-end">${chartTabs}</div>`;
  h += d.dim2 ? anMatrix(d) : panelC({title: `${d.dim_label}${AN.top && d.others ? ` — top ${AN.top} of ${d.stats.count}` : ""}`, sub: `click a row to go one level deeper`, body: anTable(d)});
  return h;
}
function anFmt(v, kind) {return kind === "sg" ? sg(v) : kind === "pct" ? pc(v) : fmtV(v, anKind(kind))}

function anTable(d) {
  const cols = [{k: "rank", l: "#", kind: "int"}, {k: "name", l: d.dim_label, kind: "name"}, ...d.measures.map(m => ({k: m.k, l: m.l, kind: anKind(m.kind)}))];
  const additive = ["pkr", "int"].includes(d.measures[0].kind);
  if (additive) cols.push({k: "share", l: "Share %", kind: "pct"});
  const rows = [...d.rows, ...(d.others ? [d.others] : [])].map(r => ({k: r.k, name: r.name, rank: r.rank, share: r.share, ...r.v, _an: r.k !== "__others"}));
  const totals = {...d.totals}; if (additive) totals.share = 100; totals.rank = null;
  return {type: "table", id: "an_t", cols, rows, totals, action: {kind: "an"}, page_size: 100};
}
function anChart(d) {
  const m = d.measures[0]; const f = anKind(m.kind); const rows = d.rows.filter(r => r.v[m.k] != null);
  let type = AN.chart;
  if (type === "auto") type = d.dim === "day" ? "line" : d.dim2 ? "bar" : rows.length > 14 || ["item", "supplier", "family"].includes(d.dim) ? "hbar" : "bar";
  if (d.dim2) {
    const cs = d.cols.slice(0, 8); const rs = rows.slice(0, type === "line" ? 60 : 20);
    if (type === "line") return lineChart({id: "an_c", xs: rs.map(r => r.name), series: cs.map((c, i) => ({n: c.name, c: PAL[i % PAL.length], v: rs.map(r => (r.cells || {})[c.k] ?? null)})), fmt: f});
    return legend(cs.map((c, i) => ({n: c.name, c: PAL[i % PAL.length]}))) + barChart({id: "an_c", cats: rs.map(r => ({l: r.name, k: r.k})), series: cs.map((c, i) => ({n: c.name, c: PAL[i % PAL.length], v: rs.map(r => (r.cells || {})[c.k] ?? 0)})), fmt: f, height: 300});
  }
  if (type === "line") return lineChart({id: "an_c", xs: rows.map(r => r.name), series: d.measures.filter(x => x.kind === m.kind).slice(0, 4).map((x, i) => ({n: x.l, c: PAL[i % PAL.length], v: rows.map(r => r.v[x.k] ?? null)})), fmt: f, zero: f !== "sg"});
  if (type === "hbar") return hbars({items: rows.slice(0, 40).map(r => ({l: r.name, v: r.v[m.k], c: m.kind === "sg" ? (r.v[m.k] >= 0 ? "var(--good)" : "var(--crit)") : undefined,
    x: d.measures.slice(1).map(x => `${x.l}: ${anFmt(r.v[x.k], x.kind)}`).join(" · ")})), fmt: f});
  const same = d.measures.filter(x => x.kind === m.kind).slice(0, 3); const rs = rows.slice(0, 24);
  return legend(same.map((x, i) => ({n: x.l, c: PAL[i % PAL.length]}))) + barChart({id: "an_c", cats: rs.map(r => ({l: r.name, k: r.k})), series: same.map((x, i) => ({n: x.l, c: PAL[i % PAL.length], v: rs.map(r => r.v[x.k] ?? 0)})), fmt: f, height: 300});
}
function anMatrix(d) {
  const m = d.measures[0]; const rows = [...d.rows, ...(d.others ? [d.others] : [])];
  const vals = rows.flatMap(r => d.cols.map(c => (r.cells || {})[c.k])).filter(v => v != null);
  const lo = Math.min(...vals), hi = Math.max(...vals); const bad = /zero|oos|not_on|lost|neg|dp_|late|sleep|leaf_zero/.test(m.k);
  const shade = v => {if (v == null || hi === lo) return ""; const x = (v - lo) / (hi - lo); return `background:color-mix(in srgb, var(${bad ? "--crit" : "--s1"}) ${Math.round(8 + x * 52)}%, var(--card))`};
  const additive = ["pkr", "int"].includes(m.kind);
  const cell = (r, c, v) => `<td class="n" style="${shade(v)}" data-tip="${esc(`<b>${esc(r.name)} · ${esc(c.name)}</b><br>${esc(m.l)}: <b>${anFmt(v, m.kind)}</b>${additive && v != null && r.v[m.k] ? `<br>${pc(v / r.v[m.k] * 100)} of ${esc(r.name)}` : ""}${additive && v != null && c.total ? `<br>${pc(v / c.total * 100)} of ${esc(c.name)}` : ""}`)}">${v == null ? "—" : bd(anFmt(v, m.kind))}</td>`;
  return `<section class="panel"><div class="phd"><h2>${esc(m.l)}: ${esc(d.dim_label)} × ${esc(d.dim2_label)} <small>${fmtN(d.stats.count)} × ${fmtN(d.cols.length)}</small></h2></div>
  <div class="tbl-wrap an-matrix"><table><thead><tr><th>${esc(d.dim_label)}</th>${d.cols.map(c => `<th class="n">${esc(c.name)}</th>`).join("")}<th class="n an-tot">${esc(t("total"))}</th></tr></thead>
  <tbody>${rows.map(r => `<tr ${r.k !== "__others" ? `class="click" data-an-row="${esc(r.k ?? "")}"` : ""}><td><b>${esc(r.name)}</b></td>${d.cols.map(c => cell(r, c, (r.cells || {})[c.k])).join("")}<td class="n an-tot">${bd(anFmt(r.v[m.k], m.kind))}</td></tr>`).join("")}</tbody>
  <tfoot><tr class="tot"><td>${esc(t("total"))}</td>${d.cols.map(c => `<td class="n">${bd(anFmt(c.total, m.kind))}</td>`).join("")}<td class="n an-tot">${bd(anFmt(d.totals[m.k], m.kind))}</td></tr></tfoot></table></div></section>`;
}
function anPicker() {
  const o = AN.opts; const sel = new Set(AN.filters[AN.pick] || []);
  return `<div class="an-pick"><div class="an-row"><b>${esc(anD(AN.pick))}</b><input id="an-optq" value="${esc(AN.optQ)}" placeholder="Search…" aria-label="Search values"><span class="spacer"></span>
    <button class="pill-btn" data-an="fall">Select shown</button><button class="pill-btn" data-an="fnone">Clear</button><button class="primary" data-an="fapply">Apply</button><button class="pill-btn" data-an="fclose">Close</button></div>
    <div class="an-opts">${!o ? `<span class="spin sm"></span>` : o.values.length ? o.values.map(v => `<label class="an-opt" title="${esc(v.n)}"><input type="checkbox" data-anopt="${esc(v.k)}" data-n="${esc(v.n)}" ${sel.has(v.k) ? "checked" : ""}> ${esc(v.n)}</label>`).join("") : `<span class="muted">No values</span>`}${o && o.more ? `<span class="muted">…more; search to narrow</span>` : ""}</div></div>`;
}
async function anOpts() {AN.opts = null; render(); AN.opts = await api("explore_options", {dim: AN.pick, measure: AN.measures[0], q: AN.optQ}); render()}
function anSet(p) {Object.assign(AN, p); AN.sort = null; analyseLoad()}

document.addEventListener("click", e => {
  const row = e.target.closest("[data-an-row]");
  if (row && S.page === "analyse") {
    const k = row.dataset.anRow; const d = AN.data; if (!d || k === "__others") return;
    const r = d.rows.find(x => String(x.k) === k); if (r) (AN.lbl = AN.lbl || {})[d.dim + "|" + k] = r.name;
    const nx = DRILL_NEXT[d.dim]; if (!nx || !k) return;
    anSet({filters: {...AN.filters, [d.dim]: [k]}, dim: nx, dim2: AN.dim2 === nx ? "" : AN.dim2}); return;
  }
  const op = e.target.closest("[data-an-open]");
  if (op) {const o = JSON.parse(decodeURIComponent(op.dataset.anOpen)); const f = {}; AN.lbl = AN.lbl || {};
    for (const p of o.path || []) {f[p.lvl === "lpo" ? "supplier" : p.lvl] = [String(p.k)]; AN.lbl[p.lvl + "|" + p.k] = p.n || p.k}
    anOpen({dim: o.by === "lpo" ? "supplier" : o.by, measures: AN_OF[o.m], filters: f}); return}
  const g = e.target.closest("[data-an]"); if (!g) return;
  const a = g.dataset.an, k = g.dataset.k;
  if (a === "main") anSet({measures: [k, ...AN.measures.filter(x => x !== k)]});
  else if (a === "rmm") anSet({measures: AN.measures.filter(x => x !== k)});
  else if (a === "swap") anSet({dim: AN.dim2, dim2: AN.dim});
  else if (a === "chart") {AN.chart = k; anSaveState(); render()}
  else if (a === "reset") {AN.filters = {}; anSet({dim: "store", dim2: "", measures: ["sales", "vs_budget", "margin_pct"], top: 25, chart: "auto"})}
  else if (a === "frm") {const f = {...AN.filters}; delete f[k]; anSet({filters: f})}
  else if (a === "fedit") {AN.pick = k; AN.optQ = ""; anOpts()}
  else if (a === "fclose") {AN.pick = null; render()}
  else if (a === "fall") document.querySelectorAll("[data-anopt]").forEach(x => {x.checked = true});
  else if (a === "fnone") document.querySelectorAll("[data-anopt]").forEach(x => {x.checked = false});
  else if (a === "fapply") {
    const vals = [...document.querySelectorAll("[data-anopt]")].filter(x => x.checked); AN.lbl = AN.lbl || {};
    vals.forEach(x => {AN.lbl[AN.pick + "|" + x.dataset.anopt] = x.dataset.n});
    const f = {...AN.filters}; if (vals.length) f[AN.pick] = vals.map(x => x.dataset.anopt); else delete f[AN.pick]; AN.pick = null; anSet({filters: f});
  }
  else if (a === "export") {
    const d = AN.data; if (!d) return;
    let cols, rows;
    if (d.dim2) {cols = [{k: "name", l: d.dim_label, kind: "text"}, ...d.cols.map(c => ({k: "c_" + c.k, l: c.name, kind: anKind(d.measures[0].kind)})), {k: "tot", l: "Total", kind: anKind(d.measures[0].kind)}];
      rows = [...d.rows, ...(d.others ? [d.others] : [])].map(r => ({name: r.name, tot: r.v[d.measures[0].k], ...Object.fromEntries(d.cols.map(c => ["c_" + c.k, (r.cells || {})[c.k]]))}))}
    else {const tb = anTable(d); cols = tb.cols.map(c => c.kind === "name" ? {...c, kind: "text"} : c); rows = tb.rows}
    api("export", {name: `Analyse ${d.measures[0].l} by ${d.dim_label}`, title: `${d.measures.map(m => m.l).join(", ")} by ${d.dim_label}${d.dim2 ? " × " + d.dim2_label : ""} · ${d.scope}`, cols, rows}).then(r => toast(r.error ? r.error : r.path ? "Saved " + r.path : "Cancelled"));
  }
});
document.addEventListener("change", e => {
  const el = e.target; if (S.page !== "analyse") return;
  if (el.id === "an-dim") anSet({dim: el.value, dim2: AN.dim2 === el.value ? "" : AN.dim2});
  else if (el.id === "an-dim2") anSet({dim2: el.value, measures: el.value ? AN.measures : AN.measures});
  else if (el.id === "an-top") anSet({top: +el.value});
  else if (el.id === "an-addm" && el.value) anSet({measures: [...AN.measures, el.value].slice(0, 8)});
  else if (el.id === "an-addf" && el.value) {AN.pick = el.value; AN.optQ = ""; anOpts()}
  else if (el.id === "an-preset" && el.value !== "") {const p = AN.meta.presets[+el.value]; AN.chart = p.chart || "auto"; anSet({dim: p.dim, dim2: p.dim2 || "", measures: p.m})}
});
let anQT = null;
document.addEventListener("input", e => {if (e.target.id === "an-optq") {AN.optQ = e.target.value; clearTimeout(anQT); anQT = setTimeout(async () => {AN.opts = await api("explore_options", {dim: AN.pick, measure: AN.measures[0], q: AN.optQ}); const box = document.querySelector(".an-opts"); if (box) {const tmp = document.createElement("div"); tmp.innerHTML = anPicker(); box.replaceWith(tmp.querySelector(".an-opts"))}}, 250)}});
/* open Analyse already set up, from anywhere: anOpen({dim, measures, filters}) */
function anOpen(p) {Object.assign(AN, {dim2: "", filters: {}}, p); AN.data = null; go("analyse")}
