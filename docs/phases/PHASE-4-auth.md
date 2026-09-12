# Phase 4 — Google sign-in + Secret Manager

Branch: `phase-4-auth`. Depends on Phase 1. Can run in parallel with 2–3.

## Decisions — settled (2026-09-12)
- **Allow-list:** `ALLOWED_EMAILS=matej@mgms.eu` only (comma-separated env var). Later this becomes a `users` table check.
- **OAuth client [Matej, still to do — blocks sign-in testing, not coding]:** create it in the GCP console (APIs & Services → Credentials → OAuth client, Web application). Redirect URIs: `http://localhost:8000/auth/callback` and the Cloud Run URL's `/auth/callback` (added in Phase 5). Paste client id/secret into `.env.local` as `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.

## Objective
Nobody but allow-listed accounts can reach any `/api/*` route or the UI. The Anthropic key is never exposed to an unauthenticated request. Secrets are read from env only; in cloud they come from Secret Manager. Every request is tied to a `users` row so multi-user is a data filter later, not a rewrite.

## Design (keep it small — this is ~150 lines)
- Routes: `GET /auth/login` → Google OAuth (authlib), `GET /auth/callback` → verify id_token, check email against allow-list, upsert `users`, set a signed HTTP-only session cookie (`itsdangerous`, `SESSION_SECRET` env, 30-day expiry, `Secure` when not localhost, `SameSite=Lax`). `POST /auth/logout`.
- Middleware: every path except `/auth/*`, `/static/*`, `/healthz` requires a valid session; API routes return 401 JSON, `/` redirects to `/auth/login`.
- `request.state.user` is set; add a `current_user(request)` dependency. **Do not** filter data by user yet — single tenant — but every new row that has a `user_id` column (only `courses` for now) gets it from `current_user`.
- No API/Bearer tokens: they existed only for the local worker, which was dropped (2026-09-12). The session cookie is the only credential. `migrations/004_auth.sql` only if the phase needs schema changes.
- Dev bypass: `AUTH=off` in `.env.local` logs in as the first address in `ALLOWED_EMAILS` without Google, for docker-only development and tests — so the bypass user is always one that real sign-in would also admit (`MATEJ_EMAIL` stays only as `migrate_sqlite.py`'s owner email). Refuse to start with `AUTH=off` when `ENV=production` or when `ALLOWED_EMAILS` is empty.
- `/healthz` returns 200 with no auth (Cloud Run probe).

## Secrets
- Code reads only `os.environ`. Phase 5 mounts Secret Manager secrets as env vars; nothing to do here beyond documenting the names: `ANTHROPIC_API_KEY`, `DATABASE_URL`, `SESSION_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.
- Add `scripts/check_env.py` that lists missing required vars at startup and exits non-zero.

## UI (`index.html`)
Add a sign-out item to the existing sidebar/top bar and show the signed-in email in `/api/config`'s response. No other changes; keep all hooks.

## Acceptance
- [ ] Incognito → `/` redirects to Google → sign in with allow-listed account → app loads; non-allow-listed account gets a plain 403 page.
- [ ] `curl /api/courses` without cookie → 401; with a valid session cookie → 200; `Authorization: Bearer …` is not accepted.
- [ ] `AUTH=off` works in docker dev and in `make test`; `ENV=production AUTH=off` refuses to boot.
- [ ] Session survives a server restart (cookie is stateless); logout clears it.
- [ ] `grep -n "ANTHROPIC_API_KEY" static/index.html` returns nothing; `/api/config` no longer exposes `has_key` beyond a boolean.
