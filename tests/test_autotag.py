"""Generation-time card tagging: run._autotag_untagged tags only the just-made cards against the applied
blueprint, is a no-op without one, and respects the created>=since window. Needs docker Postgres
(client/pg fixtures); run.ask_model is faked, so this asserts the tagging wiring, not the model."""
import json
import time
from types import SimpleNamespace as NS

from psycopg.rows import dict_row

import run

TOPICS = [
    {"topic": "Free movement of goods", "weight": 60, "doctrines": ["Art 34 TFEU", "Cassis"]},
    {"topic": "Direct effect", "weight": 40, "doctrines": ["Van Gend"]},
]


def _reply(mapping):
    return NS(content=[NS(type="text", text=json.dumps(mapping))])


def _doctrines(pg, cid):
    pg.rollback()   # end any open txn so we read the app's committed rows
    return {r["id"]: r["doctrine"] for r in pg.cursor(row_factory=dict_row).execute(
        "SELECT id, COALESCE(doctrine,'') AS doctrine FROM cards WHERE course_id=%s", (cid,)).fetchall()}


def _mk(client, cid, front, back):
    return client.post(f"/api/courses/{cid}/cards", json={"front": front, "back": back}).json()["id"]


def test_autotag_tags_new_cards_when_blueprint_applied(client, pg, monkeypatch):
    cid = client.post("/api/courses", json={"name": "EU Tag"}).json()["id"]
    assert client.post(f"/api/courses/{cid}/blueprint/apply", json={"topics": TOPICS}).json()["applied"]
    t0 = time.time()
    c1 = _mk(client, cid, "What did Cassis de Dijon establish?", "Mutual recognition.")
    c2 = _mk(client, cid, "Van Gend en Loos?", "Direct effect of EU law.")

    calls = []
    monkeypatch.setattr(run, "ask_model", lambda *a, **k: (calls.append(k) or _reply({"1": 1, "2": 2})))
    run._autotag_untagged(cid, t0)

    d = _doctrines(pg, cid)
    assert d[c1] == "Free movement of goods" and d[c2] == "Direct effect"
    assert len(calls) == 1   # two cards -> one 30-card batch -> one model call


def test_autotag_is_a_noop_without_a_blueprint(client, pg, monkeypatch):
    cid = client.post("/api/courses", json={"name": "No Blueprint"}).json()["id"]
    t0 = time.time()
    c1 = _mk(client, cid, "Q", "A")

    calls = []
    monkeypatch.setattr(run, "ask_model", lambda *a, **k: (calls.append(1) or _reply({"1": 1})))
    run._autotag_untagged(cid, t0)

    assert _doctrines(pg, cid)[c1] == ""   # untouched
    assert calls == []                     # no blueprint -> model never called


def test_autotag_scopes_to_the_since_window(client, pg, monkeypatch):
    cid = client.post("/api/courses", json={"name": "Window"}).json()["id"]
    client.post(f"/api/courses/{cid}/blueprint/apply", json={"topics": TOPICS})
    c_old = _mk(client, cid, "A card made before this generation", "x")
    pg.execute("UPDATE cards SET created=%s WHERE id=%s", (time.time() - 100, c_old)); pg.commit()
    since = time.time()

    calls = []
    monkeypatch.setattr(run, "ask_model", lambda *a, **k: (calls.append(1) or _reply({"1": 1})))
    run._autotag_untagged(cid, since)

    assert _doctrines(pg, cid)[c_old] == ""   # older than the window -> not swept in
    assert calls == []                        # nothing in window -> no model call
