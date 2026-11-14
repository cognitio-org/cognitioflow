"""Every GDPR citation in the privacy record and README must exist in the pinned table (definition-of-8 docs, Must 9a).

The table (tests/fixtures/gdpr_articles.json) lists each provision CF cites with its official short title and
which paragraphs and lettered points exist in Regulation (EU) 2016/679. This test only proves the cited
provision EXISTS; whether it supports what its row claims is a human/legal pass (Must 9b, logged in the flow
history). Extend the table when a new article is cited; a citation to a missing article fails the build.
"""
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TABLE = json.loads((ROOT / "tests" / "fixtures" / "gdpr_articles.json").read_text())["articles"]
FILES = ("docs/privacy-gateway.md", "README.md", "gateway.py", "llm.py")
# "Art. 28", "Art. 5(1)(e)", "Art. 44–46", "Arts. 15-17"; the dot after Art is required so TFEU "Art 34" is not matched.
CITE = re.compile(r"\bArts?\.\s*(\d+)((?:\(\w+\))*)(?:\s*[–-]\s*(\d+))?")


def check(art, chain, hi=None):
    """Return a list of problems for one citation (empty = fine)."""
    out = []
    spans = [str(n) for n in range(int(art), int(hi) + 1)] if hi else [art]
    for a in spans:
        if a not in TABLE:
            out.append(f"Art. {a} is not in the pinned table")
    if out or hi:
        return out
    parts = re.findall(r"\((\w+)\)", chain)
    paras = TABLE[art]["paragraphs"]
    if parts:
        if parts[0] not in paras:
            return [f"Art. {art}({parts[0]}): paragraph does not exist"]
        if len(parts) > 1 and parts[1] not in paras[parts[0]]:
            return [f"Art. {art}({parts[0]})({parts[1]}): point does not exist"]
        if len(parts) > 2:
            return [f"Art. {art}{chain}: nesting deeper than the table models"]
    return []


def citations():
    for name in FILES:
        for ln, line in enumerate((ROOT / name).read_text().splitlines(), 1):
            for m in CITE.finditer(line):
                yield name, ln, m.group(0), m.group(1), m.group(2), m.group(3)


def test_every_gdpr_citation_exists_in_the_pinned_table():
    found = list(citations())
    assert len(found) >= 20, "the record's citations were not found: the extractor is broken"
    bad = [f"{n}:{ln} {txt}: {p}" for n, ln, txt, a, c, hi in found for p in check(a, c, hi)]
    assert not bad, bad


def test_table_has_title_and_url_for_each_article():
    for a, v in TABLE.items():
        assert v["title"] and v["url"].startswith("https://eur-lex.europa.eu/"), a


@pytest.mark.parametrize("cite", ["Art. 99", "Art. 6(9)", "Art. 5(1)(z)", "Art. 28(3)(i)", "Art. 2(2)(e)", "Art. 44–99"])
def test_checker_rejects_citations_that_do_not_exist(cite):
    m = CITE.search(cite)
    assert check(m.group(1), m.group(2), m.group(3)), cite


@pytest.mark.parametrize("cite", ["Art. 6(1)(a)", "Art. 5(1)(e)", "Art. 2(2)(c)", "Art. 28(3)", "Art. 46(2)(c)", "Art. 4(7)", "Art. 44–46"])
def test_checker_accepts_real_citations(cite):
    m = CITE.search(cite)
    assert not check(m.group(1), m.group(2), m.group(3)), cite
