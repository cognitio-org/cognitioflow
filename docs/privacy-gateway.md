# Gateway lane and model routing: privacy record (GDPR)

The record of processing for CognitioFlow's model calls, and in particular for the gateway lane
(`gateway.py`). It is kept under GDPR Art. 30 (records of processing activities) and Art. 5(2)
(accountability), and should be updated whenever a route, model, provider or gateway changes.

**State of this record: 2026-11-13.** Checked against the code at `f068e36` and the live Cloud Run
configuration (env names and values, no secret values). Items marked **UNVERIFIED** or **UNKNOWN** have not
been confirmed and must not be relied on.

**In short (2026-11-13):**
- **What leaves:** the tutor prompt, the files or passages the student ticks, the conversation, and for bulk
  jobs one note or file at a time. Embeddings stay inside the container.
- **To whom:** the Kernal router, which passes it to Anthropic (`claude-sonnet-5`) or Google Vertex AI
  (`gemini-2.5-flash`); speech goes to Google Cloud under CF's own project.
- **Which region:** the cheap tier runs in **us-central1 (USA)**; Anthropic is not region-pinned; live dictation and
  read-aloud use Google's global endpoints; transcription and the spoken tutor run in europe-west4.
- **Not yet covered:** no processing agreement with the Kernal operator, no recorded transfer basis for the US
  routes, Kernal's prompt logging unknown, and the OpenRouter free lane still **on** until `CF_GATEWAY=off` is applied.
- **Being done:** the `CF_GATEWAY=off` change is written and waits for the owner's approval; the open items
  below list the rest.

### Who operates Kernal

Kernal (`router.kernal.one`) is a LiteLLM router operated by a family member of CognitioFlow's developer on that person's own GCP project, not by CognitioFlow. CognitioFlow has an API key on it and no
control over its configuration or logs. For this record its operator is treated as a processor (Art. 28) with
**no processing agreement on file** (open item 2). The cheap tier runs on the operator's GCP project
(`outfitter-509211`), not CF's.

## Where data goes today (production)

Production runs `LLM_PROVIDER=kernal`. Every non-streaming call goes: local tier (off in production) →
gateway lane (bulk tasks only) → Kernal. The tutor's streaming chat goes straight to Kernal.

| Feature | What is sent | Route and model | Region |
|---|---|---|---|
| Tutor chat (drill, explain, apply), grading, reconcile, Case Docket writer/reviewer | Tutor prompt, ticked course files or retrieved passages, the conversation, the question | Kernal (LiteLLM router, see "Who operates Kernal") → Anthropic API, `claude-sonnet-5` | Not pinned (Anthropic default) |
| Cheap tier: summaries, notes, case extraction, chunked passes; also the bulk tasks' fallback | Course text, notes, transcripts | Kernal → Google Vertex AI `gemini-2.5-flash` (the router operator's GCP project) | **us-central1 (USA)** |
| Picker alternatives, only when chosen per message | As the tutor chat | Kernal → `gemini-2.5-flash` (as above) or `gpt-5-nano` (OpenAI API) | Not pinned |
| Gateway lane: `cards`, `concepts`, `syllabus`, `oral` | One note or file (≤60,000 characters), redacted (below) | **Attempted first** on OpenRouter, `nvidia/nemotron-3-super-120b-a12b:free`; on failure, the cheap tier | Unknown free-tier provider |
| Images in chat | Nothing: the Kernal bridge drops non-text blocks (a functional bug, not a transfer) | n/a | n/a |
| Uploaded files | Text extracted locally; the file stored in GCS `cognitioflow-user-content` | CF's own GCP project; database on Neon | GCS bucket per project config; Neon `aws-eu-central-1` (Frankfurt) |
| Embeddings and retrieval | Course text | Local, inside the container (`BAAI/bge-small-en-v1.5`) | Stays in the container |
| Lecture transcription | Audio from the bucket | Google Speech-to-Text v2 `chirp_2`, CF's own project | europe-west4 |
| Live dictation (Gemini mic mode) | Microphone audio | Vertex AI Live `gemini-3.5-transcribe-live-preview`, CF's own project | **global** endpoint (may be served from any region) |
| Spoken tutor (voice dialog) | Microphone audio, tutor prompt, ticked excerpts | Vertex AI Live `gemini-live-2.5-flash-native-audio`, CF's own project | europe-west4 |
| Read aloud | Reply text or one note (≤30,000 characters) | Google Cloud Text-to-Speech, Chirp 3 HD, CF's own project | Global API, no location pinned |

There is no CF-owned Anthropic API key in production; Anthropic is reached only through Kernal. Edge,
ElevenLabs and Kokoro speech backends exist in code but are not active.

### The OpenRouter lane is dead, and is being switched off

- The free model above currently lists **0 endpoints** on OpenRouter's public API (checked 2026-11-13), and
  `llm.py` records that the direct OpenRouter key is dead. These calls therefore most likely fail and fall
  back to the cheap tier. **UNVERIFIED**: the `ai_calls` table (which provider actually served each call)
  has not been read. If a call did succeed, course text reached an unknown free-tier provider that may
  train on it.
- The spend ceiling (`CF_GATEWAY_SPEND_CEILING`) reads a LiteLLM header that OpenRouter does not send, so it
  never trips.
- The `no-log: true` flag the lane sends is a LiteLLM convention. OpenRouter does not honour it.
- **Decision: turn the lane off by config, `CF_GATEWAY=off`.** The bulk tasks then go straight to the cheap
  tier (Vertex `gemini-2.5-flash`, us-central1). The env sits in `.github/workflows/deploy.yml`, a protected
  file, so the change waits as `docs/pending-protected/cf-gateway-off.patch` for the owner's approval. Until
  that patch is applied (or the env is set on the service and the patch merged so a deploy does not revert
  it), the lane is still **on** in production, so the honest answer to "is course text still sent to a free-tier
  provider?" is: it is still attempted. If the patch stops applying (the line it replaces changed first), the
  equivalent is to append `,CF_GATEWAY=off` to the `--set-env-vars` line by hand, or to run
  `gcloud run services update <service> --update-env-vars CF_GATEWAY=off` and then also merge the deploy.yml change
  so the next deploy does not revert it.

## How each GDPR principle is met

| Principle | Article | How it is met today |
|---|---|---|
| Lawfulness, fairness, transparency | Art. 5(1)(a), Art. 6 | The only user is the account holder (`ALLOWED_EMAILS`), whose own study material and questions these are. He consented to the gateway lane and to the OpenRouter free lane on 2026-09-30 (Art. 6(1)(a)); see the history below. **The current routes (Kernal → Anthropic; Kernal → Vertex us-central1) are not yet covered by a recorded decision: open item 4.** Names of lecturers, authors and case parties in course material are public and incidental (Art. 6(1)(f)). This document is the transparency record. |
| Purpose limitation | Art. 5(1)(b) | Material is sent only to produce the study output asked for (tutor answer, cards, summary, transcription, speech). The gateway lane is a closed allow-list enforced in code (`gateway.allows`). |
| Data minimisation | Art. 5(1)(c) | The tutor sends only the files the user ticks or the passages retrieved for the question. The gateway lane sends one note or file, with e-mail addresses, phone numbers, IBANs and student numbers replaced with placeholders (`gateway.minimise`); legal citations, dates and case numbers are kept (tests guard this). Redaction applies to the gateway lane only, not to the tutor or the cheap tier. |
| Accuracy | Art. 5(1)(d) | Outputs are study aids the user checks, not records about a person. |
| Storage limitation | Art. 5(1)(e) | Anthropic API: deleted within 30 days by default. Vertex AI: in-memory cache on by default, deleted within 24 h; abuse-monitoring logging possible. Speech-to-Text: not logged by default. Kernal: **UNKNOWN** (open item 1). OpenRouter: ignores `no-log`; provider retention varies. |
| Integrity and confidentiality | Art. 5(1)(f), Art. 32 | TLS on every hop. Keys sit in Google Secret Manager and are read from the environment only (CLAUDE.md, "Secrets and data"); never logged. |
| Accountability | Art. 5(2) | Every call's usage record carries its provider, model and cost (`ai_calls`). This record and the tests document the design. |
| Data protection by design and by default | Art. 25 | The gateway lane needs a key **and** a spend ceiling, and `CF_GATEWAY=off` disables it. The local tier is off unless `CF_LOCAL_BASE_URL` is set. Embeddings never leave the container. |
| Processors | Art. 28 | Kernal's operator acts as a processor; Anthropic, Google (Vertex, via the operator's project) and OpenAI are its sub-processors; Google Cloud (STT, TTS, Vertex Live, GCS) is a direct processor under CF's own GCP terms. **No processing agreement with the Kernal operator is on file: open item 2.** |
| International transfers | Art. 44–46 | The cheap tier is served in the USA (us-central1); Anthropic and OpenAI are not region-pinned; live dictation uses Vertex's global endpoint. A transfer needs an adequacy decision (Art. 45, e.g. the EU–US Data Privacy Framework for a certified recipient) or SCCs (Art. 46(2)(c)). **Open item 3.** |
| Special categories | Art. 9 | None expected in study notes. Redaction does not detect them; keep health or similar details out of study material. |
| Data subject rights | Art. 15–17 | The originals stay in CognitioFlow's own database, where access and erasure work. Copies at providers follow their retention above. |
| DPIA | Art. 35 | Not required for one user and his own study material, no profiling, no special categories. **Reassess before any other user is added** (DPIA and DPO/SURF review before any pilot). |

No zero-retention or EU-only guarantee applies to the tutor or the cheap tier today.

## Open items (verify before relying on any of this for anything sensitive)

1. **Kernal logging.** Ask the operator whether the router keeps prompts (spend logs or request logging).
   LiteLLM's `store_prompts_in_spend_logs` is off by default, but that must be confirmed.
2. **Processor terms.** Confirm with the Kernal operator that its terms with Anthropic, Google and OpenAI
   cover Art. 28(3), and whether a zero-data-retention arrangement exists or can be made.
3. **Transfer basis and EU routing.** The cheap tier could move to an EU Vertex region (a new route on the
   router, then `CF_CHEAP_MODEL`); live dictation could move to `VOICE_LOCATION=europe-west4` only after a
   probe, since the preview model answered only on `global` when it was added.
4. **Record the routing decision.** The account holder's choice of the current routes (Anthropic and
   Vertex US via Kernal) should be recorded here with a date, as the 2026-09-30 decision was.
5. **Confirm the lane's history.** Read `ai_calls` (provider and model per task, last 30 days) to see
   whether the OpenRouter lane ever succeeded.
6. **Apply `docs/pending-protected/cf-gateway-off.patch`.**

## Gateway lane configuration

| Variable | Meaning | Production today |
|---|---|---|
| `CF_GATEWAY` | `off` disables the lane | unset (patch pending to set `off`) |
| `CF_GATEWAY_TASKS` | allow-list; default `cards,concepts,syllabus,oral` | default |
| `CF_GATEWAY_BASE`, `CF_GATEWAY_MODEL` | gateway URL and model (code defaults: the LiteLLM gateway and `gpt-6-luna`) | `https://openrouter.ai/api`, `nvidia/nemotron-3-super-120b-a12b:free` |
| `CF_GATEWAY_KEY_ENV` | which env var holds the key; default `LITELLM_API_KEY` | `OPENROUTER_KEY` |
| `CF_GATEWAY_SPEND_CEILING` | the lane turns itself off once the key's spend (the `x-litellm-key-spend` header) reaches this many dollars. Only a LiteLLM gateway sends that header | `113` (never trips on OpenRouter) |

## History (superseded)

### 2026-09-30, afternoon: the gateway lane

The four bulk tasks went to `gpt-6-luna` through the LiteLLM gateway at `litellm.augment-code.support`, with
an Anthropic fallback (Claude Haiku). Everything else ran on the Anthropic API directly.

### 2026-09-30, evening: the app left the paid Anthropic API

The Anthropic credit ran out and Matej decided the app would run on `gpt-6-luna` via the gateway for
everything (`LLM_PROVIDER=gateway`), with the four bulk tasks going to free OpenRouter models first
(`nvidia/nemotron-3-super-120b-a12b:free`), falling back to `gpt-6-luna`. He was told before choosing it
that OpenRouter serves `:free` models only to accounts that allow providers to use prompts for training,
so bulk-task text (redacted) may be retained and trained on; he accepted this for his own study material
(Art. 5(2), Art. 6(1)(a)).

### Phase 19: Kernal

The cloud tier moved to Kernal (`LLM_PROVIDER=kernal`): main tier `claude-sonnet-5` on the Anthropic API and
cheap tier `gemini-2.5-flash` on Vertex AI, both through the router. The OpenRouter gateway-lane env stayed
in the deploy config, although the direct OpenRouter key no longer works. That is the state described at
the top of this record.
