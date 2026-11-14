"""Coverage map w4 through the real endpoints, once docs/pending-protected/blueprint-build.patch is applied to run.py
(skipped before): temperature 0 is sent, the same inputs return the saved map without a model call, ?fresh=1 always asks
the model, and one 502 is retried. Needs docker Postgres (client fixture); run.ask_model is faked."""
import inspect
import json
from types import SimpleNamespace as NS

import pytest

import run

pytestmark = pytest.mark.skipif("fresh" not in inspect.signature(run.blueprint_extract).parameters,
                                reason="needs docs/pending-protected/blueprint-build.patch applied to run.py")

WEEKS = [{"week": str(n), "title": f"Topic of week {n}", "topics": [f"Point {n}"], "readings": []} for n in (1, 2, 3)]
REPLY = {"weeks": [{"week": 1, "lo": [1], "law": ["Art 34 TFEU"]}, {"week": 2, "lo": [1], "law": ["Keck"]},
                   {"week": 3, "lo": [2], "law": ["Art 102 TFEU"]}]}


def _course(client):
    cid = client.post("/api/courses", json={"name": "EU Repeatable"}).json()["id"]
    assert client.post(f"/api/courses/{cid}/syllabus/apply", json={"weeks": WEEKS, "source": "demo"}).status_code == 200
    assert client.put(f"/api/courses/{cid}", json={"brief": {"learning_objectives": "Freedoms\nCompetition"}}).status_code == 200
    return cid


def _reply(obj):
    return NS(content=[NS(type="text", text=json.dumps(obj))], stop_reason="end_turn")


def test_same_inputs_return_the_saved_map_and_fresh_asks_again(client, monkeypatch):
    cid, sent = _course(client), []
    monkeypatch.setattr(run, "ask_model", lambda *a, **k: (sent.append(k) or _reply(REPLY)))
    b = client.post(f"/api/courses/{cid}/blueprint/extract").json()
    assert sent[0]["temperature"] == 0 and b["cached"] == "" and b["input_hash"]
    assert [t["topic"] for t in b["topics"]] == ["Topic of week 1", "Topic of week 2", "Topic of week 3"]
    assert client.post(f"/api/courses/{cid}/blueprint/apply", json=b).json()["applied"]
    assert client.get(f"/api/courses/{cid}/blueprint").json()["input_hash"] == b["input_hash"]

    again = client.post(f"/api/courses/{cid}/blueprint/extract").json()
    assert len(sent) == 1 and again["cached"] == "saved"
    fresh = client.post(f"/api/courses/{cid}/blueprint/extract?fresh=1").json()
    assert len(sent) == 2 and fresh["cached"] == ""
    strip = lambda x: {k: v for k, v in x.items() if k not in ("cached", "attempts", "source", "model")}
    assert strip(fresh) == strip(b)


def test_one_502_is_retried_and_a_timeout_twice_ends_in_a_504(client, monkeypatch):
    cid, n = _course(client), []

    def flaky(*a, **k):
        n.append(1)
        if len(n) == 1:
            raise run.HTTPException(502, "upstream")
        return _reply(REPLY)
    monkeypatch.setattr(run, "ask_model", flaky)
    r = client.post(f"/api/courses/{cid}/blueprint/extract?fresh=1")
    assert r.status_code == 200 and r.json()["attempts"] == 2

    monkeypatch.setattr(run, "ask_model", lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    assert client.post(f"/api/courses/{cid}/blueprint/extract?fresh=1").status_code == 504
