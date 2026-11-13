# Multi-user readiness: what is in this PR and what needs Matej's named yes

Branch `feat/multi-user-ready`. Ownership model is unchanged from #178: course **content** is shared to every
signed-in user and edited only by its owner; **progress** (card schedule, reviews, chat, sessions, essays, AI use) is
private per user.

## In this PR (no protected file touched)

| File | What |
|---|---|
| `multiuser.py` | Routes: `/api/me`, `/api/me/export`, `/api/me/privacy`, `/api/me/delete`, `/api/admin/invites` (GET/POST/DELETE), `/api/admin/users`. Helpers the patch calls: `invited_emails`, `mark_accepted`, `capture_allowed`, `is_owner`, `cap_guard`. |
| `llm.py` | `GUARDS` seam + `LimitReached(ConfigError)`: a registered guard runs before every `client()`. Empty unless `multiuser.install()` registers the per-user cap. |
| `migrations/035_multiuser_ready.sql` | **Additive only**: `invites`, `user_prefs`, index `ai_calls(user_id, at)`, nullable `streak_freezes.user_id`. Applies automatically at boot when this PR deploys; changes no behaviour on its own. |
| `static/privacy.html` | Privacy notice, **marked DRAFT** for Matej's wording + AI-routing decision. Public (under `/static/`). |
| `static/account.html` | My account: consent toggle, my AI use, download my data, delete my account; owner sees "Invite a student" + accounts with 24h/30d AI cost. |
| `tests/test_multiuser_isolation.py` | Two-user isolation (A owner, B classmate) + export/delete/consent/invites/caps. Five tests marked `needs_patch` skip until the patch is applied. |

**Inert until the patch is applied:** every route in `multiuser.py` and the cap guard. Nothing imports `multiuser`
except `run.py` after the patch. (Tests mount it onto `run.app` themselves.)

## `protected-changes.patch` (apply with `git apply docs/multi-user/protected-changes.patch`)

Needs Matej's named yes: it edits `run.py`, `auth.py`, `.github/workflows/deploy.yml` and adds a migration that
changes a key.

### run.py
1. `multiuser.install(app, db, _CALL)` right after `auth.install`: mounts the routes, registers the cap guard.
2. `client()`: `llm.LimitReached` becomes **429** (otherwise a capped call would surface as the 400 for a missing key).
3. **Games bug (map d1):** new `_see_course(cid)` for READS. `lawyer-pack`, `docket` and `docket/{gid}` use it, so a
   classmate can play the owner's games and 3D show. A non-owner never sees drafts (`?draft=` is ignored; a draft
   game id is 404). Docket-draft authoring routes keep `_own_course` (owner-only).
4. `/api/spend/week`: the owner sees the whole app; anyone else sees only their own calls (no cross-user totals).
5. `/api/courses/{cid}/usage`: `messages` and `sessions` count the caller's own rows only.
6. `_capture_on()`: training capture also needs `multiuser.capture_allowed` — owner keeps the Phase 19 default (on
   unless he opts out), **everyone else is off until they tick yes**. No request user (background job): unchanged.
7. Streak-freeze ledger writes `user_id`.

### auth.py
- `admitted(email, db)`: `ALLOWED_EMAILS` **or** a live invite (cached 30 s; revoke takes effect within that).
  Used by the session check (every request, HTTP + WebSocket), the OAuth callback, and API-key owners.
- Callback marks an invite accepted on first sign-in. `AUTH=off` dev/test path unchanged.

### deploy.yml (production `gcloud run deploy` only; the two test-job `ALLOWED_EMAILS` lines are unchanged)
- `--set-env-vars` switches to gcloud's custom delimiter `^;^` because the allow-list itself is comma-separated.
- `ALLOWED_EMAILS=${{ vars.CF_ALLOWED_EMAILS || 'matej@mgms.eu' }}`: set the repo variable `CF_ALLOWED_EMAILS` (e.g.
  `matej@mgms.eu,student@rug.nl`) or leave it unset to keep today's single address. With invites, the variable is
  optional: the owner can invite from `/static/account.html` instead.
- `OWNER_EMAIL=matej@mgms.eu` is now explicit (otherwise the owner is whoever is first in the list).
- `CF_USER_DAILY_USD` (default 1.00) / `CF_USER_DAILY_CALLS` (default 150), overridable by repo variables. Owner is
  never capped per user; `CF_USER_CAPS=off` switches caps off without a deploy.

### tests changed by the patch (they assert the old behaviour)
- `tests/test_arena3d.py`: another user's course lawyer-pack/docket is now **200** (was 404); drafts stay 404.
- `tests/test_courses.py`: `/usage` messages/sessions are the caller's own, so only content counts are compared.

### migrations/036_streak_freezes_per_user.sql (inside the patch on purpose)
Seen during testing: an early draft of 036 without `NULLS NOT DISTINCT`, applied under the old run.py, let the old
insert's NULL user_id rows pile up (`test_streak_freeze_is_consumed_once` failed). The final 036 keeps NULLs
conflicting, but it still ships with the run.py write so the key change and the code that relies on it merge together.

Backfills `streak_freezes.user_id` from the course owner, drops the `(course_id, day)` key, adds a unique
`(course_id, user_id, day) NULLS NOT DISTINCT`. It must land together with the run.py write (7), so it is not in the
PR tree. Correction to the map: the streak *number* was always computed from the caller's own reviews; only the
write-only ledger was shared.

## Verified
- Patch applies cleanly to the PR head (`git apply --check`).
- Full suite on a Neon **test branch** of production with and without the patch (see PR body).

## Not done / Matej decides
- **(d)2** Should a student's own new courses/notes be private? Today they are visible to every signed-in user.
- **Card content sharing**: B sees A's cards as shared course content by design (#178); only the schedule is private.
- **AI routing for students**: live config routes the gateway lane to a free OpenRouter model that may log prompts
  (`CF_GATEWAY_MODEL=…:free`). Decide before inviting anyone outside your circle; the privacy notice says so.
- Caps cover the main model path (`client()`); the cheap bulk lane (`gateway.call`, `llm.local_call`) is under the
  app-wide `CF_GATEWAY_SPEND_CEILING` only.
- No link to `/static/account.html` from the main UI yet (index.html untouched to keep the hook contract safe).
- Deleting a user who owns courses is refused (409) — what happens to their courses is your call.
