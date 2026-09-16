const $ = (s) => document.querySelector(s);
const send = (msg) => chrome.runtime.sendMessage(msg).then((r) => { if (!r || !r.ok) throw new Error((r && r.error) || "no answer"); return r.data; });

let state = { courses: [], pending: {}, confirmed: {} };

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function render() {
  const list = $("#list");
  list.innerHTML = "";
  let total = 0;
  for (const c of state.courses) {
    const items = state.pending[c.org] || [];
    total += items.length;
    if (!items.length) continue;
    const first = !state.confirmed[c.org];
    const box = document.createElement("div");
    box.className = "group";
    box.innerHTML = `<h2>${esc(c.name || c.org)}${first ? " · first time, check the list" : ""}</h2>` +
      items.map((i) => `<div class="item"><input type="checkbox" checked data-org="${esc(c.org)}" data-key="${esc(i.key)}" id="k${esc(i.key)}">
        <label for="k${esc(i.key)}"><span class="name">${esc(i.title)}</span>
        <div class="small muted">${esc(i.module || "")}${i.name !== i.title ? " · " + esc(i.name) : ""}</div></label>
        ${i.week ? `<span class="week">Week ${esc(i.week)}</span>` : ""}</div>`).join("");
    list.appendChild(box);
  }
  $("#actions").hidden = !total;
  $("#count").textContent = total ? `${total} file${total === 1 ? "" : "s"} found` : "";
  if (!total) list.innerHTML = `<div class="empty">Nothing new.<div class="small">Your courses are up to date.</div></div>`;
}

const chosen = () => {
  const out = {};
  document.querySelectorAll("input[type=checkbox]:checked").forEach((b) => (out[b.dataset.org] = [...(out[b.dataset.org] || []), b.dataset.key]));
  return out;
};

async function load(rescan) {
  const cfg = await chrome.storage.sync.get({ courses: [] });
  state.courses = cfg.courses;
  if (!state.courses.length) { $("#status").textContent = "No courses linked yet — open Options."; return; }
  if (rescan) { $("#status").textContent = "Reading Brightspace…"; const r = await send({ type: "scan", notify: false }); if (r.skipped) $("#status").textContent = "Open Brightspace in a tab, then press Check now."; }
  const l = await chrome.storage.local.get({ pending: {}, confirmed: {}, lastScan: 0 });
  state.pending = l.pending; state.confirmed = l.confirmed;
  if (!$("#status").textContent.startsWith("Open ")) $("#status").textContent = l.lastScan ? `Last checked ${new Date(l.lastScan).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : "Not checked yet";
  render();
}

async function run(type, verb) {
  const picked = chosen();
  const keys = Object.values(picked).flat();
  if (!keys.length) return;
  $("#add").disabled = $("#skip").disabled = true;
  $("#status").textContent = `${verb} ${keys.length} file${keys.length === 1 ? "" : "s"}…`;
  let added = 0; const failed = [];
  for (const [org, ks] of Object.entries(picked)) {
    try { const r = await send({ type, org, keys: ks }); added += r.added ?? r.skipped ?? 0; (r.failed || []).forEach((f) => failed.push(f)); }
    catch (e) { failed.push({ name: org, error: String(e.message || e) }); }
  }
  $("#status").textContent = failed.length ? `${added} added · ${failed.length} failed: ${failed.map((f) => f.name).join(", ")}` : `${added} added.`;
  $("#add").disabled = $("#skip").disabled = false;
  await load(false);
}

$("#rescan").onclick = () => load(true);
$("#add").onclick = () => run("take", "Adding");
$("#skip").onclick = () => run("skip", "Remembering");
$("#opts").onclick = (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); };
load(true);
