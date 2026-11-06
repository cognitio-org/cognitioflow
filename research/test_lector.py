"""Lector's tests. No database, no network — run them with `python3 -m pytest research/`.

They live here rather than in `tests/` on purpose: `tests/conftest.py` opens a Postgres
connection for the whole session, and nothing Lector does needs one. Keeping these DB-free
means Gate 1 can run them even when docker is down.

Every adapter is checked against a saved fixture of the shape the API actually returns. That
is the only defence against an upstream field being renamed and a harvester quietly reporting
zero results forever.
"""

import datetime as dt
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import adapters
import lector
import scoring
import sources

TODAY = dt.date(2026, 9, 19)


# ------------------------------------------------------------------ the registry

def test_every_source_has_a_reason():
    """A source with no stated reason is a source nobody can argue with. Not allowed."""
    for source in sources.SOURCES:
        assert len(source.why) > 40, f"{source.id} needs a real justification"
        assert 1 <= source.authority <= 5, f"{source.id} has no evidence rank"
        assert source.track in sources.TRACKS


def test_every_fetchable_source_has_an_adapter_and_an_endpoint():
    for source in sources.fetchable():
        assert source.endpoint, f"{source.id} is fetchable with no endpoint"
        assert source.extract in adapters.ADAPTERS, f"{source.id} names a missing adapter"


def test_source_ids_are_unique():
    ids = [s.id for s in sources.SOURCES]
    assert len(ids) == len(set(ids))


def test_all_three_tracks_are_populated():
    for track in sources.TRACKS:
        assert len(sources.for_track(track)) >= 3
        assert sources.fetchable(track), f"{track} has nothing that can be polled"


def test_keyed_sources_are_never_polled_silently():
    """A source needing a key must be registered, visible, and excluded from the routine."""
    keyed = [s for s in sources.SOURCES if s.needs_key]
    assert keyed, "the registry should be honest about what costs money or needs an account"
    for source in keyed:
        assert source not in sources.fetchable()
        assert source.terms, f"{source.id} must say what it needs"


# ------------------------------------------------------------------ adapters

ARXIV = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <id>http://arxiv.org/abs/2609.01234v1</id>
  <published>2026-09-15T10:00:00Z</published>
  <title>Out-of-sample decay in
   published equity anomalies</title>
  <summary>We test 120 published predictors
   out of sample.</summary>
  <author><name>A Researcher</name></author>
  <author><name>B Coauthor</name></author>
 </entry>
</feed>"""

OPENALEX = json.dumps({"results": [{
    "id": "https://openalex.org/W123",
    "display_name": "Replication of the factor zoo",
    "publication_date": "2026-09-10",
    "doi": "https://doi.org/10.1234/abc",
    "authorships": [{"author": {"display_name": "C Author"}}],
    "primary_location": {"source": {"display_name": "Journal of Finance"}},
    "abstract_inverted_index": {"We": [0], "fail": [1], "to": [2], "replicate": [3]},
}]}).encode()

CROSSREF = json.dumps({"message": {"items": [{
    "DOI": "10.1016/j.jfineco.2026.01.001",
    "title": ["Liquidity and the cross-section"],
    "URL": "https://doi.org/10.1016/j.jfineco.2026.01.001",
    "published-print": {"date-parts": [[2026, 9, 1]]},
    "author": [{"given": "D", "family": "Writer"}],
    "abstract": "<jats:p>We study <jats:italic>liquidity</jats:italic>.</jats:p>",
    "container-title": ["Journal of Financial Economics"],
}]}}).encode()

FEDREG = json.dumps({"results": [{
    "document_number": "2026-12345",
    "title": "Rule on beneficial ownership reporting",
    "html_url": "https://www.federalregister.gov/d/2026-12345",
    "publication_date": "2026-09-18",
    "abstract": "FinCEN amends the reporting rule.",
    "agencies": [{"name": "Financial Crimes Enforcement Network"}],
}]}).encode()

GLEIF = json.dumps({"data": [{
    "id": "5493001KJTIIGC8Y1R12",
    "attributes": {
        "entity": {"legalName": {"name": "Example Holding B.V."},
                   "status": "ACTIVE", "legalAddress": {"country": "NL"}},
        "registration": {"lastUpdateDate": "2026-09-01T00:00:00Z"},
    },
}]}).encode()

SEC = json.dumps({
    "cik": 320193, "name": "Apple Inc.",
    "filings": {"recent": {
        "accessionNumber": ["0000320193-26-000077"],
        "filingDate": ["2026-08-01"], "reportDate": ["2026-06-28"],
        "form": ["10-Q"], "primaryDocument": ["aapl-20260628.htm"],
        "primaryDocDescription": ["10-Q"],
    }},
}).encode()

COURTLISTENER = json.dumps({"results": [{
    "id": 998877, "caseName": "Acme Corp v. Doe",
    "absolute_url": "/opinion/998877/acme-corp-v-doe/",
    "dateFiled": "2026-09-12", "court": "S.D.N.Y.", "snippet": "Securities fraud claim.",
}]}).encode()

RECHTSPRAAK = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <id>ECLI:NL:HR:2026:1234</id>
  <title>Hoge Raad, eigendomsoverdracht</title>
  <updated>2026-09-16T00:00:00Z</updated>
  <link href="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2026:1234"/>
  <summary>Overdracht van eigendom.</summary>
 </entry>
</feed>"""

DOAJ = json.dumps({"results": [{
    "id": "doaj-1",
    "bibjson": {"title": "Sanctions compliance in the EU", "year": "2026",
                "author": [{"name": "E Scholar"}], "abstract": "On screening duties.",
                "journal": {"title": "Open Law Review"},
                "link": [{"url": "https://example.org/article"}]},
}]}).encode()

CASES = [
    ("arxiv-qfin", ARXIV, "Out-of-sample decay in published equity anomalies", "2026-09-15"),
    ("openalex-replication", OPENALEX, "Replication of the factor zoo", "2026-09-10"),
    ("crossref-jfe", CROSSREF, "Liquidity and the cross-section", "2026-09-01"),
    ("federal-register", FEDREG, "Rule on beneficial ownership reporting", "2026-09-18"),
    ("gleif-lei", GLEIF, "Example Holding B.V.", "2026-09-01"),
    ("sec-edgar-submissions", SEC, "Apple Inc. — 10-Q 10-Q", "2026-08-01"),
    ("courtlistener", COURTLISTENER, "Acme Corp v. Doe", "2026-09-12"),
    ("rechtspraak", RECHTSPRAAK, "Hoge Raad, eigendomsoverdracht", "2026-09-16"),
    ("doaj", DOAJ, "Sanctions compliance in the EU", "2026-01-01"),
]


@pytest.mark.parametrize("source_id,payload,title,date", CASES)
def test_adapter_normalises_its_source(source_id, payload, title, date):
    source = sources.BY_ID[source_id]
    records = adapters.ADAPTERS[source.extract](payload, source)
    assert len(records) == 1
    record = records[0]
    assert record.title == title
    assert record.date == date
    assert record.uid.startswith(f"{source_id}:")
    assert record.track == source.track
    assert record.authority == source.authority


def test_openalex_abstract_is_put_back_in_word_order():
    record = adapters.openalex(OPENALEX, sources.BY_ID["openalex-replication"])[0]
    assert record.abstract == "We fail to replicate"


def test_crossref_strips_jats_markup():
    record = adapters.crossref(CROSSREF, sources.BY_ID["crossref-jfe"])[0]
    assert "<jats" not in record.abstract
    assert "liquidity" in record.abstract


def test_adapter_returns_nothing_rather_than_guessing_on_an_empty_reply():
    empty = json.dumps({"results": []}).encode()
    assert adapters.openalex(empty, sources.BY_ID["openalex-replication"]) == []


# ------------------------------------------------------------------ scoring

def _record(title, abstract="", authority=2, track="quant", date="2026-09-18"):
    return adapters.Record(uid="t:1", source_id="t", track=track, kind="papers",
                           title=title, abstract=abstract, authority=authority, date=date)


def test_a_replication_study_outranks_a_performance_claim():
    """The whole point of the quant track: knowing a signal is dead beats being sold one."""
    replication = _record("Out-of-sample failure of 200 anomalies",
                          "We replicate and fail to confirm.")
    claim = _record("Deep learning strategy with Sharpe 4.1",
                    "Our model outperforms with high annualized return.", authority=5)
    ranked = scoring.rank([claim, replication], TODAY)
    assert ranked[0] is replication
    assert "REPLICATION" in replication.flags
    assert "NO-OOS" in claim.flags


def test_performance_claim_with_a_holdout_is_not_flagged():
    honest = _record("A momentum signal", "Sharpe of 0.8 on a held-out test set, walk-forward.")
    _, flags = scoring.score(honest, TODAY)
    assert "NO-OOS" not in flags


def test_retraction_is_surfaced_not_buried():
    retracted = _record("Retracted: earnings drift revisited", "This article has been retracted.")
    normal = _record("Earnings drift revisited", "A study of drift.")
    ranked = scoring.rank([normal, retracted], TODAY)
    assert ranked[0] is retracted
    assert "RETRACTED" in retracted.flags


def test_course_overlap_is_rewarded():
    on_course = _record("Article 36 TFEU and the internal market", track="legal")
    off_course = _record("Municipal zoning in Ohio", track="legal")
    assert scoring.score(on_course, TODAY)[0] > scoring.score(off_course, TODAY)[0]
    assert "COURSE" in scoring.score(on_course, TODAY)[1]


def test_crossover_records_beat_single_track_records():
    both = _record("Disclosure quality and securities regulation enforcement", track="quant")
    one = _record("A note on volatility", track="quant")
    assert scoring.score(both, TODAY)[0] > scoring.score(one, TODAY)[0]


def test_undated_records_rank_last():
    dated = _record("A paper", date="2026-09-18")
    undated = _record("Another paper", date="")
    assert scoring.score(dated, TODAY)[0] > scoring.score(undated, TODAY)[0]


def test_stale_records_lose_to_fresh_ones():
    fresh = _record("A paper", date="2026-09-18")
    stale = _record("A paper", date="2025-01-01")
    assert scoring.score(fresh, TODAY)[0] > scoring.score(stale, TODAY)[0]


def test_score_is_never_negative():
    awful = _record("Sharpe 9 with 500 factors", "We outperform.", authority=5, date="2020-01-01")
    assert scoring.score(awful, TODAY)[0] >= 0.0


# ------------------------------------------------------------------ the routine

def test_a_dead_source_does_not_take_the_run_with_it(monkeypatch, tmp_path):
    """One API being down must cost one source, not the whole harvest."""
    monkeypatch.setattr(lector, "HOME", tmp_path)
    for name in ("FEED", "DIGEST", "STATE", "LOG"):
        monkeypatch.setattr(lector, name, tmp_path / f"{name.lower()}")

    calls = {"n": 0}

    def flaky(url, timeout=30):
        calls["n"] += 1
        if calls["n"] % 2:
            raise OSError("connection refused")
        return OPENALEX

    monkeypatch.setattr(lector, "fetch", flaky)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    run = lector.harvest(track="system", rows=1, days=7)
    assert run["errors"], "the dead source should be reported"
    assert run["sources_polled"] == len(sources.fetchable("system"))
    assert (tmp_path / "feed").exists()


def test_a_record_is_new_exactly_once(monkeypatch, tmp_path):
    """State is on disk, not in memory — a second run must not re-report the same paper."""
    for name in ("FEED", "DIGEST", "STATE", "LOG"):
        monkeypatch.setattr(lector, name, tmp_path / f"{name.lower()}")
    monkeypatch.setattr(lector, "fetch", lambda url, timeout=30: OPENALEX)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    first = lector.harvest(track="system", rows=1, days=7)
    second = lector.harvest(track="system", rows=1, days=7)
    assert first["new_records"] >= 1
    assert second["new_records"] == 0


def test_url_building_fills_every_placeholder():
    for source in sources.fetchable():
        url = lector.build_url(source, "2026-09-01", 10, query="0000320193")
        assert "{" not in url, f"{source.id} left a placeholder unfilled: {url}"


def test_digest_never_breaks_the_frame():
    """80x24 is the constraint the rest of the fleet's terminal work holds to."""
    feed = {"runs": [{
        "at": "2026-09-19T10:00:00", "track": "all", "since": "2026-09-05",
        "sources_polled": 13, "new_records": 2, "errors": {},
        "records": [
            {"score": 9.2, "flags": ["REPLICATION", "NEW"], "date": "2026-09-18",
             "title": "A very long title " * 12, "venue": "Journal of Finance",
             "source_id": "crossref-jfe"},
            {"score": 3.1, "flags": ["PREPRINT"], "date": "2026-09-17",
             "title": "Short one", "venue": "arXiv", "source_id": "arxiv-qfin"},
        ],
    }]}
    panel = lector.render(feed, width=80, height=24, colour=False)
    lines = panel.rstrip("\n").split("\n")
    assert all(len(line) <= 80 for line in lines), "a line ran past the frame"
    assert len(lines) <= 24, "the panel is taller than the terminal"


def test_digest_has_a_glyph_for_every_colour():
    """Colour is never the only signal — the fleet's accessibility rule."""
    for flag, (glyph, colour) in lector.GLYPH.items():
        assert glyph.strip(), f"{flag} has a colour but no glyph"
        assert colour.startswith("\033["), f"{flag} has no colour"


def test_empty_feed_renders_an_instruction_not_a_crash():
    assert "no harvest yet" in lector.render({"runs": []})


def test_lector_is_stdlib_only():
    """The fleet's terminal work installs with nothing. Keep it that way."""
    source_text = (pathlib.Path(lector.__file__).read_text()
                   + pathlib.Path(adapters.__file__).read_text()
                   + pathlib.Path(scoring.__file__).read_text())
    for banned in ("import requests", "import rich", "import textual", "import httpx",
                   "import pandas", "import numpy"):
        assert banned not in source_text, f"{banned} breaks the stdlib-only constraint"


def test_no_course_material_is_ever_sent_outward():
    """Lector reads the outside world in. It must never carry Matej's notes out."""
    text = pathlib.Path(lector.__file__).read_text()
    for leak in ("notes", "cards", "DATABASE_URL", "data/"):
        assert f"post({leak}" not in text
    assert "urlopen" in text and "data=" not in text, "every request must be a plain GET"


def test_the_same_paper_from_two_sources_is_shown_once():
    """OpenAlex and Crossref both carry the same DOI. The panel must not show it twice."""
    a = adapters.Record(uid="openalex:W1", source_id="openalex-replication", track="quant",
                        kind="papers", title="Replication of the factor zoo",
                        doi="10.1234/abc", authority=2, abstract="We fail to replicate.")
    b = adapters.Record(uid="crossref:10.1234/abc", source_id="crossref-jfe", track="quant",
                        kind="papers", title="Replication of the Factor Zoo",
                        doi="10.1234/ABC", authority=1)
    kept, merged = lector.dedupe([a, b])
    assert len(kept) == 1 and merged == 1
    assert kept[0].authority == 1, "the more authoritative copy should survive"


def test_duplicate_preprints_collapse_on_title_when_there_is_no_doi():
    a = adapters.Record(uid="arxiv:1", source_id="arxiv-qfin", track="quant", kind="papers",
                        title="Out-of-sample decay in anomalies", authority=5)
    b = adapters.Record(uid="openalex:2", source_id="openalex-replication", track="quant",
                        kind="papers", title="Out-of-sample  decay in anomalies!", authority=2,
                        abstract="Same preprint, indexed elsewhere.")
    kept, merged = lector.dedupe([a, b])
    assert len(kept) == 1 and merged == 1
    assert kept[0].authority == 2


def test_different_papers_are_not_merged():
    a = adapters.Record(uid="a", source_id="s", track="quant", kind="papers", title="Paper one")
    b = adapters.Record(uid="b", source_id="s", track="quant", kind="papers", title="Paper two")
    kept, merged = lector.dedupe([a, b])
    assert len(kept) == 2 and merged == 0


def test_a_full_panel_still_fits_a_24_row_terminal():
    """The earlier frame test passed with two records and missed that each one costs two lines."""
    records = [
        {"score": 9.0 - i * 0.1, "flags": ["REPLICATION", "NEW", "COURSE", "CROSSOVER"],
         "date": "2026-09-18", "title": f"A fairly long paper title number {i} " * 3,
         "venue": "Journal of Financial Economics", "source_id": "crossref-jfe"}
        for i in range(40)
    ]
    feed = {"runs": [{"at": "2026-09-19T10:00:00", "track": "all", "since": "2026-09-05",
                      "sources_polled": 13, "new_records": 40, "duplicates_merged": 3,
                      "errors": {"doaj": "down"}, "records": records}]}
    for height in (24, 30, 50):
        panel = lector.render(feed, width=80, height=height, colour=False)
        lines = panel.rstrip("\n").split("\n")
        assert len(lines) <= height, f"panel is {len(lines)} lines in a {height}-row terminal"
        assert all(len(line) <= 80 for line in lines)


def test_panel_degrades_by_hiding_detail_not_by_breaking():
    """80x24 is the floor the rest of the fleet's terminal work holds to."""
    records = [{"score": 5.0, "flags": ["NEW"], "date": "2026-09-18", "title": "T" * 300,
                "venue": "V" * 200, "source_id": "s"} for _ in range(10)]
    feed = {"runs": [{"at": "2026-09-19T10:00:00", "track": "all", "since": "2026-09-05",
                      "sources_polled": 1, "new_records": 10, "errors": {}, "records": records}]}
    lines = lector.render(feed, width=80, height=24, colour=False).rstrip("\n").split("\n")
    assert all(len(line) == 80 for line in lines), "every line should fill, none should overflow"
