# Gateway lane: privacy record (GDPR)

The record of processing for the gateway lane (`gateway.py`). This is the one place where CognitioFlow
sends study material to a model outside Anthropic. It is kept under GDPR Art. 30 (records of processing
activities) and Art. 5(2) (accountability), and should be updated whenever the lane's tasks, model or
gateway change.

## What the lane does

| | |
|---|---|
| **Tasks** (closed list, `CF_GATEWAY_TASKS`) | flashcards from one note or file (`cards`), concept extraction and concept cards (`concepts`), reading a syllabus (`syllabus`), viva questions (`oral`) |
| **Never** | the tutor chat in any mode (drill, explain, apply, notes), reconcile, essay marking, voice |
| **Data sent** | the text of one note or one file (at most 60,000 characters), or one concept's summary, plus the task's fixed instructions |
| **Model** | `gpt-6-luna` (`CF_GATEWAY_MODEL`) through the LiteLLM gateway at `litellm.augment-code.support` (`CF_GATEWAY_BASE`) |
| **Fallback** | Anthropic (the cheap tier, Claude Haiku) whenever the lane is off, the task isn't listed, the call fails, or spend passes the ceiling |

## How each GDPR principle is met

| Principle | Article | How the lane meets it |
|---|---|---|
| Lawfulness, fairness, transparency | Art. 5(1)(a), Art. 6 | The only user is the account holder (`ALLOWED_EMAILS`), whose own study data this is and who has asked for this processing: Art. 6(1)(a) consent, given 2026-09-30. Names of lecturers, authors and case parties that appear in course material are already public and incidental; processing them is covered by legitimate interest in studying the material (Art. 6(1)(f)). This document is the transparency record. |
| Purpose limitation | Art. 5(1)(b) | A closed allow-list of four bulk study tasks, enforced in code (`gateway.allows`). Material is sent only to produce flashcards, concepts, a syllabus reading or viva questions. It is not used for anything else, and the tutor never uses the lane. |
| Data minimisation | Art. 5(1)(c) | Only the single note or file the task needs is sent, never the whole course or the chat history. Before sending, e-mail addresses, phone numbers, IBANs and student numbers are replaced with placeholders (`gateway.minimise`); none of them helps make a flashcard. Legal citations, dates and case numbers are kept (tests guard this). |
| Accuracy | Art. 5(1)(d) | Outputs are study aids that the user checks, not records about a person. The existing quote-check on concept extraction still applies. |
| Storage limitation | Art. 5(1)(e) | Every request carries `no-log: true`, which asks the gateway not to store prompts or responses. **Open item 1.** |
| Integrity and confidentiality | Art. 5(1)(f), Art. 32 | TLS to the gateway. The gateway key sits in Google Secret Manager (EU region) and is read from the environment only (CLAUDE.md, "Secrets and data"). It is never logged. |
| Accountability | Art. 5(2) | Every call's usage record is labelled `provider: gateway` with its model and cost. This record and the tests document the design. |
| Data protection by design and by default | Art. 25 | Off by default: the lane needs the key **and** a spend ceiling (`CF_GATEWAY_SPEND_CEILING`). `CF_GATEWAY=off` turns it off without a deploy. Any failure falls back to Anthropic rather than retrying elsewhere. |
| Processors | Art. 28 | The gateway operator acts as a processor; the model provider behind it (OpenAI for `gpt-6-luna`) is a sub-processor. **Open item 2.** |
| International transfers | Art. 44–46 | `gpt-6-luna` is most likely served outside the EU. A transfer needs an adequacy decision (Art. 45, e.g. the EU–US Data Privacy Framework for a certified recipient) or standard contractual clauses (Art. 46(2)(c)). **Open item 3.** |
| Special categories | Art. 9 | None are expected in study notes. Redaction does not detect them, so health or similar details should stay out of notes that are made into flashcards. |
| Data subject rights | Art. 15–17 | The originals stay in CognitioFlow's own database, where access and erasure already work. Nothing should remain at the gateway (see open item 1). |
| DPIA | Art. 35 | Not required: one user, their own study material, no profiling, no special categories, no systematic monitoring. Reassess if other users are added (multi-user is planned). |

## Open items (verify before relying on the lane for anything sensitive)

1. **No-log is honoured.** The gateway accepts the `no-log` flag (tested 2026-09-30). Whether its
   operator's configuration honours it, and how long any request logs are kept, can only be confirmed by
   the operator.
2. **Processor terms.** Confirm with the gateway operator (the key holder) that its terms with its
   upstream providers cover Art. 28(3): processing only on instructions, confidentiality, security,
   sub-processors, deletion at the end.
3. **Transfer basis.** Confirm where `gpt-6-luna` is served and on which basis (DPF certification or SCCs).
   If no EU-served or adequately covered route exists, restrict `CF_GATEWAY_TASKS` to `syllabus`, which
   carries course material only, or set `CF_GATEWAY=off`.

## Configuration

| Variable | Meaning |
|---|---|
| `LITELLM_API_KEY` | gateway key (Secret Manager) |
| `CF_GATEWAY_SPEND_CEILING` | the lane turns itself off once the key's total spend (the `x-litellm-key-spend` header) reaches this many dollars. The key is shared with other tools, so this caps them all: set it to *current total + monthly budget* and raise it at the start of each month |
| `CF_GATEWAY_TASKS` | allow-list; default `cards,concepts,syllabus,oral` |
| `CF_GATEWAY` | `off` to disable |
| `CF_GATEWAY_MODEL`, `CF_GATEWAY_BASE` | model and gateway URL |
