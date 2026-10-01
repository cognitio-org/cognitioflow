"""The lean spoken turn (2026-10-02): a voice turn reads the week being drilled in full, the past papers, the course-wide
notes and a map of every week, instead of the first 180k characters of everything. Replayed on 12 of his real EU
questions on gpt-6-luna: 83k -> 16k prompt tokens a turn, answers as good or sharper."""
import io
import unittest.mock as mock

import pytest

import run


def _course(client, pg):
    cid = client.post("/api/courses", json={"name": "Lean Law"}).json()["id"]
    for name, week, text in [("wk1 slides.txt", "1", "Van Gend en Loos direct effect " * 50),
                             ("wk3 slides.txt", "3", "Article 56 services MediLink establishment Gebhard " * 50),
                             ("past paper.txt", "", "Advise Jeanne on her B&B " * 50)]:
        fid = client.post(f"/api/courses/{cid}/files", files={"file": (name, io.BytesIO(text.encode()), "text/plain")}).json()["id"]
        pg.execute("UPDATE files SET week=%s, role=%s, selected=1 WHERE id=%s", (week, "exam" if not week else "slides", fid))
    pg.commit()
    client.post(f"/api/courses/{cid}/notes", json={"title": "Week 1 — Foundations", "body": "Direct effect: Van Gend en Loos. Primacy: Costa v ENEL. " * 60})
    client.post(f"/api/courses/{cid}/notes", json={"title": "Week 3 — Establishment and services", "body": "Gebhard four conditions. Article 56 services. " * 60})
    client.post(f"/api/courses/{cid}/notes", json={"title": "Method", "body": "Catch, justify, proportionality. " * 80})
    run._WEEK_TERMS.clear()
    return cid


def test_a_named_week_wins_spoken_or_in_digits(client, pg):
    cid = _course(client, pg)
    assert run._voice_week(cid, "can we do week three", []) == "3"
    assert run._voice_week(cid, "week 1 please", []) == "1"


def test_a_named_week_stays_until_another_is_named(client, pg):
    cid = _course(client, pg)
    assert run._voice_week(cid, "Let's begin", ["can we do week three", "Absolutely, services first."]) == "3"


def test_without_a_name_the_rarest_shared_words_pick_the_week(client, pg):
    cid = _course(client, pg)
    assert run._voice_week(cid, "what are the Gebhard conditions?", []) == "3"
    assert run._voice_week(cid, "what did Van Gend en Loos decide?", []) == "1"


def test_the_spoken_turn_reads_its_week_the_papers_and_the_map_but_not_other_weeks(client, pg):
    cid = _course(client, pg)
    parts, notes, week = run._voice_context(cid, "Gebhard conditions?", [])
    text = "\n".join(parts)
    assert week == "3" and "wk3 slides.txt" in text and "past paper.txt" in text and "wk1 slides.txt" not in text
    assert "Gebhard four conditions" in notes and "Catch, justify" in notes and "Costa v ENEL" not in notes
    assert "COURSE MAP" in notes and "Week 1: Week 1 — Foundations" in notes   # the other weeks are still named


def _system(client, cid, speech, monkeypatch, lean=True):
    monkeypatch.setattr(run, "VOICE_LEAN", lean)

    class FakeStream:
        text_stream = iter(["<speech>ok</speech>ok"])
        def __enter__(self): return self
        def __exit__(self, *a): return False

    fake = mock.MagicMock()
    fake.messages.stream.return_value = FakeStream()
    with mock.patch.object(run, "client", return_value=fake):
        client.post(f"/api/courses/{cid}/chat", json={"message": "Gebhard conditions?", "mode": "drill", "speech": speech})
    kw = fake.messages.stream.call_args.kwargs
    return "\n".join(b["text"] for b in kw["system"]), kw["messages"]


def test_voice_turns_are_lean_and_typed_turns_are_unchanged(client, monkeypatch, pg):
    cid = _course(client, pg)
    spoken, _ = _system(client, cid, True, monkeypatch)
    typed, _ = _system(client, cid, False, monkeypatch)
    assert "SPOKEN TURN" in spoken and "wk1 slides.txt\"" not in spoken
    assert "SPOKEN TURN" not in typed and "wk1 slides.txt" in typed and "wk3 slides.txt" in typed
    off, _ = _system(client, cid, True, monkeypatch, lean=False)
    assert "SPOKEN TURN" not in off and "wk1 slides.txt" in off   # CF_VOICE_LEAN=off puts it back exactly


def test_a_spoken_turn_carries_ten_messages_of_history(client, monkeypatch, pg):
    cid = _course(client, pg)
    for i in range(30):
        pg.execute("INSERT INTO messages VALUES(%s,%s,%s,%s,%s)", (f"m{i}", cid, "user" if i % 2 == 0 else "assistant", f"turn {i}", i))
    pg.commit()
    _, msgs = _system(client, cid, True, monkeypatch)
    assert len(msgs) == run.VOICE_HISTORY + 1   # ten before, and this question


@pytest.mark.parametrize("price,warmed", [((0.10, 0.10, 0.10, 0.50), False), ((1.0, 0.10, 1.25, 5.0), None)])
def test_warm_is_skipped_where_a_cached_token_costs_the_same(client, monkeypatch, pg, price, warmed):
    cid = _course(client, pg)
    monkeypatch.setattr(run, "_turn_model", lambda *a: "m-test")
    monkeypatch.setitem(run.llm.PRICES, "m-test", price)
    fake = mock.MagicMock()
    with mock.patch.object(run, "client", return_value=fake):
        r = client.post(f"/api/courses/{cid}/warm", json={"mode": "drill"}).json()
    if warmed is False:
        assert r == {"warmed": False, "why": "no cache discount on this model"} and not fake.messages.create.called
    else:
        assert fake.messages.create.called
