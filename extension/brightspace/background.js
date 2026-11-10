/* Orchestrates. Two ways material reaches CognitioFlow:
   - automatic (sync.js): the worker reads Brightspace itself and uploads with a per-course write key,
     on an alarm, once the course's first batch was reviewed and auto is on;
   - manual (popup Add): the same pipeline with the key, or, for a course with no key yet, the old path —
     the bytes go through an open CognitioFlow tab, which uploads them as you. */
import { signalOf, looksLikeDocument } from "./lib.js";
import { createSync, badgeFor, STATE } from "./sync.js";

const DEFAULT_SYNC_HOURS = 6;
const OPEN_DEBOUNCE_MS = 10 * 60 * 1000;
const sync = createSync({ chrome, fetch: (...a) => globalThis.fetch(...a) });
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

/** Refresh the popup list (no uploads). Works with no Brightspace tab open if the worker can read it. */
async function scan({ notify = true, orgs = null } = {}) {
  const r = await sync.run({ upload: false, orgs });
  await badge();
  if (notify && r.fresh) notifyFresh(r.fresh);
  return r;
}

/** The automatic run: upload what is new for every course that is reviewed, on auto, and has a key. */
async function syncAll({ orgs = null, notify = true } = {}) {
  const r = await sync.run({ upload: true, orgs });
  await badge();
  if (notify && r.uploaded) {
    chrome.notifications.create({
      type: "basic", iconUrl: "icons/128.png", title: "Added to CognitioFlow",
      message: `${r.uploaded} new file${r.uploaded === 1 ? "" : "s"} from Brightspace synced.`,
    });
  } else if (notify && r.fresh) notifyFresh(r.fresh);
  return r;
}

function notifyFresh(fresh) {
  chrome.notifications.create({
    type: "basic", iconUrl: "icons/128.png", title: "New course material",
    message: `${fresh} new file${fresh === 1 ? "" : "s"} on Brightspace. Click the toolbar icon to add ${fresh === 1 ? "it" : "them"}.`,
  });
}

async function badge() {
  const b = badgeFor(await local({ status: {}, pending: {}, lastRun: null }));
  await chrome.action.setBadgeText({ text: b.text });
  await chrome.action.setBadgeBackgroundColor({ color: b.color });
  return b;
}

/** The first bytes of a base64 file, enough for looksLikeDocument's sniff (it reads at most 64). */
const headOf = (b64) => Uint8Array.from(atob(String(b64 || "").slice(0, 88)), (c) => c.charCodeAt(0));

/** Take the chosen items across: Brightspace tab gives the bytes, CognitioFlow tab does the upload. */
async function take({ org, keys }) {
  const { appUrl, courses } = await conf();
  const course = courses.find((c) => String(c.org) === String(org));
  if (!course || !course.cid) throw new Error("This course is not linked to a CognitioFlow course yet (Options)");
  const { cfKeys } = await local({ cfKeys: {} });
  if (cfKeys[course.cid] && cfKeys[course.cid].token) {
    const r = await sync.uploadKeys({ org, keys });
    if (r.skipped) throw new Error("A sync is running — try again in a minute");
    await badge();
    return r;
  }
  const bs = await brightspaceTab();
  if (!bs) throw new Error("Open Brightspace in a tab first");
  const app = await appTab(appUrl);
  await inject(app.id, "content-app.js");

  // Same rule as sync's Add: never a file that is handled, or held by a marker a killed upload left (its
  // bytes may already be in CognitioFlow; sync surfaces it as "check in CF" and takes it back after 24h).
  const { pending: before, ledger, seen } = await local({ pending: {}, ledger: {}, seen: {} });
  const handled = (k) => ((seen[org] || []).includes(k)) || !!((ledger[org] || {})[k]);
  const list = (before[org] || []).filter((i) => keys.includes(i.key) && !handled(i.key));
  const done = [];
  const failed = [];
  let added = 0;   // files sent, not keys marked: a twin is marked but not sent again
  // One Brightspace file can be listed twice (a File topic and a link to the same path, e.g. a first-review
  // row carried as `missing` beside the topic that replaced it). There is no sha dedupe on this path, so
  // the twin rides along with the first upload of that path instead of being POSTed again.
  const twins = new Map();   // path -> the item that goes up
  const riders = new Map();  // that item -> its twins, recorded with it on success
  for (const item of list) {
    const first = item.path ? twins.get(item.path) : null;
    if (first) { riders.get(first).push(item); continue; }
    if (item.path) twins.set(item.path, item);
    riders.set(item, []);
  }
  for (const [item, rest] of riders) {
    try {
      const b = await ask(bs.id, { type: "file", url: item.url });
      // Same check as the keyed Add: a 200 text/html login page (expired session) is not the file. Nothing
      // goes up, nothing is marked, and the rest of the Add stops, as a sign-in stop does there.
      if (!looksLikeDocument(item.name, b.type, headOf(b.base64))) throw Object.assign(new Error(STATE.login), { login: true });
      await ask(app.id, { type: "upload", cid: course.cid, name: item.name, week: item.week, base64: b.base64, mime: b.type });   // `type` routes the message: the MIME type travels as `mime`
      done.push(item, ...rest);
      added++;
    } catch (e) {
      const m = String(e.message || e);
      const login = e.login || /sign-in needed/i.test(m);
      failed.push({ name: item.name, error: login ? STATE.login : m });
      if (login) break;
    }
  }
  await record(org, done, "tab");
  await badge();
  return { added, failed };
}

/** Mark items handled, as one read-modify-write under sync's state lock (merged with whatever a running
    sync wrote meanwhile). The first review ends only when nothing in the course is left undecided and the
    scan behind the list read every page (`status` is loaded for finishReview, which fails closed without it). */
function record(org, items, via, keys = items.map((i) => i.key)) {
  return sync.mutate(async () => {
    const cur = await local({ seen: {}, pending: {}, confirmed: {}, ledger: {}, status: {} });
    const book = (cur.ledger[org] = cur.ledger[org] || {});
    for (const i of items) book[i.key] = { signal: signalOf(i), at: Date.now(), name: i.name, via };
    cur.seen[org] = [...new Set([...(cur.seen[org] || []), ...keys])];
    cur.pending[org] = (cur.pending[org] || []).filter((i) => !keys.includes(i.key));
    sync.finishReview(cur, org);
    await chrome.storage.local.set({ seen: cur.seen, pending: cur.pending, confirmed: cur.confirmed, ledger: cur.ledger });
  });
}

/** Remember these without downloading them — "I already have this" / "not interested". */
async function skip({ org, keys }) {
  const { pending } = await local({ pending: {} });
  await record(org, (pending[org] || []).filter((x) => keys.includes(x.key)), "remembered", keys);
  await badge();
  return { skipped: keys.length };
}

async function schedule() {
  const { syncHours } = await chrome.storage.sync.get({ syncHours: DEFAULT_SYNC_HOURS });
  const hours = Math.min(48, Math.max(1, Number(syncHours) || DEFAULT_SYNC_HOURS));
  await chrome.alarms.clear("scan");                      // the old hourly scan alarm, from v0.1
  await chrome.alarms.create("sync", { periodInMinutes: hours * 60 });
  return { hours };
}

async function setAuto({ org, on }) {
  const { courses } = await conf();
  if (!courses.some((c) => String(c.org) === String(org))) throw new Error("not a course in your list");
  return sync.mutate(async () => {
    const { auto } = await local({ auto: {} });
    auto[org] = !!on;
    await chrome.storage.local.set({ auto });
    return { auto };
  });
}

const routes = {
  scan, badge, schedule, "set-auto": setAuto,
  take, skip,
  "sync-now": () => syncAll({ notify: false }),
  baseline: (m) => sync.baseline({ org: m.org, mode: m.mode, names: m.names || [] }).then(async (r) => { await badge(); return r; }),
  "test-key": (m) => sync.testKey({ cid: m.cid }),
  "brightspace-open": async (msg) => {
    const { lastScan } = await chrome.storage.local.get({ lastScan: 0 });
    if (Date.now() - (lastScan || 0) < OPEN_DEBOUNCE_MS) return { skipped: "debounced" };
    return syncAll({ notify: true, orgs: msg && msg.org ? [msg.org] : null });
  },
};

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  const fn = routes[msg && msg.type];
  if (!fn) return false;
  Promise.resolve(fn(msg)).then((data) => reply({ ok: true, data }), (e) => reply({ ok: false, error: String(e.message || e) }));
  return true;
});

chrome.runtime.onInstalled.addListener(() => { schedule(); });
chrome.runtime.onStartup.addListener(() => {
  schedule();
  chrome.alarms.create("sync-startup", { delayInMinutes: 1 });   // let the SSO cookies settle; an alarm survives the worker being killed
});
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === "sync" || a.name === "sync-startup" || a.name === "scan") syncAll({ notify: true });
});

export { appTab, routes };
