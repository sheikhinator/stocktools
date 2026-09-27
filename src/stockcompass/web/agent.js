/* Stock Compass Agent: a Claude-style chat over all the store data.
   Streams the answer, shows the tools it uses, charts, reports and change approvals; files, voice, model and effort. */
"use strict";

const AG = {cfg: null, chats: [], chat: null, msgs: [], run: null, live: null, draft: "", files: [], busy: false,
  rec: null, set: "keys", local: null, mem: null, hf: null, tests: {}, loaded: false, pollT: null, dlT: null, open: {}, qd: {}};

const TOOL_LABEL = {data_overview: "Checked what data is loaded", screen: "Read a screen", drill: "Broke a number down", find: "Searched items",
  item_status: "Looked up an item", supplier_status: "Looked up a supplier", describe_tables: "Read the table guide", sql: "Queried the database",
  recall: "Searched memory", remember: "Saved to memory", chart: "Drew a chart", make_report: "Wrote a report", open_screen: "Opened a screen",
  add_promotion: "Logged a promotion", delete_promotion: "Deleted a promotion", set_bc_target: "Changed a BC target",
  set_threshold: "Changed a threshold", add_store_name: "Added a store name", ask_user: "Asked you", analyse: "Analysed", save_meaning: "Saved a meaning",
  read_import: "Read an imported file", import_queue: "Checked the Import screen", import_file: "Added a file to import",
  import_set: "Corrected an import", import_run: "Imported files", delete_import: "Deleted an import"};
const SUGGEST = [
  ["What needs my attention today?", "Across all stores: biggest problems in stock, sales and orders, with PKR impact."],
  ["How far are we behind budget?", "Sales vs budget month to date by store and department, with the main gaps."],
  ["What's the status of Dettol at Emporium?", "Stock, orders, sales and out-of-stock reason for one item in one store."],
  ["Why are sales down during the latest promotion at Packages?", "Promotion items out of stock, not on order, priced below cost."],
  ["Which suppliers are hurting availability?", "Late orders, purged LPOs and out-of-stock items by supplier."],
  ["Make a weekly head office report", "PDF, Word and Excel with charts: sales, zero stock, aged stock, BC."]];

/* ---------------- markdown (safe: everything is escaped first) ---------------- */
function mdInline(s) {
  return esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*(?!\s)(.+?)(?<!\s)\*(?!\*)/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" data-ext="$2">$1</a>');
}
function md(src) {
  const L = String(src || "").replace(/\r/g, "").split("\n"); let o = "", i = 0;
  while (i < L.length) {
    const ln = L[i];
    if (/^```/.test(ln)) {const lang = ln.slice(3).trim(); let code = []; i++; while (i < L.length && !/^```/.test(L[i])) code.push(L[i++]); i++; o += `<pre class="code"><code>${esc(code.join("\n"))}</code></pre>`; continue}
    if (!ln.trim()) {i++; continue}
    let m = ln.match(/^(#{1,4})\s+(.*)/); if (m) {const h = Math.min(4, m[1].length + 1); o += `<h${h}>${mdInline(m[2])}</h${h}>`; i++; continue}
    if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(ln)) {o += "<hr>"; i++; continue}
    if (/^\s*\|/.test(ln) && i + 1 < L.length && /^\s*\|?\s*:?-{2,}/.test(L[i + 1])) {
      const cells = r => r.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
      const head = cells(ln); i += 2; const rows = []; while (i < L.length && /^\s*\|/.test(L[i])) rows.push(cells(L[i++]));
      o += mdTable(head, rows); continue}
    if (/^\s*>\s?/.test(ln)) {const q = []; while (i < L.length && /^\s*>\s?/.test(L[i])) q.push(L[i++].replace(/^\s*>\s?/, "")); o += `<blockquote>${md(q.join("\n"))}</blockquote>`; continue}
    if (/^\s*([-*•]|\d+[.)])\s+/.test(ln)) {
      const ordered = /^\s*\d+[.)]/.test(ln); const items = [];
      while (i < L.length && (/^\s*([-*•]|\d+[.)])\s+/.test(L[i]) || (/^\s{2,}\S/.test(L[i]) && items.length))) {
        if (/^\s*([-*•]|\d+[.)])\s+/.test(L[i]) && !/^\s{3,}/.test(L[i])) items.push([L[i].replace(/^\s*([-*•]|\d+[.)])\s+/, "")]);
        else items[items.length - 1].push(L[i].trim().replace(/^([-*•]|\d+[.)])\s+/, "• "));
        i++;
      }
      o += `<${ordered ? "ol" : "ul"}>${items.map(it => `<li>${mdInline(it[0])}${it.length > 1 ? "<br>" + it.slice(1).map(mdInline).join("<br>") : ""}</li>`).join("")}</${ordered ? "ol" : "ul"}>`; continue}
    const para = [ln]; i++;
    while (i < L.length && L[i].trim() && !/^(#{1,4}\s|```|\s*([-*•]|\d+[.)])\s|\s*\||\s*>)/.test(L[i])) para.push(L[i++]);
    o += `<p>${mdInline(para.join("\n")).replace(/\n/g, "<br>")}</p>`;
  }
  return o;
}

/* markdown tables become full tables: sortable columns, frozen header, totals and hover sums */
function parseNum(txt) {
  const t0 = String(txt).replace(/\*\*/g, "").replace(/<[^>]+>/g, "").trim();
  const m = t0.match(/^(PKR\s*)?([-+−]?)\s*([\d,]*\.?\d+)\s*([KMB]?)\s*(%|×|x)?$/i);
  if (!m) return null;
  let v = parseFloat(m[3].replace(/,/g, "")) * ({K: 1e3, M: 1e6, B: 1e9}[(m[4] || "").toUpperCase()] || 1);
  if (m[2] === "-" || m[2] === "−") v = -v;
  return {d: t0, v, unit: m[5] === "%" ? "%" : m[1] ? "PKR" : ""};
}
function mdTable(head, rows) {
  const n = head.length; const kinds = head.map((h, j) => {const vals = rows.map(r => r[j]).filter(c => c != null && c !== "" && c !== "—" && !/^\**total/i.test(c));
    return vals.length && vals.every(c => parseNum(c)) ? "mdnum" : "text"});
  const units = head.map((h, j) => kinds[j] === "mdnum" ? ((rows.map(r => parseNum(r[j])).find(Boolean) || {}).unit || "") : "");
  let body = rows.filter(r => !/^\**(grand )?total/i.test(String(r[0] || "").trim()));       // the table adds its own total row
  const cols = head.map((h, j) => ({k: "c" + j, l: h.replace(/\*\*/g, ""), kind: kinds[j], unit: units[j]}));
  const data = body.map(r => Object.fromEntries(head.map((h, j) => [`c${j}`, kinds[j] === "mdnum" ? parseNum(r[j]) || {d: r[j] || "", v: null} : {d: r[j] ?? "", v: String(r[j] ?? "")}])));
  let hsh = 0; for (const ch of head.join("|") + body.length + (body[0] || []).join("|")) hsh = (hsh * 31 + ch.charCodeAt(0)) | 0;
  return `<div class="md-tbl">${tableC({type: "table", id: "md" + Math.abs(hsh), cols, rows: data, page_size: 100, total: data.length > 1 && kinds.includes("mdnum") ? undefined : false}, "Agent table")}</div>`;
}

/* ---------------- loading ---------------- */
async function agentLoad() {
  S.data = {}; render();
  const [c, ch] = await Promise.all([api("agent_config"), api("agent_chats")]);
  AG.cfg = c; AG.chats = ch.chats || []; AG.loaded = true;
  render(); agentFocus();
}
async function agentOpenChat(id) {
  AG.chat = id; AG.msgs = []; AG.live = null; render();
  if (!id) {agentFocus(); return}
  const r = await api("agent_chat", {chat: id}); AG.msgs = r.messages || []; render(); agentScroll(true); agentFocus();
}
function agentFocus() {setTimeout(() => {const t = $("#ag-input"); if (t) {t.focus(); t.setSelectionRange(t.value.length, t.value.length)}}, 20)}
function agentScroll(force) {const m = $("#ag-msgs"); if (!m) return; if (force || m.scrollHeight - m.scrollTop - m.clientHeight < 160) m.scrollTop = m.scrollHeight}

/* ---------------- model choices ---------------- */
function readyProviders() {return (AG.cfg ? AG.cfg.providers : []).filter(p => p.ready && (p.id !== "offline" || (AG.cfg.server && AG.cfg.server.running)))}
function currentPick() {
  const c = AG.cfg || {}; const rp = readyProviders();
  let p = rp.find(x => x.id === c.provider) || rp[0]; if (!p) return null;
  let m = c.model && (p.models || []).includes(c.model) ? c.model : (c.provider === p.id && c.model) || (p.models || [])[0] || "";
  if (p.id === "offline" && c.server && c.server.model) m = c.server.model;
  return {p, m};
}
function modelSelect() {
  const rp = readyProviders(); const pick = currentPick();
  if (!rp.length) return `<button class="ag-chip warn" data-ag="settings" data-tab="keys">⚙ Set up a model</button>`;
  return `<select id="ag-model" class="ag-select" title="Model">${rp.map(p => `<optgroup label="${esc(p.name)}${p.local ? " · on this PC" : ""}">${(p.models.length ? p.models : [""]).slice(0, 80).map(m => `<option value="${esc(p.id + "|" + m)}" ${pick && pick.p.id === p.id && pick.m === m ? "selected" : ""}>${esc(m || p.name)}</option>`).join("")}</optgroup>`).join("")}</select>`;
}
function effortSelect() {
  const e = (AG.cfg && AG.cfg.effort) || "medium";
  return `<select id="ag-effort" class="ag-select" title="Effort: how hard the agent works (more tool steps and thinking)">${[["low", "Quick"], ["medium", "Balanced"], ["high", "Deep"]].map(([k, n]) => `<option value="${k}" ${e === k ? "selected" : ""}>${n}</option>`).join("")}</select>`;
}
function privacyBadge() {
  const pk = currentPick(); if (!pk) return "";
  return pk.p.local ? `<span class="ag-badge ok" data-tip="${esc("The model runs on this PC. Your questions and data never leave the computer.")}">🔒 On this PC</span>`
    : `<span class="ag-badge neutral">${esc(pk.p.name)}</span>`;
}

/* ---------------- page ---------------- */
function agentPage() {
  if (!AG.loaded) return `<div class="loading"><span class="spin"></span>${esc(t("loading"))}</div>`;
  const chats = AG.chats.map(c => `<div class="ag-ci ${AG.chat === c.id ? "on" : ""}"><button data-ag="open" data-id="${esc(c.id)}" title="${esc(c.title)}">${esc(c.title || "Chat")}</button>
    <span class="ag-cmenu"><button data-ag="rename" data-id="${esc(c.id)}" title="Rename">✎</button><button data-ag="delchat" data-id="${esc(c.id)}" title="Delete">🗑</button></span></div>`).join("");
  const title = AG.chat ? (AG.chats.find(c => c.id === AG.chat) || {}).title || "Chat" : "New chat";
  const empty = !AG.chat && !AG.live;
  const hour = new Date().getHours();
  const hello = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  return `<div class="ag">
  <aside class="ag-side"><button class="ag-new" data-ag="new">＋ New chat</button>
    <div class="ag-list">${chats || `<p class="muted" style="font-size:12.5px;padding:6px 10px">Your conversations appear here.</p>`}</div>
    <div class="ag-side-foot"><button data-ag="settings" data-tab="keys">🔑 Models & keys</button><button data-ag="settings" data-tab="offline">💻 Offline models</button>
    <button data-ag="settings" data-tab="memory">🧠 Memory</button><button data-ag="settings" data-tab="behaviour">⚙ Behaviour</button></div></aside>
  <section class="ag-main ${empty ? "ag-empty" : ""}">
    <div class="ag-top"><b class="ag-title">${esc(title)}</b><span class="spacer"></span>${privacyBadge()}</div>
    ${empty ? `<div class="ag-hello"><div class="ag-spark">${svgI("agent")}</div><h1>${hello}. What would you like to know?</h1>
      <p class="muted">I can read every report you imported — stock, sales, orders, promotions, aged stock and the BC scorecard — down to the item and store.</p></div>` : `<div class="ag-msgs" id="ag-msgs">${agentMsgsHTML()}</div>`}
    ${composerHTML()}
    ${empty ? `<div class="ag-sugg">${SUGGEST.map(s => `<button class="ag-sg" data-ag="suggest" data-q="${esc(s[0])}"><b>${esc(s[0])}</b><span>${esc(s[1])}</span></button>`).join("")}</div>` : ""}
  </section></div>`;
}
function composerHTML() {
  const files = AG.files.map(f => `<span class="ag-file ${f.uploading ? "up" : ""}" title="${esc(f.preview || "")}"><span class="ag-fi">${esc(fileIcon(f))}</span><span class="ag-fn">${esc(f.name)}</span>${f.is_report ? `<button class="linkbtn" data-ag="import" data-id="${esc(f.id)}" title="Add this report to Stock Compass">Import</button>` : ""}<button data-ag="rmfile" data-id="${esc(f.id || f.name)}" aria-label="Remove">×</button></span>`).join("");
  const running = !!AG.run;
  const rec = AG.rec;
  return `<div class="ag-composer"><div class="ag-box" id="ag-drop">
    ${files ? `<div class="ag-files">${files}</div>` : ""}
    <textarea id="ag-input" rows="1" aria-label="Message to the agent" placeholder="${rec ? "Listening… click the red button to stop" : "Ask about any store, item, supplier, promotion or number…"}">${esc(AG.draft)}</textarea>
    <div class="ag-bar"><button class="ag-ib" data-ag="attach" title="Attach files (any type)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 12l-8.5 8.5a5 5 0 0 1-7-7L14 5a3.3 3.3 0 0 1 4.7 4.7L10 18.4a1.7 1.7 0 0 1-2.4-2.4L15.5 8"/></svg></button>
      <button class="ag-ib ${rec ? "rec" : ""}" data-ag="mic" title="${rec ? "Stop and type what I said" : "Voice typing"}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>${rec ? `<span class="ag-rt">${rec.secs || 0}s</span>` : ""}</button>
      <span class="spacer"></span>${modelSelect()}${effortSelect()}
      ${running ? `<button class="ag-send stop" data-ag="stop" title="Stop">■</button>` : `<button class="ag-send" data-ag="send" title="Send (Enter)" ${AG.files.some(f => f.uploading) ? "disabled" : ""}>↑</button>`}</div></div>
    <input type="file" id="ag-file" multiple hidden>
    <div class="ag-hint">Enter to send · Shift+Enter for a new line · The agent can make mistakes; check important numbers on the screens.</div></div>`;
}
const fileIcon = f => f.kind === "image" ? "IMG" : f.kind === "sheet" ? "XLS" : /\.pdf$/i.test(f.name) ? "PDF" : /\.docx?$/i.test(f.name) ? "DOC" : f.kind === "audio" ? "AUD" : "TXT";

/* ---------------- messages ---------------- */
function agentMsgsHTML() {
  let h = AG.msgs.map(m => m.role === "user" ? userHTML(m) : assistantHTML(m.blocks || [], m.text, m.error, m.model, false, m.stats)).join("");
  if (AG.live) h += userHTML(AG.live.user) + assistantHTML(AG.live.blocks, "", AG.live.error, AG.live.model, true);
  return `<div class="ag-thread">${h}</div>`;
}
function userHTML(m) {
  const att = (m.attachments || []).map(a => `<span class="ag-file sm"><span class="ag-fi">${esc(fileIcon(a))}</span><span class="ag-fn">${esc(a.name)}</span></span>`).join("");
  return `<div class="ag-u">${att ? `<div class="ag-files">${att}</div>` : ""}<div class="ag-ub">${esc(m.text || "").replace(/\n/g, "<br>")}</div></div>`;
}
function assistantHTML(blocks, text, error, model, live, stats) {
  const parts = []; let tools = [];
  const flushTools = () => {if (!tools.length) return; const key = "tl" + parts.length + (live ? "L" : "") + (model || ""); const open = AG.open[key];
    const running = tools.some(x => x.status === "running");
    parts.push(`<div class="ag-tools"><button class="ag-tsum" data-ag="toggle" data-k="${esc(key)}">${running ? '<span class="spin sm"></span>' : "✓"} ${esc(running ? (TOOL_LABEL[tools[tools.length - 1].name] || "Working") + "…" : `Used ${tools.length} tool${tools.length > 1 ? "s" : ""}`)} <span class="muted">${open ? "▾" : "▸"}</span></button>
    ${open ? `<div class="ag-tlist">${tools.map(x => `<div class="ag-t ${x.status}"><b>${esc(TOOL_LABEL[x.name] || x.name)}</b> <span class="muted">${esc(argText(x))}</span>${x.summary ? ` → <span>${esc(x.summary)}</span>` : ""}</div>`).join("")}</div>` : ""}</div>`); tools = []};
  for (const b of blocks) {
    if (b.type === "tool") {tools.push(b); continue}
    flushTools();
    if (b.type === "text") parts.push(`<div class="ag-md">${md(b.text)}</div>`);
    else if (b.type === "thinking") parts.push(`<details class="ag-think"><summary>Thinking</summary><div>${esc(b.text).replace(/\n/g, "<br>")}</div></details>`);
    else if (b.type === "chart") parts.push(`<div class="ag-chart">${panelC({title: b.title || "", sub: b.sub || "", body: b.body})}</div>`);
    else if (b.type === "report") parts.push(reportHTML(b));
    else if (b.type === "approval") parts.push(approvalHTML(b));
    else if (b.type === "question") parts.push(questionHTML(b));
    else if (b.type === "change") parts.push(`<div class="ag-change ${b.approved ? "ok" : "no"}">${b.approved ? "✓ Changed" : "✕ Not changed"}: ${esc(b.text)}</div>`);
    else if (b.type === "navigate") parts.push(`<div class="ag-note">Opened <button class="linkbtn" data-page="${esc(b.page)}">${esc(t(b.page) || b.page)}</button></div>`);
    else if (b.type === "memory") parts.push(`<div class="ag-note">🧠 Remembered: ${esc(b.text)}</div>`);
    else if (b.type === "note") parts.push(`<div class="ag-note">${esc(b.text)}</div>`);
  }
  flushTools();
  if (!blocks.some(b => b.type === "text") && text) parts.push(`<div class="ag-md">${md(text)}</div>`);
  if (live && !parts.length) parts.push(`<div class="ag-typing"><span></span><span></span><span></span></div>`);
  if (error) parts.push(`<div class="errbox">${esc(error)} ${/key|Models & keys/i.test(error) ? `<button class="linkbtn" data-ag="settings" data-tab="keys">Open Models & keys</button>` : ""}</div>`);
  return `<div class="ag-a"><div class="ag-av">${svgI("agent")}</div><div class="ag-ab">${parts.join("")}${!live && model ? `<div class="ag-meta">${esc(model)}${stats && stats.seconds ? ` · ${stats.seconds}s` : ""}${stats && stats.tps ? ` · ~${stats.tps} tokens/s` : ""}</div>` : ""}</div></div>`;
}
function argText(x) {const a = x.args || {}; if (x.name === "sql") return (a.query || "").slice(0, 120); return Object.entries(a).filter(([k, v]) => v !== "" && v != null && typeof v !== "object").map(([k, v]) => `${k}: ${v}`).join(", ").slice(0, 120)}
function reportHTML(b) {
  return `<div class="ag-report"><div class="ag-rt">📄 <b>${esc(b.title || "Report")}</b></div><div class="ag-rfiles">${(b.files || []).map(f => `<button class="ag-rf" data-ag="openfile" data-path="${esc(f.path)}"><span class="ag-fi ${f.kind}">${esc(f.kind.toUpperCase())}</span><span>${esc(f.name)}</span></button>`).join("")}</div></div>`;
}
function approvalHTML(b) {
  const pending = b.status === "pending";
  return `<div class="ag-approve ${pending ? "" : b.approved ? "ok" : "no"}"><div><b>The agent wants to make a change</b><div>${esc(b.text)}</div></div>
  ${pending ? `<div class="row"><button class="primary" data-ag="approve" data-id="${esc(b.id)}">Approve</button><button class="pill-btn" data-ag="decline" data-id="${esc(b.id)}">Decline</button></div>` : `<span class="chip ${b.approved ? "good" : "crit"}">${b.approved ? "Approved" : "Declined"}</span>`}</div>`;
}
function questionHTML(b) {
  const pending = b.status === "pending";
  if (!pending) return `<div class="ag-q done"><div class="ag-qt">❓ ${esc(b.text)}</div><div>${b.answer ? `<b>You:</b> ${esc(b.answer)}${b.term ? ` <span class="muted">· saved to the glossary as “${esc(b.term)}”</span>` : ""}` : `<span class="muted">Not answered</span>`}</div></div>`;
  return `<div class="ag-q"><div class="ag-qt">❓ ${esc(b.text)}</div>
  ${(b.options || []).length ? `<div class="ag-qopts">${b.options.map(o => `<button class="pill-btn" data-ag="qpick" data-id="${esc(b.id)}" data-v="${esc(o)}">${esc(o)}</button>`).join("")}</div>` : ""}
  <div class="ag-form"><label class="sr" for="q-${esc(b.id)}">Your answer</label><input id="q-${esc(b.id)}" data-qid="${esc(b.id)}" value="${esc(AG.qd[b.id] || "")}" placeholder="Type the meaning…"><button class="primary" data-ag="qsend" data-id="${esc(b.id)}">Answer</button><button class="pill-btn" data-ag="qskip" data-id="${esc(b.id)}">Skip</button></div>
  ${b.term ? `<div class="muted" style="font-size:12px">Saved to the glossary as “${esc(b.term)}”, so the agent will not ask again.</div>` : ""}</div>`;
}
function rerenderMsgs() {const m = $("#ag-msgs"); if (!m) {render(); return} const keep = m.scrollHeight - m.scrollTop - m.clientHeight < 160; m.innerHTML = agentMsgsHTML(); if (keep) m.scrollTop = m.scrollHeight}

/* ---------------- sending & streaming ---------------- */
async function agentSend(text) {
  text = (text ?? AG.draft).trim();
  if ((!text && !AG.files.length) || AG.run) return;
  const pick = currentPick();
  if (!pick) {agentSettings("keys"); toast("Add a key or load an offline model first."); return}
  const files = AG.files.filter(f => f.id && !f.uploading);
  AG.draft = ""; AG.files = [];
  AG.live = {user: {text, attachments: files}, blocks: [], model: `${pick.p.name} · ${pick.m}`, error: null};
  render(); agentScroll(true);
  const r = await api("agent_send", {text, chat: AG.chat, attachments: files.map(f => f.id), provider: pick.p.id, model: pick.m, effort: $("#ag-effort") ? $("#ag-effort").value : AG.cfg.effort});
  if (r.error) {AG.live.error = r.error; AG.live.done = true; rerenderMsgs(); AG.draft = text; return}
  const isNew = !AG.chat; AG.chat = r.chat; AG.run = {id: r.run, since: 0};
  if (isNew) {api("agent_chats").then(c => {AG.chats = c.chats || []})}
  render(); agentScroll(true); agentPoll();
}
async function agentPoll() {
  if (!AG.run) return;
  const r = await api("agent_poll", {run: AG.run.id, since: AG.run.since});
  const L = AG.live; let dirty = false;
  for (const e of r.events || []) {
    AG.run.since = e.i + 1; dirty = true;
    const last = L.blocks[L.blocks.length - 1];
    if (e.type === "text") {if (last && last.type === "text" && !last.closed) last.text += e.delta; else L.blocks.push({type: "text", text: e.delta})}
    else if (e.type === "thinking") {if (last && last.type === "thinking") last.text += e.delta; else L.blocks.push({type: "thinking", text: e.delta})}
    else if (e.type === "tool") {
      if (last && last.type === "text") last.closed = true;
      const ex = L.blocks.find(b => b.type === "tool" && b.id === e.id);
      if (ex) Object.assign(ex, {status: e.status, summary: e.summary || ex.summary}); else L.blocks.push({type: "tool", id: e.id, name: e.name, args: e.args, status: e.status});
    }
    else if (e.type === "approval") L.blocks.push({type: "approval", id: e.id, text: e.text, status: "pending"});
    else if (e.type === "question") L.blocks.push({type: "question", id: e.id, text: e.text, options: e.options || [], term: e.term, status: "pending"});
    else if (e.type === "answer") {const q = L.blocks.find(b => b.type === "question" && b.id === e.id); if (q) {q.status = "done"; q.answer = e.answer}}
    else if (e.type === "approval_done") {const a = L.blocks.find(b => b.type === "approval" && b.id === e.id); if (a) {a.status = "done"; a.approved = e.approved}}
    else if (["chart", "report", "memory", "note"].includes(e.type)) {if (!e.late) L.blocks.push(e)}
    else if (e.type === "navigate") {L.blocks.push(e); if (e.where) S.f.where = e.where; if (e.dept !== undefined) S.f.dept = e.dept; if (e.section !== undefined) S.f.section = e.section; if (e.tab) S.tab = e.tab; cache.clear()}
    else if (e.type === "error") L.error = e.text;
  }
  if (r.done) {
    AG.run = null;
    const [ch, cl] = await Promise.all([api("agent_chat", {chat: AG.chat}), api("agent_chats")]);
    AG.msgs = ch.messages || []; AG.chats = cl.chats || [];
    if (L.error && !(AG.msgs[AG.msgs.length - 1] || {}).error) AG.msgs.push({role: "assistant", blocks: L.blocks, error: L.error, model: L.model});
    AG.live = null; render(); agentScroll(true); agentFocus();
    const nav = L.blocks.find(b => b.type === "navigate"); if (nav) setTimeout(() => go(nav.page + (nav.tab ? ":" + nav.tab : "")), 600);
    return;
  }
  if (dirty) rerenderMsgs();
  AG.pollT = setTimeout(agentPoll, 200);
}

/* ---------------- files ---------------- */
function readB64(file) {return new Promise((res, rej) => {const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file)})}
async function agentAddFiles(list) {
  for (const f of list) {
    if (f.size > 40e6) {toast(`${f.name} is larger than 40 MB`); continue}
    const tmp = {name: f.name, uploading: true, kind: ""}; AG.files.push(tmp); render();
    const data = await readB64(f);
    const r = await api("agent_upload", {name: f.name, data, mime: f.type || ""});
    Object.assign(tmp, r, {uploading: false}); render(); agentFocus();
  }
}
async function agentAttachPaths(paths) {
  for (const p of paths) {const tmp = {name: p.split(/[\\/]/).pop(), uploading: true}; AG.files.push(tmp); render();
    const r = await api("agent_upload_path", {path: p}); Object.assign(tmp, r, {uploading: false}); render()}
}

/* ---------------- voice ---------------- */
async function agentMic() {
  if (AG.rec) {return agentMicStop()}
  let stream;
  try {stream = await navigator.mediaDevices.getUserMedia({audio: true})} catch (e) {toast("Microphone not available: " + e.message); return}
  const ctx = new (window.AudioContext || window.webkitAudioContext)({sampleRate: 16000});
  const src = ctx.createMediaStreamSource(stream); const proc = ctx.createScriptProcessor(4096, 1, 1); const chunks = [];
  proc.onaudioprocess = e => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  src.connect(proc); proc.connect(ctx.destination);
  AG.rec = {stream, ctx, proc, chunks, t0: Date.now(), secs: 0};
  AG.rec.timer = setInterval(() => {if (!AG.rec) return; AG.rec.secs = Math.round((Date.now() - AG.rec.t0) / 1000); const s = $(".ag-rt"); if (s) s.textContent = AG.rec.secs + "s"; if (AG.rec.secs >= 120) agentMicStop()}, 500);
  render();
}
async function agentMicStop() {
  const R = AG.rec; if (!R) return; AG.rec = null; clearInterval(R.timer);
  R.proc.disconnect(); R.stream.getTracks().forEach(t => t.stop()); const rate = R.ctx.sampleRate; await R.ctx.close();
  const n = R.chunks.reduce((a, c) => a + c.length, 0); const pcm = new Int16Array(n); let o = 0;
  for (const c of R.chunks) for (let i = 0; i < c.length; i++) {const v = Math.max(-1, Math.min(1, c[i])); pcm[o++] = v < 0 ? v * 0x8000 : v * 0x7fff}
  const buf = new ArrayBuffer(44 + pcm.length * 2); const dv = new DataView(buf); const w = (p, s) => {for (let i = 0; i < s.length; i++) dv.setUint8(p + i, s.charCodeAt(i))};
  w(0, "RIFF"); dv.setUint32(4, 36 + pcm.length * 2, true); w(8, "WAVE"); w(12, "fmt "); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
  dv.setUint32(24, rate, true); dv.setUint32(28, rate * 2, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); w(36, "data"); dv.setUint32(40, pcm.length * 2, true);
  new Int16Array(buf, 44).set(pcm);
  const b64 = await readB64(new Blob([buf], {type: "audio/wav"}));
  AG.draft = (AG.draft ? AG.draft + " " : "") + "…"; render();
  const r = await api("agent_transcribe", {wav: b64});
  AG.draft = AG.draft.replace(/ ?…$/, "");
  if (r.error) {toast(r.error); render(); return}
  AG.draft = (AG.draft ? AG.draft + " " : "") + (r.text || ""); render(); agentFocus();
}

/* ---------------- settings drawer ---------------- */
function agentSettings(tab) {AG.set = tab || AG.set; S.drawer = {kind: "agset"}; render(); if (AG.set === "offline") agentLocal(true); if (AG.set === "memory") agentMemory()}
async function agentLocal(detect) {AG.local = await api("local_state", {detect: !!detect}); if (S.drawer && S.drawer.kind === "agset") render(); agentDlPoll()}
function agentDlPoll() {
  clearTimeout(AG.dlT);
  const running = AG.local && ((AG.local.downloads || []).some(d => d.status === "running") || (AG.local.server.running && !AG.local.server.ready));
  if (running) AG.dlT = setTimeout(async () => {AG.local = await api("local_state", {}); if (S.drawer && S.drawer.kind === "agset" && AG.set === "offline") render();
    if (!(AG.local.downloads || []).some(d => d.status === "running")) AG.cfg = await api("agent_config"); agentDlPoll()}, 1000);
}
async function agentMemory() {[AG.mem, AG.gl] = await Promise.all([api("agent_memory"), api("agent_glossary")]); if (S.drawer && S.drawer.kind === "agset") render()}
function agentSettingsHTML() {
  const tabs = [["keys", "Models & keys"], ["offline", "Offline models"], ["memory", "Memory"], ["behaviour", "Behaviour"]];
  const body = AG.set === "keys" ? keysHTML() : AG.set === "offline" ? offlineHTML() : AG.set === "memory" ? memoryHTML() : behaviourHTML();
  return drawerShell(false, "Agent", "Settings", `<div class="tabs" style="margin-top:8px">${tabs.map(([k, n]) => `<button data-ag="settab" data-tab="${k}" aria-pressed="${AG.set === k}">${n}</button>`).join("")}</div>`, body);
}
function keysHTML() {
  const ps = (AG.cfg || {}).providers || [];
  const grp = (title, list, note) => list.length ? `<h3 class="ag-h3">${esc(title)}</h3>${note ? `<p class="muted" style="margin:0 0 6px;font-size:12.5px">${esc(note)}</p>` : ""}<div class="ag-provs">${list.map(provCard).join("")}</div>` : "";
  const free = ps.filter(p => !p.local && !p.custom && /free|trial|credit|without a key/i.test(p.free) && !/^Paid\.?$/i.test(p.free));
  const paid = ps.filter(p => !p.local && !p.custom && !free.includes(p));
  const TA = AG.testAll; const rows = TA && TA.results ? Object.values(TA.results) : [];
  const testTable = rows.length ? `<div class="tbl-wrap" style="max-height:none;margin:8px 0"><table><thead><tr><th class="nosort">Provider</th><th class="nosort">Status</th><th class="nosort">Model</th><th class="n nosort">Seconds</th><th class="nosort">Tools</th><th class="n nosort">Models</th><th class="nosort">Detail</th></tr></thead><tbody>${rows.sort((a, b) => ({ok: 0, busy: 1}[a.status] ?? 2) - ({ok: 0, busy: 1}[b.status] ?? 2)).map(r => `<tr><td><b>${esc(r.name)}</b></td><td class="nw">${r.status === "ok" ? chip("good", "Working") : r.status === "busy" ? chip("warn", "Busy — try later") : r.status === "failed" ? chip("crit", "Not working") : `<span class="spin sm"></span> ${esc(r.status)}`}</td><td>${esc(r.model || "")}</td><td class="n">${r.seconds ?? ""}</td><td>${r.tools == null ? "" : r.tools ? "✓" : "—"}</td><td class="n">${r.models || ""}</td><td class="muted" style="font-size:12px;max-width:380px">${esc((r.detail || "").slice(0, 220))}</td></tr>`).join("")}</tbody></table></div>` : "";
  return `<div class="row"><div class="muted" style="font-size:12.5px;flex:1">Paste a key and press <b>Test</b>, or check every service at once. Keys are stored encrypted on this PC.</div><button class="primary" data-ag="testall" ${TA && TA.running ? "disabled" : ""}>${TA && TA.running ? '<span class="spin sm"></span> Testing all…' : "Test all"}</button></div>
  ${testTable}
  ${grp("Free to start", free, "Free tiers change often; the Test button shows what your key can do today.")}
  ${grp("Paid", paid)}
  ${grp("On this PC", ps.filter(p => p.local && !p.custom), "Run a model on this computer: use the built-in offline runtime, or Ollama / LM Studio / Jan if you have them.")}
  ${grp("Your endpoints", ps.filter(p => p.custom))}
  <h3 class="ag-h3">Add any OpenAI-compatible endpoint</h3>
  <div class="ag-form"><input id="cu-name" aria-label="Name" placeholder="Name (e.g. Company gateway)"><input id="cu-url" aria-label="Base URL" placeholder="Base URL, e.g. https://host/v1"><input id="cu-key" type="password" aria-label="Key" placeholder="Key (optional)">
  <input id="cu-models" aria-label="Model names" placeholder="Model names, comma separated"><select id="cu-kind" aria-label="API format"><option value="openai">OpenAI format</option><option value="anthropic">Anthropic format</option></select><button class="primary" data-ag="addcustom">Add</button></div>`;
}
function provCard(p) {
  const c = AG.cfg; const using = c.provider === p.id; const tr = AG.tests[p.id];
  const tested = p.tested ? `<span class="chip ${p.tested.ok ? "good" : "crit"}">${p.tested.ok ? "Tested OK" : "Test failed"} · ${esc(p.tested.when)}</span>` : "";
  return `<div class="ag-prov ${using ? "on" : ""}"><div class="ag-ph"><b>${esc(p.name)}</b>${using ? `<span class="chip good">In use</span>` : ""}${tested}<span class="spacer"></span>${p.key_url ? `<a href="${esc(p.key_url)}" data-ext="${esc(p.key_url)}" class="linkbtn">${p.local ? "Download" : "Get a key"} ↗</a>` : ""}</div>
  <div class="muted" style="font-size:12.5px">${esc(p.free)}${p.note ? " " + esc(p.note) : ""}</div>
  <div class="ag-pr">${p.needs_key ? `<input type="password" id="key-${esc(p.id)}" aria-label="${esc(p.name)} API key" placeholder="${p.has_key ? "Saved: " + esc(p.key_mask) : "Paste your API key"}">` : ""}${p.needs_account ? `<input id="acc-${esc(p.id)}" aria-label="${esc(p.name)} account id" placeholder="Account id" value="${esc(p.account)}">` : ""}
   ${p.needs_key || p.needs_account ? `<button class="pill-btn" data-ag="savekey" data-id="${esc(p.id)}">Save</button>` : ""}
   ${p.ready ? `<button class="pill-btn" data-ag="test" data-id="${esc(p.id)}">${tr && tr.busy ? '<span class="spin sm"></span> Testing…' : "Test"}</button><button class="pill-btn" data-ag="models" data-id="${esc(p.id)}" title="Fetch the live model list">↻ Models</button><button class="${using ? "pill-btn" : "primary"}" data-ag="use" data-id="${esc(p.id)}">${using ? "Using" : "Use"}</button>` : ""}
   ${p.has_key ? `<button class="linkbtn" data-ag="clearkey" data-id="${esc(p.id)}">Remove key</button>` : ""}${p.custom ? `<button class="linkbtn" data-ag="rmcustom" data-id="${esc(p.id)}">Remove</button>` : ""}</div>
  ${tr && tr.steps ? `<div class="ag-test">${tr.steps.map(s => `<div>${s.ok ? "✓" : "✕"} <b>${esc(s.step)}</b> · ${esc(s.detail)}</div>`).join("")}${tr.model ? `<div class="muted">model: ${esc(tr.model)}${tr.seconds ? " · " + tr.seconds + "s" : ""}</div>` : ""}</div>` : tr && tr.error ? `<div class="errbox">${esc(tr.error)}</div>` : ""}
  ${p.ready && p.models.length ? `<div class="muted" style="font-size:12px">${p.models.length} models · ${esc(p.models.slice(0, 6).join(", "))}${p.models.length > 6 ? "…" : ""}</div>` : ""}</div>`;
}
function offlineHTML() {
  const L = AG.local; if (!L) return loadingBox();
  const srv = L.server; const rt = L.runtime; const dls = (L.downloads || []).filter(d => d.status !== "done" || Date.now() / 1000 - d.started < 30);
  const dl = dls.length ? `<h3 class="ag-h3">Downloads</h3>${dls.map(d => `<div class="ag-dl"><div class="row"><b>${esc(d.name)}</b><span class="spacer"></span><span class="muted">${d.status === "running" ? `${fmtN(d.done / 1e6)} / ${d.total ? fmtN(d.total / 1e6) : "?"} MB · ${d.speed ? (d.speed / 1e6).toFixed(1) + " MB/s" : ""}` : esc(d.status)}${d.error ? " · " + esc(d.error) : ""}</span>${d.status === "running" ? `<button class="linkbtn" data-ag="dlcancel" data-id="${esc(d.id)}">Cancel</button>` : ""}</div><div class="pbar"><i style="width:${d.pct || (d.status === "done" ? 100 : 0)}%"></i></div></div>`).join("")}` : "";
  const inst = L.installed.map(m => {const on = srv.path === m.path; return `<div class="ag-mrow"><div><b>${esc(m.name)}</b><div class="muted" style="font-size:12px">${esc(m.file)} · ${m.gb} GB</div></div><span class="spacer"></span>
    ${on ? `<span class="chip ${srv.ready ? "good" : "warn"}">${srv.ready ? "Loaded" : "Starting…"}</span><button class="pill-btn" data-ag="unload">Unload</button>` : `<button class="primary" data-ag="load" data-path="${esc(m.path)}" ${rt.llama ? "" : "disabled title='Install the offline runtime first'"}>Load</button>`}
    <button class="linkbtn" data-ag="delmodel" data-path="${esc(m.path)}">Delete</button></div>`}).join("");
  const cat = L.catalogue.map(c => {const have = L.installed.some(m => m.file === c.file); return `<div class="ag-mrow"><div><b>${esc(c.name)}</b> <span class="muted">· ${c.gb} GB · needs ~${c.ram} GB RAM</span><div class="muted" style="font-size:12px">${esc(c.note)}</div></div><span class="spacer"></span>${have ? `<span class="chip good">Downloaded</span>` : `<button class="pill-btn" data-ag="dl" data-repo="${esc(c.repo)}" data-file="${esc(c.file)}">Download</button>`}</div>`}).join("");
  const hf = AG.hf || {mode: "gguf"};
  const hfres = hf.loading ? loadingBox() : hf.error ? `<div class="errbox">${esc(hf.error)}</div>` : (hf.results || []).map(r => `<div class="ag-mrow"><div><b>${esc(r.repo)}</b>${r.gated ? ` <span class="chip warn">needs access</span>` : ""}<div class="muted" style="font-size:12px">${fmtN(r.downloads || 0)} downloads · ${fmtN(r.likes || 0)} likes${r.updated ? " · updated " + esc(r.updated) : ""}</div>
    ${hf.files && hf.files.repo === r.repo ? `<div class="ag-files2">${hf.files.list.map(f => `<button class="pill-btn" data-ag="dl" data-repo="${esc(r.repo)}" data-file="${esc(f.file)}" title="${esc(f.file)}">⤓ ${esc(f.quant || f.file)} · ${f.gb} GB</button>`).join("") || "<span class='muted'>No single-file GGUF models in this repository.</span>"}</div>` : ""}</div><span class="spacer"></span>
    ${r.mode === "online" ? `<button class="primary" data-ag="hfuse" data-repo="${esc(r.repo)}" ${hfp.has_key ? "" : "disabled title='Add your Hugging Face token first'"}>Use online</button>` : `<button class="pill-btn" data-ag="hffiles" data-repo="${esc(r.repo)}">Choose file ▾</button>`}</div>`).join("");
  const apps = L.local_apps || {};
  const appRow = (id, name) => apps[id] == null ? `<div class="muted">${esc(name)}: not running</div>` : `<div><b>${esc(name)}</b>: ${apps[id].length} model(s) ${apps[id].length ? "· " + esc(apps[id].slice(0, 6).join(", ")) : ""} <button class="linkbtn" data-ag="use" data-id="${id}">Use</button></div>`;
  const hfp = (AG.cfg.providers || []).find(p => p.id === "huggingface") || {};
  return `<div class="note">🔒 Offline models run on this PC. Downloads need internet once; after that they work without it. Speed depends on the PC (8–16 GB RAM recommended).</div>
  <h3 class="ag-h3">1 · Offline runtime (llama.cpp)</h3>
  <div class="ag-mrow"><div>${rt.llama ? `<span class="chip good">Installed · ${rt.variant === "gpu" ? "GPU (Vulkan)" : "CPU"}</span> <span class="muted" style="font-size:12px">${rt.cores} CPU threads</span>` : `<span class="chip warn">Not installed</span> <span class="muted">30–200 MB from the official llama.cpp releases</span>`}
    <div class="muted" style="font-size:12px;margin-top:3px">GPU version: much faster on PCs with a graphics card (NVIDIA, AMD or Intel Arc/Iris). If it cannot start, Stock Compass falls back to the CPU automatically.</div></div><span class="spacer"></span>
    <button class="pill-btn" data-ag="runtime" data-kind="llama" data-variant="cpu">${rt.llama && rt.variant !== "gpu" ? "Update" : "Install"} CPU version</button><button class="primary" data-ag="runtime" data-kind="llama" data-variant="gpu">${rt.llama && rt.variant === "gpu" ? "Update" : "Install"} GPU version</button></div>
  ${srv.running ? `<div class="ag-mrow"><div><b>Running:</b> ${esc(srv.model)} ${srv.ready ? `<span class="chip good">Ready</span>` : `<span class="chip warn">Loading into memory…</span>`} ${srv.gpu ? `<span class="chip neutral">GPU</span>` : ""}${srv.fast ? `<span class="chip neutral">Flash attention</span>` : ""}<div class="muted" style="font-size:12px">${esc((srv.log || []).slice(-1)[0] || "")}</div></div><span class="spacer"></span><button class="pill-btn" data-ag="unload">Unload</button></div>` : ""}
  ${dl}
  <h3 class="ag-h3">2 · Your models</h3>${inst || `<p class="muted">No models yet. Download one below, or <button class="linkbtn" data-ag="link">use a .gguf file already on this PC</button>.</p>`}
  ${inst ? `<p><button class="linkbtn" data-ag="link">＋ Use a .gguf file already on this PC</button> · <span class="muted" style="font-size:12px">Folder: ${esc(L.folder)}</span></p>` : ""}
  <h3 class="ag-h3">3 · Recommended models</h3>${cat}
  <h3 class="ag-h3">🤗 Hugging Face</h3>
  <div class="ag-prov"><div class="ag-pr"><input type="password" id="key-huggingface" aria-label="Hugging Face token" placeholder="${hfp.has_key ? "Token saved: " + esc(hfp.key_mask) : "Hugging Face token (free): needed for online models and gated downloads"}"><button class="pill-btn" data-ag="savekey" data-id="huggingface">Save</button><a class="linkbtn" data-ext="https://huggingface.co/settings/tokens" href="https://huggingface.co/settings/tokens">Get a token ↗</a></div>
  <div class="tabs"><button data-ag="hfmode" data-mode="gguf" aria-pressed="${hf.mode !== "online"}">Download & run on this PC</button><button data-ag="hfmode" data-mode="online" aria-pressed="${hf.mode === "online"}">Run online (Inference Providers)</button></div>
  <div class="ag-form"><input id="hf-q" aria-label="Search Hugging Face" placeholder="${hf.mode === "online" ? "Search chat models, e.g. llama, qwen, deepseek" : "Search GGUF models, e.g. qwen 7b instruct"}" value="${esc(hf.q || "")}"><button class="pill-btn" data-ag="hfsearch">Search</button><button class="linkbtn" data-ag="hftrend">Trending</button></div>
  ${hfres}</div>
  <h3 class="ag-h3">Other apps on this PC</h3>${appRow("ollama", "Ollama")}${appRow("lmstudio", "LM Studio")}${appRow("jan", "Jan")}
  ${apps.ollama != null ? `<div class="ag-form"><input id="ol-name" placeholder="Pull an Ollama model, e.g. qwen2.5:7b"><button class="pill-btn" data-ag="olpull">Pull</button></div>` : ""}
  <p><button class="linkbtn" data-ag="detect">↻ Look again</button></p>
  <h3 class="ag-h3">Voice typing without internet</h3>
  <div class="ag-mrow"><div>${rt.whisper ? `<span class="chip good">Whisper runtime installed</span>` : `<span class="chip warn">Whisper runtime not installed</span> <span class="muted">(Windows)</span>`}</div><span class="spacer"></span><button class="pill-btn" data-ag="runtime" data-kind="whisper">${rt.whisper ? "Update" : "Install"}</button></div>
  ${L.whisper.map(w => `<div class="ag-mrow"><div><b>${esc(w.name)}</b> <span class="muted">· ${w.mb} MB</span></div><span class="spacer"></span>${w.installed ? `<span class="chip good">Downloaded</span>` : `<button class="pill-btn" data-ag="whisper" data-id="${esc(w.id)}">Download</button>`}</div>`).join("")}`;
}
function memoryHTML() {
  const M = AG.mem; if (!M) return loadingBox();
  return `<div class="note">🧠 The agent remembers what you tell it, its own conclusions, and a short digest after every import — so it can answer "what happened last month at Fortress?". It also reads the full Stock Compass database directly.</div>
  <div class="ag-form"><label class="sr" for="mem-add">Teach the agent</label><input id="mem-add" placeholder="Teach the agent something, e.g. 'Packages Mall LHH is being refitted until 15 Oct'"><button class="primary" data-ag="memadd">Remember</button></div>
  <h3 class="ag-h3">Glossary</h3><p class="muted" style="font-size:12.5px">Meanings of headers, codes and terms. The agent asks when it meets something new and saves your answer here; the importer uses it too.</p>
  <div class="ag-form"><label class="sr" for="gl-term">Term</label><input id="gl-term" style="max-width:180px" placeholder="Term, e.g. RTS"><label class="sr" for="gl-mean">Meaning</label><input id="gl-mean" placeholder="Meaning, e.g. return to supplier"><button class="primary" data-ag="glossadd">Add</button></div>
  ${(AG.gl && AG.gl.glossary.length) ? `<div class="ag-gloss">${AG.gl.glossary.map(g => `<div class="ag-mem"><div class="ag-memt">${esc(g.text)}</div><button class="linkbtn" data-ag="memdel" data-id="${esc(g.id)}">Forget</button></div>`).join("")}</div>` : `<p class="muted">No meanings saved yet.</p>`}
  <h3 class="ag-h3">Memory</h3>
  ${M.memory.filter(m => m.kind !== "definition").length ? M.memory.filter(m => m.kind !== "definition").map(m => `<div class="ag-mem"><div><span class="chip ${m.kind === "digest" ? "neutral" : m.pinned ? "good" : "warn"}">${esc(m.pinned ? "pinned" : m.kind)}</span> <span class="muted" style="font-size:12px">${esc(m.ts)} · ${esc(m.source)}</span><div class="ag-memt">${esc(m.text).replace(/\n/g, "<br>")}</div></div><button class="linkbtn" data-ag="memdel" data-id="${esc(m.id)}">Forget</button></div>`).join("") : `<p class="muted">Nothing remembered yet.</p>`}
  <h3 class="ag-h3">Changes made by the agent</h3>${M.log.length ? M.log.map(l => `<div class="ag-mem"><div><b>${esc(l.action)}</b> <span class="muted" style="font-size:12px">${esc(l.ts)}</span><div class="ag-memt muted">${esc(l.detail)}</div></div></div>`).join("") : `<p class="muted">No changes yet.</p>`}`;
}
function behaviourHTML() {
  const c = AG.cfg || {};
  return `<div class="ag-set"><label class="ag-tog"><input type="checkbox" id="ag-ask" ${c.ask_changes ? "checked" : ""}> <span><b>Ask before changes</b><br><span class="muted">The agent asks for approval before logging promotions, changing targets, thresholds or store names.</span></span></label>
  <div class="fbox" style="height:auto;padding:6px 10px"><label for="ag-effd">Default effort</label><select id="ag-effd">${[["low", "Quick"], ["medium", "Balanced"], ["high", "Deep"]].map(([k, n]) => `<option value="${k}" ${c.effort === k ? "selected" : ""}>${n}</option>`).join("")}</select></div>
  <div class="fbox" style="height:auto;padding:6px 10px"><label for="ag-voice">Voice typing</label><select id="ag-voice">${[["auto", "Offline, else cloud"], ["offline", "Only offline (this PC)"], ["cloud", "Only cloud (Groq/OpenAI key)"]].map(([k, n]) => `<option value="${k}" ${c.voice === k ? "selected" : ""}>${n}</option>`).join("")}</select></div>
  <p class="muted" style="font-size:12.5px">Effort: Quick = fewer steps, fastest; Balanced = default; Deep = more tool steps and longer thinking on models that support it.</p></div>`;
}

/* ---------------- events ---------------- */
document.addEventListener("click", async e => {
  const x = e.target.closest("[data-ext]"); if (x) {e.preventDefault(); api("open_url", {url: x.dataset.ext}); return}
  const g = e.target.closest("[data-ag]"); if (!g) return; const d = g.dataset; const a = d.ag;
  if (a === "new") {AG.chat = null; AG.msgs = []; AG.live = null; render(); agentFocus()}
  else if (a === "open") agentOpenChat(d.id);
  else if (a === "rename") {const c = AG.chats.find(x => x.id === d.id); const nt = prompt("Rename chat", c ? c.title : ""); if (nt) {await api("agent_chat_rename", {chat: d.id, title: nt}); AG.chats = (await api("agent_chats")).chats; render()}}
  else if (a === "delchat") {if (confirm("Delete this conversation?")) {await api("agent_chat_delete", {chat: d.id}); if (AG.chat === d.id) {AG.chat = null; AG.msgs = []} AG.chats = (await api("agent_chats")).chats; render()}}
  else if (a === "suggest") agentSend(d.q);
  else if (a === "send") agentSend();
  else if (a === "stop") {if (AG.run) api("agent_stop", {run: AG.run.id})}
  else if (a === "attach") $("#ag-file").click();
  else if (a === "rmfile") {AG.files = AG.files.filter(f => (f.id || f.name) !== d.id); render()}
  else if (a === "import") {const r = await api("agent_import_attachment", {id: d.id}); toast(r.error || "Importing… see Add reports for progress"); pollImport()}
  else if (a === "mic") agentMic();
  else if (a === "toggle") {AG.open[d.k] = !AG.open[d.k]; rerenderMsgs()}
  else if (a === "approve" || a === "decline") {if (AG.run) api("agent_approve", {run: AG.run.id, action: d.id, yes: a === "approve"}); g.disabled = true}
  else if (a === "qpick" || a === "qsend" || a === "qskip") {
    const v = a === "qpick" ? d.v : a === "qsend" ? (($("#q-" + d.id) || {}).value || AG.qd[d.id] || "").trim() : "";
    if (a === "qsend" && !v) {toast("Type an answer, or Skip"); return}
    if (AG.run) api("agent_answer", {run: AG.run.id, id: d.id, answer: v}); delete AG.qd[d.id]; g.disabled = true}
  else if (a === "glossadd") {const t = ($("#gl-term") || {}).value, m = ($("#gl-mean") || {}).value; if (!t || !m) {toast("Term and meaning are needed"); return} AG.gl = await api("agent_define", {term: t, meaning: m}); render()}
  else if (a === "openfile") {const r = await api("agent_open", {path: d.path}); if (r.error) toast(r.error)}
  else if (a === "settings") agentSettings(d.tab);
  else if (a === "settab") agentSettings(d.tab);
  else if (a === "savekey") {const k = $("#key-" + d.id), ac = $("#acc-" + d.id); AG.cfg = await api("agent_set_key", {provider: d.id, key: k && k.value ? k.value : null, account: ac ? ac.value : null}); AG.tests[d.id] = null; render(); toast("Saved")}
  else if (a === "clearkey") {AG.cfg = await api("agent_set_key", {provider: d.id, key: ""}); render()}
  else if (a === "test") {AG.tests[d.id] = {busy: true}; render(); const pick = currentPick(); AG.tests[d.id] = await api("agent_test", {provider: d.id, model: pick && pick.p.id === d.id ? pick.m : null}); AG.cfg = await api("agent_config"); render()}
  else if (a === "models") {const r = await api("agent_models", {provider: d.id}); if (r.error) toast(r.error); AG.cfg = await api("agent_config"); render()}
  else if (a === "use") {const p = AG.cfg.providers.find(x => x.id === d.id); AG.cfg = await api("agent_prefs", {provider: d.id, model: (p && p.models[0]) || ""}); render(); toast(`Using ${p ? p.name : d.id}`)}
  else if (a === "addcustom") {const v = id => ($("#" + id) || {}).value || ""; if (!v("cu-name") || !v("cu-url")) {toast("Name and base URL are needed"); return} AG.cfg = await api("agent_custom_add", {name: v("cu-name"), base_url: v("cu-url"), key: v("cu-key"), models: v("cu-models"), kind: v("cu-kind")}); render()}
  else if (a === "rmcustom") {AG.cfg = await api("agent_custom_remove", {provider: d.id}); render()}
  else if (a === "runtime") {const r = await api("local_runtime", {kind: d.kind, variant: d.variant || "cpu"}); if (r.error) toast(r.error); agentLocal()}
  else if (a === "dl") {const r = await api("local_download", {repo: d.repo, file: d.file}); if (r.error) toast(r.error); agentLocal()}
  else if (a === "dlcancel") {await api("local_cancel", {job: d.id}); agentLocal()}
  else if (a === "load") {const r = await api("local_load", {path: d.path}); if (r.error) toast(r.error); AG.cfg = await api("agent_config"); agentLocal()}
  else if (a === "unload") {await api("local_unload"); AG.cfg = await api("agent_config"); agentLocal()}
  else if (a === "delmodel") {if (confirm("Delete this model file from the PC?")) {await api("local_delete", {path: d.path}); agentLocal()}}
  else if (a === "link") {await api("local_link"); agentLocal()}
  else if (a === "detect") agentLocal(true);
  else if (a === "olpull") {const n = ($("#ol-name") || {}).value; if (n) {await api("local_ollama_pull", {name: n}); agentLocal()}}
  else if (a === "whisper") {await api("local_whisper", {id: d.id}); agentLocal()}
  else if (a === "hfsearch" || a === "hftrend") {const q = a === "hftrend" ? "" : ($("#hf-q") || {}).value || ""; const mode = (AG.hf || {}).mode || "gguf"; AG.hf = {q, mode, loading: true}; render(); const r = await api("local_search", {query: q, mode}); AG.hf = {q, mode, results: r.results, error: r.error ? "Could not reach Hugging Face: " + r.error : null}; render()}
  else if (a === "hfmode") {AG.hf = {mode: d.mode, q: (AG.hf || {}).q || ""}; render()}
  else if (a === "hfuse") {AG.cfg = await api("agent_prefs", {provider: "huggingface", model: d.repo}); render(); toast("Using " + d.repo + " through Hugging Face")}
  else if (a === "testall") {AG.testAll = await api("agent_test_all", {start: true}); render(); const tick = async () => {AG.testAll = await api("agent_test_all", {start: false}); if (S.drawer && S.drawer.kind === "agset") render(); if (AG.testAll.running) setTimeout(tick, 700); else AG.cfg = await api("agent_config")}; setTimeout(tick, 500)}
  else if (a === "hffiles") {const r = await api("local_files", {repo: d.repo}); AG.hf.files = {repo: d.repo, list: r.files || []}; if (r.error) toast(r.error); render()}
  else if (a === "memadd") {const v = ($("#mem-add") || {}).value; if (v) {AG.mem = await api("agent_memory_add", {text: v}); render()}}
  else if (a === "memdel") {AG.mem = await api("agent_memory_delete", {id: d.id}); AG.gl = await api("agent_glossary"); render()}
});
document.addEventListener("keydown", e => {
  if (e.target.id === "ag-input" && e.key === "Enter" && !e.shiftKey && !e.isComposing) {e.preventDefault(); agentSend()}
  if (e.target.dataset && e.target.dataset.qid && e.key === "Enter") {e.preventDefault(); const b = document.querySelector(`[data-ag="qsend"][data-id="${e.target.dataset.qid}"]`); if (b) b.click()}
});
document.addEventListener("input", e => {
  if (e.target.dataset && e.target.dataset.qid) AG.qd[e.target.dataset.qid] = e.target.value;
  if (e.target.id === "ag-input") {AG.draft = e.target.value; const t = e.target; t.style.height = "auto"; t.style.height = Math.min(260, t.scrollHeight) + "px"}
});
document.addEventListener("change", async e => {
  const el = e.target;
  if (el.id === "ag-file") {await agentAddFiles([...el.files]); el.value = ""}
  else if (el.id === "ag-model") {const [p, ...m] = el.value.split("|"); AG.cfg = await api("agent_prefs", {provider: p, model: m.join("|")}); render(); agentFocus()}
  else if (el.id === "ag-effort" || el.id === "ag-effd") {AG.cfg = await api("agent_prefs", {effort: el.value}); render()}
  else if (el.id === "ag-ask") {AG.cfg = await api("agent_prefs", {ask_changes: el.checked})}
  else if (el.id === "ag-voice") {AG.cfg = await api("agent_prefs", {voice: el.value})}
});
document.addEventListener("dragover", e => {if (S.page === "agent") {e.preventDefault(); const b = $("#ag-drop"); if (b) b.classList.add("over")}});
document.addEventListener("drop", e => {if (S.page === "agent" && e.dataTransfer && e.dataTransfer.files.length) {e.preventDefault(); agentAddFiles([...e.dataTransfer.files])}});
document.addEventListener("paste", e => {if (e.target.id === "ag-input" && e.clipboardData && e.clipboardData.files.length) {e.preventDefault(); agentAddFiles([...e.clipboardData.files])}});
