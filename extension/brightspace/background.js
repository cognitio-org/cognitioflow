/* Orchestrates: read the course list from a Brightspace tab, work out what is new, and (once you say yes)
   hand the bytes to a CognitioFlow tab, which uploads them as you. Nothing is stored but a list of ids. */
import { documents, pages, moduleIds, linksIn, enforcedFolder, unseen, dedupe } from "./lib.js";

const SCAN_MINUTES = 60;
const OPEN_DEBOUNCE_MS = 10 * 60 * 1000;
const conf = () => chrome.storage.sync.get({ appUrl: "", courses: [] });
const local = (d) => chrome.storage.local.get(d);

const ask = (tabId, msg) =>
  chrome.tabs.sendMessage(tabId, msg).then((r) => {
    if (!r || !r.ok) throw new Error((r && r.error) || "no answer from the page");
    return r.data;
  });

async function brightspaceTab() {
  const [tab] = await chrome.tabs.query({ url: "https://brightspace.rug.nl/*" });
  return tab || null;
}

async function appTab(appUrl) {
  if (!appUrl) throw new Error("Set the CognitioFlow address in Options first");
  const origin = new URL(appUrl).origin;
  const [tab] = await chrome.tabs.query({ url: `${origin}/*` });
  if (tab) return tab;
  const made = await chrome.tabs.create({ url: origin, active: false });
  let timer;
  const wait = new Promise((resolve, reject) => {
    const on = (id, info) => {
      if (id === made.id && info.status === "complete") {
        chrome.tabs.onUpdated.removeListener(on);
        clearTimeout(timer);
        resolve();
      }
    };
    chrome.tabs.onUpdated.addListener(on);
    timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(on);
      reject(new Error("the CognitioFlow tab did not finish loading"));
    }, 30000);
  });
  await wait;
  return made;
}

async function inject(tabId, file) {
  await chrome.scripting.executeScript({ target: { tabId }, files: [file] });
}

/** Everything the course offers: File topics, links inside HTML topics, links inside module descriptions. */
async function collect(tabId, org) {
  const toc = await ask(tabId, { type: "toc", org });
  const folder = enforcedFolder(toc);
  const items = documents(toc, org);
  for (const p of pages(toc, org)) {
    try { items.push(...linksIn(await ask(tabId, { type: "page", url: p.url }), folder, p)); } catch {}
  }
  for (const m of moduleIds(toc)) {
    try {
      const mod = await ask(tabId, { type: "module", org, moduleId: m.id });
      const html = (mod && mod.Description && mod.Description.Html) || "";
      items.push(...linksIn(html, folder, m));
    } catch {}
  }
  return dedupe(items);
}

async function scan({ notify = true } = {}) {
  const tab = await brightspaceTab();
  if (!tab) return { skipped: "no Brightspace tab open" };
  const { courses } = await conf();
  const { seen, pending, confirmed } = await local({ seen: {}, pending: {}, confirmed: {} });
  let fresh = 0;
  for (const c of courses) {
    try {
      const items = await collect(tab.id, c.org);
      const list = unseen(items, seen[c.org] || []);
      pending[c.org] = list;
      fresh += confirmed[c.org] ? list.length : 0;
    } catch (e) {
      pending[c.org] = pending[c.org] || [];
    }
  }
  await chrome.storage.local.set({ pending, lastScan: Date.now() });
  await badge();
  if (notify && fresh) {
    chrome.notifications.create({
      type: "basic", iconUrl: "icons/128.png", title: "New course material",
      message: `${fresh} new file${fresh === 1 ? "" : "s"} on Brightspace. Click the toolbar icon to add ${fresh === 1 ? "it" : "them"}.`,
    });
  }
  return { fresh };
}

async function badge() {
  const { pending } = await local({ pending: {} });
  const n = Object.values(pending).reduce((a, l) => a + l.length, 0);
  await chrome.action.setBadgeText({ text: n ? String(n) : "" });
  await chrome.action.setBadgeBackgroundColor({ color: "#24467a" });
}

/** Take the chosen items across: Brightspace tab gives the bytes, CognitioFlow tab does the upload. */
async function take({ org, keys }) {
  const { appUrl, courses } = await conf();
  const course = courses.find((c) => String(c.org) === String(org));
  if (!course || !course.cid) throw new Error("This course is not linked to a CognitioFlow course yet (Options)");
  const bs = await brightspaceTab();
  if (!bs) throw new Error("Open Brightspace in a tab first");
  const app = await appTab(appUrl);
  await inject(app.id, "content-app.js");

  const { seen, pending, confirmed } = await local({ seen: {}, pending: {}, confirmed: {} });
  const list = (pending[org] || []).filter((i) => keys.includes(i.key));
  const done = [];
  const failed = [];
  for (const item of list) {
    try {
      const b = await ask(bs.id, { type: "file", url: item.url });
      await ask(app.id, { type: "upload", cid: course.cid, name: item.name, week: item.week, base64: b.base64, type: b.type });
      done.push(item.key);
    } catch (e) {
      failed.push({ name: item.name, error: String(e.message || e) });
    }
  }
  seen[org] = [...new Set([...(seen[org] || []), ...done])];
  pending[org] = (pending[org] || []).filter((i) => !done.includes(i.key));
  confirmed[org] = true;
  await chrome.storage.local.set({ seen, pending, confirmed });
  await badge();
  return { added: done.length, failed };
}

/** Remember these without downloading them — "I already have this" / "not interested". */
async function skip({ org, keys }) {
  const { seen, pending, confirmed } = await local({ seen: {}, pending: {}, confirmed: {} });
  seen[org] = [...new Set([...(seen[org] || []), ...keys])];
  pending[org] = (pending[org] || []).filter((i) => !keys.includes(i.key));
  confirmed[org] = true;
  await chrome.storage.local.set({ seen, pending, confirmed });
  await badge();
  return { skipped: keys.length };
}

const routes = { scan, take, skip, badge, "brightspace-open": async () => {
  const { lastScan } = await chrome.storage.local.get({ lastScan: 0 });
  if (Date.now() - (lastScan || 0) < OPEN_DEBOUNCE_MS) return { skipped: "debounced" };
  return scan({ notify: true });
} };

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  const fn = routes[msg && msg.type];
  if (!fn) return false;
  Promise.resolve(fn(msg)).then((data) => reply({ ok: true, data }), (e) => reply({ ok: false, error: String(e.message || e) }));
  return true;
});

chrome.runtime.onInstalled.addListener(() => chrome.alarms.create("scan", { periodInMinutes: SCAN_MINUTES }));
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "scan") scan({ notify: true }); });

export { appTab };
