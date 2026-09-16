const $ = (s) => document.querySelector(s);
let courses = [];
let cfCourses = [];

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function render() {
  $("#courses").innerHTML = courses.map((c, i) => `<div class="item">
    <label class="field" style="flex:1">Brightspace course number<input type="text" data-i="${i}" data-f="org" value="${esc(c.org || "")}" placeholder="564706"></label>
    <label class="field" style="flex:1">Name<input type="text" data-i="${i}" data-f="name" value="${esc(c.name || "")}" placeholder="Property Law"></label>
    <label class="field" style="flex:1">CognitioFlow course${cfCourses.length ? "" : " id"}
      ${cfCourses.length
        ? `<select data-i="${i}" data-f="cid">${["", ...cfCourses.map((x) => x.id)].map((id) => `<option value="${esc(id)}"${id === c.cid ? " selected" : ""}>${esc(id ? (cfCourses.find((x) => x.id === id) || {}).name || id : "— pick one —")}</option>`).join("")}</select>`
        : `<input type="text" data-i="${i}" data-f="cid" value="${esc(c.cid || "")}" placeholder="eu">`}</label>
    <button class="btn ghost" data-del="${i}" title="Remove">×</button></div>`).join("") || `<div class="empty small">No courses yet.</div>`;
  $("#courses").querySelectorAll("[data-f]").forEach((el) => (el.onchange = () => { courses[+el.dataset.i][el.dataset.f] = el.value.trim(); }));
  $("#courses").querySelectorAll("[data-del]").forEach((el) => (el.onclick = () => { courses.splice(+el.dataset.del, 1); render(); }));
}

async function grant() {
  const url = $("#appUrl").value.trim();
  if (!url) return;
  const origin = new URL(url).origin + "/*";
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
  const url = $("#appUrl").value.trim();
  if (url) {
    const origin = new URL(url).origin;
    const [app] = await chrome.tabs.query({ url: `${origin}/*` });
    if (app) {
      try {
        await chrome.scripting.executeScript({ target: { tabId: app.id }, files: ["content-app.js"] });
        const r = await chrome.tabs.sendMessage(app.id, { type: "courses" });
        if (r && r.ok) cfCourses = r.data || [];
      } catch {}
    }
  }
  render();
}

(async () => {
  const cfg = await chrome.storage.sync.get({ appUrl: "", courses: [] });
  $("#appUrl").value = cfg.appUrl; courses = cfg.courses;
  render();
})();

$("#addRow").onclick = () => { courses.push({ org: "", name: "", cid: "" }); render(); };
$("#grant").onclick = grant;
$("#detect").onclick = detect;
$("#save").onclick = async () => {
  await chrome.storage.sync.set({ appUrl: $("#appUrl").value.trim(), courses: courses.filter((c) => c.org) });
  $("#saved").textContent = "Saved.";
  setTimeout(() => ($("#saved").textContent = ""), 2000);
};
