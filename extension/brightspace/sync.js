/* Automatic sync: Brightspace -> CognitioFlow with no tab and no click, once a course has been reviewed.

   Everything the worker touches is injected (chrome, fetch, sleep, now), so `node --test` drives the
   real code with fakes. background.js only wires it to the real globals.

   Safety rules this file enforces (each has a test in test/sync.test.mjs):
   - A course uploads only when it is in the Options map (org -> cid), its first batch was reviewed
     (`confirmed[org]`), auto is on (`auto[org]`), and a write key exists for THAT cid. The cid comes from
     the map and the key from `cfKeys[cid]`, never from a message, so course A's key can never be sent
     with course B's upload.
   - The Authorization header only goes to the saved CognitioFlow origin, never to Brightspace.
   - A Brightspace answer that looks like a login (401/403, a redirect, another host, HTML where a
     document was expected) stops that course with status "login needed" and uploads nothing.
   - The ledger is written only after CognitioFlow answered 2xx, and after EVERY file, so a failure
     retries next run and a killed worker resumes where it stopped.
   - No LLM, no third host: only brightspace.rug.nl and the CognitioFlow origin are ever fetched. */
import {
  documents, pages, moduleIds, linksIn, enforcedFolder, dedupe, unseen, decide, signalOf,
  looksLikeDocument, isLoginResponse, sha256, sameName, BRIGHTSPACE_HOST,
} from "./lib.js";

export const BS_ORIGIN = `https://${BRIGHTSPACE_HOST}`;
export const API = (org, path = "") => `/d2l/api/le/1.97/${encodeURIComponent(org)}/content/${path}`;
export const MAX_UPLOAD_BYTES = 49 * 1024 * 1024;   // CF caps the whole multipart body at 50MB
export const LOG_MAX = 200;
export const LOCK_STALE_MS = 10 * 60 * 1000;

export const STATE = {
  ok: "ok",
  login: "login needed",
  keyMissing: "key needed",
  keyExpired: "key expired",
  keyWrongCourse: "key is for another course",
  noAccess: "no access to CognitioFlow",
  review: "waiting for first review",
  autoOff: "auto off",
  error: "error",
};

export class LoginNeeded extends Error {
  constructor(where) { super(`Brightspace sign-in needed (${where})`); this.login = true; }
}

const LOCAL_DEFAULTS = {
  seen: {}, pending: {}, confirmed: {}, auto: {}, ledger: {}, shaByCid: {}, cfKeys: {}, status: {}, log: [],
};

export function createSync({ chrome, fetch, sleep = (ms) => new Promise((r) => setTimeout(r, ms)), now = () => Date.now(),
                             pauseMs = 3000, maxPerRun = 20 }) {
  const local = (d = LOCAL_DEFAULTS) => chrome.storage.local.get(d);
  const conf = () => chrome.storage.sync.get({ appUrl: "", courses: [] });

  /* ------------------------------------------------------------------ Brightspace reads */

  async function brightspaceTab() {
    const [tab] = await chrome.tabs.query({ url: `${BS_ORIGIN}/*` });
    return tab || null;
  }

  const askTab = (tabId, msg) =>
    chrome.tabs.sendMessage(tabId, msg).then((r) => {
      if (!r || !r.ok) throw new Error((r && r.error) || "no answer from the Brightspace tab");
      return r.data;
    });

  const b64ToBytes = (b64) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));

  /** Reads Brightspace straight from the worker (session cookie, host permission). If that comes back as
      "signed out" and a Brightspace tab is open, the open tab's content script is tried instead — the
      cookie may simply not travel with an extension-origin request (spike S1). */
  function reader() {
    let mode = "direct";
    let tabId = null;

    async function direct(path, as, method = "GET") {
      let res;
      try {
        res = await fetch(BS_ORIGIN + path, {
          method, credentials: "include",
          headers: as === "json" ? { accept: "application/json" } : {},
        });
      } catch (e) {
        throw new Error(`Brightspace unreachable: ${e.message || e}`);
      }
      if (isLoginResponse(res)) throw new LoginNeeded(path);
      if (!res.ok) throw new Error(`${res.status} on ${path}`);
      const type = (res.headers && res.headers.get("content-type")) || "";
      if (as === "head") {
        const h = (n) => (res.headers && res.headers.get(n)) || "";
        return { etag: h("etag"), lastModified: h("last-modified"), size: h("content-length") };
      }
      if (as === "json") {
        if (!/json/i.test(type)) throw new LoginNeeded(`${path} answered ${type || "no type"}`);
        return res.json();
      }
      if (as === "text") return res.text();
      const bytes = new Uint8Array(await res.arrayBuffer());
      return { bytes, type, size: bytes.length };
    }

    async function viaTab(msg, as) {
      try {
        const data = await askTab(tabId, msg);
        if (as === "bytes") { const bytes = b64ToBytes(data.base64); return { bytes, type: data.type, size: bytes.length }; }
        return data;
      } catch (e) {
        const m = String(e.message || e);
        if (/^(401|403)\b/.test(m) || /JSON|Unexpected token/i.test(m)) throw new LoginNeeded(`tab: ${m}`);
        throw e;
      }
    }

    async function read(path, as, msg) {
      if (mode === "direct") {
        try {
          return await direct(path, as);
        } catch (e) {
          if (!e.login || !msg) throw e;
          const tab = await brightspaceTab();
          if (!tab) throw e;
          mode = "tab"; tabId = tab.id;
        }
      }
      return viaTab(msg, as);
    }

    return {
      get mode() { return mode; },
      toc: (org) => read(API(org, "toc"), "json", { type: "toc", org }),
      module: (org, id) => read(API(org, `modules/${encodeURIComponent(id)}`), "json", { type: "module", org, moduleId: id }),
      page: (url) => read(url, "text", { type: "page", url }),
      file: (url) => read(url, "bytes", { type: "file", url }),
      head: async (url) => (mode === "direct" ? direct(url, "head", "HEAD") : {}),
    };
  }

  /** Everything the course offers: File topics, document links in HTML topics (the PIL wrappers),
      document links in module descriptions. A login-looking answer anywhere stops the course. */
  async function collect(rd, org) {
    const toc = await rd.toc(org);
    const folder = enforcedFolder(toc);
    const items = documents(toc, org);
    const emptyPages = [];
    for (const p of pages(toc, org)) {
      try {
        const found = linksIn(await rd.page(p.url), folder, p);
        if (!found.length) emptyPages.push(p.title || p.url);
        items.push(...found);
      } catch (e) {
        if (e.login) throw e;
        emptyPages.push(`${p.title || p.url} (${e.message || e})`);
      }
    }
    for (const m of moduleIds(toc)) {
      try {
        const mod = await rd.module(org, m.id);
        items.push(...linksIn((mod && mod.Description && mod.Description.Html) || "", folder, m));
      } catch (e) {
        if (e.login) throw e;
      }
    }
    return { items: dedupe(items), emptyPages };
  }

  /* ------------------------------------------------------------------ CognitioFlow writes */

  async function upload({ appUrl, cid, key, item, got }) {
    const origin = new URL(appUrl).origin;
    const form = new FormData();
    form.append("file", new Blob([got.bytes], { type: got.type || "application/octet-stream" }), item.name);
    form.append("week", item.week || "");
    let res;
    try {
      res = await fetch(`${origin}/api/courses/${encodeURIComponent(cid)}/files`, {
        method: "POST", headers: { authorization: `Bearer ${key.token}` }, body: form, credentials: "omit",
      });
    } catch (e) {
      return { ok: false, error: `CognitioFlow unreachable: ${e.message || e}` };
    }
    if (res.ok) {
      let body = {};
      try { body = await res.json(); } catch {}
      return { ok: true, id: body.id || "", status: body.status || "" };
    }
    return { ok: false, http: res.status, error: `${res.status} from CognitioFlow` };
  }

  /** Proves key + route without uploading anything: an empty POST is refused with 413 by the key gate,
      which only happens after the key was accepted for this course. */
  async function testKey({ cid }) {
    const { appUrl, courses } = await conf();
    if (!courses.some((c) => c.cid === cid)) throw new Error("that CognitioFlow course is not in your course list");
    const { cfKeys } = await local({ cfKeys: {} });
    const key = cfKeys[cid];
    if (!key || !key.token) return { ok: false, state: STATE.keyMissing };
    const res = await fetch(`${new URL(appUrl).origin}/api/courses/${encodeURIComponent(cid)}/files`, {
      method: "POST", headers: { authorization: `Bearer ${key.token}` }, credentials: "omit",
    });
    if (res.status === 413) return { ok: true, state: STATE.ok };
    if (res.status === 401) return { ok: false, state: STATE.keyExpired };
    if (res.status === 403) return { ok: false, state: STATE.keyWrongCourse };
    return { ok: false, state: STATE.error, detail: `unexpected ${res.status}` };
  }

  /* ------------------------------------------------------------------ the run */

  const logLine = (st, org, name, action, error = "") => {
    st.log.push({ at: now(), org: String(org), name, action, ...(error ? { error } : {}) });
    if (st.log.length > LOG_MAX) st.log.splice(0, st.log.length - LOG_MAX);
  };

  const persist = (st) => chrome.storage.local.set({
    seen: st.seen, pending: st.pending, ledger: st.ledger, shaByCid: st.shaByCid, status: st.status, log: st.log,
  });

  const markSeen = (st, org, key) => {
    const list = st.seen[org] || [];
    if (!list.includes(key)) st.seen[org] = [...list, key];
  };

  async function canReachApp(appUrl) {
    if (!chrome.permissions || !chrome.permissions.contains) return true;
    try { return await chrome.permissions.contains({ origins: [`${new URL(appUrl).origin}/*`] }); } catch { return false; }
  }

  /** One course. Returns how many files went up. `budget` is shared across courses for the per-run cap. */
  async function syncCourse(st, course, { appUrl, upload: doUpload, budget, rd }) {
    const org = String(course.org);
    const cid = course.cid || "";
    const setStatus = (state, detail = "", extra = {}) => { st.status[org] = { state, detail, at: now(), ...extra }; };

    let found;
    try {
      found = await collect(rd, org);
    } catch (e) {
      if (e.login) { setStatus(STATE.login, "Open Brightspace and sign in; nothing was uploaded."); logLine(st, org, "", "stopped", STATE.login); }
      else { setStatus(STATE.error, String(e.message || e)); logLine(st, org, "", "scan failed", String(e.message || e)); }
      return { uploaded: 0, fresh: 0 };
    }
    const { items, emptyPages } = found;
    const ledger = (st.ledger[org] = st.ledger[org] || {});
    const notHandled = (list) => unseen(list, st.seen[org] || []).filter((i) => !ledger[i.key]);
    st.pending[org] = notHandled(items);
    const extra = emptyPages.length ? { emptyPages } : {};

    if (!doUpload) {   // a list refresh says nothing about the key: keep a key problem visible until a real run clears it
      const prev = st.status[org];
      const keyState = prev && [STATE.keyExpired, STATE.keyMissing, STATE.keyWrongCourse, STATE.noAccess].includes(prev.state);
      if (!keyState) setStatus(STATE.ok, "", extra);
      return { uploaded: 0, fresh: st.confirmed[org] ? st.pending[org].length : 0 }; }
    if (!cid) { setStatus(STATE.ok, "not linked to a CognitioFlow course", extra); return { uploaded: 0, fresh: 0 }; }
    if (!st.confirmed[org]) { setStatus(STATE.review, "Review the first list in the popup, or run the baseline in Options.", extra); return { uploaded: 0, fresh: 0 }; }
    if (!st.auto[org]) { setStatus(STATE.autoOff, "", extra); return { uploaded: 0, fresh: st.pending[org].length }; }

    const key = st.cfKeys[cid];
    if (!key || !key.token) { setStatus(STATE.keyMissing, "Create a sync key in Options.", extra); return { uploaded: 0, fresh: st.pending[org].length }; }
    if (key.courseId && key.courseId !== cid) { setStatus(STATE.keyWrongCourse, "", extra); return { uploaded: 0, fresh: 0 }; }
    if (key.expires && key.expires < now()) { setStatus(STATE.keyExpired, "Renew the sync key in Options.", extra); return { uploaded: 0, fresh: st.pending[org].length }; }
    if (!(await canReachApp(appUrl))) { setStatus(STATE.noAccess, "Allow access to the CognitioFlow address in Options.", extra); return { uploaded: 0, fresh: 0 }; }

    const shas = (st.shaByCid[cid] = st.shaByCid[cid] || []);
    let uploaded = 0;
    let failed = 0;
    for (const item of items) {
      const entry = ledger[item.key] || null;
      const handled = (st.seen[org] || []).includes(item.key) || !!entry;
      if (handled && item.kind === "link") {
        try { Object.assign(item, await rd.head(item.url)); } catch (e) { if (e.login) { setStatus(STATE.login, "Session ended mid-run; nothing more was uploaded."); await persist(st); return { uploaded, fresh: 0 }; } }
      }
      const verdict = decide(item, { seen: st.seen[org] || [], entry });
      if (verdict === "skip") continue;
      if (verdict === "adopt") {
        ledger[item.key] = { ...(entry || {}), signal: signalOf(item), at: now(), name: item.name };
        await persist(st);
        continue;
      }
      if (budget.left <= 0) break;

      let got;
      try {
        got = await rd.file(item.url);
      } catch (e) {
        if (e.login) { setStatus(STATE.login, "Session ended mid-run; nothing more was uploaded."); logLine(st, org, item.name, "stopped", STATE.login); await persist(st); return { uploaded, fresh: 0 }; }
        failed++; logLine(st, org, item.name, "download failed", String(e.message || e)); await persist(st); continue;
      }
      if (!looksLikeDocument(item.name, got.type, got.bytes)) {
        if (/text\/html/i.test(got.type || "")) { setStatus(STATE.login, "Brightspace sent a web page instead of the file; nothing more was uploaded."); logLine(st, org, item.name, "stopped", STATE.login); await persist(st); return { uploaded, fresh: 0 }; }
        failed++; logLine(st, org, item.name, "refused", `not a ${item.name.split(".").pop()} file`); await persist(st); continue;
      }
      if (got.size > MAX_UPLOAD_BYTES) {
        ledger[item.key] = { signal: signalOf(item), at: now(), name: item.name, skipped: "too big" };
        logLine(st, org, item.name, "skipped", `too big (${Math.round(got.size / 1048576)}MB) — add it by hand`);
        await persist(st); continue;
      }
      const sha = await sha256(got.bytes);
      if (entry && entry.sha === sha) {             // the date moved, the bytes did not
        ledger[item.key] = { ...entry, signal: signalOf(item), at: now() };
        await persist(st); continue;
      }
      if (shas.includes(sha)) {                    // same bytes reached through another key: already in CF
        ledger[item.key] = { signal: signalOf(item), sha, at: now(), name: item.name, duplicateOf: "sha" };
        markSeen(st, org, item.key);
        logLine(st, org, item.name, "already in CognitioFlow");
        await persist(st); continue;
      }

      budget.left--;
      const r = await upload({ appUrl, cid, key, item, got });
      if (!r.ok) {
        if (r.http === 401) { setStatus(STATE.keyExpired, "CognitioFlow refused the key; renew it in Options."); logLine(st, org, item.name, "stopped", STATE.keyExpired); await persist(st); return { uploaded, fresh: 0 }; }
        if (r.http === 403) { setStatus(STATE.keyWrongCourse, ""); logLine(st, org, item.name, "stopped", STATE.keyWrongCourse); await persist(st); return { uploaded, fresh: 0 }; }
        if (r.http === 413) {
          ledger[item.key] = { signal: signalOf(item), at: now(), name: item.name, skipped: "too big" };
          logLine(st, org, item.name, "skipped", "CognitioFlow says too large"); await persist(st); continue;
        }
        failed++; logLine(st, org, item.name, "upload failed", r.error);   // NOT marked: next run tries again
        await persist(st); continue;
      }
      ledger[item.key] = { signal: signalOf(item), sha, cfFileId: r.id, status: r.status, at: now(), name: item.name };
      markSeen(st, org, item.key);
      shas.push(sha);
      uploaded++;
      logLine(st, org, item.name, entry ? "updated (old version still in CognitioFlow)" : "uploaded");
      st.pending[org] = notHandled(items);
      await persist(st);
      if (budget.left > 0) await sleep(pauseMs);
    }
    st.pending[org] = notHandled(items);
    setStatus(failed ? STATE.error : STATE.ok, failed ? `${failed} file(s) failed; they will be retried` : "", { uploaded, ...extra });
    return { uploaded, fresh: 0 };
  }

  async function withLock(fn) {
    const { syncLock } = await chrome.storage.local.get({ syncLock: 0 });
    if (syncLock && now() - syncLock < LOCK_STALE_MS) return { skipped: "already running" };
    await chrome.storage.local.set({ syncLock: now() });
    try { return await fn(); } finally { await chrome.storage.local.set({ syncLock: 0 }); }
  }

  /** Every mapped course (or just `orgs`). upload=false only refreshes the popup list. */
  function run({ upload: doUpload = true, orgs = null } = {}) {
    return withLock(async () => {
      const { appUrl, courses } = await conf();
      const st = await local();
      const wanted = courses.filter((c) => c.org && (!orgs || orgs.map(String).includes(String(c.org))));
      if (orgs && !wanted.length) return { skipped: "not a mapped course" };
      const budget = { left: maxPerRun };
      const rd = reader();
      let uploaded = 0;
      let fresh = 0;
      for (const c of wanted) {
        const r = await syncCourse(st, c, { appUrl, upload: doUpload && !!appUrl, budget, rd });
        uploaded += r.uploaded; fresh += r.fresh;
      }
      await persist(st);
      await chrome.storage.local.set({ lastScan: now(), lastRun: { at: now(), uploaded } });
      return { fresh, uploaded, mode: rd.mode };
    });
  }

  /** Popup "Add": the chosen keys go up now, through the same checks, whatever auto says. */
  async function uploadKeys({ org, keys }) {
    return withLock(async () => {
      const { appUrl, courses } = await conf();
      const course = courses.find((c) => String(c.org) === String(org));
      if (!course || !course.cid) throw new Error("This course is not linked to a CognitioFlow course yet (Options)");
      const st = await local();
      const list = (st.pending[org] || []).filter((i) => keys.includes(i.key));
      const r = await syncItems(st, course, list, { appUrl, budget: { left: list.length }, rd: reader() });
      st.confirmed[org] = true;
      await chrome.storage.local.set({ confirmed: st.confirmed });
      return { added: r.added, failed: r.failed };
    });
  }

  /** Upload a fixed list (popup Add). Same pipeline as the run, minus the walk and the auto gate. */
  async function syncItems(st, course, list, { appUrl, budget, rd }) {
    const org = String(course.org);
    const cid = course.cid;
    const key = st.cfKeys[cid];
    if (!key || !key.token) throw new Error("No sync key for this course (Options)");
    if (key.courseId && key.courseId !== cid) throw new Error("That key belongs to another course");
    const ledger = (st.ledger[org] = st.ledger[org] || {});
    const shas = (st.shaByCid[cid] = st.shaByCid[cid] || []);
    const failed = [];
    let added = 0;
    for (const item of list) {
      if (budget.left-- <= 0) break;
      try {
        const got = await rd.file(item.url);
        if (!looksLikeDocument(item.name, got.type, got.bytes)) throw new LoginNeeded("got a web page instead of the file");
        if (got.size > MAX_UPLOAD_BYTES) throw new Error("too big — add it by hand");
        const sha = await sha256(got.bytes);
        if (!shas.includes(sha)) {
          const r = await upload({ appUrl, cid, key, item, got });
          if (!r.ok) throw new Error(r.http === 401 ? "CognitioFlow key expired (Options)" : r.error);
          ledger[item.key] = { signal: signalOf(item), sha, cfFileId: r.id, status: r.status, at: now(), name: item.name };
          shas.push(sha);
          added++;
          logLine(st, org, item.name, "uploaded");
        } else {
          ledger[item.key] = { signal: signalOf(item), sha, at: now(), name: item.name, duplicateOf: "sha" };
          logLine(st, org, item.name, "already in CognitioFlow");
        }
        markSeen(st, org, item.key);
        st.pending[org] = (st.pending[org] || []).filter((i) => i.key !== item.key);
        await persist(st);
      } catch (e) {
        failed.push({ name: item.name, error: e.login ? STATE.login : String(e.message || e) });
        logLine(st, org, item.name, "upload failed", String(e.message || e));
        await persist(st);
        if (e.login) break;
      }
    }
    return { added, failed };
  }

  /** First run for a course: mark what is on Brightspace now as handled, without uploading.
      mode "all": everything. mode "match": only files whose name is already in CognitioFlow (`names`,
      read by Options from a signed-in CognitioFlow tab); the rest stays pending and goes up automatically. */
  async function baseline({ org, mode = "all", names = [] }) {
    return withLock(async () => {
      const { courses } = await conf();
      const course = courses.find((c) => String(c.org) === String(org));
      if (!course) throw new Error("not a course in your list");
      const st = await local();
      const { items } = await collect(reader(), String(org));
      const ledger = (st.ledger[org] = st.ledger[org] || {});
      const marked = [];
      for (const it of items) {
        if (mode === "match" && !names.some((n) => sameName(n, it.name))) continue;
        ledger[it.key] = { ...(ledger[it.key] || {}), signal: signalOf(it), at: now(), name: it.name, baseline: true };
        markSeen(st, org, it.key);
        marked.push(it.name);
      }
      st.pending[org] = unseen(items, st.seen[org] || []).filter((i) => !ledger[i.key]);
      logLine(st, org, `${marked.length} file(s)`, `baseline (${mode})`);
      await persist(st);
      await chrome.storage.local.set({ confirmed: { ...st.confirmed, [org]: true } });
      return { marked, left: st.pending[org].map((i) => i.name) };
    });
  }

  return { run, syncCourse, uploadKeys, baseline, testKey, reader, collect };
}

/** Badge from the last run: BS (sign in, amber) > KEY (red) > ! (other) > number uploaded (green) > pending (blue). */
export function badgeFor({ status = {}, pending = {}, lastRun = null }) {
  const states = Object.values(status).map((s) => s && s.state);
  if (states.includes(STATE.login)) return { text: "BS", color: "#b7791f" };
  if (states.some((s) => [STATE.keyExpired, STATE.keyWrongCourse, STATE.keyMissing].includes(s))) return { text: "KEY", color: "#c53030" };
  if (states.some((s) => [STATE.error, STATE.noAccess].includes(s))) return { text: "!", color: "#c53030" };
  if (lastRun && lastRun.uploaded) return { text: String(lastRun.uploaded), color: "#2f855a" };
  const n = Object.values(pending).reduce((a, l) => a + (l ? l.length : 0), 0);
  return { text: n ? String(n) : "", color: "#24467a" };
}
