# CognitioFlow Brightspace grabber — working spec

Everything needed to finish this extension without re-reading the whole codebase. Written 2026-09-17
against `manifest.json` v0.1.0, after PR #40 (dedupe, size limit, sign-in errors) landed. **Updated
2026-11-10 for v0.2.0 (automatic sync, `sync.js`)** — sections 1, 2, 3 and 7 changed; section 8 is new.

**What it is:** a Chrome MV3 extension that watches the RUG Brightspace courses you list and works out
which material is new. After you have reviewed a course once (popup or Options baseline), new files go to
CognitioFlow **automatically**: the service worker reads Brightspace itself and uploads with a write key
bound to that one course. Courses with no key still work the v0.1 way (tick, then an open CognitioFlow
tab uploads them as you). It never sees a password and stores no course content.

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
| `content-app.js` | CognitioFlow tab (injected on demand by `chrome.scripting`) | `courses` (`GET /api/courses`), `upload` (`POST /api/courses/{cid}/files`, keyless path), `files` (names, for the baseline), `mintKey` (`POST /api/tokens` write key, Options only) |
| `background.js` | service worker | wiring: routes (`scan`, `sync-now`, `take`, `skip`, `baseline`, `test-key`, `set-auto`, `schedule`, `badge`, `brightspace-open`), the `sync` alarm (onInstalled **and** onStartup), badge |
| `sync.js` | imported by the worker; all deps injected, tested in `test/sync.test.mjs` | the automatic run: read Brightspace (direct, else open tab), decide per item, validate bytes, sha256, upload with the course's key, ledger, status, log, lock |
| `lib.js` | imported by the worker, unit-tested | pure parsing: `documents`, `pages`, `moduleIds`, `linksIn`/`documentPath` (wrappers), `weekOf`, `enforcedFolder`, `unseen`, `dedupe`, `decide`, `looksLikeDocument`, `isLoginResponse`, `sha256` |
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
| `storage.sync` | `appUrl` | string | CognitioFlow origin, e.g. `https://app.cognitioflow.ai` |
| `storage.sync` | `courses` | `[{org, name, cid}]` | Brightspace org unit ↔ CognitioFlow course id. **The allow-list:** nothing outside it is read or uploaded |
| `storage.sync` | `syncHours` | number (1–48, default 6) | alarm period |
| `storage.local` | `cfKeys` | `{cid: {token, id, courseId, expires(ms), origin}}` | write keys. **Local only, never sync**; only the worker sends them, and only when `appUrl`'s origin equals the `origin` recorded when the key was made or pasted (https, or http on localhost) — otherwise status `key is for another address`; the UI shows the last 4 characters |
| `storage.local` | `seen` | `{org: [key]}` | keys added **or** deliberately skipped |
| `storage.local` | `ledger` | `{org: {key: {signal, sha, cfFileId, status, at, name, baseline?, skipped?, via?}}}` | what was synced and with which change signal (TOC `LastModifiedDate`; HEAD `Last-Modified`/`ETag`/size for links). An in-flight marker `{pending: {sha, at, signal, surfaced?}, prev, name}` is written **before** each POST, replaced after the 2xx, taken back after a definite failure. The marker is placed by compare-and-set (skipped if the item was remembered/added meanwhile). A marker left by a killed worker is checked on every scan, Auto on or off: logged once as "check in CF", the same bytes are not re-sent, and the file stays out of the list; after 24h the marker is taken back, so the file is retried / offered again |
| `storage.local` | `shaByCid` | `{cid: [sha256]}` (arrays — storage drops `Set`s) | same bytes via two keys upload once |
| `storage.local` | `pending` | `{org: [item]}` | unhandled items, what the popup lists |
| `storage.local` | `confirmed` | `{org: bool}` | first batch reviewed: set by an Options baseline, or by popup Add/Remember only once **every** file of the first list has been chosen (unticked files stay pending and never auto-upload) |
| `storage.local` | `auto` | `{org: bool}` | automatic upload on for this course (Options) |
| `storage.local` | `status` | `{org: {state, detail, at, uploaded?, emptyPages?}}` | `ok`, `login needed`, `key needed`, `key expired`, `key is for another course`, `key is for another address`, `no access to CognitioFlow`, `waiting for first review`, `auto off`, `error` |
| `storage.local` | `log` | `[{at, org, name, action, error?}]`, last 200 | shown under "Recent activity" in the popup |
| `storage.local` | `lastScan`, `lastRun`, `syncLock` | epoch ms / `{at, uploaded}` / `{owner, expires}` | popup text, badge, the run lease: taken by compare-and-set under `navigator.locks`, renewed after every file, released only by its owner, expires 10 min after the last renewal |

Every write to `seen` / `pending` / `ledger` / `confirmed` / `status` / `log` is a read-modify-write under
one Web Lock (`sync.mutate`, also used by the worker's Remember/Add), merged per key, so a Remember made
while a run is uploading is never overwritten by the run's save, and the run re-reads an item just before
downloading it.

Links found in pages are accepted only under `/content/enforced/<org>-…/` of the course being read (the
org prefix, so another offering's folder of the same org counts), after decoding; `.`/`..` segments,
backslashes and double-encoded segments are refused.

An **item**: `{key, kind: "topic"|"link", title, name, week, module, url, path, lastModified}`. `key` is
`t:<TopicId>` for a File topic and `f:<decoded path>` for a document found inside a page (the PIL
wrappers) or module description; `dedupe()` collapses the two when they share a path.

**Per-item decision (`lib.js` `decide`)**: never handled → upload · handled but no stored signal (v0.1
Add/Remember, hand-added material) → *adopt* the signal seen now, upload nothing · signal unchanged or
absent → skip without downloading · signal changed → download, sha256; same hash → ledger only; entry had
no hash yet (baseline / Remember / hand-added) → learn the hash, **no upload**, logged so you can add it by
hand if the content really changed; otherwise new hash → upload as a new row, logged "updated (old
version still in CognitioFlow)". A failed HEAD on a linked file counts as "no signal", not as signed-out.

**Automatic upload happens only when all hold:** course in `courses` with a `cid`; `confirmed[org]`;
`auto[org]`; `cfKeys[cid]` present, `courseId === cid`, not expired; the CF origin permission granted.
At most 20 uploads per run, 3 s apart; the rest go next run.

## 3. Permissions, and why each one is there

`alarms` (the `sync` alarm, every `syncHours`; plus a one-off `sync-startup` a minute after browser start,
because an alarm survives the worker being killed and a `setTimeout` does not) · `storage` ·
`notifications` ("N files synced") · `scripting` (inject `content-app.js` into the app tab).
Host: `https://brightspace.rug.nl/*` — also what lets the worker `fetch` D2L with the session cookie
(`credentials: "include"`) when no Brightspace tab is open. Optional hosts: `https://*/*`,
`http://localhost/*`, `http://127.0.0.1/*` — the CognitioFlow origin is granted at runtime from Options
and checked with `permissions.contains` before every upload run. No new permission in v0.2.

**Unverified (spike S1):** whether Chrome sends the Brightspace session cookies with a worker-origin
request. If it does not, every direct read looks signed-out; the reader then falls back to an open
Brightspace tab's content script. With no tab open the course shows `login needed` and nothing uploads.

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
**Status at v0.2:** B (debounce) and C (app-tab timeout) were done before v0.2; D (visible scan errors,
`status[org]`, `login needed`) and most of H (worker tests, `test/sync.test.mjs`) are done in v0.2; A is
reduced (sha256 ledger) but not solved — see section 8.

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

- No password or cookie is ever read, stored or forwarded. Brightspace is read with the browser's own
  session; the extension never completes a sign-in. A login-looking answer (401/403, redirect, another
  host, `/d2l/login`, HTML where a document was expected, a PDF without `%PDF`) stops that course with
  `login needed` and uploads nothing.
- **Changed in v0.2:** one CognitioFlow **write key per course** is stored, in `storage.local` only. It is
  minted by the owner's signed-in session (`POST /api/tokens {scope:"write",course_id,ttl_days:90}`),
  can only `POST /api/courses/<that cid>/files|cards/generate` (server-enforced, `auth.py`), expires
  in ≤ 90 days, and is revocable (`DELETE /api/tokens/{id}`). The cid comes from the Options map and the
  key from `cfKeys[cid]` — never from a message — so one course's key is never sent for another.
- No course content is persisted by the extension — only keys, hashes, dates and file names.
- **Changed in v0.2:** the first batch per course is still never uploaded unreviewed — `confirmed[org]`
  (popup Add/Remember, or an Options baseline) and `auto[org]` must both be set before the alarm uploads.
- Uploads only ever go to the origin saved in Options, which must be granted by hand. Only documents
  (pdf, pptx, docx, …) are ever uploaded — never an `.html` wrapper, never a link to another host.
- No LLM call in the extension. Text extraction and indexing stay server-side.

---

## 8. Known gaps after v0.2

- **Dedupe is still client-side.** Wiping extension storage, reinstalling, or a second Chrome profile
  re-uploads everything; a changed file adds a second row the key cannot delete. Fix is server-side and
  needs the owner's approval (schema + auth): migration adding `files.sha256` unique per course, `upload()`
  answering `duplicate: true`; optionally let a `cfw_` key `GET` its own course's file list.
- Fixtures in `test/fixtures/` are **synthetic**; the real PIL wrapper markup and whether RUG's TOC fills
  `LastModifiedDate` are unverified. A wrapper that yields no document is listed in `status[org].emptyPages`.
- Files over 49 MB are skipped and logged (the whole multipart body is capped at 50 MB server-side).
- A key's expiry shows in Options; there is no badge warning before it lapses — a lapsed key shows `KEY`.
- Options revokes a key it removes or replaces (through the CF tab); a pasted key has no id, so revoke it
  in CognitioFlow yourself.
- Baseline "match" compares file names exactly (case and spacing folded); a hand-added file renamed on
  upload is not matched and would upload once.
- Relative links now resolve against the page's own folder (browser semantics), so an `f:` key from v0.1
  for a page in a subfolder may be offered again in the popup.
