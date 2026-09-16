"""What gets spoken, and what must never be."""
import tts


def test_provenance_tags_are_not_read_aloud():
    said = tts.speakable("Dassonville [LECTURE] is the test [OUTSIDE FILES] here.")
    assert "LECTURE" not in said and "OUTSIDE FILES" not in said
    assert "Dassonville" in said and "is the test" in said


def test_markdown_is_not_read_aloud():
    assert tts.speakable("**Keck** says `selling arrangements` are #outside") == "Keck says selling arrangements are outside"


def test_a_spoken_turn_is_capped_so_a_paid_voice_cannot_run_away():
    assert len(tts.speakable("word " * 5000)) <= tts.MAX_CHARS


def test_sentences_split_so_the_first_can_play_while_the_rest_is_written():
    assert tts.sentences("Yes. But why? Because Cassis says so!") == ["Yes.", "But why?", "Because Cassis says so!"]


def test_empty_text_is_never_sent_to_a_paid_api():
    assert tts.say("   ") is None
    assert tts.sentences("") == []


def test_browser_backend_asks_the_page_to_speak_for_itself():
    assert tts.BACKEND == "browser", "the default must cost nothing"
    assert tts.available() is False
    assert tts.describe()["server"] is False
