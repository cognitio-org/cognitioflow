"""Games written from his files: drafted by a writer, checked, reviewed, and playable only once approved."""
import io
import json
import unittest.mock as mock

import run
from test_docketgen import game


def _reply(obj):
    r = mock.MagicMock(); r.content = [mock.MagicMock(type="text", text=json.dumps(obj))]; r.stop_reason = "end_turn"; r.model = "claude-test"
    return r


def _course(client, name="Land Law"):
    cid = client.post("/api/courses", json={"name": name}).json()["id"]
    client.post(f"/api/courses/{cid}/files", files={"file": ("W3 lecture.txt", io.BytesIO(b"Registration is constitutive. Art 3:89 BW."), "text/plain")},
                data={"week": "3"})
    return cid


def _write(cid, replies):
    fake = mock.MagicMock(); fake.messages.create.side_effect = [_reply(r) for r in replies]
    with mock.patch.object(run, "client", return_value=fake):
        gid = run._docket_queue(cid, ["3"])[0]
        run._docket_write(cid, gid)
    return gid, fake


def test_a_week_is_written_reviewed_and_waits_for_approval(client):
    cid = _course(client)
    gid, fake = _write(cid, [game(), {"verdict": "ok", "issues": []}])
    assert fake.messages.create.call_count == 2                     # writer, reviewer
    sent = fake.messages.create.call_args_list[0].kwargs["messages"][0]["content"]
    assert 'key="S1" file="W3 lecture.txt"' in sent and "Registration is constitutive." in sent
    d = client.get(f"/api/courses/{cid}/docket-drafts").json()["games"][0]
    assert d["status"] == "draft" and d["title"] == "The Canal House" and d["rounds"] == 2
    assert [g["id"] for g in client.get(f"/api/courses/{cid}/docket").json()] == []           # not in the library yet
    preview = client.get(f"/api/courses/{cid}/docket", params={"draft": gid}).json()
    assert preview[0]["id"] == gid and preview[0]["draft"] is True                             # but he can play it first
    full = client.get(f"/api/courses/{cid}/docket-drafts/{gid}").json()
    assert full["questions"][0]["options"][1]["correct"] is True
    assert client.post(f"/api/courses/{cid}/docket-drafts/{gid}/approve").json()["status"] == "approved"
    lib = client.get(f"/api/courses/{cid}/docket").json()
    assert lib[0]["id"] == gid and not lib[0]["draft"]
    g = client.get(f"/api/courses/{cid}/docket/{gid}").json()
    assert g["id"] == gid and g["sources"]["S1"]["file"] == "W3 lecture.txt" and g["scenes"][1]["quiz"]["options"][1]["stamp"] == "SUSTAINED"


def test_a_broken_game_gets_one_repair_and_then_fails_honestly(client):
    cid = _course(client, "Bad Law")
    bad = game(); bad["scenes"][1]["quiz"]["options"][0]["correct"] = True
    gid, fake = _write(cid, [bad, bad])
    assert fake.messages.create.call_count == 2                     # write, repair; no reviewer for a broken game
    assert "exactly one correct" in fake.messages.create.call_args_list[1].kwargs["messages"][0]["content"]
    row = run.rows("SELECT status,error FROM docket_games WHERE id=?", gid)[0]
    assert row["status"] == "failed" and "checks" in row["error"]
    assert client.get(f"/api/courses/{cid}/docket/{gid}").status_code == 404


def test_a_high_issue_from_the_reviewer_is_revised_and_rereviewed(client):
    cid = _course(client, "Review Law")
    fixed = game(); fixed["title"] = "The Canal House, corrected"
    gid, fake = _write(cid, [game(), {"verdict": "fix", "issues": [{"where": "q2 option B", "problem": "wrong rule", "severity": "high"}]},
                             fixed, {"verdict": "ok", "issues": []}])
    assert fake.messages.create.call_count == 4
    d = client.get(f"/api/courses/{cid}/docket-drafts/{gid}").json()
    assert d["title"] == "The Canal House, corrected" and d["review"]["revised"] is True and d["review"]["issues"] == []


def test_discard_keeps_it_out_and_new_material_brings_the_week_back(client, monkeypatch):
    cid = _course(client, "Again Law")
    gid, _ = _write(cid, [game(), {"verdict": "ok", "issues": []}])
    client.post(f"/api/courses/{cid}/docket-drafts/{gid}/discard")
    assert client.get(f"/api/courses/{cid}/docket-drafts").json()["games"] == []
    assert run._docket_due(cid) == []                                # discarded: not rewritten on its own
    client.post(f"/api/courses/{cid}/files", files={"file": ("W3 WG.txt", io.BytesIO(b"WG answers"), "text/plain")}, data={"week": "3"})
    assert run._docket_due(cid) == ["3"]
    monkeypatch.setattr(run, "DOCKET_AUTO", True)
    started = []
    monkeypatch.setattr(run, "_docket_start", lambda c, ids: started.append(ids))
    assert client.get(f"/api/courses/{cid}/docket-drafts").json()["started"] == ["3"]
    assert started and run.rows("SELECT status FROM docket_games WHERE id=?", started[0][0])[0]["status"] == "writing"


def test_another_users_course_is_not_reachable(client):
    cid = _course(client, "Private Law")
    gid, _ = _write(cid, [game(), {"verdict": "ok", "issues": []}])
    assert client.get(f"/api/courses/nope/docket-drafts/{gid}").status_code == 404
