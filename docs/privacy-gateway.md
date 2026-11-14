# Gateway lane and model routing: privacy record (GDPR)

The record of processing for CognitioFlow's model calls, and in particular for the gateway lane
(`gateway.py`). It is kept under GDPR Art. 30 (records of processing activities) and Art. 5(2)
(accountability), and should be updated whenever a route, model, provider or gateway changes.

**State of this record: 2026-11-14.** Checked against the code on `main` at `c10207f`, which production serves
(`/health` reports commit `c10207f68063`; that commit has #234 (`a261d32`, `CF_GATEWAY=off`) as an ancestor, and the
deploy that shipped it succeeded on 2026-11-14). The live Cloud Run env was last read directly on 2026-11-13 (env names
and values, no secret values); on 2026-11-14 it was **not** re-read (the `gcloud` login had expired), so
`CF_GATEWAY=off` is known from `deploy.yml` at the served commit, not from a fresh service read.
Items marked **UNVERIFIED** or **UNKNOWN** have not been confirmed and must not be relied on.

**In short (2026-11-14):**
- **What leaves CF:** the tutor prompt, the files or passages the student ticks, the conversation, and for bulk jobs one note or file at a time; embeddings stay inside the container.
- **To whom:** the Kernal router, which passes it to Anthropic (`claude-sonnet-5`), Google Vertex AI (`gemini-2.5-flash`) or, only when picked per message, OpenAI (`gpt-5-nano`); speech goes to Google Cloud, and Chrome's dictation sends audio to Google.
- **Which region:** the cheap tier runs in us-central1 (USA); Anthropic and OpenAI are not region-pinned; transcription and the spoken tutor run in europe-west4; live dictation uses Google's global endpoint.
- **Not covered yet:** no processing agreement with the Kernal operator, no recorded transfer basis for the US routes (GDPR Art. 6 and 44-46 are not met), Kernal's logging and the operator's role unknown, and copyright of lecturers' material unexamined.
- **Being done:** the OpenRouter free lane has been off since 2026-11-14 (`CF_GATEWAY=off`, #234); the open items list below says who must act on each gap.

### Who operates Kernal

Kernal (`router.kernal.one`) is a LiteLLM router, operated by a private individual, not by CognitioFlow; no processing agreement on file.
CognitioFlow has an API key on it and no control over its configuration or logs. Where the router itself is hosted
is not recorded here. The cheap tier's Vertex calls run in the router operator's own Google Cloud project, not
CF's, so Google's terms bind the operator and CF has no contract of its own with Google for those calls
(known gap (a) below). The operator's legal role is **not settled: open** (see "Roles").

## Roles

| Question | Status today |
|---|---|
| Controller for course text | The account holder alone, as a private person studying from his own course files. CognitioFlow is the tool he built and has no purposes of its own. No other controller exists today. |
| Controller for account data (sign-in e-mail, `ALLOWED_EMAILS`) | The account holder, same basis. |
| Household exemption, Art. 2(2)(c) | Relied on for single-user personal study: the processing is by one natural person for his own studies. **Limit:** it ends the moment a second user's data is processed (the multi-user plan, F110), because then CF serves other people. It is a stated position, not a ruling, and **UNVERIFIED** by a lawyer. It does not exempt the providers from their own obligations. |
| Kernal operator | **Role not settled: open.** A processor under Art. 28 if it acts only on CF's instructions; a separate controller if it uses prompts for its own purposes (unknown). This record assumes processor for the Art. 28 row, with no agreement on file. |
| Anthropic, Google (Vertex via the operator's project), OpenAI | Sub-processors of the operator if the operator is a processor. What each does with the data is set by its own API terms, which this record has not confirmed for the account actually used (**UNVERIFIED**). |
| Google Cloud (Speech-to-Text, Text-to-Speech, Vertex Live, GCS) | Processor for the account holder under CF's own Google Cloud terms. The terms were not reviewed for this record. |
| Neon (database, Frankfurt) | Processor for the account holder under his Neon account. The terms were not reviewed for this record. |
| Browser vendor (Chrome's built-in dictation) | Acts for itself on the audio the browser sends; CF only receives the text. Its terms are **UNVERIFIED**. |

## Known gaps, stated plainly

| | Gap | Status and who must act |
|---|---|---|
| (a) | The Vertex calls run in the router operator's Google Cloud project, so Google's terms bind the operator; CF has no contract of its own with Google for them. | **Open.** The operator (to confirm and document its terms) and the account holder (to decide whether to accept or move the route). |
| (b) | Redaction (`gateway.minimise`) runs only on the OpenRouter lane, which is off. The Kernal routes, tutor and cheap tier alike, send course text unredacted. | **True today; open.** The account holder decides whether redaction is added to the Kernal routes. |
| (c) | The copyright position on sending lecturers' readers and slides to providers is unexamined. | **Open.** The account holder (with the faculty or its library if the tool is ever shown to others). |
| (d) | CF has a single user today and holds no other students' data. | **Stated.** Changes with the multi-user plan; reassess then. |

## Where data goes today (production)

Production runs `LLM_PROVIDER=kernal`. Every non-streaming call goes: local tier (off in production) →
gateway lane (bulk tasks only) → Kernal. The tutor's streaming chat goes straight to Kernal.

| Feature | What is sent | Route and model | Region |
|---|---|---|---|
| Tutor chat (drill, explain, apply), grading, reconcile, Case Docket writer/reviewer | Tutor prompt, ticked course files or retrieved passages, the conversation, the question | Kernal (LiteLLM router, see "Who operates Kernal") → Anthropic API, `claude-sonnet-5` | Not pinned (Anthropic default) |
| Cheap tier: summaries, notes, case extraction, chunked passes; since 2026-11-14 also the bulk tasks (`cards`, `concepts`, `syllabus`, `oral`) | Course text, notes, transcripts | Kernal → Google Vertex AI `gemini-2.5-flash` (the router operator's GCP project) | **us-central1 (USA)** |
| Picker alternatives, only when chosen per message | As the tutor chat | Kernal → `gemini-2.5-flash` (as above) or `gpt-5-nano` (OpenAI API) | Not pinned |
| Gateway lane (off since 2026-11-14) | Nothing: `CF_GATEWAY=off`, so the bulk tasks skip it and go to the cheap tier above, unredacted (redaction is a gateway-lane step) | n/a | n/a |
| Images in chat | Nothing: the Kernal bridge drops non-text blocks (a functional bug, not a transfer) | n/a | n/a |
| Uploaded files | Text extracted locally; the file stored in GCS `cognitioflow-user-content` | CF's own GCP project; database on Neon | GCS bucket per project config; Neon `aws-eu-central-1` (Frankfurt) |
| Embeddings and retrieval | Course text | Local, inside the container (`BAAI/bge-small-en-v1.5`) | Stays in the container |
| Lecture transcription | Audio from the bucket | Google Speech-to-Text v2 `chirp_2`, CF's own project | europe-west4 |
| Browser dictation (default mic mode where the browser offers it, e.g. Chrome) | Microphone audio | The browser's built-in Web Speech service (in Chrome, Google's speech service), not CF's project; CF only receives the text | Unknown (set by the browser vendor) |
| Live dictation (Gemini mic mode) | Microphone audio | Vertex AI Live `gemini-3.5-transcribe-live-preview`, CF's own project | **global** endpoint (may be served from any region) |
| Spoken tutor (voice dialog) | Microphone audio, tutor prompt, ticked excerpts | Vertex AI Live `gemini-live-2.5-flash-native-audio`, CF's own project | europe-west4 |
| Read aloud | Reply text or one note (≤30,000 characters) | Google Cloud Text-to-Speech, Chirp 3 HD, CF's own project | Global API, no location pinned |

There is no CF-owned Anthropic API key in production; Anthropic is reached only through Kernal. Edge,
ElevenLabs and Kokoro speech backends exist in code but are not active.

### The OpenRouter lane: switched off on 2026-11-14

- **Now:** `CF_GATEWAY=off` is in the Cloud Run `--set-env-vars` line of `.github/workflows/deploy.yml` (#234,
  merged as `a261d32` with the owner's named yes, deployed 2026-11-14). `gateway.enabled()` returns false, so
  `cards`, `concepts`, `syllabus` and `oral` go straight to the cheap tier (Kernal → Vertex `gemini-2.5-flash`,
  us-central1, the Kernal operator's GCP project). No course text is sent to OpenRouter.
- **Still in the config:** the OpenRouter base, model and key name (`CF_GATEWAY_BASE`, `CF_GATEWAY_MODEL`,
  `CF_GATEWAY_KEY_ENV`) are still set, so removing `CF_GATEWAY=off` alone would switch the free lane back on.
  The flag must stay in `deploy.yml`: setting it only on the service (`gcloud run services update`) is
  reverted by the next deploy, which sets the env list again.
- **Before the switch (2026-09-30 to 2026-11-14):** the bulk tasks were first tried on
  `nvidia/nemotron-3-super-120b-a12b:free`. That model listed **0 endpoints** on OpenRouter's public API
  (checked 2026-11-13) and `llm.py` records that the direct OpenRouter key is dead, so these calls most likely
  failed and fell back to the cheap tier. **UNVERIFIED**: the `ai_calls` table (which provider actually served
  each call) has not been read (open item 5). If a call did succeed, redacted course text reached an unknown
  free-tier provider that may train on it (UNVERIFIED).
- **Why the lane's own safeguards were not enough:** the spend ceiling (`CF_GATEWAY_SPEND_CEILING`) reads a
  LiteLLM header that OpenRouter does not send, so on OpenRouter it never trips; and the `no-log: true` flag is
  a LiteLLM convention that OpenRouter does not honour. Both only work on a LiteLLM gateway.

## GDPR principles: status today

Several rows below are openly **not met** yet (Art. 6 for the current routes, Art. 28, Art. 44–46); each points to its open item.

| Principle | Article | Status today |
|---|---|---|
| Lawfulness, fairness, transparency | Art. 5(1)(a), Art. 6 | The only user is the account holder (`ALLOWED_EMAILS`), whose own study material and questions these are. He consented to the gateway lane and to the OpenRouter free lane on 2026-09-30 (Art. 6(1)(a)); see the history below. That lane has been off since 2026-11-14. **Not met for the current routes (Kernal → Anthropic; Kernal → Vertex us-central1): no recorded decision or basis yet, open item 4.** Names of lecturers, authors and case parties in course material are public and incidental (Art. 6(1)(f)). This document is the transparency record. |
| Purpose limitation | Art. 5(1)(b) | Material is sent only to produce the study output asked for (tutor answer, cards, summary, transcription, speech). The gateway lane (off in production) is a closed allow-list enforced in code (`gateway.allows`). |
| Data minimisation | Art. 5(1)(c) | The tutor sends only the files the user ticks or the passages retrieved for the question. The gateway lane sends one note or file, with e-mail addresses, phone numbers, IBANs and student numbers replaced with placeholders (`gateway.minimise`); legal citations, dates and case numbers are kept (tests guard this). Redaction applies to the gateway lane only, not to the tutor or the cheap tier; with the lane off, the bulk tasks' text reaches the cheap tier unredacted. |
| Accuracy | Art. 5(1)(d) | Outputs are study aids the user checks, not records about a person. |
| Storage limitation | Art. 5(1)(e) | **Open: provider defaults only, none confirmed for the account actually used** (checked 2026-11-14). Anthropic API: inputs and outputs deleted within 30 days, with exceptions (privacy.anthropic.com/en/articles/7996866, page modified 2026-07-01). Vertex AI (Gemini): in-memory and at-rest caching both on by default, each deleted within 24 h; Google may log prompts for abuse monitoring; request-response logging off by default (cloud.google.com/vertex-ai/generative-ai/docs/vertex-ai-zero-data-retention, updated 2026-11-12); the cache setting of the Kernal operator's project is **UNKNOWN**. Speech-to-Text: audio and transcripts not logged by default (cloud.google.com/speech-to-text/docs/data-logging, updated 2026-11-10); whether CF's project opted into data logging was **not checked**. OpenAI API (picker only): **UNVERIFIED**. Kernal: **UNKNOWN** (open item 1). |
| Integrity and confidentiality | Art. 5(1)(f), Art. 32 | TLS on every hop. Keys sit in Google Secret Manager and are read from the environment only (CLAUDE.md, "Secrets and data"); never logged. |
| Accountability | Art. 5(2) | Every call's usage record carries its provider, model and cost (`ai_calls`). This record and the tests document the design. |
| Data protection by design and by default | Art. 25 | The gateway lane is **off in production** (`CF_GATEWAY=off` in `deploy.yml`, since 2026-11-14); that flag is the only effective control in production. The lane's spend ceiling only works on a LiteLLM gateway and did not trip on the OpenRouter lane production used. The local tier is off unless `CF_LOCAL_BASE_URL` is set. Embeddings never leave the container. |
| Processors | Art. 28 | **Not met for the Kernal chain.** The operator is assumed to be a processor (role not settled, see "Roles"), with Anthropic, Google (Vertex, via the operator's project) and OpenAI as its sub-processors; **no Art. 28(3) agreement with the operator is on file: open item 2.** Google Cloud (STT, TTS, Vertex Live, GCS) is a direct processor under CF's own GCP terms, which were not reviewed. |
| International transfers | Art. 44–46 | The cheap tier is served in the USA (us-central1); Anthropic and OpenAI are not region-pinned; live dictation uses Vertex's global endpoint. A transfer needs an adequacy decision (Art. 45, e.g. the EU–US Data Privacy Framework for a certified recipient) or SCCs (Art. 46(2)(c)). **Not met: no transfer basis is recorded for the US routes (open item 3).** Whether Anthropic, Google or OpenAI is certified under the Data Privacy Framework, or what SCCs the operator has with them, is **UNVERIFIED** (not checked). |
| Special categories | Art. 9 | None expected in study notes. Redaction does not detect them; keep health or similar details out of study material. |
| Data subject rights | Art. 15–17 | The originals stay in CognitioFlow's own database, where access and erasure work. Copies at providers follow their retention above. |
| DPIA | Art. 35 | Not required for one user and his own study material, no profiling, no special categories. **Reassess before any other user is added** (DPIA and DPO/SURF review before any pilot). |

No zero-retention or EU-only guarantee applies to the tutor or the cheap tier today.

**Retention sources** (provider defaults, read 2026-11-14):
- Anthropic, "How long do you store my organization's data?", privacy.anthropic.com/en/articles/7996866
  (page modified 2026-07-01).
- Google Cloud, "Vertex AI and zero data retention", cloud.google.com/vertex-ai/generative-ai/docs/vertex-ai-zero-data-retention
  (last updated 2026-11-12): sections "Implicit data caching" and "Customer data retention".
- Google Cloud, "Data logging", cloud.google.com/speech-to-text/docs/data-logging (last updated 2026-11-10).
- OpenAI API retention: not checked.

## Open items (verify before relying on any of this for anything sensitive)

Each is **open**; the last column says who must act. Any statement here that depends on one is marked UNVERIFIED.

| # | Open item | Who must act |
|---|---|---|
| 1 | **Kernal logging.** Does the router keep prompts (spend logs or request logging)? LiteLLM's `store_prompts_in_spend_logs` is off by default; **UNVERIFIED** for this router. | The Kernal operator, asked by the account holder |
| 2 | **Processor terms.** Does the operator's agreement with Anthropic, Google and OpenAI cover Art. 28(3), and does a zero-data-retention arrangement exist or can be made? No agreement with CF exists. | The Kernal operator and the account holder |
| 3 | **Transfer basis and EU route.** The cheap tier could move to an EU Vertex region (a new route on the router, then `CF_CHEAP_MODEL`); live dictation could move to `VOICE_LOCATION=europe-west4` only after a probe (the preview model answered only on `global` when added). | The account holder (decision); the operator (new route) |
| 4 | **Record the routing decision.** The account holder's choice of the current routes (Anthropic and Vertex US via Kernal) should be recorded here with a date, as the 2026-09-30 decision was. | The account holder |
| 5 | **Confirm the lane's history.** Read `ai_calls` (provider and model per task, last 30 days) to see whether the OpenRouter lane ever succeeded. **UNVERIFIED** until read. | The account holder (a read-only production query) |
| 6 | **Kernal operator's role** (processor, separate controller, or other). **UNVERIFIED.** | The operator and the account holder |
| 7 | **Copyright position** on sending lecturers' readers and slides to providers. Unexamined. | The account holder |
| 8 | **Cache and logging settings** of the operator's Vertex project and of CF's Speech-to-Text project. **UNKNOWN / not checked.** | The operator; the account holder |

Closed: the OpenRouter switch-off patch was applied on 2026-11-14 as #234 (`a261d32`) and deployed.
~~Apply `cf-gateway-off.patch`.~~

## Gateway lane configuration

| Variable | Meaning | Production today |
|---|---|---|
| `CF_GATEWAY` | `off` disables the lane | **`off`** (since 2026-11-14, #234) |
| `CF_GATEWAY_TASKS` | allow-list; default `cards,concepts,syllabus,oral` | default |
| `CF_GATEWAY_BASE`, `CF_GATEWAY_MODEL` | gateway URL and model (code defaults: the LiteLLM gateway and `gpt-6-luna`) | still set to `https://openrouter.ai/api`, `nvidia/nemotron-3-super-120b-a12b:free` (unused while `CF_GATEWAY=off`) |
| `CF_GATEWAY_KEY_ENV` | which env var holds the key; default `LITELLM_API_KEY` | `OPENROUTER_KEY` (unused while off) |
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
so bulk-task text (redacted) may be retained and trained on (that was the warning as given then; not re-checked, UNVERIFIED); he accepted this for his own study material
(Art. 5(2), Art. 6(1)(a)).

### Phase 19: Kernal

The cloud tier moved to Kernal (`LLM_PROVIDER=kernal`): main tier `claude-sonnet-5` on the Anthropic API and
cheap tier `gemini-2.5-flash` on Vertex AI, both through the router. The OpenRouter gateway-lane env stayed
in the deploy config, although the direct OpenRouter key no longer works.

### 2026-11-14: the OpenRouter lane switched off

`CF_GATEWAY=off` added to the deploy config (#234, owner's named yes) and deployed. The bulk tasks now run on
the cheap tier. That is the state described at the top of this record.
