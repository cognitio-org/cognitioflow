"""concepts.py: the parts that must not be taken on trust from a model. No network, no database."""
import json

import concepts


MATERIAL = """=== W2 Lecture A notes ===
Article 34 TFEU prohibits quantitative restrictions and all measures having equivalent effect.
All trading rules enacted by Member States which are capable of hindering, directly or indirectly,
actually or potentially, intra-Union trade are to be considered as measures having an effect
equivalent to quantitative restrictions. Students often treat Cassis as an alternative to
Dassonville; it is the step after it.
"""


def candidate(**over):
    base = {
        "name": "Dassonville formula",
        "kind": "test",
        "statement": "A trading rule capable of hindering intra-Union trade is a measure having equivalent effect.",
        "limbs": ["a trading rule of a Member State", "capable of hindering trade"],
        "traps": ["treating Cassis as an alternative rather than the next step"],
        "authority": "C-8/74",
        "method_tag": "Free Movement",
        "quote": "All trading rules enacted by Member States which are capable of hindering, directly or indirectly, actually or potentially, intra-Union trade",
        "confusable_with": ["Cassis de Dijon"],
    }
    base.update(over)
    return base


def test_a_concept_whose_quote_is_in_the_material_is_kept():
    kept, dropped = concepts.parse({"concepts": [candidate()]}, MATERIAL)
    assert len(kept) == 1 and not dropped
    got = kept[0]
    assert got["name"] == "Dassonville formula" and got["kind"] == "test"
    assert got["method_tag"] == "free movement"          # normalised, so two courses can share a tag
    assert got["limbs"][0].startswith("a trading rule")


def test_a_paraphrased_quote_loses_the_whole_concept():
    """The guard that matters: a statement about the right thing, supported by nothing."""
    kept, dropped = concepts.parse({"concepts": [candidate(
        quote="Trading rules that might hinder trade between member states count as equivalent measures")]}, MATERIAL)
    assert kept == []
    assert dropped and "quote is not in the material" in dropped[0]


def test_whitespace_and_case_are_forgiven_but_wording_is_not():
    assert concepts.grounded("ALL TRADING RULES   enacted by Member States\nwhich are capable of hindering", MATERIAL)
    assert not concepts.grounded("all trading rules invented by Member States which are capable", MATERIAL)


def test_a_short_quote_proves_nothing():
    assert not concepts.grounded("Article 34", MATERIAL)


def test_a_concept_with_no_statement_is_not_a_concept():
    assert concepts.clean(candidate(statement=""), MATERIAL) == {}
    assert concepts.clean(candidate(name=" "), MATERIAL) == {}


def test_an_unknown_kind_falls_back_rather_than_inventing_a_column_value():
    assert concepts.clean(candidate(kind="vibe"), MATERIAL)["kind"] == "rule"


def test_the_same_concept_twice_is_saved_once():
    kept, _ = concepts.parse({"concepts": [candidate(), candidate(name="dassonville FORMULA")]}, MATERIAL)
    assert len(kept) == 1


def test_a_reply_that_is_not_json_is_reported_not_raised():
    kept, dropped = concepts.parse("I think the main concepts are...", MATERIAL)
    assert kept == [] and dropped == ["the reply was not JSON"]


def test_json_wrapped_in_prose_is_still_read():
    payload = 'Here you go:\n{"concepts": [%s]}\nHope that helps.' % json.dumps(candidate())
    kept, _ = concepts.parse(payload, MATERIAL)
    assert len(kept) == 1


def test_a_link_is_only_made_to_a_concept_the_course_actually_has():
    kept, _ = concepts.parse({"concepts": [candidate(confusable_with=["Cassis de Dijon", "Some Invented Doctrine"])]}, MATERIAL)
    by_name = {"dassonville formula": "id-a", "cassis de dijon": "id-b"}
    links = concepts.pairs_for_links(kept, by_name)
    assert links == [("id-a", "id-b", "confusable")]      # the invented one is left out, not created


def test_rows_for_save_carry_the_week_and_serialise_the_lists():
    kept, _ = concepts.parse({"concepts": [candidate()]}, MATERIAL)
    row = concepts.rows_for_save(kept, "eu", "2", now=1.0)[0]
    assert row[1] == "eu" and row[4] == "2"
    assert json.loads(row[6])[0].startswith("a trading rule")
    assert json.loads(row[7])[0].startswith("treating Cassis")


def test_the_model_cannot_pad_a_week_with_forty_concepts():
    many = {"concepts": [candidate(name=f"Concept {n}") for n in range(40)]}
    kept, _ = concepts.parse(many, MATERIAL)
    assert len(kept) == concepts.MAX_CONCEPTS
