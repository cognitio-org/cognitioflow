"""games/generate.py sorter_pack — Case Sorter's cite↔principle pairs (pure: no model, no files)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "games"))
import generate  # noqa: E402


POOL = [
    {"flawed": False, "cite": "Art 34 TFEU", "ground": "A national measure capable of hindering trade is a MEQR.", "source": "src1", "why": "w1"},
    {"flawed": False, "cite": "C-8/74 Dassonville", "ground": "Defines measures of equivalent effect broadly.", "source": "", "why": ""},
    {"flawed": True, "cite": "C-999/99", "ground": "A flawed submission that should be excluded.", "source": "s", "why": "w"},
    {"flawed": False, "cite": "", "ground": "No authority, so not a usable pair.", "source": "", "why": ""},
    {"flawed": False, "cite": "Art 56 TFEU", "ground": "", "source": "", "why": ""},
]


def test_sorter_pairs_are_sound_items_carrying_both_sides():
    pack = generate.sorter_pack(POOL, course="European Law")
    assert pack["course"] == "European Law" and "pairs" in pack
    pairs = pack["pairs"]
    assert len(pairs) == 2                                   # only the two SOUND items with both a cite and a ground
    assert {p["left"] for p in pairs} == {"Art 34 TFEU", "C-8/74 Dassonville"}
    pool_cites = {it["cite"] for it in POOL}
    pool_grounds = {it["ground"] for it in POOL}
    for p in pairs:
        assert p["left"] and p["right"]                      # both sides present
        assert set(p) == {"left", "right", "source", "why"}
        assert p["left"] in pool_cites and p["right"] in pool_grounds   # verbatim, nothing fabricated


def test_sorter_pack_on_an_empty_pool_is_empty_not_an_error():
    assert generate.sorter_pack([])["pairs"] == []
