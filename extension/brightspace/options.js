import { appOrigin, readErrorsNote } from "./lib.js";

const $ = (s) => document.querySelector(s);
let courses = [];
let cfCourses = [];
let local = { cfKeys: {}, auto: {}, status: {}, confirmed: {} };
const KNOWN = [{ org: "564701", name: "Public International Law", cid: "" }, { org: "564708", name: "LaPoPo", cid: "" }];
const send = (msg) => chrome.runtime.sendMessage(msg).then((r) => { if (!r || !r.ok) throw new Error((r && r.error) || "no answer"); return r.data; });

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const day = (ms) => new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

function keyLine(cid) {
  const k = cid && local.cfKeys[cid];
  if (!k || !k.token) return `<span class="small muted">no sync key</span>`;
  const soon = k.expires && k.expires - Date.now() < 7 * 86400000;
  return `<span class="small${soon ? "" : " muted"}">key ••••${esc(k.token.slice(-4))}${k.expires ? ` · ${soon ? "expires" : "until"} ${day(k.expires)}` : ""}</span>`;
}

function render() {
  $("#courses").innerHTML = courses.map((c, i) => `<div class="item">
    <label class="field" style="flex:1">Brightspace course number<input type="text" data-i="${i}" data-f="org" value="${esc(c.org || "")}" placeholder="564706"></label>
    <label class="field" style="flex:1">Name<input type="text" data-i="${i}" data-f="name" value="${esc(c.name || "")}" placeholder="Property Law"></label>
    <label class="field" style="flex:1">CognitioFlow course${cfCourses.length ? "" : " id"}
      ${cfCourses.length
        ? `<select data-i="${i}" data-f="cid">${["", ...cfCourses.map((x) => x.id)].map((id) => `<option value="${esc(id)}"${id === c.cid ? " selected" : ""}>${esc(id ? (cfCourses.find((x) => x.id === id) || {}).name || id : "— pick one —")}</option>`).join("")}</select>`
        : `<input type="text" data-i="${i}" data-f="cid" value="${esc(c.cid || "")}" placeholder="eu">`}</label>
    <button class="btn ghost" data-del="${i}" title="Remove">×</button></div>
    <div class="sync" data-row="${i}">
      ${keyLine(c.cid)}
      <button class="btn ghost small" data-act="mint" data-i="${i}" title="Makes a 90-day write key for this one course through your signed-in CognitioFlow tab">Create sync key</button>
      <input type="password" data-paste="${i}" placeholder="or paste cfw_… key" autocomplete="off">
      <button class="btn ghost small" data-act="paste" data-i="${i}">Use</button>
      <button class="btn ghost small" data-act="test" data-i="${i}">Test</button>
      <button class="btn ghost small" data-act="forget" data-i="${i}">Remove key</button>
      <button class="btn ghost small" data-act="match" data-i="${i}" title="Marks files CognitioFlow already has (same file name) as synced; everything else will be uploaded">Mark what CognitioFlow already has</button>
      <button class="btn ghost small" data-act="all" data-i="${i}" title="Marks everything on Brightspace now as synced, uploads nothing">Mark everything as synced</button>
      <label class="small"><input type="checkbox" data-auto="${i}"${local.auto[c.org] ? " checked" : ""}${local.confirmed[c.org] ? "" : " disabled title=\"Run a baseline or review the first list in the popup first\""}> Auto</label>
      <span class="small muted" data-msg="${i}">${esc(statusText(c.org))}</span>
    </div>`).join("") || `<div class="empty small">No courses yet.</div>`;
  $("#courses").querySelectorAll("[data-f]").forEach((el) => (el.onchange = () => { courses[+el.dataset.i][el.dataset.f] = el.value.trim(); render(); }));
  $("#courses").querySelectorAll("[data-del]").forEach((el) => (el.onclick = () => { courses.splice(+el.dataset.del, 1); render(); }));
  $("#courses").querySelectorAll("[data-act]").forEach((el) => (el.onclick = () => act(el.dataset.act, +el.dataset.i)));
  $("#courses").querySelectorAll("[data-auto]").forEach((el) => (el.onchange = () => act(el.checked ? "auto-on" : "auto-off", +el.dataset.auto)));
}

function statusText(org) {
  const s = local.status[org];
  if (!s) return local.confirmed[org] ? "" : "first run: baseline needed";
  const empty = s.emptyPages && s.emptyPages.length ? ` · ${s.emptyPages.length} page(s) had no file link: ${s.emptyPages.slice(0, 3).join(", ")}` : "";
  const unread = readErrorsNote(s, !!local.confirmed[org]);
  return `${s.state}${s.detail ? ` — ${s.detail}` : ""}${s.uploaded ? ` · ${s.uploaded} uploaded last run` : ""}${empty}${unread ? ` · ${unread}` : ""}`;
}

const say = (i, text) => { const el = document.querySelector(`[data-msg="${i}"]`); if (el) el.textContent = text; };

async function refreshLocal() {
  local = await chrome.storage.local.get({ cfKeys: {}, auto: {}, status: {}, confirmed: {} });
}

async function appTab() {
  const url = $("#appUrl").value.trim();
  if (!url) throw new Error("set the CognitioFlow address first");
  const [tab] = await chrome.tabs.query({ url: `${new URL(url).origin}/*` });
  if (!tab) throw new Error("open CognitioFlow in a tab and sign in, then try again");
  await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content-app.js"] });
  return tab;
}
const askApp = async (msg) => {
  const tab = await appTab();
  const r = await chrome.tabs.sendMessage(tab.id, msg);
  if (!r || !r.ok) throw new Error((r && r.error) || "no answer from the CognitioFlow tab");
  return r.data;
};

/** The CognitioFlow origin typed in the box, or an error: https only (http only for localhost). */
function typedOrigin() {
  const origin = appOrigin($("#appUrl").value.trim());
  if (!origin) throw new Error("the CognitioFlow address must start with https:// (http only for localhost)");
  return origin;
}

async function saveConfig() {
  if ($("#appUrl").value.trim()) typedOrigin();
  const hours = Math.min(48, Math.max(1, Number($("#hours").value) || 6));
  await chrome.storage.sync.set({ appUrl: $("#appUrl").value.trim(), courses: courses.filter((c) => c.org).map(({ org, name, cid }) => ({ org, name, cid })), syncHours: hours });
  await send({ type: "schedule" }).catch(() => {});
}

async function setKey(cid, key) {
  const { cfKeys } = await chrome.storage.local.get({ cfKeys: {} });   // local only: never storage.sync
  if (key) cfKeys[cid] = key; else delete cfKeys[cid];
  await chrome.storage.local.set({ cfKeys });
}

/** Revoke a key we are dropping, through the signed-in CognitioFlow tab. null = nothing to revoke. */
async function revoke(key) {
  if (!key || !key.id) return null;
  try { await askApp({ type: "revokeKey", id: key.id }); return true; } catch { return false; }
}

async function act(what, i) {
  const c = courses[i];
  if (!c || !c.org) return;
  try {
    await saveConfig();
    if (["mint", "paste", "test", "forget", "match"].includes(what) && !c.cid) throw new Error("pick the CognitioFlow course first");
    if (what === "mint") {
      say(i, "Making a key…");
      const old = local.cfKeys[c.cid];
      const origin = typedOrigin();   // the key is bound to the address it was made on, and never sent elsewhere
      await setKey(c.cid, { ...(await askApp({ type: "mintKey", cid: c.cid, ttlDays: 90 })), origin });
      const revoked = await revoke(old);
      await refreshLocal(); render();
      say(i, `Key saved on this computer.${revoked === false ? " The old key could not be revoked — revoke it in CognitioFlow." : ""}`);
      return;
    } else if (what === "paste") {
      const box = document.querySelector(`[data-paste="${i}"]`);
      const token = box.value.trim();
      if (!/^cfw_[A-Za-z0-9_-]{20,}$/.test(token)) throw new Error("that is not a cfw_ write key");
      await setKey(c.cid, { token, courseId: c.cid, expires: null, id: "", origin: typedOrigin() });
      box.value = "";
      const t = await send({ type: "test-key", cid: c.cid });
      say(i, t.ok ? "Key saved and accepted." : `Key saved, but: ${t.state}`);
    } else if (what === "test") {
      const t = await send({ type: "test-key", cid: c.cid });
      say(i, t.ok ? "Key works for this course." : `${t.state}${t.detail ? ` (${t.detail})` : ""}`);
      return;
    } else if (what === "forget") {
      const old = local.cfKeys[c.cid];
      await setKey(c.cid, null);
      const revoked = await revoke(old);
      await refreshLocal(); render();
      say(i, revoked === true ? "Key removed and revoked." : revoked === null ? "Key removed here. It was pasted, so revoke it in CognitioFlow yourself." : "Removed here, but not revoked — revoke it in CognitioFlow (DELETE /api/tokens/{id}).");
      return;
    } else if (what === "match" || what === "all") {
      say(i, "Reading Brightspace…");
      const names = what === "match" ? await askApp({ type: "files", cid: c.cid }) : [];
      const r = await send({ type: "baseline", org: c.org, mode: what, names });
      await refreshLocal(); render(); say(i, `${r.marked.length} marked as synced${r.left.length ? `; ${r.left.length} will upload when Auto is on: ${r.left.slice(0, 5).join(", ")}${r.left.length > 5 ? "…" : ""}` : "; nothing left to upload"}`);
      return;
    } else if (what === "auto-on" || what === "auto-off") {
      await send({ type: "set-auto", org: c.org, on: what === "auto-on" });
    }
    await refreshLocal(); render();
  } catch (e) {
    say(i, String(e.message || e));
  }
}

async function grant() {
  const url = $("#appUrl").value.trim();
  if (!url) return;
  let origin;
  origin = appOrigin(url);
  if (!origin) { $("#grantState").textContent = "That is not a valid https address."; return; }
  origin += "/*";
  const ok = await chrome.permissions.request({ origins: [origin] });
  $("#grantState").textContent = ok ? "Allowed." : "Not allowed — uploads will fail without it.";
}

/** Names straight from the two open tabs, so nothing has to be typed twice. */
async function detect() {
  const [bs] = await chrome.tabs.query({ url: "https://brightspace.rug.nl/*" });
  if (bs) {
    try {
      const r = await chrome.tabs.sendMessage(bs.id, { type: "courses" });
      if (r && r.ok) for (const e of r.data || []) {
        const o = e.OrgUnit || {};
        if (!o.Id || courses.some((c) => String(c.org) === String(o.Id))) continue;
        courses.push({ org: String(o.Id), name: o.Name || "", cid: "" });
      }
    } catch {}
  }
  try { cfCourses = (await askApp({ type: "courses" })) || []; } catch {}
  render();
}

(async () => {
  const cfg = await chrome.storage.sync.get({ appUrl: "", courses: [], syncHours: 6 });
  $("#appUrl").value = cfg.appUrl; courses = cfg.courses; $("#hours").value = cfg.syncHours;
  await refreshLocal();
  render();
})();

$("#addRow").onclick = () => { courses.push({ org: "", name: "", cid: "" }); render(); };
$("#addKnown").onclick = () => { for (const k of KNOWN) if (!courses.some((c) => String(c.org) === k.org)) courses.push({ ...k }); render(); };
$("#grant").onclick = grant;
$("#detect").onclick = detect;
$("#save").onclick = async () => {
  try { await saveConfig(); } catch (e) { $("#saved").textContent = String(e.message || e); return; }
  $("#saved").textContent = "Saved.";
  setTimeout(() => ($("#saved").textContent = ""), 2000);
};
$("#syncNow").onclick = async () => {
  $("#syncState").textContent = "Syncing…";
  try {
    await saveConfig();
    const r = await send({ type: "sync-now" });
    $("#syncState").textContent = r.skipped ? `Skipped: ${r.skipped}` : `${r.uploaded} uploaded.`;
  } catch (e) { $("#syncState").textContent = String(e.message || e); }
  await refreshLocal(); render();
};
