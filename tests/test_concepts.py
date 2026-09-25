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


# ---------------------------------------------------------------- questions written from a concept

CONCEPT = {
    "name": "Gebhard test",
    "statement": "A national measure liable to hinder or make less attractive the exercise of a fundamental freedom must be justified.",
    "authority": "C-55/94",
    "limbs": ["applied in a non-discriminatory manner", "justified by an imperative requirement in the general interest",
              "suitable for attaining the objective", "does not go beyond what is necessary"],
    "traps": ["skipping the necessity limb once suitability is shown"],
}


def payload(front="State the Gebhard test.", back="Four conditions: non-discriminatory, justified, suitable, necessary.",
            question=None, model=None, steps=None, cite=""):
    q = {
        "question": question or ("Ilse, a German architect, is refused registration in Italy unless she joins a local "
                                 "chamber and sits an exam she has already passed at home. Advise her." + cite),
        "steps": steps or ["identify the restriction", "apply the Gebhard conditions in order", "conclude on necessity"],
        "model": model or ("The registration requirement is liable to make establishment less attractive, so C-55/94 "
                           "applies: it is non-discriminatory, but the exam is not necessary where an equivalent "
                           "qualification is already held." + cite),
    }
    return {"cards": [{"front": front + cite, "back": back}], "question": q}


def test_a_card_and_a_problem_come_back_from_a_clean_reply():
    cards, dropped = concepts.clean_cards(payload(), CONCEPT)
    question, why = concepts.clean_question(payload(), CONCEPT)
    assert len(cards) == 1 and not dropped
    assert question and not why
    assert len(question["steps"]) == 3 and "C-55/94" in question["model"]


def test_a_card_citing_a_case_the_concept_never_carried_is_thrown_away():
    """The guard that matters here: the model reaching past the course into what it happens to know."""
    cards, dropped = concepts.clean_cards(payload(cite=" (see also C-120/78)"), CONCEPT)
    assert cards == [] and dropped and "does not carry" in dropped[0]


def test_a_problem_citing_an_unknown_article_is_refused():
    question, why = concepts.clean_question(payload(model="Under Article 101 TFEU the exam is unlawful because it restricts competition between architects."), CONCEPT)
    assert question is None and "does not carry" in why


def test_the_authority_the_concept_does_carry_is_allowed_through():
    question, why = concepts.clean_question(payload(model="C-55/94 governs: the requirement fails the necessity limb because an equivalent qualification is held."), CONCEPT)
    assert question and not why


def test_a_problem_without_a_stappenplan_is_not_markable():
    question, why = concepts.clean_question(payload(steps=["think about it"]), CONCEPT)
    assert question is None and "stappenplan" in why


def test_a_problem_without_facts_is_not_a_problem():
    question, why = concepts.clean_question(payload(question="Discuss Gebhard."), CONCEPT)
    assert question is None and "facts" in why


def test_a_problem_without_a_model_answer_is_refused():
    question, why = concepts.clean_question(payload(model="It fails."), CONCEPT)
    assert question is None and "model answer" in why


def test_a_topic_is_not_a_card():
    cards, dropped = concepts.clean_cards({"cards": [{"front": "Art 49", "back": "yes"}]}, CONCEPT)
    assert cards == [] and dropped
