# Phase 18 — self-hosted local generation for the cheap tier (cards)

Branch: `phase-18-selfhosted-generation`. Depends on Phase 9 (the `llm.py` model seam) and Phase 10
(course-materials-supreme retrieval / the local embedder). This is **Phase A — a proof of concept**:
the cheap/bulk tier can run on a self-hosted model, starting with card generation only.

## Decisions — settled
Settled in `~/reports/cf-phaseA-decisions.md` (follow it; do not re-decide). The essentials:

- **Why.** Privacy (student text never leaves our servers) + owning/fine-tuning the model + the RUG
  pitch. **Not cost** — the Phase-9 cheap tier (DeepSeek Flash) is already near-free. So accuracy,
  grounding and the seam matter more than speed.
- **Routing is per-tier, not env-wide.** A new `CF_LOCAL_BASE_URL` (+ `CF_LOCAL_MODEL`) points the
  **cheap/bulk tier** at a local OpenAI-compatible endpoint (Ollama). The MAIN tier (tutor chat,
  reconcile, continue, grading) and all streaming stay on the existing cloud provider, untouched.
- **Default OFF.** With `CF_LOCAL_BASE_URL` unset, behaviour is **byte for byte today's** — the cheap
  tier stays DeepSeek/Haiku/gateway exactly as Phase 9 left it.
- **The bridge lives in the seam** (`llm.py`). It still speaks Anthropic-Messages to `run.py`; for the
  local tier it translates to the endpoint's OpenAI chat-completions format and the response back
  (text, model, usage). **Only the non-streaming path is bridged** — the bulk tasks don't stream, and
  the one streaming call (tutor chat) is main tier and stays cloud. Kept small.
- **Base model = Qwen2.5-7B-Instruct (Apache-2.0)**, served by the Mac's Ollama at
  `http://127.0.0.1:11434/v1` in dev mode (a): `make dev` → Mac Ollama.
- **Start with `generate_cards` only.** Other bulk tasks (`clean_text`, `tag_weeks`, quiz distractors)
  flip to local later, each on its own, once it clears the eval bar.
- **Accuracy is gated.** Local card generation is grounded strictly in the course's ticked material
  (the content `generate_cards` already feeds the model) and told to ABSTAIN/flag when the source is
  thin, rather than invent law. A task flips to local only if it meets the bar.
- **De-identified capture now, training later.** Each local card interaction is logged with identity
  and personal content stripped — only the system interaction + the feedback hook are kept — so data
  accrues for a future specialist. Additive migration.
- **Cost readout stays honest.** Local calls record in `ai_calls` with `provider=local`, cost `0`
  (own hardware); the Phase-9 spend readout keeps working.

## Objective
The cheap tier can run a named bulk task (cards first) on a self-hosted model, grounded in the ticked
files and eval-gated, selected entirely by the environment. The MAIN tier and the UI are unchanged, and
with the new env unset nothing changes at all.

## Part A — the local tier in `llm.py`
- `CF_LOCAL_BASE_URL` (unset → off), `CF_LOCAL_MODEL` (default `qwen2.5:7b-instruct`), `CF_LOCAL_TASKS`
  (default `cards`), `CF_LOCAL_TIMEOUT` (default 300 s).
- `local_enabled()` — true only when a base URL is named. `local_allows(task)` — true when enabled and
  the task is on the allow-list.
- `local_create(system, messages, max_tokens, …)` — one non-streaming POST to `{base}/chat/completions`
  (stdlib `urllib`, so the seam gains no dependency). Anthropic `system`+`messages` → OpenAI chat
  messages (a system block becomes a leading system message; text content is flattened; non-text blocks
  are dropped — the local tier serves text-only bulk tasks). The reply is dressed back in the Anthropic
  shape `run.py` reads: `content[].text`, `model`, `stop_reason` (`length`→`max_tokens`, so the Continue
  marker still works), and `usage` with `provider="local"`, `cost=0`.
- `local_call(task, **kw)` — `ask_model`'s hook. Returns the local result for an allowed task, or
  `None` to fall back to the configured cloud/gateway tier. Mirrors `gateway.call`'s contract: any
  trouble (endpoint down, empty answer) is a silent fall-back, so the job still gets done.
- `describe()` gains a `local` block (enabled / model / tasks) for the banner. The local tier is a
  routing override on the cheap tier, **not** a catalogue entry — the dropdown is unchanged.

## Part B — `run.py`: routing and grounding
- `ask_model` tries `llm.local_call(task, …)` before the gateway lane, but only for a cheap-tier named
  bulk task. Order: local → gateway → cloud. Default-off keeps this inert.
- `generate_cards`: the call routes local when `llm.local_allows("cards")` and the chosen model is the
  cheap tier (an explicit dropdown pick still goes cloud). On the local path only, a grounding system
  prompt (`CARD_GROUNDING_RULES`) is sent: use only the material, never invent/"recall" law, one
  testable point per card, write FEWER cards when the source is thin. The cloud cheap tier keeps its
  exact Phase-9 prompt, so with the env unset the prompt is identical.
- `thin` = source under `CF_CARD_MIN_SOURCE_CHARS` (default 400). On the local path the response adds
  `grounded`/`thin`; the default path returns `{"made": n}` byte for byte.

## Part C — de-identified capture (migration 026)
- `026_card_capture.sql`: `card_gen_samples` (the interaction — source material and the cards it
  produced) and an additive `cards.gen_sample_id` column (the feedback hook).
- Capture runs only on the local/grounded path, best-effort (a capture failure never fails the call).
  Source text and cards are passed through the same pseudonymisation the privacy gateway uses
  (`gateway.minimise`: emails, IBANs, student numbers, phone numbers → placeholders) before being
  written. No name, account or identity is kept.
- The later feedback signal (card edits, FSRS ratings) is joined through `cards.gen_sample_id` — not
  copied — so no new write path on the edit/review endpoints.

## Part D — the eval harness (`scripts/eval_local_cards.py`)
- Generates cards from a few short **public** EU-law passages with the local model (grounded) and, with
  `--cloud` and a provider key, the cloud cheap tier (its exact prompt). Scores two axes:
  **faithfulness** (every legal reference on a card — article, case name, ECJ case number, directive —
  must appear in the source passage; a reference the source lacks is invented) and **usefulness**
  (well-formed, specific, non-duplicate Q/A). Goes through the seam; imports no model SDK; no DB.
- Deliberately tiny so it runs on a laptop. A fuller eval is in **Later**.

## How to see it
```
make dev
export CF_LOCAL_BASE_URL=http://127.0.0.1:11434/v1
export CF_LOCAL_MODEL=qwen2.5:7b-instruct      # ollama pull qwen2.5:7b-instruct if missing
# Generate cards in the app (Cards → Generate on a week's note/file): they are written by the local 7B,
# grounded in that material; the cost readout shows provider=local, $0.
# And the eval:
python scripts/eval_local_cards.py --count 5            # local only
python scripts/eval_local_cards.py --count 5 --cloud    # + the cloud cheap-tier baseline (needs a key)
```
No UI change, so no light/dark screenshots: the only visible surface is the existing cost readout, which
shows the local call at `provider=local`, cost `0`.

## Tests
- `tests/test_llm_local.py` (no DB, no endpoint): default-off; the allow-list; the Anthropic→OpenAI
  translation; `local_create` request body + response shape (provider=local, cost 0); `length`→
  `max_tokens`; the fall-back-to-None contract; `describe()`.
- `tests/test_card_capture.py` (needs docker Postgres): local routing captures a de-identified sample,
  identity stripped and law content kept, the card tied back through `gen_sample_id`; default-off
  captures nothing and the response is unchanged.

## Acceptance
- [ ] `CF_LOCAL_BASE_URL` unset: every existing test passes unchanged; `generate_cards` returns
  `{"made": n}` and no `card_gen_samples` row is written.
- [ ] With it set to a running Ollama: cards are generated by Qwen2.5-7B, grounded in the ticked
  material; a thin source yields fewer cards, not invented law.
- [ ] Each local call logs an `ai_calls` row with `provider=local`, cost `0`; the spend readout is
  unaffected.
- [ ] A local interaction writes one `card_gen_samples` row with emails/IBANs/student numbers replaced
  and the generated cards tied back through `cards.gen_sample_id`.
- [ ] The endpoint being down falls back to the cloud cheap tier and the cards are still made.
- [ ] `scripts/eval_local_cards.py` reports faithfulness + usefulness for the local model (and, with a
  key, the cloud baseline). The numbers meet the bar before `cards` is flipped to local by default.
- [ ] `make test` green; migration `026` applies on a fresh DB and on one already at `025`.

## Later (not this phase)
- **Train a cards specialist (LoRA)** from the user's own existing + edited cards (the captured
  feedback signal) — Qwen2.5-7B QLoRA, Apache-2.0 base. Defer: needs wall power and, for multi-user, a
  privacy notice + opt-in. The frozen-gold gate is part of this.
- **Prod serving (mode b):** the live Cloud Run URL → the Mac's Ollama over Tailscale (subnet router /
  funnel). Cloud Run has no GPU and scales to zero, so it can't host the 7B itself; the always-on
  GPU/A100 endpoint is the later at-scale upgrade, not a blocker for the PoC.
- Flip the next bulk tasks to local once each clears the eval bar: `clean_text`, `tag_weeks`, quiz
  distractors.
- A fuller eval: a frozen gold set of the user's own ticked files (not public passages); judging
  against his edited cards; an LLM judge for nuance beyond the citation-grounding proxy.
