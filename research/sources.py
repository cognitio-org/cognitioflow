"""The source registry — what Lector reads, and why each source earns its place.

This module is data. It makes no network calls, so the registry can be printed, reviewed,
diffed and tested without touching the wire. `lector.py` does the fetching; `adapters.py`
turns each reply into records.

Every entry carries the two things a research agent is useless without:

- `authority` — where the source sits in an evidence hierarchy, the same idea CognitioFlow
  already applies to course material (annotated WG notes > lecture > slides > Schutze).
  1 is binding or primary, 5 is un-reviewed commentary. A brief that cannot tell a judgment
  from a blog post is not a brief.
- `terms` — what the publisher's access policy actually requires. Every source here is open
  or officially free. Nothing in this registry scrapes a paywall, bypasses a login, or
  ignores a robots policy, and nothing licensed to the university through RUG is piped into
  an agent store.
"""

from dataclasses import dataclass, field

# Tracks. One agent, three reading lists.
QUANT = "quant"    # market structure, asset pricing, and the methods that falsify both
LEGAL = "legal"    # primary law and public records — the investigation/reporting side hustle
SYSTEM = "system"  # the literature CognitioFlow itself is built on: memory, retrieval, eval


@dataclass(frozen=True)
class Source:
    """One place Lector reads from."""

    id: str
    name: str
    track: str
    kind: str          # papers | filings | caselaw | legislation | register | regulatory | data
    authority: int     # 1 binding/primary .. 5 un-reviewed
    why: str           # why this source is on the list at all
    endpoint: str = ""  # {since} {rows} {query} are filled in by lector.py
    fmt: str = "json"   # json | atom
    extract: str = "manual"   # adapter name in adapters.py; "manual" = registered, not fetched
    terms: str = ""
    rate_s: float = 1.0       # minimum seconds between requests to this host
    needs_key: bool = False
    verify: bool = False      # endpoint shape not verified against the live API yet
    tags: tuple = field(default_factory=tuple)

    @property
    def fetchable(self) -> bool:
        return self.extract != "manual" and not self.needs_key


# --------------------------------------------------------------------------------------
# Track A — quant. The point of this track is not signals. It is knowing which signals died.
# --------------------------------------------------------------------------------------

_QUANT = [
    Source(
        id="arxiv-qfin",
        name="arXiv q-fin (ST, PM, TR, RM)",
        track=QUANT,
        kind="papers",
        authority=5,
        why="Method moves here first, months before a journal. Un-reviewed, so it is a source "
            "of hypotheses and of critiques — never of conclusions.",
        endpoint="https://export.arxiv.org/api/query?search_query="
                 "cat:q-fin.ST+OR+cat:q-fin.PM+OR+cat:q-fin.TR+OR+cat:q-fin.RM"
                 "&sortBy=submittedDate&sortOrder=descending&max_results={rows}",
        fmt="atom",
        extract="arxiv",
        terms="Open access. arXiv asks for <1 request per 3s and a real User-Agent.",
        rate_s=3.0,
        tags=("preprint", "frontier"),
    ),
    Source(
        id="arxiv-ml-methods",
        name="arXiv stat.ML / cs.LG applied to finance",
        track=QUANT,
        kind="papers",
        authority=5,
        why="Where the backtest-overfitting, purged cross-validation and deflated-Sharpe work "
            "lives. The discipline layer, not the signal layer.",
        endpoint="https://export.arxiv.org/api/query?search_query="
                 "abs:%22backtest%20overfitting%22+OR+abs:%22deflated%20Sharpe%22"
                 "+OR+abs:%22purged%20cross-validation%22"
                 "&sortBy=submittedDate&sortOrder=descending&max_results={rows}",
        fmt="atom",
        extract="arxiv",
        terms="Open access. Same rate limit as above.",
        rate_s=3.0,
        tags=("methodology", "falsification"),
    ),
    Source(
        id="openalex-replication",
        name="OpenAlex — replication and out-of-sample studies in finance",
        track=QUANT,
        kind="papers",
        authority=2,
        why="The single highest-value stream on this list. Hou/Xue/Zhang, Harvey/Liu/Zhu and "
            "McLean/Pontiff are why most published predictors should be assumed dead until "
            "shown otherwise. This query keeps that literature arriving.",
        endpoint="https://api.openalex.org/works?filter=from_publication_date:{since},"
                 "title_and_abstract.search:replication%20OR%20out-of-sample%20OR%20"
                 "%22factor%20zoo%22%20OR%20%22multiple%20testing%22"
                 "&sort=publication_date:desc&per-page={rows}",
        extract="openalex",
        terms="CC0 metadata. Polite pool: send a mailto in the User-Agent.",
        rate_s=1.0,
        tags=("replication", "falsification", "high-value"),
    ),
    Source(
        id="crossref-jfe",
        name="Crossref — Journal of Financial Economics",
        track=QUANT,
        kind="papers",
        authority=2,
        why="Peer-reviewed anchor. Metadata is open even where the article is not, which is "
            "enough to decide whether the article is worth the library's copy.",
        endpoint="https://api.crossref.org/works?filter=issn:0304-405X,"
                 "from-pub-date:{since}&sort=published&order=desc&rows={rows}",
        extract="crossref",
        terms="Open metadata. Polite pool requires a mailto in the User-Agent.",
        rate_s=1.0,
        tags=("peer-reviewed",),
    ),
    Source(
        id="crossref-retractions",
        name="Crossref — retraction and correction notices",
        track=QUANT,
        kind="papers",
        authority=1,
        why="A retracted finance paper is worse than no paper, because it arrives with a "
            "citation count. The Retraction Watch database became CC0 through Crossref in "
            "2023; checking it costs one request and prevents building on a withdrawn result.",
        endpoint="https://api.crossref.org/works?filter=type:retraction,"
                 "from-created-date:{since}&sort=created&order=desc&rows={rows}",
        extract="crossref",
        terms="CC0. Polite pool as above.",
        rate_s=1.0,
        tags=("integrity", "high-value"),
    ),
    Source(
        id="openalex-macro",
        name="OpenAlex — monetary policy transmission and term structure",
        track=QUANT,
        kind="papers",
        authority=2,
        why="The regime layer. Whether a cross-sectional signal works this decade is mostly a "
            "question about policy and liquidity, not about the signal.",
        endpoint="https://api.openalex.org/works?filter=from_publication_date:{since},"
                 "title_and_abstract.search:%22monetary%20policy%22%20OR%20%22term%20structure%22"
                 "%20OR%20%22liquidity%20premium%22"
                 "&sort=publication_date:desc&per-page={rows}",
        extract="openalex",
        terms="CC0 metadata. Polite pool.",
        rate_s=1.0,
        tags=("macro", "regime"),
    ),
    Source(
        id="sec-edgar-submissions",
        name="SEC EDGAR — structured submissions (data.sec.gov)",
        track=QUANT,
        kind="filings",
        authority=1,
        why="Primary-source fundamentals with exact filing timestamps, free and officially "
            "supported. This is where the quant track and the investigation track are "
            "literally the same request.",
        endpoint="https://data.sec.gov/submissions/CIK{query}.json",
        extract="sec_submissions",
        terms="Fair-access policy: declare a real User-Agent with contact details, <=10 req/s.",
        rate_s=0.2,
        verify=True,
        tags=("primary", "crossover"),
    ),
    Source(
        id="osap-chen-zimmermann",
        name="Open Source Asset Pricing (Chen & Zimmermann)",
        track=QUANT,
        kind="data",
        authority=2,
        why="200+ published predictors with replication code and signal data. Turns 'read a "
            "paper' into 'run the factor and see the decay for yourself'. Registered rather "
            "than polled: it is a versioned dataset, not a feed.",
        terms="Open dataset, cite the authors. Download manually, refresh on release.",
        tags=("dataset", "replication", "high-value"),
    ),
    Source(
        id="bis-ecb-fed-wp",
        name="BIS / ECB / Federal Reserve working papers",
        track=QUANT,
        kind="papers",
        authority=2,
        why="Central-bank research is the closest thing to a primary source on liquidity, "
            "market structure and stress. Free, and reaches the market before academia does.",
        terms="Open access. Each bank publishes its own RSS; register per-bank feeds on first run.",
        verify=True,
        tags=("macro", "regime"),
    ),
]

# --------------------------------------------------------------------------------------
# Track B — legal. Primary law and public records: the billable half.
# --------------------------------------------------------------------------------------

_LEGAL = [
    Source(
        id="rechtspraak",
        name="Rechtspraak.nl Open Data — Dutch judgments",
        track=LEGAL,
        kind="caselaw",
        authority=1,
        why="Full text of Dutch case law, complete, official and genuinely free through an "
            "open API. Almost no other jurisdiction offers this. You are in NL — this is the "
            "single most valuable source on the legal track.",
        endpoint="https://data.rechtspraak.nl/uitspraken/zoeken?type=Uitspraak"
                 "&date={since}&max={rows}&sort=DESC",
        fmt="atom",
        extract="rechtspraak",
        terms="Open data, free reuse with attribution. Bulk downloads have their own endpoint.",
        rate_s=1.0,
        verify=True,
        tags=("primary", "netherlands", "high-value"),
    ),
    Source(
        id="eurlex-cellar",
        name="EUR-Lex / Cellar — EU legislation, case law and preparatory acts",
        track=LEGAL,
        kind="legislation",
        authority=1,
        why="Your course domain and your billable domain are the same corpus. Official, "
            "machine-readable through ELI/CDM, and free. Registered as a SPARQL endpoint "
            "because a useful query here is written per question, not polled blindly.",
        endpoint="https://publications.europa.eu/webapi/rdf/sparql",
        terms="Open reuse under the EU legal notice. SPARQL endpoint, be gentle with it.",
        verify=True,
        tags=("primary", "eu", "course-overlap", "high-value"),
    ),
    Source(
        id="curia",
        name="CURIA — Court of Justice judgments and AG opinions",
        track=LEGAL,
        kind="caselaw",
        authority=1,
        why="The authority your tutor already ranks at the top for EU law. AG opinions are "
            "where the reasoning is visible before the Court compresses it.",
        terms="Official publication, free to read. Reachable through EUR-Lex identifiers.",
        tags=("primary", "eu", "course-overlap"),
    ),
    Source(
        id="officiele-bekendmakingen",
        name="officielebekendmakingen.nl / wetten.overheid.nl (SRU)",
        track=LEGAL,
        kind="legislation",
        authority=1,
        why="Dutch legislation and the official gazettes, with an SRU search API. What "
            "changed, when, and in whose name — the spine of any Dutch regulatory memo.",
        terms="Open government data, free reuse.",
        verify=True,
        tags=("primary", "netherlands"),
    ),
    Source(
        id="gleif-lei",
        name="GLEIF — Legal Entity Identifier registry",
        track=LEGAL,
        kind="register",
        authority=1,
        why="Resolves the same company across jurisdictions, which is the hard part of any "
            "due-diligence report. Fully open, CC0, no key, global coverage.",
        endpoint="https://api.gleif.org/api/v1/lei-records?filter%5Bentity.legalName%5D={query}"
                 "&page%5Bsize%5D={rows}",
        extract="gleif",
        terms="CC0. No key required.",
        rate_s=1.0,
        verify=True,
        tags=("entity-resolution", "due-diligence", "high-value"),
    ),
    Source(
        id="eu-sanctions",
        name="EU consolidated financial sanctions list",
        track=LEGAL,
        kind="register",
        authority=1,
        why="Screening is the most commoditised and most reliably billable task in this whole "
            "field, and the authoritative list is free. Official EU publication.",
        terms="Free public list; the EC download endpoint expects a registered token.",
        needs_key=True,
        tags=("sanctions", "due-diligence", "billable"),
    ),
    Source(
        id="ofac-sdn",
        name="OFAC — Specially Designated Nationals list",
        track=LEGAL,
        kind="register",
        authority=1,
        why="The US half of the same screening job. Published by Treasury as structured XML, "
            "free, no key.",
        terms="US government work, public domain.",
        verify=True,
        tags=("sanctions", "due-diligence", "billable"),
    ),
    Source(
        id="courtlistener",
        name="CourtListener / RECAP — US federal court records",
        track=LEGAL,
        kind="caselaw",
        authority=1,
        why="A counterparty's US litigation history, free, where PACER charges per page. "
            "Run by a non-profit with an explicit API policy.",
        endpoint="https://www.courtlistener.com/api/rest/v4/search/?q={query}&type=o"
                 "&filed_after={since}&order_by=dateFiled%20desc",
        extract="courtlistener",
        terms="Free API, token required for most endpoints. Respect the documented rate limits.",
        needs_key=True,
        tags=("litigation", "due-diligence"),
    ),
    Source(
        id="federal-register",
        name="Federal Register API — US rulemaking",
        track=LEGAL,
        kind="regulatory",
        authority=1,
        why="'What changed this week in X regulation' is a subscription product people pay "
            "for. On free official feeds it is a daily diff.",
        endpoint="https://www.federalregister.gov/api/v1/documents.json"
                 "?conditions%5Bpublication_date%5D%5Bgte%5D={since}"
                 "&per_page={rows}&order=newest",
        extract="federal_register",
        terms="US government work, public domain. No key.",
        rate_s=1.0,
        tags=("regulatory", "billable"),
    ),
    Source(
        id="kvk-bris",
        name="KVK Handelsregister / EU Business Registers (BRIS)",
        track=LEGAL,
        kind="register",
        authority=1,
        why="Who owns what and who directs it — the spine of a due-diligence report. Note "
            "honestly: KVK's API is paid per query, and after CJEU C-37/20 (WM and Sovim, "
            "2022) general public access to UBO registers was struck down. Knowing that "
            "constraint is exactly the edge a law student has over a generic OSINT tool.",
        terms="Paid API key; UBO access restricted by CJEU C-37/20. Do not route around it.",
        needs_key=True,
        tags=("due-diligence", "netherlands", "legal-constraint"),
    ),
    Source(
        id="doaj",
        name="DOAJ — open-access legal scholarship",
        track=LEGAL,
        kind="papers",
        authority=3,
        why="Open-access journals only, so everything it returns can actually be read and "
            "quoted without a licence question.",
        endpoint="https://doaj.org/api/search/articles/{query}?pageSize={rows}",
        extract="doaj",
        terms="Open API, attribution requested.",
        rate_s=1.0,
        verify=True,
        tags=("open-access",),
    ),
]

# --------------------------------------------------------------------------------------
# Track C — the intelligence of the system itself. CognitioFlow is a memory application;
# this track is the evidence base for whether it actually works.
# --------------------------------------------------------------------------------------

_SYSTEM = [
    Source(
        id="openalex-spacing",
        name="OpenAlex — spacing effect, retrieval practice, testing effect",
        track=SYSTEM,
        kind="papers",
        authority=2,
        why="`schedule.py` and the `reviews` table implement this literature whether or not "
            "anyone read it. Cepeda's spacing work and Roediger/Karpicke on testing are the "
            "direct evidence base for the scheduler.",
        endpoint="https://api.openalex.org/works?filter=from_publication_date:{since},"
                 "title_and_abstract.search:%22spacing%20effect%22%20OR%20"
                 "%22retrieval%20practice%22%20OR%20%22testing%20effect%22"
                 "&sort=publication_date:desc&per-page={rows}",
        extract="openalex",
        terms="CC0 metadata. Polite pool.",
        rate_s=1.0,
        tags=("memory", "scheduler", "high-value"),
    ),
    Source(
        id="arxiv-eval",
        name="arXiv — LLM evaluation, judge reliability, retrieval evaluation",
        track=SYSTEM,
        kind="papers",
        authority=5,
        why="The Board Examiner grades tutor answers and `tutor_eval.py` grades the tutor. If "
            "the judge is unreliable the whole fleet optimises against noise — which is the "
            "expensive failure mode, because it looks like progress.",
        endpoint="https://export.arxiv.org/api/query?search_query="
                 "abs:%22LLM-as-a-judge%22+OR+abs:%22evaluation%20of%20retrieval%22"
                 "+OR+abs:%22rubric%20grading%22"
                 "&sortBy=submittedDate&sortOrder=descending&max_results={rows}",
        fmt="atom",
        extract="arxiv",
        terms="Open access. <1 request per 3s.",
        rate_s=3.0,
        tags=("eval", "high-value"),
    ),
    Source(
        id="legal-benchmarks",
        name="LegalBench / CaseHOLD / LexGLUE",
        track=SYSTEM,
        kind="data",
        authority=2,
        why="An objective read on whether the tutor's legal reasoning is any good, instead of "
            "a vibe. Registered as datasets: they move on release, not daily.",
        terms="Open datasets under their own licences; check each before redistribution.",
        tags=("eval", "dataset", "legal"),
    ),
    Source(
        id="fsrs",
        name="FSRS — open spaced-repetition algorithm and datasets",
        track=SYSTEM,
        kind="data",
        authority=3,
        why="An openly published, openly benchmarked scheduler with real review logs behind "
            "it. The obvious comparator for whatever `schedule.py` currently does.",
        terms="Open source and open data; check the dataset licence before reuse.",
        tags=("scheduler", "memory"),
    ),
]

SOURCES = tuple(_QUANT + _LEGAL + _SYSTEM)

BY_ID = {s.id: s for s in SOURCES}
TRACKS = (QUANT, LEGAL, SYSTEM)


def for_track(track: str) -> tuple:
    """Every source on one track, registered or fetchable."""
    return tuple(s for s in SOURCES if s.track == track)


def fetchable(track: str = "") -> tuple:
    """Sources lector.py can actually poll right now — no key needed, adapter written."""
    pool = SOURCES if not track else for_track(track)
    return tuple(s for s in pool if s.fetchable)
