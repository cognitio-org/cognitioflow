/* Automatic sync, end to end, with fake chrome.* and a fake fetch. No network is touched.
   Storage is JSON round-tripped on every get/set, as chrome.storage does, so a Set or a shared live
   object that would not survive the real thing fails here too. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createSync, badgeFor, STATE, BS_ORIGIN } from "../sync.js";

const fixture = (name) => readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8");
const TOC = JSON.parse(fixture("pil-toc.synthetic.json"));
const WRAPPER = fixture("pil-wrapper.synthetic.html");
const FOLDER = "/content/enforced/564701-RGBIR50010.2026-2027.1";
const APP = "https://app.cognitioflow.ai";
const enc = (p) => p.split("/").map(encodeURIComponent).join("/");

const pdf = (label) => new TextEncoder().encode(`%PDF-1.7\n${label}\n%%EOF`);
const docx = (label) => new Uint8Array([0x50, 0x4b, 0x03, 0x04, ...new TextEncoder().encode(label)]);

function response({ status = 200, url, type = "application/json", body = "", headers = {}, rtype = "basic" }) {
  const h = { "content-type": type, ...headers };
  const bytes = () => (body instanceof Uint8Array ? body : new TextEncoder().encode(typeof body === "string" ? body : JSON.stringify(body)));
  return {
    ok: status >= 200 && status < 300, status, url, type: rtype,
    headers: { get: (n) => h[n.toLowerCase()] ?? null },
    json: async () => (typeof body === "string" ? JSON.parse(body) : body),
    text: async () => (typeof body === "string" ? body : new TextDecoder().decode(bytes())),
    arrayBuffer: async () => bytes().slice().buffer,
  };
}

/** One world: Brightspace routes (path -> response factory), CognitioFlow recorder, chrome fake. */
const HANG = Symbol("the worker is killed while this request is in flight");

/** `store` lets two sync instances (two worker contexts) share one chrome.storage; `locks` is the Web Locks
    manager they share (null = none, the fallback path); `start` sets the fake clock; a CF handler that
    returns HANG never answers, like a worker killed mid-request. */
function world({ bs = {}, cf = () => ({ status: 200, body: { id: "f1", status: "indexed" } }), local = {}, sync = {}, tabs = [], maxPerRun = 20,
                 store: shared = null, locks, start = "2026-11-10T12:00:00Z" } = {}) {
  const store = shared || { local: JSON.parse(JSON.stringify(local)), sync: JSON.parse(JSON.stringify(sync)) };
  const area = (name) => ({
    get: async (d = {}) => JSON.parse(JSON.stringify({ ...d, ...pick(store[name], d) })),
    set: async (v) => { Object.assign(store[name], JSON.parse(JSON.stringify(v))); },
  });
  const pick = (obj, d) => Object.fromEntries(Object.keys(d).filter((k) => k in obj).map((k) => [k, obj[k]]));
  const calls = { bs: [], cf: [], tab: [] };
  const fetch = async (url, init = {}) => {
    url = String(url);
    if (url.startsWith(BS_ORIGIN)) {
      const path = url.slice(BS_ORIGIN.length);
      calls.bs.push({ path, method: init.method || "GET", auth: init.headers && (init.headers.authorization || init.headers.Authorization) });
      const route = bs[path] || bs[decodeURI(path)];
      if (!route) return response({ status: 404, url, type: "text/plain", body: "not found" });
      return response({ url, ...route(init) });
    }
    if (url.startsWith(APP)) {
      const file = init.body && init.body.get ? init.body.get("file") : null;
      const call = {
        url, cid: decodeURIComponent(url.split("/api/courses/")[1].split("/")[0]),
        auth: init.headers && init.headers.authorization, name: file && file.name,
        week: init.body && init.body.get ? init.body.get("week") : null,
      };
      calls.cf.push(call);
      const out = cf(call);
      if (out === HANG) return new Promise(() => {});
      return response({ url, ...out });
    }
    throw new Error(`test touched an unexpected host: ${url}`);
  };
  const chrome = {
    storage: { local: area("local"), sync: area("sync") },
    tabs: {
      query: async () => tabs,
      sendMessage: async (id, msg) => { calls.tab.push(msg); return { ok: false, error: "401 on tab" }; },
    },
    permissions: { contains: async () => true },
  };
  let clock = Date.parse(start);
  const s = createSync({ chrome, fetch, sleep: async () => {}, now: () => (clock += 1000), maxPerRun, ...(locks !== undefined ? { locks } : {}) });
  return { s, store, calls, chrome };
}

const COURSES = [{ org: "564701", name: "PIL", cid: "pil" }, { org: "564708", name: "LaPoPo", cid: "lapopo" }];
const FAR = Date.parse("2027-01-31T00:00:00Z");
const KEYS = {
  pil: { token: "cfw_PIL_secret", courseId: "pil", expires: FAR, id: "k1", origin: APP },
  lapopo: { token: "cfw_LAPOPO_secret", courseId: "lapopo", expires: FAR, id: "k2", origin: APP },
};
const READY = { confirmed: { 564701: true, 564708: true }, auto: { 564701: true, 564708: true }, cfKeys: KEYS };
const CONF = { appUrl: APP, courses: COURSES };

/** PIL as the synthetic fixture describes it: one plain PDF topic, one HTML wrapper with three documents. */
const pilRoutes = (over = {}) => ({
  "/d2l/api/le/1.97/564701/content/toc": () => ({ body: TOC }),
  "/d2l/api/le/1.97/564701/content/modules/101": () => ({ body: { Description: { Html: "" } } }),
  "/d2l/api/le/1.97/564701/content/modules/102": () => ({ body: { Description: { Html: "" } } }),
  "/d2l/le/content/564701/topics/files/download/9001/DirectFileTopicDownload": () => ({ type: "application/pdf", body: pdf("lecture 1") }),
  [enc(`${FOLDER}/Week 2/Lecture 2.html`)]: () => ({ type: "text/html", body: WRAPPER }),
  [enc(`${FOLDER}/Week 2/Lecture 2 slides.pdf`)]: () => ({ type: "application/pdf", body: pdf("lecture 2"), headers: { etag: '"l2-v1"' } }),
  [enc(`${FOLDER}/Readings/Reading week 2.pdf`)]: () => ({ type: "application/pdf", body: pdf("reading 2"), headers: { etag: '"r2-v1"' } }),
  [enc(`${FOLDER}/Week 2/Handout 2.docx`)]: () => ({ type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", body: docx("handout 2"), headers: { etag: '"h2-v1"' } }),
  ...over,
});
const lapopoRoutes = (over = {}) => ({
  "/d2l/api/le/1.97/564708/content/toc": () => ({ body: { Modules: [{ ModuleId: 201, Title: "Week 1: Legal theory", Modules: [], Topics: [
    { TopicId: 8001, Title: "LaPoPo lecture 1", TypeIdentifier: "File", Url: "/content/enforced/564708-X/LaPoPo 1.pdf", LastModifiedDate: "2026-11-04T08:00:00Z" },
  ] }] } }),
  "/d2l/api/le/1.97/564708/content/modules/201": () => ({ body: { Description: { Html: "" } } }),
  "/d2l/le/content/564708/topics/files/download/8001/DirectFileTopicDownload": () => ({ type: "application/pdf", body: pdf("lapopo 1") }),
  ...over,
});

/* ------------------------------------------------------------------ required behaviours */

test("already-synced files are skipped: no download, no upload", async () => {
  const first = world({ bs: pilRoutes(), local: READY, sync: { ...CONF, courses: [COURSES[0]] } });
  const r1 = await first.s.run();
  assert.equal(r1.uploaded, 4);
  // Second run on the stored state: everything has a ledger entry with an unchanged signal.
  const again = world({ bs: pilRoutes(), local: first.store.local, sync: { ...CONF, courses: [COURSES[0]] } });
  const r2 = await again.s.run();
  assert.equal(r2.uploaded, 0);
  assert.equal(again.calls.cf.length, 0, "nothing sent to CognitioFlow");
  assert.ok(!again.calls.bs.some((c) => /DirectFileTopicDownload|\.pdf$|\.docx$/.test(c.path) && c.method === "GET"),
            "no file bytes downloaded when the signal is unchanged");
  assert.equal(again.store.local.status["564701"].state, STATE.ok);
});

test("a file added by hand before sync existed (PIL Lecture 1 via popup Remember) is adopted, not re-uploaded", async () => {
  // seen has the key (manual Add/Remember in v0.1), but there is no ledger entry and no signal yet.
  const w = world({ bs: pilRoutes(), local: { ...READY, seen: { 564701: ["t:9001"] } }, sync: { ...CONF, courses: [COURSES[0]] } });
  await w.s.run();
  assert.ok(!w.calls.cf.some((c) => c.name === "Lecture 1.pdf"), "Lecture 1 must not go up twice");
  assert.equal(w.store.local.ledger["564701"]["t:9001"].signal, "2026-11-03T10:00:00.000Z", "it adopts the TOC date as its baseline");
  assert.equal(w.calls.cf.length, 3, "the three wrapped documents still go up");
});

test("baseline 'match' marks only what CognitioFlow already has; the rest stays pending for the next run", async () => {
  const w = world({ bs: pilRoutes(), local: { cfKeys: KEYS }, sync: { ...CONF, courses: [COURSES[0]] } });
  const r = await w.s.baseline({ org: "564701", mode: "match", names: ["lecture 1.pdf", "unrelated notes.pdf"] });
  assert.deepEqual(r.marked, ["Lecture 1.pdf"]);
  assert.equal(r.left.length, 3);
  assert.equal(w.calls.cf.length, 0, "a baseline never uploads");
  assert.equal(w.store.local.confirmed["564701"], true);
});

test("HTML-wrapped PDF is resolved: the slides inside the wrapper go up, the .html never does", async () => {
  const w = world({ bs: pilRoutes(), local: { ...READY, seen: { 564701: ["t:9001"] } }, sync: { ...CONF, courses: [COURSES[0]] } });
  await w.s.run();
  const names = w.calls.cf.map((c) => c.name).sort();
  assert.deepEqual(names, ["Handout 2.docx", "Lecture 2 slides.pdf", "Reading week 2.pdf"]);
  assert.ok(!names.some((n) => /\.html?$/i.test(n)), "the wrapper page itself is never uploaded");
  assert.ok(!w.calls.bs.some((c) => c.path.includes("elsewhere")), "an off-host link is never fetched");
  assert.equal(w.calls.cf.find((c) => c.name === "Lecture 2 slides.pdf").week, "2", "the module's week travels with it");
});

test("course A's key is never used for course B; a course without a key sends nothing", async () => {
  const w = world({ bs: { ...pilRoutes(), ...lapopoRoutes() }, local: READY, sync: CONF });
  await w.s.run();
  assert.ok(w.calls.cf.length >= 2);
  for (const c of w.calls.cf) {
    assert.equal(c.auth, `Bearer ${KEYS[c.cid].token}`, `upload to ${c.cid} carries ${c.cid}'s own key`);
  }
  assert.ok(w.calls.cf.some((c) => c.cid === "lapopo") && w.calls.cf.some((c) => c.cid === "pil"));
  assert.ok(w.calls.bs.every((c) => !c.auth), "no Authorization header ever goes to Brightspace");

  // Now LaPoPo has no key of its own: PIL's key must not be borrowed.
  const only = world({ bs: { ...pilRoutes(), ...lapopoRoutes() }, local: { ...READY, cfKeys: { pil: KEYS.pil } }, sync: CONF });
  await only.s.run();
  assert.equal(only.calls.cf.filter((c) => c.cid === "lapopo").length, 0);
  assert.ok(!only.calls.cf.some((c) => c.auth === `Bearer ${KEYS.pil.token}` && c.cid !== "pil"));
  assert.equal(only.store.local.status["564708"].state, STATE.keyMissing);

  // A key whose recorded course differs from the slot it sits in is refused before any request.
  const crossed = world({ bs: lapopoRoutes(), local: { ...READY, cfKeys: { lapopo: { ...KEYS.pil } } }, sync: { ...CONF, courses: [COURSES[1]] } });
  await crossed.s.run();
  assert.equal(crossed.calls.cf.length, 0);
  assert.equal(crossed.store.local.status["564708"].state, STATE.keyWrongCourse);
});

test("an upload failure leaves the file un-marked, and the next run retries it", async () => {
  const fail = world({ bs: lapopoRoutes(), local: READY, sync: { ...CONF, courses: [COURSES[1]] },
                      cf: () => ({ status: 500, body: { detail: "boom" } }) });
  await fail.s.run();
  const L = fail.store.local;
  assert.equal(fail.calls.cf.length, 1);
  assert.ok(!(L.seen["564708"] || []).includes("t:8001"), "not in seen");
  assert.equal((L.ledger["564708"] || {})["t:8001"], undefined, "no ledger entry");
  assert.deepEqual(L.shaByCid.lapopo || [], [], "its hash is not remembered either");
  assert.equal(L.status["564708"].state, STATE.error);
  assert.ok(L.log.some((l) => l.action === "upload failed" && l.name === "LaPoPo 1.pdf"));

  const retry = world({ bs: lapopoRoutes(), local: L, sync: { ...CONF, courses: [COURSES[1]] } });
  const r = await retry.s.run();
  assert.equal(r.uploaded, 1);
  assert.ok(retry.store.local.seen["564708"].includes("t:8001"));
});

for (const [label, toc] of [
  ["401 on the TOC", () => ({ status: 401, type: "text/html", body: "<html>sign in</html>" })],
  ["302 left unfollowed (opaque redirect)", () => ({ status: 0, rtype: "opaqueredirect", type: "", body: "" })],
  ["200 that is really the SSO page on another host", () => ({ status: 200, type: "text/html", body: "<!doctype html><html>SURFconext</html>", url: "https://signon.rug.nl/nidp/saml2/sso" })],
]) {
  test(`session-expired Brightspace (${label}) -> no upload, status 'login needed', badge BS`, async () => {
    const w = world({ bs: lapopoRoutes({ "/d2l/api/le/1.97/564708/content/toc": toc }), local: READY, sync: { ...CONF, courses: [COURSES[1]] } });
    await w.s.run();
    assert.equal(w.calls.cf.length, 0, "nothing reached CognitioFlow");
    assert.equal(w.store.local.status["564708"].state, "login needed");
    assert.equal(badgeFor(w.store.local).text, "BS");
  });
}

test("a download that comes back as the D2L login page stops the course before any upload", async () => {
  const w = world({
    bs: lapopoRoutes({ "/d2l/le/content/564708/topics/files/download/8001/DirectFileTopicDownload":
      () => ({ status: 200, type: "text/html", body: "<!doctype html><html>login</html>", url: `${BS_ORIGIN}/d2l/login?target=x` }) }),
    local: READY, sync: { ...CONF, courses: [COURSES[1]] },
  });
  await w.s.run();
  assert.equal(w.calls.cf.length, 0);
  assert.equal(w.store.local.status["564708"].state, "login needed");
  assert.ok(!(w.store.local.seen["564708"] || []).includes("t:8001"));
});

/* ------------------------------------------------------------------ the rest of the plan's checks */

test("first-run gate: an unreviewed course never uploads, even with a key and auto on", async () => {
  const w = world({ bs: lapopoRoutes(), local: { ...READY, confirmed: {} }, sync: { ...CONF, courses: [COURSES[1]] } });
  await w.s.run();
  assert.equal(w.calls.cf.length, 0);
  assert.equal(w.store.local.status["564708"].state, STATE.review);
  assert.equal(w.store.local.pending["564708"].length, 1, "the popup still lists it for review");
});

test("an org that is not in the Options map is never read or uploaded", async () => {
  const w = world({ bs: lapopoRoutes(), local: { ...READY, auto: { 999: true }, confirmed: { 999: true } }, sync: { ...CONF, courses: [COURSES[0]] } });
  const r = await w.s.run({ orgs: ["999"] });
  assert.deepEqual(r, { skipped: "not a mapped course" });
  assert.equal(w.calls.bs.length, 0);
  assert.equal(w.calls.cf.length, 0);
});

test("same bytes reached through two keys upload once", async () => {
  const same = pdf("identical");
  const w = world({
    bs: lapopoRoutes({
      "/d2l/api/le/1.97/564708/content/toc": () => ({ body: { Modules: [{ ModuleId: 201, Title: "Week 1", Modules: [], Topics: [
        { TopicId: 8001, Title: "A", TypeIdentifier: "File", Url: "/content/enforced/564708-X/A.pdf", LastModifiedDate: "d1" },
        { TopicId: 8002, Title: "B (same file, re-posted)", TypeIdentifier: "File", Url: "/content/enforced/564708-X/B.pdf", LastModifiedDate: "d1" },
      ] }] } }),
      "/d2l/le/content/564708/topics/files/download/8001/DirectFileTopicDownload": () => ({ type: "application/pdf", body: same }),
      "/d2l/le/content/564708/topics/files/download/8002/DirectFileTopicDownload": () => ({ type: "application/pdf", body: same }),
    }),
    local: READY, sync: { ...CONF, courses: [COURSES[1]] },
  });
  await w.s.run();
  assert.equal(w.calls.cf.length, 1);
  assert.ok(w.store.local.seen["564708"].includes("t:8002"), "the twin is remembered as handled");
  assert.ok(w.store.local.log.some((l) => l.action === "already in CognitioFlow"));
});

test("a changed file (new TOC date, new bytes) goes up again and is logged as an update", async () => {
  const first = world({ bs: lapopoRoutes(), local: READY, sync: { ...CONF, courses: [COURSES[1]] } });
  await first.s.run();
  const changed = lapopoRoutes({
    "/d2l/api/le/1.97/564708/content/toc": () => ({ body: { Modules: [{ ModuleId: 201, Title: "Week 1", Modules: [], Topics: [
      { TopicId: 8001, Title: "LaPoPo lecture 1", TypeIdentifier: "File", Url: "/content/enforced/564708-X/LaPoPo 1.pdf", LastModifiedDate: "2026-11-12T08:00:00Z" },
    ] }] } }),
    "/d2l/le/content/564708/topics/files/download/8001/DirectFileTopicDownload": () => ({ type: "application/pdf", body: pdf("lapopo 1, corrected") }),
  });
  const w = world({ bs: changed, local: first.store.local, sync: { ...CONF, courses: [COURSES[1]] } });
  await w.s.run();
  assert.equal(w.calls.cf.length, 1);
  assert.ok(w.store.local.log.some((l) => /^updated/.test(l.action)));
  assert.equal(w.store.local.ledger["564708"]["t:8001"].signal, "2026-11-12T08:00:00Z");
});

test("a CognitioFlow 401 marks the key expired, stops the course and shows KEY", async () => {
  const w = world({ bs: pilRoutes(), local: READY, sync: { ...CONF, courses: [COURSES[0]] }, cf: () => ({ status: 401, body: { detail: "Unknown or revoked key" } }) });
  await w.s.run();
  assert.equal(w.calls.cf.length, 1, "stops after the first refusal");
  assert.equal(w.store.local.status["564701"].state, STATE.keyExpired);
  assert.equal(badgeFor(w.store.local).text, "KEY");
});

test("per-run cap: at most N uploads, the rest wait for the next run", async () => {
  const w = world({ bs: pilRoutes(), local: READY, sync: { ...CONF, courses: [COURSES[0]] }, maxPerRun: 2 });
  const r = await w.s.run();
  assert.equal(r.uploaded, 2);
  assert.equal(w.calls.cf.length, 2);
  assert.equal(w.store.local.pending["564701"].length, 2, "the other two are still pending");
  const next = world({ bs: pilRoutes(), local: w.store.local, sync: { ...CONF, courses: [COURSES[0]] }, maxPerRun: 2 });
  assert.equal((await next.s.run()).uploaded, 2);
});

test("the ledger is on disk after each file, not only at the end of the run", async () => {
  const snapshots = [];
  const w = world({ bs: pilRoutes(), local: READY, sync: { ...CONF, courses: [COURSES[0]] },
    cf: (call) => {
      const book = (w.store.local.ledger || {})["564701"] || {};
      snapshots.push([Object.values(book).filter((e) => !e.pending).length, Object.values(book).filter((e) => e.pending).length]);
      return { status: 200, body: { id: call.name } };
    } });
  await w.s.run();
  // before the k-th upload, k-1 finished uploads are persisted, plus the in-flight marker of the k-th itself
  assert.deepEqual(snapshots, [[0, 1], [1, 1], [2, 1], [3, 1]]);
  assert.ok(Object.values(w.store.local.ledger["564701"]).every((e) => !e.pending), "every marker is settled after its 2xx");
});

test("an expired key never leaves the extension", async () => {
  const w = world({ bs: lapopoRoutes(), local: { ...READY, cfKeys: { lapopo: { ...KEYS.lapopo, expires: Date.parse("2026-01-01") } } }, sync: { ...CONF, courses: [COURSES[1]] } });
  await w.s.run();
  assert.equal(w.calls.cf.length, 0);
  assert.equal(w.store.local.status["564708"].state, STATE.keyExpired);
});

test("testKey: 413 on an empty POST means the key and the route are good", async () => {
  const w = world({ local: { cfKeys: KEYS }, sync: CONF, cf: () => ({ status: 413, body: {} }) });
  assert.deepEqual(await w.s.testKey({ cid: "pil" }), { ok: true, state: STATE.ok });
  assert.equal(w.calls.cf[0].auth, `Bearer ${KEYS.pil.token}`);
  await assert.rejects(w.s.testKey({ cid: "not-mine" }));
});


test("a baselined file whose date moves (same bytes) is hashed once and never re-uploaded", async () => {
  const w = world({ bs: lapopoRoutes(), local: { cfKeys: KEYS, auto: { 564708: true } }, sync: { ...CONF, courses: [COURSES[1]] } });
  await w.s.baseline({ org: "564708", mode: "all" });
  await w.s.run();
  assert.equal(w.calls.cf.length, 0);
  const moved = lapopoRoutes({ "/d2l/api/le/1.97/564708/content/toc": () => ({ body: { Modules: [{ ModuleId: 201, Title: "Week 1", Modules: [], Topics: [
    { TopicId: 8001, Title: "LaPoPo lecture 1 (renamed)", TypeIdentifier: "File", Url: "/content/enforced/564708-X/LaPoPo 1.pdf", LastModifiedDate: "2026-11-20T08:00:00Z" },
  ] }] } }) });
  const again = world({ bs: moved, local: w.store.local, sync: { ...CONF, courses: [COURSES[1]] } });
  await again.s.run();
  assert.equal(again.calls.cf.length, 0, "no twin of a hand-added file");
  const e = again.store.local.ledger["564708"]["t:8001"];
  assert.ok(e.sha && e.signal === "2026-11-20T08:00:00Z");
  // and from now on a real content change is detectable
  const third = world({ bs: lapopoRoutes({ ...Object.fromEntries([["/d2l/api/le/1.97/564708/content/toc", moved["/d2l/api/le/1.97/564708/content/toc"]]]) }), local: again.store.local, sync: { ...CONF, courses: [COURSES[1]] } });
  await third.s.run();
  assert.equal(third.calls.cf.length, 0, "unchanged signal: no download, no upload");
});

test("a HEAD that fails on a linked file is 'no signal', not a sign-in problem", async () => {
  const first = world({ bs: pilRoutes(), local: READY, sync: { ...CONF, courses: [COURSES[0]] } });
  await first.s.run();
  const headFails = pilRoutes();
  const p = enc(`${FOLDER}/Readings/Reading week 2.pdf`);
  headFails[p] = (init) => (init.method === "HEAD" ? { status: 403, type: "text/html", body: "" } : { type: "application/pdf", body: pdf("reading 2") });
  const w = world({ bs: headFails, local: first.store.local, sync: { ...CONF, courses: [COURSES[0]] } });
  await w.s.run();
  assert.equal(w.store.local.status["564701"].state, STATE.ok);
  assert.equal(w.calls.cf.length, 0);
});

/* ------------------------------------------------------------------ adversarial-review regressions */

const PIL_ONLY = { ...CONF, courses: [COURSES[0]] };
const HANDOUT = `f:${FOLDER}/Week 2/Handout 2.docx`;
/** What background.js skip() ("I already have these") writes, done straight on the store mid-run. */
const rememberBehindTheRunsBack = (store, key) => {
  const L = store.local;
  L.seen = { ...(L.seen || {}), 564701: [...((L.seen || {})["564701"] || []), key] };
  L.ledger = { ...(L.ledger || {}), 564701: { ...((L.ledger || {})["564701"] || {}), [key]: { signal: "", at: 1, name: "Handout 2.docx", via: "remembered" } } };
};
/** A minimal shared Web Locks manager: exclusive per name, like navigator.locks across worker contexts. */
function fakeLocks() {
  const tails = new Map();
  return {
    request(name, cb) {
      const prev = tails.get(name) || Promise.resolve();
      const run = prev.then(() => cb({ name }));
      tails.set(name, run.catch(() => {}));
      return run;
    },
  };
}
const settle = async (n = 200) => { for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r)); };

test("finding 1: a Remember written while a run is uploading survives the run's save (probe2)", async () => {
  let w;
  let fired = false;
  w = world({ bs: pilRoutes(), maxPerRun: 1, local: READY, sync: PIL_ONLY, cf: () => {
    if (!fired) { fired = true; rememberBehindTheRunsBack(w.store, HANDOUT); }
    return { status: 200, body: { id: "f1", status: "indexed" } };
  } });
  await w.s.run();
  assert.ok(w.store.local.seen["564701"].includes(HANDOUT), "the Remember is still in seen");
  assert.ok(w.store.local.ledger["564701"][HANDOUT], "the Remember is still in the ledger");
  assert.ok(!w.store.local.pending["564701"].some((i) => i.key === HANDOUT), "and it is not offered again");
  const next = world({ bs: pilRoutes(), local: w.store.local, sync: PIL_ONLY });
  await next.s.run();
  assert.ok(!next.calls.cf.some((c) => c.name === "Handout 2.docx"), "the remembered file never goes up");
});

test("finding 1: a file remembered mid-run is not uploaded later in the same run", async () => {
  let w;
  let fired = false;
  w = world({ bs: pilRoutes(), local: READY, sync: PIL_ONLY, cf: () => {
    if (!fired) { fired = true; rememberBehindTheRunsBack(w.store, HANDOUT); }
    return { status: 200, body: { id: "f1", status: "indexed" } };
  } });
  await w.s.run();
  assert.equal(w.calls.cf.length, 3);
  assert.ok(!w.calls.cf.some((c) => c.name === "Handout 2.docx"));
});

test("finding 1: mutate() serializes read-modify-write so no writer's entry is lost", async () => {
  const w = world({ local: {}, sync: PIL_ONLY });
  assert.equal(typeof w.s.mutate, "function");
  await Promise.all(Array.from({ length: 10 }, (_, i) => w.s.mutate(async () => {
    const { seen } = await w.chrome.storage.local.get({ seen: {} });
    await new Promise((r) => setImmediate(r));
    seen.o = [...(seen.o || []), `k${i}`];
    await w.chrome.storage.local.set({ seen });
  })));
  assert.equal(w.store.local.seen.o.length, 10);
});

for (const [label, locks] of [["Web Locks", () => fakeLocks()], ["no Web Locks (lease re-check)", () => null]]) {
  test(`finding 2 (${label}): two runs at once upload each file once (probe P1)`, async () => {
    const w = world({ bs: pilRoutes(), local: READY, sync: PIL_ONLY, locks: locks() });
    const [a, b] = await Promise.all([w.s.run(), w.s.run()]);
    assert.equal(w.calls.cf.length, 4, "4 files, 4 uploads");
    assert.ok([a, b].some((r) => r.skipped === "already running"));
  });

  test(`finding 2 (${label}): two worker contexts over one storage never overlap`, async () => {
    const shared = fakeLocks();
    const a = world({ bs: pilRoutes(), local: READY, sync: PIL_ONLY, locks: locks() === null ? null : shared });
    const b = world({ bs: pilRoutes(), store: a.store, locks: locks() === null ? null : shared });
    const [ra, rb] = await Promise.all([a.s.run(), b.s.run()]);
    assert.equal(a.calls.cf.length + b.calls.cf.length, 4, "each file once across both contexts");
    assert.ok([ra, rb].some((r) => r.skipped === "already running"));
  });
}

test("finding 2: a live lease held by another run blocks; an expired one is taken over", async () => {
  const live = world({ bs: pilRoutes(), local: { ...READY, syncLock: { owner: "popup", expires: Date.parse("2026-11-10T12:05:00Z") } }, sync: PIL_ONLY });
  assert.deepEqual(await live.s.run(), { skipped: "already running" });
  assert.equal(live.calls.cf.length, 0);
  const dead = world({ bs: pilRoutes(), local: { ...READY, syncLock: { owner: "killed", expires: Date.parse("2026-11-10T11:00:00Z") } }, sync: PIL_ONLY });
  assert.equal((await dead.s.run()).uploaded, 4);
});

test("finding 2: a run never releases a lease it does not own", async () => {
  let w;
  w = world({ bs: pilRoutes(), local: READY, sync: PIL_ONLY, cf: (call) => {
    if (call.name === "Handout 2.docx") w.store.local.syncLock = { owner: "someone-else", expires: Date.parse("2027-01-01") };
    return { status: 200, body: { id: "f1" } };
  } });
  await w.s.run();
  assert.equal(w.store.local.syncLock && w.store.local.syncLock.owner, "someone-else", "the other run's lease is left alone");
});

test("finding 2: the lease is renewed while a run works, so a long run does not go stale", async () => {
  const seen = [];
  let w;
  w = world({ bs: pilRoutes(), local: READY, sync: PIL_ONLY, cf: () => { seen.push(w.store.local.syncLock && w.store.local.syncLock.expires); return { status: 200, body: { id: "f1" } }; } });
  await w.s.run();
  assert.equal(seen.length, 4);
  assert.ok(seen.every((e) => typeof e === "number"), "a lease with an expiry exists during the run");
  assert.ok(seen[3] > seen[0], "and its expiry moves forward per file");
  assert.ok(!w.store.local.syncLock || !w.store.local.syncLock.owner, "released at the end");
});

test("finding 3: a wrapper's links to another course or outside the content tree are never fetched or uploaded (probe3)", async () => {
  const evil = `<a href="/content/enforced/999999-OTHERCOURSE/exam-answers.pdf">x</a><a href="/content/enforced/x/..%2F..%2Fshared%2Fother.pdf">y</a>`;
  const w = world({ bs: pilRoutes({
    [enc(`${FOLDER}/Week 2/Lecture 2.html`)]: () => ({ type: "text/html", body: evil }),
    "/content/enforced/999999-OTHERCOURSE/exam-answers.pdf": () => ({ type: "application/pdf", body: pdf("other course") }),
    "/content/enforced/x/../../shared/other.pdf": () => ({ type: "application/pdf", body: pdf("outside tree") }),
  }), local: READY, sync: PIL_ONLY });
  await w.s.run();
  assert.deepEqual(w.calls.cf.map((c) => c.name), ["Lecture 1.pdf"]);
  assert.ok(!w.calls.bs.some((c) => /OTHERCOURSE|shared|%2F\.\.|\.\./i.test(c.path)), "never even fetched");
});

test("finding 3: the real PIL wrapper shape (embedded PDF in the same enforced folder) is uploaded", async () => {
  const name = "PIL Lecture 1 - 2026-2027-FINAL.pdf";
  const html = `<iframe src="${encodeURIComponent(name)}"></iframe><a href="${name}">download</a>`;
  const w = world({ bs: pilRoutes({
    [enc(`${FOLDER}/Week 2/Lecture 2.html`)]: () => ({ type: "text/html", body: html }),
    [enc(`${FOLDER}/Week 2/${name}`)]: () => ({ type: "application/pdf", body: pdf("pil 1") }),
  }), local: { ...READY, seen: { 564701: ["t:9001"] } }, sync: PIL_ONLY });
  await w.s.run();
  assert.deepEqual(w.calls.cf.map((c) => c.name), [name]);
});

test("finding 4: a worker killed after the POST does not re-send the same bytes on restart; it says 'check in CF'", async () => {
  const w = world({ bs: pilRoutes(), local: READY, sync: PIL_ONLY, cf: () => HANG });
  w.s.run();                                                     // never settles: the worker dies mid-request
  await settle();
  assert.equal(w.calls.cf.length, 1);
  const lost = w.calls.cf[0].name;
  const crashed = JSON.parse(JSON.stringify(w.store.local));
  // the browser restarts 11 minutes later (the dead run's lease has expired)
  const again = world({ bs: pilRoutes(), local: crashed, sync: PIL_ONLY, start: "2026-11-10T12:11:00Z" });
  await again.s.run();
  assert.ok(!again.calls.cf.some((c) => c.name === lost), `${lost} is not sent a second time`);
  assert.equal(again.calls.cf.length, 3, "the others still go up");
  assert.ok(again.store.local.log.some((l) => l.name === lost && l.action === "check in CF"), "surfaced in Recent activity");
  // a later run does not repeat the line
  const third = world({ bs: pilRoutes(), local: again.store.local, sync: PIL_ONLY, start: "2026-11-10T18:00:00Z" });
  await third.s.run();
  assert.equal(third.calls.cf.length, 0);
  assert.equal(third.store.local.log.filter((l) => l.action === "check in CF").length, 1);
});

test("finding 4: a pending upload older than 24h is retried", async () => {
  const w = world({ bs: pilRoutes(), local: READY, sync: PIL_ONLY, cf: () => HANG });
  w.s.run();
  await settle();
  const lost = w.calls.cf[0].name;
  const later = world({ bs: pilRoutes(), local: JSON.parse(JSON.stringify(w.store.local)), sync: PIL_ONLY, start: "2026-11-11T13:00:00Z" });
  await later.s.run();
  assert.ok(later.calls.cf.some((c) => c.name === lost));
  assert.ok(!later.store.local.ledger["564701"]["t:9001"].pending, "marked done after the 2xx");
});

test("finding 5: the key only goes to the origin it was made for, and only over https (or localhost)", async () => {
  const other = world({ bs: pilRoutes(), local: { ...READY, cfKeys: { pil: { ...KEYS.pil, origin: "https://other.example" } } }, sync: PIL_ONLY });
  await other.s.run();
  assert.equal(other.calls.cf.length, 0, "key bound to another origin is never sent");
  assert.equal(other.store.local.status["564701"].state, STATE.keyOrigin);
  assert.equal(badgeFor(other.store.local).text, "KEY");

  const legacy = world({ bs: pilRoutes(), local: { ...READY, cfKeys: { pil: { ...KEYS.pil, origin: undefined } } }, sync: PIL_ONLY });
  await legacy.s.run();
  assert.equal(legacy.calls.cf.length, 0, "a key with no recorded origin is never sent");

  const plain = world({ bs: pilRoutes(), local: { ...READY, cfKeys: { pil: { ...KEYS.pil, origin: "http://app.cognitioflow.ai" } } },
                        sync: { ...PIL_ONLY, appUrl: "http://app.cognitioflow.ai" } });
  plain.s.run && await plain.s.run().catch(() => {});
  assert.equal(plain.calls.cf.length, 0, "never over plain http to a real host");

  const t = world({ local: { cfKeys: { pil: { ...KEYS.pil, origin: "https://other.example" } } }, sync: CONF, cf: () => ({ status: 413, body: {} }) });
  const r = await t.s.testKey({ cid: "pil" });
  assert.equal(r.ok, false);
  assert.equal(t.calls.cf.length, 0, "Test sends nothing to a foreign origin");
});

test("finding 6: files left unticked on the first review stay pending and never auto-upload", async () => {
  const w = world({ bs: pilRoutes(), local: { cfKeys: KEYS, auto: { 564701: true } }, sync: PIL_ONLY });
  await w.s.run({ upload: false });
  assert.equal(w.store.local.pending["564701"].length, 4);
  await w.s.uploadKeys({ org: "564701", keys: ["t:9001"] });
  assert.equal(w.calls.cf.length, 1);
  assert.ok(!w.store.local.confirmed["564701"], "the review is not finished while files are undecided");
  assert.equal(w.store.local.pending["564701"].length, 3, "the unticked files are still waiting for a choice");
  await w.s.run();
  assert.equal(w.calls.cf.length, 1, "no automatic upload of files the user did not choose");
  // deciding the rest (Add) finishes the review
  await w.s.uploadKeys({ org: "564701", keys: w.store.local.pending["564701"].map((i) => i.key) });
  assert.equal(w.store.local.confirmed["564701"], true);
});

test("finding 1: a Remember that lands while the file is downloading stops its upload (marker is compare-and-set)", async () => {
  let w;
  const routes = pilRoutes();
  const p = enc(`${FOLDER}/Week 2/Handout 2.docx`);
  const orig = routes[p];
  routes[p] = (init) => { if ((init.method || "GET") === "GET") rememberBehindTheRunsBack(w.store, HANDOUT); return orig(init); };
  w = world({ bs: routes, local: READY, sync: PIL_ONLY });
  await w.s.run();
  assert.ok(!w.calls.cf.some((c) => c.name === "Handout 2.docx"), "the remembered file is not posted");
  assert.equal(w.store.local.ledger["564701"][HANDOUT].via, "remembered", "and the Remember stands");
});

test("finding 4: a popup Add killed mid-request is surfaced even with Auto off, and comes back after 24h", async () => {
  const start = { cfKeys: KEYS, confirmed: { 564701: true } };
  const w = world({ bs: pilRoutes(), local: start, sync: PIL_ONLY, cf: () => HANG });
  await w.s.run({ upload: false });
  w.s.uploadKeys({ org: "564701", keys: ["t:9001"] });          // never settles
  await settle();
  assert.equal(w.calls.cf.length, 1);
  const crashed = JSON.parse(JSON.stringify(w.store.local));
  const again = world({ bs: pilRoutes(), local: crashed, sync: PIL_ONLY, start: "2026-11-10T12:11:00Z" });
  await again.s.run();
  assert.equal(again.calls.cf.length, 0, "auto is off: nothing is sent");
  assert.ok(again.store.local.log.some((l) => l.name === "Lecture 1.pdf" && l.action === "check in CF"));
  assert.ok(!again.store.local.pending["564701"].some((i) => i.key === "t:9001"), "while held it is not offered twice");
  const later = world({ bs: pilRoutes(), local: again.store.local, sync: PIL_ONLY, start: "2026-11-11T13:00:00Z" });
  await later.s.run({ upload: false });
  assert.ok(later.store.local.pending["564701"].some((i) => i.key === "t:9001"), "after 24h it is back in the list");
  assert.ok(!later.store.local.ledger["564701"]["t:9001"], "and the stale marker is gone");
});

/* ------------------------------------------------------------------ red-team round 2 regressions */

test("red-team B1: a popup Add of a file a killed run already sent does not POST the same bytes again", async () => {
  const w = world({ bs: pilRoutes(), local: READY, sync: PIL_ONLY, cf: () => HANG });
  await w.s.run({ upload: false });                 // popup list of 4 on disk
  w.s.run();                                        // the worker dies while the first POST is in flight
  await settle();
  assert.equal(w.calls.cf.length, 1);
  const lost = w.calls.cf[0].name;
  const crashed = JSON.parse(JSON.stringify(w.store.local));
  const lostKey = Object.entries(crashed.ledger["564701"]).find(([, v]) => v.pending)[0];
  assert.ok(crashed.pending["564701"].some((i) => i.key === lostKey), "precondition: disk still lists the in-flight file");
  const again = world({ bs: pilRoutes(), local: crashed, sync: PIL_ONLY, start: "2026-11-10T12:11:00Z" });
  const r = await again.s.uploadKeys({ org: "564701", keys: [lostKey] });
  assert.equal(again.calls.cf.filter((c) => c.name === lost).length, 0, `${lost} is not sent a second time`);
  assert.equal(r.added, 0);
  assert.ok(again.store.local.log.some((l) => l.name === lost && l.action === "check in CF"), "surfaced as 'check in CF'");
  assert.ok(!again.store.local.pending["564701"].some((i) => i.key === lostKey), "and taken out of the popup list");
  assert.ok(again.store.local.ledger["564701"][lostKey].pending, "the marker stays until it is 24h old");
});

test("red-team B1b: popup opened under the dead lease, Add retried after it lapses: still no second POST", async () => {
  const w = world({ bs: pilRoutes(), local: READY, sync: PIL_ONLY, cf: () => HANG });
  w.s.run(); await settle();
  const crashed = JSON.parse(JSON.stringify(w.store.local));
  const lostKey = Object.entries(crashed.ledger["564701"]).find(([, v]) => v.pending)[0];
  const early = world({ bs: pilRoutes(), local: crashed, sync: PIL_ONLY, start: "2026-11-10T12:02:00Z" });
  assert.deepEqual(await early.s.run({ upload: false }), { skipped: "already running" });
  const late = world({ bs: pilRoutes(), local: early.store.local, sync: PIL_ONLY, start: "2026-11-10T12:12:00Z" });
  await late.s.uploadKeys({ org: "564701", keys: [lostKey] });
  assert.equal(late.calls.cf.length, 0, "not re-POSTed");
});

test("red-team B1: a popup Add of a file whose lost upload is over 24h old does go up (the marker is taken back)", async () => {
  const w = world({ bs: pilRoutes(), local: READY, sync: PIL_ONLY, cf: () => HANG });
  await w.s.run({ upload: false });
  w.s.run(); await settle();
  const crashed = JSON.parse(JSON.stringify(w.store.local));
  const lostKey = Object.entries(crashed.ledger["564701"]).find(([, v]) => v.pending)[0];
  const later = world({ bs: pilRoutes(), local: crashed, sync: PIL_ONLY, start: "2026-11-11T13:00:00Z" });
  const r = await later.s.uploadKeys({ org: "564701", keys: [lostKey] });
  assert.equal(r.added, 1);
  assert.equal(later.calls.cf.length, 1);
  assert.ok(!later.store.local.ledger["564701"][lostKey].pending, "marked done after the 2xx");
});

const FIRST = { cfKeys: KEYS, auto: { 564701: true } };
const WRAPPER_PATH = enc(`${FOLDER}/Week 2/Lecture 2.html`);

test("red-team B2: a page that failed to read blocks the first review; its files never auto-upload unreviewed", async () => {
  const flaky = pilRoutes({ [WRAPPER_PATH]: () => ({ status: 500, type: "text/plain", body: "busy" }) });
  const w = world({ bs: flaky, local: FIRST, sync: PIL_ONLY });
  await w.s.run({ upload: false });
  assert.deepEqual(w.store.local.pending["564701"].map((i) => i.key), ["t:9001"], "precondition: only Lecture 1 is visible");
  assert.equal(w.store.local.status["564701"].readErrors.length, 1, "the failed page is recorded as a read error");
  await w.s.uploadKeys({ org: "564701", keys: ["t:9001"] });   // every visible file decided
  assert.ok(!w.store.local.confirmed["564701"], "the review is not finished on an incomplete list");
  const next = world({ bs: pilRoutes(), local: w.store.local, sync: PIL_ONLY });
  const r = await next.s.run();
  assert.equal(r.uploaded, 0, "nothing goes up unreviewed");
  assert.equal(next.calls.cf.length, 0);
  assert.equal(next.store.local.pending["564701"].length, 3, "the three files are offered for review instead");
  assert.ok(!next.store.local.status["564701"].readErrors, "a clean read clears the error");
});

test("red-team B2: a module description that failed to read is recorded and blocks the review until a clean re-check", async () => {
  const flaky = pilRoutes({ "/d2l/api/le/1.97/564701/content/modules/102": () => ({ status: 500, type: "text/plain", body: "busy" }) });
  const w = world({ bs: flaky, local: FIRST, sync: PIL_ONLY });
  await w.s.run({ upload: false });
  assert.equal(w.store.local.status["564701"].readErrors.length, 1, "module read errors are no longer swallowed");
  await w.s.uploadKeys({ org: "564701", keys: w.store.local.pending["564701"].map((i) => i.key) });
  assert.ok(!w.store.local.confirmed["564701"], "not finished while a module could not be read");
  // a clean re-check that finds nothing new finishes the review (no dead end)
  const clean = world({ bs: pilRoutes(), local: w.store.local, sync: PIL_ONLY });
  await clean.s.run({ upload: false });
  assert.equal(clean.store.local.pending["564701"].length, 0);
  assert.equal(clean.store.local.confirmed["564701"], true);
});

test("red-team B2: read errors survive a later scan that fails (sign-in), so the stale list cannot finish the review", async () => {
  const flaky = pilRoutes({ [WRAPPER_PATH]: () => ({ status: 500, type: "text/plain", body: "busy" }) });
  const w = world({ bs: flaky, local: FIRST, sync: PIL_ONLY });
  await w.s.run({ upload: false });
  const out = world({ bs: { "/d2l/api/le/1.97/564701/content/toc": () => ({ status: 401, body: "" }) }, local: w.store.local, sync: PIL_ONLY });
  await out.s.run({ upload: false });
  assert.equal(out.store.local.status["564701"].state, STATE.login);
  assert.equal(out.store.local.status["564701"].readErrors.length, 1, "kept with the list it belongs to");
  await out.s.uploadKeys({ org: "564701", keys: ["t:9001"] });
  assert.ok(!out.store.local.confirmed["564701"]);
});

test("red-team B2: a page that reads fine but has no file link does not block the review", async () => {
  const bare = pilRoutes({ [WRAPPER_PATH]: () => ({ type: "text/html", body: "<p>Read chapter 3.</p>" }) });
  const w = world({ bs: bare, local: FIRST, sync: PIL_ONLY });
  await w.s.run({ upload: false });
  assert.equal(w.store.local.status["564701"].emptyPages.length, 1);
  await w.s.uploadKeys({ org: "564701", keys: ["t:9001"] });
  assert.equal(w.store.local.confirmed["564701"], true);
});

test("red-team B3: a TOC page Url that is not a path in this course is never fetched", async () => {
  const toc = { Modules: [{ ModuleId: 101, Title: "Week 1", Modules: [], Topics: [
    { TopicId: 1, Title: "x", TypeIdentifier: "File", Url: ".evil.example/x.html" },
    { TopicId: 2, Title: "y", TypeIdentifier: "File", Url: "/content/enforced/999999-OTHER/secret.html" },
    { TopicId: 3, Title: "z", TypeIdentifier: "File", Url: "/content/enforced/564701-Z/ok.html" }] }] };
  const w = world({ bs: { "/d2l/api/le/1.97/564701/content/toc": () => ({ body: toc }),
    "/d2l/api/le/1.97/564701/content/modules/101": () => ({ body: {} }),
    [enc("/content/enforced/999999-OTHER/secret.html")]: () => ({ type: "text/html", body: '<a href="/content/enforced/564701-Z/b.pdf">b</a>' }),
    [enc("/content/enforced/564701-Z/ok.html")]: () => ({ type: "text/html", body: "<p>nothing</p>" }) }, local: READY, sync: PIL_ONLY });
  await w.s.run();
  assert.ok(w.calls.bs.every((c) => c.path.startsWith("/")), `every Brightspace read is a path: ${w.calls.bs.map((c) => c.path)}`);
  assert.ok(!w.calls.bs.some((c) => c.path.includes("999999-OTHER")), "another course's page is not read with the session");
  assert.ok(w.calls.bs.some((c) => c.path === enc("/content/enforced/564701-Z/ok.html")), "this course's page still is");
});

test("red-team B3: the reader refuses anything that would leave brightspace.rug.nl", async () => {
  const hosts = [];
  const s = createSync({ chrome: world().chrome, sleep: async () => {}, fetch: async (url) => { hosts.push(String(url)); throw new Error("no"); } });
  const rd = s.reader();
  for (const bad of [".evil.example/x.html", "@evil.example/x.html", ":8080/x.html", "x.html", ""]) {
    await assert.rejects(rd.page(bad));
  }
  assert.deepEqual(hosts, [], "no request left the extension");
});

test("red-team B5: Auto switched off mid-run stops the course before its next upload", async () => {
  let w; let n = 0;
  w = world({ bs: pilRoutes(), local: READY, sync: PIL_ONLY, cf: () => {
    if (++n === 1) w.store.local.auto = { 564701: false };   // what setAuto writes
    return { status: 200, body: { id: "f" + n } };
  } });
  const r = await w.s.run();
  assert.equal(w.calls.cf.length, 1, "nothing more goes up once Auto is off");
  assert.equal(r.uploaded, 1);
  assert.equal(w.store.local.status["564701"].state, STATE.autoOff);
  assert.equal(w.store.local.auto["564701"], false, "the run does not write Auto back");
});

test("red-team B5: a key removed mid-run is not used for the rest of the run, nor written back", async () => {
  let w; let n = 0;
  w = world({ bs: pilRoutes(), local: READY, sync: PIL_ONLY, cf: () => {
    if (++n === 1) w.store.local.cfKeys = {};                // Options removed / revoked the key
    return { status: 200, body: { id: "f" + n } };
  } });
  await w.s.run();
  assert.equal(w.calls.cf.length, 1);
  assert.equal(w.store.local.status["564701"].state, STATE.keyMissing);
  assert.deepEqual(w.store.local.cfKeys, {}, "the removed key is not resurrected");
});

test("red-team B5: a key removed during a popup Add stops the Add", async () => {
  let w; let n = 0;
  w = world({ bs: pilRoutes(), local: { cfKeys: KEYS, confirmed: { 564701: true } }, sync: PIL_ONLY, cf: () => {
    if (++n === 1) w.store.local.cfKeys = {};
    return { status: 200, body: { id: "f" + n } };
  } });
  await w.s.run({ upload: false });
  const r = await w.s.uploadKeys({ org: "564701", keys: w.store.local.pending["564701"].map((i) => i.key) });
  assert.equal(w.calls.cf.length, 1);
  assert.equal(r.added, 1);
  assert.ok(r.failed.length >= 1, "the rest is reported, not sent");
});

/* The change lands while the NEXT file downloads, after the pre-download check: only the check made under
   the state lock, as the in-flight marker is placed, can stop the POST. */
const duringDownloadOf = (routes, path, fn) => {
  const orig = routes[path];
  routes[path] = (init) => { if ((init.method || "GET") === "GET") fn(); return orig(init); };
  return routes;
};
const HANDOUT_PATH = enc(`${FOLDER}/Week 2/Handout 2.docx`);
const LECTURE1_PATH = "/d2l/le/content/564701/topics/files/download/9001/DirectFileTopicDownload";

test("red-team B5: Auto switched off while a file downloads stops its POST (checked under the lock)", async () => {
  let w;
  const routes = duringDownloadOf(pilRoutes(), LECTURE1_PATH, () => { w.store.local.auto = { 564701: false }; });
  w = world({ bs: routes, local: READY, sync: PIL_ONLY });
  await w.s.run();
  assert.equal(w.calls.cf.length, 0, "nothing is posted once Auto is off");
  assert.equal(w.store.local.status["564701"].state, STATE.autoOff);
  assert.ok(!(w.store.local.ledger["564701"] || {})["t:9001"], "no in-flight marker is left behind");
});

test("red-team B5: a key removed while a file downloads is never sent (checked under the lock)", async () => {
  let w;
  const routes = duringDownloadOf(pilRoutes(), LECTURE1_PATH, () => { w.store.local.cfKeys = {}; });
  w = world({ bs: routes, local: READY, sync: PIL_ONLY });
  await w.s.run();
  assert.equal(w.calls.cf.length, 0);
  assert.equal(w.store.local.status["564701"].state, STATE.keyMissing);
});

test("red-team B5: a key removed while a popup Add downloads is never sent (checked under the lock)", async () => {
  let w;
  const routes = duringDownloadOf(pilRoutes(), HANDOUT_PATH, () => { w.store.local.cfKeys = {}; });
  w = world({ bs: routes, local: { cfKeys: KEYS, confirmed: { 564701: true } }, sync: PIL_ONLY });
  await w.s.run({ upload: false });
  const r = await w.s.uploadKeys({ org: "564701", keys: [HANDOUT] });
  assert.equal(w.calls.cf.length, 0);
  assert.equal(r.added, 0);
  assert.equal(r.failed.length, 1);
});

/* ------------------------------------------------------------------ round 3: a shrinking first list */

/** What background.js record() does for "I already have these": one write under the state lock, with
    `status` loaded so finishReview can see the scan's read errors. */
async function rememberLikeThePopup(w, org, keys) {
  await w.s.mutate(async () => {
    const cur = await w.chrome.storage.local.get({ seen: {}, pending: {}, confirmed: {}, ledger: {}, status: {} });
    const book = (cur.ledger[org] = cur.ledger[org] || {});
    for (const k of keys) book[k] = { signal: "", at: 1, name: k, via: "remembered" };
    cur.seen[org] = [...new Set([...(cur.seen[org] || []), ...keys])];
    cur.pending[org] = (cur.pending[org] || []).filter((i) => !keys.includes(i.key));
    w.s.finishReview(cur, org);
    await w.chrome.storage.local.set({ seen: cur.seen, pending: cur.pending, confirmed: cur.confirmed, ledger: cur.ledger });
  });
}
const LINKLESS = { [WRAPPER_PATH]: () => ({ type: "text/html", body: "<p>Slides move to next week</p>" }) };
const tocWithoutPages = () => {
  const toc = JSON.parse(JSON.stringify(TOC));
  for (const m of toc.Modules) m.Topics = (m.Topics || []).filter((t) => !/\.html$/i.test(t.Url || ""));
  return toc;
};
const WRAPPED = [`f:${FOLDER}/Week 2/Lecture 2 slides.pdf`, `f:${FOLDER}/Readings/Reading week 2.pdf`, HANDOUT];

test("red-team round 3 A1: a wrapper page that briefly has no links does not finish a first review with undecided files", async () => {
  const w1 = world({ bs: pilRoutes(), local: FIRST, sync: PIL_ONLY });
  await w1.s.run({ upload: false });
  assert.equal(w1.store.local.pending["564701"].length, 4);
  await rememberLikeThePopup(w1, "564701", ["t:9001"]);   // one decided, three left undecided
  const w2 = world({ bs: pilRoutes(LINKLESS), local: w1.store.local, sync: PIL_ONLY });
  await w2.s.run({ upload: false });                        // list refresh while the page is being edited
  assert.ok(!w2.store.local.confirmed["564701"], "the review is not finished");
  assert.deepEqual(w2.store.local.pending["564701"].map((i) => i.key).sort(), [...WRAPPED].sort(), "the undecided files stay in the list");
  assert.ok(w2.store.local.pending["564701"].every((i) => i.missing), "flagged as not on Brightspace right now");
  const w3 = world({ bs: pilRoutes(), local: w2.store.local, sync: PIL_ONLY });
  const r = await w3.s.run();                               // the page is back
  assert.equal(r.uploaded, 0, "nothing the user never decided goes up");
  assert.equal(w3.calls.cf.length, 0);
  assert.deepEqual(w3.store.local.pending["564701"].map((i) => i.key).sort(), [...WRAPPED].sort());
  assert.ok(w3.store.local.pending["564701"].every((i) => !i.missing), "a file that is back is listed as itself again");
});

test("red-team round 3 A2: an HTML topic briefly missing from the TOC does not finish a first review", async () => {
  const w1 = world({ bs: pilRoutes(), local: FIRST, sync: PIL_ONLY });
  await w1.s.run({ upload: false });
  await rememberLikeThePopup(w1, "564701", ["t:9001"]);
  const w2 = world({ bs: pilRoutes({ "/d2l/api/le/1.97/564701/content/toc": () => ({ body: tocWithoutPages() }) }), local: w1.store.local, sync: PIL_ONLY });
  await w2.s.run({ upload: false });
  assert.ok(!w2.store.local.confirmed["564701"]);
  const w3 = world({ bs: pilRoutes(), local: w2.store.local, sync: PIL_ONLY });
  const r = await w3.s.run();
  assert.equal(r.uploaded, 0);
  assert.equal(w3.calls.cf.length, 0);
});

test("red-team round 3: deciding only what a shrunken list shows does not finish the review either", async () => {
  const w1 = world({ bs: pilRoutes(), local: FIRST, sync: PIL_ONLY });
  await w1.s.run({ upload: false });                        // the popup showed all four
  const w2 = world({ bs: pilRoutes(LINKLESS), local: w1.store.local, sync: PIL_ONLY });
  await w2.s.run({ upload: false });
  await rememberLikeThePopup(w2, "564701", ["t:9001"]);     // the user decides the one file still on Brightspace
  assert.ok(!w2.store.local.confirmed["564701"], "three shown files are still undecided");
  const w3 = world({ bs: pilRoutes(), local: w2.store.local, sync: PIL_ONLY });
  assert.equal((await w3.s.run()).uploaded, 0);
});

test("red-team round 3: a page that failed, then came back with no links, does not finish the review", async () => {
  const w1 = world({ bs: pilRoutes(), local: FIRST, sync: PIL_ONLY });
  await w1.s.run({ upload: false });
  await rememberLikeThePopup(w1, "564701", ["t:9001"]);
  const w2 = world({ bs: pilRoutes({ [WRAPPER_PATH]: () => ({ status: 500, type: "text/plain", body: "busy" }) }), local: w1.store.local, sync: PIL_ONLY });
  await w2.s.run({ upload: false });
  const w3 = world({ bs: pilRoutes(LINKLESS), local: w2.store.local, sync: PIL_ONLY });
  await w3.s.run({ upload: false });
  assert.ok(!w3.store.local.confirmed["564701"]);
  const w4 = world({ bs: pilRoutes(), local: w3.store.local, sync: PIL_ONLY });
  assert.equal((await w4.s.run()).uploaded, 0);
});

test("red-team round 3: a file gone from Brightspace can still be decided, and then the review finishes", async () => {
  const w1 = world({ bs: pilRoutes(), local: FIRST, sync: PIL_ONLY });
  await w1.s.run({ upload: false });
  await rememberLikeThePopup(w1, "564701", ["t:9001"]);
  const w2 = world({ bs: pilRoutes(LINKLESS), local: w1.store.local, sync: PIL_ONLY });
  await w2.s.run({ upload: false });
  await rememberLikeThePopup(w2, "564701", WRAPPED);       // "I already have these" on the files that went away
  assert.equal(w2.store.local.confirmed["564701"], true, "every shown file has a choice: finished");
  const w3 = world({ bs: pilRoutes(), local: w2.store.local, sync: PIL_ONLY });
  assert.equal((await w3.s.run()).uploaded, 0, "remembered files are not uploaded when they come back");
});

test("red-team round 3: once reviewed, a file that leaves Brightspace simply drops out of the list", async () => {
  const w1 = world({ bs: pilRoutes(), local: READY, sync: PIL_ONLY });
  await w1.s.run({ upload: false });
  assert.equal(w1.store.local.pending["564701"].length, 4);
  const w2 = world({ bs: pilRoutes(LINKLESS), local: w1.store.local, sync: PIL_ONLY });
  await w2.s.run({ upload: false });
  assert.deepEqual(w2.store.local.pending["564701"].map((i) => i.key), ["t:9001"]);
});
