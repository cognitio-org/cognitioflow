"""Phase 12: grading a spoken answer outside the card queue."""
import json
from unittest import mock

import run


def _grader(payload):
    msg = mock.MagicMock()
    msg.content = [mock.MagicMock(type="text", text=json.dumps(payload))]
    fake = mock.MagicMock()
    fake.messages.create.return_value = msg
    return fake


def test_the_spoken_answer_reaches_the_grader_with_the_cached_rules(client):
    fake = _grader({"mastery": "shaky", "verdict": "Right test, wrong case",
                    "spoken": "Good on the test. Which case set it?", "note": "Cite Dassonville."})
    with mock.patch.object(run, "client", return_value=fake):
        r = client.post("/api/speech", json={"question": "What is an MEQR?",
                                             "answer": "um, anything that could hinder trade, like Cassis",
                                             "notes": "Dassonville defines MEQRs."})
    assert r.status_code == 200
    assert r.json()["mastery"] == "shaky" and r.json()["rating"] in (0, 1, 2, 3)
    kw = fake.messages.create.call_args.kwargs
    said = kw["messages"][0]["content"]
    assert "anything that could hinder trade" in said and "Dassonville defines MEQRs." in said
    assert kw["system"][0]["text"] == run.GRADER_RULES
    assert kw["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert kw["model"] == run.pick_model("drill", None), "auto-routing only — never a caller-chosen model"


def test_an_unreadable_grade_is_never_solid(client):
    with mock.patch.object(run, "client", return_value=_grader({"mastery": "excellent!!"})):
        r = client.post("/api/speech", json={"question": "Q", "answer": "A"})
    assert r.status_code == 200 and r.json()["mastery"] == "missed"


def test_no_card_is_rescheduled(client):
    fake = _grader({"mastery": "solid", "verdict": "Solid", "spoken": "Nailed it.", "note": ""})
    with mock.patch.object(run, "client", return_value=fake), mock.patch.object(run, "review") as review:
        client.post("/api/speech", json={"question": "Q", "answer": "A"})
    review.assert_not_called()


def test_an_empty_answer_is_refused_without_calling_the_model(client):
    fake = _grader({})
    with mock.patch.object(run, "client", return_value=fake):
        r = client.post("/api/speech", json={"question": "Q", "answer": "   "})
    assert r.status_code == 400
    fake.messages.create.assert_not_called()


def test_a_grader_outage_is_a_502_not_a_crash(client):
    fake = mock.MagicMock()
    fake.messages.create.side_effect = RuntimeError("down")
    with mock.patch.object(run, "client", return_value=fake):
        r = client.post("/api/speech", json={"question": "Q", "answer": "A"})
    assert r.status_code == 502
