import assert from "node:assert/strict";
import test from "node:test";

const memory = { local: {}, sync: {} };
const runtimeListeners = [];
const updatedListeners = new Set();
const timers = [];
let tabId = 1;
let queryImpl = async () => [];
let createImpl = async () => ({ id: tabId++, url: "https://app.example/", active: false });
let sendMessageImpl = async () => ({ ok: true, data: [] });

const onUpdated = {
  addListener: (fn) => { updatedListeners.add(fn); },
  removeListener: (fn) => { updatedListeners.delete(fn); },
};

const fakeChrome = {
  storage: {
    local: {
      get: async (defaults = {}) => ({ ...defaults, ...memory.local }),
      set: async (values) => Object.assign(memory.local, values),
    },
    sync: {
      get: async (defaults = {}) => ({ ...defaults, ...memory.sync }),
      set: async (values) => Object.assign(memory.sync, values),
    },
  },
  tabs: {
    query: async () => queryImpl(),
    create: async () => createImpl(),
    sendMessage: async () => sendMessageImpl(),
    onUpdated,
  },
  scripting: { executeScript: async () => {} },
  action: {
    setBadgeText: async () => {},
    setBadgeBackgroundColor: async () => {},
  },
  alarms: {
    create: async () => {},
    onAlarm: { addListener: () => {} },
  },
  notifications: { create: async () => {} },
  runtime: {
    onMessage: { addListener: (fn) => { runtimeListeners.push(fn); } },
    onInstalled: { addListener: () => {} },
  },
};

const originalChrome = globalThis.chrome;
globalThis.chrome = fakeChrome;
const { appTab } = await import("../background.js");

test.after(() => {
  if (originalChrome === undefined) delete globalThis.chrome;
  else globalThis.chrome = originalChrome;
});

function resetState() {
  memory.local = {};
  memory.sync = {};
  tabId = 1;
  queryImpl = async () => [];
  createImpl = async () => ({ id: tabId++, url: "https://app.example/", active: false });
  sendMessageImpl = async () => ({ ok: true, data: [] });
  updatedListeners.clear();
}

function send(type) {
  return new Promise((resolve, reject) => {
    const listener = runtimeListeners[runtimeListeners.length - 1];
    let replied = false;
    const reply = (data) => {
      if (replied) return;
      replied = true;
      resolve(data);
    };
    try {
      listener({ type }, {}, reply);
    } catch (e) {
      reject(e);
    }
  });
}

const originalSetTimeout = globalThis.setTimeout;
const originalClearTimeout = globalThis.clearTimeout;

async function flushMicrotasks() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

/** Yield until `cond()` holds, or give up after `ticks` microtasks.
 *
 * Three fixed ticks were not enough: appTab awaits tabs.query and then tabs.create before it
 * registers the listener and the timer, so the assertions ran while that was still in flight.
 * The test then failed AND kept resolving afterwards, which node reports as "asynchronous
 * activity after the test ended" rather than as the assertion that actually broke. Waiting on
 * the condition removes the guess.
 */
async function until(cond, ticks = 50) {
  for (let i = 0; i < ticks; i++) {
    if (cond()) return true;
    await Promise.resolve();
  }
  return cond();
}

async function withFakeTimers(run) {
  timers.length = 0;
  globalThis.setTimeout = (fn, ms) => {
    const timer = { fn, ms, cleared: false };
    timers.push(timer);
    return timer;
  };
  globalThis.clearTimeout = (timer) => {
    if (!timer) return;
    timer.cleared = true;
    const index = timers.indexOf(timer);
    if (index !== -1) timers.splice(index, 1);
  };
  try {
    await run();
  } finally {
    globalThis.setTimeout = originalSetTimeout;
    globalThis.clearTimeout = originalClearTimeout;
    timers.length = 0;
  }
}

test("brightspace-open ignores a fresh lastScan", async () => {
  resetState();
  const lastScan = Date.now();
  memory.local.lastScan = lastScan;
  memory.sync.courses = [{ org: "org" }];
  let queried = false;
  queryImpl = async () => {
    queried = true;
    throw new Error("scan should not run");
  };

  const response = await send("brightspace-open");

  assert.equal(response.ok, true);
  assert.deepEqual(response.data, { skipped: "debounced" });
  assert.equal(queried, false);
  assert.equal(memory.local.lastScan, lastScan);
});

test("brightspace-open scans when lastScan is older than the window", async () => {
  resetState();
  const before = Date.now();
  memory.local.lastScan = before - 10 * 60 * 1000 - 1;
  memory.sync.courses = [{ org: "org" }];
  let queries = 0;
  let sends = 0;
  queryImpl = async () => {
    queries++;
    return [{ id: 3 }];
  };
  sendMessageImpl = async () => {
    sends++;
    return { ok: true, data: [] };
  };

  const response = await send("brightspace-open");

  assert.equal(response.ok, true);
  assert.equal(response.data.fresh, 0);
  assert.equal(queries, 1);
  assert.ok(sends >= 1);
  assert.ok(memory.local.lastScan >= before);
});

test("appTab resolves and removes its onUpdated listener", async () => {
  await withFakeTimers(async () => {
    resetState();
    queryImpl = async () => [];
    createImpl = async () => ({ id: 5, url: "https://app.example/", active: false });

    const ready = appTab("https://app.example/path");
    assert.ok(await until(() => timers.length === 1 && updatedListeners.size === 1),
              "appTab should have registered one timer and one onUpdated listener");

    assert.equal(timers.length, 1);
    assert.equal(timers[0].ms, 30000);
    assert.equal(updatedListeners.size, 1);
    const on = [...updatedListeners][0];
    assert.equal(typeof on, "function");

    on(5, { status: "complete" });
    const tab = await ready;

    assert.equal(tab.id, 5);
    assert.equal(updatedListeners.size, 0);
    assert.equal(timers.length, 0);
  });
});

test("appTab rejects on timeout and removes its onUpdated listener", async () => {
  await withFakeTimers(async () => {
    resetState();
    queryImpl = async () => [];
    createImpl = async () => ({ id: 5, url: "https://app.example/", active: false });

    const ready = appTab("https://app.example/path");
    assert.ok(await until(() => timers.length === 1 && updatedListeners.size === 1),
              "appTab should have registered one timer and one onUpdated listener");

    assert.equal(timers.length, 1);
    assert.equal(timers[0].ms, 30000);
    assert.equal(updatedListeners.size, 1);

    timers[0].fn();
    await assert.rejects(ready, (error) =>
      error.message === "the CognitioFlow tab did not finish loading"
    );

    assert.equal(updatedListeners.size, 0);
  });
});
