/* Stock Compass — Other data: every table the importer did not know, understood column by column (store, item,
   supplier, date, amounts) and shown with the same filters as every screen. Correct a column once; it is remembered. */

const DS = {list: null, key: null, by: null, view: null, busy: false, cols: false, sig: ""};
const DS_FMT = {money: "pkr", quantity: "int", percent: "pct", number: "num"};
const dsFmt = c => DS_FMT[c.kind] || "num";

async function dataLoad() {
  const sig = JSON.stringify(ctx());
  if (!DS.list || DS.sig !== sig) {DS.sig = sig; DS.list = null; render(); DS.list = await api("data_list"); if (DS.key) DS.view = null}
  if (!DS.key && DS.list.datasets && DS.list.datasets.length) DS.key = DS.list.datasets[0].key;
  render();
  if (DS.key && !DS.view) dataView();
}
async function dataView() {
  DS.busy = true; render();
  try {DS.view = await api("data_view", {key: DS.key, by: DS.by})} catch (e) {DS.view = {error: String(e)}}
  DS.busy = false; if (DS.view && DS.view.by) DS.by = DS.view.by; render();
}

function dataPage() {
  const L0 = DS.list;
  const hd = head({title: t("data"), sub: "Any other file you add: each table is read column by column, matched to stores, items and suppliers, and kept by date."});
  if (!L0) return hd + loadingBox();
  if (L0.error) return hd + errBox(L0, false);
  if (!L0.datasets.length) return hd + emptyBox("No other data yet", "Add any Excel or CSV file (waste, shrink, footfall, supplier list with addresses, targets, anything). Stock Compass finds the store, item, supplier and date columns by itself and it appears here, in item and supplier cards, in Analyse, on the map and for the agent.", `<button class="primary" data-page="import">${esc(t("goImport"))}</button>`);
  const cards = `<div class="ds-cards">${L0.datasets.map(x => `<button class="ds-card" data-dskey="${esc(x.key)}" aria-pressed="${DS.key === x.key}">
    <b>${esc(x.name)}</b><small>${fmtN(x.rows)} rows${x.stores ? ` · ${x.stores} store${x.stores > 1 ? "s" : ""}` : " · country"}${x.last ? " · " + esc(fdate(x.last)) : ""}</small>
    <span class="ds-keys">${x.keys.map(k => `<span class="tag">${esc(k)}</span>`).join("")}</span>
    ${x.headline.slice(0, 2).map(h => `<span class="ds-h"><span>${esc(h.name)}</span><b>${bd(fmtV(h.v, DS_FMT[h.kind] || "num"))}</b></span>`).join("")}</button>`).join("")}</div>`;
  let h = hd + panelC({title: "Datasets", sub: `${L0.datasets.length} kinds of table · filtered: ${L0.scope}`, body: {type: "raw"}}).replace("\u0000BODY\u0000", () => cards);
  const V = DS.view;
  if (DS.busy && !V) return h + loadingBox();
  if (!V) return h;
  if (V.error) return h + errBox(V, false);
  return h + dataViewHTML(V);
}

function dataViewHTML(V) {
  const ds = V.ds, ms = ds.measures, st = V.stats || {};
  const grp = V.groups || [];
  const tools = `<div class="row ds-tools"><label class="an-lbl" for="ds-name">Name</label><input id="ds-name" value="${esc(ds.name)}" style="min-width:260px"><button class="pill-btn" data-dsrename="1">Rename</button>
    <span class="spacer"></span>${grp.length ? `<label class="an-lbl" for="ds-by">Group by</label><select id="ds-by">${grp.map(g => `<option value="${esc(g.k)}" ${V.by === g.k ? "selected" : ""}>${esc(g.n)}</option>`).join("")}</select>` : ""}
    <button class="pill-btn" data-dscols="1" aria-pressed="${DS.cols}">✎ Columns</button><button class="pill-btn" data-dsexport="1">⤓ Export all rows</button><button class="pill-btn" data-dshide="1" title="Hide this dataset from every screen (the rows stay; delete the imports in Add reports to remove them)">Hide</button></div>`;
  const k = (l, v, sub) => `<div class="kpi"><div class="kpi-l"><span>${esc(l)}</span></div><div class="kpi-top"><div class="kpi-v num">${bd(v)}</div></div><div class="kpi-s">${esc(sub || "")}</div></div>`;
  let kp = k("Rows", fmtN(V.n), `${fmtN((V.imports || []).length)} import${(V.imports || []).length === 1 ? "" : "s"}`);
  if (st.stores) kp += k("Stores", fmtN(st.stores), "with rows in this view");
  if (st.items) kp += k("Items", fmtN(st.items), "");
  if (st.first) kp += k("Dates", st.first === st.last ? fdate(st.first) : `${fdate(st.first)} – ${fdate(st.last)}`, V.series ? "history builds up with every import" : "");
  for (const c of ms.slice(0, 6)) kp += k(c.label || c.name, fmtV(V.totals[c.name], dsFmt(c)), c.kind === "percent" ? "average" : "total");
  let h = panelC({title: ds.name, sub: `filtered: ${V.scope}`, body: {type: "raw"}}).replace("\u0000BODY\u0000", () => tools + (DS.cols ? dataColsHTML(ds) : "")) + `<div class="kpis">${kp}</div>`;
  const panels = [];
  if (V.by_store && V.by_store.length && ms.length) {
    const m0 = ms[0];
    panels.push({html: panelC({title: `${m0.label || m0.name} by store`, sub: m0.kind === "percent" ? "average" : "total", body: {type: "raw"}}).replace("\u0000BODY\u0000",
      () => hbars({items: V.by_store.filter(r => r.k).map(r => ({l: r.name, v: r.v[m0.name], x: `${fmtN(r.n)} rows`})).slice(0, 25), fmt: dsFmt(m0)}))});
  }
  if (V.trend && V.trend.length > 1 && ms.length) panels.push({html: panelC({title: `${ms[0].label || ms[0].name} by day`, body: {type: "line", id: "ds_tr", xs: V.trend.map(p => p.d), series: [{n: ms[0].label || ms[0].name, v: V.trend.map(p => p.v)}], fmt: dsFmt(ms[0])}})});
  h += layout(panels);
  const byName = (grp.find(g => g.k === V.by) || {}).n || "";
  if (V.rows && V.rows.length) {
    const rows = V.rows.map(r => {const o = {name: r.name, n: r.n, k: r.k}; for (const c of ms) o["m_" + c.name] = r.v[c.name];
      if (V.by === "item") o.item = r.k; else if (V.by === "supplier") o.supplier = r.k; else if (V.by === "store") o.store = r.k; return o});
    const cols = [{k: "name", l: byName, kind: "name"}, ...ms.map(c => ({k: "m_" + c.name, l: c.label || c.name, kind: dsFmt(c)})), {k: "n", l: "Rows", kind: "int"}];
    const act = V.by === "item" ? {kind: "item"} : V.by === "supplier" ? {kind: "supplier"} : V.by === "store" ? {kind: "focus_store"} : null;
    h += panelC({title: `By ${byName.toLowerCase()}`, sub: `${fmtN(V.rows.length)}${V.more ? "+" : ""} groups${act ? " · click a row to open it" : ""}`, body: {type: "table", id: "ds_g_" + ds.key, cols, rows, action: act, page_size: 25}});
  }
  const det = V.detail;
  if (det && det.rows.length) h += panelC({title: "Rows", sub: `${fmtN(det.rows.length)} of ${fmtN(det.total)} shown · Export all rows gives everything`, body: {type: "table", id: "ds_rows_" + ds.key, cols: det.cols, rows: det.rows, action: ds.has.includes("item") ? {kind: "item"} : null, page_size: 30, total: false}});
  if (V.imports && V.imports.length) h += panelC({title: "Files it comes from", body: {type: "table", id: "ds_imp_" + ds.key, cols: [{k: "file_name", l: "File", kind: "text"}, {k: "sheet", l: "Sheet", kind: "text"}, {k: "snapshot_date", l: "Date", kind: "date"}, {k: "stores", l: "Stores", kind: "text"}, {k: "rows", l: "Rows", kind: "int"}, {k: "imported_at", l: "Imported", kind: "date"}], rows: V.imports, page_size: 10, total: false}});
  return h;
}

function dataColsHTML(ds) {
  const R = DS.list.roles, K = DS.list.kinds;
  return `<p class="muted" style="font-size:12.5px;margin:8px 0">What each column is. Stock Compass guessed from the header and the values; change anything that is wrong. It is remembered for every file with these columns.</p>
  <div class="tbl-wrap set-tbl" style="max-height:none"><table><thead><tr><th class="nosort">Column</th><th class="nosort">Is</th><th class="nosort">Amount type</th><th class="nosort">Meaning (optional)</th></tr></thead><tbody>
  ${ds.columns.map(c => `<tr><td><b>${esc(c.name)}</b>${c.user ? ` <span class="tag">set by you</span>` : ""}</td>
    <td><select data-dscol="${esc(c.name)}" data-f="role" aria-label="${esc("What " + c.name + " is")}">${Object.entries(R).filter(([r]) => r !== "wide_store").map(([r, n]) => `<option value="${r}" ${c.role === r ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></td>
    <td>${c.role === "measure" ? `<select data-dscol="${esc(c.name)}" data-f="kind" aria-label="${esc("Amount type of " + c.name)}">${Object.entries(K).map(([r, n]) => `<option value="${r}" ${c.kind === r ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>` : ""}</td>
    <td><input data-dscol="${esc(c.name)}" data-f="label" value="${esc(c.label || "")}" placeholder="e.g. waste at cost price" aria-label="${esc("Meaning of " + c.name)}"></td></tr>`).join("")}</tbody></table></div>`;
}

document.addEventListener("click", async e => {
  if (S.page !== "data") return;
  const g = e.target.closest("[data-dskey],[data-dsrename],[data-dscols],[data-dsexport],[data-dshide]"); if (!g) return;
  const d = g.dataset;
  if (d.dskey) {DS.key = d.dskey; DS.by = null; DS.view = null; DS.cols = false; dataView()}
  else if (d.dsrename) {const n = ($("#ds-name") || {}).value || ""; if (!n.trim()) return; await api("data_rename", {key: DS.key, name: n}); DS.list = null; DS.view = null; toast("Renamed"); dataLoad()}
  else if (d.dscols) {DS.cols = !DS.cols; render()}
  else if (d.dsexport) {const r = await api("data_export", {key: DS.key}); toast(r.path ? t("exported") + ": " + r.path : r.error || t("cancelled"))}
  else if (d.dshide) {if (!confirm("Hide this dataset from every screen? Its rows stay on this PC.")) return; await api("data_hide", {key: DS.key, hidden: true}); DS.key = null; DS.view = null; DS.list = null; dataLoad()}
});
document.addEventListener("change", async e => {
  if (S.page !== "data") return; const el = e.target;
  if (el.id === "ds-by") {DS.by = el.value; dataView(); return}
  if (el.dataset && el.dataset.dscol) {
    const r = await api("data_column", {key: DS.key, name: el.dataset.dscol, [el.dataset.f]: el.value});
    toast(r.note || "Saved"); DS.list = null; DS.view = null; dataLoad();
  }
});
