"""The oral engine's decisions, without a model, a microphone or a database."""
import oral


def test_a_grade_becomes_one_of_the_apps_four_ratings():
    assert oral.rating_for("missed") == 0
    assert oral.rating_for("shaky") == 1
    assert oral.rating_for("solid") == 2
    assert oral.rating_for("brilliant") == 0, "an unknown grade must never be treated as known"


def test_misses_jump_the_queue():
    qs = [{"id": "a", "concept": "Direct effect"}, {"id": "b", "concept": "Primacy"}]
    mastery = {"Direct effect": "solid", "Primacy": "missed"}
    # 4 + 100 = 104; any roll past the first slice lands on the missed concept
    assert oral.choose(qs, mastery, {}, roll=0.5)["id"] == "b"
    assert oral.choose(qs, mastery, {}, roll=0.0)["id"] == "a"


def test_a_question_just_asked_is_not_asked_again_immediately():
    qs = [{"id": "a", "concept": "X"}, {"id": "b", "concept": "Y"}]
    assert oral.choose(qs, {}, {"a": 2}, roll=0.0)["id"] == "b"


def test_cooldown_is_ignored_rather_than_leaving_nothing_to_ask():
    qs = [{"id": "a", "concept": "X"}]
    assert oral.choose(qs, {}, {"a": 3}, roll=0.0)["id"] == "a"


def test_cooldowns_count_down_and_expire():
    assert oral.tick({"a": 2, "b": 1}) == {"a": 1}


def test_two_misses_on_a_concept_switch_to_teaching():
    assert not oral.should_teach("Primacy", {"Primacy": 1})
    assert oral.should_teach("Primacy", {"Primacy": 2})


def test_a_broken_grade_is_never_read_as_solid():
    assert oral.normalise({"mastery": "SOLID?"})["mastery"] == "missed"
    assert oral.normalise(None)["mastery"] == "missed"
    assert oral.normalise("not json at all")["mastery"] == "missed"


def test_a_solid_answer_carries_no_weak_point_note():
    out = oral.normalise({"mastery": "solid", "verdict": "Complete", "spoken": "Yes.", "note": "leftover"})
    assert out["note"] == ""


def test_spoken_reply_and_note_are_held_to_budget():
    out = oral.normalise({"mastery": "shaky", "spoken": "word " * 80, "note": "gap " * 60})
    assert len(out["spoken"].split()) == oral.SPOKEN_WORDS
    assert len(out["note"].split()) == oral.NOTE_WORDS


def test_every_grade_gets_a_verdict_even_when_the_model_omits_one():
    assert oral.normalise({"mastery": "shaky"})["verdict"] == "Partly there"


def test_a_question_without_a_model_answer_cannot_be_graded_against():
    assert oral.valid_question({"question": "q", "model": "m", "concept": "c"})
    assert not oral.valid_question({"question": "q", "model": "", "concept": "c"})
    assert not oral.valid_question({"question": "q", "model": "m", "concept": " "})
