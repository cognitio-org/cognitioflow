"""citecheck: which citations in a tutor answer are missing from the student's own files. Pure, no network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import citecheck  # noqa: E402


def test_finds_each_kind_once_in_order():
    found = citecheck.find_citations("ECLI:NL:HR:2019:1734, C‑26/62, C-26/62 and Art. 3:84 BW")
    assert [(c["kind"], c["norm"]) for c in found] == [("ecli", "ECLI:NL:HR:2019:1734"), ("case", "C-26/62"),
                                                         ("article", "art 3:84 bw")]


def test_a_citation_in_the_materials_is_verified_and_an_invented_one_is_not():
    sources = ["Google Spain, ECLI:EU:C:2014:317"]
    assert citecheck.unverified("See ECLI:EU:C:2014:317.", sources) == []
    assert [c["norm"] for c in citecheck.unverified("ECLI:EU:C:2099:1", sources)] == ["ECLI:EU:C:2099:1"]
    assert len(citecheck.unverified("C-26/62 and Art. 34", [])) == 2


def test_an_article_without_instrument_matches_any_instrument_but_a_wrong_one_does_not():
    assert citecheck.unverified("Art. 267 applies", ["Article 267 TFEU"]) == []
    assert len(citecheck.unverified("Art. 267 TEU", ["Article 267 TFEU"])) == 1


def test_an_old_case_cited_with_a_prefix_matches_the_bare_number_in_the_reader():
    # found live on 2026-09-24: the tutor wrote Simmenthal as C-106/77, the reader has "Case 106/77"
    assert citecheck.unverified("Simmenthal (C-106/77)", ["Simmenthal, Case 106/77, para 24"]) == []
    assert len(citecheck.unverified("C-106/77", ["Case 1106/77 and 106/771"])) == 1   # a longer number is not a match


def test_an_invented_old_style_case_is_flagged_and_a_real_one_in_the_files_is_not():
    # wave 6: "Case 99/74" (no C- prefix) never reached the "Not in your materials" box, only the panel
    src = ["Procureur du Roi v Dassonville. Case 8/74. All trading rules capable of hindering trade."]
    assert [c["norm"] for c in citecheck.unverified("Case 99/74 held the opposite.", src)] == ["C-99/74"]
    assert citecheck.unverified("Dassonville (Case 8/74) set the formula.", src) == []
    assert citecheck.unverified("Dassonville (C-8/74) set the formula.", src) == []
    assert [c["norm"] for c in citecheck.unverified("Case 26/62 is van Gend en Loos.", src)] == ["C-26/62"]
    assert citecheck.find_citations("In Case 1/93 and Case 12/05 nothing") == []         # outside the Court's old series: not a citation here
    assert citecheck.unverified("Case 8/74", ["EUR-Lex prints Case 8-74 for it"]) == []   # the dashed form stays accepted
