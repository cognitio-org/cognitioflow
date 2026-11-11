"""WRITER v2 wired into run.py behind CF_DOCKET_WRITER (Game Studio model-quality plan rungs 0-2).

v1 (the default) stays today's writer exactly: tests/test_docket_drafts.py is unmodified and still passes. v2 is the
M4-only writer: pinned to allow-listed M4 bases with no fallback, the Qwen3-Coder card sampling sent explicitly, the
Thinker (studio.runtime) as reviewer, and a provenance record on the draft. Fakes only: no M4, no network.
"""
import json
import unittest.mock as mock

import docketgen
import llm
import run
from studio import runtime as srt
from test_docket_drafts import _course
from test_docketgen_v2 import SRC, inter

CODER = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-DWQ"
THINKER = "mlx-community/Qwen3-30B-A3B-Thinking-2507-4bit"


def _reply(obj, model=CODER):
    r = mock.MagicMock(); r.content = [mock.MagicMock(type="text", text=json.dumps(obj))]
    r.stop_reason = "end_turn"; r.model = model
    return r


def _v2(monkeypatch, coder_replies, thinker_replies, provider="kernal", base="http://127.0.0.1:8080/v1", model=CODER):
    monkeypatch.setattr(run, "DOCKET_WRITER", "v2")
    monkeypatch.setattr(run, "MODEL", model)
    monkeypatch.setattr(llm, "PROVIDER", provider)
    monkeypatch.setattr(llm, "KERNAL_BASE", base)
    monkeypatch.setattr(llm, "LOCAL_BASE_URL", "", raising=False)
    monkeypatch.setattr(docketgen, "pick_mix", lambda salt: "A")
    seen = {"thinker": []}

    def fake_reviewer(system=None, max_tokens=None, **kw):
        replies = list(thinker_replies)

        def r(prompt):
            seen["thinker"].append({"system": system, "prompt": prompt, "max_tokens": max_tokens})
            return json.dumps(replies.pop(0))
        r.model, r.url, r.last_served = THINKER, "http://127.0.0.1:8082/v1/chat/completions", THINKER
        return r
    monkeypatch.setattr(srt, "m4_reviewer", fake_reviewer)
    fake = mock.MagicMock(); fake.messages.create.side_effect = [_reply(r) for r in coder_replies]
    return fake, seen


def _write(cid, fake):
    with mock.patch.object(run, "client", return_value=fake):
        gid = run._docket_queue(cid, ["3"])[0]
        run._docket_write(cid, gid)
    return gid, run.rows("SELECT status,error,game,review,model FROM docket_games WHERE id=?", gid)[0]


def _course_v2(client):
    cid = _course(client, "PIL v2")
    client.post(f"/api/courses/{cid}/files", files={"file": ("W3 lecture.txt", __import__("io").BytesIO(SRC.encode()), "text/plain")},
        data={"week": "3"})
    return cid


def test_v1_is_the_default():
    assert run.DOCKET_WRITER == "v1" or __import__("os").environ.get("CF_DOCKET_WRITER")


def test_v2_writes_a_produce_game_with_explicit_sampling_thinker_review_and_provenance(client, monkeypatch):
    cid = _course_v2(client)
    fake, seen = _v2(monkeypatch, [inter("A")], [{"verdict": "ok", "issues": []}])
    gid, row = _write(cid, fake)
    assert row["status"] == "draft", row["error"]
    kw = fake.messages.create.call_args_list[0].kwargs
    assert fake.messages.create.call_count == 1                        # the Coder never reviews its own game
    assert {k: kw[k] for k in run.DOCKET_SAMPLING} == {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "repetition_penalty": 1.05}
    brief = (run.Path(run.__file__).parent / "studio" / "brief.md").read_text().strip()
    assert kw["system"] == brief                                         # STUDIO_BRIEF is the system prompt
    user = kw["messages"][0]["content"]
    assert user.index("LEXICON") < user.index("SOURCES") < user.index("TASK (writer)") if "LEXICON" in user \
        else user.index("SOURCES") < user.index("TASK (writer)")
    t = seen["thinker"][0]
    assert t["system"] == brief and t["max_tokens"] == run.DOCKET_REVIEW_MAX_TOKENS and "WRONG ON PURPOSE" in t["prompt"]
    assert user.split("TASK (writer)")[0] == t["prompt"].split("TASK (reviewer)")[0]   # byte-identical shared prefix
    kinds = [str((s.get("quiz") or {}).get("kind") or "mcq") for s in row["game"]["scenes"] if s.get("quiz")]
    assert kinds == ["mcq", "slot", "spot"] and docketgen.generation_ratio(row["game"]) >= 0.4
    prov = row["review"]["provenance"]
    assert row["review"]["writer"] == "v2" and row["review"]["mix"] == "A"
    assert prov["provenance"] == "clean", prov["taint_reason"]
    assert [c["role"] for c in prov["calls"]] == ["write", "review"]
    assert prov["calls"][0] == {"role": "write", "model": CODER, "base": "http://127.0.0.1:8080/v1"}
    assert prov["calls"][1]["model"] == THINKER and prov["prompt_version"] == docketgen.PROMPT_VERSION
    assert prov["brief_hash"] and prov["sampling"] == run.DOCKET_SAMPLING


def test_v2_refuses_off_the_m4_and_fails_closed(client, monkeypatch):
    cid = _course_v2(client)
    for provider, base, model in (("anthropic", "http://127.0.0.1:8080/v1", CODER),
                                  ("kernal", "https://router.kernal.one/v1", CODER),
                                  ("kernal", "http://127.0.0.1:8080/v1", "claude-sonnet-5")):
        fake, _ = _v2(monkeypatch, [inter("A")], [{"verdict": "ok", "issues": []}], provider, base, model)
        gid, row = _write(cid, fake)
        assert row["status"] == "failed" and fake.messages.create.call_count == 0, (provider, base, model)


def test_v2_refuses_a_rag_base_off_the_m4(client, monkeypatch):
    cid = _course_v2(client)
    fake, _ = _v2(monkeypatch, [inter("A")], [{"verdict": "ok", "issues": []}])
    monkeypatch.setattr(run, "DOCKET_RAG_URL", "http://100.64.0.3:8123,https://rag-mirror.example.com")
    with mock.patch("urllib.request.urlopen") as net:
        gid, row = _write(cid, fake)
    assert row["status"] == "failed" and fake.messages.create.call_count == 0 and not net.called


def test_v2_unknown_sentence_id_is_repaired_then_fails(client, monkeypatch):
    cid = _course_v2(client)
    bad = inter("A"); bad["checks"][0]["sentence"] = "S1.99"
    fake, _ = _v2(monkeypatch, [bad, bad], [])
    gid, row = _write(cid, fake)
    assert row["status"] == "failed" and "checks" in row["error"]
    assert "S1.99 is not a sentence shown" in fake.messages.create.call_args_list[1].kwargs["messages"][0]["content"]


def test_v2_a_typed_quote_is_replaced_by_the_cited_sentence(client, monkeypatch):
    cid = _course_v2(client)
    g = inter("A"); g["checks"][0]["quote"] = "reservations are void under jus cogens norms always"
    fake, _ = _v2(monkeypatch, [g], [{"verdict": "ok", "issues": []}])
    gid, row = _write(cid, fake)
    assert row["status"] == "draft", row["error"]
    user = fake.messages.create.call_args_list[0].kwargs["messages"][0]["content"]
    assert "[S1.1] A reservation is a unilateral statement" in user
    assert row["game"]["checks"][0]["quote"] == "A reservation is a unilateral statement made by a State when signing a treaty."


def test_v2_draft_runs_without_db_rows_for_best_of_n(client, monkeypatch):
    cid = _course_v2(client)
    fake, _ = _v2(monkeypatch, [inter("A")], [])
    n0 = len(run.rows("SELECT id FROM docket_games WHERE course_id=?", cid))
    course = run.rows("SELECT * FROM courses WHERE id=?", cid)[0]
    with mock.patch.object(run, "client", return_value=fake):
        dctx = run._docket_context(cid, course, "3")
        out = run._docket_draft_v2(dctx, "salt", review=False)
    assert out["issues"] == [] and [c["role"] for c in out["calls"]] == ["write"] and out["grounding"] == 1.0
    assert out["provenance"]["split"] in ("dev", "heldout", "unassigned")
    assert len(run.rows("SELECT id FROM docket_games WHERE course_id=?", cid)) == n0     # no rows written


def test_kernal_body_forwards_sampling_only_when_given():
    base = llm._kernal_body("m", None, [{"role": "user", "content": "x"}], 10, None, False)
    assert set(base) == {"model", "messages", "max_tokens", "stream"}
    b = llm._kernal_body("m", None, [{"role": "user", "content": "x"}], 10, 0.7, False,
                         {"top_p": 0.8, "top_k": 20.0, "repetition_penalty": 1.05, "stop_sequences": ["x"]})
    assert b["temperature"] == 0.7 and b["top_p"] == 0.8 and b["top_k"] == 20 and isinstance(b["top_k"], int)
    assert b["repetition_penalty"] == 1.05 and "stop_sequences" not in b


def test_kernal_create_sends_the_sampling_fields():
    sent = {}

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"model": CODER, "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}).encode()

    def fake_open(req, timeout=None):
        sent.update(json.loads(req.data)); return R()
    with mock.patch("urllib.request.urlopen", fake_open):
        llm._KernalMessages("http://127.0.0.1:8080/v1", "k").create(model=CODER, max_tokens=5, messages=[{"role": "user", "content": "x"}],
                                                                   temperature=0.7, top_p=0.8, top_k=20, repetition_penalty=1.05)
    assert sent["top_k"] == 20 and sent["top_p"] == 0.8 and sent["repetition_penalty"] == 1.05 and sent["temperature"] == 0.7
