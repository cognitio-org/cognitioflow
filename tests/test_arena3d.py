"""Phase 11f: the Arena in 3D — the player and game JSON stay behind sign-in, and the show's question pack is built
from the signed-in user's own cards for the course asked for, in the player's pack schema."""
import io
import json
import re
import time
import types
import uuid

import pytest
from fastapi.testclient import TestClient


class FakeClient:
    """Stands in for anthropic.Anthropic(): returns queued replies and records every call."""
    def __init__(self, *replies):
        self.replies, self.calls, self.messages = list(replies), [], self

    def create(self, **kw):
        self.calls.append(kw)
        if not self.replies:
            raise AssertionError("unexpected model call")
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=self.replies.pop(0))],
                                     stop_reason="end_turn", model="fake-model")


@pytest.fixture
def fake(monkeypatch):
    import run
    def install(*replies):
        c = FakeClient(*replies)
        monkeypatch.setattr(run, "client", lambda: c)
        return c
    return install


def _card(client, cid, front, back, source="manual", week=""):
    return client.post(f"/api/courses/{cid}/cards", json={"front": front, "back": back, "source": source, "week": week}).json()["id"]


def _wrong_for(n):
    """Distractors for every question number the prompt can carry, none equal to a right answer."""
    return json.dumps([{"i": i, "wrong": [f"Wrong {i}a", f"Wrong {i}b", f"Wrong {i}c"]} for i in range(n)])


def _assert_pack_schema(pack):
    """games/SPEC_lawyer_tutor.md: the contract the player's lawyer.js reads."""
    assert pack["mode"] == "lawyer"
    for k in ("id", "course", "title", "logline", "tutor", "generated"):
        assert isinstance(pack[k], str) and pack[k]
    for q in pack["questions"]:
        assert re.fullmatch(r"q-[0-9a-f]{8}", q["id"])
        assert q["level"] in (1, 2, 3)
        assert isinstance(q["question"], str) and q["question"]
        assert [o["key"] for o in q["options"]] == ["A", "B", "C", "D"]
        texts = [o["text"] for o in q["options"]]
        assert len(set(texts)) == 4 and all(texts)
        assert q["answer"] in ("A", "B", "C", "D")
        assert q["quote"].strip()
        assert q["cites"] and all(c["source"] for c in q["cites"])
        assert q["week"] is None or isinstance(q["week"], int)


# ---------------------------------------------------------------- the pack
def test_lawyer_pack_schema_answers_and_quotes(client, fake):
    import run
    k1 = _card(client, "eu", "Which case set the MEQR scope test?", "Dassonville", source="W2 slides.txt", week="2")
    k2 = _card(client, "eu", "What did Keck carve out?", "Certain selling arrangements")
    client.post("/api/courses/eu/files", files={"file": ("W2 slides.txt", io.BytesIO(
        b"Welcome to week two. The scope test for MEQRs comes from Dassonville: all trading rules capable of hindering trade. "
        b"Unrelated closing words here."), "text/plain")}, data={"week": "2"})
    fc = fake(_wrong_for(2))
    pack = client.get("/api/courses/eu/lawyer-pack").json()
    _assert_pack_schema(pack)
    assert fc.calls[0]["model"] == run.CHEAP_MODEL  # the /quiz distractor path, never above CF_MODEL
    assert pack["course"] == "European Law" and pack["course_id"] == "eu"
    by_card = {q["card_id"]: q for q in pack["questions"]}
    assert set(by_card) == {k1, k2}
    for kid, right in ((k1, "Dassonville"), (k2, "Certain selling arrangements")):
        q = by_card[kid]
        assert next(o["text"] for o in q["options"] if o["key"] == q["answer"]) == right
        assert q["explanation"] == right
    # the quote is the source file's own sentence; a card without a file quotes the card itself
    assert "Dassonville" in by_card[k1]["quote"] and by_card[k1]["quote"] in "Welcome to week two. The scope test for MEQRs comes from Dassonville: all trading rules capable of hindering trade."
    assert by_card[k1]["cites"] == [{"source": "W2 slides.txt"}] and by_card[k1]["week"] == 2
    assert by_card[k2]["quote"] == "Certain selling arrangements" and by_card[k2]["week"] is None


def test_lawyer_pack_cites_the_slide_a_quote_came_from(client, fake, pg):
    import run
    _card(client, "eu", "What is the Cassis rule of reason?", "Mandatory requirements", source="L3.pptx")
    fid = uuid.uuid4().hex
    text = "--- slide 1 ---\nIntroduction\n\n--- slide 7 ---\nCassis de Dijon introduced mandatory requirements as a rule of reason."
    pg.execute("INSERT INTO files(id,course_id,name,kind,key,text,chars,selected,status,week,created) VALUES(%s,'eu','L3.pptx','pptx','',%s,%s,1,'indexed','',%s)",
               (fid, text, len(text), time.time())); pg.commit()
    fake(_wrong_for(1))
    q = client.get("/api/courses/eu/lawyer-pack").json()["questions"][0]
    assert q["cites"] == [{"source": "L3.pptx", "page": 7}] and "rule of reason" in q["quote"]


def test_lawyer_pack_levels_follow_the_scheduler(client, fake, pg):
    easy = _card(client, "eu", "Easy?", "Yes easy")
    hard = _card(client, "eu", "Hard?", "Yes hard")
    new = _card(client, "eu", "New?", "Yes new")
    pg.execute("UPDATE cards SET difficulty=2 WHERE id=%s", (easy,))
    pg.execute("UPDATE cards SET reps=3, ease=1.9 WHERE id=%s", (hard,)); pg.commit()
    fake(_wrong_for(3))
    levels = {q["card_id"]: q["level"] for q in client.get("/api/courses/eu/lawyer-pack").json()["questions"]}
    assert levels == {easy: 1, hard: 3, new: 2}


def test_lawyer_pack_caps_at_fifteen_and_uses_only_this_course(client, fake):
    for i in range(22):
        _card(client, "eu", f"EU question {i}?", f"EU answer {i}")
    _card(client, "prop", "Property question?", "Property answer")
    fc = fake(_wrong_for(20))
    pack = client.get("/api/courses/eu/lawyer-pack").json()
    assert len(pack["questions"]) == 15
    prompt = fc.calls[0]["messages"][0]["content"]
    assert "Property" not in prompt and all(q["question"].startswith("EU question") for q in pack["questions"])


def test_lawyer_pack_without_cards_makes_no_model_call(client, fake):
    fake()  # any call would raise
    pack = client.get("/api/courses/prop/lawyer-pack").json()
    assert pack["questions"] == [] and pack["course"] == "Property Law"


def test_lawyer_pack_other_users_course_is_404(client, fake, pg):
    fake()
    other = uuid.uuid4().hex
    pg.execute("INSERT INTO users(id,email,name,created) VALUES(%s,'someone@example.com','',%s)", (other, time.time()))
    pg.execute("INSERT INTO courses(id,name,accent,tutor_prompt,created,user_id) VALUES('theirs','Their course','#000','',%s,%s)", (time.time(), other))
    pg.execute("INSERT INTO cards(id,course_id,front,back,due,created) VALUES('tc1','theirs','Q','A','2020-01-01',%s)", (time.time(),)); pg.commit()
    assert client.get("/api/courses/theirs/lawyer-pack").status_code == 404
    assert client.get("/api/courses/theirs/docket").status_code == 404
    assert client.get("/api/courses/nope/lawyer-pack").status_code == 404
    mine = client.post("/api/courses", json={"name": "Mine"}).json()["id"]  # owned by the signed-in user
    assert client.get(f"/api/courses/{mine}/lawyer-pack").status_code == 200


# ---------------------------------------------------------------- the Case Docket
def test_docket_lists_only_this_courses_games(client):
    eu = client.get("/api/courses/eu/docket").json()
    assert eu and {g["course"] for g in eu} == {"IIEL"}
    game = client.get(eu[0]["path"])
    assert game.status_code == 200 and game.json()["id"] == eu[0]["id"]
    assert client.get("/api/courses/prop/docket").json() == []
    assert client.get(f"/api/courses/prop/docket/{eu[0]['id']}").status_code == 404   # an IIEL game is not a Property Law game
    assert client.get("/api/courses/eu/docket/..%2F..%2Frun").status_code == 404
    assert client.get("/api/courses/eu/docket/nope").status_code == 404


def test_game_files_are_not_served_statically(client):
    assert client.get("/play/player/index.html").status_code == 200
    assert client.get("/play/player/lawyer.js").status_code == 200
    for path in ("/play/games/index.json", "/play/games/IIEL/w1-direct-effect-supremacy.json",
                 "/static/play/games/index.json", "/play/player/../games/index.json"):
        assert client.get(path).status_code == 404, path


def test_player_cache_headers(client):
    """Versioned folders are cached for a year; the player's own files and game JSON always revalidate."""
    for path in ("/play/player/vendor-r170/three.module.js", "/play/player/vendor-r170/addons/loaders/GLTFLoader.js",
                 "/play/player/fonts-v1/Oswald-var.woff2"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=31536000, immutable", path
    for path in ("/play/player/index.html", "/play/player/main.js", "/play/player/fonts-v1/fonts.css/../../lawyer.css"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path
    etag = client.get("/play/player/main.js").headers["etag"]
    r = client.get("/play/player/main.js", headers={"If-None-Match": etag})
    assert r.status_code == 304 and r.headers["cache-control"] == "no-cache"
    game = client.get("/api/courses/eu/docket").json()[0]["path"]
    assert client.get(game).headers["cache-control"] == "private, no-cache"
    # the import map points at the versioned folder, so a three.js upgrade has to rename it
    html = client.get("/play/player/index.html").text
    assert '"three": "./vendor-r170/three.module.js"' in html and "./fonts-v1/fonts.css" in html


# ---------------------------------------------------------------- signed out
@pytest.fixture
def signed_out(monkeypatch):
    import auth
    monkeypatch.delenv("AUTH", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-" + "x" * 32)
    monkeypatch.setenv("ALLOWED_EMAILS", "matej@mgms.eu")
    from run import app, init
    init()
    return auth, TestClient(app, base_url="http://localhost")


def test_player_and_packs_need_sign_in(signed_out, fake):
    auth, web = signed_out
    fake()
    for path in ("/play/player/index.html", "/play/player/main.js", "/play/player/vendor-r170/three.module.js"):
        r = web.get(path, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "/auth/login", path
    for path in ("/api/courses/eu/lawyer-pack", "/api/courses/eu/docket", "/api/courses/eu/docket/w1-direct-effect-supremacy"):
        assert web.get(path).status_code == 401, path
    web.cookies.set(auth.COOKIE, auth.serializer().dumps({"user": {"email": "matej@mgms.eu", "name": ""}}))
    assert web.get("/play/player/index.html").status_code == 200
    assert web.get("/api/courses/eu/docket").status_code == 200
