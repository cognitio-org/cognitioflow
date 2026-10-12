# Phase 19 — the flywheel: cloud-path capture + the edit signal, and CF's cloud tier via Kernal

Branch: `phase-19-flywheel-capture`. Depends on Phase 18 (#151): the `card_gen_samples` capture table,
`cards.gen_sample_id`, the OpenAI-compatible bridge in `llm.py`, and `gateway.minimise`.

**Why.** Get CF's real training data flowing properly. As Matej uses CF, we must log the signal that
will later train a cards specialist that genuinely beats base. The last experiment failed only because
the data lacked this signal — specifically the *correction* signal (what Matej changes), which is what
teaches his taste. Phase 18 captured generation only on the self-hosted path; this captures every
generation and, above all, the edits.

## What is captured and where

1. **Cloud-path capture (Matej decision b).** `card_gen_samples` now logs **every** card generation —
   cloud AND the self-hosted path — not only the grounded local path. Each row keeps the de-identified
   source passage, the generated cards, the provider/model, and whether the grounded prompt was used
   (`grounded`). Every generated card still ties back through `cards.gen_sample_id`. Capture is
   best-effort (`run.py:_capture_card_sample`): a logging failure never fails or slows generation.

2. **The edit signal — THE GOLD (`card_edits`, migration 027).** When Matej edits a card the AI
   generated (`cards.gen_sample_id` set) and the front/back actually change, the pair
   **(the AI's card → Matej's edited card)** is recorded: `front_before/back_before` (on the first edit
   of a freshly generated card, that is the AI original) and `front_after/back_after`, linked to the
   generation through `gen_sample_id` and to the card through `card_id`. This is the correction /
   preference signal a LoRA actually learns from. Best-effort (`run.py:_capture_card_edit`).

   There was **no edit route** before (the "All cards" table only had Remove). This phase adds a minimal
   one: `PUT /api/cards/{id}` (`run.py:edit_card`) updates front/back/week/source and hooks the
   before/after there, and an **Edit** button in the "All cards" table (`static/app.js:renderAll`, new
   `data-editcard` hook; `data-delcard` and every other hook preserved; no `index.html` change, no CSS).

3. **Review ratings linked (`reviews.gen_sample_id`, migration 027).** Each FSRS rating of an
   AI-generated card carries the `gen_sample_id` of the card it rated (`run.py:review`), a lighter
   quality signal joined to the same interaction. NULL for manually written cards.

Everything is **de-identified** through the existing `gateway.minimise` (emails, IBANs, student numbers,
phone numbers → placeholders) before anything is written — on the cloud path and the edit path too. No
name, account or identity is kept. The flywheel is on by default and can be switched off without a
deploy: `CF_CARD_CAPTURE=off` (privacy by default, Art. 25).

## CF's cloud tier via Kernal (`llm.py`)

The direct `OPENROUTER_KEY` is dead. `LLM_PROVIDER=kernal` points the **whole cloud tier** at Matej's
own OpenAI-compatible LiteLLM router (`https://router.kernal.one/v1`), reusing the Phase-18 bridge
(`_to_openai_messages` / `_LocalMessage` / `_LocalUsage`):

- A `_KernalClient` exposes exactly the slice of the anthropic SDK `run.py` uses —
  `client().messages.create(...)` (non-streaming, for the bulk/main calls) and
  `client().messages.stream(...)` (a small stdlib SSE reader, for the one streaming call: tutor chat via
  `llm.hedged_stream`). `run.py` needs no change.
- Defaults on the Kernal path: `CF_CHEAP_MODEL=gemini-2.5-flash`, `CF_MODEL=claude-sonnet-5`. Model ids
  pass through as-is (`resolve`), both tiers are offered by the picker (`catalogue`), and routers / Fable
  / Opus are refused as everywhere.
- Cost: `usage()` labels the call `provider=kernal` and computes the `PRICES` cost when the model is
  priced (Sonnet), or reports unknown rather than guessing (e.g. `gemini-2.5-flash`).
- The key is read from the environment (`KERNAL_API_KEY`); `.env.local` loads it from
  `~/.config/swarm/kernal_router_key`.

**Default behaviour is unchanged unless the env selects Kernal.** `anthropic` (default), `openrouter`
and `gateway` are byte-for-byte as before.

## How to see it

```
make dev
# 1) Generate cards in the app (Recall → Generate from a week's note/file). On any provider, one
#    card_gen_samples row is written, de-identified, with each card tied back via cards.gen_sample_id.
# 2) Open "All cards", click Edit on an AI-generated card, change the wording, save.
# 3) The (AI card -> edited card) pair has landed in card_edits:

psql "$DATABASE_URL" -c "
  SELECT e.front_before, e.front_after, e.gen_sample_id
  FROM card_edits e ORDER BY e.at DESC LIMIT 5;"

# the generation it came from:
psql "$DATABASE_URL" -c "
  SELECT provider, model, grounded, made, left(source_text,60) AS source
  FROM card_gen_samples ORDER BY at DESC LIMIT 5;"

# review ratings of AI cards, tied back to their generation:
psql "$DATABASE_URL" -c "
  SELECT card_id, rating, gen_sample_id FROM reviews
  WHERE gen_sample_id IS NOT NULL ORDER BY created DESC LIMIT 5;"
```

To route the cloud tier through Kernal:
```
export LLM_PROVIDER=kernal
export KERNAL_API_KEY="$(cat ~/.config/swarm/kernal_router_key)"
export CF_MODEL=claude-sonnet-5 CF_CHEAP_MODEL=gemini-2.5-flash
make dev
```

No visual redesign (one additive Edit button reusing existing button styling), so no light/dark
screenshot pass is required.

## Tests

- `tests/test_flywheel.py` (docker Postgres): editing an AI card records the de-identified
  (before → after) pair; a no-op edit and a manual-card edit record nothing; a review of an AI card
  carries its `gen_sample_id`, a manual card's does not.
- `tests/test_card_capture.py`: the cloud path now also captures (grounded False), identity stripped,
  response shape unchanged; `CF_CARD_CAPTURE=off` disables it; the local grounded path is as Phase 18.
- `tests/test_llm_kernal.py` (no endpoint, urllib patched): defaults, resolve pass-through, the
  catalogue (both tiers, no router/Fable), the non-streaming bridge (body + Anthropic shape + provider
  `kernal` + PRICES cost / honest unknown), the SSE streaming reader, and that `hedged_stream` works
  over the shim.

## Acceptance

- [x] Every card generation (cloud and local) writes one de-identified `card_gen_samples` row; each
  card ties back via `cards.gen_sample_id`; the cloud response shape is unchanged.
- [x] Editing an AI-generated card records the (AI card → edited card) pair in `card_edits`,
  de-identified and linked by `gen_sample_id`; no-op and manual edits record nothing.
- [x] FSRS ratings of AI cards carry `gen_sample_id`.
- [x] `LLM_PROVIDER=kernal` routes the cloud tier (create + stream) through the OpenAI-compatible
  router; defaults `claude-sonnet-5` / `gemini-2.5-flash`; the other providers are unchanged and
  default-off.
- [x] `CF_CARD_CAPTURE=off` switches the flywheel off without a deploy.
- [x] Migration `027` applies on a fresh DB and on one already at `026`; full suite green.

## Later (not this phase)

- Train the cards specialist (LoRA) from `card_gen_samples` + `card_edits` (the frozen-gold gate, the
  LLaMA-Factory harness) — deferred per the Phase-18 "Later" and the build queue.
- A richer edit UI (inline editing rather than `prompt()`), if the table grows.
- Kernal cost from the router's own response/headers if it returns one, instead of the PRICES table.
