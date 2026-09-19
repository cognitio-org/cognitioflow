"""Phase 11g: backend result caching for quiz distractors and hints.

Both /quiz and /hint used to call CHEAP_MODEL on every request even though the prompts are too short
for Anthropic prompt caching to help. These tests assert the model is only ever called for genuinely
uncached (or stale) work, and that the fallback hint text is never persisted.
"""
import hashlib
import json
import time
import unittest.mock as mock

from fastapi.testclient import TestClient


def _course_id(client: TestClient) -> str:
    r = client.get("/api/courses")
    assert r.status_code == 200
    return next(c["id"] for c in r.json() if c["id"] == "eu")


def _make_card(client: TestClient, cid: str, front: str, back: str) -> str:
    r = client.post(f"/api/courses/{cid}/cards", json={"front": front, "back": back, "source": "test"})
    assert r.status_code == 200
    return r.json()["id"]


def _fake_distractor_client(pairs):
    """pairs: [(question index, [wrong, wrong, wrong]), ...] -> a fake Anthropic client returning that JSON."""
    payload = json.dumps([{"i": i, "wrong": wrong} for i, wrong in pairs])
    msg = mock.MagicMock()
    msg.content = [mock.MagicMock(type="text", text=payload)]
    fake = mock.MagicMock()
    fake.messages.create.return_value = msg
    return fake


def _fake_text_client(text: str):
    msg = mock.MagicMock()
    msg.content = [mock.MagicMock(type="text", text=text)]
    fake = mock.MagicMock()
    fake.messages.create.return_value = msg
    return fake


# ---------------------------------------------------------------- quiz() distractor cache

def test_quiz_second_call_zero_model_calls(client: TestClient):
    cid = _course_id(client)
    _make_card(client, cid, "What is Art 34 TFEU?", "Prohibits quantitative restrictions on imports and MEQRs")

    fake = _fake_distractor_client([(0, ["Prohibits exports only", "Applies only to services", "A defence, not a prohibition"])])
    import run
    with mock.patch.object(run, "client", return_value=fake):
        r1 = client.post(f"/api/courses/{cid}/quiz", json={"count": 1})
    assert r1.status_code == 200
    body1 = r1.json()
    assert len(body1) == 1 and len(body1[0]["options"]) == 4
    assert fake.messages.create.call_count == 1

    fake.messages.create.reset_mock()
    with mock.patch.object(run, "client", return_value=fake):
        r2 = client.post(f"/api/courses/{cid}/quiz", json={"count": 1})
    assert r2.status_code == 200
    body2 = r2.json()
    assert len(body2) == 1 and len(body2[0]["options"]) == 4
    assert fake.messages.create.call_count == 0  # fully cached -> the model is never called
    assert set(body2[0]["options"]) == set(body1[0]["options"])  # same four strings (order may be reshuffled)


def test_quiz_regenerates_when_card_back_changes(client: TestClient, pg):
    cid = _course_id(client)
    kid = _make_card(client, cid, "Q1", "Original answer text")

    fake1 = _fake_distractor_client([(0, ["Wrong A", "Wrong B", "Wrong C"])])
    import run
    with mock.patch.object(run, "client", return_value=fake1):
        r1 = client.post(f"/api/courses/{cid}/quiz", json={"count": 1})
    assert r1.status_code == 200 and fake1.messages.create.call_count == 1

    pg.execute("UPDATE cards SET back=%s WHERE id=%s", ("Changed answer text", kid))
    pg.commit()

    fake2 = _fake_distractor_client([(0, ["New Wrong A", "New Wrong B", "New Wrong C"])])
    with mock.patch.object(run, "client", return_value=fake2):
        r2 = client.post(f"/api/courses/{cid}/quiz", json={"count": 1})
    assert r2.status_code == 200
    assert fake2.messages.create.call_count == 1  # stale back_hash -> regenerated, not served from the old cache row
    assert r2.json()[0]["correct"] == "Changed answer text"


def test_quiz_only_sends_uncached_cards_to_model(client: TestClient, pg):
    cid = _course_id(client)
    kid_a = _make_card(client, cid, "Q-A", "Answer A")
    _make_card(client, cid, "Q-B", "Answer B")

    back_hash = hashlib.sha1(b"Answer A").hexdigest()
    pg.execute("INSERT INTO card_distractors(card_id,back_hash,wrong,model,created) VALUES(%s,%s,%s,%s,%s)",
               (kid_a, back_hash, json.dumps(["Wrong 1", "Wrong 2", "Wrong 3"]), "claude-haiku-4-5", time.time()))
    pg.commit()

    fake = _fake_distractor_client([(0, ["Fresh Wrong 1", "Fresh Wrong 2", "Fresh Wrong 3"])])
    import run
    with mock.patch.object(run, "client", return_value=fake):
        r = client.post(f"/api/courses/{cid}/quiz", json={"count": 2})
    assert r.status_code == 200
    assert fake.messages.create.call_count == 1  # one call total, covering only the uncached card

    prompt = fake.messages.create.call_args.kwargs["messages"][0]["content"]
    questions_section = prompt.split("OTHER CARDS")[0]
    assert "Q-B" in questions_section and "Q-A" not in questions_section

    body = r.json()
    assert len(body) == 2
    a = next(x for x in body if x["correct"] == "Answer A")
    assert set(a["options"]) == {"Answer A", "Wrong 1", "Wrong 2", "Wrong 3"}


def test_quiz_skips_card_without_three_valid_distractors(client: TestClient):
    cid = _course_id(client)
    _make_card(client, cid, "Q1", "Right answer")
    # Only two distinct, non-echoing wrongs -> never show fewer than four options.
    fake = _fake_distractor_client([(0, ["Only two", "Only two", "Right answer"])])
    import run
    with mock.patch.object(run, "client", return_value=fake):
        r = client.post(f"/api/courses/{cid}/quiz", json={"count": 1})
    assert r.status_code == 200
    assert r.json() == []


def test_quiz_unknown_course_is_404(client: TestClient):
    assert client.post("/api/courses/does-not-exist/quiz", json={"count": 1}).status_code == 404


# ---------------------------------------------------------------- hint() cache

def test_hint_twice_is_one_model_call(client: TestClient):
    cid = _course_id(client)
    fake = _fake_text_client("Look at Article 34 TFEU and its scope over MEQRs.")
    payload = {"question": "What does Art 34 prohibit?", "options": ["A", "B", "C", "D"]}
    import run
    with mock.patch.object(run, "client", return_value=fake):
        r1 = client.post(f"/api/courses/{cid}/hint", json=payload)
        r2 = client.post(f"/api/courses/{cid}/hint", json=payload)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["hint"] == r2.json()["hint"] != ""
    assert fake.messages.create.call_count == 1


def test_hint_fallback_not_stored_and_retried(client: TestClient, pg):
    cid = _course_id(client)
    payload = {"question": "Stuck question?", "options": ["A", "B"]}
    import run

    failing = mock.MagicMock()
    failing.messages.create.side_effect = RuntimeError("boom")
    with mock.patch.object(run, "client", return_value=failing):
        r1 = client.post(f"/api/courses/{cid}/hint", json=payload)
    assert r1.status_code == 200
    assert r1.json()["hint"] == run.HINT_FALLBACK

    key = run._hint_key(cid, payload["question"], payload["options"])
    assert pg.execute("SELECT 1 FROM hint_cache WHERE key=%s", (key,)).fetchone() is None

    fake = _fake_text_client("Second try works.")
    with mock.patch.object(run, "client", return_value=fake):
        r2 = client.post(f"/api/courses/{cid}/hint", json=payload)
    assert r2.status_code == 200
    assert r2.json()["hint"] == "Second try works."
    assert fake.messages.create.call_count == 1  # the fallback wasn't cached, so the model was tried again


def test_hint_expired_entry_is_regenerated(client: TestClient, pg):
    cid = _course_id(client)
    payload = {"question": "Old question?", "options": ["A", "B", "C"]}
    import run
    key = run._hint_key(cid, payload["question"], payload["options"])
    old = time.time() - run.HINT_TTL_S - 3600
    pg.execute("INSERT INTO hint_cache(key,course_id,hint,model,created) VALUES(%s,%s,%s,%s,%s)",
               (key, cid, "A stale hint.", "claude-haiku-4-5", old))
    pg.commit()

    fake = _fake_text_client("A fresh hint.")
    with mock.patch.object(run, "client", return_value=fake):
        r = client.post(f"/api/courses/{cid}/hint", json=payload)
    assert r.status_code == 200
    assert r.json()["hint"] == "A fresh hint."
    assert fake.messages.create.call_count == 1


def test_hint_unknown_course_is_404(client: TestClient):
    assert client.post("/api/courses/does-not-exist/hint", json={"question": "q", "options": []}).status_code == 404
