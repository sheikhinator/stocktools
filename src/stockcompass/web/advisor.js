/* Stock Compass — Order Advisor: before an LPO, check every line: how much to order, whether to order at all, or
   transfer from another store first (IST). Two ways in: a suggested order, or a check of a pasted order. */

const OA = {meta: null, mode: "suggest", store: "", supplier: "", text: "", data: null, busy: false, filter: "all", rulesOpen: false, draft: {}};
const OA_DEC = {order: ["crit", "Order"], ist_order: ["warn", "Transfer + order"], ist: ["good", "Transfer instead"], none: ["neutral", "Enough stock"],
  stop: ["crit", "Don't order"], check: ["warn", "Check"]};
const OA_VERDICT = {ok: ["good", "OK as it is"], reduce: ["warn", "Reduce"], increase: ["warn", "Increase"], remove: ["crit", "Remove"], ist: ["good", "Transfer instead"], check: ["warn", "Check"]};

async function advisorLoad() {
  if (!OA.meta) {OA.meta = await api("advisor_meta")}
  if (!OA.store) OA.store = storeRole() ? (S.roleStore || "") : (S.f.where && !/^(fmt|reg):/.test(S.f.where) && S.f.where !== "all" ? S.f.where : "all");
  render();
}
async function advisorRun() {
  OA.busy = true; OA.data = null; render();
  const p = {store: OA.store || "all", supplier: OA.supplier || null, dept: S.f.dept || (S.role === "dh" ? S.roleDept : null), section: S.f.section || (S.role === "sec" ? S.roleSec : null)};
  if (OA.mode === "check") p.text = OA.text;
  try {OA.data = await api("advisor", p)} catch (e) {OA.data = {error: String(e)}}
  OA.busy = false; OA.filter = "all"; render();
}
const oaMoney = v => fmtV(v, "pkr");

function advisorPage() {
  const M = OA.meta; if (!M) return `<div class="loading"><span class="spin"></span>${esc(t("loading"))}</div>`;
  if (M.error) return errBox(M, false);
  const b = S.boot || {stores: []};
  // 1. the data it needs, step by step
  const steps = `<div class="oa-steps">${M.steps.map(x => {const [c, l] = STEP_CHIP[x.status] || ["neutral", x.status];
    return `<div class="oa-step ${x.status}" data-tip="${esc(`<b>${esc(x.title)}</b><br>${esc(x.where)}<br><i>${esc(x.note)}</i>`)}"><span class="step-n sm">${x.status === "done" ? "✓" : x.n}</span><span class="oa-st">${esc(x.title)}</span>${chip(c, esc(l))}
      ${x.future || x.status === "done" ? "" : `<button class="linkbtn" data-oastep="${esc(x.key)}">Add</button>`}</div>`}).join("")}</div>`;
  const stepsPanel = panelC({title: "1 · The data it uses", sub: "add what is missing; everything stays saved on this PC", body: {type: "raw"}}).replace("\u0000BODY\u0000", () => steps);
  // 2. what to check
  const storeSel = `<select id="oa-store" aria-label="Store">${storeRole() ? "" : `<option value="all" ${OA.store === "all" ? "selected" : ""}>All stores (district view)</option>`}${b.stores.map(s => `<option value="${esc(s.code)}" ${OA.store === s.code ? "selected" : ""}>${esc(s.name)} (${esc(s.code)})</option>`).join("")}</select>`;
  const supSel = `<select id="oa-sup" aria-label="Supplier"><option value="">All suppliers</option>${M.suppliers.map(s => `<option value="${esc(s.code)}" ${OA.supplier === s.code ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select>`;
  const modeTabs = `<div class="tabs"><button data-oamode="suggest" aria-pressed="${OA.mode === "suggest"}">Suggest an order</button><button data-oamode="check" aria-pressed="${OA.mode === "check"}">Check my order</button></div>`;
  const form = OA.mode === "suggest"
    ? `<div class="oa-form"><label class="an-lbl" for="oa-store">Store</label>${storeSel}<label class="an-lbl" for="oa-sup">Supplier</label>${supSel}
       <button class="primary" data-oarun="1" ${OA.busy ? "disabled" : ""}>${OA.busy ? '<span class="spin sm"></span> Working…' : "Build the suggested order"}</button></div>
       <p class="muted" style="font-size:12.5px;margin:6px 0 0">Uses the department / section chosen at the top. Every line says how much, why, and whether another store can send it instead.</p>`
    : `<div class="oa-form"><label class="an-lbl" for="oa-store">Store</label>${storeSel}<button class="primary" data-oarun="1" ${OA.busy ? "disabled" : ""}>${OA.busy ? '<span class="spin sm"></span> Checking…' : "Check this order"}</button></div>
       <label class="sr" for="oa-text">Order lines</label><textarea id="oa-text" class="oa-text" placeholder="Paste the order from Excel: item code and quantity per line (a Store column is optional).&#10;Item&#9;Qty&#10;178986&#9;120&#10;178987&#9;48">${esc(OA.text)}</textarea>`;
  const formPanel = panelC({title: "2 · What to check", sub: "", body: {type: "raw"}}).replace("\u0000BODY\u0000", () => `<div class="row" style="margin-bottom:8px">${modeTabs}</div>${form}`);
  let h = head({title: t("advisor"), sub: "Before an LPO: order or not, how much, or transfer from another store first."}) + stepsPanel + formPanel;
  const d = OA.data;
  if (d && d.error) h += errBox(d, false);
  else if (d) h += advisorResults(d);
  h += advisorRules();
  return h;
}

function advisorResults(d) {
  const s = d.summary; let h = "";
  for (const n of d.notes || []) h += `<div class="banner">ⓘ ${esc(n)}</div>`;
  const k = (l, v, sub, st) => `<div class="kpi"${st ? ` style="box-shadow:var(--shadow),inset 0 3px 0 var(--${st})"` : ""}><div class="kpi-l"><span>${esc(l)}</span></div><div class="kpi-top"><div class="kpi-v num">${bd(v)}</div></div><div class="kpi-s">${esc(sub || "")}</div></div>`;
  h += `<div class="kpis">` + (d.check
    ? k("Your order", oaMoney(s.proposed_value), `${fmtN(s.lines)} lines`) + k("Suggested", oaMoney(s.value), `${fmtN(s.order)} lines to order`)
      + k("Difference", oaMoney(s.saving), s.saving >= 0 ? "less stock tied up" : "more needed", s.saving > 0 ? "good" : "warn")
      + k("Lines to change", fmtN(s.remove + s.reduce + s.increase), `${s.remove} remove · ${s.reduce} reduce · ${s.increase} increase`, "warn")
      + k("Transfer instead", fmtN(s.ist), oaMoney(s.ist_value) + " from other stores", "good")
    : k("Lines to order", fmtN(s.order), oaMoney(s.value), "crit") + k("Transfer instead", fmtN(s.ist), oaMoney(s.ist_value) + " from other stores", "good")
      + k("Don't order", fmtN(s.stop), "blocked, aged or not selling") + k("Enough stock", fmtN(s.none), "no order needed")
      + k("Sales at risk", oaMoney(s.lost_risk), "before the next delivery if not ordered", s.lost_risk ? "crit" : "")) + `</div>`;
  if (d.by_store && d.by_store.length) h += panelC({title: "By store", sub: "district view: click a store to see its lines", body: {type: "table", id: "oa_st",
    cols: [{k: "name", l: "Store", kind: "name"}, {k: "order", l: "Lines to order", kind: "int"}, {k: "value", l: "Order value", kind: "pkr"}, {k: "ist", l: "Transfers", kind: "int"},
      {k: "ist_value", l: "Transfer value", kind: "pkr"}, {k: "stop", l: "Don't order", kind: "int"}, {k: "risk", l: "Sales at risk", kind: "pkr"}],
    rows: d.by_store.map(r => ({...r, k: r.store})), action: {kind: "oastore"}, page_size: 20}});
  const counts = {}; for (const l of d.lines) counts[l.decision] = (counts[l.decision] || 0) + 1;
  const tabs = `<div class="tabs">${[["all", "All"], ...Object.keys(OA_DEC).filter(x => counts[x]).map(x => [x, OA_DEC[x][1]])].map(([x, n]) => `<button data-oafilter="${x}" aria-pressed="${OA.filter === x}">${esc(n)}${x === "all" ? "" : ` (${counts[x]})`}</button>`).join("")}</div>`;
  const rows = d.lines.filter(l => OA.filter === "all" || l.decision === OA.filter).map(l => ({...l,
    dec: {d: OA_DEC[l.decision] ? OA_DEC[l.decision][1] : l.decision}, ver: l.verdict ? {d: OA_VERDICT[l.verdict][1]} : null,
    name: `${l.item} ${l.description || ""}`, sub: `${l.store_name}${l.supplier_name ? " · " + l.supplier_name : ""}`,
    ist: l.ist_qty ? {d: `${fmtN(l.ist_qty)} from ${l.ist_from_name}`} : null, _c: l.decision === "stop" ? "crit" : l.decision === "ist" ? "good" : l.decision === "order" ? "warn" : ""}));
  const cols = [{k: "dec", l: "Decision", kind: "text"}, {k: "name", l: "Item", kind: "name"}, {k: "speed", l: "Sells / day", kind: "num"}, {k: "cover_days", l: "Cover (days)", kind: "num"},
    {k: "on_hand", l: "On hand", kind: "int"}, {k: "on_order", l: "On order", kind: "int"}, {k: "lead", l: "Lead (days)", kind: "num"}];
  if (d.check) cols.push({k: "proposed", l: "Your qty", kind: "int"}, {k: "ver", l: "Verdict", kind: "text"});
  cols.push({k: "qty", l: d.check ? "Suggested" : "Order qty", kind: "int"}, {k: "ist", l: "Transfer", kind: "text"}, {k: "value", l: "Value", kind: "pkr"}, {k: "reason", l: "Why", kind: "text"});
  h += panelC({title: "3 · Line by line", sub: `${fmtN(d.lines.length)} lines${d.truncated ? " (first 5,000)" : ""} · as of ${fdate(d.as_of)}`, body: {type: "raw"}}).replace("\u0000BODY\u0000",
    () => `<div class="row" style="margin-bottom:8px">${tabs}</div><div class="oa-lines">` + tableC({type: "table", id: "oa_lines", cols, rows, action: {kind: "item"}, page_size: 40}) + `</div>`);
  return h;
}

function advisorRules() {
  const M = OA.meta; const r = M.rules;
  if (!OA.rulesOpen) return `<div class="row" style="justify-content:flex-end;margin-top:6px"><button class="pill-btn" data-oarules="1">⚙ Ordering rules</button></div>`;
  const fields = Object.entries(M.help).map(([k, l]) => `<tr><td>${esc(l)}</td><td class="n"><input type="number" step="any" data-oarule="${k}" aria-label="${esc(l)}" value="${esc(OA.draft[k] ?? r[k])}"></td></tr>`).join("");
  const depts = (S.boot ? S.boot.depts : []).map(d => `<tr><td>Maximum days of cover · ${esc(d.name)}</td><td class="n"><input type="number" step="any" data-oamax="${d.code}" aria-label="Maximum cover ${esc(d.name)}" value="${esc((OA.draft.max_cover || {})[d.code] ?? r.max_cover[d.code] ?? r.max_cover_default)}"></td></tr>`).join("");
  return panelC({title: "Ordering rules", sub: "used for every suggestion; change them to match your ordering policy", body: {type: "raw"}}).replace("\u0000BODY\u0000", () =>
    `<div class="tbl-wrap set-tbl" style="max-height:none"><table><tbody>${fields}${depts}
     <tr><td>Transfers only between stores in the same city (aged stock can always move)</td><td class="n"><input type="checkbox" data-oarule="ist_same_city" aria-label="Same city only" ${r.ist_same_city ? "checked" : ""}></td></tr></tbody></table></div>
     <div class="row"><span class="spacer"></span><button class="pill-btn" data-oarules="1">Close</button><button class="primary" data-oasaverules="1">Save rules</button></div>`);
}

document.addEventListener("click", async e => {
  if (S.page !== "advisor") return;
  const g = e.target.closest("[data-oamode],[data-oarun],[data-oafilter],[data-oarules],[data-oasaverules],[data-oastep],[data-oastore]"); if (!g) return;
  const d = g.dataset;
  if (d.oamode) {OA.mode = d.oamode; OA.data = null; render()}
  else if (d.oarun) advisorRun();
  else if (d.oafilter) {OA.filter = d.oafilter; render()}
  else if (d.oarules) {OA.rulesOpen = !OA.rulesOpen; render()}
  else if (d.oastep) {await impCall("import_step", {key: d.oastep}); OA.meta = null; go("import")}
  else if (d.oastore) {OA.store = d.oastore; advisorRun()}
  else if (d.oasaverules) {
    const rules = {...OA.draft}; document.querySelectorAll("[data-oarule]").forEach(x => {rules[x.dataset.oarule] = x.type === "checkbox" ? x.checked : +x.value});
    const mc = {}; document.querySelectorAll("[data-oamax]").forEach(x => {mc[x.dataset.oamax] = +x.value}); rules.max_cover = mc;
    const r = await api("advisor_rules", {rules}); OA.meta.rules = r.rules; OA.draft = {}; OA.rulesOpen = false; toast("Rules saved"); if (OA.data) advisorRun(); else render();
  }
});
document.addEventListener("change", e => {
  if (S.page !== "advisor") return; const el = e.target;
  if (el.id === "oa-store") {OA.store = el.value; OA.data = null; render()}
  else if (el.id === "oa-sup") {OA.supplier = el.value; OA.data = null; render()}
});
document.addEventListener("input", e => {if (e.target.id === "oa-text") OA.text = e.target.value});
