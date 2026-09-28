/* Stock Compass — Map & logistics: stores, suppliers and warehouses on a real map (street map tiles are fetched once
   and kept on this PC; without internet the country outline, cities and every pin still show). Road km, driving time,
   fuel and vehicle cost for any trip; the transfer (IST) plan from the Order Advisor grouped into vehicle runs;
   open orders on the road from every supplier; where each supplier delivers from. Auto planning, manual changes, what-if. */

const MAP = {tab: "layers", boot: null, busy: false, map: null, el: null, lay: {}, show: {stores: true, suppliers: true, dcs: true, orders: false, transfers: true, cities: true},
  color: "zero_pct", edit: false, pick: null, pickMsg: "",
  trip: {start: "", stops: [], vehicle: "", cartons: "", value: "", back: true, opt: true, res: null, busy: false},
  tr: {data: null, busy: false, excl: new Set(), veh: {}, fuel: 0, maxpct: null, open: null},
  sup: {data: null, busy: false}, place: {kind: "supplier", code: "", name: "", text: "", found: null, busy: false},
  pre: null, set: null, sig: "", dc: {data: null, busy: false, open: null}};
const MAP_METRICS = {zero_pct: ["Zero stock %", -1, "pct"], not_on_order: ["Out of stock, not on order", -1, "int"], lost_day: ["Sales lost / day", -1, "pkr"],
  vs_budget: ["Sales vs budget", 1, "sg"], sales: ["Net sales", 1, "pkr"], dp_value: ["Aged (DP) stock", -1, "pkr"], late_count: ["Late orders", -1, "int"]};
const FMT_N = {H: "Hypermarket", S: "Supermarket", M: "Myli"};
const hm = m => {m = Math.round(m || 0); return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`};
const km = v => v == null ? "—" : `${(+v).toLocaleString("en-US", {maximumFractionDigits: v < 10 ? 1 : 0})} km`;

async function mapLoad(force) {
  const sig = JSON.stringify(ctx());
  if (!MAP.boot || force || MAP.sig !== sig) {MAP.sig = sig; MAP.busy = true; render(); try {MAP.boot = await api("map_boot")} catch (e) {MAP.boot = {error: String(e)}} MAP.busy = false; MAP.set = null}
  render(); mapDraw();
}
const placeKey = p => p.kind + ":" + p.code;
const places = () => (MAP.boot && MAP.boot.places) || [];
const findPlace = k => places().find(p => placeKey(p) === k);

/* ---------------- page ---------------- */
function mapPage() {
  const B = MAP.boot;
  const hd = head({title: t("map"), sub: "Stores, suppliers and warehouses on the map: road km, time, fuel and cost for every trip, transfer and order."});
  if (!B || MAP.busy && !B) return hd + loadingBox();
  if (B.error) return hd + errBox(B, true);
  const tabs = [["layers", "Map"], ["dc", "DC deliveries"], ["trip", "Trip"], ["transfers", "Transfers (IST)"], ["suppliers", "Suppliers & orders"], ["places", "Locations"], ["costs", "Costs & vehicles"]];
  const side = `<div class="tabs map-tabs">${tabs.map(([k, n]) => `<button data-mtab="${k}" aria-pressed="${MAP.tab === k}">${esc(n)}</button>`).join("")}</div><div class="map-side-body">${mapSide()}</div>`;
  const pick = MAP.pick ? `<div class="map-pick">📍 ${esc(MAP.pickMsg || "Click on the map")} <button class="pill-btn" data-mpickcancel="1">Cancel</button></div>` : "";
  return hd + `<div class="map-wrap"><div class="map-main"><div id="map-slot" class="map-slot"></div>${pick}${mapLegend()}</div><aside class="map-side panel">${side}</aside></div>`;
}
function mapLegend() {
  const m = MAP_METRICS[MAP.color];
  return `<div class="map-legend"><b>Stores: ${esc(m[0])}</b><span><i class="lg good"></i>best third</span><span><i class="lg warn"></i>middle</span><span><i class="lg crit"></i>worst third</span><span><i class="lg none"></i>no data</span>
  <span><i class="lg sup"></i>supplier</span><span><i class="lg dcs"></i>DC</span><span><i class="lg dc"></i>warehouse</span><span class="muted">○ approximate pin</span></div>`;
}
function mapSide() {
  switch (MAP.tab) {
    case "trip": return mapTripHTML();
    case "transfers": return mapTransfersHTML();
    case "suppliers": return mapSuppliersHTML();
    case "places": return mapPlacesHTML();
    case "costs": return mapCostsHTML();
    case "dc": return mapDcHTML();
    default: return mapLayersHTML();
  }
}
function mapLayersHTML() {
  const B = MAP.boot; const st = places().filter(p => p.kind === "store"), su = places().filter(p => p.kind === "supplier");
  const cb = (k, l) => `<label class="map-cb"><input type="checkbox" data-mshow="${k}" ${MAP.show[k] ? "checked" : ""}> ${esc(l)}</label>`;
  const ranked = (B.stores || []).map(s => ({...s, val: (s.v || {})[MAP.color]})).filter(s => s.val != null).sort((a, b) => (b.val - a.val) * MAP_METRICS[MAP.color][1]);
  const f = MAP_METRICS[MAP.color][2];
  return `<div class="map-sec"><label class="an-lbl" for="m-color">Colour stores by</label><select id="m-color">${Object.entries(MAP_METRICS).map(([k, v]) => `<option value="${k}" ${MAP.color === k ? "selected" : ""}>${esc(v[0])}</option>`).join("")}</select></div>
  <div class="map-sec">${cb("stores", "Stores")}${cb("suppliers", "Suppliers")}${cb("dcs", "Warehouses / other places")}${cb("orders", "Open orders on the road")}${cb("transfers", "Transfer plan (IST)")}${cb("cities", "City names")}</div>
  <div class="map-sec map-stat"><div><b>${st.length}</b> stores <span class="muted">(${st.filter(p => p.exact).length} exact pins)</span></div><div><b>${su.length}</b> of ${fmtN((B.suppliers || []).length)} suppliers located</div>
    <div><b>${fmtN(B.tiles.tiles)}</b> map tiles kept on this PC <span class="muted">(${B.tiles.mb} MB)</span></div></div>
  <div class="map-sec"><label class="map-cb"><input type="checkbox" data-medit="1" ${MAP.edit ? "checked" : ""}> Move pins (drag a store or supplier to its exact spot)</label></div>
  ${ranked.length ? `<div class="map-sec"><b style="font-size:13px">${esc(MAP_METRICS[MAP.color][0])}, best to worst</b><div class="map-rank">${ranked.map((s, i) => `<button class="map-rrow" data-mfly="${esc(placeKey(s))}"><span>${i + 1}. ${esc(s.name)}</span><b>${bd(fmtV(s.val, f))}</b></button>`).join("")}</div></div>` : `<p class="muted" style="font-size:12.5px">No ${esc(MAP_METRICS[MAP.color][0].toLowerCase())} numbers yet: add the reports and the stores are coloured by them.</p>`}`;
}
function placeOptions(sel, withPick) {
  const g = {store: [], supplier: [], dc: [], other: []};
  for (const p of places()) (g[p.kind] || g.other).push(p);
  return `${withPick ? `<option value="">Choose…</option>` : ""}${Object.entries(g).filter(([, v]) => v.length).map(([k, v]) => `<optgroup label="${esc((MAP.boot.kinds || {})[k] || k)}">${v.map(p => `<option value="${esc(placeKey(p))}" ${sel === placeKey(p) ? "selected" : ""}>${esc(p.name)}${p.city ? " · " + esc(p.city) : ""}</option>`).join("")}</optgroup>`).join("")}`;
}
function vehOptions(sel, auto) {
  const vs = MAP.boot.settings.vehicles;
  return (auto ? `<option value="">Automatic (smallest that fits)</option>` : "") + vs.map(v => `<option value="${esc(v.key)}" ${sel === v.key ? "selected" : ""}>${esc(v.name)} · ${fmtN(v.cap_cartons)} cartons</option>`).join("");
}
function mapTripHTML() {
  const T = MAP.trip;
  const stops = T.stops.map((s, i) => `<div class="map-stop"><span class="step-n sm">${i + 1}</span><span>${esc(s.name)}</span><button class="linkbtn" data-mstopdel="${i}" aria-label="Remove stop">×</button></div>`).join("");
  let res = "";
  const R = T.res;
  if (T.busy) res = loadingBox();
  else if (R && R.error) res = `<div class="errbox">${esc(R.error)}</div>`;
  else if (R) {
    const k = (l, v, sub) => `<div class="mk"><span>${esc(l)}</span><b>${bd(v)}</b>${sub ? `<small>${esc(sub)}</small>` : ""}</div>`;
    res = `<div class="mk-grid">${k("Distance", km(R.km), R.source === "estimate" ? "estimate (no road route yet)" : "road route")}${k("Driving time", hm(R.minutes), `+ ${fmtN(MAP.boot.settings.stop_minutes)} min per stop · ${hm(R.hours * 60)} in all`)}
      ${k("Fuel", `${fmtN(R.litres)} L`, `${esc(fmtV(R.fuel_price, "num"))} PKR/L`)}${k("Fuel cost", pkr(R.fuel_pkr), "")}${k("Driver & helper", pkr(R.crew_pkr), "")}${k("Total cost", pkr(R.total), `${pkr(R.per_km)}/km${R.trips > 1 ? ` · ${R.trips} trips` : ""}`)}
      ${R.per_carton != null ? k("Per carton", pkr(R.per_carton), "") : ""}${R.cost_pct != null ? k("Cost vs value", pc(R.cost_pct), R.cost_pct <= MAP.boot.settings.max_cost_pct ? "worth it" : "expensive for this value") : ""}</div>
      <div class="muted" style="font-size:12px;margin:4px 0">${esc(R.vehicle_name)}${R.days > 1 ? ` · about ${R.days} working days` : ""}</div>
      ${R.legs.length ? `<div class="tbl-wrap"><table><thead><tr><th class="nosort">From</th><th class="nosort">To</th><th class="n nosort">km</th><th class="n nosort">Time</th></tr></thead><tbody>${R.legs.map(l => `<tr><td>${esc(l.frm)}</td><td>${esc(l.to)}</td><td class="n">${fmtN(l.km)}</td><td class="n">${esc(hm(l.minutes))}</td></tr>`).join("")}</tbody></table></div>` : ""}`;
  }
  const dcp = places().find(p => p.dc);
  return `<p class="muted map-help">Any trip: from a store, supplier or warehouse to one or more stops. Pick from the list or click on the map.</p>
  <div class="map-sec"><label class="an-lbl" for="m-start">From</label><div class="row"><select id="m-start" style="flex:1">${placeOptions(T.start, true)}</select><button class="pill-btn" data-mpick="start" title="Pick a point on the map">📍</button>${dcp ? `<button class="pill-btn" data-mfromdc="1" title="Start at the distribution centre (${esc(dcp.name)})">DC</button>` : ""}</div>
   ${T.startPt ? `<div class="muted" style="font-size:12px">${esc(T.startPt.name)}</div>` : ""}</div>
  <div class="map-sec"><label class="an-lbl" for="m-addstop">Stops</label>${stops || `<div class="muted" style="font-size:12.5px">No stops yet.</div>`}
   <div class="row"><select id="m-addstop" style="flex:1">${placeOptions("", true)}</select><button class="pill-btn" data-mpick="stop" title="Pick a stop on the map">📍</button></div></div>
  <div class="map-sec map-form2"><label class="an-lbl" for="m-veh">Vehicle</label><select id="m-veh">${vehOptions(T.vehicle, true)}</select>
   <label class="an-lbl" for="m-cart">Load (cartons)</label><input id="m-cart" type="number" min="0" value="${esc(T.cartons)}" placeholder="optional">
   <label class="an-lbl" for="m-val">Value of the goods (PKR)</label><input id="m-val" type="number" min="0" value="${esc(T.value)}" placeholder="optional"></div>
  <div class="map-sec"><label class="map-cb"><input type="checkbox" id="m-back" ${T.back ? "checked" : ""}> Round trip (back to the start)</label><label class="map-cb"><input type="checkbox" id="m-opt" ${T.opt ? "checked" : ""}> Best order of stops (automatic)</label></div>
  <div class="row"><button class="primary" data-mtrip="1" ${T.busy ? "disabled" : ""}>Work out the trip</button><button class="pill-btn" data-mtripclear="1">Clear</button></div>${res}`;
}
function trRuns() {
  const D = MAP.tr.data; if (!D) return [];
  const f = 1 + (MAP.tr.fuel || 0) / 100; const maxp = MAP.tr.maxpct ?? D.max_cost_pct;
  return D.runs.map(r => {const total = r.fuel_pkr * f + r.crew_pkr + r.fixed_pkr * r.trips; const pct = r.value ? total / r.value * 100 : null;
    return {...r, total_w: total, pct_w: pct, worth_w: pct != null && pct <= maxp, on: !MAP.tr.excl.has(r.id)}});
}
function mapTransfersHTML() {
  const T = MAP.tr, D = T.data;
  const intro = `<p class="muted map-help">The Order Advisor's transfers between stores, grouped into vehicle runs (one sending store to the stores of one city), with km, time, fuel and cost. Untick a run or change its vehicle to plan by hand; move the fuel price to see what-if.</p>`;
  if (T.busy) return intro + loadingBox();
  if (!D) return intro + `<button class="primary" data-mtrans="1">Build the transfer plan</button><p class="muted" style="font-size:12px">Uses the department / section chosen at the top.</p>`;
  if (D.error) return intro + errBox(D, false);
  if (!D.runs.length) return intro + emptyBox("No transfers suggested", "The Order Advisor found no store with stock to spare for another store (needs stock on hand and item sales).") + `<button class="pill-btn" data-mtrans="1">Build again</button>`;
  const runs = trRuns(), on = runs.filter(r => r.on);
  const sum = k => on.reduce((a, r) => a + (r[k] || 0), 0);
  const cost = sum("total_w"), val = sum("value");
  const k = (l, v, sub) => `<div class="mk"><span>${esc(l)}</span><b>${bd(v)}</b>${sub ? `<small>${esc(sub)}</small>` : ""}</div>`;
  const tot = `<div class="mk-grid">${k("Runs", `${on.length} of ${runs.length}`, `${sum("trips")} trips`)}${k("Distance", km(sum("km")), hm(sum("minutes")) + " driving")}${k("Fuel", `${fmtN(sum("litres"))} L`, pkr(sum("fuel_pkr") * (1 + (T.fuel || 0) / 100)))}
    ${k("Total cost", pkr(cost), val ? pc(cost / val * 100) + " of the value moved" : "")}${k("Value moved", pkr(val), `${fmtN(sum("cartons"))} cartons`)}${k("Sales protected", pkr(sum("risk")), "at risk before the next delivery")}</div>`;
  const whatif = `<div class="map-sec map-form2"><label class="an-lbl" for="m-fuelw">Fuel price change: <b id="m-fuelw-v">${T.fuel > 0 ? "+" : ""}${T.fuel}%</b></label><input id="m-fuelw" type="range" min="-30" max="60" step="5" value="${T.fuel}">
    <label class="an-lbl" for="m-maxp">Worth it when cost is at most (% of value)</label><input id="m-maxp" type="number" step="0.5" min="0" value="${esc(T.maxpct ?? D.max_cost_pct)}"></div>`;
  const rows = runs.map(r => `<div class="map-run ${r.on ? "" : "off"} ${T.open === r.id ? "open" : ""}">
    <div class="row" style="gap:6px"><input type="checkbox" data-mrun="${esc(r.id)}" ${r.on ? "checked" : ""} aria-label="Include ${esc(r.src_name)} to ${esc(r.city)}">
     <button class="linkbtn map-runt" data-mrunopen="${esc(r.id)}"><b>${esc(r.src_name)}</b> → ${esc(r.city)} <span class="muted">(${r.stops.length} store${r.stops.length > 1 ? "s" : ""})</span></button><span class="spacer"></span>${chip(r.worth_w ? "good" : "warn", r.worth_w ? "Worth it" : "Costly")}</div>
    <div class="map-run-n"><span>${fmtN(r.cartons)} ctn</span><span>${km(r.km)}</span><span>${esc(hm(r.minutes))}</span><span>${pkr(r.total_w)}</span><span>${pkr(r.value)} value</span><span>${r.pct_w == null ? "" : pc(r.pct_w)}</span></div>
    <label class="sr" for="m-rv-${esc(r.id)}">Vehicle</label><select id="m-rv-${esc(r.id)}" data-mrunveh="${esc(r.id)}">${vehOptions(T.veh[r.id] || "", true)}</select>
    <span class="muted" style="font-size:11.5px">${esc(r.vehicle_name)} · ${r.trips} trip${r.trips > 1 ? "s" : ""} · ${Math.round(r.fill)}% full${r.route_source === "estimate" ? " · km estimated" : ""}</span>
    ${T.open === r.id ? `<div class="map-run-d">${r.stops.map(s => `<div><b>${esc(s.name)}</b> · ${s.lines} lines · ${fmtN(s.cartons)} ctn · ${pkr(s.value)}<div class="muted" style="font-size:11.5px">${s.items.slice(0, 8).map(i => `${esc(i.item)} ${esc((i.description || "").slice(0, 26))} ×${fmtN(i.qty)}`).join(" · ")}${s.items.length > 8 ? " …" : ""}</div></div>`).join("")}</div>` : ""}</div>`).join("");
  return intro + tot + whatif + `<div class="row"><button class="primary" data-mtrans="1">Recalculate</button><button class="pill-btn" data-mtransx="1">⤓ Export plan</button><span class="spacer"></span><span class="muted" style="font-size:12px">as of ${esc(fdate(D.as_of))}${D.estimated ? " · some km estimated" : ""}</span></div><div class="map-runs">${rows}</div>`;
}
function mapSuppliersHTML() {
  const Sd = MAP.sup;
  const intro = `<p class="muted map-help">Open orders from each supplier to each store (from the LPO list), late ones in red on the map, and how far and how fast each supplier really delivers. Locate the biggest suppliers first.</p>`;
  if (Sd.busy) return intro + loadingBox();
  if (!Sd.data) return intro + `<button class="primary" data-msup="1">Show suppliers and open orders</button>`;
  if (Sd.data.error) return intro + errBox(Sd.data, false);
  const R = Sd.data.road, L = Sd.data.suppliers;
  const k = (l, v, sub) => `<div class="mk"><span>${esc(l)}</span><b>${bd(v)}</b>${sub ? `<small>${esc(sub)}</small>` : ""}</div>`;
  const late = R.lines.reduce((a, l) => a + l.late, 0);
  let h = intro + `<div class="mk-grid">${k("Open orders", fmtN(R.open_total), pkr(R.open_value))}${k("On the map", fmtN(R.lines.reduce((a, l) => a + l.n, 0)), "orders with a located supplier")}${k("Late (on map)", fmtN(late), "")}${k("Suppliers located", `${L.filter(s => s.located).length} of ${L.length}`, "with orders")}</div>`;
  if (R.unlocated.length) h += `<div class="map-sec"><b style="font-size:13px">Locate these first (biggest open orders)</b>${R.unlocated.slice(0, 12).map(u => `<div class="map-rrow"><span>${esc(u.name)} <span class="muted">${fmtN(u.n)} open · ${pkr(u.value)}${u.late ? ` · ${u.late} late` : ""}</span></span><button class="linkbtn" data-mlocate="${esc(u.supplier)}">Locate</button></div>`).join("")}</div>`;
  h += tableC({type: "table", id: "map_sup", cols: [{k: "name", l: "Supplier", kind: "name"}, {k: "city", l: "Delivers from", kind: "text"}, {k: "open", l: "Open", kind: "int"}, {k: "late_pct", l: "Late %", kind: "pct"},
    {k: "lead_days", l: "Lead (days)", kind: "num"}, {k: "avg_km", l: "Avg km to stores", kind: "int"}, {k: "dc_km", l: "km to DC", kind: "int"}, {k: "stores", l: "Stores", kind: "int"}],
    rows: L.map(s => ({...s, city: s.located ? (s.city || "") + (s.exact ? "" : " (approx.)") : "— not located", _c: s.late ? "warn" : "", k: s.supplier})), action: {kind: "mapsup"}, page_size: 15});
  return h;
}
function mapPlacesHTML() {
  const P = MAP.place; const B = MAP.boot;
  const supSel = P.kind === "supplier" ? `<label class="an-lbl" for="m-psup">Supplier</label><input id="m-psup" list="m-psups" value="${esc(P.name ? `${P.name} — ${P.code}` : P.code)}" placeholder="type a supplier name or code"><datalist id="m-psups">${(B.suppliers || []).slice(0, 3000).map(s => `<option value="${esc(s.name)} — ${esc(s.code)}"></option>`).join("")}</datalist>`
    : P.kind === "store" ? `<label class="an-lbl" for="m-pstore">Store</label><select id="m-pstore">${(S.boot ? S.boot.stores : []).map(s => `<option value="${esc(s.code)}" ${P.code === s.code ? "selected" : ""}>${esc(s.name)} (${esc(s.code)})</option>`).join("")}</select>`
    : `<label class="an-lbl" for="m-pname">Name</label><input id="m-pname" value="${esc(P.name)}" placeholder="e.g. Lahore DC, Karachi warehouse">`;
  const list = places().filter(p => p.kind !== "store" || true);
  return `<p class="muted map-help">Where each supplier delivers from, where warehouses are, and exact store pins. Paste a Google Maps link, type coordinates or an address, pick on the map, or import a supplier list with addresses (Add reports) and they are placed by themselves.</p>
  <div class="map-sec map-form2"><label class="an-lbl" for="m-pkind">Kind</label><select id="m-pkind">${Object.entries(B.kinds).map(([k, n]) => `<option value="${k}" ${P.kind === k ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>${supSel}
   <label class="an-lbl" for="m-ptext">Address, Google Maps link or coordinates</label><input id="m-ptext" value="${esc(P.text)}" placeholder="e.g. 31.4712, 74.3553 or a maps link or 'Sundar Industrial Estate, Lahore'"></div>
  <div class="row"><button class="pill-btn" data-mfind="1" ${P.busy ? "disabled" : ""}>Find</button><button class="pill-btn" data-mpick="place">📍 Pick on map</button><span class="spacer"></span><button class="primary" data-mpsave="1" ${P.found ? "" : "disabled"}>Save location</button></div>
  ${P.found ? `<div class="note" style="margin-top:6px">${P.found.error ? esc(P.found.error) : `Found: ${fmtV(P.found.lat, "num")}, ${fmtV(P.found.lng, "num")} · ${esc(P.found.how || "")}${P.found.found ? "<br>" + esc(P.found.found) : ""}`}</div>` : ""}
  <div class="map-sec"><b style="font-size:13px">Saved places</b><div class="map-rank">${list.map(p => `<div class="map-rrow"><button class="linkbtn" data-mfly="${esc(placeKey(p))}">${esc(p.name)}</button><span class="muted" style="font-size:11.5px">${esc((B.kinds[p.kind] || p.kind))} · ${esc(p.city || "")} · ${p.exact ? "exact" : "approx."}</span>${p.kind === "store" && !String(p.source).startsWith("approx") || p.kind !== "store" ? `<button class="linkbtn" data-mpdel="${esc(placeKey(p))}" aria-label="Remove">×</button>` : ""}</div>`).join("")}</div></div>`;
}
function mapCostsHTML() {
  const s = MAP.set || (MAP.set = JSON.parse(JSON.stringify(MAP.boot.settings)));
  const f = s.fuel; const P = MAP.pre;
  const num = (id, l, v, step = "any") => `<label class="an-lbl" for="${id}">${esc(l)}</label><input id="${id}" data-mset="${id.slice(4)}" type="number" step="${step}" value="${esc(v)}">`;
  const vi = (i, k, l, type = "number") => `<label class="an-lbl" for="m-v${i}-${k}">${esc(l)}</label><input id="m-v${i}-${k}" type="${type}" step="any" data-mveh="${i}|${k}" value="${esc(s.vehicles[i][k])}">`;
  const veh = s.vehicles.map((v, i) => `<div class="map-veh">${vi(i, "name", "Vehicle", "text")}<div class="map-veh-g">${vi(i, "cap_cartons", "Cartons")}${vi(i, "km_per_l", "km per litre")}
    <label class="an-lbl" for="m-v${i}-fuel">Fuel</label><select id="m-v${i}-fuel" data-mveh="${i}|fuel"><option value="diesel" ${v.fuel === "diesel" ? "selected" : ""}>Diesel</option><option value="petrol" ${v.fuel === "petrol" ? "selected" : ""}>Petrol</option></select>
    ${vi(i, "crew_cost_hr", "Driver + helper PKR/h")}${vi(i, "fixed_trip", "Fixed PKR per trip")}</div></div>`).join("");
  return `<div class="map-sec"><b style="font-size:13px">Fuel prices (PKR per litre)</b><div class="map-form2">${num("m-s-fuel.petrol", "Petrol", f.petrol)}${num("m-s-fuel.diesel", "Diesel (HSD)", f.diesel)}</div>
    <div class="row"><span class="muted" style="font-size:12px">${f.as_of ? `as of ${esc(fdate(f.as_of))} · ${esc(f.source || "")}` : esc(f.source || "")}</span><span class="spacer"></span><button class="pill-btn" data-mfuel="1">⟳ Fetch latest</button></div></div>
  <div class="map-sec"><b style="font-size:13px">Vehicles</b>${veh}</div>
  <div class="map-sec map-form2"><label class="an-lbl" for="m-s-dc_store">Distribution centre (DC) store</label><select id="m-s-dc_store" data-mset="dc_store">${(S.boot ? S.boot.stores : []).filter(x => x.format !== "M").map(x => `<option value="${esc(x.code)}" ${String(s.dc_store) === x.code ? "selected" : ""}>${esc(x.name)} (${esc(x.code)})</option>`).join("")}</select>
    <label class="an-lbl" for="m-s-dc_vehicle_city">DC truck in the same city</label><select id="m-s-dc_vehicle_city" data-mset="dc_vehicle_city">${vehOptions(s.dc_vehicle_city, false)}</select>
    <label class="an-lbl" for="m-s-dc_vehicle_intercity">DC truck to other cities</label><select id="m-s-dc_vehicle_intercity" data-mset="dc_vehicle_intercity">${vehOptions(s.dc_vehicle_intercity, false)}</select></div>
  <div class="map-sec map-form2">${num("m-s-city_kmh", "Truck speed in the city (km/h)", s.city_kmh)}${num("m-s-highway_kmh", "Truck speed on highways (km/h)", s.highway_kmh)}${num("m-s-stop_minutes", "Minutes per stop (unloading)", s.stop_minutes)}
    ${num("m-s-working_hours", "Driving hours per day", s.working_hours)}${num("m-s-max_cost_pct", "Transfer worth it up to (% of value)", s.max_cost_pct)}${num("m-s-truck_factor", "Truck time vs car time on road routes (×)", s.truck_factor)}</div>
  <div class="map-sec"><label class="map-cb"><input type="checkbox" data-mset="online" ${s.online ? "checked" : ""}> Use the internet for street maps, road routes and addresses (kept on this PC after)</label>
    <label class="an-lbl" for="m-s-router">Road route service (OSRM; empty = public OpenStreetMap router)</label><input id="m-s-router" data-mset="router" value="${esc(s.router || "")}" placeholder="https://router.project-osrm.org">
    <label class="an-lbl" for="m-s-tile_server">Street map tiles (empty = OpenStreetMap)</label><input id="m-s-tile_server" data-mset="tile_server" value="${esc(s.tile_server || "")}" placeholder="https://tile.openstreetmap.org/{z}/{x}/{y}.png"></div>
  <div class="row"><span class="spacer"></span><button class="primary" data-msave="1">Save</button></div>
  <div class="map-sec"><b style="font-size:13px">Offline map</b><p class="muted" style="font-size:12.5px;margin:4px 0">Keep the map of Pakistan and the streets around every store and supplier on this PC, for working without internet.</p>
    ${P && P.total ? `<div class="pbar"><i style="width:${Math.round(P.done / P.total * 100)}%"></i></div><div class="muted" style="font-size:12px">${fmtN(P.done)} of ${fmtN(P.total)} tiles${P.running ? "…" : " · done"} ${P.msg ? "· " + esc(P.msg) : ""}</div>` : ""}
    <button class="pill-btn" data-mprefetch="1" ${P && P.running ? "disabled" : ""}>⤓ Download the offline map</button></div>`;
}

/* ---------------- the Leaflet map (kept alive between screen refreshes) ---------------- */
function mapEnsure() {
  if (MAP.map || typeof L === "undefined") return;
  MAP.el = document.createElement("div"); MAP.el.className = "sc-map";
  const m = L.map(MAP.el, {zoomControl: true, preferCanvas: true, minZoom: 5, maxZoom: 17, worldCopyJump: false,
    maxBounds: [[18, 55], [41, 86]], maxBoundsViscosity: 0.8}).setView([30.3, 70.2], 5);
  MAP.map = m;
  if (typeof MAP_OUTLINE !== "undefined") L.geoJSON(MAP_OUTLINE, {style: f => ({color: f.properties.main ? "#8a6a3a" : "#b9ab94", weight: f.properties.main ? 1.6 : 0.8, fillColor: f.properties.main ? "#f6efe3" : "#ece7df", fillOpacity: 1}), interactive: false}).addTo(m);
  const Tiles = L.GridLayer.extend({createTile(c, done) {
    const img = document.createElement("img"); img.alt = ""; img.setAttribute("role", "presentation");
    api("map_tile", {z: c.z, x: c.x, y: c.y}).then(r => {if (r && r.url) {img.onload = () => done(null, img); img.onerror = () => done(null, img); img.src = r.url} else done(null, img)}).catch(() => done(null, img));
    return img;
  }});
  new Tiles({attribution: "© OpenStreetMap contributors", maxZoom: 17, keepBuffer: 2, updateWhenIdle: true}).addTo(m);
  m.attributionControl.setPrefix("Leaflet");
  m.on("click", e => {if (MAP.pick) {const cb = MAP.pick; MAP.pick = null; cb(e.latlng)}});
  m.on("zoomend", () => {mapCities(); MAP.el.classList.toggle("zoom-low", m.getZoom() < 9)});
  MAP.el.classList.add("zoom-low");
  MAP.fit = true;
  for (const k of ["cities", "stores", "suppliers", "dcs", "orders", "transfers", "trip", "found"]) MAP.lay[k] = L.layerGroup().addTo(m);
}
function mapAttach() {
  if (S.page !== "map") return;
  const slot = document.getElementById("map-slot"); if (!slot) return;
  mapEnsure(); if (!MAP.el) {slot.innerHTML = `<div class="errbox">The map library did not load.</div>`; return}
  if (MAP.el.parentNode !== slot) {slot.appendChild(MAP.el); setTimeout(() => {if (!MAP.map) return; MAP.map.invalidateSize(); mapFit()}, 0)}
  MAP.el.classList.toggle("picking", !!MAP.pick);
}
function mapCities() {
  const g = MAP.lay.cities; if (!g) return; g.clearLayers(); if (!MAP.show.cities) return;
  const z = MAP.map.getZoom(); const big = ["Lahore", "Karachi", "Islamabad", "Rawalpindi", "Faisalabad", "Multan", "Peshawar", "Quetta", "Gujranwala", "Sialkot", "Hyderabad", "Bahawalpur", "Sukkur"];
  for (const [n, p] of Object.entries((MAP.boot && MAP.boot.cities) || {})) {
    if (z < 8 && !big.includes(n)) continue;
    L.circleMarker(p, {radius: 2.5, color: "#6b5a44", weight: 1, fillOpacity: 1, interactive: false}).bindTooltip(n, {permanent: true, direction: "right", className: "city-lbl", offset: [4, 0]}).addTo(g);
  }
}
function colorFor(val, all, dir) {
  if (val == null || !all.length) return "none";
  const s = [...all].sort((a, b) => (a - b) * dir); const i = s.indexOf(val); const q = i / Math.max(1, s.length - 1);
  return q >= 0.66 ? "good" : q >= 0.33 ? "warn" : "crit";
}
function pinIcon(cls, label, exact) {return L.divIcon({className: "", html: `<span class="pin ${cls}${exact ? "" : " approx"}">${label ? `<i>${esc(label)}</i>` : ""}</span>`, iconSize: [18, 18], iconAnchor: [9, 9]})}
function mapDraw() {
  if (S.page !== "map" || !MAP.boot || MAP.boot.error) return;
  mapAttach(); if (!MAP.map) return;
  const B = MAP.boot; const [lbl, dir, f] = MAP_METRICS[MAP.color];
  for (const k of ["stores", "suppliers", "dcs", "orders", "transfers"]) MAP.lay[k].clearLayers();
  mapCities();
  if (MAP.show.stores) {
    const vals = (B.stores || []).map(s => (s.v || {})[MAP.color]).filter(v => v != null);
    for (const s of B.stores || []) {
      const v = (s.v || {})[MAP.color]; const c = colorFor(v, vals, dir);
      const mk = L.marker([s.lat, s.lng], {icon: pinIcon(`st ${c} f${s.format}${s.dc ? " isdc" : ""}`, s.dc ? "DC " + s.code : s.format === "M" ? "" : s.code, s.exact), draggable: MAP.edit, title: s.name, riseOnHover: true});
      const v2 = s.v || {};
      mk.bindTooltip(`<b>${esc(s.name)}</b> (${esc(s.code)}) · ${esc(FMT_N[s.format] || "")}${s.dc ? "<br><b>Distribution centre (DC)</b>" : ""}<br>${esc(lbl)}: <b>${fmtV(v, f)}</b>${v2.sales != null ? `<br>Net sales ${pkr(v2.sales)}${v2.vs_budget != null ? ` · ${sg(v2.vs_budget)} vs budget` : ""}` : ""}${v2.not_on_order != null ? `<br>${fmtN(v2.not_on_order)} out of stock, not on order` : ""}${v2.dp_value != null ? `<br>Aged stock ${pkr(v2.dp_value)}` : ""}<br><span style="opacity:.8">${esc(s.exact ? "exact pin" : s.source)}</span>`, {direction: "top", offset: [0, -8]});
      mk.on("click", () => {if (MAP.edit) return; mapStorePopup(s, mk)});
      mk.on("dragend", e => mapMoved("store", s.code, e.target.getLatLng(), s.name));
      mk.addTo(MAP.lay.stores);
    }
  }
  for (const p of places()) {
    if (p.kind === "store") continue;
    const layer = p.kind === "supplier" ? "suppliers" : "dcs"; if (!MAP.show[layer]) continue;
    const mk = L.marker([p.lat, p.lng], {icon: pinIcon(p.kind === "supplier" ? "sup" : "dc", "", p.exact), draggable: MAP.edit, title: p.name});
    mk.bindTooltip(`<b>${esc(p.name)}</b><br>${esc((B.kinds[p.kind] || p.kind))}${p.city ? " · " + esc(p.city) : ""}<br><span style="opacity:.8">${esc(p.exact ? p.source : "approximate: " + p.source)}</span>`, {direction: "top"});
    mk.on("click", () => {if (!MAP.edit && p.kind === "supplier") openSup(p.code)});
    mk.on("dragend", e => mapMoved(p.kind, p.code, e.target.getLatLng(), p.name));
    mk.addTo(MAP.lay[layer]);
  }
  if (MAP.show.orders && MAP.sup.data && MAP.sup.data.road) {
    const mx = Math.max(1, ...MAP.sup.data.road.lines.map(l => l.value || 0));
    for (const l of MAP.sup.data.road.lines) {
      L.polyline([l.frm, l.to], {color: l.late ? "#c0392b" : "#2a7ab0", weight: 1.5 + 5 * Math.sqrt((l.value || 0) / mx), opacity: .65, dashArray: l.late ? null : "6 5"})
        .bindTooltip(`<b>${esc(l.supplier_name)} → ${esc(l.store)}</b><br>${fmtN(l.n)} open order${l.n > 1 ? "s" : ""} · ${pkr(l.value)}${l.late ? `<br><b style="color:#c0392b">${l.late} late (up to ${l.max_late} days)</b>` : ""}<br>${km(l.km)} · about ${esc(hm(l.minutes))} by road`, {sticky: true}).addTo(MAP.lay.orders);
    }
  }
  if (MAP.show.transfers && MAP.tr.data) {
    for (const r of trRuns()) {
      if (!r.on) continue;
      const sel = MAP.tr.open === r.id;
      L.polyline(r.geometry, {color: r.worth_w ? "#2e8b57" : "#d98c1f", weight: sel ? 6 : 3.5, opacity: sel ? .95 : .75})
        .bindTooltip(`<b>${esc(r.src_name)} → ${esc(r.stops.map(s => s.name).join(", "))}</b><br>${fmtN(r.cartons)} cartons · ${pkr(r.value)}<br>${km(r.km)} · ${esc(hm(r.minutes))} · ${pkr(r.total_w)} (${pc(r.pct_w)})<br>${esc(r.vehicle_name)} × ${r.trips}`, {sticky: true})
        .on("click", () => {MAP.tab = "transfers"; MAP.tr.open = r.id; render(); mapDraw()}).addTo(MAP.lay.transfers);
    }
  }
  mapDrawTrip();
  mapFit();
}
function mapFit() {       // first time: show every store and supplier
  if (!MAP.fit || !MAP.map || !MAP.el.clientHeight || !MAP.boot) return;
  MAP.fit = false; const pts = places().map(p => [p.lat, p.lng]);
  if (pts.length > 1) MAP.map.fitBounds(pts, {padding: [30, 30], maxZoom: 7});
}
function mapDcHTML() {
  const D = MAP.dc; const dcp = places().find(p => p.dc);
  const intro = `<p class="muted map-help">The distribution centre is <b>${esc(dcp ? dcp.name + " (" + dcp.code + ")" : "not set")}</b>. Delivery to every store: road km, driving time, fuel and the cost of a round trip with the usual truck (city truck inside ${esc(dcp && dcp.city || "the DC's city")}, container truck to other cities). Change the DC or the trucks in Costs &amp; vehicles.</p>`;
  if (D.busy) return intro + loadingBox();
  if (!D.data) return intro + `<button class="primary" data-mdc="1">Show DC deliveries</button>`;
  if (D.data.error) return intro + `<div class="errbox">${esc(D.data.error)}</div>`;
  const T = D.data.totals; const k = (l, v, sub) => `<div class="mk"><span>${esc(l)}</span><b>${bd(v)}</b>${sub ? `<small>${esc(sub)}</small>` : ""}</div>`;
  const rows = D.data.rows.map(r => `<button class="map-rrow${D.open === r.store ? " on" : ""}" data-mdcrow="${esc(r.store)}"><span><b>${esc(r.name)}</b> <span class="muted">${esc(r.city || "")} · ${esc(r.vehicle_name)}${r.with_ && r.with_.length ? ` · with ${esc(r.with_.join(", "))}` : ""}</span><br><span class="muted" style="font-size:11.5px">${km(r.km)} one way · ${esc(hm(r.minutes))} · ${fmtN(r.litres)} L round trip${r.source === "estimate" ? " · km estimated" : ""}</span></span><b class="nw">${pkr(r.cost)}</b></button>`).join("");
  return intro + `<div class="mk-grid">${k("Stores served", fmtN(T.stores), "Mylis go with their host store")}${k("One round of deliveries", pkr(T.cost), `${km(T.round_km)} · ${fmtN(T.hours)} h`)}${k("Fuel for one round", pkr(T.fuel_pkr), `diesel ${fmtV(D.data.fuel.diesel, "num")} PKR/L`)}</div>
    <div class="row"><button class="pill-btn" data-mdc="1">Recalculate</button><button class="pill-btn" data-mdcx="1">⤓ Export</button></div><div class="map-rank" style="max-height:none">${rows}</div>`;
}
async function mapDc() {
  MAP.dc.busy = true; render(); mapAttach();
  try {MAP.dc.data = await api("map_dc")} catch (e) {MAP.dc.data = {error: String(e)}}
  MAP.dc.busy = false; render(); mapDraw();
}
function mapDrawTrip() {
  const g = MAP.lay.trip; if (!g) return; g.clearLayers();
  if (MAP.tab === "dc" && MAP.dc.data && MAP.dc.data.rows) for (const r of MAP.dc.data.rows) {
    const sel = MAP.dc.open === r.store;
    L.polyline(r.geometry, {color: "#94481a", weight: sel ? 6 : 2.5, opacity: sel ? .95 : .55, dashArray: sel ? null : "4 6"})
      .bindTooltip(`<b>DC → ${esc(r.name)}</b><br>${km(r.km)} · ${esc(hm(r.minutes))} one way<br>Round trip ${pkr(r.cost)} (${esc(r.vehicle_name)})`, {sticky: true}).addTo(g);
  }
  const R = MAP.trip.res; if (!R || R.error || !R.geometry) return;
  L.polyline(R.geometry, {color: "#5b3fa0", weight: 5, opacity: .85}).addTo(g);
}
function mapStorePopup(s, mk) {
  const v = s.v || {};
  const rows = Object.entries(MAP_METRICS).filter(([k]) => v[k] != null).map(([k, m]) => `<tr><td>${esc(m[0])}</td><td class="n"><b>${fmtV(v[k], m[2])}</b></td></tr>`).join("");
  const el = document.createElement("div"); el.className = "map-pop";
  el.innerHTML = `<b>${esc(s.name)}</b> <span class="muted">${esc(s.code)} · ${esc(FMT_N[s.format] || "")} · ${esc(s.city || "")}</span>${rows ? `<table>${rows}</table>` : `<p class="muted">No numbers yet.</p>`}
    <div class="row" style="gap:6px;margin-top:6px"><button class="pill-btn sm" data-a="open">Open this store</button><button class="pill-btn sm" data-a="trip">Trip from here</button><button class="pill-btn sm" data-a="stop">Add as a stop</button></div>`;
  el.addEventListener("click", ev => {
    const b = ev.target.closest("button[data-a]"); if (!b) return;
    MAP.map.closePopup();
    if (b.dataset.a === "open") {S.f.where = s.code; saveView(); go("home"); return}
    if (b.dataset.a === "trip") {MAP.trip.start = "store:" + s.code; MAP.trip.startPt = null}
    else MAP.trip.stops.push({name: s.name, lat: s.lat, lng: s.lng});
    MAP.tab = "trip"; render(); mapAttach();
  });
  mk.unbindPopup(); mk.bindPopup(el, {maxWidth: 320}).openPopup();
}
async function mapMoved(kind, code, ll, name) {
  const r = await api("map_place", {kind, code, lat: ll.lat, lng: ll.lng, name});
  if (r.error) {toast(r.error); return}
  MAP.boot.places = r.places; if (kind === "store") (MAP.boot.stores || []).forEach(s => {if (s.code === code) {s.lat = ll.lat; s.lng = ll.lng; s.exact = true; s.source = "you"}});
  toast(`${name}: pin saved`); render(); mapDraw();
}
function mapFly(k) {
  const p = findPlace(k); if (!p || !MAP.map) return;
  MAP.map.flyTo([p.lat, p.lng], Math.max(MAP.map.getZoom(), 13), {duration: .6});
}
function mapPickStart(what, msg) {
  MAP.pickMsg = msg; render(); mapAttach();
  MAP.pick = ll => {
    const pt = {name: `Point ${ll.lat.toFixed(4)}, ${ll.lng.toFixed(4)}`, lat: ll.lat, lng: ll.lng};
    if (what === "start") {MAP.trip.start = ""; MAP.trip.startPt = pt}
    else if (what === "stop") MAP.trip.stops.push(pt);
    else if (what === "place") {MAP.place.found = {lat: ll.lat, lng: ll.lng, how: "picked on the map", exact: true}; mapShowFound()}
    render(); mapAttach();
  };
  render(); mapAttach();
}
function mapShowFound() {
  const g = MAP.lay.found; if (!g) return; g.clearLayers(); const F = MAP.place.found;
  if (F && !F.error) {L.circleMarker([F.lat, F.lng], {radius: 10, color: "#5b3fa0", weight: 3, fillOpacity: .2}).addTo(g); MAP.map.flyTo([F.lat, F.lng], Math.max(MAP.map.getZoom(), 12), {duration: .5})}
}
function tripPoint(k) {const p = findPlace(k); return p ? {name: p.name, lat: p.lat, lng: p.lng} : null}
async function mapTrip() {
  const T = MAP.trip; const st = T.start ? tripPoint(T.start) : T.startPt;
  if (!st) {toast("Choose where the trip starts"); return}
  if (!T.stops.length) {toast("Add at least one stop"); return}
  T.busy = true; render(); mapAttach();
  try {T.res = await api("map_trip", {start: st, stops: T.stops, vehicle: T.vehicle || null, back: T.back, optimise: T.opt, cartons: +T.cartons || 0, value: +T.value || 0})} catch (e) {T.res = {error: String(e)}}
  T.busy = false; render(); mapDraw();
  if (T.res && T.res.geometry && T.res.geometry.length > 1) MAP.map.fitBounds(T.res.geometry, {padding: [40, 40]});
  const sb = document.querySelector(".map-side-body"); if (sb) sb.scrollTop = sb.scrollHeight;
}
async function mapTransfers() {
  const T = MAP.tr; T.busy = true; render(); mapAttach();
  try {T.data = await api("map_transfers", {vehicles: T.veh, exclude: []})} catch (e) {T.data = {error: String(e)}}
  T.busy = false; render(); mapDraw();
}
async function mapSuppliers() {
  MAP.sup.busy = true; render(); mapAttach();
  try {MAP.sup.data = await api("map_orders")} catch (e) {MAP.sup.data = {error: String(e)}}
  MAP.sup.busy = false; MAP.show.orders = true; render(); mapDraw();
}
function mapSetFromInputs() {
  const s = MAP.set; if (!s) return;
  document.querySelectorAll("[data-mset]").forEach(x => {const k = x.dataset.mset; const v = x.type === "checkbox" ? x.checked : x.type === "number" ? +x.value : x.value;
    if (k.startsWith("fuel.")) s.fuel[k.slice(5)] = v; else s[k] = v});
  document.querySelectorAll("[data-mveh]").forEach(x => {const [i, k] = x.dataset.mveh.split("|"); s.vehicles[+i][k] = x.type === "number" ? +x.value : x.value});
}
async function mapPrefetchPoll(start) {
  MAP.pre = await api("map_prefetch", {start}); if (S.page === "map" && MAP.tab === "costs") {render(); mapAttach()}
  if (MAP.pre.running) setTimeout(() => mapPrefetchPoll(false), 1500); else if (MAP.boot) MAP.boot.tiles = {tiles: MAP.pre.tiles, mb: MAP.pre.mb};
}

document.addEventListener("click", async e => {
  if (S.page !== "map") return;
  const g = e.target.closest("[data-mtab],[data-mpick],[data-mpickcancel],[data-mstopdel],[data-mtrip],[data-mtripclear],[data-mtrans],[data-mtransx],[data-mrunopen],[data-msup],[data-mlocate],[data-mfind],[data-mpsave],[data-mpdel],[data-mfly],[data-mfuel],[data-msave],[data-mprefetch],[data-mapsup]");
  if (!g) return; const d = g.dataset;
  if (d.mtab) {MAP.tab = d.mtab; render(); mapAttach(); mapDrawTrip(); if (d.mtab === "suppliers" && !MAP.sup.data) mapSuppliers(); if (d.mtab === "dc" && !MAP.dc.data) mapDc(); return}
  if (d.mdc) {mapDc(); return}
  if (d.mdcrow) {MAP.dc.open = MAP.dc.open === d.mdcrow ? null : d.mdcrow; render(); mapDrawTrip(); const r = MAP.dc.data.rows.find(x => x.store === MAP.dc.open); if (r && r.geometry.length > 1) MAP.map.fitBounds(r.geometry, {padding: [40, 40]}); return}
  if (d.mdcx) {const rows = MAP.dc.data.rows.map(r => ({store: r.name, city: r.city, vehicle: r.vehicle_name, km_one_way: Math.round(r.km), hours_one_way: +(r.minutes / 60).toFixed(1), litres_round_trip: Math.round(r.litres), fuel_pkr: Math.round(r.fuel_pkr), round_trip_cost: Math.round(r.cost)}));
    const cols = Object.keys(rows[0] || {store: 1}).map(k => ({k, l: k.replace(/_/g, " "), kind: ["store", "city", "vehicle"].includes(k) ? "text" : "num"}));
    const r = await api("export", {name: "DC deliveries", title: "Deliveries from the DC", cols, rows}); toast(r.path ? t("exported") + ": " + r.path : r.error || t("cancelled")); return}
  if (d.mfromdc) {const p = places().find(x => x.dc); if (p) {MAP.trip.start = placeKey(p); MAP.trip.startPt = null; render(); mapAttach()} return}
  if (d.mpick) {mapPickStart(d.mpick, d.mpick === "place" ? "Click where the place is" : d.mpick === "start" ? "Click where the trip starts" : "Click to add a stop"); return}
  if (d.mpickcancel) {MAP.pick = null; render(); mapAttach(); return}
  if (d.mstopdel) {MAP.trip.stops.splice(+d.mstopdel, 1); render(); mapAttach(); return}
  if (d.mtrip) {mapTrip(); return}
  if (d.mtripclear) {MAP.trip = {...MAP.trip, start: "", startPt: null, stops: [], res: null}; render(); mapDraw(); return}
  if (d.mtrans) {mapTransfers(); return}
  if (d.mtransx) {const rows = trRuns().filter(r => r.on).flatMap(r => r.stops.map(s => ({from: r.src_name, to: s.name, city: r.city, vehicle: r.vehicle_name, trips: r.trips, cartons: Math.round(s.cartons), value: Math.round(s.value), run_km: Math.round(r.km), run_hours: +(r.minutes / 60).toFixed(1), run_cost: Math.round(r.total_w), cost_pct: r.pct_w == null ? null : +r.pct_w.toFixed(1), lines: s.lines})));
    const cols = ["from", "to", "city", "vehicle", "trips", "cartons", "value", "lines", "run_km", "run_hours", "run_cost", "cost_pct"].map(k => ({k, l: k.replace(/_/g, " "), kind: ["from", "to", "city", "vehicle"].includes(k) ? "text" : "num"}));
    const r = await api("export", {name: "Transfer plan", title: "Transfer plan (IST)", cols, rows}); toast(r.path ? t("exported") + ": " + r.path : r.error || t("cancelled")); return}
  if (d.mrunopen) {MAP.tr.open = MAP.tr.open === d.mrunopen ? null : d.mrunopen; render(); mapDraw(); const r = trRuns().find(x => x.id === MAP.tr.open); if (r && r.geometry.length > 1) MAP.map.fitBounds(r.geometry, {padding: [40, 40]}); return}
  if (d.msup) {mapSuppliers(); return}
  if (d.mlocate || d.mapsup) {
    const code = d.mlocate || d.mapsup; const p = findPlace("supplier:" + code);
    if (p && d.mapsup) {mapFly("supplier:" + code); return}
    const sname = ((MAP.boot.suppliers || []).find(s => s.code === code) || {}).name || code;
    MAP.place = {kind: "supplier", code, name: sname, text: "", found: null}; MAP.tab = "places"; render(); mapAttach(); return;
  }
  if (d.mfind) {
    const P = MAP.place; if (!P.text.trim()) {toast("Type an address, a Google Maps link or coordinates"); return}
    P.busy = true; render(); mapAttach(); P.found = await api("map_locate", {text: P.text}); P.busy = false; render(); mapAttach(); mapShowFound(); return;
  }
  if (d.mpsave) {
    const P = MAP.place, F = P.found; if (!F || F.error) return;
    const code = P.kind === "store" ? (P.code || (S.boot.stores[0] || {}).code) : P.kind === "supplier" ? P.code : "";
    if (P.kind === "supplier" && !code) {toast("Choose the supplier"); return}
    if ((P.kind === "dc" || P.kind === "other") && !P.name.trim()) {toast("Give the place a name"); return}
    const r = await api("map_place", {kind: P.kind, code, lat: F.lat, lng: F.lng, name: P.name, address: P.text.startsWith("http") ? "" : P.text});
    if (r.error) {toast(r.error); return}
    MAP.boot.places = r.places; if (P.kind === "store") await mapLoad(true);
    MAP.place = {kind: P.kind, code: "", name: "", text: "", found: null}; MAP.lay.found.clearLayers(); toast("Location saved"); render(); mapDraw(); return;
  }
  if (d.mpdel) {const [kind, ...c] = d.mpdel.split(":"); if (!confirm("Remove this location?")) return; const r = await api("map_place", {kind, code: c.join(":"), delete: true}); MAP.boot.places = r.places; if (kind === "store") await mapLoad(true); render(); mapDraw(); return}
  if (d.mfly) {mapFly(d.mfly); return}
  if (d.mfuel) {mapSetFromInputs(); const r = await api("map_fuel"); if (r.ok) {MAP.set.fuel = {...MAP.set.fuel, petrol: r.petrol, diesel: r.diesel, as_of: r.as_of, source: r.source}; MAP.boot.settings.fuel = MAP.set.fuel; toast("Latest fuel prices saved")} else toast(r.error || "Could not fetch"); render(); mapAttach(); return}
  if (d.msave) {mapSetFromInputs(); const r = await api("map_settings", {changes: MAP.set}); MAP.boot.settings = r.settings; MAP.set = null; MAP.dc.data = null; toast("Saved"); await mapLoad(true); if (MAP.tr.data) mapTransfers(); else {render(); mapAttach()} return}
  if (d.mprefetch) {mapPrefetchPoll(true); return}
});
document.addEventListener("change", async e => {
  if (S.page !== "map") return; const el = e.target;
  if (el.id === "m-color") {MAP.color = el.value; render(); mapDraw(); return}
  if (el.dataset.mshow) {MAP.show[el.dataset.mshow] = el.checked; if (el.dataset.mshow === "orders" && el.checked && !MAP.sup.data) {mapSuppliers(); return} render(); mapDraw(); return}
  if (el.dataset.medit) {MAP.edit = el.checked; render(); mapDraw(); if (MAP.edit) toast("Drag a pin to its exact spot; it is saved when you let go"); return}
  if (el.id === "m-start") {MAP.trip.start = el.value; MAP.trip.startPt = null; render(); mapAttach(); return}
  if (el.id === "m-addstop") {const p = tripPoint(el.value); if (p) MAP.trip.stops.push(p); render(); mapAttach(); return}
  if (el.id === "m-veh") {MAP.trip.vehicle = el.value; return}
  if (el.id === "m-back") {MAP.trip.back = el.checked; return}
  if (el.id === "m-opt") {MAP.trip.opt = el.checked; return}
  if (el.dataset.mrun) {el.checked ? MAP.tr.excl.delete(el.dataset.mrun) : MAP.tr.excl.add(el.dataset.mrun); render(); mapDraw(); return}
  if (el.dataset.mrunveh) {const id = el.dataset.mrunveh; if (el.value) MAP.tr.veh[id] = el.value; else delete MAP.tr.veh[id]; mapTransfers(); return}
  if (el.id === "m-maxp") {MAP.tr.maxpct = +el.value; render(); mapDraw(); return}
  if (el.id === "m-fuelw") {MAP.tr.fuel = +el.value; render(); mapDraw(); return}
  if (el.id === "m-pkind") {MAP.place = {kind: el.value, code: "", name: "", text: MAP.place.text, found: MAP.place.found}; render(); mapAttach(); return}
  if (el.id === "m-pstore") {MAP.place.code = el.value; return}
  if (el.id === "m-psup") {const m = el.value.match(/ — (.+)$/); const code = m ? m[1] : el.value.trim(); MAP.place.code = code; MAP.place.name = ((MAP.boot.suppliers || []).find(s => s.code === code) || {}).name || ""; return}
});
document.addEventListener("input", e => {
  if (S.page !== "map") return; const el = e.target;
  if (el.id === "m-cart") MAP.trip.cartons = el.value; else if (el.id === "m-val") MAP.trip.value = el.value;
  else if (el.id === "m-ptext") MAP.place.text = el.value; else if (el.id === "m-pname") MAP.place.name = el.value;
  else if (el.id === "m-fuelw") {MAP.tr.fuel = +el.value; const b = document.getElementById("m-fuelw-v"); if (b) b.textContent = (MAP.tr.fuel > 0 ? "+" : "") + MAP.tr.fuel + "%"}
});
