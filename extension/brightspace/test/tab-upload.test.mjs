/* The keyless tab Add end to end: background.js take() builds the upload message, the REAL content-app.js
   (run in a sandbox, as Chrome injects it) receives it and POSTs the file. No network is touched. */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const APP = "https://app.example";
const memory = {
  local: { pending: { org: [{ key: "t:2", name: "b.pdf", url: "/x/b.pdf", week: "2" }] } },
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
      if (id === BS_TAB.id && msg.type === "file") return { ok: true, data: { base64: "JVBERi0xLjcK", type: "application/pdf" } };
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
