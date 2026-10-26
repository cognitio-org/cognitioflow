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


def test_the_server_writes_no_game_unless_asked_to(client, monkeypatch):
    """He does not run CognitioFlow on paid API credit (2026-09-30): off by default, Write a game refused."""
    monkeypatch.setattr(run, "DOCKET_AUTO", False)
    cid = _course(client, "Quiet Law")
    started = []
    monkeypatch.setattr(run, "_docket_start", lambda c, ids: started.append(ids))
    d = client.get(f"/api/courses/{cid}/docket-drafts").json()
    assert d["auto"] is False and d["started"] == [] and not started
    assert client.post(f"/api/courses/{cid}/docket-drafts", json={"week": "3"}).status_code == 400


def _course_multi(client, name="Across Weeks"):
    cid = client.post("/api/courses", json={"name": name}).json()["id"]
    client.post(f"/api/courses/{cid}/files", files={"file": ("W3 lecture.txt", io.BytesIO(b"Registration is constitutive. Art 3:89 BW."), "text/plain")}, data={"week": "3"})
    client.post(f"/api/courses/{cid}/files", files={"file": ("W4 lecture.txt", io.BytesIO(b"Good faith acquisition under Art 3:86 BW."), "text/plain")}, data={"week": "4"})
    client.post(f"/api/courses/{cid}/files", files={"file": ("W5 lecture.txt", io.BytesIO(b"Priority of limited rights, Art 3:21 BW."), "text/plain")}, data={"week": "5"})
    return cid


def test_scope_parsing_and_labels():
    assert run._scope_weeks("5") == ["5"]
    assert run._scope_weeks("3,4,5") == ["3", "4", "5"]
    assert run._scope_weeks("all") is None and run._scope_weeks("") is None
    assert run._scope_label("5") == "week 5"
    assert run._scope_label("3,4,5") == "weeks 3, 4, 5"
    assert run._scope_label("all") == "the whole course"


def test_docket_files_honours_scope(client):
    cid = _course_multi(client)
    assert {f["week"] for f in run._docket_files(cid, "4")} == {"4"}               # one week
    assert {f["week"] for f in run._docket_files(cid, "3,5")} == {"3", "5"}        # a chosen set
    assert {f["week"] for f in run._docket_files(cid, "all")} == {"3", "4", "5"}   # the whole course


def test_a_whole_course_game_draws_from_every_week(client):
    cid = _course_multi(client)
    fake = mock.MagicMock(); fake.messages.create.side_effect = [_reply(r) for r in [game(), {"verdict": "ok", "issues": []}]]
    with mock.patch.object(run, "client", return_value=fake):
        gid = run._docket_queue(cid, ["all"])[0]
        run._docket_write(cid, gid)
    sent = fake.messages.create.call_args_list[0].kwargs["messages"][0]["content"]
    assert "W3 lecture.txt" in sent and "W4 lecture.txt" in sent and "W5 lecture.txt" in sent   # every week reached the writer
    assert "covering the whole course" in sent
    d = client.get(f"/api/courses/{cid}/docket-drafts").json()["games"][0]
    assert d["status"] == "draft" and d["scope"] == "the whole course"


def test_broad_scope_fills_with_exam_relevant_material():
    """A broad scope orders each week's lower-authority files by how closely they match the past exam, so the
    writer's budget fills with exam-relevant material; exams and WG still lead by authority."""
    exam = {"week": "1", "role": "exam", "text": "State aid Article 107 TFEU selectivity private investor test"}
    on = {"week": "2", "role": "lecture", "text": "State aid, Article 107 TFEU, selectivity and the market economy investor principle."}
    off = {"week": "2", "role": "lecture", "text": "Free movement of goods, Article 34 TFEU, quantitative restrictions."}
    tagged = run._tag_exam_relevance([exam, on, off])
    assert tagged[1]["_rel"] > tagged[2]["_rel"] > 0.0                 # on-topic lecture scores above off-topic
    picked = run._budget_across_weeks(run._tag_exam_relevance([exam, off, on]))   # off deliberately before on
    assert picked[0]["role"] == "exam"                                # exam still leads by authority
    wk2 = [f for f in picked if f["week"] == "2"]
    assert wk2[0]["text"].startswith("State aid")                     # the exam-relevant lecture comes first


def test_no_exam_signal_leaves_order_to_authority_and_coverage():
    """With no exam/WG text, every relevance score is 0.0 and selection is the authority+coverage order."""
    a = {"week": "1", "role": "lecture", "text": "offer and acceptance"}
    b = {"week": "2", "role": "lecture", "text": "consideration and intention"}
    tagged = run._tag_exam_relevance([a, b])
    assert all(f["_rel"] == 0.0 for f in tagged)
    assert {f["week"] for f in run._budget_across_weeks(tagged)} == {"1", "2"}


# --- Phase B: games grounded in the shared EU-law / CJEU knowledge ------------------------------------------------ #
class _FakeResp:
    def __init__(self, payload): self._b = json.dumps(payload).encode()
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_law_sources_off_by_default(monkeypatch):
    monkeypatch.setattr(run, "DOCKET_RAG_URL", "")
    assert run._law_sources([{"text": "Art 107 TFEU", "role": "exam"}]) == []


def test_law_sources_parses_hits(monkeypatch):
    monkeypatch.setattr(run, "DOCKET_RAG_URL", "http://127.0.0.1:8100")
    hits = {"hits": [{"doc_id": "32019L0790", "title": "Copyright Directive", "snippet": "Article 17 governs online platforms."}]}
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResp(hits))
    out = run._law_sources([{"text": "copyright online platforms", "role": "exam"}])
    assert len(out) == 1 and out[0]["kind"] == "law" and out[0]["role"] == "cases"
    assert "32019L0790" in out[0]["name"] and "Article 17" in out[0]["text"]


def test_law_sources_degrade_on_error(monkeypatch):
    monkeypatch.setattr(run, "DOCKET_RAG_URL", "http://127.0.0.1:8100")
    def boom(*a, **k): raise OSError("connection refused")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    assert run._law_sources([{"text": "anything", "role": "exam"}]) == []


def test_a_game_can_cite_shared_law_because_it_joins_the_citecheck_corpus(client, monkeypatch):
    """A citation to real EU law passes only because the retrieved law passage is added to the verification corpus;
    with no law source the same citation would be flagged as not in the files."""
    cid = _course(client, "State Aid Law")
    law = [{"id": "law:12008E107", "name": "12008E107 — TFEU", "text": "Article 107 TFEU prohibits State aid that distorts competition.",
            "role": "cases", "kind": "law", "week": "", "_rel": 0.0}]
    g = game(); g["verdict"]["takeaway"] = "Remember Article 107 TFEU on State aid."

    monkeypatch.setattr(run, "_law_sources", lambda files, k=4: law)
    fake = mock.MagicMock(); fake.messages.create.side_effect = [_reply(g), _reply({"verdict": "ok", "issues": []})]
    with mock.patch.object(run, "client", return_value=fake):
        gid = run._docket_queue(cid, ["3"])[0]; run._docket_write(cid, gid)
    sent = fake.messages.create.call_args_list[0].kwargs["messages"][0]["content"]
    assert 'kind="law"' in sent and "Article 107 TFEU prohibits State aid" in sent     # law reached the writer as a source
    row = run.rows("SELECT status FROM docket_games WHERE id=?", gid)[0]
    assert row["status"] == "draft"                                                    # citation verified -> no failure

    monkeypatch.setattr(run, "_law_sources", lambda files, k=4: [])                    # without the law source...
    fake2 = mock.MagicMock(); fake2.messages.create.side_effect = [_reply(g), _reply(g)]  # write + one repair, same game
    with mock.patch.object(run, "client", return_value=fake2):
        gid2 = run._docket_queue(cid, ["3"])[0]; run._docket_write(cid, gid2)
    row2 = run.rows("SELECT status,error FROM docket_games WHERE id=?", gid2)[0]
    assert row2["status"] == "failed"                                                  # Article 107 TFEU now unverifiable
