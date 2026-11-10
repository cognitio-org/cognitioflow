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
   - Before each POST an in-flight marker (with the file's sha256) goes into the ledger; a 2xx turns it into
     the done entry, a definite failure takes it back, so a failure retries next run. A worker killed
     mid-request leaves the marker: the restart does not re-send the same bytes, it logs "check in CF"
     (and only retries once the marker is 24h old). The ledger is on disk after EVERY file.
   - All writes to seen / pending / ledger / confirmed are read-modify-write under one lock (`mutate`),
     merged per key, so a Remember in the popup can never be lost to a run's save. One run at a time:
     a storage lease { owner, expires }, taken by compare-and-set under navigator.locks, renewed per file,
     released only by its owner.
   - The key only goes to the CognitioFlow origin it was made for, over https (http only on localhost).
   - A first review is finished only when every file in it was added or remembered, AND the scan that made
     the list read every page and module description (`status[org].readErrors` empty). A clean re-check
     that leaves nothing undecided finishes it too. Until then a file once listed stays in `pending` (flagged
     `missing` if a scan no longer finds it), so a list that shrinks can never finish the review.
   - A marker held for a lost upload is honoured by popup Add exactly as by the run: same bytes, no POST.
   - Auto and the key are re-read before every upload: switching Auto off or removing the key stops the run.
   - No LLM, no third host: only brightspace.rug.nl and the CognitioFlow origin are ever fetched. Every
     Brightspace read is a "/…" path on that origin; TOC page Urls must sit in the course's own folder. */
import {
  documents, pages, moduleIds, linksIn, enforcedFolder, dedupe, unseen, decide, signalOf,
  looksLikeDocument, isLoginResponse, sha256, sameName, appOrigin, BRIGHTSPACE_HOST,
} from "./lib.js";

export const BS_ORIGIN = `https://${BRIGHTSPACE_HOST}`;
export const API = (org, path = "") => `/d2l/api/le/1.97/${encodeURIComponent(org)}/content/${path}`;
export const MAX_UPLOAD_BYTES = 49 * 1024 * 1024;   // CF caps the whole multipart body at 50MB
export const LOG_MAX = 200;
export const LEASE_MS = 10 * 60 * 1000;          // a run's lease; renewed after every file
export const LOCK_STALE_MS = LEASE_MS;
export const PENDING_HOLD_MS = 24 * 60 * 60 * 1000;   // a lost upload is not re-sent for this long
const STATE_LOCK = "cf-brightspace-state";
const LEASE_LOCK = "cf-brightspace-lease";

export const STATE = {
  ok: "ok",
  login: "login needed",
  keyMissing: "key needed",
  keyExpired: "key expired",
  keyWrongCourse: "key is for another course",
  keyOrigin: "key is for another address",
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
                             pauseMs = 3000, maxPerRun = 20, locks = (globalThis.navigator && globalThis.navigator.locks) || null }) {
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

    /** Only ever a "/…" path on brightspace.rug.nl: a TOC value like ".evil.example/x.html" would otherwise
        turn BS_ORIGIN + path into another host, asked with the session cookie. */
    function onBrightspace(path) {
      const ok = typeof path === "string" && path.startsWith("/") && !path.startsWith("//") &&
        (() => { try { return new URL(BS_ORIGIN + path).origin === BS_ORIGIN; } catch { return false; } })();
      if (!ok) throw new Error(`refused: ${String(path).slice(0, 80)} is not a Brightspace path`);
    }

    async function direct(path, as, method = "GET") {
      onBrightspace(path);
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
        if (/^(401|403)\b/.test(m) || /JSON|Unexpected token|sign-in needed/i.test(m)) throw new LoginNeeded(`tab: ${m}`);
        throw e;
      }
    }

    async function read(path, as, msg) {
      onBrightspace(path);
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
    const emptyPages = [];   // read fine, no file link (or refused): nothing hidden, never blocks a review
    const readErrors = [];   // could not be read: its files may be missing from the list
    const refused = [];
    for (const p of pages(toc, org, refused)) {
      try {
        const found = linksIn(await rd.page(p.url), folder, { ...p, org });
        if (!found.length) emptyPages.push(p.title || p.url);
        items.push(...found);
      } catch (e) {
        if (e.login) throw e;
        readErrors.push(`${p.title || p.url} (${e.message || e})`);
      }
    }
    for (const t of refused) emptyPages.push(`${t} (not in this course's folder; not read)`);
    for (const m of moduleIds(toc)) {
      try {
        const mod = await rd.module(org, m.id);
        items.push(...linksIn((mod && mod.Description && mod.Description.Html) || "", folder, { ...m, org }));
      } catch (e) {
        if (e.login) throw e;
        readErrors.push(`module ${m.title || m.id} (${e.message || e})`);
      }
    }
    return { items: dedupe(items), emptyPages, readErrors };
  }

  /* ------------------------------------------------------------------ locks and shared state */

  /** Exclusive section by name. Web Locks (navigator.locks) span every extension context — worker, popup,
      options — and are dropped if a context dies; without them, an in-memory queue serializes this context. */
  const tails = new Map();
  function exclusive(name, fn) {
    if (locks) return locks.request(name, () => fn());
    const prev = tails.get(name) || Promise.resolve();
    const run = prev.then(() => fn());
    tails.set(name, run.catch(() => {}));
    return run;
  }

  /** Every read-modify-write of seen / pending / ledger / confirmed goes through here (background.js
      skip/take too), so two writers can never overwrite each other's entries. Never nest it. */
  const mutate = (fn) => exclusive(STATE_LOCK, fn);

  /* The run lease: { owner, expires } in storage.local, taken by compare-and-set inside the lease lock,
     renewed after every file, released only by its owner. A worker killed mid-run leaves a lease that
     simply expires. */
  const leaseOf = new WeakMap();   // run snapshot -> its lease { owner, lost }
  const newOwner = () => (globalThis.crypto && crypto.randomUUID ? crypto.randomUUID() : `${now()}-${Math.random()}`);
  async function readLease() {
    const { syncLock } = await chrome.storage.local.get({ syncLock: null });
    if (typeof syncLock === "number") return syncLock ? { owner: "v0.2", expires: syncLock + LEASE_MS } : null;   // old format
    return syncLock && syncLock.owner ? syncLock : null;
  }
  function acquire(owner) {
    return exclusive(LEASE_LOCK, async () => {
      const cur = await readLease();
      if (cur && cur.owner !== owner && cur.expires > now()) return false;
      await chrome.storage.local.set({ syncLock: { owner, expires: now() + LEASE_MS } });
      if (locks) return true;
      // No Web Locks: another context may have written between our get and set. Let it land, then re-check.
      await new Promise((r) => setTimeout(r, 20));
      const back = await readLease();
      return !!back && back.owner === owner;
    });
  }
  function renewLease(h) {
    if (!h) return Promise.resolve();
    return exclusive(LEASE_LOCK, async () => {
      const cur = await readLease();
      if (cur && cur.owner !== h.owner && cur.expires > now()) { h.lost = true; return; }
      if (!h.lost) await chrome.storage.local.set({ syncLock: { owner: h.owner, expires: now() + LEASE_MS } });
    });
  }
  function release(owner) {
    return exclusive(LEASE_LOCK, async () => {
      const cur = await readLease();
      if (cur && cur.owner === owner) await chrome.storage.local.set({ syncLock: null });
    });
  }
  /** fn(lease): the run binds its snapshot to the lease (`leaseOf.set(st, lease)`) so persist() renews it. */
  async function withLock(fn) {
    const owner = newOwner();
    if (!(await acquire(owner))) return { skipped: "already running" };
    try { return await fn({ owner, lost: false }); } finally { await release(owner); }
  }
  const leaseLost = (st) => { const h = leaseOf.get(st); return !!(h && h.lost); };

  /* A run works on a snapshot `st` and records what it changed; persist() merges those changes into what
     is on disk NOW (under the state lock) and refreshes the snapshot, so a Remember / Add / another
     context's write that landed meanwhile survives, and the run sees it before its next upload. */
  const dirtyOf = new WeakMap();
  const dirty = (st) => {
    let d = dirtyOf.get(st);
    if (!d) dirtyOf.set(st, (d = { ledger: new Set(), status: new Set(), pending: new Set(), confirmed: new Set(), log: [] }));
    return d;
  };
  const setLedger = (st, org, key, value) => {
    const book = (st.ledger[org] = st.ledger[org] || {});
    if (value) book[key] = value; else delete book[key];
    dirty(st).ledger.add(JSON.stringify([org, key]));
  };
  const setPending = (st, org, list) => { st.pending[org] = list; dirty(st).pending.add(org); };
  const setConfirmed = (st, org) => { st.confirmed[org] = true; dirty(st).confirmed.add(org); };

  async function persist(st) {
    const d = dirty(st);
    dirtyOf.delete(st);
    await mutate(async () => {
      const cur = await local({ seen: {}, pending: {}, ledger: {}, shaByCid: {}, status: {}, log: [], confirmed: {} });
      for (const [org, list] of Object.entries(st.seen || {})) cur.seen[org] = [...new Set([...(cur.seen[org] || []), ...list])];
      for (const k of d.ledger) {
        const [org, key] = JSON.parse(k);
        const v = st.ledger[org] && st.ledger[org][key];
        const book = (cur.ledger[org] = cur.ledger[org] || {});
        if (v) book[key] = v; else delete book[key];
      }
      for (const [cid, list] of Object.entries(st.shaByCid || {})) cur.shaByCid[cid] = [...new Set([...(cur.shaByCid[cid] || []), ...list])];
      for (const org of d.status) cur.status[org] = st.status[org];
      for (const org of d.confirmed) cur.confirmed[org] = true;
      const handled = (org, key) => (cur.seen[org] || []).includes(key) || !!(cur.ledger[org] || {})[key];
      for (const org of new Set([...d.pending, ...Object.keys(cur.pending)]))
        cur.pending[org] = ((d.pending.has(org) ? st.pending[org] : cur.pending[org]) || []).filter((i) => !handled(org, i.key));
      cur.log = [...cur.log, ...d.log].slice(-LOG_MAX);
      await chrome.storage.local.set(cur);
      Object.assign(st, cur);
      // Auto and the keys are only read here, never written back (Options owns them): a run sees Auto
      // switched off or a key removed before its next upload, and cannot resurrect a removed key.
      const live = await local({ auto: {}, cfKeys: {} });
      st.auto = live.auto; st.cfKeys = live.cfKeys;
    });
    await renewLease(leaseOf.get(st));
  }

  /** A ledger entry may be an in-flight marker { pending: { sha, at, signal }, prev } written just before a
      POST. settled() is the entry as it was before that upload started (null for a first upload). */
  const settled = (raw) => (raw && raw.pending ? raw.prev || null : raw || null);

  /* ------------------------------------------------------------------ CognitioFlow writes */

  /** Where this key may go: the origin it was made for, and only over https (http on localhost). */
  function keyTarget(key, appUrl) {
    const origin = appOrigin(appUrl);
    if (!origin) return { error: "address", detail: "The CognitioFlow address must be https (Options)." };
    if (!key || !key.origin || key.origin !== origin)
      return { error: "origin", detail: "This key was made for another CognitioFlow address; create it again in Options." };
    return { origin };
  }

  /** Why this key may not be used for `cid` right now, as a status, or null. */
  function keyProblem(key, cid, appUrl) {
    if (!key || !key.token) return { state: STATE.keyMissing, detail: "Create a sync key in Options." };
    if (key.courseId && key.courseId !== cid) return { state: STATE.keyWrongCourse, detail: "" };
    if (key.expires && key.expires < now()) return { state: STATE.keyExpired, detail: "Renew the sync key in Options." };
    const target = keyTarget(key, appUrl);
    if (target.error) return { state: target.error === "origin" ? STATE.keyOrigin : STATE.error, detail: target.detail };
    return null;
  }
  /** The key on disk now is still the one this run started with (not removed, not replaced). */
  const sameKey = (cfKeys, cid, key) => !!(cfKeys && cfKeys[cid] && cfKeys[cid].token && cfKeys[cid].token === key.token);
  /** An in-flight marker younger than 24h: the bytes it names are not sent again. */
  const held = (raw) => !!(raw && raw.pending && now() - raw.pending.at < PENDING_HOLD_MS);

  async function upload({ appUrl, cid, key, item, got }) {
    const target = keyTarget(key, appUrl);
    if (target.error) return { ok: false, error: target.detail };
    const form = new FormData();
    form.append("file", new Blob([got.bytes], { type: got.type || "application/octet-stream" }), item.name);
    form.append("week", item.week || "");
    let res;
    try {
      res = await fetch(`${target.origin}/api/courses/${encodeURIComponent(cid)}/files`, {
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

  /** The POST with the in-flight marker around it: the marker (with the sha) is on disk before the request
      leaves, replaced by the done entry after a 2xx, and taken back after a definite failure. A worker
      killed in between leaves the marker, so the restart does not send the same bytes again blindly. */
  async function guardedUpload(st, org, { appUrl, cid, key, item, got, sha, entry, expect, gate = null }) {
    await persist(st);
    // Compare-and-set: the marker goes down only if nobody handled the item since `expect` was read
    // (a Remember can land while the file downloads); otherwise the item is left to the other writer.
    // `gate(cur)` re-checks Auto / the key as they are on disk right now; a reason stops the upload.
    const marker = { pending: { sha, at: now(), signal: signalOf(item) }, prev: entry || null, name: item.name };
    const placed = await mutate(async () => {
      const cur = await local({ ledger: {}, seen: {}, auto: {}, cfKeys: {} });
      const why = gate && gate(cur);
      if (why) return { stopped: why };
      const book = (cur.ledger[org] = cur.ledger[org] || {});
      if (JSON.stringify([book[item.key] || null, (cur.seen[org] || []).includes(item.key)]) !== expect) return { conflict: true };
      book[item.key] = marker;
      await chrome.storage.local.set({ ledger: cur.ledger });
      return { placed: true };
    });
    if (placed.stopped) return { ok: false, stopped: placed.stopped };
    if (placed.conflict) return { ok: false, conflict: true };
    (st.ledger[org] = st.ledger[org] || {})[item.key] = marker;   // already on disk: not dirty
    const r = await upload({ appUrl, cid, key, item, got });
    if (!r.ok) setLedger(st, org, item.key, entry || null);
    return r;
  }
  const stateOf = (st, org, key) => JSON.stringify([(st.ledger[org] || {})[key] || null, (st.seen[org] || []).includes(key)]);

  /** Markers left by a killed upload, on every scan whatever the gates say: a fresh one is surfaced once
      as "check in CF"; one older than 24h is taken back (the file returns to the list / is retried). */
  function reviewMarkers(st, org) {
    for (const [key, raw] of Object.entries(st.ledger[org] || {})) {
      if (!raw || !raw.pending) continue;
      if (now() - raw.pending.at >= PENDING_HOLD_MS) {
        setLedger(st, org, key, raw.prev || null);
        logLine(st, org, raw.name || key, "retrying", "CognitioFlow never answered the upload 24h ago");
      } else if (!raw.pending.surfaced) {
        setLedger(st, org, key, { ...raw, pending: { ...raw.pending, surfaced: true } });
        logLine(st, org, raw.name || key, "check in CF", "sent, but the answer was lost — check it is in CognitioFlow; it is retried after 24h");
      }
    }
  }

  /** Proves key + route without uploading anything: an empty POST is refused with 413 by the key gate,
      which only happens after the key was accepted for this course. */
  async function testKey({ cid }) {
    const { appUrl, courses } = await conf();
    if (!courses.some((c) => c.cid === cid)) throw new Error("that CognitioFlow course is not in your course list");
    const { cfKeys } = await local({ cfKeys: {} });
    const key = cfKeys[cid];
    if (!key || !key.token) return { ok: false, state: STATE.keyMissing };
    const target = keyTarget(key, appUrl);
    if (target.error) return { ok: false, state: target.error === "origin" ? STATE.keyOrigin : STATE.error, detail: target.detail };
    const res = await fetch(`${target.origin}/api/courses/${encodeURIComponent(cid)}/files`, {
      method: "POST", headers: { authorization: `Bearer ${key.token}` }, credentials: "omit",
    });
    if (res.status === 413) return { ok: true, state: STATE.ok };
    if (res.status === 401) return { ok: false, state: STATE.keyExpired };
    if (res.status === 403) return { ok: false, state: STATE.keyWrongCourse };
    return { ok: false, state: STATE.error, detail: `unexpected ${res.status}` };
  }

  /* ------------------------------------------------------------------ the run */

  const logLine = (st, org, name, action, error = "") => {
    const line = { at: now(), org: String(org), name, action, ...(error ? { error } : {}) };
    st.log.push(line);
    if (st.log.length > LOG_MAX) st.log.splice(0, st.log.length - LOG_MAX);
    dirty(st).log.push(line);
  };

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
    // Read errors belong to the list in `pending`: until this run has read the course again, the last
    // scan's errors are kept, whatever state is written (a sign-in stop must not make a stale list look
    // complete to finishReview).
    let readErrors = null;
    const setStatus = (state, detail = "", extra = {}) => {
      const prev = st.status[org];
      const errs = readErrors || (prev && prev.readErrors) || [];
      st.status[org] = { state, detail, at: now(), ...extra, ...(errs.length ? { readErrors: errs } : {}) };
      dirty(st).status.add(org);
    };
    const book = () => (st.ledger[org] = st.ledger[org] || {});
    const shas = () => (st.shaByCid[cid] = st.shaByCid[cid] || []);

    let found;
    try {
      found = await collect(rd, org);
    } catch (e) {
      if (e.login) { setStatus(STATE.login, "Open Brightspace and sign in; nothing was uploaded."); logLine(st, org, "", "stopped", STATE.login); }
      else { setStatus(STATE.error, String(e.message || e)); logLine(st, org, "", "scan failed", String(e.message || e)); }
      return { uploaded: 0, fresh: 0 };
    }
    const { items, emptyPages } = found;
    readErrors = found.readErrors;
    reviewMarkers(st, org);
    const notHandled = (list) => unseen(list, st.seen[org] || []).filter((i) => !book()[i.key]);
    if (st.confirmed[org]) setPending(st, org, notHandled(items));
    else {
      // First review: a file the popup already showed stays in the list until it is decided, even if this
      // scan no longer finds it (a wrapper page being edited, a topic briefly hidden). Otherwise a shrinking
      // list would finish the review and the file would auto-upload, undecided, when it comes back.
      const listed = notHandled(items);
      const here = new Set(listed.map((i) => i.key));
      const gone = notHandled((st.pending[org] || []).filter((i) => i && i.key && !here.has(i.key)))
        .map((i) => ({ ...i, missing: true }));
      setPending(st, org, [...listed, ...gone]);
    }
    const extra = emptyPages.length ? { emptyPages } : {};
    // A first review whose list is now complete and fully decided is finished, even if the last Add /
    // Remember happened while a page could not be read (otherwise nothing would ever finish it). `pending`
    // still holds every file shown during the review and not yet decided, so empty means all were decided.
    if (!st.confirmed[org] && !readErrors.length && items.length && !st.pending[org].length) {
      setConfirmed(st, org);
      logLine(st, org, "", "first review finished", "every file on Brightspace has a choice");
    }

    if (!doUpload) {   // a list refresh says nothing about the key: keep a key problem visible until a real run clears it
      const prev = st.status[org];
      const keyState = prev && [STATE.keyExpired, STATE.keyMissing, STATE.keyWrongCourse, STATE.keyOrigin, STATE.noAccess].includes(prev.state);
      if (!keyState) setStatus(STATE.ok, "", extra);
      else setStatus(prev.state, prev.detail || "", extra);   // same state, this scan's page notes
      return { uploaded: 0, fresh: st.confirmed[org] ? st.pending[org].length : 0 }; }
    if (!cid) { setStatus(STATE.ok, "not linked to a CognitioFlow course", extra); return { uploaded: 0, fresh: 0 }; }
    if (!st.confirmed[org]) { setStatus(STATE.review, "Choose Add or 'I already have these' for every file in the popup, or run the baseline in Options.", extra); return { uploaded: 0, fresh: 0 }; }
    if (!st.auto[org]) { setStatus(STATE.autoOff, "", extra); return { uploaded: 0, fresh: st.pending[org].length }; }

    const key = st.cfKeys[cid];   // the key this run started with; changedUnderUs() stops the run if it goes
    if (!key || !key.token) { setStatus(STATE.keyMissing, "Create a sync key in Options.", extra); return { uploaded: 0, fresh: st.pending[org].length }; }
    if (key.courseId && key.courseId !== cid) { setStatus(STATE.keyWrongCourse, "", extra); return { uploaded: 0, fresh: 0 }; }
    if (key.expires && key.expires < now()) { setStatus(STATE.keyExpired, "Renew the sync key in Options.", extra); return { uploaded: 0, fresh: st.pending[org].length }; }
    const target = keyTarget(key, appUrl);
    if (target.error) { setStatus(target.error === "origin" ? STATE.keyOrigin : STATE.error, target.detail, extra); return { uploaded: 0, fresh: 0 }; }
    if (!(await canReachApp(appUrl))) { setStatus(STATE.noAccess, "Allow access to the CognitioFlow address in Options.", extra); return { uploaded: 0, fresh: 0 }; }

    /** Where this item stands right now, from the (refreshed) snapshot. */
    const look = (item) => {
      const raw = book()[item.key] || null;
      const inflight = raw && raw.pending ? raw.pending : null;
      const entry = settled(raw);
      const seen = st.seen[org] || [];
      const holding = !!inflight && now() - inflight.at < PENDING_HOLD_MS;
      return { raw, inflight, entry, seen, holding, handled: seen.includes(item.key) || !!entry };
    };

    /** Auto switched off, or the key removed / replaced, since the run started: stop this course here. */
    const stopNow = async (why, name = "") => {
      setStatus(why.state, why.detail, extra);
      logLine(st, org, name, "stopped", why.state);
      setPending(st, org, notHandled(items));
      await persist(st);
    };
    const changedUnderUs = (cur) => {
      if (!cur.auto[org]) return { state: STATE.autoOff, detail: "Auto was switched off during the run; nothing more was sent." };
      if (!sameKey(cur.cfKeys, cid, key))
        return keyProblem(cur.cfKeys[cid], cid, appUrl) || { state: STATE.error, detail: "The sync key changed during the run; the next run uses the new one." };
      return null;
    };

    let uploaded = 0;
    let failed = 0;
    for (const item of items) {
      let at = look(item);
      if (at.handled && !at.holding && item.kind === "link") {
        try { Object.assign(item, await rd.head(item.url)); } catch { /* no HEAD answer = no signal; the TOC read already proved the session */ }
      }
      const verdict = at.holding ? "hold" : decide(item, { seen: at.seen, entry: at.entry });
      if (verdict === "skip") continue;
      if (verdict === "adopt") {
        setLedger(st, org, item.key, { ...(at.entry || {}), signal: signalOf(item), at: now(), name: item.name });
        await persist(st);
        continue;
      }
      if (verdict !== "hold" && budget.left <= 0) break;
      if (leaseLost(st)) { setStatus(STATE.error, "another sync took over; the rest waits for the next run"); await persist(st); return { uploaded, fresh: 0 }; }

      // Re-validate the moment before acting: a Remember / Add / other context may have handled it meanwhile.
      const before = JSON.stringify([at.raw, at.seen.includes(item.key)]);
      await persist(st);
      at = look(item);
      if (JSON.stringify([at.raw, at.seen.includes(item.key)]) !== before) continue;   // changed under us: next run decides
      const why = changedUnderUs(st);                 // `st.auto` / `st.cfKeys` were just re-read by persist()
      if (why) { await stopNow(why, item.name); return { uploaded, fresh: 0 }; }
      const expect = stateOf(st, org, item.key);

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
      const { entry, inflight } = at;
      if (got.size > MAX_UPLOAD_BYTES) {
        setLedger(st, org, item.key, { signal: signalOf(item), at: now(), name: item.name, skipped: "too big" });
        logLine(st, org, item.name, "skipped", `too big (${Math.round(got.size / 1048576)}MB) — add it by hand`);
        await persist(st); continue;
      }
      const sha = await sha256(got.bytes);
      if (verdict === "hold" && sha === inflight.sha) continue;   // sent before, answer lost: never re-sent blindly (surfaced by reviewMarkers)
      if (verdict === "hold" && budget.left <= 0) continue;   // new bytes since the lost send: an upload, so it needs budget
      if (entry && entry.sha === sha) {             // the date moved, the bytes did not
        setLedger(st, org, item.key, { ...entry, signal: signalOf(item), at: now() });
        await persist(st); continue;
      }
      if (entry && !entry.sha) {
        // Handled before sync knew its bytes (baseline, Remember, hand-added like PIL Lecture 1). A moved
        // date may be a renamed topic or an unstable header, so learn the hash instead of uploading a twin.
        setLedger(st, org, item.key, { ...entry, signal: signalOf(item), sha, at: now() });
        if (!shas().includes(sha)) shas().push(sha);
        logLine(st, org, item.name, "changed on Brightspace; not re-uploaded (it was added by hand) — add it again yourself if the content is new");
        await persist(st); continue;
      }
      if (shas().includes(sha)) {                    // same bytes reached through another key: already in CF
        setLedger(st, org, item.key, { signal: signalOf(item), sha, at: now(), name: item.name, duplicateOf: "sha" });
        markSeen(st, org, item.key);
        logLine(st, org, item.name, "already in CognitioFlow");
        await persist(st); continue;
      }

      budget.left--;
      const r = await guardedUpload(st, org, { appUrl, cid, key, item, got, sha, entry, expect, gate: changedUnderUs });
      if (r.conflict) { budget.left++; continue; }   // handled by someone else while it downloaded
      if (r.stopped) { budget.left++; await stopNow(r.stopped, item.name); return { uploaded, fresh: 0 }; }
      if (!r.ok) {
        if (r.http === 401) { setStatus(STATE.keyExpired, "CognitioFlow refused the key; renew it in Options."); logLine(st, org, item.name, "stopped", STATE.keyExpired); await persist(st); return { uploaded, fresh: 0 }; }
        if (r.http === 403) { setStatus(STATE.keyWrongCourse, ""); logLine(st, org, item.name, "stopped", STATE.keyWrongCourse); await persist(st); return { uploaded, fresh: 0 }; }
        if (r.http === 413) {
          setLedger(st, org, item.key, { signal: signalOf(item), at: now(), name: item.name, skipped: "too big" });
          logLine(st, org, item.name, "skipped", "CognitioFlow says too large"); await persist(st); continue;
        }
        failed++; logLine(st, org, item.name, "upload failed", r.error);   // NOT marked: next run tries again
        await persist(st); continue;
      }
      setLedger(st, org, item.key, { signal: signalOf(item), sha, cfFileId: r.id, status: r.status, at: now(), name: item.name });
      markSeen(st, org, item.key);
      shas().push(sha);
      uploaded++;
      logLine(st, org, item.name, entry ? "updated (old version still in CognitioFlow)" : "uploaded");
      setPending(st, org, notHandled(items));
      await persist(st);
      if (budget.left > 0) await sleep(pauseMs);
    }
    setPending(st, org, notHandled(items));
    setStatus(failed ? STATE.error : STATE.ok, failed ? `${failed} file(s) failed; they will be retried` : "", { uploaded, ...extra });
    return { uploaded, fresh: 0 };
  }

  /** Every mapped course (or just `orgs`). upload=false only refreshes the popup list. */
  function run({ upload: doUpload = true, orgs = null } = {}) {
    return withLock(async (lease) => {
      const { appUrl, courses } = await conf();
      const st = await local();
      leaseOf.set(st, lease);
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

  /** The first review of a course is finished only when nothing in it is left undecided: a file left
      unticked stays pending (never auto-uploaded) until it is added or remembered. A course already
      reviewed stays reviewed. Runs inside the state lock; `cur` is fresh from disk. */
  const finishReview = (cur, org) => {
    if (!cur.status) return;   // a caller that did not load status cannot know the list was complete: fail closed
    const errs = (cur.status[org] && cur.status[org].readErrors) || [];
    if (!(cur.pending[org] || []).length && !errs.length) cur.confirmed[org] = true;
  };

  /** Popup "Add": the chosen keys go up now, through the same checks, whatever auto says. */
  async function uploadKeys({ org, keys }) {
    return withLock(async (lease) => {
      const { appUrl, courses } = await conf();
      const course = courses.find((c) => String(c.org) === String(org));
      if (!course || !course.cid) throw new Error("This course is not linked to a CognitioFlow course yet (Options)");
      const o = String(org);
      const st = await local();
      leaseOf.set(st, lease);
      // A popup list can be older than a killed upload's marker (the popup showed the disk list while the
      // dead run's lease was live). Same rule as the run: surface the marker, take back a 24h-old one, and
      // never offer a file that is handled or held.
      reviewMarkers(st, o);
      await persist(st);
      const book = st.ledger[o] || {};
      const heldNames = keys.filter((k) => held(book[k])).map((k) => book[k].name || k);
      const handled = (k) => (st.seen[o] || []).includes(k) || !!book[k];
      const list = (st.pending[o] || []).filter((i) => keys.includes(i.key) && !handled(i.key));
      const r = await syncItems(st, course, list, { appUrl, budget: { left: list.length }, rd: reader() });
      await mutate(async () => {
        const cur = await local({ pending: {}, confirmed: {}, status: {} });
        finishReview(cur, o);
        await chrome.storage.local.set({ confirmed: cur.confirmed });
      });
      return { added: r.added, failed: r.failed, held: [...heldNames, ...r.held] };
    });
  }

  /** Upload a fixed list (popup Add). Same pipeline as the run, minus the walk and the auto gate. */
  async function syncItems(st, course, list, { appUrl, budget, rd }) {
    const org = String(course.org);
    const cid = course.cid;
    const key = st.cfKeys[cid];
    if (!key || !key.token) throw new Error("No sync key for this course (Options)");
    if (key.courseId && key.courseId !== cid) throw new Error("That key belongs to another course");
    const target = keyTarget(key, appUrl);
    if (target.error) throw new Error(target.detail);
    const shas = () => (st.shaByCid[cid] = st.shaByCid[cid] || []);
    const keyGone = () => Object.assign(new Error("The sync key was removed or replaced during the Add; nothing more was sent."), { stop: true });
    const gate = (cur) => (sameKey(cur.cfKeys, cid, key) ? null : { state: STATE.keyMissing });
    const failed = [];
    const heldNames = [];
    let added = 0;
    for (const item of list) {
      if (budget.left-- <= 0) break;
      try {
        if (leaseLost(st)) throw new Error("another sync took over");
        if (gate(st)) throw keyGone();                // `st.cfKeys` was re-read by the last persist()
        const expect = stateOf(st, org, item.key);
        const got = await rd.file(item.url);
        if (!looksLikeDocument(item.name, got.type, got.bytes)) throw new LoginNeeded("got a web page instead of the file");
        if (got.size > MAX_UPLOAD_BYTES) throw new Error("too big — add it by hand");
        const sha = await sha256(got.bytes);
        const raw = (st.ledger[org] || {})[item.key];
        if (held(raw) && raw.pending.sha === sha) { heldNames.push(item.name); continue; }   // sent before, answer lost: same rule as the run
        if (!shas().includes(sha)) {
          const entry = settled(raw);
          const r = await guardedUpload(st, org, { appUrl, cid, key, item, got, sha, entry, expect, gate });
          if (r.conflict) continue;   // remembered / added elsewhere meanwhile
          if (r.stopped) throw keyGone();
          if (!r.ok) throw new Error(r.http === 401 ? "CognitioFlow key expired (Options)" : r.error);
          setLedger(st, org, item.key, { signal: signalOf(item), sha, cfFileId: r.id, status: r.status, at: now(), name: item.name });
          shas().push(sha);
          added++;
          logLine(st, org, item.name, "uploaded");
        } else {
          setLedger(st, org, item.key, { signal: signalOf(item), sha, at: now(), name: item.name, duplicateOf: "sha" });
          logLine(st, org, item.name, "already in CognitioFlow");
        }
        markSeen(st, org, item.key);
        setPending(st, org, (st.pending[org] || []).filter((i) => i.key !== item.key));
        await persist(st);
      } catch (e) {
        failed.push({ name: item.name, error: e.login ? STATE.login : String(e.message || e) });
        logLine(st, org, item.name, e.stop ? "stopped" : "upload failed", String(e.message || e));
        await persist(st);
        if (e.login || e.stop) break;
      }
    }
    return { added, failed, held: heldNames };
  }

  /** First run for a course: mark what is on Brightspace now as handled, without uploading.
      mode "all": everything. mode "match": only files whose name is already in CognitioFlow (`names`,
      read by Options from a signed-in CognitioFlow tab); the rest stays pending and goes up automatically.
      Files the list showed that this scan no longer finds are decided the same way and reported in `left`. */
  async function baseline({ org, mode = "all", names = [] }) {
    return withLock(async (lease) => {
      const { courses } = await conf();
      const course = courses.find((c) => String(c.org) === String(org));
      if (!course) throw new Error("not a course in your list");
      const st = await local();
      leaseOf.set(st, lease);
      const { items } = await collect(reader(), String(org));
      // Files the list already showed that this scan does not find (a wrapper read link-less, a topic briefly
      // hidden) are part of what the baseline decides too: otherwise they would come back after `confirmed`
      // and go up, never decided. Not keyed on `missing`: a baseline can run before a scan has set it.
      const here = new Set(items.map((i) => i.key));
      const handledKey = (k) => (st.seen[org] || []).includes(k) || !!(st.ledger[org] || {})[k];
      const shown = unseen((st.pending[org] || []).filter((i) => i && i.key && !here.has(i.key) && !handledKey(i.key)), []);
      const marked = [];
      for (const it of [...items, ...shown]) {
        if (mode === "match" && !names.some((n) => sameName(n, it.name))) continue;
        setLedger(st, org, it.key, { ...(settled((st.ledger[org] || {})[it.key]) || {}), signal: signalOf(it), at: now(), name: it.name, baseline: true });
        markSeen(st, org, it.key);
        marked.push(it.name);
      }
      const undecided = (list) => unseen(list, st.seen[org] || []).filter((i) => !(st.ledger[org] || {})[i.key]);
      setPending(st, org, [...undecided(items), ...undecided(shown).map((i) => ({ ...i, missing: true }))]);
      setConfirmed(st, org);   // the baseline is the explicit choice for everything it leaves: "upload these"
      logLine(st, org, `${marked.length} file(s)`, `baseline (${mode})`);
      await persist(st);
      return { marked, left: st.pending[org].map((i) => i.name) };
    });
  }

  return { run, syncCourse, uploadKeys, baseline, testKey, reader, collect, mutate, finishReview };
}

/** Badge from the last run: BS (sign in, amber) > KEY (red) > ! (other) > number uploaded (green) > pending (blue). */
export function badgeFor({ status = {}, pending = {}, lastRun = null }) {
  const states = Object.values(status).map((s) => s && s.state);
  if (states.includes(STATE.login)) return { text: "BS", color: "#b7791f" };
  if (states.some((s) => [STATE.keyExpired, STATE.keyWrongCourse, STATE.keyMissing, STATE.keyOrigin].includes(s))) return { text: "KEY", color: "#c53030" };
  if (states.some((s) => [STATE.error, STATE.noAccess].includes(s))) return { text: "!", color: "#c53030" };
  if (lastRun && lastRun.uploaded) return { text: String(lastRun.uploaded), color: "#2f855a" };
  const n = Object.values(pending).reduce((a, l) => a + (l ? l.length : 0), 0);
  return { text: n ? String(n) : "", color: "#24467a" };
}
