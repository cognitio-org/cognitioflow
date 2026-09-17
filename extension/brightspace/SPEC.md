# CognitioFlow Brightspace grabber — working spec

Everything needed to finish this extension without re-reading the whole codebase. Written 2026-09-17
against `manifest.json` v0.1.0, after PR #40 (dedupe, size limit, sign-in errors) landed.

**What it is:** a Chrome MV3 extension that watches the RUG Brightspace courses you list, works out which
material is new, and — once you tick it — hands the bytes to an open CognitioFlow tab, which uploads them
as you. It never sees a password and stores no course content, only a list of keys it has already handled.

---

## 1. How the pieces fit

```
popup.html/js ──┐                                  ┌── content-brightspace.js  (in a brightspace.rug.nl tab)
options.html/js ┼── chrome.runtime.sendMessage ──► background.js ──chrome.tabs.sendMessage──┤   toc/module/page/file
                │        (service worker)              routes                               └── content-app.js (in a CognitioFlow tab)
                └── chrome.storage (sync + local)                                                courses/upload
```

Two content scripts, because each side's fetches must be same-origin to carry that side's own login:

| File | Runs in | Responsibility |
|---|---|---|
| `content-brightspace.js` | `brightspace.rug.nl` tab (declared in manifest, `document_idle`) | D2L API reads: `toc`, `module`, `page`, `file` (bytes as base64), `courses` (enrolments) |
| `content-app.js` | CognitioFlow tab (injected on demand by `chrome.scripting`) | `courses` (`GET /api/courses`), `upload` (`POST /api/courses/{cid}/files`) |
| `background.js` | service worker | orchestration: `scan`, `take`, `skip`, `badge`, hourly alarm |
| `lib.js` | imported by the worker, unit-tested | pure parsing: `documents`, `pages`, `moduleIds`, `linksIn`, `weekOf`, `enforcedFolder`, `unseen`, `dedupe` |
| `popup.js` | popup | the tick-list, Add / Remember / Check now |
| `options.js` | options page | app URL, host permission grant, course pairing (Brightspace org ↔ CognitioFlow course id) |

**Message contract** (both directions use the same envelope): send `{type, ...args}`, reply
`{ok: true, data}` or `{ok: false, error}`. `background.js:9` (`ask`) and the two `onMessage` listeners
throw on `ok: false`, so every failure surfaces as an `Error` with the page's own message.

### D2L endpoints in use (`content-brightspace.js:3,36-41`)
- `GET /d2l/api/le/1.97/{org}/content/toc`
- `GET /d2l/api/le/1.97/{org}/content/modules/{moduleId}`
- `GET /d2l/api/lp/1.47/enrollments/myenrollments/?orgUnitTypeId=3`
- topic/page HTML and file bytes by their own URLs, `credentials: "same-origin"`

**API versions are pinned in a template string.** A D2L upgrade that retires 1.97/1.47 breaks every read
with a 404 and no fallback.

---

## 2. State

| Store | Key | Shape | Meaning |
|---|---|---|---|
| `storage.sync` | `appUrl` | string | CognitioFlow origin, e.g. `https://cognitioflow-…run.app` |
| `storage.sync` | `courses` | `[{org, name, cid}]` | Brightspace org unit ↔ CognitioFlow course id |
| `storage.local` | `seen` | `{org: [key]}` | keys added **or** deliberately skipped — the only duplicate guard |
| `storage.local` | `pending` | `{org: [item]}` | last scan's unseen items, what the popup lists |
| `storage.local` | `confirmed` | `{org: bool}` | has the first batch for this course been reviewed once |
| `storage.local` | `lastScan` | epoch ms | shown in the popup |

An **item**: `{key, kind: "topic"|"link", title, name, week, module, url, path}`. `key` is `t:<TopicId>`
for a File topic and `f:<decoded path>` for a link found inside a page or module description — which is
why `dedupe()` (`lib.js:107`) collapses the two when they point at the same `/content/enforced/…` path,
preferring the topic.

**First-run safety:** `confirmed[org]` is false until the first Add/Skip, so the first scan never fires a
notification for a course — you review the initial list yourself (`background.js:70`, `popup.js:20`).

---

## 3. Permissions, and why each one is there

`alarms` (hourly rescan) · `storage` · `notifications` (new-material toast) · `scripting` (inject
`content-app.js` into the app tab). Host: `https://brightspace.rug.nl/*`. Optional hosts: `https://*/*`,
`http://localhost/*`, `http://127.0.0.1/*` — the CognitioFlow origin is granted at runtime from Options
(`options.js:35` `grant()`), so the extension does not ship with access to every site.

---

## 4. What already works

- Collect across all three places material hides: File topics, links inside HTML topics, links inside
  module descriptions (`background.js:37` `collect`).
- Week detection from names and paths (`lib.js` `weekOf`), shown as a chip in the popup.
- `unseen()` key filtering + `dedupe()` path collapsing, so one file is offered once.
- Badge count, hourly alarm, notification when a confirmed course has new material.
- Per-item failure isolation in `take()` — one bad file does not abort the batch; failures are returned.
- 40 MB refusal with a readable message (`content-brightspace.js:21`), because the base64 message hop has
  an undocumented ceiling well below a lecture recording.
- `401` from the app turns into "sign in to CognitioFlow first" (`content-app.js:15,24`).
- `test/lib.test.mjs` covers the pure parsers; `npm test` runs `node --test`.

---

## 5. What is not finished — the actual work list

Ordered by what would bite a student first. Each item names the acceptance check that should prove it.

### A. Duplicate uploads are only prevented client-side — **highest risk**
`POST /api/courses/{cid}/files` (`run.py:320`) inserts a fresh `uuid` row for every upload and **never
checks for an existing file with the same name or bytes**. The `seen` list in `storage.local` is the only
guard. Clear extension data, use a second Chrome profile, or reinstall, and every file uploads again —
the course fills with duplicates and the tutor's context budget doubles.
*Finish:* either a server-side content hash (`sha256` of the bytes, unique per course, return the existing
id on a repeat) or a `HEAD`-style `GET /api/courses/{cid}/files?name=` check before upload.
*Accept:* uploading the same file twice leaves one row; the popup reports it as "already there", not added.

### B. Every Brightspace page load triggers a full scan
`content-brightspace.js:52` fires `brightspace-open` on every load where the path matches
`/(content|lessons|home)/(\d+)/`, and the worker routes that straight to `scan({notify: true})`
(`background.js:132`). Browsing five pages means five full scans of every configured course, each walking
the TOC plus every page and module.
*Finish:* debounce — ignore a `brightspace-open` within N minutes of `lastScan`, and scan only the org
that was opened.
*Accept:* a test that calls the route twice inside the window and asserts one collect pass.

### C. `appTab()` can hang forever
`background.js:23-31` creates the app tab and awaits an `onUpdated` "complete" that may never arrive
(offline, auth redirect loop, tab closed by the user). There is no timeout and no `onRemoved` handler, so
Add sits disabled with "Adding…" until the popup is closed.
*Accept:* a rejected promise with a readable message after ~30s, and the popup re-enabling its buttons.

### D. Scan failures are invisible
`background.js:75-77` catches per-course errors and writes an empty `pending` list. A course whose TOC
read failed is indistinguishable from a course with nothing new — including when the real cause is an
expired Brightspace session.
*Finish:* keep `lastError[org]` in `storage.local`, render it in the popup group header, and say plainly
when the session looks logged out.
*Accept:* a 401 on the TOC surfaces "Brightspace session expired — open Brightspace and sign in".

### E. Notifications are dead ends
`notifications` is requested and a toast is created (`background.js:79`), but there is no
`chrome.notifications.onClicked` listener, so clicking it does nothing.
*Accept:* clicking opens the popup or focuses the Brightspace tab.

### F. Popup does not show per-item errors
`take()` returns `failed: [{name, error}]`, but `popup.js:60` only concatenates the names. The item stays
in the list with no mark, so the student re-ticks it and hits the same failure.
*Accept:* the failed row shows its error inline and is visibly distinct from an untried one.

### G. No packaging or install path
No build script, no zip, no store listing, no `README` for "load unpacked". Version is `0.1.0` and never
bumped by anything.
*Accept:* `npm run build` produces a loadable zip; a short install section exists for a fresh machine.

### H. Test coverage stops at `lib.js`
`background.js` (scan/take/skip/badge), the message envelope and the popup rendering are untested. The
D2L shapes are only exercised through the `TOC` fixture in `test/lib.test.mjs`.
*Accept:* worker tests with a faked `chrome.*` surface for: first-run confirm gate, `seen` growth on
take/skip, badge count, per-item failure isolation.

### I. Smaller things
- Options accepts any `appUrl` string; a typo only shows up as a failed grant. Validate and offer a
  "test connection" that calls `GET /api/courses` through the app tab.
- `weekOf` has no explicit handling for `wk2`, `week-02`, `W2` mixed in one course — confirm against real
  RUG names, add fixtures for the ones that miss.
- `MAX_GRAB_BYTES` (40 MB) is asserted but never surfaced in the UI before a grab; show the size in the
  list so a refusal is not a surprise.
- Pin the D2L API versions in one constant with a fallback ladder, so an upgrade is a one-line change.

---

## 6. How to run it while working on it

```bash
cd extension/brightspace && npm test          # node --test, pure lib.js parsers
# Chrome → chrome://extensions → Developer mode → Load unpacked → this folder
# Options → app URL → Grant → Detect (fills courses from both open tabs) → pair each course → Save
# Open Brightspace, then the toolbar icon → Check now
```

Service-worker logs: `chrome://extensions` → the extension's **service worker** link. The worker is
killed aggressively when idle; a `console.log` in a route only appears if the worker is awake, so prefer
asserting through `storage.local` when debugging a scan.

---

## 7. Boundaries to keep

- No password, token or cookie is ever read, stored or forwarded. Both sides rely on `credentials:
  "same-origin"` inside a tab the student is already signed into.
- No course content is persisted by the extension — only `seen` keys, `pending` metadata and `lastScan`.
- The student confirms the first batch per course before anything is ever added automatically.
- Uploads only ever go to the origin saved in Options, which must be granted by hand.
