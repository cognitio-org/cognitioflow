"""scripts/pr_worthiness.py: rules, verdicts and the comment. No network; fake secrets are assembled at runtime."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import pr_worthiness as pw  # noqa: E402


def diff_for(path: str, added=(), removed=()) -> str:
    body = "".join(f"-{l}\n" for l in removed) + "".join(f"+{l}\n" for l in added)
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n{body}"


def f(path, additions=1, deletions=0):
    return {"path": path, "additions": additions, "deletions": deletions}


FAKE_ANTHROPIC = "sk-" + "ant-" + "api03-" + "A1b2" * 12
FAKE_NEON = "npg" + "_" + "Q7w8E9r0T1y2"


def test_css_only_change_scores_full_marks():
    assert pw.rules([f("static/index.html", 20, 18)], diff_for("static/index.html", ["  .toast{opacity:1}"])) == (100, [], [])


@pytest.mark.parametrize("line", [f'ANTHROPIC_API_KEY="{FAKE_ANTHROPIC}"', f"DATABASE_URL=postgresql://neondb_owner:{FAKE_NEON}@ep-x.neon.tech/db",
                                  "-----BEGIN " + "PRIVATE KEY-----"])
def test_leaked_credentials_block(line):
    score, _, blocking = pw.rules([f("run.py")], diff_for("run.py", [line]))
    assert blocking and score <= 20


@pytest.mark.parametrize("line", ['os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key")',
                                  "postgresql://cf:cf@localhost:5432/cognitioflow",
                                  "postgresql://u:hunter2secret@localhost:1/none",
                                  "postgresql://user:${PASSWORD}@ep-x.neon.tech/db"])
def test_test_fixtures_and_placeholders_are_not_secrets(line):
    assert pw.rules([f("tests/test_x.py")], diff_for("tests/test_x.py", [line]))[2] == []


def test_committed_env_and_data_files_block_but_the_example_does_not():
    assert pw.rules([f(".env")], "")[2]
    assert pw.rules([f("data/cognitioflow.db")], "")[2]
    assert pw.rules([f(".env.local.example")], "")[2] == []


def test_sensitive_areas_lower_the_score():
    score, findings, blocking = pw.rules([f("auth.py"), f("infra/backup.sh")], "")
    assert score == 100 - 12 - 8 and not blocking
    assert [label for _, label in findings] == ["sign-in and sessions", "cloud infrastructure"]


def test_risky_patterns_count_only_when_added():
    wf = ".github/workflows/deploy.yml"
    removed = pw.rules([f(wf)], diff_for(wf, removed=["            --allow-unauthenticated \\"]))
    added = pw.rules([f(wf)], diff_for(wf, added=["            --allow-unauthenticated \\"]))
    # deploy.yml now also trips the CHECKER row (-20) on top of the workflow row (-8),
    # so both drop by 20; the 10-point gap is the point: the risky line counts only when added.
    assert removed[0] == 100 - 20 - 8 and added[0] == 100 - 20 - 8 - 10


def test_verdicts():
    assert pw.decide("success", 90, [], []).verdict == "approve"
    assert pw.decide("failure", 100, [], []).verdict == "hold"
    assert pw.decide("cancelled", 100, [], []).explanation == "Hold: the tests did not run (cancelled)."
    assert pw.decide("success", 74, [(26, "x")], []).verdict == "hold"
    assert pw.decide("success", 75, [(25, "x")], []).verdict == "approve"
    held = pw.decide("success", 95, [], [], {"verdict": "hold", "security": 60, "explanation": "Drops the auth check on /api."})
    assert (held.verdict, held.security, held.explanation) == ("hold", 60, "Drops the auth check on /api.")
    assert pw.decide("success", 20, [], ["it adds .env, which must never be committed"]).explanation.startswith("Hold: it adds .env")


def test_model_reply_parsing():
    assert pw.parse_model('Sure.\n{"verdict": "APPROVE", "security": 140, "explanation": "CSS only."}') == \
        {"verdict": "approve", "security": 100, "explanation": "CSS only."}
    with pytest.raises(Exception):
        pw.parse_model("no json here")


def test_comment_is_short_and_marked():
    a = pw.decide("success", 84, [(8, "the deploy workflow"), (8, "cloud infrastructure")], [])
    body = pw.render(a, "4b9d6e0c0ffee", [f(".github/workflows/deploy.yml", 22), f("infra/backup.sh", 140)])
    assert body.startswith(pw.MARKER) and "✅ **Approve for deployment** · security **84%**" in body
    assert "4b9d6e0 · tests: success · 2 files, +162 −0" in body and len(body.splitlines()) == 4


def test_long_model_explanations_are_trimmed_at_a_word():
    long = "Adds backup and restore with least-privilege IAM, no-overwrite writes and restore safeguards, " * 3
    out = pw.parse_model('{"verdict": "approve", "security": 80, "explanation": "%s"}' % long)["explanation"]
    assert len(out) <= 181 and out.endswith("…") and not out[:-1].endswith(" ")


def test_changes_to_the_checker_are_always_held_for_a_person():
    score, findings, blocking = pw.rules([f("scripts/pr_worthiness.py")], "")
    a = pw.decide("success", score, findings, blocking)
    assert a.verdict == "hold" and "a person has to review it" in a.explanation


class FakeGh:
    def __init__(self, reviews):
        self.reviews, self.calls = reviews, []

    def __call__(self, *args):
        self.calls.append(args)
        return __import__("json").dumps([self.reviews]) if args[:1] == ("api",) and args[1].endswith("/reviews") and len(args) > 2 and args[2] == "--paginate" else "{}"


def test_approve_once_per_commit(monkeypatch):
    a = pw.decide("success", 90, [], [])
    fake = FakeGh([])
    monkeypatch.setattr(pw, "gh", fake)
    assert pw.approve("o/r", 7, "abc123", a) == "approved"
    assert any("event=APPROVE" in c for c in fake.calls[-1])
    fake = FakeGh([{"id": 1, "user": {"login": pw.BOT}, "state": "APPROVED", "commit_id": "abc123"}])
    monkeypatch.setattr(pw, "gh", fake)
    assert pw.approve("o/r", 7, "abc123", a) == "already approved" and len(fake.calls) == 1


def test_hold_withdraws_earlier_bot_approvals_but_not_peoples(monkeypatch):
    fake = FakeGh([{"id": 1, "user": {"login": pw.BOT}, "state": "APPROVED", "commit_id": "old"},
                   {"id": 2, "user": {"login": "TEJ42000"}, "state": "APPROVED", "commit_id": "old"}])
    monkeypatch.setattr(pw, "gh", fake)
    out = pw.approve("o/r", 7, "new", pw.decide("failure", 90, [], []))
    assert out == "not approved, 1 earlier approval(s) withdrawn"
    assert [c for c in fake.calls if "/dismissals" in " ".join(c)][0][3].endswith("/reviews/1/dismissals")


def test_sweep_plan_skips_drafts_pending_tests_and_assessed_commits():
    prs = [{"number": 1, "isDraft": True, "headRefOid": "aaaaaaa1"}, {"number": 2, "isDraft": False, "headRefOid": "bbbbbbb2"},
           {"number": 3, "isDraft": False, "headRefOid": "ccccccc3"}, {"number": 4, "isDraft": False, "headRefOid": "ddddddd4"}]
    todo, skipped = pw.plan(prs, {1: "success", 2: "pending", 3: "success", 4: "failure"}, {3: {"ccccccc"}})
    assert todo == [(4, "failure")]
    assert skipped == {1: "draft", 2: "tests pending", 3: "latest commit already assessed"}
    assert pw.plan(prs, {3: "success"}, {3: {"ccccccc"}}, force=True)[0] == [(3, "success")]



def test_default_model_is_haiku(monkeypatch):
    import importlib
    monkeypatch.delenv("PR_CHECK_MODEL", raising=False)
    assert importlib.reload(pw).MODEL == "claude-haiku-4-5"
    monkeypatch.setenv("PR_CHECK_MODEL", "")
    assert importlib.reload(pw).MODEL == "claude-haiku-4-5"


def test_model_ids_with_a_slash_go_through_openrouter(monkeypatch):
    import types as pytypes
    seen = {}
    class FakeAnthropic:
        def __init__(self, **kw):
            seen.update(kw)
            self.messages = pytypes.SimpleNamespace(create=lambda **k: seen.setdefault("create", k) and pytypes.SimpleNamespace(
                content=[pytypes.SimpleNamespace(text='{"verdict": "approve", "security": 90, "explanation": "Docs only."}')]))
    monkeypatch.setitem(sys.modules, "anthropic", pytypes.SimpleNamespace(Anthropic=FakeAnthropic))
    monkeypatch.setattr(pw, "MODEL", "z-ai/glm-5.3-flash")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    assert pw.model_key_present()
    out = pw.model_review("Docs", "", [f("README.md")], diff_for("README.md", ["x"]), [])
    assert out["verdict"] == "approve" and seen["base_url"] == "https://openrouter.ai/api" and seen["auth_token"] == "or-test"
    assert seen["create"]["model"] == "z-ai/glm-5.3-flash"
    monkeypatch.setattr(pw, "MODEL", "claude-haiku-4-5")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert not pw.model_key_present()


def test_risky_lines_in_docs_and_tests_do_not_count():
    assert pw.rules([f("README.md")], diff_for("README.md", ["AUTH=off signs you in as the first address"]))[0] == 100
    assert pw.rules([f("tests/test_x.py")], diff_for("tests/test_x.py", ["subprocess.run(cmd, shell=True)"]))[0] == 100
    assert pw.rules([f("run.py")], diff_for("run.py", ["subprocess.run(cmd, shell=True)"]))[0] == 92


def test_using_the_public_helper_is_not_a_change_to_public_routes():
    use = pw.rules([f("auth.py")], diff_for("auth.py", ['        if user is None and not _public(scope["path"]):']))
    define = pw.rules([f("auth.py")], diff_for("auth.py", ["def _public(path: str) -> bool:"]))
    assert use[0] == 100 - 12 and define[0] == 100 - 12 - 8
