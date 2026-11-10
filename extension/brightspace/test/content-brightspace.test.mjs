/* The REAL content-brightspace.js (run in a sandbox, as Chrome injects it) answering `file` for an expired
   session, and sync.js's tab-mode reader turning that answer into a sign-in stop. No network is touched. */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { createSync, BS_ORIGIN } from "../sync.js";

const LOGIN_HTML = "<!DOCTYPE html><html><head><title>Login - Brightspace</title></head><body><form>Username</form></body></html>";
const PDF = "%PDF-1.7\nslides\n%%EOF";

/** Brightspace answers, by requested url: what fetch() would hand back after following redirects. */
const answers = {
  "/x/expired.pdf": { redirected: true, url: `${BS_ORIGIN}/d2l/login?sessionExpired=1`, type: "text/html; charset=utf-8", body: LOGIN_HTML },
  "/x/sso.pdf": { redirected: true, url: "https://idp.example.org/saml/login", type: "text/html", body: LOGIN_HTML },
  "/x/slides.pdf": { redirected: false, url: `${BS_ORIGIN}/x/slides.pdf`, type: "application/pdf", body: PDF },
  "/x/moved.pdf": { redirected: true, url: `${BS_ORIGIN}/content/enforced/1-X/moved.pdf`, type: "application/pdf", body: PDF },
  "/x/no-url.pdf": { type: "application/pdf", body: PDF },   // a fetch stub with no url / redirected fields
};
const listeners = [];
const box = {
  atob, btoa, Uint8Array, String, Promise, JSON, encodeURIComponent, Error, URL,
  location: { pathname: "/d2l/home" },
  chrome: { runtime: { onMessage: { addListener: (fn) => listeners.push(fn) }, sendMessage: async () => {} } },
  fetch: async (url) => {
    const a = answers[url];
    if (!a) return { ok: false, status: 404, headers: { get: () => null }, arrayBuffer: async () => new ArrayBuffer(0) };
    const body = new TextEncoder().encode(a.body);
    return { ok: true, status: 200, redirected: a.redirected, url: a.url,
      headers: { get: (n) => (n.toLowerCase() === "content-type" ? a.type : null) }, arrayBuffer: async () => body.slice().buffer };
  },
};
vm.createContext(box);
vm.runInContext(readFileSync(new URL("../content-brightspace.js", import.meta.url), "utf8"), box);
const ask = (msg) => new Promise((resolve) => {
  if (!listeners.some((fn) => fn(msg, {}, resolve) === true)) resolve(undefined);
});

test("red-team K1: a file request bounced to the Brightspace login page is refused, not handed over as the file", async () => {
  const r = await ask({ type: "file", url: "/x/expired.pdf" });
  assert.equal(r.ok, false, "no bytes come back");
  assert.match(r.error, /sign-in needed/i);
});

test("red-team K1: a file request bounced to another host (the SSO) is refused", async () => {
  const r = await ask({ type: "file", url: "/x/sso.pdf" });
  assert.equal(r.ok, false);
  assert.match(r.error, /sign-in needed/i);
});

test("a real file, or one redirected inside Brightspace, still comes back", async () => {
  for (const url of ["/x/slides.pdf", "/x/moved.pdf", "/x/no-url.pdf"]) {
    const r = await ask({ type: "file", url });
    assert.equal(r.ok, true, `${url}: ${r.error}`);
    assert.equal(Buffer.from(r.data.base64, "base64").toString(), PDF);
    assert.equal(r.data.type, "application/pdf");
  }
});

test("red-team K1: sync's tab-mode reader treats that refusal as a sign-in stop, not a per-file failure", async () => {
  const chrome = {
    storage: { local: { get: async (d = {}) => d, set: async () => {} }, sync: { get: async (d = {}) => d, set: async () => {} } },
    tabs: { query: async () => [{ id: 7 }], sendMessage: async (_id, msg) => ask(msg) },
    permissions: { contains: async () => true },
  };
  // the worker's own request is signed out (401), so the reader falls back to the open Brightspace tab
  const fetch = async (url) => ({ ok: false, status: 401, url: String(url), type: "basic", headers: { get: () => null } });
  const rd = createSync({ chrome, fetch, sleep: async () => {} }).reader();
  await assert.rejects(rd.file("/x/expired.pdf"), (e) => e.login === true);
  assert.equal(rd.mode, "tab");
  const ok = await rd.file("/x/slides.pdf");
  assert.equal(new TextDecoder().decode(ok.bytes), PDF);
});
