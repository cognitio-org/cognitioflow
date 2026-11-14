# Gateway lane and model routing: privacy record (GDPR)

The record of processing for CognitioFlow's model calls, and in particular for the gateway lane
(`gateway.py`). It is kept in the manner of GDPR Art. 30 (records of processing activities) and under Art. 5(2)
(accountability), because this record treats the GDPR as applying (see "Roles"), and should be updated whenever a route, model, provider or gateway changes.

**State of this record: 2026-11-14.** Checked against the code on `main` at `c10207f`, which production serves
(`/health` reports commit `c10207f68063`; that commit has #234 (`a261d32`, `CF_GATEWAY=off`) as an ancestor, and the
deploy that shipped it succeeded on 2026-11-14). The live Cloud Run env was last read directly on 2026-11-13 (env names
and values, no secret values); on 2026-11-14 it was **not** re-read (the `gcloud` login had expired), so
`CF_GATEWAY=off` is known from `deploy.yml` at the served commit, not from a fresh service read.
Items marked **UNVERIFIED** or **UNKNOWN** have not been confirmed and must not be relied on.

**In short (2026-11-14):**
- **What leaves CF:** the tutor prompt, the files or passages the student ticks, the conversation, and for bulk jobs one note or file at a time; embeddings stay inside the container.
- **To whom:** the Kernal router (operated by Matej himself), which passes it to Anthropic (`claude-sonnet-5`), Google Vertex AI (`gemini-2.5-flash`) or, only when picked per message, OpenAI (`gpt-5-nano`); speech goes to Google Cloud, and Chrome's dictation sends audio to Google.
- **Which region:** the cheap tier runs in us-central1 (USA); Anthropic and OpenAI are not region-pinned; transcription and the spoken tutor run in europe-west4; live dictation uses Google's global endpoint.
- **Not covered yet:** no review of the providers' terms for the accounts actually used (Art. 28 not met), no recorded transfer basis for the US routes (Art. 6 and 44-46 not met), Kernal's own logging unchecked, a lawful-basis balancing for third persons' names drafted but not lawyer-reviewed, and copyright of lecturers' material unexamined.
- **Being done:** the OpenRouter free lane has been off since 2026-11-14 (`CF_GATEWAY=off`, #234); the open items list below says who must act on each gap.

### Who operates Kernal

Kernal (`router.kernal.one`) is a LiteLLM router, operated by Matej himself, the owner of CognitioFlow; no processing agreement with the providers behind it is on file.
Matej runs it himself and is also the person who built and owns CognitioFlow, so there is no
separate operator and no processor relationship between the two: CognitioFlow's API key on the router is
one person's key on that person's own router. What stands behind the router are the providers' own services
(Anthropic, Google Vertex AI, OpenAI), each under its own terms, which this record has not reviewed for the
accounts actually used. Where the router is hosted is not recorded here. The cheap tier's Vertex calls run in
the router's own Google Cloud project, a different project from the one CognitioFlow's speech and storage use,
so Google's terms for those calls are the ones of that project's account holder (known gap (a) below). Whether
the router keeps prompts is **UNVERIFIED** (open item 1); he can check it himself.

## Roles

| Question | Status today |
|---|---|
| Controller for course text | Matej, as the person who decides why and how the course text is processed. CognitioFlow is the tool he built and has no purposes of its own. No other controller exists today. |
| Controller for account data (sign-in e-mail, `ALLOWED_EMAILS`) | Matej, same basis. |
| Household exemption, Art. 2(2)(c) | **Not relied on.** The exemption covers purely personal or household processing and the Court of Justice reads it narrowly (under the predecessor Directive 95/46, whose wording the GDPR kept: Lindqvist, C-101/01, paragraph 47; Ryneš, C-212/13, paragraphs 29-30, "narrowly construed"). A tool in a public repository, shown to a faculty and built to serve other students, is hard to call purely personal, so this record takes the cautious position: the GDPR is treated as applying, Matej is the controller, and the rows below are judged on that footing (hence "not met" where they are not). That position is stated, not a ruling, and **UNVERIFIED** by a lawyer. |
| Kernal operator | Matej himself (see "Who operates Kernal"). Not a separate processor and not a separate controller: the router is his own tool. The role question that was open before 2026-11-14 is **settled** on his statement. Whether the router keeps prompts is still **UNVERIFIED** (open item 1). |
| Anthropic, Google (Vertex, via the router's project), OpenAI | Processors acting for Matej as controller, each under its own API terms, which this record has not confirmed for the account actually used (**UNVERIFIED**). Whether each is bound by a data-processing agreement that satisfies Art. 28(3) is open item 2. |
| Google Cloud (Speech-to-Text, Text-to-Speech, Vertex Live, GCS) | Processor for Matej under CognitioFlow's own Google Cloud terms. The terms were not reviewed for this record. |
| Neon (database, Frankfurt) | Processor for Matej under his Neon account. The terms were not reviewed for this record. |
| Browser vendor (Chrome's built-in dictation) | Acts for itself on the audio the browser sends; CF only receives the text. Its terms are **UNVERIFIED**. |

## Known gaps, stated plainly

| | Gap | Status and who must act |
|---|---|---|
| (a) | The Vertex calls run in the router's own Google Cloud project, a different project from the one CognitioFlow uses for speech and storage; the terms that apply to them are the ones of that project's account holder. | **Open.** Matej (to read and record those terms and the project's caching and logging settings, or to move the route into CF's own project). |
| (b) | Redaction (`gateway.minimise`, placeholder replacement, not pseudonymisation under Art. 4(5)) runs only on the OpenRouter lane, which is off. The Kernal routes, tutor and cheap tier alike, send course text unredacted. | **True today; open.** Matej decides whether redaction is added to the Kernal routes. |
| (c) | The copyright position on sending lecturers' readers and slides to providers is unexamined. | **Open.** Matej (with the faculty or its library if the tool is ever shown to others). |
| (d) | CF has a single user today and holds no other students' data. | **Stated.** Changes with the multi-user plan; reassess then. |

## Where data goes today (production)

Production runs `LLM_PROVIDER=kernal`. Every non-streaming call goes: local tier (off in production) →
gateway lane (bulk tasks only) → Kernal. The tutor's streaming chat goes straight to Kernal.

| Feature | What is sent | Route and model | Region |
|---|---|---|---|
| Tutor chat (drill, explain, apply), grading, reconcile, Case Docket writer/reviewer | Tutor prompt, ticked course files or retrieved passages, the conversation, the question | Kernal (LiteLLM router, see "Who operates Kernal") → Anthropic API, `claude-sonnet-5` | Not pinned (Anthropic default) |
| Cheap tier: summaries, notes, case extraction, chunked passes; since 2026-11-14 also the bulk tasks (`cards`, `concepts`, `syllabus`, `oral`) | Course text, notes, transcripts | Kernal → Google Vertex AI `gemini-2.5-flash` (the Kernal router's own Google Cloud project) | **us-central1 (USA)** |
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
  us-central1, the Kernal router's own Google Cloud project). No course text is sent to OpenRouter.
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
| Lawfulness, fairness, transparency | Art. 5(1)(a), Art. 6 | Two groups of people are involved. **(1) Matej** (his questions, notes and uploads): his own wish to have them processed is his consent for the gateway lane and the OpenRouter free lane, given on 2026-09-30 (Art. 6(1)(a), see the history below); that lane has been off since 2026-11-14. His consent covers only his own data. **(2) Third persons named in course material** (lecturers, authors, judges, case parties): his consent cannot cover them, so the basis drafted for them is legitimate interests, Art. 6(1)(f), with this balancing. *Interest:* studying his own course with a tutoring tool. *Necessity:* the names are in the readers and slides the course itself provides; the tool sends them only as part of the passage needed for the answer, builds no profile and no list of persons. *Impact and expectations:* lecturers and authors expect students to read and annotate course material, and case parties in published judgments are named by the court itself; against that stand a transfer to providers in the USA, provider retention (see Storage limitation) and the absence of redaction on the Kernal routes (known gap (b)). *Outcome:* provisionally in favour while there is one user and no onward publication; **UNVERIFIED** by a lawyer, to be redone before a second user is added. **Not met for the current routes until Matej records his decision on them (open item 4)**. This document is the transparency record. |
| Purpose limitation | Art. 5(1)(b) | Material is sent only to produce the study output asked for (tutor answer, cards, summary, transcription, speech). The gateway lane (off in production) is a closed allow-list enforced in code (`gateway.allows`). |
| Data minimisation | Art. 5(1)(c) | The tutor sends only the files the user ticks or the passages retrieved for the question. The gateway lane sends one note or file, with e-mail addresses, phone numbers, IBANs and student numbers replaced with placeholders (`gateway.minimise`); legal citations, dates and case numbers are kept (tests guard this). Redaction applies to the gateway lane only, not to the tutor or the cheap tier; with the lane off, the bulk tasks' text reaches the cheap tier unredacted. |
| Accuracy | Art. 5(1)(d) | Outputs are study aids the user checks, not records about a person. |
| Storage limitation | Art. 5(1)(e) | **Open: provider defaults only, none confirmed for the account actually used** (checked 2026-11-14). *Anthropic API:* inputs and outputs deleted within 30 days, with exceptions (privacy.anthropic.com/en/articles/7996866, page modified 2026-07-01). *Vertex AI, Google's own Gemini models* (docs.cloud.google.com/gemini-enterprise-agent-platform/resources/zero-data-retention, "Last updated 2026-11-12 UTC", accessed 2026-11-14), as the page says: "Google may log prompts to detect potential abuse and violations of its Acceptable Use Policy and Prohibited Use Policy" (no retention period is stated for this logging on that page); "Request-response logging: This feature is disabled by default"; implicit caching, in-memory and durable, is "Enabled by default for supported Gemini models" and cached data is "deleted no later than 24 hours after it's written"; "Google won't use your data to train or fine-tune any AI/ML models without your prior permission or instruction". The same page states a 30-day log ("By default, Google Cloud logs prompts, file inputs, and responses for up to 30 days in Google-owned storage in the us multi-region") in its section on OpenAI flagship models served on Google's platform; that section is not about Google's own models and CF does not call OpenAI through Google, so it is not applied to `gemini-2.5-flash` here. The caching setting of the router's Vertex project is **UNKNOWN**. *Speech-to-Text:* audio and transcripts not logged by default (cloud.google.com/speech-to-text/docs/data-logging, updated 2026-11-10); whether CF's project opted into data logging was **not checked**. *OpenAI API (picker only):* **UNVERIFIED**. *Kernal:* **UNKNOWN** (open item 1). |
| Integrity and confidentiality | Art. 5(1)(f), Art. 32 | TLS on every hop. Keys sit in Google Secret Manager and are read from the environment only (CLAUDE.md, "Secrets and data"); never logged. |
| Accountability | Art. 5(2) | Every call's usage record carries its provider, model and cost (`ai_calls`). This record and the tests document the design. |
| Data protection by design and by default | Art. 25 | The gateway lane is **off in production** (`CF_GATEWAY=off` in `deploy.yml`, since 2026-11-14); that flag is the only effective control in production. The lane's spend ceiling only works on a LiteLLM gateway and did not trip on the OpenRouter lane production used. The local tier is off unless `CF_LOCAL_BASE_URL` is set. Embeddings never leave the container. |
| Processors | Art. 28 | **Not met for the Kernal chain.** Matej is the controller and runs the router himself, so the router is not a processor; the processors are Anthropic, Google (Vertex, in the router's own Google Cloud project) and OpenAI, each under its own API terms. **No review of those terms against Art. 28(3) is on file for the accounts actually used: open item 2.** Google Cloud (STT, TTS, Vertex Live, GCS) is a processor under CF's own Google Cloud terms, which were not reviewed. |
| International transfers | Art. 44–46 | The cheap tier is served in the USA (us-central1); Anthropic and OpenAI are not region-pinned; live dictation uses Vertex's global endpoint. A transfer needs an adequacy decision (Art. 45, e.g. the EU–US Data Privacy Framework for a certified recipient) or SCCs (Art. 46(2)(c)). **Not met: no transfer basis is recorded for the US routes (open item 3).** Whether Anthropic, Google or OpenAI is certified under the Data Privacy Framework, or which SCCs apply to the accounts used, is **UNVERIFIED** (not checked). |
| Special categories | Art. 9 | None expected in study notes. Redaction does not detect them; keep health or similar details out of study material. |
| Data subject rights | Art. 15–17 | The originals stay in CognitioFlow's own database, where access and erasure work. Copies at providers follow their retention above. |
| DPIA | Art. 35 | Not required for one user and his own study material, no profiling, no special categories. **Reassess before any other user is added** (DPIA and DPO/SURF review before any pilot). |

No zero-retention or EU-only guarantee applies to the tutor or the cheap tier today.

**Retention sources** (provider defaults, read 2026-11-14):
- Anthropic, "How long do you store my organization's data?", privacy.anthropic.com/en/articles/7996866
  (page modified 2026-07-01).
- Google Cloud, "Gemini Enterprise Agent Platform and zero data retention" (formerly "Vertex AI and zero data retention"),
  docs.cloud.google.com/gemini-enterprise-agent-platform/resources/zero-data-retention (last updated 2026-11-12, accessed
  2026-11-14; saved copy kept with the flow evidence): sections "Customer data retention", "Implicit data caching" and "Partner models".
- Google Cloud, "Data logging", cloud.google.com/speech-to-text/docs/data-logging (last updated 2026-11-10).
- OpenAI API retention: not checked.

## Open items (verify before relying on any of this for anything sensitive)

Each is **open**; the last column says who must act. Any statement here that depends on one is marked UNVERIFIED.

| # | Open item | Who must act |
|---|---|---|
| 1 | **Kernal logging.** Does the router keep prompts (spend logs or request logging)? LiteLLM's `store_prompts_in_spend_logs` is off by default; **UNVERIFIED** for this router. | Matej (reads his router's configuration) |
| 2 | **Provider terms against Art. 28(3).** Do the terms of the Anthropic, Google and OpenAI accounts behind the router include a data-processing agreement that meets Art. 28(3), and can a zero-data-retention arrangement be obtained? Not reviewed. | Matej |
| 3 | **Transfer basis and EU route.** The cheap tier could move to an EU Vertex region (a new route on the router, then `CF_CHEAP_MODEL`); live dictation could move to `VOICE_LOCATION=europe-west4` only after a probe (the preview model answered only on `global` when added). | Matej (decision and the new route) |
| 4 | **Record the routing decision.** Matej's choice of the current routes (Anthropic and Vertex US via Kernal) should be recorded here with a date, as the 2026-09-30 decision was, together with the legitimate-interests balancing in the Art. 6 row. | Matej |
| 5 | **Confirm the lane's history.** Read `ai_calls` (provider and model per task, last 30 days) to see whether the OpenRouter lane ever succeeded. **UNVERIFIED** until read. | Matej (a read-only production query) |
| 6 | **Lawyer review** of the Roles position (household exemption not relied on, Matej as controller) and of the Art. 6(1)(f) balancing. **UNVERIFIED** until done. | Matej (names the reviewer) |
| 7 | **Copyright position** on sending lecturers' readers and slides to providers. Unexamined. | Matej |
| 8 | **Cache and logging settings** of the router's Vertex project and of CF's Speech-to-Text project. **UNKNOWN / not checked.** | Matej |

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
