# Lector — the reading agent

Scriptorium copies. Claude decides. Matej ships. **Lector reads.**

The swarm has scribes and it has judgement, and it had no way to bring anything in from
outside. Lector is that: a routine that wakes daily, polls open academic and public-record
APIs, ranks what comes back for *evidence quality* as well as relevance, and writes an
80-column panel the CommandTerminal can show as a lane.

It is fleet tooling, not application code. It is the same category of thing as
`docs/AI_WORKFLOW_HANDOFF.md`: it describes and serves the machine that builds CognitioFlow,
not CognitioFlow itself. It touches no seam, no migration, no route, and nothing in `run.py` or
`static/index.html`.

```
research/lector.py --list      the registry, with a stated reason per source
research/lector.py --check     probe every endpoint, report what answers
research/lector.py --once      one harvest; writes feed.json and digest.txt
research/lector.py --render    redraw the panel from the stored feed
```

State lives in `~/.cognitio/lector/`. The code lives here, under version control — deliberately
the opposite way round from the other three daemons, which the handoff correctly calls the
biggest single risk in the fleet.

---

## Read this before trusting a number

**Academic finance research does not give you market prediction, and an agent that implies
otherwise is worse than no agent.** That is not hedging; it is the strongest finding in the
field:

- McLean and Pontiff measured published anomaly returns decaying roughly **26%** between the
  end of a paper's sample and its publication, and a further **32%** after publication. The act
  of publishing a signal is part of what kills it.
- Hou, Xue and Zhang replicated the cross-sectional literature at scale and **could not
  reproduce the majority** of it under consistent methodology.
- Harvey, Liu and Zhu argued that because hundreds of factors have been tried, the t-statistic
  hurdle for accepting a *new* one should be about **3.0, not 2.0** — most of the "discovered"
  factor zoo does not clear it.

So this agent is not built to find alpha. It is built to do the four things the literature
genuinely supports:

1. **Tell you which signals are already dead**, so you do not rediscover them.
2. **Give you the methodology that stops you fooling yourself** — holdouts, purged
   cross-validation, deflated Sharpe, multiple-testing correction.
3. **Track the regime** — policy, liquidity and market structure, which determine whether any
   cross-sectional signal works this decade.
4. **Reach primary sources legitimately**, which is the part that transfers directly to paid
   investigation work.

The scoring function encodes this. A replication study *outranks* a Sharpe-4.1 preprint by a
wide margin, and a performance claim with no holdout vocabulary anywhere near it is flagged
`NO-OOS` and pushed down. This is checked by a test, not by good intentions.

---

## Track A — quant

*Nine sources. The point of the track is knowing which signals died, not finding new ones.*

| Source | Rank | Why it earns its place |
|---|---|---|
| **OpenAlex — replication & out-of-sample studies** | 2 | The highest-value stream on the whole list. Keeps the falsification literature arriving: replications, factor-zoo audits, multiple-testing corrections. If you read one thing, read this one. |
| **Crossref — retraction notices** | 1 | A retracted finance paper is worse than no paper, because it arrives with a citation count. The Retraction Watch database went CC0 through Crossref in 2023. One request, and it stops you building on a withdrawn result. |
| **arXiv q-fin (ST/PM/TR/RM)** | 5 | Method moves here months before a journal. Un-reviewed, so it is a source of hypotheses and critiques, never of conclusions — flagged `PREPRINT` on sight. |
| **arXiv — backtest overfitting, deflated Sharpe, purged CV** | 5 | The discipline layer. This is the stream that stops you shipping an overfit model, which for a solo quant is the only failure mode that actually matters. |
| **Crossref — Journal of Financial Economics** | 2 | Peer-reviewed anchor. Metadata is open even where the article is not, which is enough to decide whether the article is worth fetching through the RUG library. |
| **OpenAlex — monetary policy & term structure** | 2 | The regime layer. Whether a cross-sectional signal works this decade is mostly a question about policy and liquidity, not about the signal. |
| **SEC EDGAR — structured submissions** | 1 | Primary-source fundamentals with exact filing timestamps, free and officially supported. **This is where the two halves of the ask are literally the same HTTP request.** |
| **Open Source Asset Pricing (Chen & Zimmermann)** | 2 | 200+ published predictors with replication code and signal data. Turns "read a paper" into "run the factor and watch the decay yourself". Registered as a dataset, refreshed on release. |
| **BIS / ECB / Fed working papers** | 2 | Central-bank research is the closest thing to a primary source on liquidity and stress, and it reaches the market before academia does. |

**Why this helps the quant theory, concretely.** It gives you a standing, dated record of what
has been tried and what survived — which is the input a factor model actually needs and the one
you cannot get from a data vendor. Every signal you consider arrives with its replication
status attached, its decay estimate, and a flag if its authors never held anything out. That
turns "I have an idea" into "this was tried in 2019, decayed 40% post-publication, and failed
to replicate in 2023" before you spend a weekend on it. The regime sources tell you whether the
conditions the original paper ran under still hold. None of that predicts the market. All of it
stops you paying to learn things that are already in the literature for free.

---

## Track B — legal

*Eleven sources. Primary law and public records: the billable half.*

| Source | Rank | Why it earns its place |
|---|---|---|
| **Rechtspraak.nl Open Data** | 1 | Full text of Dutch case law — complete, official, genuinely free, real API. Almost no other jurisdiction offers this. You are in NL: this is the most valuable single source on the legal track. |
| **EUR-Lex / Cellar (SPARQL)** | 1 | Your course domain and your billable domain are the same corpus. Official, machine-readable through ELI/CDM, free. |
| **CURIA — CJEU judgments and AG opinions** | 1 | The authority your tutor already ranks top for EU law. AG opinions show the reasoning before the Court compresses it. |
| **officielebekendmakingen.nl / wetten.overheid.nl** | 1 | Dutch legislation and the official gazettes, searchable over SRU. What changed, when, and in whose name — the spine of any Dutch regulatory memo. |
| **GLEIF — LEI registry** | 1 | Resolves the same company across jurisdictions, which is the genuinely hard part of due diligence. Fully open, CC0, no key, global. |
| **EU consolidated sanctions list** | 1 | Screening is the most commoditised and most reliably billable task in the field, and the authoritative list is free. |
| **OFAC SDN list** | 1 | The US half of the same job. Treasury publishes it as structured XML, public domain. |
| **Federal Register API** | 1 | "What changed this week in X regulation" is a paid subscription product. On free official feeds it is a daily diff. |
| **CourtListener / RECAP** | 1 | A counterparty's US litigation history, free, where PACER charges per page. Needs a free token. |
| **KVK / EU Business Registers (BRIS)** | 1 | Who owns what and who directs it. Registered *with its constraints stated*: the KVK API is paid per query, and after **CJEU C-37/20 (WM and Sovim, 2022)** general public access to UBO registers was struck down. |
| **DOAJ** | 3 | Open-access journals only, so everything it returns can be read and quoted without a licence question. |

**Why this helps the side hustle, concretely.** Paid investigation and reporting work — due
diligence, litigation support, sanctions screening, regulatory monitoring — is mostly the same
four steps every time: find the primary source, retrieve it legitimately, date-stamp and cite
it so it survives challenge, and rank how much weight it bears. Those four steps are exactly
what this registry automates the tedious half of. The differentiator you have over a generic
OSINT tool is not access; these sources are public. It is knowing what the sources *mean* and
where they stop — that C-37/20 closed public UBO access, that an AG opinion is not a judgment,
that a Form 4 has a filing deadline you can test against. That is a law student's edge, and
Lector is built to put the primary text in front of it rather than to replace it.

The KVK line is the template for how this registry handles a legal constraint: it is recorded,
with the case that created it, and the tooling does not route around it. An investigator who
cannot say why a source is closed is not one anybody should pay.

---

## Track C — the intelligence of the system

*Four sources. CognitioFlow is a memory application; this is the evidence base for whether it
works.*

| Source | Rank | Why it earns its place |
|---|---|---|
| **OpenAlex — spacing effect, retrieval practice, testing effect** | 2 | `schedule.py` and the `reviews` table implement this literature whether or not anyone read it. Cepeda on spacing and Roediger/Karpicke on the testing effect are the direct evidence base for the scheduler. |
| **arXiv — LLM evaluation, judge reliability** | 5 | The Board Examiner grades tutor answers and `tutor_eval.py` grades the tutor. If the judge is unreliable the fleet optimises against noise — the expensive failure, because it looks like progress. |
| **LegalBench / CaseHOLD / LexGLUE** | 2 | An objective read on whether the tutor's legal reasoning is any good, instead of a vibe. |
| **FSRS** | 3 | An openly published, openly benchmarked scheduler with real review logs behind it — the obvious comparator for whatever `schedule.py` does today. |

This is the track the other two pay for. A measurable improvement to the scheduler compounds
across every hour of study; a better eval harness is what stops the swarm shipping regressions
its own reviewer passed, which the handoff records happening twice on 19 September.

---

## Why one agent, and not three

Because all three tracks are the same pipeline, and the app already has the vocabulary for it.

CognitioFlow ranks its course material — annotated WG notes > lecture > slides > Schütze — and
labels anything outside the ticked files `[OUTSIDE FILES]`. That is an authority hierarchy with
provenance tags, which is precisely what an investigator needs and precisely what a quant
reading the factor literature needs. So Lector reuses it rather than inventing a second one:
every record carries an `authority` rank from its source, and every record carries flags that
say what is wrong with it.

The scoring function rewards records that serve two tracks at once (`CROSSOVER`) and records
that touch the courses Matej actually sits exams in (`COURSE`). Securities disclosure,
enforcement, market abuse and financial reporting all score on both the quant and legal tracks,
because one read genuinely does two jobs there.

### The flags

Every record on the panel carries a glyph as well as a colour, because colour is never the only
signal:

| Flag | Glyph | Meaning |
|---|---|---|
| `REPLICATION` | `✓` | Checks someone else's homework. Scores **up** — this is the good kind of paper. |
| `RETRACTED` | `!` | Withdrawn or corrected. Scores **up**, because you must see it precisely because it is wrong. |
| `NO-OOS` | `~` | A performance claim with no holdout vocabulary anywhere near it. Scores **down**. |
| `MULTI-TEST` | `~` | Claims about many signals with no nod to multiple testing. Scores **down**. |
| `CROSSOVER` | `+` | Serves the quant and legal tracks at once. |
| `COURSE` | `*` | Overlaps the exam material. |
| `PREPRINT` | `·` | Not peer-reviewed. |

---

## What Lector does not do

- **It calls no model.** Retrieval, de-duplication and ranking are cheaper and more reliable as
  plain code than as tokens. The panel costs nothing per run. A Claude agent gets spawned only
  when a record has earned a real read — see `.claude/agents/lector.md`. Talking to Mission
  Control is not free and this does not add to the bill.
- **It sends nothing out.** Every source is public by construction. No note, card, `data/`
  file or database row is ever sent anywhere; a test asserts every request is a plain GET. This
  is the same rule the swarm's `Private: yes` guard enforces, kept by construction rather than
  by a check.
- **It bypasses nothing.** No paywall, no login, no robots policy. `Source.terms` records what
  each publisher asks in return for free access, and sources needing a key are registered,
  visible and excluded from the routine rather than quietly skipped.
- **It gives no advice.** Not investment advice, not legal advice. It reports what was found
  and how well it was tested.

## Honest status

**None of these endpoints has been verified against the live API.** This was built in a
container whose network policy refused every one of the hosts outright — `api.openalex.org`,
`export.arxiv.org`, `api.crossref.org` and the rest all returned a 403 at CONNECT. The adapters
are therefore tested against saved fixtures of the shape each API documents, which catches a
parsing bug but not a wrong URL.

`--list` marks every unverified endpoint with `?`. Verify them in one pass on the Mac before
trusting a single result:

```bash
python3 research/lector.py --check
```

Expect some to need adjusting — `rechtspraak`, `gleif`, `sec-edgar-submissions`,
`officiele-bekendmakingen`, `doaj` and the EUR-Lex SPARQL endpoint are the ones most likely to
have drifted from what is written here.

## Tests

```bash
python3 -m pytest research/ -q        # 33 tests, no database, no network
```

They are in `research/` rather than `tests/` on purpose: `tests/conftest.py` opens a Postgres
connection for the whole session and nothing here needs one. `scripts/check.sh` runs them, so
Gate 1 covers this code even when docker is down.
