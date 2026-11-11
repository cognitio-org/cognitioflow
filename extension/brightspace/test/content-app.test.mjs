/* content-app.js is injected again on every ask. A copy left behind by an older (reloaded) extension used to
   leave `window.__cfGrabber = true`, so the new copy registered nothing and "Create sync key" hung forever.
   The REAL file runs here in a vm context, as Chrome injects it, against a fake chrome.runtime. */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const SOURCE = readFileSync(new URL("../content-app.js", import.meta.url), "utf8");

function page({ window = {} } = {}) {
  const live = new Set();
  const fetched = [];
  const sandbox = {
    window, atob, Blob, FormData, Uint8Array, Promise, String, JSON, Math, Number, encodeURIComponent,
    chrome: { runtime: {
      id: "ext", getManifest: () => ({ version: "0.2.0" }),
      onMessage: { addListener: (fn) => live.add(fn), removeListener: (fn) => live.delete(fn) },
    } },
    fetch: async (url, init = {}) => {
      fetched.push({ url, method: init.method || "GET" });
      return { ok: true, status: 200, json: async () => [{ id: "eu", name: "EU Law" }] };
    },
  };
  vm.createContext(sandbox);
  const inject = () => vm.runInContext(SOURCE, sandbox);
  /** Delivers a message as Chrome does: to every live listener; the first reply wins. */
  const send = (msg) => new Promise((resolve) => {
    let replied = 0;
    const kept = [...live].map((fn) => fn(msg, {}, (r) => { replied++; resolve({ ...r, replied }); }));
    if (!kept.includes(true)) resolve({ handled: false });
  });
  return { live, fetched, inject, send, sandbox };
}

test("a flag left by an older extension's copy no longer blocks the new listener", async () => {
  const p = page({ window: { __cfGrabber: true } });   // what a pre-fix copy leaves behind
  p.inject();
  assert.equal(p.live.size, 1);
  const r = await p.send({ type: "courses" });
  assert.equal(r.ok, true);
  assert.deepEqual(r.data, [{ id: "eu", name: "EU Law" }]);
  assert.equal(p.sandbox.window.__cfGrabber.runtimeId, "ext");
  assert.equal(p.sandbox.window.__cfGrabber.version, "0.2.0");
});

test("injecting twice keeps exactly one live listener, so a request runs once", async () => {
  const p = page();
  p.inject();
  const first = p.sandbox.window.__cfGrabber.listener;
  p.inject();   // a second classic-script run in the same world must not throw on redeclared consts
  assert.equal(p.live.size, 1);
  assert.notEqual(p.sandbox.window.__cfGrabber.listener, first);
  assert.ok(p.live.has(p.sandbox.window.__cfGrabber.listener));
  await p.send({ type: "courses" });
  assert.equal(p.fetched.length, 1);
});

test("a previous listener that cannot be removed (dead context) does not stop registration", () => {
  const p = page({ window: { __cfGrabber: { listener: () => false } } });
  p.sandbox.chrome.runtime.onMessage.removeListener = () => { throw new Error("Extension context invalidated."); };
  p.inject();
  assert.equal(p.live.size, 1);
});

test("an unknown message type is left for other listeners", async () => {
  const p = page();
  p.inject();
  assert.deepEqual(await p.send({ type: "nope" }), { handled: false });
});
