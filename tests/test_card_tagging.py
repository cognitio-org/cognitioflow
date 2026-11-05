"""card_tagging: classify a card into an examined blueprint topic. Pure, no database, no model."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import card_tagging as ct  # noqa: E402


TOPICS = [
    {"topic": "Free movement of goods", "weight": 60, "doctrines": ["Art 34 TFEU", "Cassis", "Keck"]},
    {"topic": "Direct effect", "weight": 40, "doctrines": ["Van Gend"]},
    {"topic": "  ", "doctrines": ["junk"]},          # filtered — no usable topic
    "not a dict",                                      # filtered
]
KEYS = ["Free movement of goods", "Direct effect"]
CARDS = [
    {"id": "c1", "front": "What does Cassis de Dijon establish?", "back": "Mutual recognition."},
    {"id": "c2", "front": "Van Gend en Loos?", "back": "Direct effect of EU law."},
    {"id": "c3", "front": "Unrelated civil procedure point", "back": "n/a"},
]


def test_valid_topics_and_keys_filter_junk():
    assert ct.topic_keys(TOPICS) == KEYS
    assert len(ct.valid_topics(TOPICS)) == 2
    assert ct.topic_keys([]) == [] and ct.topic_keys(None) == []


def test_build_prompt_numbers_match_keys():
    p = ct.build_prompt(TOPICS, CARDS)
    assert "1. Free movement of goods" in p and "2. Direct effect" in p
    assert "Art 34 TFEU" in p                       # doctrines travel as hints
    assert "[1]" in p and "[3]" in p and "junk" not in p
    # card numbering is 1-based and aligned with the cards list
    assert p.index("[1]") < p.index("[2]") < p.index("[3]")


def test_parse_tags_object_shape():
    out = ct.parse_tags({"1": 1, "2": 2, "3": 0}, CARDS, KEYS)
    assert out == {"c1": "Free movement of goods", "c2": "Direct effect"}   # 3 -> 0 means untagged


def test_parse_tags_list_shape():
    out = ct.parse_tags([{"card": 1, "topic": 2}, {"card": 2, "topic": 1}], CARDS, KEYS)
    assert out == {"c1": "Direct effect", "c2": "Free movement of goods"}


def test_parse_tags_drops_out_of_range_and_invented():
    # 9 is out of range, "x" unparseable, missing card 3 -> all untagged. No invented key can survive.
    out = ct.parse_tags({"1": 9, "2": "x"}, CARDS, KEYS)
    assert out == {}
    assert all(v in KEYS for v in ct.parse_tags({"1": 1, "2": 2}, CARDS, KEYS).values())


def test_parse_tags_empty_inputs():
    assert ct.parse_tags({"1": 1}, CARDS, []) == {}       # no topics -> nothing tags
    assert ct.parse_tags({}, [], KEYS) == {}


def test_batches():
    cards = [{"id": str(i)} for i in range(70)]
    bs = ct.batches(cards, 30)
    assert [len(b) for b in bs] == [30, 30, 10]
    assert ct.batches([], 30) == []
    assert len(ct.batches(cards, 0)) == 70                # size<1 clamps to 1


def test_card_text_bounded_and_joined():
    long = {"id": "x", "front": "a " * 400, "back": "b " * 400}
    txt = ct._card_text(long)
    assert len(txt) <= ct._CARD_CHARS
    assert ct._card_text({"id": "y", "front": "Front only", "back": ""}) == "Front only"


def test_stale_tags():
    used = ["Direct effect", "Old removed topic", "  ", "Another gone"]
    assert ct.stale_tags(used, KEYS) == ["Another gone", "Old removed topic"]
    assert ct.stale_tags([], KEYS) == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q", "--noconftest"]))
