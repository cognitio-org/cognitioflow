/* The keyless tab Add end to end: background.js take() builds the upload message, the REAL content-app.js
   (run in a sandbox, as Chrome injects it) receives it and POSTs the file. No network is touched. */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const APP = "https://app.example";
const LOGIN_PAGE = Buffer.from('<!DOCTYPE html><html><head><title>Login - Brightspace</title></head><body><form>Username</form></body></html>').toString("base64");
const PDF = Buffer.from("%PDF-1.7\nslides\n%%EOF").toString("base64");
const SLIDES = "/content/enforced/1-X/Week 2/slides.pdf";
const memory = {
  local: { pending: { org: [
    { key: "t:2", name: "b.pdf", url: "/x/b.pdf", week: "2" },
    { key: "t:3", name: "expired.pdf", url: "/x/expired.pdf", week: "3" },   // the session expired: Brightspace answers its login page
    { key: "t:4", name: "after.pdf", url: "/x/after.pdf", week: "3" },
    { key: `f:${SLIDES}`, name: "slides.pdf", url: "/x/slides-link.pdf", path: SLIDES, week: "2", missing: true },   // one file, listed as a link
    { key: "t:5", name: "slides.pdf", url: "/x/slides-topic.pdf", path: SLIDES, week: "2" },                       // ...and as a topic
  ] } },
  sync: { appUrl: APP, courses: [{ org: "org", cid: "c1", name: "C" }] },
};
const workerListeners = [];

/* content-app.js in its own context, with its own chrome.runtime and a recording fetch */
const appListeners = [];
const posts = [];
const sandbox = {
  window: {}, atob, Blob, FormData, Uint8Array, Promise, String, JSON, encodeURIComponent,
  chrome: { runtime: { onMessage: { addListener: (fn) => appListeners.push(fn) } } },
  fetch: async (url, init = {}) => {
    const file = init.body && init.body.get ? init.body.get("file") : null;
    posts.push({ url, method: init.method, name: file && file.name, type: file && file.type, week: init.body && init.body.get && init.body.get("week") });
    return { ok: true, status: 200, json: async () => ({ id: "f1" }) };
  },
};
vm.createContext(sandbox);
vm.runInContext(readFileSync(new URL("../content-app.js", import.meta.url), "utf8"), sandbox);
const toApp = (msg) => new Promise((resolve) => {
  const handled = appListeners.some((fn) => fn(msg, {}, resolve) === true);
  if (!handled) resolve({ ok: false, error: `content-app has no handler for type "${msg.type}"` });
});

const BS_TAB = { id: 7, url: "https://brightspace.rug.nl/d2l/home" };
const APP_TAB = { id: 8, url: `${APP}/` };
globalThis.chrome = {
  storage: {
    local: { get: async (d = {}) => ({ ...d, ...JSON.parse(JSON.stringify(memory.local)) }), set: async (v) => Object.assign(memory.local, JSON.parse(JSON.stringify(v))) },
    sync: { get: async (d = {}) => ({ ...d, ...JSON.parse(JSON.stringify(memory.sync)) }), set: async (v) => Object.assign(memory.sync, v) },
  },
  tabs: {
    query: async ({ url }) => (url.startsWith("https://brightspace.rug.nl") ? [BS_TAB] : url.startsWith(APP) ? [APP_TAB] : []),
    sendMessage: async (id, msg) => {
      if (id === BS_TAB.id && msg.type === "file") {
        if (msg.url === "/x/expired.pdf") return { ok: true, data: { base64: LOGIN_PAGE, type: "text/html; charset=utf-8" } };
        return { ok: true, data: { base64: PDF, type: "application/pdf" } };
      }
      if (id === APP_TAB.id) return toApp(msg);
      return { ok: false, error: "unexpected message" };
    },
    onUpdated: { addListener: () => {}, removeListener: () => {} },
  },
  scripting: { executeScript: async () => {} },
  action: { setBadgeText: async () => {}, setBadgeBackgroundColor: async () => {} },
  alarms: { create: async () => {}, clear: async () => true, onAlarm: { addListener: () => {} } },
  notifications: { create: async () => {} },
  runtime: { onMessage: { addListener: (fn) => workerListeners.push(fn) }, onInstalled: { addListener: () => {} }, onStartup: { addListener: () => {} } },
  permissions: { contains: async () => true },
};
globalThis.fetch = async (url) => { throw new Error(`the worker touched the network: ${url}`); };
await import("../background.js");
const toWorker = (msg) => new Promise((resolve) => workerListeners[workerListeners.length - 1](msg, {}, resolve));

test("keyless tab Add: take() -> content-app.js upload handler -> one POST with the file's MIME type", async () => {
  const r = await toWorker({ type: "take", org: "org", keys: ["t:2"] });
  assert.equal(r.ok, true, r.error);
  assert.deepEqual(r.data.failed, [], `nothing failed: ${JSON.stringify(r.data.failed)}`);
  assert.equal(r.data.added, 1);
  assert.equal(posts.length, 1, "content-app.js uploaded the file");
  assert.equal(posts[0].url, "/api/courses/c1/files");
  assert.equal(posts[0].method, "POST");
  assert.equal(posts[0].name, "b.pdf");
  assert.equal(posts[0].type, "application/pdf", "the Blob keeps the MIME type");
  assert.equal(posts[0].week, "2");
  assert.ok((memory.local.seen.org || []).includes("t:2"), "recorded as handled");
});

const pendingKeys = () => (memory.local.pending.org || []).map((i) => i.key);
const handled = (k) => (memory.local.seen.org || []).includes(k) || !!((memory.local.ledger.org || {})[k]);

test("red-team K1: keyless Add given a 200 text/html login page uploads nothing, marks nothing, and stops", async () => {
  const before = posts.length;
  const r = await toWorker({ type: "take", org: "org", keys: ["t:3", "t:4"] });
  assert.equal(r.ok, true, r.error);
  assert.equal(r.data.added, 0);
  assert.deepEqual(r.data.failed, [{ name: "expired.pdf", error: "login needed" }], "same answer as the keyed Add");
  assert.equal(posts.length, before, "nothing was POSTed to CognitioFlow");
  for (const k of ["t:3", "t:4"]) {
    assert.ok(!handled(k), `${k} is not recorded as handled`);
    assert.ok(pendingKeys().includes(k), `${k} is still waiting in the list`);
  }
});

test("red-team K2: one file listed under a topic key and a link key goes up once in a keyless Add-all", async () => {
  const before = posts.length;
  const r = await toWorker({ type: "take", org: "org", keys: [`f:${SLIDES}`, "t:5"] });
  assert.equal(r.ok, true, r.error);
  assert.deepEqual(r.data.failed, []);
  assert.equal(posts.length - before, 1, "one POST for one file");
  assert.equal(r.data.added, 1);
  for (const k of [`f:${SLIDES}`, "t:5"]) {
    assert.ok(handled(k), `${k} is recorded as handled`);
    assert.ok(!pendingKeys().includes(k), `${k} left the list`);
  }
});
