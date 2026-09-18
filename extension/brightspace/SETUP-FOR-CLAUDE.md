# Set up the CognitioFlow Brightspace grabber

Paste this whole file to Claude. It is self-contained: it assumes no knowledge of the repo.

## What you are setting up

A Chrome MV3 extension that watches my RUG Brightspace courses, finds material I do not have yet, and —
after I tick it — hands the bytes to an open CognitioFlow tab, which uploads them as me. It never sees a
password: both sides fetch `credentials: "same-origin"` inside tabs I am already signed into.

- Extension folder: `/Users/matejmonteleone/dev/cognitioflow/extension/brightspace`
- CognitioFlow app: `https://cognitioflow-sarfwmfd3q-ez.a.run.app` (Google sign-in, allow-listed account)
- Brightspace: `https://brightspace.rug.nl`
- Full technical spec, if you need it: `extension/brightspace/SPEC.md` in the same repo

## Rules for you

- **Never type a password, and never complete a sign-in flow.** If a tab is signed out, stop and tell me
  to sign in myself, then continue.
- Do not delete any file, note or course in CognitioFlow.
- The first batch per course is meant to be reviewed by a human. Show me the list; do not tick "Add" for
  the first batch without asking.
- If the same browser step fails 2–3 times, stop and report rather than retrying.

## Step 1 — check it loads

1. Open `chrome://extensions`, turn on **Developer mode** (top right).
2. **Load unpacked** → choose `/Users/matejmonteleone/dev/cognitioflow/extension/brightspace`.
3. Confirm "CognitioFlow Brightspace grabber" appears with no errors. If Chrome shows an error, report
   the exact text.
4. Open the extension's **service worker** link from that page and keep the console visible — the worker
   is killed when idle, so logs only appear while it is awake.

## Step 2 — run its tests (terminal)

```bash
cd /Users/matejmonteleone/dev/cognitioflow/extension/brightspace && npm test
```

All tests should pass. Report any failure verbatim.

## Step 3 — configure it

1. Open Brightspace in one tab and CognitioFlow in another, both signed in (I sign in, not you).
2. Extension → **Options** (or `chrome://extensions` → Details → Extension options).
3. **CognitioFlow address**: `https://cognitioflow-sarfwmfd3q-ez.a.run.app`
4. Click **Grant** and accept the host permission prompt. Without it, uploads fail.
5. Click **Detect** — it reads my enrolled courses from the Brightspace tab and my course list from the
   CognitioFlow tab, so nothing has to be typed twice.
6. Pair each Brightspace course with the matching CognitioFlow course (`eu` = European Law,
   `prop` = Property Law). A course with no pairing is skipped with an error at upload time.
7. **Save**, and confirm it says "Saved."

## Step 4 — first scan

1. With a Brightspace tab open, click the toolbar icon → **Check now**.
2. It walks the course TOC, the HTML topics and the module descriptions, then lists what it believes is
   new, grouped by course, with a Week chip where it could work one out.
3. **Show me that list and wait.** The first batch per course is the one most likely to contain things I
   already have.
4. Once I confirm, tick what I said and press **Add**. Report `added` and any `failed` entries with their
   error text.
5. "Remember" (Skip) marks items as handled without downloading them — use it for anything I say I
   already have.

## Step 5 — verify the upload actually landed

Open CognitioFlow → **Files**. The added files should be listed under the right course and week with
status `indexed` (or `no text` for a scan-only PDF, `image` for a photo). Tell me anything that arrived
as `no text` — that file will be invisible to the tutor.

## Known gaps — do not be surprised by these

- **Duplicate protection is client-side only.** The server inserts a new row per upload with no name or
  content check; the extension's local `seen` list is the only guard. If extension storage was cleared or
  this is a different Chrome profile, a second Add re-uploads everything. Check Files before adding in
  bulk.
- **Files over 40 MB are refused by design** (the base64 message hop cannot carry them). The message
  tells me to download it from Brightspace and add it in CognitioFlow directly.
- **Every Brightspace page load currently triggers a full rescan** — expect it to be slower than it
  should be while browsing. A debounce is queued but may not be in the build you are looking at.
- **A failed scan looks identical to "nothing new"**, including when my Brightspace session has expired.
  If a course shows nothing and you expected material, open Brightspace and check I am still signed in.
- The D2L API versions are pinned (`le/1.97`, `lp/1.47`). If reads start 404ing, that is the cause.

## If something breaks

Report to me: which step, the exact error text, whether the service worker console shows anything, and
whether the Brightspace tab and the CognitioFlow tab were both open and signed in. Do not attempt to work
around a sign-in problem.
