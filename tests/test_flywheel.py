"""Phase 19 — the flywheel's feedback signal. Needs docker Postgres (the `client`/`pg` fixtures).

The GOLD: when Matej corrects an AI-generated card, the pair (the AI's card -> his edited card) is
recorded de-identified in card_edits, linked to the generation interaction. FSRS review ratings of an
AI-generated card carry the gen_sample_id too. No real model: generation is stubbed, as in
test_card_capture."""
from types import SimpleNamespace as NS

from psycopg.rows import dict_row

import llm
import run

# A note carrying identifiers the capture must strip, plus enough law to generate from.
NOTE = ("Ownership under Article 5:1 BW. Contact s7654321 at piet@example.com about this. "
        "A rule, a case, a citation. " * 8)


def _cloud_msg(cards):
    u = NS(input_tokens=900, output_tokens=40, cache_read_input_tokens=0, cache_creation_input_tokens=0,
           cost=0.004, provider=None)
    return NS(model="claude-haiku-4-5", usage=u, content=[NS(type="text", text=cards)], stop_reason="end_turn")


def _gen_one_ai_card(client, monkeypatch, cid, front, back):
    """Generate a single AI card into cid (cloud path, stubbed) and return its row (dict)."""
    monkeypatch.setattr(llm, "LOCAL_BASE_URL", "")
    import json as _json
    monkeypatch.setattr(run, "client",
                        lambda: NS(messages=NS(create=lambda **kw: _cloud_msg(_json.dumps([{"front": front, "back": back}])))))
    nid = client.post(f"/api/courses/{cid}/notes", json={"title": "Week 1 — Ownership", "body": NOTE}).json()["id"]
    assert client.post(f"/api/courses/{cid}/cards/generate", json={"note_id": nid, "count": 1}).json()["made"] == 1
    return client.get(f"/api/courses/{cid}/cards").json()[0]


def _edits(pg):
    return pg.cursor(row_factory=dict_row).execute("SELECT * FROM card_edits ORDER BY at").fetchall()


def test_editing_an_ai_card_records_the_before_after_pair(client, pg, monkeypatch):
    cid = client.post("/api/courses", json={"name": "Edit Law"}).json()["id"]
    card = _gen_one_ai_card(client, monkeypatch, cid, "What is ownership?", "A right over a thing.")
    assert card["gen_sample_id"]

    # Matej corrects the card — and leaks an email into the back, which must be stripped on the way in.
    r = client.put(f"/api/cards/{card['id']}",
                   json={"front": "What is ownership under Art. 5:1 BW?",
                         "back": "The most comprehensive right a person can have in a thing (ask jan@example.com)."})
    assert r.status_code == 200

    edits = _edits(pg)
    assert len(edits) == 1
    e = edits[0]
    assert e["card_id"] == card["id"] and e["gen_sample_id"] == card["gen_sample_id"] and e["course_id"] == cid
    # before == the AI's original card; after == Matej's edited card
    assert e["front_before"] == "What is ownership?" and e["back_before"] == "A right over a thing."
    assert e["front_after"] == "What is ownership under Art. 5:1 BW?"
    # de-identified: the leaked email is replaced, the law is kept
    assert "jan@example.com" not in e["back_after"] and "[email]" in e["back_after"]
    assert "Art. 5:1 BW" in e["front_after"]


def test_a_no_op_edit_records_nothing(client, pg, monkeypatch):
    cid = client.post("/api/courses", json={"name": "No-op Law"}).json()["id"]
    card = _gen_one_ai_card(client, monkeypatch, cid, "Q", "A")
    # Save the identical text (only week changes): no front/back change → no preference signal.
    r = client.put(f"/api/cards/{card['id']}", json={"front": "Q", "back": "A", "week": "3"})
    assert r.status_code == 200
    assert _edits(pg) == []
    assert client.get(f"/api/courses/{cid}/cards").json()[0]["week"] == "3"   # the edit still applied


def test_editing_a_manual_card_records_nothing(client, pg):
    """A hand-written card has no gen_sample_id, so there is no AI card to learn a correction from."""
    cid = client.post("/api/courses", json={"name": "Manual Law"}).json()["id"]
    kid = client.post(f"/api/courses/{cid}/cards", json={"front": "Hand", "back": "Written"}).json()["id"]
    assert client.put(f"/api/cards/{kid}", json={"front": "Hand (edited)", "back": "Written"}).status_code == 200
    assert _edits(pg) == []


def test_review_links_an_ai_card_rating_to_its_gen_sample(client, pg, monkeypatch):
    cid = client.post("/api/courses", json={"name": "Rating Law"}).json()["id"]
    ai = _gen_one_ai_card(client, monkeypatch, cid, "Q", "A")
    manual = client.post(f"/api/courses/{cid}/cards", json={"front": "M", "back": "m"}).json()["id"]

    assert client.post(f"/api/cards/{ai['id']}/review", json={"rating": 3}).status_code == 200
    assert client.post(f"/api/cards/{manual}/review", json={"rating": 2}).status_code == 200

    got = {row["card_id"]: row["gen_sample_id"] for row in pg.cursor(row_factory=dict_row).execute(
        "SELECT card_id, gen_sample_id FROM reviews").fetchall()}
    assert got[ai["id"]] == ai["gen_sample_id"]   # the AI card's rating ties back to its generation
    assert got[manual] is None                    # the manual card has nothing to tie back to
