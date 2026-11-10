import { readErrorsNote } from "./lib.js";

const $ = (s) => document.querySelector(s);
const send = (msg) => chrome.runtime.sendMessage(msg).then((r) => { if (!r || !r.ok) throw new Error((r && r.error) || "no answer"); return r.data; });

let state = { courses: [], pending: {}, confirmed: {}, status: {}, log: [] };
const PROBLEM = { "login needed": "Brightspace sign-in needed — open Brightspace and sign in", "key needed": "no sync key (Options)",
  "key expired": "CognitioFlow key expired — renew it in Options", "key is for another course": "wrong key for this course (Options)",
  "key is for another address": "this key was made for another CognitioFlow address — create it again in Options",
  "no access to CognitioFlow": "allow the CognitioFlow address in Options", error: "some files failed; they will be retried" };

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function render() {
  const list = $("#list");
  list.innerHTML = "";
  let total = 0;
  for (const c of state.courses) {
    const items = state.pending[c.org] || [];
    total += items.length;
    const st = state.status[c.org];
    if (st && PROBLEM[st.state]) {
      const warn = document.createElement("div");
      warn.className = "small";
      warn.textContent = `${c.name || c.org}: ${PROBLEM[st.state]}${st.detail && st.state === "error" ? ` (${st.detail})` : ""}`;
      list.appendChild(warn);
    }
    const unread = readErrorsNote(st, !!state.confirmed[c.org]);   // shown whatever the state: these files are missing from the list below
    if (unread) {
      const warn = document.createElement("div");
      warn.className = "small";
      warn.textContent = `${c.name || c.org}: ${unread}.`;
      list.appendChild(warn);
    }
    if (!items.length) continue;
    const first = !state.confirmed[c.org];
    const box = document.createElement("div");
    box.className = "group";
    box.innerHTML = `<h2>${esc(c.name || c.org)}${first ? " · first time, check the list" : ""}</h2>` +
      (first ? `<div class="small muted">Choose for every file: tick and Add, or tick and “I already have these”. Unticked files wait here; nothing uploads automatically until the whole list is decided.</div>` : "") +
      items.map((i) => `<div class="item"><input type="checkbox" checked data-org="${esc(c.org)}" data-key="${esc(i.key)}" id="k${esc(i.key)}">
        <label for="k${esc(i.key)}"><span class="name">${esc(i.title)}</span>
        <div class="small muted">${esc(i.module || "")}${i.name !== i.title ? " · " + esc(i.name) : ""}</div></label>
        ${i.week ? `<span class="week">Week ${esc(i.week)}</span>` : ""}</div>`).join("");
    list.appendChild(box);
  }
  $("#actions").hidden = !total;
  $("#count").textContent = total ? `${total} file${total === 1 ? "" : "s"} found` : "";
  if (!total && !list.children.length) list.innerHTML = `<div class="empty">Nothing new.<div class="small">Your courses are up to date.</div></div>`;
  const name = (org) => (state.courses.find((c) => String(c.org) === String(org)) || {}).name || org;
  $("#log").innerHTML = state.log.slice(-30).reverse().map((l) => `<div>${esc(new Date(l.at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }))} · ${esc(name(l.org))} · ${esc(l.name || "")} · ${esc(l.action)}${l.error ? ` — <span class="muted">${esc(l.error)}</span>` : ""}</div>`).join("") || `<div class="muted">Nothing yet.</div>`;
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
  let note = "";
  if (rescan) {
    $("#status").textContent = "Reading Brightspace…";
    try { const r = await send({ type: "scan", notify: false }); if (r.skipped) note = r.skipped === "already running" ? "A sync is running — showing the last result." : r.skipped; }
    catch (e) { note = String(e.message || e); }
  }
  const l = await chrome.storage.local.get({ pending: {}, confirmed: {}, lastScan: 0, status: {}, log: [] });
  state.pending = l.pending; state.confirmed = l.confirmed; state.status = l.status; state.log = l.log;
  if (note) $("#status").textContent = note;
  else $("#status").textContent = l.lastScan ? `Last checked ${new Date(l.lastScan).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : "Not checked yet";
  render();
}

async function run(type, verb) {
  const picked = chosen();
  const keys = Object.values(picked).flat();
  if (!keys.length) return;
  $("#add").disabled = $("#skip").disabled = true;
  $("#status").textContent = `${verb} ${keys.length} file${keys.length === 1 ? "" : "s"}…`;
  let added = 0; const failed = []; const held = [];
  for (const [org, ks] of Object.entries(picked)) {
    try { const r = await send({ type, org, keys: ks }); added += r.added ?? r.skipped ?? 0; (r.failed || []).forEach((f) => failed.push(f)); (r.held || []).forEach((n) => held.push(n)); }
    catch (e) { failed.push({ name: org, error: String(e.message || e) }); }
  }
  const undecided = Object.keys(picked).filter((org) => !state.confirmed[org]);
  let msg = failed.length ? `${added} added · ${failed.length} failed: ${failed.map((f) => f.name).join(", ")}` : `${added} added.`;
  if (held.length) msg += ` Already sent earlier, answer lost — check it is in CognitioFlow (not sent again): ${held.join(", ")}.`;
  $("#add").disabled = $("#skip").disabled = false;
  await load(false);
  if (undecided.some((org) => !state.confirmed[org] && (state.pending[org] || []).length))
    msg += " The rest of the first list still needs a choice (Add or “I already have these”); nothing uploads automatically until then.";
  $("#status").textContent = msg;
}

$("#rescan").onclick = () => load(true);
$("#syncNow").onclick = async () => {
  $("#syncNow").disabled = true; $("#status").textContent = "Syncing…";
  try { const r = await send({ type: "sync-now" }); $("#status").textContent = r.skipped ? r.skipped : `${r.uploaded} uploaded.`; }
  catch (e) { $("#status").textContent = String(e.message || e); }
  $("#syncNow").disabled = false;
  await load(false);
};
$("#add").onclick = () => run("take", "Adding");
$("#skip").onclick = () => run("skip", "Remembering");
$("#opts").onclick = (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); };
load(true);
