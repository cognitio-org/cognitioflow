# Set up the CognitioFlow Brightspace grabber

Paste this whole file to Claude. It is self-contained: it assumes no knowledge of the repo.

## What you are setting up

A Chrome MV3 extension that watches my RUG Brightspace courses and finds material I do not have yet.
After a course's first list has been reviewed, new files go to CognitioFlow **automatically** (v0.2):
the extension reads Brightspace with my browser session and uploads with a write key bound to that one
course. It never sees a password and never signs in for me.

- Extension folder: `/Users/matejmonteleone/dev/cognitioflow/extension/brightspace`
- CognitioFlow app: `https://app.cognitioflow.ai` (Google sign-in, allow-listed account)
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
3. **CognitioFlow address**: `https://app.cognitioflow.ai`
4. Click **Grant** and accept the host permission prompt. Without it, uploads fail.
5. Click **Detect** — it reads my enrolled courses from the Brightspace tab and my course list from the
   CognitioFlow tab, so nothing has to be typed twice.
6. Pair each Brightspace course with the matching CognitioFlow course (`eu` = European Law,
   `prop` = Property Law). A course with no pairing is skipped with an error at upload time.
7. **Save**, and confirm it says "Saved."

## Step 3b — automatic sync (v0.2), per course

Do this for each course that should sync by itself (PIL `564701`, LaPoPo `564708`):

1. In Options, use **Add PIL + LaPoPo** (or **Read from open tabs**) and pick each row's CognitioFlow
   course, then **Save**.
2. With CognitioFlow open and signed in (I sign in), press **Create sync key** on the row. It makes a
   90-day write key for that one course and keeps it on this computer only. You never see or copy it.
   Fallback: I mint one myself and paste it into the row's key field, then **Use**.
3. Press **Test**. Expect "Key works for this course".
4. **Baseline before anything else.** Press **Mark what CognitioFlow already has**. Files whose name is
   already in that CognitioFlow course (for PIL: Lecture 1, which I added by hand) are marked as synced.
   The message lists what will upload. If that list holds something I already have under another name,
   stop and show me. **Mark everything as synced** uploads nothing at all.
5. Tick **Auto**. From now on the extension checks every N hours (default 6), a minute after Chrome
   starts, and when I open that course on Brightspace. Popup → **Sync now** runs it immediately.
6. Badge meanings: a green number means files were synced. **BS** means sign in to Brightspace. **KEY**
   means the key is missing or expired, so make a new one in Options. **!** means another error; see
   popup → Recent activity.

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
  content check; the extension's local `seen` list, ledger and sha256 hashes are the only guard. Sync from
  one Chrome profile only. If extension storage was cleared or
  this is a different Chrome profile, a second Add re-uploads everything. Check Files before adding in
  bulk.
- **Files over 40 MB are refused by design** (the base64 message hop cannot carry them). The message
  tells me to download it from Brightspace and add it in CognitioFlow directly.
- **Background reading without a Brightspace tab is unverified.** If Chrome does not send the Brightspace
  cookie with the extension's own requests, every course shows `login needed` (badge **BS**) unless a
  Brightspace tab is open. Report which one you see.
- The PIL HTML-wrapper parsing is tested against a synthetic page only. If the popup or Options says
  a page had "no file link", tell me the page title.
- The D2L API versions are pinned (`le/1.97`, `lp/1.47`). If reads start 404ing, that is the cause.

## If something breaks

Report to me: which step, the exact error text, whether the service worker console shows anything, and
whether the Brightspace tab and the CognitioFlow tab were both open and signed in. Do not attempt to work
around a sign-in problem.
