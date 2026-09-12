# Phase 1 — SQLite → Postgres (docker locally, Neon in cloud)

Branch: `phase-1-postgres`. One PR. Read `CLAUDE.md` first.

## Objective

Replace the `sqlite3` data layer in `run.py` with Postgres via `psycopg` (v3), keep every endpoint's behaviour identical, and ship a one-shot migration script that moves Matej's real `data/cognitioflow.db` into Postgres without loss. Add the `users` table and `courses.user_id` so later multi-user work needs no schema change.

Nothing in this phase touches `static/index.html`, storage paths, transcription, or auth. Files and audio keep their current filesystem `path` values — Phase 2 changes that.

## What exists today (verified from `run.py`)

- `db()` returns `sqlite3.connect(DATA/"cognitioflow.db")` with `row_factory = sqlite3.Row`.
- `rows(q, *a)` runs a query and returns a list of Row objects; **50 call sites**.
- `with db() as d: d.execute(...)` at **38 call sites**; relies on the sqlite context manager committing on exit.
- `init()` creates 9 tables via one `executescript` and seeds the two courses.
- Placeholders are `?` everywhere.
- Only two SQL-level SQLite-isms: `GROUP_CONCAT(name, ' | ')` (planner auto-plan) and nothing else — the `strftime` hits are Python, not SQL.
- Booleans are stored as `INTEGER` 0/1 (`files.selected`, `sessions.done`); timestamps as `REAL` epoch seconds; `cards.due` is an ISO date **TEXT**.

## Schema (target)

Create `migrations/001_initial.sql` reproducing the 9 tables faithfully, plus:

```sql
CREATE TABLE users(
  id TEXT PRIMARY KEY,           -- uuid hex, same style as other ids
  email TEXT UNIQUE NOT NULL,
  name TEXT DEFAULT '',
  created DOUBLE PRECISION
);
ALTER TABLE courses ADD COLUMN user_id TEXT REFERENCES users(id);
```

Type mapping: `TEXT`→`TEXT`, `INTEGER`→`INTEGER`, `REAL`→`DOUBLE PRECISION`. Keep 0/1 integers for `selected`/`done` (don't convert to BOOLEAN — the UI and 11 call sites compare to `1`/`0`). Keep `cards.due` as TEXT ISO date. Add the obvious indexes: every `course_id`, `note_id`, `card_id` column.

Migrations are plain SQL files applied in order by `python -m migrate` (a ~40-line runner with a `schema_migrations(version)` table). No Alembic.

## Code changes in `run.py`

1. Replace `sqlite3` import with `psycopg` (`psycopg[binary,pool]`). Add a module-level `ConnectionPool(os.environ["DATABASE_URL"])`.
2. `db()` returns a pooled connection context whose `__exit__` commits on success and rolls back on exception, matching today's semantics. Rows come back as dicts (`row_factory=dict_row`) so `r["col"]` keeps working.
3. `rows(q, *a)` unchanged in signature; internally converts `?` → `%s` **at call time** with a small helper so the 50 call sites don't have to be rewritten by hand (a regex replace on `?` outside quotes is fine — there are no `?` characters inside string literals in the SQL; verify with grep before relying on it). Alternative if you prefer explicitness: sed the 88 SQL strings to `%s` in one commit. Either is acceptable; pick one and be consistent.
4. `init()` no longer creates tables; it runs the migration runner then seeds the two courses if the table is empty (same as now). Seeding the Property Law prompt from `prompts/property_law.md` stays.
5. `GROUP_CONCAT(name, ' | ')` → `string_agg(name, ' | ' ORDER BY name)`.
6. `d.execute(...).fetchone()[0]` patterns: with dict rows, `[0]` on a dict fails. There are a handful (grep `fetchone()[0]`); change to `fetchone()["col"]` or use `tuple_row` for that query.
7. `.env` loading: `DATABASE_URL` is required; fail loudly at startup if missing. Default in `.env.local.example` points at docker.

## Two latent bugs to fix while you're here (they break outright on Postgres)

- **Planner auto-plan compares `cards.due` (ISO TEXT) to `time.time()` (float).** In SQLite this silently compares a REAL to TEXT and always yields 0 due cards; in Postgres it's a type error. Fix: pass `date.today().isoformat()` like the Recall screen does (`cards()` endpoint, line ~390). Add a test.
- **`ALTER TABLE cards ADD COLUMN week` in `init()`** is a SQLite-era in-place patch. Delete it; the column is in `001_initial.sql`.

## Migration script — `migrate_sqlite.py`

`python migrate_sqlite.py --sqlite ~/Desktop/cognitioflow/data/cognitioflow.db --dry-run` then without `--dry-run`.

- Reads all 9 tables from SQLite in FK-safe order: courses → files, messages, notes, cards, sessions → note_versions, recordings, reviews.
- Creates one row in `users` for `MATEJ_EMAIL` (env var) and sets `courses.user_id` to it.
- Inserts with `INSERT ... ON CONFLICT (id) DO NOTHING` so the script is idempotent and safe to re-run.
- Prints a per-table count from source and destination and **exits non-zero if any differ**.
- Never modifies the SQLite file. Never copies files/audio (Phase 2).

## Dev environment (deliverables in this PR)

- `docker-compose.yml` (provided) and `.env.local.example` (provided).
- `Makefile` with `dev`, `test`, `migrate`, `db-reset` targets. `dev` = `uvicorn run:app --reload --env-file .env.local`.
- `requirements.txt`: remove nothing yet; add `psycopg[binary,pool]`, `pytest`, `httpx`.
- `tests/`: pytest with a fixture that creates a throwaway schema in the docker DB per test session (or `TRUNCATE ... CASCADE` per test), then:
  - every table is created and migrations are idempotent (run twice);
  - `init()` seeds exactly two courses on an empty DB and zero on a populated one;
  - smoke tests via `httpx.AsyncClient` on: create file record, list files by week, create/rate a card (SM-2 fields update, `due` is ISO), list due cards, create/edit note + version history, sessions CRUD, planner auto-plan runs without a model call (mock `client()`);
  - `migrate_sqlite.py --dry-run` against a small fixture `.db` reports matching counts.

## Neon

- Create the Neon project (EU region), database `cognitioflow`. Put the **pooled** connection string in `.env.local` as `DATABASE_URL` to test against it once docker passes. Never commit it.
- Add `make db-branch NAME=...` that calls `neonctl branches create --name $(NAME)` and prints the branch's connection string. Document in the README that PRs may be tested against a branch of prod.
- Do **not** run `migrate_sqlite.py` against Neon prod in this phase — cutover is Phase 7. Running it against a Neon branch to prove the script is encouraged.

## Acceptance checklist (paste results in the PR)

- [ ] `docker compose up -d && make migrate && make dev` → app boots, http://localhost:8000 loads, all seven screens render with no console errors.
- [ ] `make test` green.
- [ ] `grep -n "sqlite3" run.py` returns nothing. `grep -n "?" run.py` inside SQL strings returns nothing (or the converter is unit-tested).
- [ ] `migrate_sqlite.py --dry-run` on the real `.db` (Matej runs this; paste the count table) shows equal source/destination counts for all 9 tables.
- [ ] Recall screen shows the same due count as before migration; Planner auto-plan no longer reports 0 due cards when cards are due.
- [ ] `static/index.html` diff is empty.
- [ ] Same test suite passes with `DATABASE_URL` pointing at a Neon branch.

## Out of scope (do not do)

Storage backend, GCS, `jobs` table, transcription interface, auth, Dockerfile, Cloud Run, UI changes, new endpoints for courses. Each has its own phase.
