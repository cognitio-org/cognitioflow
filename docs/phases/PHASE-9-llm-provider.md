# Phase 9 — LLM provider seam: Anthropic direct or OpenRouter

Branch: `phase-9-llm-provider`. Depends on Phase 1 (everything lives in `run.py`); the cloud secret needs Phase 5's Secret Manager wiring but the phase runs locally without it.

## Decisions — settled (2026-09-13)
- **The switch is environment-wide:** `LLM_PROVIDER=anthropic|openrouter`, default `anthropic`. One key, one bill, one cache namespace at a time. No per-message provider picker.
- **Cheap tier on OpenRouter is DeepSeek V4.1 Flash** (`deepseek/deepseek-v4.1-flash`: $0.15 / $0.60 per M, images, 1M context — about 7× under Haiku) from day one. `CF_CHEAP_MODEL` defaults to it when `LLM_PROVIDER=openrouter`; Haiku stays the default on `anthropic`. House style (provenance tags, mermaid, the "In one glance" box) is checked in acceptance, not assumed. Note: Anthropic `cache_control` markers are dropped for non-Anthropic providers; DeepSeek has its own automatic caching (reads at ~0.1× input), so the notes-mode chat still benefits, just without the explicit breakpoint.
- **No privacy restriction on routing:** requests do not set `provider.data_collection`; OpenRouter's default (widest routing, lowest price) applies. **[Matej]** may still tighten the account-level "providers that may train" setting in the OpenRouter console at any time without a code change.
- **Usage is recorded in the database** (`llm_usage`, migration `007`) and this month's spend shows in the existing `#costState` slot.
- **Credits, not BYOK.** Pay OpenRouter by card top-up (5.5% fee, $0.80 minimum). One console.
- **Main tier moves to Sonnet 5 now:** `CF_MODEL=claude-sonnet-5` ($2 / $10 instead of $3 / $15). Applied to `.env.local` on 2026-09-13; this phase updates `.env.local.example`, the guide's model block and the cloud env to match. `CF_STRONG_MODEL` follows `CF_MODEL` as before.

## Objective
Every model call in `run.py` goes through one seam, `llm.py`, and the environment picks the backend: the Anthropic API exactly as today, or OpenRouter — which speaks the same Anthropic Messages protocol, exposes 445 models under one key, and returns the cost of each call. Auto-routing rules, prompts, caching order and the Fable rule do not change. The app reports what each call cost, whichever backend served it.

## What the research found

### How the app uses the model today (11 call sites, all `client().messages.*`)
| Task | Where | Tier | Streams | `max_tokens` | System prompt | Cache |
|---|---|---|---|---|---|---|
| Tutor chat (drill / explain / notes) | `chat` | `pick_model(mode, requested, text)` | yes, SSE | 2000 | array; files block has `cache_control` | yes |
| Reconcile with lecture | `reconcile_note` | `STRONG_MODEL` | no | 8000 | string | no |
| Continue a cut-off note | `continue_note` | strong or notes | no | 8000 / 4000 | string | no |
| Draft notes from files | `draft_notes` | `pick_model("notes")` | no | 4000 | string | no |
| Cards from a file | `generate_cards` | `pick_model("cards", g.model)` | no | 3000 | none | no |
| Quiz distractors | `quiz` | `CHEAP_MODEL` | no | 3000 | none | no |
| Clean garble (per 70 lines) | `clean_text` | `CHEAP_MODEL` | no | 4000 | string | no |
| Tag files with weeks | `tag_weeks` | `CHEAP_MODEL` | no | 1000 | none | no |
| Study plan | `auto_plan` | `pick_model("summarise")` | no | 2000 | string | no |

What the code relies on from the response: `m.content[].type == "text"` / `.text`, `m.stop_reason == "max_tokens"` (the Continue marker), `m.model` (echoed to the UI), and `stream.text_stream`. Images go in as base64 `image` blocks (chat only). JSON replies are parsed tolerantly by `_model_json`. Only chat uses prompt caching; the cached files block sits after the rules block and before the mode text, and that order must stay.

Config surface: `CF_MODEL`, `CF_CHEAP_MODEL`, `CF_STRONG_MODEL`, the hard-coded `MODELS` allow-list (five Claude ids), `/api/config`, and `check_env.py` requiring `ANTHROPIC_API_KEY` in production. The UI builds the model dropdown from `cfg.models`, strips `claude-` for display, mirrors the routing rule in `routeGuess()`, and titles `#dot` "Claude connected". Tests replace `run.client` with `FakeClient` (has `.messages.create` only — no streaming fake yet).

**Gap found:** `static/index.html` already parses a `usage` SSE event (`cost`, `cache_read`, `in`, `out`) into `#costState` and the per-reply tooltip, but `run.py` has never emitted one — the readout is dead. This phase feeds it.

### OpenRouter facts (verified 2026-09-12)
- **`POST https://openrouter.ai/api/v1/messages` is an Anthropic Messages endpoint.** Probed from this machine: it answers in Anthropic's error format. Accepts `system` as an array with `cache_control`, base64 `image` blocks, `stream`, `max_tokens`, `thinking`, `tools`; returns `content` blocks, `stop_reason` incl. `max_tokens`, `model`, and `usage` with `cache_read_input_tokens`, `cache_creation_input_tokens`, plus `cost` (USD) and `provider`. Streaming uses the same event types. [reference](https://openrouter.ai/docs/api/api-reference/anthropic-messages/create-a-message.md)
- **So the installed SDK can be pointed at it:** `anthropic.Anthropic(base_url="https://openrouter.ai/api", auth_token=OPENROUTER_API_KEY)` — the SDK appends `/v1/messages`; `auth_token` sends `Authorization: Bearer`. Verified the constructor takes `auth_token`, `base_url`, `default_headers` in the installed `anthropic` 0.75.0. This is the same recipe OpenRouter documents for Claude Code. [cookbook](https://openrouter.ai/docs/cookbook/coding-agents/claude-code-integration)
- **Non-Anthropic models work on the same endpoint** (`google/gemini-*`, `openai/gpt-*`, `deepseek/*`); OpenRouter translates. `cache_control` markers pass through unchanged to Anthropic-compatible providers and are converted or dropped elsewhere. [prompt caching](https://openrouter.ai/docs/guides/best-practices/prompt-caching)
- **OpenRouter-only body fields:** `models` (fallback list, max 3, billed for the model that ran), `provider` preferences (`sort`, `order`, `only`, `ignore`, `allow_fallbacks`, `data_collection`, `zdr`, `max_price`), `plugins`. With the SDK these go in `extra_body=`. [model routing](https://openrouter.ai/blog/insights/model-routing/) · [provider routing](https://openrouter.ai/docs/features/provider-routing)
- **Model ids use dots:** `anthropic/claude-sonnet-4.6`, `anthropic/claude-haiku-4.5`, `anthropic/claude-sonnet-5`, `anthropic/claude-opus-5`, `anthropic/claude-fable-5.1`.
- **Pricing is pass-through of list price** — Haiku 4.5 $1 / $5, Sonnet 4.6 $3 / $15, Sonnet 5 $2 / $10, Opus 5 $5 / $25, Fable 5.1 $10 / $50 per M tokens, cache reads at 0.1× input. No per-request markup; 5.5% when buying credits by card. **Routing Claude through OpenRouter therefore saves nothing; it costs about 5% more and adds a hop.** The savings are in swapping the cheap tier. [faq](https://openrouter.ai/docs/faq)
- **Usage is always in the response** (no opt-in needed any more); on streams it arrives in the final chunk. [usage accounting](https://openrouter.ai/docs/use-cases/usage-accounting)
- **`openrouter/auto`** picks by community spend per task type and can land on any model — including Fable-class. It is not a tier value the app may use (CLAUDE.md: auto-routing must never select Fable). The app's own `ROUTE` table stays the router.
- Prompts are not logged by default; per-provider retention policies apply; the account setting "allow providers that may train on your data" should be off **[Matej]**.

### Where the money goes (estimates from the code's own budgets, tokens ≈ chars ÷ 4)
| Task | Input | Output | Haiku | Sonnet 4.6 | Gemini 3.1 Flash Lite |
|---|---|---|---|---|---|
| Drill turn, 45k-token files block cached | 45k cached + ~1k new | ~1k | — | ~$0.03 | — |
| Draft notes (full budget) | ~45k | ~4k | ~$0.065 | ~$0.20 | ~$0.017 |
| Reconcile (Sonnet as strong) | ~25k | ~8k | — | ~$0.20 | — |
| Cards from one file | ~15k | ~2k | ~$0.025 | — | ~$0.007 |
| Clean garble, 90-min transcript (~10 chunks) | ~15k | ~15k | ~$0.09 | — | ~$0.026 |

Reading: the cheap tier is where the bulk tokens are (drafts, garble, cards); a Flash-class model cuts those calls ~4×. The main tier's cost is mostly Sonnet output tokens on drills and reconciles, which OpenRouter does not touch — Sonnet 5 does.

## Part A — `llm.py`, the fourth seam
- `llm.py` exposes `client()`, `resolve(model_id) -> str`, `usage(m, task) -> dict`, `PROVIDER`, `catalogue()`. `run.py` imports only these; it never imports `anthropic` and never reads `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY` itself (`config`, `check_env` and the startup banner ask `llm`).
- `LLM_PROVIDER=anthropic` (default): `client()` returns `anthropic.Anthropic()` — today's behaviour, byte for byte. `resolve` is the identity.
- `LLM_PROVIDER=openrouter`: `client()` returns `anthropic.Anthropic(base_url="https://openrouter.ai/api", auth_token=os.environ["OPENROUTER_API_KEY"], default_headers={"HTTP-Referer": "https://github.com/cognitio-org/cognitioflow", "X-OpenRouter-Title": "CognitioFlow"})`. `resolve` maps a Claude id without a slash to OpenRouter's spelling (`claude-sonnet-4-6 → anthropic/claude-sonnet-4.6`, `claude-sonnet-5 → anthropic/claude-sonnet-5`) so the same `.env` works for both backends; ids with a slash pass through. No OpenRouter-specific body fields are sent in v1 (no `provider` preferences, no `models` fallback list).
- Every `client().messages.create/stream(model=X, ...)` in `run.py` becomes `model=llm.resolve(X)`; a tiny wrapper around `create`/`stream` records usage (Part B) so the call sites stay one-liners. No other change to prompts, `max_tokens`, system arrays, `cache_control` placement or history.
- Tier defaults: on `openrouter`, `CF_CHEAP_MODEL` defaults to `deepseek/deepseek-v4.1-flash` and `CF_MODEL` to `claude-sonnet-5` (resolved); on `anthropic` the defaults are `claude-haiku-4-5` and `claude-sonnet-5`. `MODELS` becomes `llm.catalogue()`: the five Claude ids on `anthropic`; on `openrouter` the same five (resolved) plus `CF_EXTRA_MODELS` (comma-separated ids, default `deepseek/deepseek-v4.1-flash,google/gemini-3.8-flash,google/gemini-3.1-flash-lite`). `pick_model` keeps its allow-list check against the catalogue, so a client cannot request an arbitrary id. `openrouter/*` router ids are refused everywhere (catalogue, tiers, requested) — `check_env` fails the boot if a tier is set to one.
- `/api/config` adds `provider` and returns `models` as `[{id, label}]` (label = id without the vendor prefix and `claude-`); `has_key` reflects the active provider's key.
- `check_env.py`: in production require `OPENROUTER_API_KEY` when `LLM_PROVIDER=openrouter`, else `ANTHROPIC_API_KEY`; refuse an unknown provider value.
- `.env.local.example`: `LLM_PROVIDER`, `OPENROUTER_API_KEY`, `CF_EXTRA_MODELS` documented next to the model block. Phase 5's `infra/setup.sh` and deploy workflow gain an optional sixth secret `OPENROUTER_API_KEY` and the `LLM_PROVIDER` env var; the cloud default stays `anthropic` until Matej flips it.
- `CLAUDE.md`: the "Three seams" section gains a fourth entry for `llm.py` (`client() / resolve() / usage()`; `run.py` never imports `anthropic`), and the model-and-cost rules note that tier ids may be OpenRouter ids but never `openrouter/*` routers.
- Fallback chains (`models: [...]`) are deliberately not wired in v1: the SDK's own retries stay, and a silent fallback to a different model would break the cost readout's honesty. Listed under Later.

## Part B — usage and cost, one shape for both backends
- `llm.usage(m, task)` normalises a response (or a stream's `get_final_message()`) to `{provider, model, task, in, cache_read, cache_write, out, cost}`. On OpenRouter `cost` is `usage.cost` from the response; on Anthropic it is computed from a `PRICES` table in `llm.py` (USD per M: in / cache read / cache write / out, for the five Claude ids; an unknown id gives `cost: null`, never a guess).
- Migration `007_llm_usage.sql`: `llm_usage(id, created, course_id, task, provider, model, input_tokens, cache_read, cache_write, output_tokens, cost_usd)` with an index on `created`. One row per model call, written by the wrapper in Part A. This is the only schema change.
- `GET /api/usage?days=30` → `{total, by_model: [...], by_task: [...]}` for the signed-in user's courses.
- Chat's SSE stream emits `{"usage": {...}}` after the last text delta and before `[DONE]` — the event `index.html` already parses. Non-streaming endpoints (`reconcile`, `draft`, `continue`, `cards`, `quiz`, `plan`) add `usage` to their JSON next to the `model` they already return.

## Part C — UI (only what the brief allows; every `id` and `data-` hook stays)
- `#costState` shows `$X.XX this month` from `/api/usage` (loaded with `/config`, refreshed after each call), title = per-model breakdown. The `cf.cost` localStorage counter is removed (CLAUDE.md: no app state in localStorage). Click no longer resets anything.
- `#modelSel` renders `label` from the new `models` shape; `routeGuess()` and `#tutorSub` use labels too. `#dot` title reads `Connected via OpenRouter · auto haiku-4.5 / sonnet-4.6` or `Claude connected · …` depending on `cfg.provider`.
- Result toasts for reconcile / draft / cards / quiz append `· $0.19 · sonnet-4.6` from the returned `usage`.
- No new colours, no new tokens, sentence case. Light + dark screenshots at 1440 and 1190 px in the PR.

## Tests (`tests/test_llm.py` + additions)
- Provider selection from env; `resolve` for all five Claude ids and pass-through for slashed ids; the request body carries no `provider` or `models` field on either backend; `openrouter/auto` rejected in tiers, catalogue and per-request `model`.
- `usage()` from an Anthropic-shaped response (cost computed) and an OpenRouter-shaped one (`cost` taken from the response); unknown model → `cost: null`.
- `check_env`: production with `LLM_PROVIDER=openrouter` and no `OPENROUTER_API_KEY` is fatal; the Anthropic path is unchanged.
- `FakeClient` gains `.messages.stream()` (context manager with `text_stream` and `get_final_message()`); a chat test asserts the SSE order `model → t… → usage → [DONE]` and one `llm_usage` row.
- `/api/config` shape; `/api/usage` totals over seeded rows.
- No test calls a real backend. No user content is fabricated against Neon.

## Acceptance
- [ ] `LLM_PROVIDER` unset or `anthropic`: every existing test passes unchanged; a drill turn's request body (SDK debug log) is identical to `main` apart from nothing.
- [ ] `LLM_PROVIDER=openrouter` with a real key: drill, explain, reconcile and continue complete on Sonnet 5 via OpenRouter; draft, cards, quiz, clean garble, tag weeks and plan complete on DeepSeek V4.1 Flash with the same output format; `#costState` shows spend; each reply's tooltip shows cost and cached tokens.
- [ ] Second drill turn on OpenRouter reports `cache_read > 0` in its usage (the files block is cached across the hop).
- [ ] A draft on `deepseek/deepseek-v4.1-flash` with `DRAFT_TOKENS` temporarily set to 300 produces a `<!--cf:continue …-->` marker and Continue finishes it (`stop_reason` is mapped).
- [ ] Cards and quiz on DeepSeek V4.1 Flash yield at least as many usable items as Haiku on the same file; a week's draft on it keeps the house style (In one glance box, provenance tag on every substantive line, a mermaid decision tree, `## Gaps / verify`) — **[Matej]** signs this off from the rendered note.
- [ ] Clean garble on DeepSeek V4.1 Flash keeps every line, `[mm:ss]` timestamp and `<!--…-->` marker on the 90-minute fixture (the existing line-count guard must not reject chunks).
- [ ] Cost readout on `anthropic` matches Anthropic's console for a day within 5%; on `openrouter` matches the OpenRouter activity page.
- [ ] `openrouter/auto` as `CF_CHEAP_MODEL` refuses to boot with a clear message; Fable is still reachable only from the dropdown and `CF_STRONG_MODEL`.
- [ ] `docker build` + `make test` green; migration `007` applies on a fresh database and on one that already has `006`.

## How to see it
```
LLM_PROVIDER=openrouter OPENROUTER_API_KEY=sk-or-… make dev      # then open http://localhost:8000
```
Tutor → ask one drill question → hover the reply: `answered by haiku-4.5 · $0.0041 · 44.9k cached, 0.2k new, 312 out`. Pick `deepseek-v4.1-flash` in the dropdown, ask again, compare the two tooltips. Notes → Draft from files on each → compare `$` in the toast. `#costState` totals the session. Switch `LLM_PROVIDER` back and restart: nothing else changes.

## Later (not this phase)
- Fallback chains via `models: [...]` for the cheap tier when a non-Anthropic model is down.
- Per-task tiers beyond the current three (`CF_CARDS_MODEL`, …) if the A/B shows different cheap models suit different tasks.
- Batch variants (`:batch`, 50% off) for overnight jobs such as cleaning a whole term's transcripts — needs a jobs-table job type, so it belongs with a transcription phase.
- Effort / thinking controls on the strong tier for reconcile.
