/* Runs inside a Brightspace tab. Every fetch here is same-origin, so your normal university login
   carries it — the extension never sees, stores or asks for a password. */
const API = (org, path = "") => `/d2l/api/le/1.97/${encodeURIComponent(org)}/content/${path}`;

async function json(url) {
  const r = await fetch(url, { credentials: "same-origin", headers: { accept: "application/json" } });
  if (!r.ok) throw new Error(`${r.status} on ${url}`);
  return r.json();
}

async function text(url) {
  const r = await fetch(url, { credentials: "same-origin" });
  if (!r.ok) throw new Error(`${r.status} on ${url}`);
  return r.text();
}

async function bytes(url) {
  const r = await fetch(url, { credentials: "same-origin" });
  if (!r.ok) throw new Error(`${r.status} on ${url}`);
  const buf = new Uint8Array(await r.arrayBuffer());
  let s = "";
  for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return { base64: btoa(s), type: r.headers.get("content-type") || "application/octet-stream", size: buf.length };
}

const handlers = {
  toc: ({ org }) => json(API(org, "toc")),
  module: ({ org, moduleId }) => json(API(org, `modules/${encodeURIComponent(moduleId)}`)),
  page: ({ url }) => text(url),
  file: ({ url }) => bytes(url),
  /** Course ids and names as the menu shows them, for first-time setup. */
  courses: () => json("/d2l/api/lp/1.47/enrollments/myenrollments/?orgUnitTypeId=3"),
};

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  const fn = handlers[msg && msg.type];
  if (!fn) return false;
  Promise.resolve(fn(msg)).then((data) => reply({ ok: true, data }), (e) => reply({ ok: false, error: String(e.message || e) }));
  return true; // reply comes later
});

/* Tell the worker we are here, so a scan can run while you are already reading Brightspace. */
const org = (/\/(?:content|lessons|home)\/(\d+)/.exec(location.pathname) || [])[1];
if (org) chrome.runtime.sendMessage({ type: "brightspace-open", org, tab: true }).catch(() => {});
