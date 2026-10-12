"""Phase 18 — card generation routes to the self-hosted model, and the interaction is captured
de-identified for later training. Needs docker Postgres (the `client`/`pg` fixtures). No real endpoint:
llm.local_create is replaced with a fake, so this asserts the routing and the capture, not the model."""
from types import SimpleNamespace as NS

from psycopg.rows import dict_row

import llm
import run

# A note that carries exactly the identifiers the capture must strip.
NOTE = ("Ownership under Article 5:1 BW. Contact s1234567 at jan@example.com about this. "
        "A rule, a case, a citation. " * 8)


def _local_msg(cards='[{"front":"What is ownership?","back":"The most comprehensive right (Art. 5:1 BW)."}]'):
    u = NS(input_tokens=900, output_tokens=40, cache_read_input_tokens=0, cache_creation_input_tokens=0,
           cost=0, provider="local")
    return NS(model="qwen2.5:7b-instruct", usage=u, content=[NS(type="text", text=cards)], stop_reason="end_turn")


def _rows(pg):
    return pg.cursor(row_factory=dict_row).execute("SELECT * FROM card_gen_samples ORDER BY at").fetchall()


def test_local_routing_captures_a_de_identified_sample(client, pg, monkeypatch):
    monkeypatch.setattr(llm, "LOCAL_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(llm, "LOCAL_TASKS", ("cards",))
    monkeypatch.setattr(llm, "local_create", lambda **kw: _local_msg())

    cid = client.post("/api/courses", json={"name": "Capture Law"}).json()["id"]
    nid = client.post(f"/api/courses/{cid}/notes", json={"title": "Week 1 — Ownership", "body": NOTE}).json()["id"]
    r = client.post(f"/api/courses/{cid}/cards/generate", json={"note_id": nid, "count": 5})
    assert r.status_code == 200 and r.json()["made"] == 1 and r.json()["grounded"] is True

    samples = _rows(pg)
    assert len(samples) == 1
    s = samples[0]
    assert s["provider"] == "local" and s["model"] == "qwen2.5:7b-instruct"
    assert s["source_kind"] == "note" and s["grounded"] is True and s["made"] == 1 and s["requested"] == 5
    # identity and personal content stripped; the law content kept
    blob = s["source_text"] + " " + s["cards_json"]
    assert "jan@example.com" not in blob and "s1234567" not in blob
    assert "[email]" in s["source_text"] and "[student number]" in s["source_text"]
    assert "Article 5:1 BW" in s["source_text"]

    # the generated card is tied back to its capture row for the feedback signal
    card = pg.cursor(row_factory=dict_row).execute(
        "SELECT gen_sample_id FROM cards WHERE course_id=%s", (cid,)).fetchone()
    assert card["gen_sample_id"] == s["id"]


def _cloud_msg(cards='[{"front":"What is ownership?","back":"The most comprehensive right (Art. 5:1 BW)."}]'):
    """A cloud reply: no provider on the usage (so run.py falls back to llm.PROVIDER, e.g. 'anthropic')."""
    u = NS(input_tokens=900, output_tokens=40, cache_read_input_tokens=0, cache_creation_input_tokens=0,
           cost=0.004, provider=None)
    return NS(model="claude-haiku-4-5", usage=u, content=[NS(type="text", text=cards)], stop_reason="end_turn")


def test_cloud_path_also_captures(client, pg, monkeypatch):
    """Phase 19 (Matej decision b): the self-hosted tier off → the cloud cheap tier answers AND the
    interaction is still captured de-identified (grounded False), while the response shape is unchanged."""
    monkeypatch.setattr(llm, "LOCAL_BASE_URL", "")   # the default: no self-hosted tier
    monkeypatch.setattr(run, "client", lambda: NS(messages=NS(create=lambda **kw: _cloud_msg())))

    cid = client.post("/api/courses", json={"name": "Off Law"}).json()["id"]
    nid = client.post(f"/api/courses/{cid}/notes", json={"title": "Week 1", "body": NOTE}).json()["id"]
    r = client.post(f"/api/courses/{cid}/cards/generate", json={"note_id": nid, "count": 3})
    assert r.status_code == 200 and "grounded" not in r.json()   # cloud response shape unchanged (callers read .made)

    samples = _rows(pg)
    assert len(samples) == 1
    s = samples[0]
    assert s["grounded"] is False and s["model"] == "claude-haiku-4-5"
    # identity stripped on the cloud path too
    assert "jan@example.com" not in (s["source_text"] + " " + s["cards_json"])
    assert "[student number]" in s["source_text"] and "Article 5:1 BW" in s["source_text"]
    card = pg.cursor(row_factory=dict_row).execute(
        "SELECT gen_sample_id FROM cards WHERE course_id=%s", (cid,)).fetchone()
    assert card["gen_sample_id"] == s["id"]


def test_capture_can_be_switched_off(client, pg, monkeypatch):
    """CF_CARD_CAPTURE=off disables the flywheel without a deploy (privacy by default, Art. 25)."""
    monkeypatch.setattr(llm, "LOCAL_BASE_URL", "")
    monkeypatch.setattr(run, "client", lambda: NS(messages=NS(create=lambda **kw: _cloud_msg())))
    monkeypatch.setenv("CF_CARD_CAPTURE", "off")

    cid = client.post("/api/courses", json={"name": "No Capture Law"}).json()["id"]
    nid = client.post(f"/api/courses/{cid}/notes", json={"title": "Week 1", "body": NOTE}).json()["id"]
    r = client.post(f"/api/courses/{cid}/cards/generate", json={"note_id": nid, "count": 3})
    assert r.status_code == 200 and r.json()["made"] == 1
    assert _rows(pg) == []
