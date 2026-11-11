"""S9 follow-up: WRITER v2 drafts (#207, CF_DOCKET_WRITER=v2) go through the same S9 gate card as v1 drafts.

Both writers call run._studio_gate before their final _set_docket. off (the default) must leave both writers'
final write exactly as before S9: no adapter call, no `gates` key, same fields. shadow stores the card and never
blocks; enforce turns a draft the gates do not literally pass into `failed`. v2 imports the real studio package
(runtime/context/grounding), so here the real `studio.docket_adapter.gate_docket` is replaced by a spy, and the real
block_message is used. Fakes only: no M4, no network, no Chromium.
"""
import json

import pytest
from studio import docket_adapter

import docketgen
import run
from test_docket_drafts import _course, _write as _write_v1
from test_docket_writer_v2 import _course_v2, _v2, _write as _write_v2
from test_docketgen import game
from test_docketgen_v2 import SRC, inter

OK = {"verdict": "ok", "issues": []}
V1_REVIEW_KEYS = {"issues", "unverified", "revised"}
V2_REVIEW_KEYS = {"issues", "unverified", "revised", "writer", "mix", "provenance"}       # exactly #207's set
FINAL_WRITE_KEYS = {"v1": ["status", "title", "game", "model", "error", "review", "files"],   # origin/main's field order
                    "v2": ["status", "title", "game", "model", "error", "files", "review"]}


def _spy(monkeypatch, *, card=None, raises=None):
    calls = []

    def gate_docket(final, keyed, texts, course, *, issues=None, unverified=None, mode="shadow", heartbeat=None, runtime=None):
        calls.append({"final": final, "keyed": keyed, "texts": texts, "course": course, "issues": issues,
                      "unverified": unverified, "mode": mode, "heartbeat": heartbeat})
        if raises is not None:
            raise raises
        return card
    monkeypatch.setattr(docket_adapter, "gate_docket", gate_docket)
    return calls


def _final_writes(monkeypatch):
    """Every _set_docket call that sets a status: the writer's last write is the row's outcome."""
    seen, orig = [], run._set_docket

    def rec(gid, **fields):
        if "status" in fields:
            seen.append(list(fields))
        return orig(gid, **fields)
    monkeypatch.setattr(run, "_set_docket", rec)
    return seen


def _card(passed, mode="shadow", blocking=()):
    return {"mode": mode, "overall_pass": passed, "gates": [{"name": "doctrine", "passed": passed is True}],
            "blocking_failures": list(blocking), "infra_error": False}


def _review(row):
    r = row["review"]
    return r if isinstance(r, dict) else json.loads(r or "{}")


def _run_v2(client, monkeypatch):
    cid = _course_v2(client)
    fake, _ = _v2(monkeypatch, [inter("A")], [OK])
    gid, row = _write_v2(cid, fake)
    return cid, gid, row


# ---------------------------------------------------------------- off: both writers' final write unchanged


@pytest.mark.parametrize("writer", ["v1", "v2"])
def test_off_never_calls_the_gates_and_writes_as_before(client, monkeypatch, writer):
    monkeypatch.setattr(run, "STUDIO_GATES", "off")
    calls = _spy(monkeypatch, raises=AssertionError("the gates must not run when CF_STUDIO_GATES is off"))
    writes = _final_writes(monkeypatch)
    if writer == "v1":
        cid = _course(client, "Off v1 Law")
        gid, _ = _write_v1(cid, [game(), OK])
        row = run.rows("SELECT status,error,review FROM docket_games WHERE id=?", gid)[0]
        keys = V1_REVIEW_KEYS
    else:
        _, gid, row = _run_v2(client, monkeypatch)
        keys = V2_REVIEW_KEYS
    assert calls == []
    assert row["status"] == "draft" and row["error"] == ""
    assert set(_review(row)) == keys                                   # no `gates` key, nothing else added
    assert writes[-1] == FINAL_WRITE_KEYS[writer]                      # same fields, same order as before S9


def test_off_v2_imports_no_adapter_beyond_what_207_already_loads(client, monkeypatch):
    """off returns before `from studio import docket_adapter`: a broken adapter import cannot touch a v2 draft."""
    monkeypatch.setattr(run, "STUDIO_GATES", "off")
    monkeypatch.delattr(docket_adapter, "gate_docket")                # any call would raise AttributeError
    _, _, row = _run_v2(client, monkeypatch)
    assert row["status"] == "draft" and row["error"] == "" and "gates" not in _review(row)


# ---------------------------------------------------------------- shadow: card stored, never blocks


def test_v2_shadow_stores_the_card_and_keeps_the_draft(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "shadow")
    card = _card(False, blocking=["doctrine"])
    calls = _spy(monkeypatch, card=card)
    cid, gid, row = _run_v2(client, monkeypatch)
    review = _review(row)
    assert row["status"] == "draft" and row["error"] == ""             # a failing card blocks nothing in shadow
    assert review["gates"] == card
    assert set(review) == V2_REVIEW_KEYS | {"gates"} and review["writer"] == "v2"
    (c,) = calls
    assert c["mode"] == "shadow" and c["issues"] == review["issues"] and c["unverified"] == review["unverified"]
    assert c["final"]["id"] == gid and c["final"] == row["game"] and c["course"]["id"] == cid
    assert "S1" in c["keyed"] and any(SRC in t for t in c["texts"])
    with run.db() as d:                                                # an old stamp, so a no-op heartbeat cannot pass
        d.execute("UPDATE docket_games SET updated=? WHERE id=?", (1.0, gid))
    c["heartbeat"]()
    assert run.rows("SELECT updated FROM docket_games WHERE id=?", gid)[0]["updated"] > 1.0


def test_v2_shadow_adapter_raising_still_drafts_with_the_error(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "shadow")
    _spy(monkeypatch, raises=RuntimeError("M4 unreachable"))
    _, _, row = _run_v2(client, monkeypatch)
    review = _review(row)
    assert row["status"] == "draft" and row["error"] == ""
    assert review["gates"]["mode"] == "shadow" and "M4 unreachable" in review["gates"]["error"]


# ---------------------------------------------------------------- enforce: a failing v2 draft is blocked


def test_v2_enforce_failing_card_blocks_the_draft(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "enforce")
    card = _card(False, mode="enforce", blocking=["doctrine", "playability"])
    calls = _spy(monkeypatch, card=card)
    _, gid, row = _run_v2(client, monkeypatch)
    assert calls and calls[0]["mode"] == "enforce"
    assert row["status"] == "failed"
    assert row["error"].startswith(docketgen.GATE_BLOCKED) and "doctrine" in row["error"]   # S8's content cap counts it
    assert _review(row)["gates"] == card and _review(row)["writer"] == "v2"
    assert row["game"]["id"] == gid                                    # the blocked game is kept for him to inspect
    r = run.rows("SELECT status FROM docket_games WHERE id=?", gid)[0]
    assert r["status"] == "failed"


@pytest.mark.parametrize("passed", ["true", 1, None])
def test_v2_enforce_trusts_nothing_but_literal_true(client, monkeypatch, passed):
    monkeypatch.setattr(run, "STUDIO_GATES", "enforce")
    _spy(monkeypatch, card=_card(passed, mode="enforce"))
    _, _, row = _run_v2(client, monkeypatch)
    assert row["status"] == "failed" and row["error"].startswith(docketgen.GATE_BLOCKED)


def test_v2_enforce_passing_card_is_a_draft(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "enforce")
    _spy(monkeypatch, card=_card(True, mode="enforce"))
    _, _, row = _run_v2(client, monkeypatch)
    assert row["status"] == "draft" and row["error"] == "" and _review(row)["gates"]["overall_pass"] is True


def test_v2_enforce_adapter_raising_fails_the_row_on_the_infra_cap(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "enforce")
    _spy(monkeypatch, raises=RuntimeError("M4 unreachable"))
    _, _, row = _run_v2(client, monkeypatch)
    assert row["status"] == "failed" and row["error"].startswith(docketgen.GATE_UNAVAILABLE)
    assert "M4 unreachable" in row["error"]


# ---------------------------------------------------------------- v2's own findings reach the gate card

HIGH = {"verdict": "revise", "issues": [{"where": "round 1", "problem": "states the wrong test", "severity": "high"}]}


def test_v2_reviewer_issues_and_unverified_citations_reach_the_gate(client, monkeypatch):
    """The other v2 tests use a clean review (issues == unverified == []), so a mutant passing [] for either to
    the adapter survived them. Here the Thinker's high-severity issue survives the revision and one citation stays
    unverified: both must reach gate_docket exactly as stored, or enforce's reviewer_high/citations gates pass a
    draft v2's own checks flagged."""
    monkeypatch.setattr(run, "STUDIO_GATES", "enforce")
    monkeypatch.setattr(run.citecheck, "unverified", lambda text, texts: [{"raw": "[Z9]"}])
    calls = _spy(monkeypatch, card=_card(False, mode="enforce", blocking=["reviewer_high", "citations"]))
    cid = _course_v2(client)
    fake, _ = _v2(monkeypatch, [inter("A"), inter("A"), inter("A")], [HIGH, HIGH])   # write, repair, revise
    gid, row = _write_v2(cid, fake)
    review = _review(row)
    (c,) = calls
    assert review["issues"] and review["issues"][0]["severity"] == "high"
    assert review["unverified"] == ["[Z9]"]
    assert c["issues"] == review["issues"] and c["unverified"] == review["unverified"]
    assert row["status"] == "failed" and row["error"].startswith(docketgen.GATE_BLOCKED)
