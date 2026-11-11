"""S9: the Game Studio quality gates wired into the docket writer behind CF_STUDIO_GATES (off | shadow | enforce).

off (the default) must be today's writer exactly. shadow stores the gate card and never blocks. enforce turns any
draft the gates do not literally pass into `failed`. The real adapter is never used here: a fake `studio` package is
put in sys.modules, so CI needs no playwright, no M4 and no gate sys.path. The static guards prove `import run`
(what Cloud Run does) never loads studio/, which is not in the image.
"""
import ast
import io
import json
import os
import pathlib
import subprocess
import sys
import time
import types

import pytest

import docketgen
import run
from test_docket_drafts import _course, _write
from test_docketgen import game

ROOT = pathlib.Path(__file__).resolve().parent.parent
OK = {"verdict": "ok", "issues": []}
TODAY_REVIEW_KEYS = {"issues", "unverified", "revised"}
GATE_NAMES = {"harness", "a11y", "playability", "review_card", "terminology_lock", "doctrinal_review",
              "retrieval_density", "self_contained", "aesthetic_judge"}


# ---------------------------------------------------------------- a fake adapter


def _install(monkeypatch, *, card=None, raises=None):
    """Put a fake `studio.docket_adapter` where `from studio import docket_adapter` finds it, both as the package
    attribute and in sys.modules: the real one may already be imported by tests/test_studio_adapter.py."""
    calls = []
    mod = types.ModuleType("studio.docket_adapter")

    def gate_docket(final, keyed, texts, course, *, issues=None, unverified=None, mode="shadow", heartbeat=None, runtime=None):
        calls.append({"final": final, "keyed": keyed, "texts": texts, "course": course, "issues": issues,
                      "unverified": unverified, "mode": mode, "heartbeat": heartbeat})
        if raises is not None:
            raise raises
        return card

    def block_message(c):
        names = c.get("blocking_failures") if isinstance(c, dict) else None
        return f"{docketgen.GATE_BLOCKED}: " + (", ".join(names) if isinstance(names, list) and names else "no enforced gate passed")

    mod.gate_docket, mod.block_message = gate_docket, block_message
    pkg = types.ModuleType("studio"); pkg.__path__ = []; pkg.docket_adapter = mod
    monkeypatch.setitem(sys.modules, "studio", pkg)
    monkeypatch.setitem(sys.modules, "studio.docket_adapter", mod)
    return calls


def _card(passed, mode="shadow", blocking=()):
    return {"mode": mode, "overall_pass": passed, "gates": [{"name": "doctrine", "passed": passed is True}],
            "blocking_failures": list(blocking), "infra_error": False}


def _row(gid):
    r = run.rows("SELECT status,error,review FROM docket_games WHERE id=?", gid)[0]
    rev = r["review"] if isinstance(r["review"], dict) else json.loads(r["review"] or "{}")
    return r["status"], r["error"], rev


# ---------------------------------------------------------------- off: today, byte for byte


def test_off_is_todays_writer_and_never_touches_studio(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "off")
    calls = _install(monkeypatch, raises=AssertionError("the adapter must not run when the gates are off"))
    cid = _course(client, "Off Law")
    gid, fake = _write(cid, [game(), OK])
    status, error, review = _row(gid)
    assert fake.messages.create.call_count == 2
    assert calls == []
    assert status == "draft" and error == ""
    assert set(review) == TODAY_REVIEW_KEYS and "gates" not in review


def test_unset_env_means_off():
    out = _fresh_import({})
    assert out["gates"] == "off" and out["cap"] == 0


# ---------------------------------------------------------------- shadow: card stored, never blocks


def test_shadow_stores_the_card_and_keeps_the_draft(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "shadow")
    calls = _install(monkeypatch, card=_card(False, blocking=["doctrine"]))
    cid = _course(client, "Shadow Law")
    gid, _ = _write(cid, [game(), OK])
    status, error, review = _row(gid)
    assert status == "draft" and error == ""                          # a failing card blocks nothing in shadow
    assert review["gates"]["mode"] == "shadow" and review["gates"]["overall_pass"] is False
    assert TODAY_REVIEW_KEYS <= set(review)
    (c,) = calls
    assert c["mode"] == "shadow" and c["issues"] == [] and c["unverified"] == []
    assert c["final"]["id"] == gid and "S1" in c["keyed"] and c["course"]["id"] == cid
    assert any("Registration is constitutive." in t for t in c["texts"])
    with run.db() as d:                                                # an old stamp, so a no-op heartbeat cannot pass
        d.execute("UPDATE docket_games SET updated=? WHERE id=?", (1.0, gid))
    c["heartbeat"]()                                                   # the reaper sees a long gate run as alive
    assert run.rows("SELECT updated FROM docket_games WHERE id=?", gid)[0]["updated"] > 1.0


def test_shadow_passes_the_unverified_citations_to_the_adapter(client, monkeypatch):
    """A citation no source has survives the one repair round: the adapter must get it, as the review does."""
    monkeypatch.setattr(run, "STUDIO_GATES", "shadow")
    calls = _install(monkeypatch, card=_card(True))
    g = game(); g["logline"] = "As held in Case C-999/99."              # in no source; validate() is still clean
    cid = _course(client, "Shadow Uncited Law")
    gid, fake = _write(cid, [g, g, OK])                                # write, repair (kept), reviewer
    assert fake.messages.create.call_count == 3
    (c,) = calls
    assert c["unverified"] == ["C-999/99"]
    assert _row(gid)[2]["unverified"] == ["C-999/99"]


def test_shadow_adapter_raising_still_drafts_with_the_error(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "shadow")
    _install(monkeypatch, raises=RuntimeError("M4 unreachable"))
    cid = _course(client, "Shadow Boom Law")
    gid, _ = _write(cid, [game(), OK])
    status, error, review = _row(gid)
    assert status == "draft" and error == ""
    assert review["gates"]["mode"] == "shadow" and "M4 unreachable" in review["gates"]["error"]


def test_shadow_adapter_import_failing_still_drafts(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "shadow")
    monkeypatch.setitem(sys.modules, "studio", None)                   # `from studio import ...` -> ImportError
    cid = _course(client, "Shadow Missing Law")
    gid, _ = _write(cid, [game(), OK])
    status, _, review = _row(gid)
    assert status == "draft" and "Error" in review["gates"]["error"]


@pytest.mark.parametrize("bad", [{"overall_pass": False, "x": object()}, {"overall_pass": False, "x": float("nan")}])
def test_shadow_card_that_cannot_be_stored_still_drafts(client, monkeypatch, bad):
    """_set_docket serialises review outside the gate try: an unstorable card must not fail a shadow row."""
    monkeypatch.setattr(run, "STUDIO_GATES", "shadow")
    _install(monkeypatch, card=bad)
    cid = _course(client, "Shadow Odd Law")
    gid, _ = _write(cid, [game(), OK])
    status, _, review = _row(gid)
    assert status == "draft" and review["gates"]["error"]


# ---------------------------------------------------------------- enforce: only a literal True is a draft


def test_enforce_passing_card_is_a_draft(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "enforce")
    calls = _install(monkeypatch, card=_card(True, mode="enforce"))
    cid = _course(client, "Enforce Pass Law")
    gid, _ = _write(cid, [game(), OK])
    status, error, review = _row(gid)
    assert status == "draft" and error == "" and review["gates"]["overall_pass"] is True
    assert calls[0]["mode"] == "enforce"


def test_enforce_failing_card_blocks_the_draft(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "enforce")
    _install(monkeypatch, card=_card(False, mode="enforce", blocking=["doctrine", "retrieval"]))
    cid = _course(client, "Enforce Block Law")
    gid, _ = _write(cid, [game(), OK])
    status, error, review = _row(gid)
    assert status == "failed" and error.startswith("Blocked by the quality gates")
    assert "doctrine" in error and review["gates"]["blocking_failures"] == ["doctrine", "retrieval"]
    assert client.get(f"/api/courses/{cid}/docket/{gid}").status_code == 404           # never served
    r = client.post(f"/api/courses/{cid}/docket-drafts/{gid}/approve")
    assert r.status_code == 409                                                         # the existing status machine


def test_enforce_adapter_raising_fails_the_row(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "enforce")
    _install(monkeypatch, raises=RuntimeError("doctrine reviewer timed out"))
    cid = _course(client, "Enforce Boom Law")
    gid, _ = _write(cid, [game(), OK])
    status, error, _ = _row(gid)
    assert status == "failed" and error.startswith(docketgen.GATE_UNAVAILABLE)          # S8 counts it as infra
    assert "doctrine reviewer timed out" in error


def test_enforce_adapter_missing_fails_the_row(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "enforce")
    monkeypatch.setitem(sys.modules, "studio", None)
    cid = _course(client, "Enforce Missing Law")
    gid, _ = _write(cid, [game(), OK])
    status, error, _ = _row(gid)
    assert status == "failed" and error.startswith(docketgen.GATE_UNAVAILABLE)


@pytest.mark.parametrize("passed", ["true", 1, None, "missing"])
def test_enforce_trusts_nothing_but_literal_true(client, monkeypatch, passed):
    monkeypatch.setattr(run, "STUDIO_GATES", "enforce")
    card = _card(True, mode="enforce")
    if passed == "missing":
        del card["overall_pass"]
    else:
        card["overall_pass"] = passed
    _install(monkeypatch, card=card)
    cid = _course(client, f"Enforce Literal {passed} Law")
    gid, _ = _write(cid, [game(), OK])
    status, error, _ = _row(gid)
    assert status == "failed" and error.startswith("Blocked by the quality gates")


@pytest.mark.parametrize("card", [None, [], "x"], ids=["none", "list", "str"])
def test_enforce_non_dict_card_fails_the_row(client, monkeypatch, card):
    """Blocked on purpose, with a prefix S8 counts: an AttributeError would also fail the row, but its error has
    neither prefix, so the retry quota never stops that week."""
    monkeypatch.setattr(run, "STUDIO_GATES", "enforce")
    _install(monkeypatch, card=card)
    cid = _course(client, f"Enforce Odd {type(card).__name__} Law")
    gid, _ = _write(cid, [game(), OK])
    status, error, _ = _row(gid)
    assert status == "failed" and error.startswith(docketgen.GATE_BLOCKED)


def test_enforce_block_error_is_capped_at_300(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "enforce")
    _install(monkeypatch, card=_card(False, mode="enforce", blocking=[f"gate_{i}_" + "x" * 40 for i in range(50)]))
    cid = _course(client, "Enforce Long Law")
    gid, _ = _write(cid, [game(), OK])
    status, error, _ = _row(gid)
    assert status == "failed" and error.startswith(docketgen.GATE_BLOCKED) and len(error) <= 300


def test_approve_on_a_gate_failed_row_is_409(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "enforce")
    _install(monkeypatch, card=_card("true", mode="enforce"))
    cid = _course(client, "Approve Law")
    gid, _ = _write(cid, [game(), OK])
    r = client.post(f"/api/courses/{cid}/docket-drafts/{gid}/approve")
    assert r.status_code == 409 and "failed" in r.json()["detail"]
    assert _row(gid)[0] == "failed"


# ---------------------------------------------------------------- _docket_due: retry quota and weekly cap (R2)


def _failed_rows(cid, n, error):
    for gid in run._docket_queue(cid, ["3"] * n):
        run._set_docket(gid, status="failed", error=error)
    with run.db() as d:                                                # age them past the backoff, keep them newer than the file
        d.execute("UPDATE docket_games SET updated=? WHERE course_id=?", (1.0, cid))


def test_off_keeps_requeueing_gate_blocked_rows_as_today(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "off")
    cid = _course(client, "Due Off Law")
    _failed_rows(cid, 3, f"{docketgen.GATE_BLOCKED}: doctrine")
    assert run._docket_due(cid) == ["3"]


def test_gates_on_stop_after_three_blocked_attempts(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "shadow")
    cid = _course(client, "Due Shadow Law")
    _failed_rows(cid, 3, f"{docketgen.GATE_BLOCKED}: doctrine")
    assert run._docket_due(cid) == []
    client.post(f"/api/courses/{cid}/files", files={"file": ("W3 WG.txt", io.BytesIO(b"New WG answers"), "text/plain")},
                data={"week": "3"})
    assert run._docket_due(cid) == ["3"]                               # new material resets the quota


def test_gates_on_infra_failures_have_their_own_cap(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "enforce")
    cid = _course(client, "Due Infra Law")
    _failed_rows(cid, 3, f"{docketgen.GATE_UNAVAILABLE}: doctrine: timeout")
    assert run._docket_due(cid) == ["3"]                               # 3 outages do not spend the content quota
    _failed_rows(cid, 3, f"{docketgen.GATE_UNAVAILABLE}: doctrine: timeout")
    assert run._docket_due(cid) == []                                  # 6 do


def test_weekly_cap_counts_drafts_across_his_courses(client, monkeypatch):
    """The cap is its own knob: it applies with CF_STUDIO_GATES off too (only cap 0 is today's behaviour)."""
    monkeypatch.setattr(run, "STUDIO_GATES", "off")
    other = _course(client, "Cap Other Law")
    gid, _ = _write(other, [game(), OK])                               # one draft this week, another course
    cid = _course(client, "Cap Law")
    monkeypatch.setattr(run, "STUDIO_WEEKLY_CAP", 1)
    assert run._docket_due(cid) == []
    monkeypatch.setattr(run, "STUDIO_WEEKLY_CAP", 2)
    assert run._docket_due(cid) == ["3"]
    monkeypatch.setattr(run, "STUDIO_WEEKLY_CAP", 0)                   # 0 = no cap, today's behaviour
    assert run._docket_due(cid) == ["3"]
    with run.db() as d:                                                # the same draft, 8 days old: outside the window
        d.execute("UPDATE docket_games SET created=? WHERE id=?", (time.time() - 8 * 86400, gid))
    monkeypatch.setattr(run, "STUDIO_WEEKLY_CAP", 1)
    assert run._docket_due(cid) == ["3"]                               # last week's drafts do not spend this week's cap


# ---------------------------------------------------------------- pins: the gate run holds the row in 'writing' (S9 review)
# These document current behaviour, not a fix: they pass before and after. The final write was already unconditional
# before S9; the gates only lengthen the window. Whether shadow should draft first is Matej's design call.


def test_pin_shadow_row_is_writing_while_the_gates_run(client, monkeypatch):
    monkeypatch.setattr(run, "STUDIO_GATES", "shadow")
    seen = {}
    _install(monkeypatch, card=_card(True))
    mod = sys.modules["studio.docket_adapter"]
    orig = mod.gate_docket

    def watch(final, *a, **k):
        seen["status"] = run.rows("SELECT status FROM docket_games WHERE id=?", final["id"])[0]["status"]
        return orig(final, *a, **k)

    monkeypatch.setattr(mod, "gate_docket", watch)
    cid = _course(client, "Pin Shadow Law")
    gid, _ = _write(cid, [game(), OK])
    assert seen["status"] == "writing" and _row(gid)[0] == "draft"


def test_pin_a_row_reaped_mid_gates_is_still_written(client, monkeypatch):
    """No heartbeat for AUTO_STALE_S during the gates -> the reaper fails the row -> the writer then drafts it."""
    monkeypatch.setattr(run, "STUDIO_GATES", "shadow")
    _install(monkeypatch, card=_card(True))
    mod = sys.modules["studio.docket_adapter"]
    orig = mod.gate_docket
    seen = {}

    def reaped(final, keyed, texts, course, **k):
        with run.db() as d:
            d.execute("UPDATE docket_games SET updated=? WHERE id=?", (time.time() - 2 * docketgen.AUTO_STALE_S, final["id"]))
        run._docket_collect_stale(course["id"])
        seen["after_reaper"] = run.rows("SELECT status FROM docket_games WHERE id=?", final["id"])[0]["status"]
        return orig(final, keyed, texts, course, **k)

    monkeypatch.setattr(mod, "gate_docket", reaped)
    cid = _course(client, "Pin Reaper Law")
    gid, _ = _write(cid, [game(), OK])
    assert seen["after_reaper"] == "failed" and _row(gid)[0] == "draft"


# ---------------------------------------------------------------- static guards: Cloud Run never loads studio/


def test_run_does_not_import_studio_at_module_level():
    tree = ast.parse((ROOT / "run.py").read_text(encoding="utf-8"))
    banned = {"studio", *GATE_NAMES}
    bad = []

    def scan(node):
        """Everything that runs at import: module body, top-level if/try/with, class bodies. Not function bodies."""
        for sub in ast.iter_child_nodes(node):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue                                               # runs only when called
            if isinstance(sub, ast.Import) and any(a.name.split(".")[0] in banned for a in sub.names):
                bad.append(sub.lineno)
            if isinstance(sub, ast.ImportFrom) and (sub.module or "").split(".")[0] in banned:
                bad.append(sub.lineno)
            scan(sub)

    scan(tree)
    assert bad == [], f"run.py imports studio/gate modules at module level on lines {bad}"
    src = (ROOT / "run.py").read_text(encoding="utf-8")
    assert src.count("from studio import") == 1                        # the one lazy import, in _docket_write


def _fresh_import(extra_env: dict) -> dict:
    """`import run` in a new interpreter: an in-process check is order-dependent (test_studio_adapter imports studio)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("CF_STUDIO_")}
    env.update(extra_env)
    code = ("import json, sys, run; names = %r; "
            "print(json.dumps({'mods': sorted(m for m in sys.modules if m == 'studio' or m.startswith('studio.') or m in names), "
            "'gates': run.STUDIO_GATES, 'cap': run.STUDIO_WEEKLY_CAP}))") % (sorted(GATE_NAMES),)
    p = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-2000:]
    return json.loads(p.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("flag", [None, "shadow", "enforce"])
def test_import_run_loads_no_studio_module(flag):
    out = _fresh_import({} if flag is None else {"CF_STUDIO_GATES": flag})
    assert out["mods"] == []                                           # even with the flag on: the import is lazy
    assert out["gates"] == (flag or "off")


def test_unknown_flag_value_fails_closed_to_enforce():
    assert _fresh_import({"CF_STUDIO_GATES": "on"})["gates"] == "enforce"
    assert _fresh_import({"CF_STUDIO_GATES": " Shadow "})["gates"] == "shadow"
    assert _fresh_import({"CF_STUDIO_GATES": ""})["gates"] == "off"
    assert _fresh_import({"CF_STUDIO_WEEKLY_CAP": "three"})["cap"] == 0
    assert _fresh_import({"CF_STUDIO_WEEKLY_CAP": "3"})["cap"] == 3


@pytest.mark.parametrize("raw", ["\u00b2", "\u0663", "-1", "1.5"])
def test_weekly_cap_junk_is_no_cap_not_a_crash(raw):
    """str.isdigit() is True for '\u00b2' and Arabic-Indic digits, which int() rejects: that would crash `import run`."""
    assert _fresh_import({"CF_STUDIO_WEEKLY_CAP": raw})["cap"] == 0


# The image's COPY list at origin/main 1c433b7. studio/ is deliberately absent: Cloud Run never runs the writer.
DOCKER_COPIES = [
    "COPY requirements.txt .",
    "COPY run.py llm.py auth.py storage.py migrate.py embed.py retrieval.py schedule.py oral.py essay.py casetrainer.py "
    "tts.py course_brief.py blueprint.py readiness.py card_tagging.py concepts.py citecheck.py countdown.py weaktopics.py "
    "pack.py mockexam.py docketgen.py relevance.py gateway.py ./",
    "COPY transcribe/ transcribe/",
    "COPY scripts/check_env.py scripts/start.sh scripts/",
    "COPY static/ static/",
    "COPY play/ play/",
    "COPY prompts/ prompts/",
    "COPY migrations/ migrations/",
]


def test_dockerfile_does_not_need_studio():
    lines = [ln.strip() for ln in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()]
    copies = [ln for ln in lines if ln.split(" ", 1)[0] in ("COPY", "ADD")]
    assert not any("studio" in ln for ln in copies)
    assert copies == DOCKER_COPIES
