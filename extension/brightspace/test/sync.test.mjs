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
function world({ bs = {}, cf = () => ({ status: 200, body: { id: "f1", status: "indexed" } }), local = {}, sync = {}, tabs = [], maxPerRun = 20 } = {}) {
  const store = { local: JSON.parse(JSON.stringify(local)), sync: JSON.parse(JSON.stringify(sync)) };
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
      return response({ url, ...cf(call) });
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
  let clock = Date.parse("2026-11-10T12:00:00Z");
  const s = createSync({ chrome, fetch, sleep: async () => {}, now: () => (clock += 1000), maxPerRun });
  return { s, store, calls, chrome };
}

const COURSES = [{ org: "564701", name: "PIL", cid: "pil" }, { org: "564708", name: "LaPoPo", cid: "lapopo" }];
const FAR = Date.parse("2027-01-31T00:00:00Z");
const KEYS = {
  pil: { token: "cfw_PIL_secret", courseId: "pil", expires: FAR, id: "k1" },
  lapopo: { token: "cfw_LAPOPO_secret", courseId: "lapopo", expires: FAR, id: "k2" },
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
    cf: (call) => { snapshots.push(Object.keys((w.store.local.ledger || {})["564701"] || {}).length); return { status: 200, body: { id: call.name } }; } });
  await w.s.run();
  // before the k-th upload, k-1 uploads (plus any adoptions) are already persisted
  assert.deepEqual(snapshots, [0, 1, 2, 3]);
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

