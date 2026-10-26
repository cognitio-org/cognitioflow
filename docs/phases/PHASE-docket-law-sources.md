# Phase — docket games grounded in the shared EU-law / CJEU knowledge

## What was asked
Games should be able to cite the full EU-law corpus and CJEU case law from the shared knowledge RAG, not only the
week's course files — while keeping the hard guarantee that every citation is backed by a real source.

## What was built
Optional, graceful augmentation of a game's sources with real law, inside `_docket_write`:

- **`_law_sources(files)`** — queries the shared-knowledge RAG (`GET {CF_RAG_URL}/api/rag/ask`, corpora
  `law:eu:3,6,2`) with the course's **exam language** as the query, and returns the top passages as extra sources
  (`kind="law"`, authority tier `cases`, so course files always lead). **Off unless `CF_RAG_URL` is set**, and it
  returns `[]` on any error or timeout — so a game always writes from the course files alone when the knowledge
  service is unreachable (it is, on Cloud Run; the writer runs on the Mac, where the fleet RAG is reachable).
- **Grounding preserved and extended.** The retrieved passages are appended to the writer's SOURCES *and* to the
  `citecheck` verification corpus, so a citation to real EU law verifies instead of being flagged "not in your
  files." The integrity guarantee is unchanged: a citation with no backing source still fails. A test proves both
  directions — the same `Article 107 TFEU` citation passes with the law source present and fails without it.
- **Writer nudge** only when law is present: a one-line note on the per-call `ask` (not the house WRITER prompt)
  saying the `kind="law"` sources are EU legislation / CJEU case law, to use after the course files.

## Config
- `CF_RAG_URL` — shared-knowledge RAG base, e.g. `http://127.0.0.1:8100`. Empty (default) disables the feature.
- `CF_RAG_LAW_CORPORA` — corpora to pull, default `law:eu:3,law:eu:6,law:eu:2`.

## Deliberately not built
- No new dependency (stdlib `urllib`), no account, nothing sent off the local fleet; the query is the local course's
  own exam text, to a local service.
- No change to the shared RAG itself (built in newsglobe); this is only the CF consumer side.

## Acceptance checklist
- [ ] `tests/test_docket_drafts.py` — `_law_sources` off by default / parses hits / degrades on error; a game cites
      shared law only because the passage joins the citecheck corpus (and fails without it).
- [ ] Existing docket, scope and selection tests still pass; full suite green.
- [ ] Prod unchanged until `CF_RAG_URL` is set (feature is dark by default).
