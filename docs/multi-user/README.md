# Multi-user readiness: what is in this PR and what needs Matej's named yes

Branch `feat/multi-user-ready`. Ownership model from #178, tightened 2026-11-14: course **content** the owner made is
shared to every signed-in user and edited only by him; **progress** (card schedule, reviews, chat, sessions, essays,
AI use, the cards a student's own misses create) is private per user; a course a **student** creates is private to
that student (default private, the owner included).

## 2026-11-14 fixes (Matej: "un-park multi-user"; production only after 27 Nov)

| # | Fix | Where | Test (tests/test_multiuser_isolation.py) |
|---|-----|-------|------|
| 1 LEAK | A non-owner's missed case MCQ / bench question is a PRIVATE card (`cards.user_id`, 037). Every per-user card read adds `(c.user_id IS NULL OR c.user_id=?)`; owner bulk jobs, counts, quiz distractors and the owner's export read shared cards only. A private card is 404 to anyone else on edit. | patch (run.py, 037), multiuser.py export | `test_bs_missed_bench_note_is_bs_private_card_never_in_as_deck` (canary sweep of every GET route as A and as a 3rd student), `test_bs_missed_case_mcq_is_private_and_dedupes_per_user` |
| 2 LEAK | `run._USER_IDS` removed: the email->id lookup is fresh on every AI call, so a deleted-and-re-signed student is logged against the new id and capped (and a 2nd Cloud Run instance cannot keep a stale copy). | patch (run.py) | `test_delete_then_sign_in_again_is_capped_and_logged_to_the_new_id` |
| 4 | Account + Privacy links in the main UI (sidebar, under the email). A non-owner must acknowledge the notice before first use: the page redirects to `/static/account.html?ack=1`, and the server (PrivacyGate) answers **428** on every signed-in route (see 4b) except `/api/me`, `/api/me/privacy`, `/api/me/export`, `/api/me/delete`, `/api/config` until they do. The owner is never asked. | multiuser.py, static/ | `test_privacy_ack_is_enforced_before_first_use`, `test_main_ui_links_account_and_privacy_and_gates_on_ack` |
| 5 | Caps on every lane: `llm.check_guards()` runs before the local lane and the gateway bulk-card lane (outside their fall-back catch); Timer/threads (docket writer, note audio) run in a copied context, so the uploader is capped and logged; server TTS (`/api/speak`, note audio), hosted STT and voice sockets are metered (cap check + one `ai_calls` row each). `LimitReached` passes through the broad `except Exception` handlers and becomes **429** (app exception handler). Voice sockets close 4429 / 4428 / 4404. | multiuser.py, llm.py, gateway.py, patch | `test_bulk_card_and_local_lanes_are_capped`, `test_background_jobs_keep_the_requesting_user`, `test_server_voice_is_metered_and_capped`, `test_a_capped_student_gets_429` |
| 6 | `card_gen_samples` / `card_edits` get `user_id` (037), written by the capture; erase deletes them and export includes them (found by schema, `_user_tables`). | patch (run.py, 037) | `test_capture_rows_carry_the_user_and_are_erased_with_them` |
| 7 | A course a student creates is private: its files, notes, versions, recordings, cards, concepts, search and voice dialog are 404 to everyone else; it is left out of `/api/courses`, `/api/today`, `/api/due`. Enforced centrally by PrivacyGate on `/api/courses/{cid}`, `/api/notes|files|cards|concepts|recordings|versions/{id}`. | multiuser.py, patch | `test_a_students_own_course_is_private_to_them` |
| S8 | `/api/courses` hides `user_id` from non-owners (gives `mine`). | patch | (in the test above) |
| S9 | Case rotation per user (`case_seen`, 037); the course owner keeps the per-course mark too. | patch, 037 | `test_case_rotation_is_per_user` |
| S11 | Erase deletes the invite row (the address is not kept). | multiuser.py | `test_erase_drops_the_invite_and_the_owner_can_erase_an_account` |
| S5 | Owner-side erase: `POST /api/admin/users/{uid}/delete {confirm: email}`. | multiuser.py | same |
| C1 | Invite lookup keeps the last list and retries after 5 s during a DB outage, not on every request. | multiuser.py | `test_invite_lookup_does_not_retry_every_request_during_an_outage` |
| 4b | The gate is default-deny for every signed-in path, not only /api: `POST /speech` (non-/api alias of `/api/speech`, sends the answer to the grader) is 428 before the acknowledgement. Exempt only: `/`, `/sw.js`, `/health(z)`, `/static/*`, `/play/*`, `/auth/*` (`multiuser.gated_path`). A route audit test fails if a new non-/api route skips the gate. | multiuser.py | `test_speech_alias_outside_api_is_gated_before_ack`, `test_every_signed_in_route_outside_api_is_gated_or_known_harmless` |
| C2 | Checked on the unpatched test branch: the PK really is `streak_freezes_pkey`. | - | - |

Known limits (documented, not fixed): the cap is check-then-log, so concurrent calls can overshoot it by the calls
already in flight; a voice session is metered once per session, not per minute; S12 (export holds file names, not
file bytes) is unchanged; the student AI routing (free OpenRouter model may log prompts) is still Matej's decision.

## In this PR (no protected file touched)

| File | What |
|---|---|
| `multiuser.py` | Routes: `/api/me`, `/api/me/export`, `/api/me/privacy`, `/api/me/delete`, `/api/admin/invites` (GET/POST/DELETE), `/api/admin/users`. Helpers the patch calls: `invited_emails`, `mark_accepted`, `capture_allowed`, `is_owner`, `cap_guard`. |
| `llm.py` | `GUARDS` seam + `LimitReached(ConfigError)`: a registered guard runs before every `client()`. Empty unless `multiuser.install()` registers the per-user cap. |
| `static/privacy.html` | Privacy notice, **marked DRAFT** for Matej's wording + AI-routing decision. Public (under `/static/`). |
| `static/account.html` | My account: consent toggle, my AI use, download my data, delete my account; owner sees "Invite a student" + accounts with 24h/30d AI cost. |
| `tests/test_multiuser_isolation.py` | Two-user isolation (A owner, B classmate) + export/delete/consent/invites/caps. Every test on the `mu` fixture needs migration 035, which is inside the patch, so without the patch they skip; tests marked `needs_patch` also need the run.py/auth.py changes. |

**Inert until the patch is applied:** every route in `multiuser.py` and the cap guard. Nothing imports `multiuser`
except `run.py` after the patch. (Tests mount it onto `run.app` themselves.)

## `protected-changes.patch` (apply with `git apply docs/multi-user/protected-changes.patch`)

Needs Matej's named yes: it edits `run.py`, `auth.py`, `.github/workflows/deploy.yml` and adds three migrations
(035, 036, 037; 036 changes a key). No migration is committed in the PR tree: migrations change only through this patch.

### run.py
1. `multiuser.install(app, db, _CALL)` right after `auth.install`: mounts the routes, registers the cap guard.
2. `client()`: `llm.LimitReached` is re-raised as-is (not the 400 for a missing key); multiuser's app exception
   handler turns it into **429**, and the user-facing broad `except Exception` handlers re-raise it first.
3. **Games bug (map d1):** new `_see_course(cid)` for READS. `lawyer-pack`, `docket` and `docket/{gid}` use it, so a
   classmate can play the owner's games and 3D show. A non-owner never sees drafts (`?draft=` is ignored; a draft
   game id is 404). Docket-draft authoring routes keep `_own_course` (owner-only).
4. `/api/spend/week`: the owner sees the whole app; anyone else sees only their own calls (no cross-user totals).
5. `/api/courses/{cid}/usage`: `messages` and `sessions` count the caller's own rows only.
6. `_capture_on()`: training capture also needs `multiuser.capture_allowed` — owner keeps the Phase 19 default (on
   unless he opts out), **everyone else is off until they tick yes**. No request user (background job): unchanged.
7. Streak-freeze ledger writes `user_id`.
8. `_oral_bank`: called `_card_scope(cid, 0, week, 0)` against `(cid, uid, due, week, weak)`, so uid was 0 (the
   student's own private cards dropped out) and `week` landed in `due` (the week filter became a due filter; this half
   is also on main). Now `_card_scope(cid, _uid(), 0, week, 0)`. Test: `test_oral_bank_is_the_callers_cards_filtered_by_week`.

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
- `tests/test_arena3d.py`: another (student) user's course stays **404** for lawyer-pack/docket/docket-drafts, now
  because a student's course is private; a classmate opening the OWNER's games is tested in the isolation file.
- `tests/test_courses.py`: `/usage` messages/sessions are the caller's own, so only content counts are compared.

### migrations/035_multiuser_ready.sql (inside the patch, additive)
`invites`, `user_prefs`, index `ai_calls(user_id, at)`, nullable `streak_freezes.user_id`. It was committed on the
branch until 2026-11-14 and moved here byte-identical (blob f84cc8f), so merging the PR alone adds no migration. Its
header comment still says it reaches production when the PR deploys; that is now true only once the patch is applied.

### migrations/037_private_progress_cards.sql (inside the patch on purpose, additive)
`cards.user_id` (private practice cards, FK users ON DELETE CASCADE), `card_gen_samples.user_id`, `card_edits.user_id`,
table `case_seen(user_id, case_id, seen)`, partial indexes. Old code ignores all of it. Rollback: `DROP TABLE case_seen;`
`ALTER TABLE cards DROP COLUMN user_id;` (after deleting private cards: `DELETE FROM cards WHERE user_id IS NOT NULL`),
`ALTER TABLE card_gen_samples DROP COLUMN user_id; ALTER TABLE card_edits DROP COLUMN user_id;`.

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
- Full suite with and without the patch, re-run after 035 moved into the patch (see PR body for the counts). Migration 037 checksummed on a Neon **test branch** of production (see PR body).

## Not done / Matej decides
- **(d)2** Student-created courses are now **private by default** (owner included). Sharing one is not built yet.
- **Card content sharing**: B sees A's cards as shared course content by design (#178); only the schedule is private.
- **AI routing for students**: live config routes the gateway lane to a free OpenRouter model that may log prompts
  (`CF_GATEWAY_MODEL=…:free`). Decide before inviting anyone outside your circle; the privacy notice says so.
- Deleting a user who owns courses is refused (409) — what happens to their courses is your call.
